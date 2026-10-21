import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from oap.analytics.backtest import maps_from_frame
from oap.analytics.regime_calibration import (
    COMPARISON_COLUMNS,
    REGIME_MAP_COLUMNS,
    Decision,
)
from oap.analytics.rulelab import REGIME_COLUMNS
from scripts import regime_calibration as cli
from tests.scripts.growth_gold import write_growth_gold

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
HEADINGS = [
    "# Regime-conditional calibration: one map per regime against the pooled map",
    "## Out of sample, overall",
    "## By regime",
    "## By days to expiry",
    "## By year",
    "## Reliability",
    "## Protocol",
    "## Caveats",
]
FORBIDDEN = ("buy", "sell", "recommend", "should")


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """The tiny gold schema of the growth lab."""
    return write_growth_gold(tmp_path / "tiny.duckdb")


def test_step_one_writes_the_files_and_the_report(db: Path, tmp_path: Path) -> None:
    lab, out = tmp_path / "lab", tmp_path / "docs" / "regime-calibration.md"
    assert cli.main(["--db", str(db), "--lab-dir", str(lab), "--out", str(out)]) == 0
    text = out.read_text()
    assert [line for line in text.splitlines() if line.startswith("#")] == HEADINGS
    first = text.split("\n\n")[1]
    assert first.startswith("**Decision: the pooled map is used downstream.**")
    assert text.endswith("\n")
    assert not any(word in text.lower() for word in FORBIDDEN)
    assert (out.parent / cli.IMAGE).read_bytes()[:8] == PNG_MAGIC
    decision = json.loads((lab / cli.DECISION_FILE).read_text())
    assert decision["chosen"] == "pooled" and decision["use_regime"] is False
    maps = pd.read_parquet(lab / cli.MAPS_FILE)
    assert list(maps.columns) == list(REGIME_MAP_COLUMNS)
    assert {"fold_2021", "fold_2021_high_up", "fold_2022_unknown"} <= set(maps_from_frame(maps))
    comparison = pd.read_csv(lab / cli.COMPARISON_FILE)
    assert list(comparison.columns) == list(COMPARISON_COLUMNS)
    regime = pd.read_parquet(lab / cli.REGIME_FILE)
    assert list(regime.columns) == list(REGIME_COLUMNS)


def test_the_lead_states_a_regime_decision(db: Path) -> None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        result = cli.run(con)
    finally:
        con.close()
    assert result.mismatched == () and result.leaking == ()
    won = replace(result, decision=Decision(True, 0.13, 0.12, -0.01, -0.02, -0.005, 100, 10))
    text = cli.render_markdown(won)
    assert "**Decision: the regime maps are used downstream.**" in text
    assert "-0.0100 (95% interval -0.0200 to -0.0050" in text
    cli.plot_reliability(pd.DataFrame(), db.parent / "empty.png")
    assert (db.parent / "empty.png").read_bytes()[:8] == PNG_MAGIC


def test_a_stale_gold_map_fails_the_check(db: Path, tmp_path: Path) -> None:
    con = duckdb.connect(str(db))
    con.execute("update gold.calibration_map set calibrated = calibrated * 0.5")
    con.close()
    args = ["--db", str(db), "--lab-dir", str(tmp_path / "lab"), "--out", str(tmp_path / "r.md")]
    assert cli.main(args) == 3
    assert not (tmp_path / "r.md").exists()


def test_exit_codes(tmp_path: Path) -> None:
    out = ["--lab-dir", str(tmp_path / "lab"), "--out", str(tmp_path / "r.md")]
    assert cli.main(["--db", str(tmp_path / "none.duckdb"), *out]) == 2
    empty = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty)).close()
    assert cli.main(["--db", str(empty), *out]) == 2
