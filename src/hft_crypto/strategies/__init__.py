"""Candle strategies, `V0`, one module per document in docs/01_strategies/.

A strategy holds no root and reads no file. It is given a `MarketView`, which holds only what has been
released.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hft_crypto.strategies.base import Strategy
from hft_crypto.strategies.s01_floor_pivot_rejection import S01FloorPivotRejection
from hft_crypto.strategies.s02_pivot_breakout_retest import S02PivotBreakoutRetest
from hft_crypto.strategies.s03_market_structure import S03MarketStructure
from hft_crypto.strategies.s04_supply_demand_zones import S04SupplyDemandZones
from hft_crypto.strategies.s05_zone_polarity_flip import S05ZonePolarityFlip
from hft_crypto.strategies.s06_liquidity_sweep_reclaim import S06LiquiditySweepReclaim
from hft_crypto.strategies.s07_anchored_vwap_pullback import S07AnchoredVwapPullback
from hft_crypto.strategies.s08_volume_profile_value_area import S08VolumeProfileValueArea
from hft_crypto.strategies.s09_session_range_breakout import S09SessionRangeBreakout
from hft_crypto.strategies.s10_volatility_compression import S10VolatilityCompression

_BUILDERS: dict[str, Callable[[dict[str, Any]], Strategy]] = {
    "S01": S01FloorPivotRejection,
    "S02": S02PivotBreakoutRetest,
    "S03": S03MarketStructure,
    "S04": S04SupplyDemandZones,
    "S05": S05ZonePolarityFlip,
    "S06": S06LiquiditySweepReclaim,
    "S07": S07AnchoredVwapPullback,
    "S08": S08VolumeProfileValueArea,
    "S09": S09SessionRangeBreakout,
    "S10": S10VolatilityCompression,
}


def available_strategies() -> tuple[str, ...]:
    return tuple(sorted(_BUILDERS))


def build_strategy(strategy_id: str, params: dict[str, Any]) -> Strategy:
    return _BUILDERS[strategy_id](params)
