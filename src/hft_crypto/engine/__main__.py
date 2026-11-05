"""`python -m hft_crypto.engine`: run every strategy on every asset over a stated date range.

It writes files. It can place no orders, because nothing in this package can reach a venue.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from hft_crypto.bars.core import TimingContractError
from hft_crypto.config import ConfigError
from hft_crypto.data.atomic import canonical_json_bytes
from hft_crypto.data.guard import PathGuardError
from hft_crypto.data.zones import DataRootError
from hft_crypto.engine.config import DateRange
from hft_crypto.engine.run import declare_costs, run_engine
from hft_crypto.reports.portfolio import stream_status
from hft_crypto.timeutil import parse_date


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hft_crypto.engine",
        description="V0 of the strategies, in IDEAL-1M. Output is labelled SIMULATED. Sends no orders.",
    )
    parser.add_argument("--data-root", help="data directory. Defaults to the DATA_ROOT variable.")
    parser.add_argument(
        "--config", required=True, help="the engine configuration, such as configs/engine.toml"
    )
    parser.add_argument("--start", required=True, help="first UTC day of the range, YYYY-MM-DD. Required")
    parser.add_argument("--end", required=True, help="last UTC day of the range, YYYY-MM-DD. Required")
    parser.add_argument("--out-dir", help="where to write. Defaults to results/runs under the data root")
    parser.add_argument("--pipeline-config-dir", help="directory holding pipeline.toml")
    parser.add_argument(
        "--declare-costs",
        action="store_true",
        help="log the configuration's costs in the trial registry under C12, and run nothing",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    try:
        if args.declare_costs:
            declare_costs(data_root=args.data_root, config_path=args.config)
            sys.stdout.write("The configuration's costs are in the trial registry. Nothing ran.\n")
            return 0
        outcome = run_engine(
            data_root=args.data_root,
            config_path=args.config,
            date_range=DateRange(parse_date(args.start), parse_date(args.end)),
            out_dir=args.out_dir,
            pipeline_config_dir=args.pipeline_config_dir,
        )
    except (ConfigError, DataRootError, PathGuardError, TimingContractError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    summary = {
        "labels": list(outcome.labels),
        "run_id": outcome.run_id,
        "date_range": outcome.header["date_range"],
        "risk": outcome.header["risk"],
        "costs": outcome.header["costs"],
        "funding": outcome.header["funding"],
        "streams": [
            {
                "strategy": stream.strategy,
                "line": stream.line,
                "is_default": stream.is_default,
                "asset": stream.symbol,
                "status": stream_status(stream),
                "setups": stream.setups,
                "trades": len(stream.trades),
            }
            for stream in outcome.streams
        ],
    }
    sys.stdout.write(canonical_json_bytes(summary).decode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
