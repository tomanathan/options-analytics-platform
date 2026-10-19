from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from oap.analytics.backtest import maps_to_frame, walk_forward_maps
from oap.analytics.rulelab import BASELINE_RULE, REGIME_COLUMNS, pick_rules, prepare, rule_grid
from oap.analytics.strategy import ELIGIBLE_ALL, SETTLED_COLUMNS
from scripts import rule_lab as cli
from tests.analytics.frames import lognormal_quotes, outcomes_frame, synthetic_predictions

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SESSIONS = [date(2021, 3, 1), date(2021, 9, 1), date(2022, 3, 1), date(2022, 9, 1)]

HEADINGS = [
    "# Rule lab: put credit spread selection rules on a hold-out",
    "## Headline picks (hold-out)",
    "## Top 10 rules on dev, with their hold-out results",
    "## Multiple-comparisons check",
    "## Protocol",
    "## Hold-out equity",
    "## Caveats",
]


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """A DuckDB file whose gold schema has the five tables, with sessions in 2021-2022."""
    quotes = pd.concat(
        [
            lognormal_quotes(underlying, day, day + timedelta(days=dte), close, 0.3, 0.045, strikes)
            for day in SESSIONS
            for underlying, close, strikes in (
                ("SPY", 100.0, np.arange(80.0, 121.0)),
                ("AAPL", 190.0, np.arange(160.0, 221.0, 2.0)),
            )
            for dte in (14, 28)
        ],
        ignore_index=True,
    )
    quotes["source_iv"] = 0.3
    snapshots = quotes[["underlying", "trade_date", "expiration"]].drop_duplicates()
    snapshots = snapshots.assign(status="ok")
    expiries = quotes[["underlying", "expiration"]].drop_duplicates()
    closes = {"SPY": 97.0, "AAPL": 195.0}
    outcomes = outcomes_frame(
        [
            (u, e.date(), e.date(), closes[u])
            for u, e in zip(expiries["underlying"], expiries["expiration"], strict=True)
        ]
    )
    days = pd.bdate_range("2020-12-01", "2022-10-31")
    daily = pd.concat(
        [
            pd.DataFrame(
                {
                    "underlying": u,
                    "trade_date": days,
                    "close_price": 100.0,
                    "log_return": np.r_[np.nan, np.full(len(days) - 1, step)],
                }
            )
            for u, step in (("SPY", 0.001), ("AAPL", -0.001))
        ],
        ignore_index=True,
    )
    maps = maps_to_frame(walk_forward_maps(synthetic_predictions([2020, 2021, 2022], 400)))
    path = tmp_path / "tiny.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create schema gold")
    for name, frame in (
        ("fct_option_quote", quotes),
        ("calibration_snapshot", snapshots),
        ("fct_expiration_outcome", outcomes),
        ("calibration_map", maps),
        ("fct_underlying_daily", daily),
    ):
        con.register("frame", frame)
        con.execute(f"create table gold.{name} as select * from frame")
        con.unregister("frame")
    con.execute(
        "alter table gold.fct_option_quote alter trade_date type date; "
        "alter table gold.fct_option_quote alter expiration type date"
    )
    con.close()
    return path


def _sweep_args(lab: Path, out: Path, *extra: str) -> list[str]:
    return [
        "--sweep",
        "--lab-dir",
        str(lab),
        "--out",
        str(out),
        "--holdout-year",
        "2022",
        "--min-dev-trades",
        "1",
        *extra,
    ]


def test_score_writes_both_caches(db: Path, tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    assert cli.main(["--score", "--db", str(db), "--lab-dir", str(lab)]) == 0
    trades = pd.read_parquet(lab / cli.SCORED_FILE)
    regime = pd.read_parquet(lab / cli.REGIME_FILE)
    assert list(trades.columns) == list(SETTLED_COLUMNS)
    assert set(trades["strategy"]) == {ELIGIBLE_ALL}
    assert trades["eligible"].all()
    assert sorted(pd.to_datetime(trades["trade_date"]).dt.date.unique()) == SESSIONS
    assert trades["rank_entry"].notna().sum() > 0
    assert list(regime.columns) == list(REGIME_COLUMNS)
    spy = regime.loc[
        (regime["underlying"] == "SPY") & (pd.to_datetime(regime["trade_date"]) == "2022-03-01")
    ]
    assert spy["ret_20"].iloc[0] == pytest.approx(0.02)
    assert spy["atm_iv"].iloc[0] == pytest.approx(0.3)


def test_score_then_sweep_writes_the_report(
    db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lab, out = tmp_path / "lab", tmp_path / "docs" / "rule-lab.md"
    args = ["--score", "--db", str(db), *_sweep_args(lab, out, "--grid-limit", "40")]
    assert cli.main(args) == 0
    text = out.read_text()
    assert [line for line in text.splitlines() if line.startswith("#")] == HEADINGS
    assert f"`{BASELINE_RULE.rule_id}`" in text
    assert "dev is 2021, the hold-out is 2022" in text
    assert "40 rules were searched" in text
    assert text.endswith("\n")
    assert "**Best overall: `" in text
    assert (out.parent / cli.HOLDOUT_IMAGE).read_bytes()[:8] == PNG_MAGIC
    results = pd.read_csv(lab / cli.SWEEP_FILE)
    assert len(results) == 40
    assert results["rule_id"].tolist() == [r.rule_id for r in rule_grid()[:40]]
    assert {"sharpe_per_trade_dev", "mean_realised_return_ci_low_holdout"} <= set(results)
    err = capsys.readouterr().err
    assert "scoring 4 sessions" in err
    assert "40/40 rules" in err


def test_sweep_without_qualifying_rules_says_so(db: Path, tmp_path: Path) -> None:
    lab, out = tmp_path / "lab", tmp_path / "rule-lab.md"
    assert cli.main(["--score", "--db", str(db), "--lab-dir", str(lab)]) == 0
    args = _sweep_args(lab, out, "--grid-limit", "3")
    args[args.index("--min-dev-trades") + 1] = "100000"
    assert cli.main(args) == 0
    text = out.read_text()
    assert "nothing is picked" in text
    assert "there is no median dev rule" in text


def test_the_markdown_states_both_picks_in_words(db: Path, tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    assert cli.main(["--score", "--db", str(db), "--lab-dir", str(lab)]) == 0
    trades = pd.read_parquet(lab / cli.SCORED_FILE)
    regime = pd.read_parquet(lab / cli.REGIME_FILE)
    prepared = prepare(trades, regime)
    rules = list(rule_grid()[:80])
    dev, hold = cli.split_years(trades, 2022)
    results, _ = cli.sweep(prepared, rules, dev_years=dev, holdout_years=hold)
    picks = pick_rules(results, baseline_id=BASELINE_RULE.rule_id, min_dev_trades=1)
    report = cli.LabReport(
        results=results,
        picks=picks,
        rules={r.rule_id: r for r in rules},
        grid_size=1600,
        dev_years=dev,
        holdout_years=hold,
        first_session=SESSIONS[0],
        last_session=SESSIONS[-1],
        n_scored=len(trades),
        n_guarded=len(prepared.frame),
        min_dev_trades=1,
        runtime_seconds=0.5,
    )
    text = cli.render_markdown(report)
    assert picks.best_overall is not None
    assert f"**Best overall: `{picks.best_overall}`.** Rank by" in text
    assert "hold-out interval" in text
    if picks.best_roi is not None:
        assert f"**Best ROI: `{picks.best_roi}`.** Rank by" in text
    for phrase in (
        "rules were searched",
        "inflated by selection",
        "end-of-day",
        "natural credit",
        "held to expiry",
        "hindsight",
        "about 0.67 years",
        "Only settled expiries are scored",
    ):
        assert phrase in text
    top = text.split("## Top 10 rules on dev")[1].split("##")[0]
    assert "| baseline | `rm-dany-many-all-any-e0-n10` |" in top
    curve = cli.holdout_curves(prepared, [("base", BASELINE_RULE)], hold)
    cli.plot_holdout(curve, tmp_path / "h.png", ["base"])
    assert (tmp_path / "h.png").read_bytes()[:8] == PNG_MAGIC
    cli.plot_holdout(pd.DataFrame(), tmp_path / "empty.png", ["base"])
    assert (tmp_path / "empty.png").read_bytes()[:8] == PNG_MAGIC


def test_exit_codes(db: Path, tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    assert cli.main(["--score", "--db", str(tmp_path / "none.duckdb"), "--lab-dir", str(lab)]) == 2
    empty = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty)).close()
    assert cli.main(["--score", "--db", str(empty), "--lab-dir", str(lab)]) == 2
    assert cli.main(["--sweep", "--lab-dir", str(tmp_path / "nothing")]) == 2
    with pytest.raises(SystemExit):
        cli.main([])
    with pytest.raises(SystemExit):
        cli.main(["--sweep", "--grid-limit", "0"])
