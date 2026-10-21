import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from oap.analytics.growth import POOLED_SUFFIX, SCORED_COLUMNS, VARIANT_COLUMNS
from oap.analytics.growth_rules import rule_grid
from scripts import growth_lab as cli
from scripts import regime_calibration as step_one
from tests.scripts.growth_gold import SESSIONS, write_growth_gold

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
HEADINGS = [
    "# Growth lab: growth-optimal single options on a hold-out",
    "## Headline (hold-out)",
    "## Top 10 rules on dev, with their hold-out results",
    "## Regime contribution",
    "## Multiple-comparisons check",
    "## Scored options",
    "## Protocol",
    "## Hold-out equity",
    "## Caveats",
]
FORBIDDEN = ("buy", "sell", "recommend", "should")


@pytest.fixture
def lab(tmp_path: Path) -> tuple[Path, Path]:
    """The tiny gold schema and a lab directory with step 1's outputs."""
    db = write_growth_gold(tmp_path / "tiny.duckdb")
    lab_dir = tmp_path / "lab"
    args = ["--db", str(db), "--lab-dir", str(lab_dir), "--out", str(tmp_path / "step1.md")]
    assert step_one.main(args) == 0
    return db, lab_dir


def _args(db: Path, lab_dir: Path, out: Path, *extra: str) -> list[str]:
    return [
        "--db",
        str(db),
        "--lab-dir",
        str(lab_dir),
        "--out",
        str(out),
        "--holdout-year",
        "2022",
        "--min-dev-trades",
        "1",
        *extra,
    ]


def test_score_then_sweep_writes_the_cache_and_the_report(
    lab: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db, lab_dir = lab
    out = tmp_path / "docs" / "growth-lab.md"
    assert cli.main(["--score", "--sweep", *_args(db, lab_dir, out, "--grid-limit", "36")]) == 0
    parts = sorted(p.name for p in (lab_dir / cli.SCORED_DIR).glob("*.parquet"))
    assert parts == ["2021.parquet", "2022.parquet"]
    options = pd.read_parquet(lab_dir / cli.SCORED_DIR)
    assert list(options.columns) == list(SCORED_COLUMNS)
    assert sorted(pd.to_datetime(options["trade_date"]).dt.date.unique()) == SESSIONS
    assert set(options["map_id"]) == {"fold_2021", "fold_2022"}
    assert options["is_out_of_sample"].all()
    assert (options["growth_rate"] > 0).any()
    meta = json.loads((lab_dir / cli.META_FILE).read_text())
    assert meta["chosen"] == "pooled" and meta["sessions"] == 4 and meta["rows"] == len(options)
    text = out.read_text()
    assert [line for line in text.splitlines() if line.startswith("#")] == HEADINGS
    assert "dev is 2021, the hold-out is 2022" in text
    assert "36 rules were searched" in text
    assert "Step 1 chose the pooled map" in text
    assert "**Best growth: `" in text
    assert "| Baseline, calls only | random calls, equal weight, top " in text
    assert "By right the averages differ: calls returned" in text
    assert not any(word in text.lower() for word in FORBIDDEN)
    assert text.endswith("\n")
    assert (out.parent / cli.HOLDOUT_IMAGE).read_bytes()[:8] == PNG_MAGIC
    results = pd.read_csv(lab_dir / cli.SWEEP_FILE)
    assert results["rule_id"].tolist() == [r.rule_id for r in rule_grid()[:36]]
    assert {"growth_per_session_dev", "mean_return_ci_low_holdout"} <= set(results)
    err = capsys.readouterr().err
    assert "scoring 4 sessions" in err and "36/36 rules" in err


def test_a_regime_decision_scores_the_pooled_map_alongside(
    lab: tuple[Path, Path], tmp_path: Path
) -> None:
    db, lab_dir = lab
    decision_path = lab_dir / step_one.DECISION_FILE
    decision = json.loads(decision_path.read_text())
    decision_path.write_text(json.dumps({**decision, "chosen": "regime", "use_regime": True}))
    out = tmp_path / "growth-lab.md"
    assert cli.main(["--score", "--sweep", *_args(db, lab_dir, out, "--grid-limit", "18")]) == 0
    options = pd.read_parquet(lab_dir / cli.SCORED_DIR)
    assert {f"{c}{POOLED_SUFFIX}" for c in VARIANT_COLUMNS} <= set(options.columns)
    assert set(options["map_id"]) == {"fold_2021_unknown", "fold_2022_unknown"}
    text = out.read_text()
    section = text.split("## Regime contribution")[1].split("##")[0]
    assert "(pooled map)" in section
    assert "regime maps" in section


def test_sweep_without_qualifying_rules_says_so(lab: tuple[Path, Path], tmp_path: Path) -> None:
    db, lab_dir = lab
    out = tmp_path / "growth-lab.md"
    assert cli.main(["--score", *_args(db, lab_dir, out)]) == 0
    args = _args(db, lab_dir, out, "--grid-limit", "4")
    args[args.index("--min-dev-trades") + 1] = "100000"
    assert cli.main(["--sweep", *args]) == 0
    text = out.read_text()
    assert "nothing is picked" in text
    assert "there is no median dev rule" in text


def test_a_map_trained_on_its_own_outcomes_fails_the_check(
    lab: tuple[Path, Path], tmp_path: Path
) -> None:
    db, lab_dir = lab
    maps_path = lab_dir / step_one.MAPS_FILE
    maps = pd.read_parquet(maps_path)
    maps["train_max_expiration"] = pd.Timestamp("2030-01-01")
    maps.to_parquet(maps_path, index=False)
    assert cli.main(["--score", *_args(db, lab_dir, tmp_path / "g.md")]) == 3
    assert not (lab_dir / cli.META_FILE).exists()


def test_exit_codes(tmp_path: Path, lab: tuple[Path, Path]) -> None:
    db, lab_dir = lab
    missing = tmp_path / "nothing"
    assert cli.main(["--score", "--db", str(db), "--lab-dir", str(missing)]) == 2
    assert cli.main(["--sweep", "--lab-dir", str(lab_dir)]) == 2
    assert (
        cli.main(["--score", "--db", str(tmp_path / "none.duckdb"), "--lab-dir", str(lab_dir)]) == 2
    )
    empty = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty)).close()
    assert cli.main(["--score", "--db", str(empty), "--lab-dir", str(lab_dir)]) == 2
    with pytest.raises(SystemExit):
        cli.main([])
    with pytest.raises(SystemExit):
        cli.main(["--sweep", "--grid-limit", "0"])
