# Candle strategy index

Status: revised after the leak audit of 2026-11-04, findings L-01 to L-37, and awaiting re-audit of the
changed text. Date: 2026-11-04. Owner: `strategy-architect`. Changes are listed in
[CHANGES_2026-11-04.md](CHANGES_2026-11-04.md).

**Nothing in this folder has been tested.** No document claims or implies that any strategy is
profitable. Trade counts, typical stop sizes and cost figures in sections 9 and 13 of each document are
descriptive design estimates or arithmetic illustrations, to be replaced by measured descriptions at gate
G3. Measuring them changes no rule: a rule constant changes only by a new document version, which counts as
a trial. See [C12](#c12-indicators-and-frozen-values). Worked examples use invented prices.

## 1. The strategies

| ID | Document | Mechanism in one line | Family | Default `T_d` | Live on the hourly cycle | Tier | Evidence grade for the rule | Adjacent mechanism evidence |
|---|---|---|---|---|---|---|---|---|
| S01 | [Floor pivot rejection](S01_floor_pivot_rejection.md) | Formula levels from the prior UTC day or week as coordination points, faded on a fast reaction | Reversal at a computed level | 15m | **No**, backtest only | T0 | `PRACTITIONER` | `LITERATURE` (support and resistance in FX and stocks) |
| S02 | [Pivot breakout, acceptance, retest](S02_pivot_breakout_acceptance_retest.md) | The same levels, joined after price proves it can stay beyond them | Continuation from a computed level | 1h | **Yes**, 1h | T0 | `NONE` | `LITERATURE`, mixed (stop clusters, trends after crossing) |
| S03 | [Market structure, BOS and CHoCH](S03_market_structure_bos_choch.md) | Close-based breaks of causally confirmed swings, entered only after the structure has flipped | Trend following | 1h | **Yes**, 1h or 4h | T0 | `NONE` | `LITERATURE`, weak and mixed (Dow Theory, daily breakouts) |
| S04 | [Supply and demand zones](S04_supply_demand_zones.md) | First return to the base behind a strong departure, ranked by a causal quality score | Reversal at a formed zone | 1h | **Yes**, 1h or 4h | T0 | `NONE` | `LITERATURE`, indirect (order splitting, depth at levels) |
| S05 | [Zone polarity flip](S05_zone_polarity_flip.md) | A failed zone retested from the other side, while trapped participants exit | Continuation from a failed zone | 1h | **Yes**, 1h or 4h | T0 | `NONE` | `LITERATURE`, indirect (disposition effect) |
| S06 | [Liquidity sweep and reclaim](S06_liquidity_sweep_reclaim.md) | Stops beyond an obvious high or low are taken, then price reclaims the level | Failed breakout reversal | 15m | **No**, backtest only | T0 | `NONE` | `LITERATURE`, for the fuel but not for the reversal |
| S07 | [Anchored VWAP pullback](S07_anchored_vwap_pullback.md) | Pullback to the average cost of everyone who traded since a confirmed swing | Trend pullback to volume-weighted cost | 1h | **Yes**, 1h | T1 | `PRACTITIONER` | `LITERATURE`, indirect (reference prices) |
| S08 | [Volume profile value area](S08_volume_profile_value_area.md) | Excursion outside the prior day's value is classified as rejected or accepted | Auction rotation or migration | 1h | **Yes**, 1h only. 30m is backtest only | T1 | `NONE` | None found |
| S09 | [UTC session range breakout](S09_utc_session_range_breakout.md) | Range built in the seasonal volume trough, broken as seasonal volume arrives | Clock-driven breakout | 1h | **Yes**, 1h | T0 | `LITERATURE` (other markets) | `LITERATURE` (crypto seasonality of volume, not of return) |
| S10 | [Volatility compression expansion](S10_volatility_compression_expansion.md) | A statistically compressed market expands, and the first close out of the box sets the side | State-driven breakout | 4h | **Yes**, 1h or 4h | T0 | `LITERATURE` (other markets, unfavourable in recent data) | `LITERATURE` (volatility clustering) |

Eight of ten can run live, all at 1h or slower. S01 and S06 cannot, because the hour lost to the cycle is
longer than the reaction they trade. See [C17](#c17-hourly-live-cycle).

Six of ten rules have no published or practitioner test that I could find. That is the honest position
for pivot breakouts, BOS and CHoCH, supply and demand zones, polarity flips, sweeps and value areas. It
makes these ideas hypotheses, and it makes the placebo control in [C15](#c15-placebo-control) essential.

## 2. What each one adds

| ID | Adds to the portfolio | Dynamic stop and target signature |
|---|---|---|
| S01 | Short-holding mean reversion on quiet, rotational days | Reaction clock squeezes the stop if nothing happens, target ladder of pivots rebuilt at the UTC roll |
| S02 | Exposure to the days S01 loses on, using the same levels | Ladder ratchet: each accepted pivot becomes the new stop basis, plus a participation check |
| S03 | Multi-day trend capture | Steps on confirmed higher lows, BOS lock, climax tighten, measured-move targets recomputed at each BOS |
| S04 | Reversal entries away from formula levels | Absorption check, zone-stack stop from newly knowable zones, targets pulled in by newly knowable opposing zones |
| S05 | The other side of S04's failures | Staged on the break extreme: trapped-inventory clock, then the flip zone must hold |
| S06 | Very short reversals after forced flow | Reclaim line invalidation, linger test, aftershock exit, opposite pool target |
| S07 | Volume-weighted cost basis instead of price geometry | Stop rides a stack of anchored VWAPs, band targets move on every bar |
| S08 | Volume-at-price structure, from trade data | Developing value area trails the stop, rotation target decays with time |
| S09 | Time-of-day conditioning | Session clock tightens the chandelier as seasonal volume fades, volume-arrival check, hard flat time |
| S10 | Regime state, with slow holding and few trades | Chandelier tightens as volatility expands, volatility-thesis exit, climax target |

### Why ten, and why compression rather than the fair value gap

I kept ten candidates because each has a different counterparty story and fails in a different way. S02
and S05 came closest to being the same idea, since both retest a broken level. I kept both because S02
relies on coordination around a formula level, where nobody necessarily holds a position, while S05
relies on real inventory trapped in a zone with a known price range. If the correlation in section 3
comes back high at G4, S05 is the first candidate to retire, under the rules in
[C18](#c18-selection-purge-and-retirement).

For the tenth slot I chose volatility compression and dropped the three-candle fair value gap fill. A
gap fill is a displacement-defined zone, so its mechanism is mostly contained in S04, and the expected
correlation would be high. Compression is the only candidate here defined by a volatility state, with
no price level as its reason to trade, so it differs more from the other nine. The evidence pointed the
same way. A broker review states that no peer-reviewed study tests the pattern and that quoted fill
rates are unsourced ([Alphaex Capital](https://www.alphaexcapital.com/smart-money-concepts/fair-value-gap-explained)).
An informal tick-level test on EURUSD found that gaps and random nearby levels converge in fill rate at
long horizons, and attributed the effect to proximity
([Curupira](https://curupira-blog.pages.dev/blog/fvg-magnetism-fair-value-gaps)). That is a blog post,
not proof, but it is the only outcome test I found, and it gives no reason to prefer the gap.

## 3. Expected correlations

These are expectations, to be measured at G4 on trade-level returns. Sign is the expected sign of the
daily P&L correlation between the two streams on the same symbol.

| Pair | Expected | Reason |
|---|---|---|
| S01, S02 | Negative on the same level and day | Same levels with opposite theses: when one is right the other is usually wrong |
| S04, S05 | Negative on the same zone | S05 trades the zones S04 lost on, by construction |
| S02, S05 | Positive, moderate | Both enter on the retest of something broken. Most likely pair to be redundant |
| S01, S06 | Positive, moderate to high | Both fade a level on a close back, on short timeframes, in rotational conditions |
| S01, S08 (rejection branch) | Positive, moderate | Both fade an edge back toward the middle of the prior day. Levels often sit near each other |
| S04, S06 | Positive, moderate | Reversal after a fast move into a structural area. A sweep low often sits inside a demand zone |
| S03, S07 | Positive, moderate to high | Both ride trends from confirmed swings. They differ in entry location and in stop logic |
| S03, S10 | Positive, moderate | Both need sustained directional moves. S10 is slower and much less frequent |
| S09, S10 | Positive, low to moderate | Both are breakouts from quiet. S09 is defined by the clock, S10 by volatility state |
| S02, S09 | Positive, moderate on US-hour days | Breakouts during the seasonal volume rise |
| S08 (acceptance branch), S02 | Positive, moderate | Both are continuation after a held break of a prior-day reference |
| Trend family (S02, S03, S09, S10) against reversal family (S01, S04, S06, S08 rejection) | Negative or near zero | They want opposite market behaviour. This is the main diversification the portfolio is built on |

All strategies are also linked through BTC itself. BTC and ETH positions in the same strategy should be
treated as highly correlated risk at layer 5.

## 4. Trial budget

Grids are pre-declared in each document and total **64 candidate configurations** for `V0`.

| S01 | S02 | S03 | S04 | S05 | S06 | S07 | S08 | S09 | S10 |
|---|---|---|---|---|---|---|---|---|---|
| 8 | 4 | 8 | 8 | 4 | 8 | 4 | 8 | 4 | 8 |

Each symbol and each flow variant multiplies this count, and all of it goes to the trial registry. The
stop and target parameters are deliberately **not** in the grids. They are frozen, because tuning them
is the fastest way to overfit an exit.

The hourly-cycle requirement did not raise this count. S08 and S09 now use 1h defaults, because a
timeframe that can never run live is a poor use of trials. S08's 30m runs still count as trials, although
they cannot be selected. The delay scenarios in [C17](#c17-hourly-live-cycle) are stress reports on a chosen
configuration. They are logged, but they are not used to pick parameters beyond the one selection scenario
named in [C18](#c18-selection-purge-and-retirement). The `m` and `H` of each `V0S` control are outside the
grids and are frozen. Changing them is a counted trial.

## 5. Common conventions

Every strategy document uses the rules below. They are written once here so they cannot drift. A
strategy document may add to them and must state any exception explicitly.

**Simulation modes.** Every result belongs to exactly one mode, and the mode is recorded on it.

| Mode | Decision | Entry and close-based exit fill, and when an update acts | Used by |
|---|---|---|---|
| `IDEAL` | At the bar close, **labelled zero latency and zero allowance** | The next `T_d` open. An update acts from the next `T_d` bar | All strategies, as a research measure. Never compared with live results |
| `IDEAL-1M` | At the bar close | The first 1m bar with `open_time >= t + max(latency, A)`, where `t` is the close and `A` is the allowance. The exit engine walks 1m bars | All strategies, reported beside `IDEAL` everywhere. It is the selection mode for S01 and S06 |
| `CYCLE` | At a run, [C17](#c17-hourly-live-cycle) | Steps 5 and 6 of C17 | Live-eligible strategies. The only mode compared with live results |

One fill model holds for a whole sample within a mode. There is no switch to finer data where coverage
happens to exist. `latency` and `A` are declared in [C17](#c17-hourly-live-cycle). C6 and C7 are written in
`IDEAL` terms, as are sections 1 to 13 of each document and their worked examples. Section 14 of each document
states how they change under `CYCLE`.

### C1. Instrument and venue

One linear perpetual per symbol, on one venue per run. Prices from different venues are never merged
into one bar or one profile. Candle prices are last-trade prices, not mark prices. The reference venue
is open under decision `D-01`, and results are retested on the chosen venue. No result may be described
as venue-independent without that retest.

### C2. Bars and calendar

- A bar covers `(open_time, close_time]` and is knowable at `close_time`. Bar `k` has `O_k, H_k, L_k,
  C_k, V_k` and close time `t_k`.
- Bars sit on a fixed UTC grid. A 1h bar closes on the hour, a 4h bar at 00, 04, ..., 20 UTC.
- A UTC day is `(00:00, 24:00]`. A UTC week runs from Monday 00:00 to the next Monday 00:00.
- `T_d` is the strategy's decision timeframe. `n` counts bars since entry, and the fill bar is `n = 1`.
- **Bar source.** Canonical bars are built from trades under decision `D-12`. In every mode and for both tiers, 1m bars
  come from trades and `T_d` bars are aggregated from those 1m bars, so `IDEAL` and `CYCLE` read the same bars. In research
  the trades come from the archive. On the live path they come from the hourly poll of the same venue, and the same code
  builds the bars. This trade feed is the one candle source of a tier `T0` strategy. Official venue bars are only a
  reconciliation check at gate G1.
- **A minute with no trades.** It is a bar with zero volume and no price only when the response that delivered the data
  proves continuity across that minute, by a trade id or sequence number with no skip, or by overlapping pages. Such a bar
  can touch nothing and adds nothing to a `T_d` bar's high, low or volume. `P_dec` or a `T_d` close uses the last trade before
  it, and a fill uses the first 1m bar that has a price. **Otherwise the minute is a gap**, so a hole cannot pass as zero-volume
  minutes and hide a stop touched inside it. The [completeness check](#c17-hourly-live-cycle) speaks only to the end of the data
  and is not this proof. A source with no sequence therefore treats every empty minute as a gap, which costs little on a liquid
  perpetual. The same test applies to the archive at gate G1.
- **Levels and the bar that built them.** A bar is evaluated against the level set in force at its open. A new
  UTC day or week set first acts on the bar that opens at the roll, so the bar that closes at the roll is never
  tested against a level built from itself. Rules that update an open trade at the close of that roll bar are
  unchanged: they read the new set at that close and act as any other update does.
- **Missing bars.** If a bar needed by a formula is missing, the object is not computed and no setup is created.
  Nothing is forward-filled or backfilled. See [C3](#c3-indicators) for how indicators recover.
- **A gap during an open position in `IDEAL`.** Mark the trade `GAP_UNRESOLVED` and report it both ways: as if
  the active stop was touched at the start of the gap, and as if no touch happened. The worse of the two is the
  headline. `IDEAL-1M` follows the same rule for a gap in 1m bars. `CYCLE` has its own rule in
  [C17](#c17-hourly-live-cycle).

### C3. Indicators

All values below are computed from closed bars of the stated timeframe, and each is knowable at the close
of its last input bar.

| Name | Definition |
|---|---|
| `TR_k` | `max(H_k - L_k, abs(H_k - C_(k-1)), abs(L_k - C_(k-1)))` |
| `ATR_k` | Wilder ATR(14) on `T_d`, unless a list or rule names another timeframe. Seed with the mean of the first 14 `TR`. Then `ATR_k = (13*ATR_(k-1) + TR_k) / 14` |
| `ATRD` | Wilder ATR(14) on UTC daily bars, last completed day only. It changes at 00:00 UTC |
| `VR_k` | `ATR_k / median(ATR_(k-N+1), ..., ATR_k)`, with `N` the number of `T_d` bars in 30 days. Undefined with fewer than `N/2` values in the window |
| `SRV_k` | Seasonal relative volume: `V_k / median(V of the same weekly slot in each of the previous 8 weeks)`. Undefined with fewer than 4 of those slots |
| `CLV_k` | `(C_k - L_k) / (H_k - L_k)`, or `0.5` if `H_k = L_k` |
| `clip(x, a, b)` | `min(max(x, a), b)` |
| `DayOpen` | Open of the first `T_d` bar of the current UTC day |

**Warm-up and recovery.**

- Recursive values warm up from a canonical start date, declared in configuration, and carry their state forward.
  A live run keeps that state, and a rebuild after a cache miss replays from the canonical start, so live and
  backtest values match exactly.
- After a gap in a timeframe's bars, `ATR` on that timeframe is undefined until 14 complete bars have followed the
  gap, and it is then re-seeded with the mean of those 14 `TR`.
- Any condition using an undefined value fails, so no setup is created. At a close where an open position's stop or
  target update needs an undefined value, that update is not computed and the stop holds.
- **Exit rules do not fail open.** An open position's invalidation and exit rules, and every `ATR`-based register state event
  (`broken_at`, `consumed_at`, `dead_at`), use the last defined `ATR` of that timeframe, frozen and logged, until the re-seed. The
  amplitude test in [C4](#c4-swing-pivots-and-registers) uses the same value. Before the first seed no such value exists, so a swing
  confirmed then is ignored. Setups still fail. Register events follow this whether or not a position is open, so a register never
  depends on a position. This fills no bar.
- Filling a missing value to avoid any of this is forbidden.

### C4. Swing pivots and registers

- `SwingHigh(i; Lf, Rt)` is true when `H_i > max(H_(i-Lf), ..., H_(i-1))` and
  `H_i >= max(H_(i+1), ..., H_(i+Rt))`.
- `SwingLow(i; Lf, Rt)` is true when `L_i < min(L_(i-Lf), ..., L_(i-1))` and
  `L_i <= min(L_(i+1), ..., L_(i+Rt))`.
- The swing is **knowable at `t_(i+Rt)`**, its confirmation time, and never at `t_i`.
- If one bar `i` is both a swing high and a swing low, both confirm at one close. Process the high first if
  `C_i >= O_i`, otherwise the low first. This uses only that bar's data, so replay and live agree.
- `Sigma(Lf, Rt, a)` is the alternating list of confirmed swings. On confirmation of a swing `X` at time `t`,
  with `last` the latest entry valid at `t`:

```text
if X has the same type as last:
    if X is more extreme than last:
        last.valid_to = t
        add X with valid_from = t
    else: ignore X
else:
    if abs(X.price - last.price) >= a * ATR: add X with valid_from = t
    else: ignore X
```

`ATR` here is on the list's own timeframe, valued at the confirmation bar. During a re-seed it is the last defined value,
under [C3](#c3-indicators). A replacement never changes a stop that has already moved.

**Registers are event-sourced.** This applies to every list of objects in this folder: swing lists, zones, flips,
liquidity pools and anchors.

- Each entry carries `valid_from`, its confirmation or birth time, and `valid_to`, the time it was replaced or
  superseded, empty while it stands.
- A change of state (`broken_at`, `consumed_at`, `dead_at`, `superseded_at`, each touch) is an event with its own time.
- **Every read is as of a time `t`:** an entry is visible when `valid_from <= t < valid_to`, and a state event counts
  only if its time is at or before `t`.
- **A final-state table is forbidden as an input** to any decision, stop, target, placebo or report calculation.
- **Truncation invariance is a required test for every register.** Recomputing with all data after `t` removed must
  give the same as-of state at `t`. The timestamp audit cannot replace this test: a final-state list joined by
  knowable time passes `knowable_time <= decision_time` and still uses later data.

### C5. Setup object and gate window

A setup is created at the close of the trigger bar `k`, from closed bars only. It holds `side`,
`level_or_zone`, `invalidation` (the initial stop `S0`), `targets`, `created_at = t_k` and `expiry`.

- `V0` sends its entry at `t_k`.
- Flow variants may send `ENTER` from `t_k` until `expiry`. They use the same `S0`. The gate must return
  `EXPIRE` if the price has moved more than `0.5 * ATR_k` from `C_k`, and must refuse entry if
  `abs(price - S0)` is below the floor of [C9](#c9-floors).
- A vetoed or expired setup stays in the record with its counterfactual, as in [C14](#c14-event-log).

### C6. Entry, fill, `R` and size

- **Decision price.** `P_D` is `C_k` in `IDEAL` and `IDEAL-1M`, and `P_dec` in `CYCLE`.
- **Fill reference.** A decision at `t_k` fills no earlier than `t_k + latency`. The fill reference `F` is `O_(k+1)`
  in `IDEAL`, labelled zero latency. In the other modes it is the open of the first 1m bar named in the mode table, or of
  the first after it that has a price. A long pays `F * (1 + slip)`, a short receives `F * (1 - slip)`.
- **Collar.** The entry is sent as a marketable limit, immediate or cancel, with its limit fixed at the decision: a
  long at `P_D + 0.5 * ATR_k`, a short at `P_D - 0.5 * ATR_k`. If `F` is beyond the collar there is no fill, logged
  `ENTRY_COLLAR`. The test is on `F`, before slippage. Nothing else cancels an order already sent.
- **A gap the other way fills.** If `F` is at or beyond `S0`, the trade exists. [C7](#c7-exit-engine) stops it on the
  fill bar at `F` less stop slippage, logged `ENTRY_THROUGH_STOP`. Its `Result_B` uses `R_dec`, and no `Result_R`
  is reported for it. `Result_B` always includes these trades, and every statistic in `R` prints the count it excludes.
- **`R_dec` and size.** `R_dec = abs(P_D - S0)` is recorded with the decision and never changes. Size is sent before
  the fill price is known, so it is `risk_budget / R_dec`. The risk budget belongs to layer 5.
- **`R`.** `R = abs(fill - S0)`, fixed at the fill. It is the input to every rule written in `R` multiples.
  Accounting is in [C10](#c10-accounting).
- **Passive fills.** `V0` entries are taker orders, so gate G5's passive-fill test is not needed for entries. Target
  exits are passive fills, and G5 applies to them. See [C7](#c7-exit-engine).

Slippage needs care. Published work finds the largest crypto volatility burst in the first minute of the
hour, with smaller ones at minutes 15, 30 and 45
([Hansen et al.](https://ar5iv.labs.arxiv.org/html/2109.12142)). A decision on a bar close therefore
tends to fill inside that burst, so `slip` must reflect bar opens and not an average over all minutes. How its
value is set is in [C12](#c12-indicators-and-frozen-values).

### C7. Exit engine

Long side shown. A short is the mirror image. In `IDEAL-1M` the same loop walks 1m bars, with close-based rules still
evaluated at `T_d` closes. There, a pending exit fills at the 1m bar named in the mode table, and every earlier 1m bar is walked
first under the stop in force.

```text
for each bar b from the fill bar onward, while quantity > 0:
    if an exit is pending:                      # decided at t_(b-1) by an invalidation, time stop or flow exit
        exit all at O_b, less slip              # a stop gap on this open is the same price,
        end                                     # and is labelled by the earlier decision
    S = active stop, Ts = active targets        # set at t_(b-1); on the fill bar, S0 and the setup targets
    if O_b <= S:
        exit all at O_b, less stop slippage     # ENTRY_THROUGH_STOP on the fill bar, otherwise STOP_GAP
    elif L_b <= S:
        exit all at S, less stop slippage       # STOP. The stop is tested first (timing contract, item 8)
    else:
        for each unfilled target Ti in ascending order:
            if H_b > Ti: exit its planned quantity at Ti    # passive fill on a trade-through
    at t_b, if quantity > 0, in this order:
        1. invalidation rules: if any fires, set an exit pending
        2. time stops: same handling
        3. compute stop candidates and target updates, apply C8, log, effective from bar b+1
```

- **Same-bar conflicts.** When both `S` and a `Ti` lie inside `[L_b, H_b]` of one `T_d` bar, 1m bars are always used,
  walking the same loop. If one 1m bar contains both, the stop is first. Where 1m data is missing, the stop is first
  and the bar is counted in a report. Updates still take effect only from the next `T_d` bar.
- **Targets are passive fills.** A target needs a trade through its price by at least one tick, and fills at its price
  with no positive slippage. A gap beyond a target fills at the target, not at the better open. The fee on target
  exits is a declared configuration value, and the base case uses the taker rate.
- **G5 stress for targets.** Report two cases: a required trade-through of 2 bp, and a target that exits at the next 1m
  open after the touch, less `slip`.
- **Slippage.** Stop slippage is a separate required configuration value, because stops fill worst during cascades.
  Close-based and time exits pay `slip`.

### C8. Stop ratchet and `BE+`

Every stop change in every strategy goes through this one rule, so a stop cannot move backward.

```text
long:  S_new = max(S_old, min(S_cand, C_b - 0.10 * ATR_b))
short: S_new = min(S_old, max(S_cand, C_b + 0.10 * ATR_b))
```

If several candidates fire at one close, `S_cand` is the tightest. Flow overlays use the same rule, and between `T_d`
closes they use the values of the last closed `T_d` bar, as in [C17](#c17-hourly-live-cycle). `BE+` means break-even plus costs: `fill * (1 + RT)` for a long and `fill * (1 - RT)` for a short.

### C9. Floors

`RT = 2 * (fee_taker + slip)` is the base-case round-trip cost as a fraction of price.

```text
R_min(a) = max(a * ATR_k, 4 * RT * C_k)
S0 (long) = min(S_struct, C_k - R_min(a))
```

The factor 4 limits the base-case cost to about `0.25R` per trade. The value `a` differs by strategy.
`RT` here is frozen at the 1x base case, so the 2x and 3x cost reports change P&L and not the trade list. Because
`RT` feeds setups through this floor, its value is set as [C12](#c12-indicators-and-frozen-values) requires.

### C10. Accounting

For a long, with `q0 = risk_budget / R_dec` and `f_i` the fraction of the original quantity exiting at price `X_i`:

```text
money P&L = q0 * sum(f_i * (X_i - fill)) - fees - funding
Result_B  = money P&L / risk_budget  = sum(f_i * (X_i - fill)) / R_dec - (fees + funding) / risk_budget
Result_R  = sum(f_i * (X_i - fill)) / R - (fees + funding) / (q0 * R)
```

- Price slippage is already inside `fill` and `X_i`. The cost term holds fees and funding only, so nothing is
  counted twice.
- **`Result_B` is the measure** for gates, placebo comparisons and variant comparisons, which charter section 7 rule 4
  names, and here that includes `V0` against `V0S` and `IDEAL` against `CYCLE`. This index adds parameter selection to that
  list, because its denominator is fixed at the decision. A fill close to the stop makes `R` tiny and inflates `Result_R`,
  and `R_dec` does not have that problem. Reports may show `Result_R` beside it, with the count of trades it excludes.

**Funding** is charged at actual settlement times, on the quantity open at that moment, using the rate published then.
No rule may use a future funding rate. It is charged when `entry fill time < settlement <= exit fill time`, consistent
with `(open, close]` bars: a fill at the first trade after a settlement pays nothing for it, and an exit after a
settlement pays it. A rate that has not arrived stays open as a reported liability, and is settled by an appended event
when it arrives. Settlement times and rates come from the chosen venue. As an example of one venue's schedule,
Binance's default for USDT-margined contracts is every 8 hours at 00:00, 08:00 and 16:00 UTC, and it can differ by
contract ([Binance funding](https://www.binance.com/en/support/faq/detail/360033525031)).

### C11. Overlap policy

One open position per strategy and symbol. A setup that arrives while one is open is logged as
`SKIPPED_OPEN` and not traded. Reversing into the opposite side requires a new setup after the position
is flat. Portfolio-level overlap between strategies belongs to layer 5.

Under `CYCLE`, `SKIPPED_OPEN` is judged on the position state committed at `t_dec`, with a pending exit counted as open.
If several setups for one strategy and symbol pass in one run, the one with the earliest `t_k` proceeds and the others
are `SKIPPED_OPEN`.

### C12. Indicators and frozen values

**Indicators.** A statistic computed at each close only from bars at or before that close (`ATR`, `VR`, `SRV`, percentile
ranks) is a causal indicator with no fitted state, under timing contract item 10, and needs no freezing.

**Three kinds of frozen value:**

| Kind | Members | Rule |
|---|---|---|
| Estimated | S09's seasonal profile. `RT` and stop slippage, if they are not declared as constants | Fitted only on data before the block they apply to, frozen for that block, and the value logged in the trial registry |
| Selected thresholds | Any grid value, such as `PR_max`, `SRV_min` and `Q_min` | Chosen on training folds under [C18](#c18-selection-purge-and-retirement), frozen for the block |
| Declared constants | Everything else: stop and target multiples, `VR_k <= 2.0`, the `CR` band, the `Q` weights, `A_max`, chase and `RR_late` values, `m` and `H`, and `RT` and stop slippage if declared | Set before any run. A change is a new document version and a counted trial |

`RT` and stop slippage must be one or the other, chosen before the first run. A value measured over a whole history and
applied to it would let later data change `S0` for an early setup, and is forbidden.

**Estimation calendar.** Estimated values refit at 00:00 UTC on 1 January, 1 April, 1 July and 1 October. It is declared
here before any run, without sight of any result, and a change is a counted trial. S09's rules for what happens across a
refit are in [its section 3](S09_utc_session_range_breakout.md#3-definitions).

### C13. `V0S` control

Same setup, same entry, same `S0` and `R` as `V0`. One fixed target at `fill + m*R` (long) or `fill - m*R`
(short), and a fixed maximum hold of `H` bars, closed at the next open. No scale-out, no invalidation, no
update of any kind. Same fees and funding. Each document gives `m` and `H`, and both are declared constants.

A `V0S` target is set from the fill, so the fill bar uses that target, an exception to the setup target named in
[C7](#c7-exit-engine). `V0S` follows C7 for a pending exit and for exit slippage. Under the cycle, `H` follows charter
section 7 rule 7.

### C14. Event log

Every event is logged with old value, new value, reason, computed-at time and effective-from time:
`SETUP_CREATED`, `ENTRY`, `ENTRY_COLLAR`, `ENTRY_THROUGH_STOP`, `STOP_UPDATE`, `TARGET_UPDATE`, `SCALE_OUT`, `INVALIDATION`,
`TIME_STOP`, `EXIT`, `SKIPPED_OPEN`, `GAP_UNRESOLVED`. Under `CYCLE`, also `STALE_SETUP`, `DATA_GAP` and `GAP_CLOSE`, and every
event carries the time fields defined in [C17](#c17-hourly-live-cycle).

**Mode.** Every event, registry row and report carries a `mode` field. Report code refuses to combine modes in one statistic. The
one exception is the named difference `IDEAL` minus `CYCLE` in [C17](#c17-hourly-live-cycle), which shows each side with its mode.

**Counterfactuals.** A setup not taken (`VETO`, `EXPIRE`, `STALE_SETUP`, `SKIPPED_OPEN`, `ENTRY_COLLAR`) keeps a counterfactual. In `IDEAL`
and `IDEAL-1M`, it is the same trade in that mode, ignoring the failed check. Under `CYCLE` there are two labelled fields:

| Field | Meaning | Where it may be used |
|---|---|---|
| `CF_CYCLE` | The same trade under `CYCLE`, filling at the step 5 price and ignoring the failed check | `CYCLE` statistics, and the ledger |
| `CF_IDEAL` | The same setup under `IDEAL` | Analysis only. Never in the ledger, and never in `CYCLE` statistics |

A counterfactual result is a later event, with `knowable_time` at its maturity. Training may read it only after that time.

### C15. Placebo control

For gates G3 and G4. This copies the design of
[Osler (2000)](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html), where
arbitrary levels "bounced" 56.2 percent of the time and published levels 60.8 percent. A bounce rate alone
therefore says little, and only the difference from the placebo is informative.

**Strategies with levels or bands (S01, S02, S04, S05, S06, S08).**

- A placebo level is drawn at the real level's knowable time, as a distance in `ATR` units from the close at that time.
  A placebo band also keeps the real object's width in `ATR` units.
- The distance distribution is built only on earlier blocks, from real levels and the closes at their knowable times. The
  first block therefore has no placebo.
- The whole level set is replaced, including levels used as targets, so no real level stays in the placebo's result.

**Strategies with no level (S03, S10).** Entry bars are drawn uniformly over bars passing the strategy's non-signal filters.
The side is random, at the block's real long and short share, and independent of returns. That share is same-block information. It
gives the placebo the block's direction, which can only make it harder to beat, and reports say so. S03's stop uses the causal list
as of that bar, and its targets are in its [section 10](S03_market_structure_bos_choch.md#10-regime-expectations). S10's box is the box
as of that bar.

**S07.** A random-anchor placebo, with as many anchors per side as the block's real major swings, in its
[section 10](S07_anchored_vwap_pullback.md#10-regime-expectations). **S09.** The window is moved by a shift drawn independently per day,
from 1 to 23 hours, and the whole schedule moves with it, in its [section 10](S09_utc_session_range_breakout.md#10-regime-expectations).

**All placebos.** At least 100 draws, declared in advance and reported as a distribution. Redrawing or selecting a draw is forbidden.
The configuration and the mode are the same as the real run. Under `CYCLE`, placebo setups pass through the same run function, checks and
run times. Comparisons use `Result_B`. Placebo runs are recorded in the trial registry as controls.

### C16. Rounding and arithmetic in examples

Stops and targets round to the instrument tick: a long stop or target rounds down, a short stop or target
rounds up. Worked examples use BTC tick 0.1 and ETH tick 0.01, `fee_taker = 5 bp` and `slip = 1 bp`, so
`RT = 12 bp`. These are **assumptions for arithmetic only**, not venue facts. Binance's fee page refers to
a separate schedule that I could not open.

Worked examples run in `IDEAL`, and hold `ATR` flat unless a table shows otherwise. Entries show `slip`, because `R` depends on it.
Exit prices are shown before exit slippage, and results in `R` and `Result_B` are shown before fees, funding and exit slippage.

### C17. Hourly live cycle

Live paper positions run from GitHub scheduled jobs with no server and no live order book. GitHub states
that scheduled runs can be delayed under load, especially at the top of the hour, and that queued jobs may
be dropped ([GitHub Actions documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)).
It publishes no delay distribution, so nothing here assumes one.

**The run clock.** This index owns this definition, and `GATE_SPEC.md` refers to it rather than defining its own.

```text
t_poll[source] = the runner's UTC clock at the start of the fetch attempt that delivered that source's data
t_cut          = floor_1m( min over all sources fetched for this symbol of t_poll[source] - A )
```

`A` is the declared allowance. It covers the source's publication lag and the skew between the runner's clock and the source's clock. A
run can fetch several sources at different moments, so the earliest fetch sets the cut-off. **There is one `t_cut` per run and symbol**, shared
by all strategies and variants on that symbol. A candle-only strategy needs only its one candle source, but it reads the same `t_cut`. All of
steps 1 to 4 use only bars with close time at or before `t_cut` and trades with time at or before `t_cut`, and `P_dec` is the close of the last
such bar. This is identical live and in backtests.

**Completeness check.** It runs in the `fetch` stage, before `decide`, for each source that feeds bars or windows. The gap check finds missing bars but not a
partial one, so the run must also hold evidence that the source's data is complete through `t_cut`:

| Where | Evidence |
|---|---|
| Live | A record stamped after `t_cut`, or a source server time at or after `t_cut + A` that came in the response delivering the last page |
| Backtest | A record stamped in `(t_cut, t_poll - A]`, or the modelled server time if the source gives one. The window is slightly stricter than live, so a record from after the run cannot pass |

If any source lacks this, `t_cut` moves back one minute and the check repeats once. If it still fails, the run logs `DATA_GAP` for that symbol. Each run logs
`t_poll` for each source, the skew, meaning the runner's clock minus the source's server time where the source gives one, and whether the check passed on server
time alone. Reports show the share of runs that did, because a server time proves the clock and not the feed, so that risk is bounded only by the measured `A`.

Funding does not take this check, because it has a record only every few hours. It follows [C10](#c10-accounting) alone. Any other sparse source declares its own rule.

**What a run sees.** Closed 1-minute bars since the last processed minute, trades, and funding settlement times and rates, all up to `t_cut`, plus the
committed state from the previous run. It sees no book, so no book feature can gate a live entry or exit.

**Timeframes.** Under 1h is backtest-only, unless a document justifies otherwise, and none does.

**Declared run constants.** Frozen before any run, in configuration, with these values. A change is a counted trial.

| Constant | Value | Note |
|---|---|---|
| Nominal start | Minute 7 of each hour | Avoids the top of the hour |
| `latency` | 500 ms | Time from commit to the first possible fill or update |
| `A` | 10 s, `UNVERIFIED` | Time for a closed bar or a trade to become readable. To be measured later from a GitHub runner |
| `D_run` | 60 s for tier `T0`, 180 s for tier `T1` | Declared run duration, used in backtests in place of a real commit time. Both tiers now fetch the same trades, so the `T0` value has lost its basis. C-10 re-bases it on that same fetch. Before the first run, that is not a counted change |
| Fetch offset | 0 s for the symbol's trade feed, until C-10 declares it. Other sources are declared in `GATE_SPEC.md` | In backtests, `t_poll[source] = run_start + its offset` |
| Fill wait | 2 minutes | Longest wait in step 5 |
| Hole deadline | 24 hours after the run that logged `GAP_CLOSE` | See "Gaps in 1m bars" below |
| Trade feed values | **`PLACEHOLDER`, re-audit condition C-10.** Page size, rate limit, retention and fetch offset for the trade feed of the chosen source, and `D_run` for tier `T0` re-based on that same fetch. They wait for the source decision under `D-01` and `D-17`. `data-steward` supplies them and `strategy-architect` records them here | **No `CYCLE` run may start until these are filled**, for any strategy, including selection under `C-LATE`, the S01 and S06 control runs, and `CYCLE` placebos. `IDEAL` and `IDEAL-1M` read the archive and do not need them |

**Order of work in one run**, for each symbol and strategy. A run has a `fetch` stage, and then two separate parts:

```text
fetch:
 0. Fetch each source and record its t_poll. Set t_cut by the run clock and the completeness check. Mark each empty
    minute by its proof of continuity under C2. Pass t_cut and the data truncated at t_cut to decide.

decide(t_cut, bars and trades at or before t_cut):
 1. Load state as of t_cut: positions, the stored history of stops and targets, the last processed minute. A fill
    dated after t_cut by the last settle is still pending here. P_dec = close of the last 1m bar with close time
    <= t_cut. Check for gaps, below.
 2. Walk each open position through the new 1m bars, in time order, with C7's logic on the 1m bar. For each 1m bar,
    the stop and targets are those in force for it, read from the stored history (effective_from <= its open_time).
    Resolve first any entry fill or exit left pending by the last run, walking every 1m bar before the fill bar.
    Charge funding on the quantity open at each settlement passed. A missing rate is logged as DATA_GAP for funding
    and is not assumed.
       gap through the stop -> exit at that 1m open, less stop slippage
       L_1m <= S            -> exit at S, less stop slippage    # stop first inside one 1m bar
       H_1m > Ti            -> scale out at Ti
 3. Build T_d bars from 1m bars. For each T_d bar newly closed, in time order:
       position state is as of t_b: T1 fill, stage, MFE and highest high use only 1m bars up to t_b
       a position already closed in the walk gets no further rules
       run invalidation rules and time stops
       compute stop and target updates, carrying each through C8 into the next
       run setup detection and the late-entry checks
    Fills from the walk stand. The rules for close b apply to whatever quantity remains.
 3b. Flow, for flow variants only, at every run: the entry gate, and flow exits, scale-outs and tightening. The gate sits
    here because decide is the only place a decision can change. It reads only bars and trades at or before t_cut, with
    position state as of t_cut. It never computes a model update.
 4. Commit all decisions to the ledger, including those of step 3b. t_dec = the commit time.

settle(the committed decisions, data up to t_dec + latency + fill wait):
 5. Entries, close-based exits, time exits, and flow exits and scale-outs fill at the open of the first 1m bar with
    open_time >= t_dec + latency that has a price, entries under the C6 collar, exits less slip. For a pending exit, first walk every 1m bar before the fill bar
    under the stop in force, charging funding as step 2 does. A touch there stands, and the pending exit is cancelled
    and logged as superseded. Otherwise it fills, and funding up to the fill is charged by the C10 boundary rule. If the
    fill bar does not exist within the fill wait, the next run's step 2 resolves it.
 6. effective_from for each new stop and target = the open time of that same first 1m bar. Add them to the stored
    history. Every earlier 1m bar, including the one straddling t_dec + latency, keeps the previous stop and targets.
```

`settle` receives the decisions and has no way to change them. It only executes them, including flow's. Truncation invariance applies to `decide`,
because only `settle` may read past `t_cut`. `t_dec` is used only for fills and `effective_from`. Since `effective_from` follows from `t_dec` alone, a
run that dies after its commit loses nothing, and the next run derives it.

**Timing consequences.**

- An update computed from the bar closing at `t_b` is knowable at `t_b`, is computed during the run, and acts only from
  `effective_from`. The old stop stays in force in between. A stop is never applied retroactively over a period in which it did
  not exist. This satisfies timing contract item 12.
- `C8` gains one clamp under `CYCLE`, since price may have moved after the close:
  `S_new = max(S_old, min(S_cand, C_b - 0.10*ATR_b, P_dec - 0.10*ATR_b))` for a long, mirrored for a short. `P_dec` is set in
  step 1, before any of these. Stops still only tighten.
- Strategy model updates happen only at `T_d` closes, the same as `IDEAL`. On a 4h strategy, the three runs between 4h closes resolve
  touches and compute no model update. Flow may still act at those runs, in step 3b.
- **Between `T_d` closes, no partial `T_d` bar is ever read.** `C_b` and `ATR_b` in the clamp above are those of the last closed `T_d` bar, with the
  `P_dec` clamp as well.
- **Time stops follow charter section 7 rule 7.** A time stop takes effect at the first run after it falls due, and fills after that
  run. The overrun is logged, and the result earned during overruns is reported, because it can be positive. Price after the due
  time cannot cancel a time stop, because step 3 reads the position as of `t_b`.
- A close-based exit also fills after the run that noticed it. A late run makes the exit later, and this is recorded and never hidden.
- `n` counts `T_d` closes, and `n = 1` is the `T_d` bar that contains the fill, so a late fill can make `n = 1` a later bar than in
  `IDEAL`. Trailing lows are based on `T_d` bars. Highest high since entry counts only 1m bars at or after the fill.
- **Label.** Item 13 of the timing contract models paper stops and targets as orders resting on the exchange between runs. Every
  `CYCLE` chart and table says so, and says that this is fair only if a real system would hold such orders.

**Time fields on every event.**

| Field | Meaning |
|---|---|
| `mode` | `IDEAL`, `IDEAL-1M` or `CYCLE`, with the scenario and seed in a backtest |
| `knowable_time` | When the input became knowable, usually a bar close. For an event that depends on a fill, the fill's time |
| `event_time` | Close time of the 1m bar in which a touch or fill happened, or `t_dec` for a decision |
| `detection_time` | `run_start` of the run that found it |
| `t_poll`, skew | For each source: the clock reading in the run clock, the runner's clock minus the source's server time where given, and whether the completeness check passed on server time alone |
| `t_cut`, `t_dec` | The run's data cut-off and commit time |
| `effective_from` | Open time of the first 1m bar on which a new stop or target acts |
| `lateness` | `detection_time - knowable_time` |

**Gaps in 1m bars.**

- If any 1m bar between the last processed minute and `t_cut` is missing, log `DATA_GAP`. An empty minute with no proof of continuity under
  [C2](#c2-bars-and-calendar) counts as missing, even when trades have resumed before the run. Resolve nothing past the gap, and take no new
  decisions for this symbol in this run. Never fill or assume.
- If the gap is still open at the next run, decide to close each open position. It fills through step 5, at the first available 1m open
  after that run's `t_dec + latency`, logged `GAP_CLOSE`. A fill any earlier would come before its own decision.
- Bars that arrive later may resolve touches only, with their true `detection_time`. If they show a stop or target touched before the
  `GAP_CLOSE` fill, a correction event is appended. Nothing is edited, under rule 10 of `CLAUDE.md`.
- **Hole deadline.** A hole still unfilled at the deadline in the constants table is marked `GAP_UNRESOLVED` by an appended event. The trade is then
  reported both ways, as in [C2](#c2-bars-and-calendar): as if the stop in force was touched at the start of the hole, and as recorded. The worse of the
  two is the headline.

**Late entries.** A setup is detected at a run, up to an hour or more after its trigger bar closed at `t_k`. The trigger, `S0` and targets
stay as computed at `t_k`, and are not recomputed for the later price. In step 3, before deciding `ENTER`, all of these must pass, or the
setup is logged as `STALE_SETUP` with its reason and its counterfactuals under [C14](#c14-event-log):

| Check | Rule |
|---|---|
| Age | `t_cut - t_k <= A_max`, given per strategy |
| Path | No 1m bar between `t_k` and `t_cut` touched `S0` or `T1`, and no `T_d` close in that span fired the strategy's invalidation |
| Chase | `abs(P_dec - C_k) <= chase * ATR_k`, given per strategy |
| Risk | `abs(P_dec - S0)` is at least the setup's `R_min` and at most the strategy's stop cap |
| Reward | `(T1 - P_dec) >= RR_late * (P_dec - S0)` for a long, given per strategy |
| Thesis | Strategy-specific: the price must still be on the correct side of the level or zone |

The entry then goes out under the [C6](#c6-entry-fill-r-and-size) collar, around `P_dec`: `P_dec + 0.5 * ATR_k` for a long, and
`P_dec - 0.5 * ATR_k` for a short. A fill reference beyond it gives `ENTRY_COLLAR`, and one at or beyond `S0` gives
`ENTRY_THROUGH_STOP`. `R_dec = abs(P_dec - S0)` and size are set at the decision. `R = abs(fill - S0)` is fixed at the fill.

**Flow under `CYCLE`.**

- A gate may only use what a run can see. It is evaluated at runs only, so `WAIT` means the next run, up to `expiry` and `A_max`.
- Flow decides in step 3b, from data at or before `t_cut`, and is committed at step 4. Steps 5 and 6 only execute it, and nothing in `settle` feeds it. Flow
  may act at any run, including runs between `T_d` closes on a 4h strategy, since it can only reduce risk under charter section 7 rule 3.
- A flow stop enters the stored history, and the next `T_d` close passes through C8 from it, so it can never be undone. Flow does not change `n` or any time
  stop. Comparing a flow variant with `V0` uses the same run times and seeds.
- **A later fill must not raise a target.** Under `.T`, where `WAIT` can make the fill later than the first look, targets stay as computed for the setup.
  Each fill-based term in a target rule, of the form `fill + x * R`, uses the less distant of its actual value and its value with the first look's
  `P_dec` in place of `fill` and `abs(P_dec - S0)` in place of `R`. This is the case in S02, S03, S07 and S10.

**Backtest reproduction.** Every live-eligible strategy reports `IDEAL`, `IDEAL-1M` and `CYCLE`. `CYCLE` must:

1. Call the same `decide` and `settle` as live, one simulated run at a time, after a modelled `fetch` that sees the archive only through the evidence
   window above. `decide` receives `t_cut` and a dataset truncated at it. `settle` receives the committed decisions, and data up to
   `t_dec + latency + fill wait`.
2. Use the run clock above, with `t_dec = run_start + D_run`, for all of steps 1 to 4 and their tests.
3. **Model each run's fetch.** A run that would exceed its time budget or a source's rate limit must behave in the backtest as it would live, by logging
   the same gap and taking the same fail-closed path, even though an archive would have the data. Per-source page size, rate limit and retention for flow
   sources are in `GATE_SPEC.md`. For the trade feed they are the placeholder in the constants table, which holds back every `CYCLE` run.
4. Build `T_d` bars from 1m bars, and check them against the venue's own bars at gate G1. Include funding in the walk, as live does.
5. Draw run times from a declared, seeded scenario:

| Scenario | Delay after the nominal minute | Dropped runs | Outages | Use |
|---|---|---|---|---|
| `C-FAST` | 2 minutes, fixed | None | None | Upper bound for comparison |
| `C-LATE` | Uniform, 2 to 45 minutes | 5 percent | None | **Parameter selection** and the headline `CYCLE` result, until measured data replaces it |
| `C-BAD` | Uniform, 2 to 60 minutes | 15 percent | None | Stress report |
| `C-GAP` | As `C-LATE` | As `C-LATE` | One 90-minute hole in 1m bars per 30 days, at random times. A hole removes the trades and the proof of continuity across them, so its minutes are gaps under C2. Two reports: hidden bars arrive 3 hours after the hole ends, and hidden bars never arrive | Data-gap stress report. Real gap logs replace it at G8 |
| `C-MEASURED` | Empirical, from real run logs, once at least 30 days exist | Empirical | Empirical | Replaces `C-LATE` as a new, visibly labelled configuration. It also replaces `D_run` and fetch offsets with values from real logs |

These delay and outage values are my assumptions and are not GitHub figures. The seed count and the seed list are declared in configuration before the
first run, with at least 5 seeds for each random scenario. A change to them is a counted trial. Report the spread across seeds. Selecting a seed is forbidden.

6. For gate G8, replay the live period with the **actual** run timestamps. The trade list must match the ledger exactly, and each mismatch goes in
   the paper versus simulation report.
7. Report the `IDEAL` minus `CYCLE` difference in `Result_B` per trade as the cost of the cycle, and `IDEAL-1M` beside both. `R` may be shown too.

A backtest result quoted beside a live record must be the `CYCLE` one. `IDEAL` and `IDEAL-1M` are research measures and are never compared with
live results.

**Required tests when code exists.** On every register and engine: truncation invariance, future perturbation, the shift test and the timestamp
audit. Also that `decide` gives identical output with data after `t_cut` removed, with held state as of `t_cut` and a later-dated fill treated as still
pending, that a backtest's `fetch` gives the same `t_cut` with data after `t_poll - A` removed, that a hole in trades is a gap and never zero-volume minutes, and
that each stop and target acting on a 1m bar in a walk has `effective_from` at or before that bar.

**Worked timeline.** A 1h setup bar closes at 13:00. The last good run was the 12:07 one. The 13:07 run is dropped. The next run starts at 14:21:05, and a
candle-only strategy's one fetch begins at that moment. So `t_cut = floor_1m(14:20:55) = 14:20:00`. The `fetch` stage holds a record stamped after 14:20:00, which in
a backtest must lie in `(14:20:00, 14:20:55]`, so the completeness check passes, and `P_dec` is the close of the 1m bar closing 14:20. It
walks 1m bars from about 12:06 onward using the stops in force from the stored history, then processes the 13:00 and 14:00 closes in order, each with position
state as of its close. The setup has age 80 minutes and `lateness` 81 minutes. With `D_run` of 60 s, `t_dec` is 14:22:05, so the first 1m bar with
`open_time >= 14:22:05.5` opens at 14:23. If the checks pass, the fill is that open. A position's stop update computed from the 13:00 close has `effective_from`
14:23, not 13:00.

### C18. Selection, purge and retirement

**Purge.** Under timing contract item 11, a training setup is removed from `V0` selection when `t_k + H_max` reaches the test block. `H_max` is the maximum
possible hold and not the actual exit, because a rule on the actual exit would make removal depend on the outcome. Under `CYCLE`, add `A_max` plus 2 hours
for one dropped run. Each training simulation's data also ends at the test block's start, and a trade still open then is removed from selection and counted.
So the engine cannot read test data at all, even after more dropped runs than this allowance covers.

| Strategy | `T_d` | `H_max` | `A_max` under `CYCLE` |
|---|---|---|---|
| S01 | 15m, 30m | 12 h, 24 h | Control only, 90 min |
| S02 | 1h | 3 d | 90 min |
| S03 | 1h, 4h | 10 d, 10 d | 90 min, 150 min |
| S04 | 1h, 4h | 4 d, 7 d | 75 min, 150 min |
| S05 | 1h, 4h | 3 d, 6 d | 90 min, 150 min |
| S06 | 5m, 15m | 8 h, 12 h | Control only, 90 min |
| S07 | 1h | 5 d | 90 min |
| S08 | 1h, 30m | 24 h, 24 h | 75 min at 1h. 30m has no `CYCLE` |
| S09 | 1h | 11 h | 75 min |
| S10 | 1h, 4h | 5 d, 10 d | 90 min, 150 min |

**Selection.**

- Parameters are chosen on training folds only, and within one mode. Modes are never compared to pick a configuration.
- For a live-eligible strategy, selection is among its configurations that can run live, under `C-LATE`, on `Result_B`, using the mean over the declared seed list in C17.
- S01 and S06 cannot run live, so they select under `IDEAL-1M`.
- A configuration that cannot run live is a labelled comparison report. It cannot be selected, and its runs still count as trials. This applies to S08 at 30m.

**Dropping or retiring.**

- A decision to drop or retire a stream or a configuration is logged in the trial registry, with the data it used.
- A comparison that picks a configuration uses training folds only.
- A retired stream stays in the portfolio record up to its retirement date. Survivors are quoted only on later blocks, and as survivors.
- A new document version counts as new trials.

## 6. Evidence grades

| Grade | Meaning here |
|---|---|
| `LITERATURE` | A paper I read, at least its abstract, tests this rule or a close proxy of it |
| `PRACTITIONER` | No such paper found, but a practitioner source I read reports a test with a stated method |
| `NONE` | I found no test, only definitions and claims |

The grade describes the rule as written. Evidence for a nearby mechanism is listed separately, because a
paper on FX order clusters does not test a 15-minute crypto trade. A popular idea graded `NONE` is a
finding, not an omission.

## 7. Sources I opened

"Full text" means I read the paper's methods and results. "Abstract" means I read only the abstract or
listing page, and any claim from that source is limited accordingly.

**Technical rules and multiple testing**

| Source | Read |
|---|---|
| [Sullivan, Timmermann, White (1999), data snooping and the bootstrap](https://ideas.repec.org/p/fmg/fmgdps/dp303.html) | Abstract |
| [Bajgrowicz, Scaillet (2012), false discoveries and costs](https://econpapers.repec.org/RePEc:eee:jfinec:v:106:y:2012:i:3:p:473-491) | Abstract |
| [Hudson, Urquhart (2021), technical trading and cryptocurrencies](https://ideas.repec.org/a/spr/annopr/v297y2021i1d10.1007_s10479-019-03357-1.html) | Abstract |
| [Brown, Goetzmann, Kumar (1998), the Dow Theory](https://econpapers.repec.org/RePEc:fth:nystfi:98-013) | Abstract |
| [Fang, Jacobsen, Qin, Bollinger Bands, via CXO Advisory](https://www.cxoadvisory.com/big-ideas/when-bollinger-bands-snapped/) | Secondary summary only |
| [Zarattini, Pagani, Barbon, crypto trends, via CXO Advisory](https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/) | Secondary summary only |

**Support, resistance and order clusters**

| Source | Read |
|---|---|
| [Osler (2000), support for resistance](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html) | Full text, to Table 8 |
| [Osler (2001, later Journal of Finance 2003), currency orders](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html) | Full text, sections I and II |
| [Osler (2002, later JIMF 2005), price cascades](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.html) | Abstract and introduction |
| [Chung, Bellotti (2021), support and resistance levels](https://ar5iv.labs.arxiv.org/html/2101.07410) | Full text, through a summary of the HTML version |
| [Garzarelli et al. (2014), memory effects](https://ar5iv.arxiv.org/html/1110.5197) | Full text, through a summary of the HTML version |
| [Kavajecz, Odders-White (2004), technical analysis and liquidity provision](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html) | Abstract. This listing names the first author only |
| [Bouchaud, Farmer, Lillo (2008), how markets slowly digest supply and demand](https://ar5iv.labs.arxiv.org/html/0809.0822) | First part of the review |
| [Brunnermeier, Pedersen (2005), predatory trading](https://econpapers.repec.org/RePEc:bla:jfinan:v:60:y:2005:i:4:p:1825-1863) | Abstract |
| [Grinblatt, Han (2005), prospect theory and momentum](https://ideas.repec.org/a/eee/jfinec/v78y2005i2p311-339.html) | Abstract |

**Crypto microstructure**

| Source | Read |
|---|---|
| [Hansen, Kim, Kimbrough, periodicity in volatility and liquidity](https://ar5iv.labs.arxiv.org/html/2109.12142) | Full text, through a summary of the HTML version |
| [Baur et al. (2019), time-of-day effects](https://econpapers.repec.org/RePEc:eee:finlet:v:31:y:2019:i:c:p:78-92) | Abstract |
| [Shen, Urquhart, Wang (2022), intraday momentum](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/) | Abstract |
| [Schatzmann, Haslhofer, disposition effect in Bitcoin](https://ar5iv.labs.arxiv.org/html/2010.12415) | Full text, through a summary of the HTML version |
| [Cheng et al. (2021), liquidation and leverage](https://ar5iv.labs.arxiv.org/html/2102.04591) | Full text, through a summary of the HTML version |
| [Garcia Seuma (2026), liquidation cascades](https://ideas.repec.org/p/arx/papers/2608.03616.html) | Abstract |
| [Cong et al. (2023), crypto wash trading](https://nber.org/papers/w30783) | Abstract |
| [Makarov, Schoar (2020), trading and arbitrage](https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:2:p:293-319) | Abstract |
| [Urquhart (2017), price clustering in Bitcoin](https://econpapers.repec.org/RePEc:eee:ecolet:v:159:y:2017:i:c:p:145-148) | Abstract |
| [de Sousa Filho et al., stylized facts of Bitcoin returns](https://ar5iv.labs.arxiv.org/html/2004.05870) | Full text, through a summary of the HTML version |
| [Binance, funding rates](https://www.binance.com/en/support/faq/detail/360033525031) | Official help page |
| [GitHub Actions, schedule event](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) | Official documentation, schedule section |

**Practitioner and vendor material**

| Source | Read |
|---|---|
| [Bulkowski, pivot points](https://thepatternsite.com/PivotPoints.html) | Full page |
| [Holmberg, Lönnbark, Lundström (2012), opening range breakout](https://swopec.hhs.se/umnees/abs/umnees0845.htm) | Abstract. This one is academic |
| [Zarattini, Barbon, Aziz, opening range breakout](https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/) | Authors' summary page, promotional in tone |
| [Replication of the opening range paper on five index CFDs](https://www.mql5.com/en/blogs/post/776235) | Full post, not peer reviewed |
| [Zarattini, Aziz, VWAP](https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/) | Authors' summary page |
| [Thinkorswim, anchored VWAP study](https://toslc.thinkorswim.com/center/reference/Tech-Indicators/studies-library/A-B/AnchoredVWAP) | Vendor documentation, no formula given |
| [CQG, market profile value areas](https://help.cqg.com/cqgic/25/Documents/marketprofilevalueareasmpva.htm) | Vendor documentation |
| [El Trader Financiado, volume profile](https://www.eltraderfinanciado.com/en/blog/volume-profile) | Blog, gives no method for the figures it quotes |
| [Elite Trader thread on market profile](https://elitetrader.com/et/threads/trading-with-market-profile.9727/post-598444) | Forum thread |
| [LuxAlgo, supply and demand zones](https://www.luxalgo.com/library/concept/supply-and-demand-zones.md) | Vendor education, no statistics |
| [LuxAlgo, liquidity sweep](https://www.luxalgo.com/library/concept/liquidity-sweep.md) | Vendor education, no statistics |
| [Smart Money Concepts, BOS and CHoCH](https://smartmoney.gitbook.io/smart-money-concepts/definitions/bos-and-choch) | Vendor education, no statistics |
| [MQL5, statistical validation of supply and demand zones](https://www.mql5.com/en/articles/20904) | Full article. Measures candle geometry, not outcomes |
| [Alphaex Capital, fair value gaps](https://www.alphaexcapital.com/smart-money-concepts/fair-value-gap-explained) | Broker review |
| [Curupira, fair value gap magnetism](https://curupira-blog.pages.dev/blog/fvg-magnetism-fair-value-gaps) | Blog |

### `UNVERIFIED`

- **Brian Shannon's book on anchored VWAP.** I could not read it, so its rules are not used as a source.
- **Steidlmayer and Dalton on market profile.** The originals were not available to me. The "80 percent
  rule" is known to me only from secondary pages. NexusFi's article refused access.
- **A TradingView "sweep radar" description.** A search snippet reports that a raw sweep showed no
  reversal edge out of sample on top coins, with a lean to continuation. The page I could open was cut off
  before that text, and no sample or method was visible. It is noted in S06 and marked as such.
- **Who actually uses floor pivots in crypto.** I found no data on it, and the coordination argument is
  my judgement.
- **Post-2021 stability of the seasonal pattern.** Hansen et al.'s main sample ends in 2021. Spot ETFs and
  venue changes since then may have shifted it, which is why S09 refits the profile by block.
- **Exchange bar boundaries.** From memory, venues label bars as `[open, close)`, while the charter says
  `(open_time, close_time]`. The official Binance page I tried did not show kline fields. `data-steward`
  should confirm and map this at G1 on the chosen source, since treating a bar's open-time label as its
  knowable time would be a one-bar leak.
- **All statements in sections 9 and 13 of each document about typical BTC and ETH behaviour and
  typical stop sizes.** These are my trading judgement unless a source is linked. They are not measured.

## 8. Open questions for the project manager and leak auditor

### Closed

| Earlier question | Closed by |
|---|---|
| 1. Rolling normalisers under timing item 10 | Charter item 10 now separates fixed-window indicators from fitted objects. See [C12](#c12-indicators-and-frozen-values) |
| 2. Size against `R` under section 7 rule 4 | Charter rule 4 now rules on this. See [C6](#c6-entry-fill-r-and-size) and [C10](#c10-accounting) |
| 3. Maximum hold in `V0S` | The charter's variant table now includes a fixed maximum hold. See [C13](#c13-v0s-control) |
| 5. Paper stops between runs | Charter item 13 now models them as resting orders, with reports saying so. See [C17](#c17-hourly-live-cycle) |
| 6. Book features on a live position | Charter section 2 now has `.L` and `.R` kinds, and the data center document limits live gates to trades and candles |
| 7. Timely events in channel posts | Charter section 8 now requires the time of the event and the time the run detected it on each post |
| 9. State between runs in a public repository | `08_DATA_CENTER.md` section 5 keeps it in the Actions cache, with a deterministic rebuild or `DATA_GAP` |
| 10. Role file | The role file now lists section 14 |

### Still open

1. **`VWAP` data tier.** The charter places VWAP in tier `T1`. S07 needs `T1` for its true value and allows a labelled `T0-APPROX` for cross-checks
   only. This stands unless someone objects to keeping that cross-check.
2. **Scheduled job continuity.** GitHub's documentation says scheduled workflows in public repositories are disabled after 60 days with no repository
   activity. `08_DATA_CENTER.md` expects result commits to keep it active, "to be confirmed in practice". `app-builder` should confirm this, and should
   alert if a run has not happened.
3. **`docs/02_features/` depends on text changed here.** `feature-integrator` should conform it. `GATE_SPEC` still has: a fill at or beyond `S0` being cancelled,
   the `t_last` clock in place of the run clock in C17, `P_dec` and `t_dec` as they stood in the old step 4, updates acting from `t_dec + latency`, and objectives in
   net `R`, where charter rule 4 asks for `Result_B`. Its purge rule uses a label interval, where this index uses `H_max`. Links to the renamed C4 and C12 headings
   may also need updating.
4. **Fold plan.** `GATE_SPEC` marks its fold plan as to be confirmed once `V0` results exist. A fold plan chosen after seeing results would be selection on them,
   and it should be fixed before the first `V0` run. S09's calendar in [C12](#c12-indicators-and-frozen-values) does not depend on it.
5. **Proof of freezing.** The auditor notes that nothing shows the frozen constants were set without sight of outcomes. A hash of these documents committed before
   the first run would make that checkable. `project-manager` to decide.
6. **Venue.** Under `D-01` and `D-17`, the research source and venue are undecided. Funding schedules, bar labels and tick sizes must be read from the chosen source.
7. **Trade feed values.** A marked placeholder in [C17](#c17-hourly-live-cycle), re-audit condition C-10 as restated. It waits for the source decision, and no `CYCLE` run of any
   strategy may start until it is filled.

Conditions C-3, C-4, C-5 and C-7 of the re-audit have other owners and are not settled here. Questions 4 and 5 above are the same matters as C-7 and C-5.
