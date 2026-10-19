import dataclasses
import re
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from oap.analytics.config import DEFAULT_CONFIG
from oap.analytics.scoring import ENTRY_RULE
from scripts import make_report as report

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
HEADINGS = [
    "# Results",
    "## Data coverage",
    "## Snapshot exclusions",
    "## Calibration: risk-neutral vs calibrated",
    "## Reliability",
    "## Top 10 to enter (2024-06-14)",
    "## Top put credit spreads (2024-06-14)",
    "## Top spreads by edge (2024-06-14)",
    "## How to read this",
    "## Caveats",
]
UNDERLYINGS = ("AAPL", "SPY", "TSLA")


def _metric(
    segment_type: str,
    segment: str,
    variant: str,
    metric: str,
    value: float,
    *,
    ci: tuple[float, float] | None = None,
) -> dict[str, object]:
    return {
        "segment_type": segment_type,
        "segment": segment,
        "variant": variant,
        "metric": metric,
        "value": value,
        "ci_low": None if ci is None else ci[0],
        "ci_high": None if ci is None else ci[1],
        "n_predictions": 1200,
        "n_snapshots": 150,
        "n_clusters": 40,
    }


def _metrics_frame() -> pd.DataFrame:
    rows = []
    for segment_type, segments in (
        ("overall", ["all"]),
        ("underlying", list(UNDERLYINGS)),
        ("dte_bucket", ["<=20d", "21-35d", "36-50d"]),
        ("fold", ["2021", "2022"]),
    ):
        for segment in segments:
            for variant, scale in (("raw", 1.0), ("calibrated", 0.9)):
                rows.append(_metric(segment_type, segment, variant, "brier_score", 0.2123 * scale))
                rows.append(_metric(segment_type, segment, variant, "log_loss", 0.61 * scale))
                rows.append(
                    _metric(
                        segment_type, segment, variant, "expected_calibration_error", 0.05 * scale
                    )
                )
    rows.append(_metric("overall", "all", "delta", "brier_score", -0.0212, ci=(-0.031, -0.012)))
    return pd.DataFrame(rows)


def _bins_frame() -> pd.DataFrame:
    rows = []
    for variant, shift in (("raw", 0.04), ("calibrated", 0.0)):
        for i in range(10):
            n = 0 if i == 9 else 50 + 20 * i
            mid = (i + 0.5) / 10
            rows.append(
                {
                    "variant": variant,
                    "bin_index": i,
                    "lower": i / 10,
                    "upper": (i + 1) / 10,
                    "n": n,
                    "mean_predicted": None if n == 0 else mid,
                    "frequency_realised": None if n == 0 else min(1.0, mid + shift),
                }
            )
    return pd.DataFrame(rows)


def _scores_frame() -> pd.DataFrame:
    rows = []
    for i in range(14):
        underlying = UNDERLYINGS[i % 3]
        rank = i + 1 if i < 12 else None
        # The edge order is the reverse of the return order; eleven spreads pass the entry
        # guards and they are ordered like the return ranking.
        rank_edge = 12 - i if i < 12 else None
        rank_entry = i + 1 if i < 11 else None
        rows.append(
            {
                "spread_key": f"{underlying}|2024-06-14|2024-07-19|{100 - i:.3f}|{90 - i:.3f}",
                "underlying": underlying,
                "trade_date": date(2024, 6, 14),
                "expiration": date(2024, 7, 19),
                "dte_days": 35,
                "short_strike": 100.0 - i,
                "long_strike": 90.0 - i,
                "credit": 1.0 + 0.1 * i,
                "credit_natural": 0.9 + 0.1 * i,
                "prob_profit": 0.9 - 0.02 * i,
                "prob_profit_raw": 0.88 - 0.02 * i,
                "expected_roc": 0.02 - 0.001 * i,
                "expected_roc_raw": 0.003,
                "annualised_roc": 0.25 - 0.02 * i,
                "annualised_roc_raw": 0.03,
                "eligible": rank is not None,
                "rank": rank,
                "cash_apy": 0.036,
                "fair_credit": 0.5 + 0.05 * i,
                "edge": 0.5 - 0.02 * i,
                "edge_natural": 0.4 - 0.02 * i,
                "edge_pct": 0.2 + 0.02 * i,
                "reward_to_risk": None if i == 11 else 0.3 - 0.01 * i,
                "pop_implied": 0.8 + 0.001 * i,
                "pop_gap": 0.05 - 0.002 * i,
                "rank_edge": rank_edge,
                "rank_entry": rank_entry,
            }
        )
    return pd.DataFrame(rows).astype({"rank": "Int64", "rank_edge": "Int64", "rank_entry": "Int64"})


def _write_gold(path: Path, *, with_oos: bool = True, omit: tuple[str, ...] = ()) -> None:
    quotes = pd.DataFrame(
        [
            {"underlying": u, "trade_date": date(2024, 6, d), "occ_symbol": f"{u}{d}{k}"}
            for u in UNDERLYINGS
            for d in (13, 14)
            for k in range(3)
        ]
    )
    snapshots = pd.DataFrame(
        [
            {
                "underlying": u,
                "trade_date": date(2024, 6, 13),
                "expiration": date(2024, 7, 19),
                "settlement_date": None if status == "unsettled" else date(2024, 7, 19),
                "status": status,
            }
            for u in UNDERLYINGS
            for status in ("ok", "unsettled", "too_few_puts")
        ]
    )
    sample = pd.DataFrame(
        [
            {
                "underlying": u,
                "trade_date": date(2024, 6, 13),
                "expiration": date(2024, 7, 19),
                "moneyness": m,
                "cdf_flags": "monotonicity_repaired,right_tail_uncovered" if u == "SPY" else "",
                "predicted_raw": 0.01 if m == 0.95 else 0.5,
                "realised": u == "SPY" and m == 0.95,
                "is_out_of_sample": True,
            }
            for u in UNDERLYINGS
            for m in (0.95, 1.0)
        ]
        # Two more snapshots, so five snapshots fall on two expirations (2.5 per expiration).
        + [
            {
                "underlying": u,
                "trade_date": t,
                "expiration": e,
                "moneyness": 1.0,
                "cdf_flags": "",
                "predicted_raw": 0.5,
                "realised": False,
                "is_out_of_sample": True,
            }
            for u, t, e in (
                ("TSLA", date(2024, 6, 14), date(2024, 7, 19)),
                ("SPY", date(2024, 6, 13), date(2024, 8, 16)),
            )
        ]
    )
    maps = pd.DataFrame(
        [
            {"map_id": "fold_2024", "fold": 2024, "n_samples": 0, "is_identity": True},
            {"map_id": "fold_2024", "fold": 2024, "n_samples": 0, "is_identity": True},
            {"map_id": "production", "fold": None, "n_samples": 900, "is_identity": False},
        ]
    ).astype({"fold": "Int64"})
    outcomes = pd.DataFrame(
        {"underlying": list(UNDERLYINGS), "expiration": [date(2024, 7, 19)] * 3}
    )
    tables = {
        "fct_option_quote": quotes,
        "fct_expiration_outcome": outcomes,
        "calibration_snapshot": snapshots,
        "calibration_sample": sample,
        "calibration_metrics": _metrics_frame() if with_oos else _metrics_frame().iloc[0:0],
        "calibration_bins": _bins_frame() if with_oos else _bins_frame().iloc[0:0],
        "calibration_map": maps,
        "spread_scores": _scores_frame(),
    }
    con = duckdb.connect(str(path))
    con.execute("create schema gold")
    for name, frame in tables.items():
        if name in omit:
            continue
        con.register("frame", frame)
        con.execute(f"create table gold.{name} as select * from frame")
        con.unregister("frame")
    con.close()


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "oap.duckdb"
    _write_gold(path)
    return path


def _section(out: Path, heading: str) -> str:
    """Return the text of one section of ``results.md``, from its heading to the next one."""
    text = (out / "results.md").read_text()
    return text.split(heading)[1].split("\n## ")[0]


def _run(db: Path, out: Path, *extra: str) -> int:
    return report.main(["--db", str(db), "--out", str(out), *extra])


def test_main_writes_the_report_and_returns_zero(db: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"

    assert _run(db, out) == 0

    assert (out / "results.md").read_text().startswith("# Results\n")
    assert (out / "img" / "calibration.png").exists()
    assert (out / "img" / "spread_scores.png").exists()


def test_all_eight_headings_are_present_and_in_order(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()

    found = re.findall(r"^#{1,2} .*$", text, flags=re.MULTILINE)

    assert found == HEADINGS


def test_the_fixture_brier_values_appear_formatted(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()

    assert "| Brier score | 0.2123 | 0.1911 | -0.0212 |" in text
    assert "Brier change -0.0212 (95% cluster-bootstrap interval -0.0310 to -0.0120" in text
    assert "1,200 predictions, 150 snapshots and 40 expiration clusters" in text


def test_the_source_line_names_the_gold_schema_and_the_as_of_session(
    db: Path, tmp_path: Path
) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()

    assert "`gold` schema" in text
    assert "2024-06-14 session" in text


def test_the_top_table_has_at_most_ten_rows_in_rank_order(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)
    section = _section(tmp_path, "## Top put credit spreads")

    rows = [line for line in section.splitlines() if re.match(r"\| \d+ \|", line)]
    ranks = [int(line.split("|")[1]) for line in rows]

    assert len(rows) == 10
    assert ranks == list(range(1, 11))
    assert "| 1 | AAPL | 2024-06-14 | 2024-07-19 | 35 | 100/90 |" in section


def test_top_limits_the_table(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path, "--top", "3")
    section = _section(tmp_path, "## Top put credit spreads")

    assert len([line for line in section.splitlines() if re.match(r"\| \d+ \|", line)]) == 3


def test_both_figures_are_png_files(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)

    for name in ("calibration.png", "spread_scores.png"):
        assert (tmp_path / "img" / name).read_bytes().startswith(PNG_MAGIC)


def test_a_second_run_gives_identical_markdown_and_images(db: Path, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"

    _run(db, first)
    _run(db, second)

    for relative in ("results.md", "img/calibration.png", "img/spread_scores.png"):
        assert (first / relative).read_bytes() == (second / relative).read_bytes()


def test_a_missing_database_returns_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tmp_path / "absent.duckdb", tmp_path / "out") == 2

    assert "make dbt-build-local" in capsys.readouterr().err


def test_a_missing_table_returns_two_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "partial.duckdb"
    _write_gold(path, omit=("calibration_bins",))

    assert _run(path, tmp_path / "out") == 2

    err = capsys.readouterr().err
    assert "calibration_bins" in err
    assert "make dbt-build-local" in err
    assert not (tmp_path / "out" / "results.md").exists()


def test_the_empty_sample_message_and_placeholder_figures(tmp_path: Path) -> None:
    path = tmp_path / "empty.duckdb"
    _write_gold(path, with_oos=False)

    assert _run(path, tmp_path / "out") == 0

    text = (tmp_path / "out" / "results.md").read_text()
    first_test_year = DEFAULT_CONFIG.first_test_year
    assert (
        f"No out-of-sample predictions yet (needs settled history before {first_test_year})."
        in text
    )
    assert (tmp_path / "out" / "img" / "calibration.png").read_bytes().startswith(PNG_MAGIC)


def test_snapshot_exclusions_and_caveat_counts_come_from_the_database(
    db: Path, tmp_path: Path
) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()

    assert "| `ok` | 3 | 33.3% | enters the calibration sample |" in text
    assert "| `too_few_puts` | 3 |" in text
    assert "3 snapshots with fewer than 4 usable puts" in text
    assert "right tail uncovered 20.0%" in text


def test_the_top_table_shows_the_session_of_every_row(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)
    section = _section(tmp_path, "## Top put credit spreads")

    header = next(line for line in section.splitlines() if line.startswith("| Rank"))
    rows = [line for line in section.splitlines() if re.match(r"\| \d+ \|", line)]

    assert [cell.strip() for cell in header.strip("|").split("|")[:3]] == [
        "Rank",
        "Underlying",
        "Session",
    ]
    assert report.SPREAD_HEADERS[:3] == ("Rank", "Underlying", "Session")
    assert all(line.split("|")[3].strip() == "2024-06-14" for line in rows)


def test_the_spread_return_columns_and_prose_say_return_on_max_loss(
    db: Path, tmp_path: Path
) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()
    header = next(
        line
        for line in _section(tmp_path, "## Top put credit spreads").splitlines()
        if line.startswith("| Rank")
    )

    assert report.SPREAD_HEADERS[-2:] == (
        "Expected return on max loss",
        "Annualised return on max loss",
    )
    assert "| Expected return on max loss | Annualised return on max loss |" in header
    assert "return on max loss is the expected return over the trade" in text
    assert "expected return on max loss is roughly the cash rate" in text
    assert "collateral" not in text.replace("which is the collateral held", "")
    assert "ROC" not in text.replace("POP", "")


def test_the_exclusions_note_does_not_claim_row_level_filters_are_counted(
    db: Path, tmp_path: Path
) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()

    assert "Nothing is dropped" not in text
    assert "Snapshot exclusions are counted here." in text
    assert "logged by the loaders and are not counted in this report" in text


def test_the_caveats_use_the_computed_cluster_size_and_the_configured_split_threshold(
    db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()

    assert "on average 2.5 snapshots share an expiration" in text
    assert "about eight" not in text
    assert f"beyond {DEFAULT_CONFIG.split_abs_log_return:g} in log terms" in text

    monkeypatch.setattr(
        report, "DEFAULT_CONFIG", dataclasses.replace(DEFAULT_CONFIG, split_abs_log_return=0.55)
    )
    _run(db, tmp_path)
    assert "beyond 0.55 in log terms" in (tmp_path / "results.md").read_text()


def test_the_cluster_size_is_omitted_when_the_sample_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "nosample.duckdb"
    _write_gold(path)
    con = duckdb.connect(str(path))
    con.execute("delete from gold.calibration_sample")
    con.close()

    assert _run(path, tmp_path / "out") == 0

    text = (tmp_path / "out" / "results.md").read_text()
    assert "snapshots share an expiration" not in text
    assert "and the market moves together on an expiration date" in text


def test_coverage_totals(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()

    assert "| SPY | 2024-06-13 | 2024-06-14 | 2 | 3 | 2 | 3 |" in text
    assert "In total: 18 quotes on 18 contracts, in 9 chain snapshots" in text


README = "# Title\n\nintro\n\n<!-- results:start -->\nold\n<!-- results:end -->\n\nrest\n"


def test_the_readme_excerpt_replaces_only_the_marked_block() -> None:
    updated = report.replace_readme_excerpt(README, "| new |")

    assert updated == (
        "# Title\n\nintro\n\n<!-- results:start -->\n| new |\n<!-- results:end -->\n\nrest\n"
    )
    assert report.replace_readme_excerpt(updated, "| new |") == updated


@pytest.mark.parametrize(
    "readme",
    [
        "no markers",
        "<!-- results:start -->only start",
        "<!-- results:end --> before <!-- results:start -->",
    ],
)
def test_missing_or_misordered_markers_raise(readme: str) -> None:
    with pytest.raises(ValueError, match="results:start"):
        report.replace_readme_excerpt(readme, "x")


def test_main_updates_the_readme_excerpt(db: Path, tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(README)

    assert _run(db, tmp_path / "out", "--readme", str(readme)) == 0

    text = readme.read_text()
    body = text.split(report.README_START)[1].split(report.README_END)[0]
    assert "| Brier score | 0.2123 | 0.1911 | -0.0212 |" in body
    assert (
        len([line for line in body.splitlines() if re.match(r"\| (\d+|Brier|Log|Expected) ", line)])
        == 6
    )
    assert text.startswith("# Title") and text.endswith("rest\n")


def test_main_returns_two_when_the_readme_has_no_markers(
    db: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Title\n")

    assert _run(db, tmp_path / "out", "--readme", str(readme)) == 2

    assert readme.read_text() == "# Title\n"
    assert "results:start" in capsys.readouterr().err


def test_load_report_data_rejects_a_non_positive_top(db: Path) -> None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        with pytest.raises(ValueError, match="top"):
            report.load_report_data(con, top=0)
        data = report.load_report_data(con, top=5)
    finally:
        con.close()

    assert data.as_of == date(2024, 6, 14)
    assert len(data.scores) == 12
    assert list(data.scores["rank"]) == list(range(1, 13))


def test_render_markdown_is_pure(db: Path) -> None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        data = report.load_report_data(con, top=10)
    finally:
        con.close()

    assert report.render_markdown(data, top=10) == report.render_markdown(data, top=10)


def _table_rows(section: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in section.splitlines()
        if re.match(r"\| \d+ \|", line)
    ]


def test_the_entry_section_precedes_the_top_table_and_states_the_rule(
    db: Path, tmp_path: Path
) -> None:
    _run(db, tmp_path)
    text = (tmp_path / "results.md").read_text()
    section = _section(tmp_path, "## Top 10 to enter")

    assert text.index("## Top 10 to enter") < text.index("## Top put credit spreads")
    assert section.lstrip().split("\n")[0].startswith("(2024-06-14)")
    assert ENTRY_RULE in section
    assert section.index(ENTRY_RULE) < section.index("| Rank")
    assert "not trade advice" in section


def test_the_entry_table_has_ten_rows_in_entry_rank_order(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)
    section = _section(tmp_path, "## Top 10 to enter")
    header = next(line for line in section.splitlines() if line.startswith("| Rank"))
    rows = _table_rows(section)

    assert [cell.strip() for cell in header.strip("|").split("|")] == list(report.ENTRY_HEADERS)
    assert [int(r[0]) for r in rows] == list(range(1, 11))
    assert len(rows) == 10
    # Rank 1 is the first spread: natural credit 0.90, mid 1.00, POP 90.0%, edge 20.0%.
    assert rows[0][1:] == [
        "AAPL",
        "2024-06-14",
        "2024-07-19",
        "35",
        "100/90",
        "0.90",
        "1.00",
        "90.0%",
        "2.00%",
        "25.0%",
        "20.0%",
        "0.30",
    ]


def test_the_entry_table_skips_spreads_without_an_entry_rank(db: Path, tmp_path: Path) -> None:
    con = duckdb.connect(str(db))
    con.execute("update gold.spread_scores set rank_entry = null")
    con.execute('update gold.spread_scores set rank_entry = 1 where "rank" = 5')
    con.close()
    _run(db, tmp_path)
    rows = _table_rows(_section(tmp_path, "## Top 10 to enter"))

    assert len(rows) == 1
    assert rows[0][1:5] == ["SPY", "2024-06-14", "2024-07-19", "35"]
    assert rows[0][5] == "96/86"


def test_the_entry_table_says_so_when_nothing_passes(db: Path, tmp_path: Path) -> None:
    con = duckdb.connect(str(db))
    con.execute("update gold.spread_scores set rank_entry = null")
    con.close()
    _run(db, tmp_path)
    section = _section(tmp_path, "## Top 10 to enter")

    assert ENTRY_RULE in section
    assert "No spread passes the entry guards on the latest session." in section
    assert not _table_rows(section)


def test_the_edge_section_lists_five_spreads_in_edge_order(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)
    section = _section(tmp_path, "## Top spreads by edge")
    header = next(line for line in section.splitlines() if line.startswith("| Rank"))
    rows = _table_rows(section)

    assert [cell.strip() for cell in header.strip("|").split("|")] == list(report.EDGE_HEADERS)
    assert "Price-implied POP" in header
    assert "POP gap" in header
    assert [int(r[0]) for r in rows] == [1, 2, 3, 4, 5]
    # The edge rank runs against the return rank: edge rank 1 is the twelfth return rank.
    assert rows[0][1:] == [
        "TSLA",
        "2024-07-19",
        "89/79",
        "2.10",
        "2.00",
        "1.05",
        "+0.28",
        "42.0%",
        "68.0%",
        "66.0%",
        "81.1%",
        "+2.8 pp",
        "n/a",
    ]
    assert rows[1][1] == "SPY"


def test_the_edge_section_carries_the_caveat_and_the_tail_count(db: Path, tmp_path: Path) -> None:
    _run(db, tmp_path)
    section = _section(tmp_path, "## Top spreads by edge")

    assert (
        "Edge measures the mid credit against one pooled calibration map, so it is the historical "
        "variance risk premium applied to this chain, not a contract-specific mispricing; it is "
        "correlated across strikes, concentrated in the far tail, and partly the half-spread the "
        "natural credit gives up."
    ) in section
    assert "the same information as the edge in probability units" in section
    assert "predictions with a raw probability under 2% saw 1 breach in 3" in section
    for word in ("buy", "sell", "recommend", "overpriced"):
        assert not re.search(rf"\b{word}\b", section, flags=re.IGNORECASE)


def test_the_tail_count_is_omitted_without_out_of_sample_tail_rows(tmp_path: Path) -> None:
    path = tmp_path / "notail.duckdb"
    _write_gold(path)
    con = duckdb.connect(str(path))
    con.execute("update gold.calibration_sample set is_out_of_sample = false")
    con.close()

    assert _run(path, tmp_path / "out") == 0

    section = _section(tmp_path / "out", "## Top spreads by edge")
    assert "saw" not in section


def test_the_readme_excerpt_has_no_edge_columns(db: Path) -> None:
    con = duckdb.connect(str(db), read_only=True)
    try:
        data = report.load_report_data(con, top=10)
    finally:
        con.close()

    excerpt = report.readme_excerpt(data)
    spread_header = "| " + " | ".join(report.SPREAD_HEADERS[:-1]) + " |"

    assert spread_header in excerpt
    assert len([line for line in excerpt.splitlines() if re.match(r"\| [123] \|", line)]) == 3
    for text in ("Fair credit", "Edge", "Reward/risk", "Price-implied", "POP gap", "to enter"):
        assert text not in excerpt
