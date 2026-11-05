"""The whole command on a generated root, through the real reader: refusals, labels, range, registry,
identity.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from engine_helpers import (
    DAY,
    GENERATED_CONFIG,
    MINUTE,
    generated_trades,
    minute_bars,
    utc,
)
from hft_crypto.bars.core import UTC_TIME, TimingContractError
from hft_crypto.config import ConfigError, load_pipeline_config
from hft_crypto.data.atomic import atomic_write_parquet
from hft_crypto.data.catalog import Catalog
from hft_crypto.data.derive import BARS_1M, TRADES
from hft_crypto.data.zones import SYNTHETIC_MARKER, DataRoot
from hft_crypto.engine.__main__ import main
from hft_crypto.engine.accounting import to_cents
from hft_crypto.engine.config import DateRange, load_engine_config, parse_engine_config
from hft_crypto.engine.fold_plan import check_range, span_labels
from hft_crypto.engine.registry import REGISTRY_PATH, TrialRegistry
from hft_crypto.engine.run import RunOutcome, read_cut, required_allowance, run_engine
from hft_crypto.timeutil import date_of_us
from hft_crypto.versioning import stable_hash

VENUE = "synthetic"
SYMBOLS = ("SYNTHBTC", "SYNTHETH")
FIRST = dt.date(2000, 1, 3)
DAYS = 70
FILES = ("run", "strategy_asset", "strategy", "portfolio", "trades", "equity", "events", "trials")


def default_only_config(base: Path) -> Path:
    """The shipped file, with only the default lines, so each test here stays quick."""
    text = GENERATED_CONFIG.read_text(encoding="utf-8").replace('lines = "all"', 'lines = "default_only"')
    path = base / "default_only.toml"
    path.write_text(text, encoding="utf-8")
    return path


def write_generated_root(path: Path, *, first: dt.date = FIRST, days: int = DAYS, seed: int = 41) -> DataRoot:
    """A root holding generated bars and trades, written where the reader looks for them."""
    root = DataRoot(path)
    root.guard.check(SYNTHETIC_MARKER).write_text("Generated test data. Not market data.\n", encoding="utf-8")
    catalog = Catalog(root.catalog_path)
    catalog.set_meta("data_kind", "SYNTHETIC")
    catalog.close()
    start = utc(first.year, first.month, first.day)
    for index, symbol in enumerate(SYMBOLS):
        trades = generated_trades(
            seed=seed + index, start_us=start, days=days, start_price=1000.0 if index == 0 else 100.0
        )
        bars = minute_bars(
            trades, first_close_us=start + MINUTE, last_close_us=start + days * DAY
        ).with_columns(pl.lit(VENUE).alias("venue"), pl.lit(symbol).alias("symbol"))
        for offset in range(days):
            day = first + dt.timedelta(days=offset)
            low = pl.lit(start + offset * DAY, dtype=pl.Int64).cast(UTC_TIME)
            high = pl.lit(start + (offset + 1) * DAY, dtype=pl.Int64).cast(UTC_TIME)
            atomic_write_parquet(
                root.curated_part(BARS_1M, VENUE, symbol, day),
                bars.filter((pl.col("open_time") >= low) & (pl.col("open_time") < high)),
                guard=root.guard,
            )
            atomic_write_parquet(
                root.curated_part(TRADES, VENUE, symbol, day),
                trades.filter((pl.col("ts") >= low) & (pl.col("ts") < high)),
                guard=root.guard,
            )
    return root


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    base = tmp_path_factory.mktemp("engine")
    root_path = base / "root"
    write_generated_root(root_path)
    value = DateRange(FIRST, FIRST + dt.timedelta(days=DAYS - 1))
    config = default_only_config(base)
    outcome = run_engine(data_root=str(root_path), config_path=config, date_range=value, out_dir=base / "one")
    yield {
        "base": base,
        "root": root_path,
        "range": value,
        "outcome": outcome,
        "out": base / "one",
        "config": config,
    }


def _load(out: Path, name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((out / f"{name}.json").read_text(encoding="utf-8"))
    return loaded


def test_a_root_with_no_approved_source_is_refused(tmp_path: Path) -> None:
    DataRoot(tmp_path / "plain")
    with pytest.raises(ConfigError, match="no approved source"):
        run_engine(
            data_root=str(tmp_path / "plain"),
            config_path=_market_config(tmp_path),
            date_range=DateRange(FIRST, FIRST),
            out_dir=tmp_path / "out",
        )


def test_a_generated_configuration_is_refused_on_a_root_that_is_not_generated(tmp_path: Path) -> None:
    DataRoot(tmp_path / "plain")
    with pytest.raises(ConfigError, match="generated runs"):
        run_engine(
            data_root=str(tmp_path / "plain"),
            config_path=GENERATED_CONFIG,
            date_range=DateRange(FIRST, FIRST),
            out_dir=tmp_path / "out",
        )


def test_a_market_configuration_is_refused_on_a_generated_root(tmp_path: Path) -> None:
    write_generated_root(tmp_path / "r", days=2)
    with pytest.raises(ConfigError, match="market data"):
        run_engine(
            data_root=str(tmp_path / "r"),
            config_path=_market_config(tmp_path),
            date_range=DateRange(FIRST, FIRST),
            out_dir=tmp_path / "out",
        )


def test_a_root_that_lost_its_marker_is_refused(tmp_path: Path) -> None:
    root = write_generated_root(tmp_path / "r", days=2)
    root.guard.check(SYNTHETIC_MARKER).unlink()
    with pytest.raises(ConfigError, match="marker is missing"):
        run_engine(
            data_root=str(tmp_path / "r"),
            config_path=GENERATED_CONFIG,
            date_range=DateRange(FIRST, FIRST),
            out_dir=tmp_path / "out",
        )


def _market_config(base: Path) -> Path:
    """The generated file with its kind changed, so these tests rest on nothing shipped for market runs."""
    text = (
        GENERATED_CONFIG.read_text(encoding="utf-8")
        .replace('data_kind = "SYNTHETIC"', 'data_kind = "MARKET"')
        .replace('opened_blocks = ["generated"]', 'opened_blocks = ["first_training_span"]')
    )
    path = base / "market.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize("flag", ["--start", "--end", "--config"])
def test_the_command_requires_its_range_and_configuration(
    flag: str, capsys: pytest.CaptureFixture[str]
) -> None:
    arguments = {"--config": str(GENERATED_CONFIG), "--start": "2000-01-03", "--end": "2000-01-04"}
    del arguments[flag]
    with pytest.raises(SystemExit) as caught:
        main([item for pair in arguments.items() for item in pair])
    assert caught.value.code == 2
    assert flag in capsys.readouterr().err


def test_a_range_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ConfigError, match="ends before"):
        DateRange(FIRST + dt.timedelta(days=1), FIRST)


def test_nothing_outside_the_range_is_opened(tmp_path: Path) -> None:
    """A later file is ruined, so a run that opened it would fail, and an earlier one the same way."""
    root = write_generated_root(tmp_path / "r", days=6)
    value = DateRange(FIRST + dt.timedelta(days=1), FIRST + dt.timedelta(days=3))
    config = default_only_config(tmp_path)
    clean = run_engine(
        data_root=str(tmp_path / "r"), config_path=config, date_range=value, out_dir=tmp_path / "a"
    )
    for offset in (0, 4, 5):
        day = FIRST + dt.timedelta(days=offset)
        for symbol in SYMBOLS:
            root.curated_part(BARS_1M, VENUE, symbol, day).write_bytes(b"this is not a parquet file")
            root.curated_part(TRADES, VENUE, symbol, day).write_bytes(b"this is not a parquet file")
    ruined = run_engine(
        data_root=str(tmp_path / "r"), config_path=config, date_range=value, out_dir=tmp_path / "b"
    )
    assert clean.header["data_manifest_hash"] == ruined.header["data_manifest_hash"]
    for name in FILES:
        assert (tmp_path / "a" / f"{name}.json").read_bytes() == (
            tmp_path / "b" / f"{name}.json"
        ).read_bytes()
    with pytest.raises(pl.exceptions.ComputeError):
        run_engine(
            data_root=str(tmp_path / "r"),
            config_path=config,
            date_range=DateRange(FIRST, FIRST + dt.timedelta(days=3)),
            out_dir=tmp_path / "c",
        )


def test_the_run_ends_a_minute_before_the_range_does(generated: dict[str, Any]) -> None:
    outcome: RunOutcome = generated["outcome"]
    last = generated["range"].end_us
    manifest = _load(generated["out"], "run")["manifest"]
    for symbol in SYMBOLS:
        assert manifest["symbols"][symbol]["last_close"] == last - MINUTE
    assert outcome.header["date_range"] == {"start": "2000-01-03", "end": "2000-03-12"}
    assert date_of_us(last - 1) == dt.date(2000, 3, 12)


@pytest.mark.parametrize("name", FILES)
def test_every_file_prints_labels_range_risk_costs_funding_and_credit(
    generated: dict[str, Any], name: str
) -> None:
    header = _load(generated["out"], name)["header"]
    assert header["labels"] == ["SIMULATED", "SYNTHETIC"]
    assert header["date_range"] == {"start": "2000-01-03", "end": "2000-03-12"}
    assert header["risk"]["state"] == "placeholder"
    assert header["risk"]["risk_per_trade_pct"]["S01"]["SYNTHBTC"] == 0.25
    assert header["risk"]["leverage_cap_per_position"] == 2.0
    assert header["risk"]["gross_exposure_cap_portfolio"] == 3.0
    assert header["costs"]["rt_bps"] == 12.0
    assert header["costs"]["stop_slip_bps"] == 5.0
    assert header["costs"]["stop_slip_state"] == "placeholder"
    assert "UNVERIFIED" in header["bar_allowance_note"]
    assert "not a selection" in header["line_note"].lower() or "not a selection" in header["line_note"]
    assert header["funding"]["status"] == "absent"
    assert "absent" in header["funding"]["note"]
    assert "Binance Vision" in header["data_credit"]
    assert "CC BY-NC-SA 4.0" in header["data_credit"]
    assert "Not associated with or endorsed by Binance" in header["data_credit"]
    assert "generated data" in header["data_credit"]
    assert header["mode"] == "IDEAL-1M"
    assert header["config_hash"]
    assert header["code_version"]
    assert header["data_manifest_hash"]


@pytest.mark.parametrize("name", [item for item in FILES if item != "run"])
def test_every_row_is_labelled_simulated_and_synthetic(generated: dict[str, Any], name: str) -> None:
    for row in _load(generated["out"], name)["rows"]:
        assert row["label"].startswith("SIMULATED SYNTHETIC")


@pytest.mark.parametrize("name", ["strategy_asset", "strategy", "trades", "events"])
def test_s01_and_s06_say_they_are_not_live_comparable_on_every_row(
    generated: dict[str, Any], name: str
) -> None:
    rows = _load(generated["out"], name)["rows"]
    for row in rows:
        marked = "NOT LIVE-COMPARABLE" in row["label"]
        assert marked is (row["strategy"] in ("S01", "S06")), row["strategy"]


def test_nothing_in_the_output_names_a_local_path(generated: dict[str, Any]) -> None:
    for name in FILES:
        text = (generated["out"] / f"{name}.json").read_text(encoding="utf-8")
        assert str(generated["base"]) not in text
        assert str(generated["base"]).replace("\\", "\\\\") not in text


def test_the_same_inputs_give_byte_identical_output(generated: dict[str, Any], tmp_path: Path) -> None:
    run_engine(
        data_root=str(generated["root"]),
        config_path=generated["config"],
        date_range=generated["range"],
        out_dir=tmp_path / "again",
    )
    for name in FILES:
        first = (generated["out"] / f"{name}.json").read_bytes()
        assert first == (tmp_path / "again" / f"{name}.json").read_bytes(), name


def test_every_stream_of_every_run_is_registered_before_and_after(generated: dict[str, Any]) -> None:
    root = DataRoot(generated["root"], create=False)
    lines = root.guard.check(REGISTRY_PATH).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    outcome: RunOutcome = generated["outcome"]
    started = [row for row in rows if row["event"] == "trial_started"]
    finished = [row for row in rows if row["event"] == "trial_finished"]
    assert len(started) >= len(outcome.streams)
    assert len(started) == len(finished)
    assert all(row["mode"] == "IDEAL-1M" and row["variant"] == "V0" for row in rows)
    assert all(row["costs"]["rt_bps"] == 12.0 and row["costs"]["stop_slip_bps"] == 5.0 for row in rows)
    assert all(row["date_range"] == {"start": "2000-01-03", "end": "2000-03-12"} for row in rows)
    assert {row["strategy"] for row in started} >= {stream.strategy for stream in outcome.streams}
    # C12: a generated run is logged, and it does not count as a trial.
    assert all(row["counts_as_trial"] is False for row in rows)
    # The start of each one comes before its end.
    assert lines.index(json.dumps(started[0], sort_keys=True, ensure_ascii=False)) == 0


def test_a_repeat_of_the_same_run_is_a_repeat_in_the_registry(tmp_path: Path) -> None:
    root_path = tmp_path / "r"
    root = write_generated_root(root_path, days=3)
    value = DateRange(FIRST, FIRST + dt.timedelta(days=1))
    config = default_only_config(tmp_path)
    for name in ("a", "b"):
        run_engine(data_root=str(root_path), config_path=config, date_range=value, out_dir=tmp_path / name)
    rows = [
        json.loads(line) for line in root.guard.check(REGISTRY_PATH).read_text(encoding="utf-8").splitlines()
    ]
    keys = [row["trial_key"] for row in rows if row["event"] == "trial_started"]
    assert len(keys) == 2 * len(set(keys))


def test_every_trade_and_every_equity_mark_reconcile_to_the_cent(generated: dict[str, Any]) -> None:
    out = generated["out"]
    capital = to_cents(_load(out, "run")["header"]["risk"]["capital"])
    trades = _load(out, "trades")["rows"]
    last = _load(out, "equity")["rows"][-1]["equity"]
    per_stream: dict[str, int] = {}
    for trade in trades:
        key = f"{trade['strategy']}:{trade['asset']}"
        per_stream[key] = per_stream.get(key, 0) + to_cents(trade["net_pnl"])
    for row in _load(out, "strategy_asset")["rows"]:
        key = f"{row['strategy']}:{row['asset']}"
        assert to_cents(row["net_pnl"]) == per_stream.get(key, 0), key
        assert to_cents(row["equity_final"]) == capital + per_stream.get(key, 0), key
        assert to_cents(last[key]) == capital + per_stream.get(key, 0), key
    capped = sum(to_cents(trade["portfolio_net_pnl"] or 0.0) for trade in trades if trade["in_portfolio"])
    assert to_cents(last["portfolio"]) == capital + capped
    portfolio, uncapped = _load(out, "portfolio")["rows"]
    assert to_cents(portfolio["net_pnl"]) == capped
    summed = sum(per_stream.values())
    assert to_cents(uncapped["net_pnl"]) == summed
    assert to_cents(last["portfolio:uncapped"]) == capital + summed


def test_gross_and_net_are_separate_in_money_and_in_r_on_every_row(generated: dict[str, Any]) -> None:
    out = generated["out"]
    for name in ("strategy_asset", "strategy", "portfolio"):
        for row in _load(out, name)["rows"]:
            for section in (row, row["long"], row["short"]):
                for key in ("gross_pnl", "net_pnl", "gross_r_total", "net_r_total"):
                    assert key in section
                identity = (
                    to_cents(section["gross_pnl"])
                    - to_cents(section["slippage"])
                    - to_cents(section["fees"])
                    - to_cents(section["funding"])
                )
                assert identity == to_cents(section["net_pnl"])
    for trade in _load(out, "trades")["rows"]:
        identity = (
            to_cents(trade["gross_pnl"])
            - to_cents(trade["costs"]["slippage"])
            - to_cents(trade["costs"]["fees"])
            - to_cents(trade["costs"]["funding"])
        )
        assert identity == to_cents(trade["net_pnl"])
        assert "gross_r" in trade and "net_r" in trade


def test_long_and_short_add_up_to_the_row(generated: dict[str, Any]) -> None:
    for row in _load(generated["out"], "strategy_asset")["rows"]:
        assert to_cents(row["long"]["net_pnl"]) + to_cents(row["short"]["net_pnl"]) == to_cents(
            row["net_pnl"]
        )
        assert row["long"]["trades"] + row["short"]["trades"] == row["trades"]


def test_the_overlap_between_assets_is_reported(generated: dict[str, Any]) -> None:
    overlap = _load(generated["out"], "portfolio")["rows"][0]["overlap_between_assets"]
    assert overlap["assets"] == list(SYMBOLS)
    assert 0 <= overlap["same_direction_marks"] <= overlap["open_together_marks"] <= overlap["marks"]
    assert overlap["gross_exposure_max"] >= overlap["gross_exposure_mean"] >= 0.0


def test_what_is_not_built_is_stated(generated: dict[str, Any]) -> None:
    run = _load(generated["out"], "run")
    assert {"V0S", "counterfactuals", "netted_portfolio", "deflated_sharpe", "selection"} <= set(
        run["not_built"]
    )
    assert "not available" in run["header"]["modes"]["IDEAL"]
    assert "C-10" in run["header"]["modes"]["CYCLE"]


# ---- the configuration: nothing has a default
# ------------------------------------------------------------------


def _raw_config() -> dict[str, Any]:
    import tomllib

    with GENERATED_CONFIG.open("rb") as handle:
        return tomllib.load(handle)


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ("costs", "rt_bps"),
        ("costs", "stop_slip_bps"),
        ("costs", "stop_slip_state"),
        ("timing", "latency_ms"),
        ("costs", "slip_bps"),
        ("risk", "capital"),
        ("risk", "leverage_cap"),
        ("risk", "gross_cap"),
        ("risk", "per_trade_pct"),
        ("risk", "state"),
        ("run", "credit_line"),
        ("run", "funding"),
        ("run", "tier"),
    ],
)
def test_every_required_value_has_no_default(table: str, key: str) -> None:
    raw = _raw_config()
    del raw[table][key]
    with pytest.raises(ConfigError, match=key):
        parse_engine_config(raw)


def test_risk_per_trade_must_be_stated_for_every_strategy_and_asset() -> None:
    raw = _raw_config()
    del raw["risk"]["per_trade_pct"]["S04"]["SYNTHETH"]
    with pytest.raises(ConfigError, match="SYNTHETH"):
        parse_engine_config(raw)


def test_a_misspelt_key_is_an_error() -> None:
    raw = _raw_config()
    raw["costs"]["rt_bpz"] = 12.0
    with pytest.raises(ConfigError, match="rt_bpz"):
        parse_engine_config(raw)


def test_the_shipped_generated_configuration_is_marked_a_placeholder() -> None:
    config = load_engine_config(GENERATED_CONFIG)
    assert config.data_kind == "SYNTHETIC"
    assert config.costs.rt_bps == 12.0
    assert config.costs.stop_slip_bps == 5.0
    assert config.costs.stop_slip_state == "placeholder"
    assert config.costs.fee_taker == pytest.approx(0.0005)
    assert config.risk.state == "placeholder"
    assert config.risk.leverage_cap == 2.0
    assert config.risk.gross_cap == 3.0
    assert config.risk.risk_budget("S01", "SYNTHBTC") == pytest.approx(250.0)


def test_the_config_hash_follows_the_values() -> None:
    raw = _raw_config()
    one = parse_engine_config(raw).config_hash
    raw["costs"]["rt_bps"] = 13.0
    assert parse_engine_config(raw).config_hash != one
    assert one == stable_hash(_raw_config())


def test_a_read_past_the_range_is_an_error_and_not_a_quiet_drop() -> None:
    from hft_crypto.engine.run import _inside_range

    start = utc(2000, 1, 3)
    frame = pl.DataFrame({"open_time": pl.Series([start + 2 * DAY], dtype=pl.Int64).cast(UTC_TIME)})
    with pytest.raises(TimingContractError, match="outside"):
        _inside_range(frame, DateRange(dt.date(2000, 1, 3), dt.date(2000, 1, 3)), "open_time", "a row")


# ---- the fold plan: a range outside what is open is refused
# --------------------------------------------------------


def test_a_generated_range_inside_the_generated_block_passes() -> None:
    blocks = check_range(DateRange(FIRST, FIRST), ("generated",), "SYNTHETIC")
    assert [block.name for block in blocks] == ["generated"]


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (dt.date(2023, 12, 31), dt.date(2024, 1, 1)),
        (dt.date(2024, 1, 1), dt.date(2024, 3, 31)),
        (dt.date(2019, 12, 31), dt.date(2020, 1, 1)),
        (dt.date(2026, 1, 1), dt.date(2026, 1, 2)),
    ],
)
def test_a_market_range_outside_the_first_span_is_refused(start: dt.date, end: dt.date) -> None:
    with pytest.raises(ConfigError, match="outside the opened dates"):
        check_range(DateRange(start, end), ("first_training_span",), "MARKET")


def test_the_first_span_passes_and_carries_its_label() -> None:
    blocks = check_range(
        DateRange(dt.date(2020, 1, 1), dt.date(2023, 12, 31)), ("first_training_span",), "MARKET"
    )
    assert span_labels(blocks) == ("FIRST TRAINING SPAN, IN-SAMPLE",)


@pytest.mark.parametrize(
    "names",
    [
        (),
        ("2024-Q1",),
        ("first_training_span", "2024-Q2"),
        ("first_training_span", "locked_block"),
        ("first_training_span", "2026-Q4"),
        ("generated",),
    ],
)
def test_blocks_open_only_in_the_plans_order(names: tuple[str, ...]) -> None:
    with pytest.raises(ConfigError):
        check_range(DateRange(dt.date(2020, 1, 1), dt.date(2020, 1, 2)), names, "MARKET")


def test_a_generated_run_may_not_name_a_block_of_the_plan() -> None:
    with pytest.raises(ConfigError, match="generated block"):
        check_range(DateRange(FIRST, FIRST), ("first_training_span",), "SYNTHETIC")


def test_a_named_block_opens_only_its_own_dates() -> None:
    names = ("first_training_span", "2024-Q1")
    assert check_range(DateRange(dt.date(2024, 1, 1), dt.date(2024, 3, 31)), names, "MARKET")
    with pytest.raises(ConfigError, match="outside"):
        check_range(DateRange(dt.date(2024, 4, 1), dt.date(2024, 4, 2)), names, "MARKET")


def test_the_command_refuses_a_generated_range_outside_the_generated_block(tmp_path: Path) -> None:
    write_generated_root(tmp_path / "r", days=2)
    with pytest.raises(ConfigError, match="outside the opened dates"):
        run_engine(
            data_root=str(tmp_path / "r"),
            config_path=default_only_config(tmp_path),
            date_range=DateRange(dt.date(2020, 1, 1), dt.date(2020, 1, 2)),
            out_dir=tmp_path / "out",
        )


# ---- C12: declared costs
# ---------------------------------------------------------------------------------------


VALUES = {"rt_bps": 12.0, "slip_bps": 1.0, "stop_slip_bps": 5.0, "target_fee_bps": 5.0}


def test_a_market_run_refuses_without_declared_costs_or_with_different_ones(tmp_path: Path) -> None:
    registry = TrialRegistry(DataRoot(tmp_path / "r"))
    with pytest.raises(ConfigError, match="no declared costs"):
        registry.require_declared(VALUES)
    registry.declare(VALUES, basis="C16", logged_at="2000-01-01T00:00:00Z")
    registry.require_declared(VALUES)
    with pytest.raises(ConfigError, match="differ"):
        registry.require_declared({**VALUES, "stop_slip_bps": 10.0})


def test_declaring_again_adds_nothing_and_a_change_is_refused(tmp_path: Path) -> None:
    root = DataRoot(tmp_path / "r")
    registry = TrialRegistry(root)
    registry.declare(VALUES, basis="C16", logged_at="2000-01-01T00:00:00Z")
    registry.declare(VALUES, basis="C16", logged_at="2000-01-02T00:00:00Z")
    lines = root.guard.check(REGISTRY_PATH).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    with pytest.raises(ConfigError, match="counted trial"):
        registry.declare({**VALUES, "rt_bps": 13.0}, basis="C16", logged_at="2000-01-03T00:00:00Z")


def test_generated_runs_add_no_trials_to_the_count(generated: dict[str, Any]) -> None:
    assert TrialRegistry(DataRoot(generated["root"], create=False)).distinct_trials() == 0
    assert _load(generated["out"], "run")["header"]["registry_distinct_trials"] == 0


# ---- grid lines: all run, the default is marked, none is ranked
# -----------------------------------------------------


def test_every_grid_line_runs_is_logged_and_the_default_is_marked(tmp_path: Path) -> None:
    root_path = tmp_path / "r"
    root = write_generated_root(root_path, days=4)
    outcome = run_engine(
        data_root=str(root_path),
        config_path=GENERATED_CONFIG,
        date_range=DateRange(FIRST, FIRST + dt.timedelta(days=3)),
        out_dir=tmp_path / "out",
    )
    # 60 lines on two symbols. The fold plan's 52, S07's 4 and S08's 4. The index counts S08 as 8, for its two
    # branches, which come from one run and are split in its rows.
    assert len(outcome.streams) == 120
    rows = _load(tmp_path / "out", "strategy_asset")["rows"]
    assert len(rows) == 120
    for strategy in ("S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10"):
        mine = [row for row in rows if row["strategy"] == strategy]
        # The default comes first on each symbol, and exactly one line is the default.
        assert mine[0]["is_default"] is True and mine[1]["is_default"] is True
        assert sum(1 for row in mine if row["is_default"]) == 2
    lines = root.guard.check(REGISTRY_PATH).read_text(encoding="utf-8").splitlines()
    started = [json.loads(line) for line in lines if '"trial_started"' in line]
    assert len(started) == 120
    assert len({row["trial_key"] for row in started}) == 120


def test_read_days_must_be_stated() -> None:
    raw = _raw_config()
    del raw["run"]["read_days"]
    with pytest.raises(ConfigError, match="read_days"):
        parse_engine_config(raw)


def test_the_rows_are_in_grid_order_and_never_sorted_by_a_result() -> None:
    config = load_engine_config(GENERATED_CONFIG)
    grid = config.strategies["S03"]
    lines = grid.lines()
    assert lines[0].is_default
    assert lines[0].params == {"timeframe_minutes": 60, "swing": [5, 3], "max_bos": 2}
    assert len(lines) == 8
    source = (Path(__file__).resolve().parents[2] / "src/hft_crypto/reports/portfolio.py").read_text(
        encoding="utf-8"
    )
    assert "sorted(streams" not in source
    assert "sort(key" not in source


def test_a_default_line_off_its_grid_is_refused() -> None:
    raw = _raw_config()
    raw["strategies"]["S04"]["default_line"]["q_min"] = 50.0
    raw["strategies"]["S04"]["portfolio_line"]["q_min"] = 50.0
    with pytest.raises(ConfigError, match="not on its grid"):
        parse_engine_config(raw)


def test_the_portfolio_line_is_an_input_on_the_grid() -> None:
    raw = _raw_config()
    raw["strategies"]["S04"]["portfolio_line"]["q_min"] = 50.0
    with pytest.raises(ConfigError, match="portfolio_line"):
        parse_engine_config(raw)
    raw = _raw_config()
    del raw["strategies"]["S04"]["portfolio_line"]
    with pytest.raises(ConfigError, match="portfolio_line"):
        parse_engine_config(raw)


def test_the_portfolio_uses_the_line_the_configuration_names_and_no_other(tmp_path: Path) -> None:
    root_path = tmp_path / "r"
    write_generated_root(root_path, days=3)
    text = (
        GENERATED_CONFIG.read_text(encoding="utf-8")
        .replace('lines = "all"', 'lines = "default_only"')
        .replace(
            "portfolio_line = { timeframe_minutes = 60, q_min = 60.0, touch_limit = 0 }",
            "portfolio_line = { timeframe_minutes = 240, q_min = 45.0, touch_limit = 1 }",
        )
    )
    config = tmp_path / "other_line.toml"
    config.write_text(text, encoding="utf-8")
    outcome = run_engine(
        data_root=str(root_path),
        config_path=config,
        date_range=DateRange(FIRST, FIRST + dt.timedelta(days=2)),
        out_dir=tmp_path / "out",
    )
    mine = [stream for stream in outcome.streams if stream.strategy == "S04"]
    assert sorted(stream.is_default for stream in mine) == [False, False, True, True]
    chosen = [stream for stream in mine if stream.in_portfolio]
    assert len(chosen) == 2
    assert all(stream.params["q_min"] == 45.0 and stream.timeframe_minutes == 240 for stream in chosen)
    row = _load(tmp_path / "out", "portfolio")["rows"][0]
    assert "S04: q_min=45.0,timeframe_minutes=240,touch_limit=1" in row["lines_used"]


def test_an_undeclared_candle_allowance_refuses_the_run_and_it_has_no_default() -> None:
    """Ruling 7: its own key, and leak-auditor has not ruled on it. It may not fall back on anything."""
    pipeline = load_pipeline_config(GENERATED_CONFIG.parent)
    undeclared = replace(pipeline.sources["binance"], bar_source="official_1m", candle_allowance_ms=None)
    with pytest.raises(ConfigError, match="candle_allowance_ms"):
        required_allowance(undeclared, 10_000_000)
    declared = replace(undeclared, candle_allowance_ms=2_000.0)
    assert required_allowance(declared, 10_000_000) == 2_000_000
    with pytest.raises(TimingContractError, match="cover this source"):
        required_allowance(replace(undeclared, candle_allowance_ms=20_000.0), 10_000_000)


def test_the_market_configuration_is_otherwise_complete_and_names_only_the_first_span() -> None:
    config = load_engine_config(GENERATED_CONFIG.parent / "engine.toml")
    assert config.data_kind == "MARKET"
    assert config.symbols == ("BTCUSDT", "ETHUSDT")
    assert config.tier == "T0"
    assert config.funding == "required"
    assert config.opened_blocks == ("first_training_span",)
    assert config.costs.rt_bps == 12.0
    assert config.costs.stop_slip_bps == 5.0
    assert config.costs.stop_slip_state == "declared"
    assert config.risk.state == "placeholder"
    assert "Not associated with or endorsed by Binance" in config.credit_line


def test_a_range_ending_on_the_last_opened_date_reads_its_last_bar_and_any_other_stops_a_minute_short() -> (
    None
):
    """The span holds every bar closing at or before 24:00 on its last date, and the reader opens nothing
    after it.
    """
    last_opened = dt.date(2023, 12, 31)
    whole = DateRange(dt.date(2020, 1, 1), last_opened)
    assert read_cut(whole, last_opened) == whole.end_us
    earlier = DateRange(dt.date(2020, 1, 1), dt.date(2023, 6, 30))
    assert read_cut(earlier, last_opened) == earlier.end_us - 1
