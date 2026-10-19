import dataclasses
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from oap.analytics.backtest import maps_to_frame, walk_forward_maps
from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.scoring import ENTRY_RULE, SPREAD_COLUMNS
from oap.analytics.strategy import settle_trades, strategy_metrics, strategy_names
from scripts import backtest_entry_rule as cli
from tests.analytics.frames import lognormal_quotes, outcomes_frame, synthetic_predictions

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ENTRY, BY_RETURN, BASELINE = strategy_names(10)


def _trade(strategy: str, day: str, underlying: str, short: float, n: int) -> dict[str, object]:
    row: dict[str, object] = dict.fromkeys(SPREAD_COLUMNS, 0.0)
    trade_date = pd.Timestamp(day)
    row.update(
        {
            "spread_key": f"{strategy}|{underlying}|{day}|{n}",
            "underlying": underlying,
            "trade_date": trade_date,
            "expiration": trade_date + pd.Timedelta(days=28),
            "dte_days": 28,
            "short_strike": short,
            "long_strike": short - 5.0,
            "width": 5.0,
            "credit": 1.2,
            "credit_natural": 1.0,
            "prob_profit": 0.8,
            "expected_roc": 0.04,
            "eligible": True,
            "map_id": f"fold_{trade_date.year}",
            "strategy": strategy,
            "is_out_of_sample": trade_date.year >= 2021,
        }
    )
    return row


def _summary() -> cli.BacktestSummary:
    """Twelve trades per strategy over 2020-2022 and two underlyings, settled by hand."""
    rows = []
    for strategy in (ENTRY, BY_RETURN, BASELINE):
        for i, day in enumerate(["2020-06-01", "2021-03-01", "2021-09-01", "2022-03-01"]):
            for j, (underlying, short) in enumerate(
                (("SPY", 100.0), ("AAPL", 190.0), ("SPY", 98.0))
            ):
                rows.append(_trade(strategy, day, underlying, short, 3 * i + j))
    trades = pd.DataFrame(rows)
    keys = trades[["underlying", "expiration"]].drop_duplicates()
    closes = {"SPY": 97.0, "AAPL": 200.0}
    outcomes = outcomes_frame(
        [
            (u, e.date(), e.date(), closes[u])
            for u, e in zip(keys["underlying"], keys["expiration"], strict=True)
        ]
    )
    settled, dropped = settle_trades(trades, outcomes)
    entry = settled.loc[settled["strategy"] == ENTRY].reset_index(drop=True)
    return cli.BacktestSummary(
        top_n=10,
        first_session=date(2020, 6, 1),
        last_session=date(2022, 3, 1),
        sessions=4,
        sessions_with_trades=4,
        unsettled=dropped,
        metrics=strategy_metrics(settled),
        trades=entry,
        oos_trades={name: 9 for name in strategy_names(10)},
        runtime_seconds=1.0,
    )


def test_markdown_has_the_sections_in_order_and_states_the_rule() -> None:
    text = cli.render_markdown(_summary())
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert headings == [
        "# Strategy backtest: the Top 10 rule applied historically",
        "## Out of sample, overall",
        f"## By year (`{ENTRY}`)",
        f"## By underlying (`{ENTRY}`)",
        f"## Worst 10 trades (`{ENTRY}`, out of sample)",
        "## Caveats",
    ]
    assert ENTRY_RULE in text
    assert "![Cumulative realised return](img/strategy_equity.png)" in text
    assert text.endswith("\n")


def test_the_overall_table_lists_the_three_strategies_with_intervals() -> None:
    text = cli.render_markdown(_summary())
    lines = [line for line in text.splitlines() if line.startswith("| `")]
    overall = [
        line
        for line in lines
        if line.split("|")[1].strip() in {f"`{n}`" for n in (ENTRY, BY_RETURN, BASELINE)}
    ]
    assert [line.split("|")[1].strip() for line in overall] == [
        f"`{ENTRY}`",
        f"`{BY_RETURN}`",
        f"`{BASELINE}`",
    ]
    # SPY 100/95 settles at 97 (loss), SPY 98/93 at 97 (loss), AAPL 190/185 at 200 (win).
    cells = [c.strip() for c in overall[0].split("|")[1:-1]]
    assert cells[1] == "9"
    assert cells[2] == "3"
    assert cells[3].startswith("33.3% (")
    assert cells[4] == "80.0%"
    assert cells[5] == "-46.7 pp"


def test_the_segment_tables_cover_out_of_sample_years_and_underlyings_only() -> None:
    text = cli.render_markdown(_summary())
    by_year = text.split(f"## By year (`{ENTRY}`)")[1].split("##")[0]
    assert "| 2021 |" in by_year
    assert "| 2022 |" in by_year
    assert "2020" not in by_year
    by_underlying = text.split(f"## By underlying (`{ENTRY}`)")[1].split("##")[0]
    assert "| AAPL |" in by_underlying
    assert "| SPY |" in by_underlying


def test_the_worst_trades_are_out_of_sample_and_worst_first() -> None:
    text = cli.render_markdown(_summary())
    worst = text.split("## Worst 10 trades")[1].split("##")[0]
    rows = [line for line in worst.splitlines() if line.startswith("| 20")]
    assert len(rows) == 9
    returns = [float(r.split("|")[-2].strip().rstrip("%")) for r in rows]
    assert returns == sorted(returns)
    assert not any(r.startswith("| 2020") for r in rows)


def test_the_caveats_name_the_assumptions() -> None:
    text = cli.render_markdown(_summary())
    caveats = text.split("## Caveats")[1]
    for phrase in (
        "natural credit",
        "no commissions",
        "held to expiry",
        "one dollar of maximum loss",
        f"before {DEFAULT_CONFIG.first_test_year}",
        "hindsight",
        "misses some sessions",
        "not a tradeable portfolio",
    ):
        assert phrase in caveats


def test_markdown_without_out_of_sample_trades_says_so() -> None:
    summary = _summary()
    empty = dataclasses.replace(summary, metrics=summary.metrics.iloc[0:0], oos_trades={})
    text = cli.render_markdown(empty)
    assert "No out-of-sample trades" in text
    assert "## By year" not in text


def test_the_equity_figure_is_a_png(tmp_path: Path) -> None:
    from oap.analytics.strategy import equity_curve

    summary = _summary()
    path = tmp_path / "img" / "strategy_equity.png"
    cli.plot_equity(equity_curve(summary.trades, basis="session"), path, top_n=10)
    assert path.read_bytes()[:8] == PNG_MAGIC
    cli.plot_equity(pd.DataFrame(), tmp_path / "empty.png", top_n=10)
    assert (tmp_path / "empty.png").read_bytes()[:8] == PNG_MAGIC


# --- end to end on a tiny gold schema --------------------------------------------------------


@pytest.fixture
def db(tmp_path: Path) -> Path:
    """A DuckDB file whose gold schema has the four tables, with sessions in 2020-2022."""
    sessions = [date(2020, 6, 1), date(2021, 3, 1), date(2022, 3, 1)]
    quotes = pd.concat(
        [
            lognormal_quotes(
                "SPY", day, day + timedelta(days=28), 100.0, 0.25, 0.045, np.arange(80.0, 121.0)
            )
            for day in sessions
        ],
        ignore_index=True,
    )
    snapshots = quotes[["underlying", "trade_date", "expiration"]].drop_duplicates()
    snapshots = snapshots.assign(status="ok")
    outcomes = outcomes_frame(
        [("SPY", d + timedelta(days=28), d + timedelta(days=28), 103.0) for d in sessions]
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


def test_main_runs_end_to_end(db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "docs" / "backtest-entry-rule.md"
    assert cli.main(["--db", str(db), "--out", str(out)]) == 0
    text = out.read_text()
    assert "Sessions scored: 3 (2020-06-01 to 2022-03-01)" in text
    assert "## By year (`entry_top10`)" in text
    assert (out.parent / "img" / "strategy_equity.png").read_bytes()[:8] == PNG_MAGIC
    assert "backtesting 3 sessions" in capsys.readouterr().err


def test_start_skips_earlier_sessions(db: Path, tmp_path: Path) -> None:
    out = tmp_path / "b.md"
    assert cli.main(["--db", str(db), "--out", str(out), "--start", "2021-01-01"]) == 0
    assert "Sessions scored: 2 (2021-03-01 to 2022-03-01)" in out.read_text()


def test_a_missing_database_or_table_returns_two(tmp_path: Path) -> None:
    assert cli.main(["--db", str(tmp_path / "none.duckdb"), "--out", str(tmp_path / "x.md")]) == 2
    empty = tmp_path / "empty.duckdb"
    duckdb.connect(str(empty)).close()
    assert cli.main(["--db", str(empty), "--out", str(tmp_path / "x.md")]) == 2
