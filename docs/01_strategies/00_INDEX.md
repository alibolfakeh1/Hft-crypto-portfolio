# Candle strategy index

Status: draft for leak audit. Date: 2026-11-04. Owner: `strategy-architect`.

**Nothing in this folder has been tested.** No document claims or implies that any strategy is
profitable. Every frequency, stop distance and cost figure here is a design estimate or an arithmetic
illustration, to be replaced by measured values at gate G3. Worked examples use invented prices.

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
comes back high at G4, S05 is the one to retire.

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
timeframe that can never run live is a poor use of trials. The delay scenarios in
[C17](#c17-hourly-live-cycle) are stress reports on a chosen configuration. They are logged, but they are
not used to pick parameters beyond the one selection scenario named there.

## 5. Common conventions

Every strategy document uses the rules below. They are written once here so they cannot drift. A
strategy document may add to them and must state any exception explicitly.

C6 and C7 describe the `IDEAL` simulation, where a decision happens exactly at the bar close and fills at
the next open. [C17](#c17-hourly-live-cycle) describes the `CYCLE` simulation, which is what the live paper
record actually does. Sections 1 to 13 of each document, including the worked examples, are written in
`IDEAL` terms. Section 14 of each document states how they change under `CYCLE`.

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
- If a bar needed by a formula is missing, the object is not computed and no setup is created. Nothing is
  forward-filled or backfilled. A gap during an open position is logged, and the next available bar is
  processed by [C7](#c7-exit-engine).

### C3. Indicators

All values below are computed from closed bars of the stated timeframe, and each is knowable at the close
of its last input bar.

| Name | Definition |
|---|---|
| `TR_k` | `max(H_k - L_k, abs(H_k - C_(k-1)), abs(L_k - C_(k-1)))` |
| `ATR_k` | Wilder ATR(14) on `T_d`. Seed with the mean of the first 14 `TR`. Then `ATR_k = (13*ATR_(k-1) + TR_k) / 14` |
| `ATRD` | Wilder ATR(14) on UTC daily bars, last completed day only. It changes at 00:00 UTC |
| `VR_k` | `ATR_k / median(ATR_(k-N+1), ..., ATR_k)`, with `N` the number of `T_d` bars in 30 days |
| `SRV_k` | Seasonal relative volume: `V_k / median(V of the same weekly slot in each of the previous 8 weeks)`. If fewer than 4 of those slots exist, `SRV` is undefined and any condition using it fails, so no setup is created |
| `CLV_k` | `(C_k - L_k) / (H_k - L_k)`, or `0.5` if `H_k = L_k` |
| `clip(x, a, b)` | `min(max(x, a), b)` |
| `DayOpen` | Open of the first `T_d` bar of the current UTC day |

### C4. Swing pivots

- `SwingHigh(i; Lf, Rt)` is true when `H_i > max(H_(i-Lf), ..., H_(i-1))` and
  `H_i >= max(H_(i+1), ..., H_(i+Rt))`.
- `SwingLow(i; Lf, Rt)` is true when `L_i < min(L_(i-Lf), ..., L_(i-1))` and
  `L_i <= min(L_(i+1), ..., L_(i+Rt))`.
- The swing is **knowable at `t_(i+Rt)`**, its confirmation time, and never at `t_i`.
- `Sigma(Lf, Rt, a)` is the alternating list of confirmed swings. On confirmation of a swing `X` at time
  `t`, with `last` the current end of the list:

```text
if X has the same type as last:
    if X is more extreme than last: replace last with X
    else: ignore X
else:
    if abs(X.price - last.price) >= a * ATR at t: append X
    else: ignore X
```

Every decision in this list is made at a confirmation time, so the list can be replayed without looking
ahead. A replacement never changes a stop that has already moved.

### C5. Setup object and gate window

A setup is created at the close of the trigger bar `k`, from closed bars only. It holds `side`,
`level_or_zone`, `invalidation` (the initial stop `S0`), `targets`, `created_at = t_k` and `expiry`.

- `V0` sends its entry at `t_k`.
- Flow variants may send `ENTER` from `t_k` until `expiry`. They use the same `S0`. The gate must return
  `EXPIRE` if the price has moved more than `0.5 * ATR_k` from `C_k`, and must refuse entry if
  `abs(price - S0)` is below the floor of [C9](#c9-floors).
- A vetoed or expired setup stays in the record with its `V0` counterfactual.

### C6. Entry, fill, `R` and size

- A decision at `t_k` fills no earlier than `t_k + latency`. In a bar simulation the fill reference is
  `O_(k+1)`. A long pays `O_(k+1) * (1 + slip)`, a short receives `O_(k+1) * (1 - slip)`. If finer data
  exists, use the first trade after `t_k + latency` instead.
- **Entry guard.** Cancel and log `ENTRY_GUARD` if the fill reference is at or beyond `S0`, or if
  `abs(O_(k+1) - C_k) > 0.5 * ATR_k`.
- `R = abs(fill - S0)`. It is fixed at the fill and never changes.
- **Size** is sent at `t_k`, before the fill price is known, so it uses `risk_budget / abs(C_k - S0)`. The
  risk budget belongs to layer 5.
- `V0` uses taker entries only. No strategy here relies on passive fills, so gate G5's passive-fill test
  is not needed for `V0`.

Slippage needs care. Published work finds the largest crypto volatility burst in the first minute of the
hour, with smaller ones at minutes 15, 30 and 45
([Hansen et al.](https://ar5iv.labs.arxiv.org/html/2109.12142)). A decision on a bar close therefore
tends to fill inside that burst, so `slip` must be measured at bar opens and not averaged over all minutes.

### C7. Exit engine

Long side shown. A short is the mirror image.

```text
for each bar b from the fill bar onward, while quantity > 0:
    S = active stop, Ts = active targets        # set at t_(b-1); on the fill bar, S0 and the setup targets
    if b is not the fill bar and O_b <= S:
        exit all at O_b, less stop slippage     # STOP_GAP
    elif L_b <= S:
        exit all at S, less stop slippage       # STOP. The stop is tested first (timing contract, item 8)
    else:
        for each unfilled target Ti in ascending order:
            if H_b > Ti: exit its planned quantity at Ti    # trade-through, no positive slippage
    at t_b, if quantity > 0, in this order:
        1. invalidation rules: if any fires, decide EXIT, filled at O_(b+1)
        2. time stops: same handling
        3. compute stop candidates and target updates, apply C8, log, effective from bar b+1
```

- Same-bar conflicts resolve to the stop, so a bar that touches both records no scale-out. One-minute bars
  may settle the order when both `S` and `Ti` lie inside `[L_b, H_b]`, walking the same loop. If one
  one-minute bar contains both, the stop is first. Updates still take effect only from the next `T_d` bar.
- A target requires a trade through its price by at least one tick. A gap beyond a target fills at the
  target, not at the better open.
- Stop slippage is a separate required configuration value, because stops fill worst during cascades.

### C8. Stop ratchet and `BE+`

Every stop change in every strategy goes through this one rule, so a stop cannot move backward.

```text
long:  S_new = max(S_old, min(S_cand, C_b - 0.10 * ATR_b))
short: S_new = min(S_old, max(S_cand, C_b + 0.10 * ATR_b))
```

If several candidates fire at one close, `S_cand` is the tightest. Flow overlays use the same rule.
`BE+` means break-even plus costs: `fill * (1 + RT)` for a long and `fill * (1 - RT)` for a short.

### C9. Floors

`RT = 2 * (fee_taker + slip)` is the base-case round-trip cost as a fraction of price.

```text
R_min(a) = max(a * ATR_k, 4 * RT * C_k)
S0 (long) = min(S_struct, C_k - R_min(a))
```

The factor 4 limits the base-case cost to about `0.25R` per trade. The value `a` differs by strategy.
`RT` here is frozen at the 1x base case, so the 2x and 3x cost reports change P&L and not the trade list.

### C10. Accounting

`Result_R = sum(f_i * (X_i - fill) / R) - (fees + slippage + funding) / R` for a long, where `f_i` is the
fraction of the original quantity exiting at price `X_i`. Funding is charged at actual settlement times
on positions open at that moment, using the rate published then. No rule may use a future funding rate.
Binance's default for USDT-margined contracts is every 8 hours at 00:00, 08:00 and 16:00 UTC, and it can
differ by contract ([Binance funding](https://www.binance.com/en/support/faq/detail/360033525031)).

### C11. Overlap policy

One open position per strategy and symbol. A setup that arrives while one is open is logged as
`SKIPPED_OPEN` and not traded. Reversing into the opposite side requires a new setup after the position
is flat. Portfolio-level overlap between strategies belongs to layer 5.

### C12. Rolling indicators and fitted objects

A fixed-window statistic computed only from bars at or before `t` (`ATR`, `VR`, `SRV`, percentile ranks)
is treated as an indicator: it has no fitted state and is recomputed causally at each close. A value
estimated across a sample and then applied forward is a fitted object and is frozen at the start of each
walk-forward block. Only one object in this folder is fitted: the seasonal profile of S09. See open
question 1 in [section 8](#8-open-questions-for-the-project-manager-and-leak-auditor).

### C13. `V0S` control

Same setup, same entry, same `S0` and `R` as `V0`. One fixed target at `fill + m*R` (long) or `fill - m*R`
(short), and a fixed maximum hold of `H` bars, closed at the next open. No scale-out, no invalidation, no
update of any kind. Same fees and funding. Each document gives `m` and `H`.

### C14. Event log

Every event is logged with old value, new value, reason, computed-at time and effective-from time:
`SETUP_CREATED`, `ENTRY`, `STOP_UPDATE`, `TARGET_UPDATE`, `SCALE_OUT`, `INVALIDATION`, `TIME_STOP`, `EXIT`,
`ENTRY_GUARD`, `SKIPPED_OPEN`. Under `CYCLE`, also `STALE_SETUP` and `DATA_GAP`, and every event carries
the time fields defined in [C17](#c17-hourly-live-cycle).

### C15. Placebo control

For gates G3 and G4, run each level-based strategy with its levels replaced by random levels drawn at the
same distance distribution, keeping everything else unchanged. This copies the design of
[Osler (2000)](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html), where
arbitrary levels "bounced" 56.2 percent of the time and published levels 60.8 percent. A bounce rate alone
therefore says little, and only the difference from the placebo is informative. For the strategies with
no level (S03, S10), use random entry times with the same stop and target geometry. Placebo runs are
controls and are recorded as such in the trial registry.

### C16. Rounding and arithmetic in examples

Stops and targets round to the instrument tick: a long stop or target rounds down, a short stop or target
rounds up. Worked examples use BTC tick 0.1 and ETH tick 0.01, `fee_taker = 5 bp` and `slip = 1 bp`, so
`RT = 12 bp`. These are **assumptions for arithmetic only**, not venue facts. Binance's fee page refers to
a separate schedule that I could not open. Examples show results in `R` before costs and hold `ATR` flat
unless a table shows otherwise.

### C17. Hourly live cycle

Live paper positions run from GitHub scheduled jobs with no server and no live order book. GitHub states
that scheduled runs can be delayed under load, especially at the top of the hour, and that queued jobs may
be dropped ([GitHub Actions documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)).
It publishes no delay distribution, so nothing here assumes one.

**What a run sees.** Closed 1-minute bars since the last processed minute, trades since then for tier `T1`
strategies, and the committed state from the previous run. It sees no book, so no book feature can gate a
live entry or exit.

**Timeframes.** Under 1h is backtest-only, unless a document justifies otherwise, and none does. The nominal
start is a fixed minute that avoids the top of the hour, such as minute 7.

**Order of work in one run**, for each symbol and strategy:

```text
1. Load state: positions, active stops and targets, last processed minute.
   If any 1m bar between the last processed minute and now is missing, log DATA_GAP.
   Resolve nothing past the gap and take no new decisions for this symbol. Never fill or assume.
2. Resolve any fill left pending by the previous run. Then walk each open position through the new 1m bars
   in time order, using the stop and targets that were active before this run. Same logic as C7 with the 1m
   bar as the bar:
       gap through the stop -> exit at that 1m open
       L_1m <= S            -> exit at S                 # stop first inside one 1m bar
       H_1m > Ti            -> scale out at Ti
3. Build T_d bars from 1m bars. For each T_d bar newly closed, in time order, and for positions still open:
       run invalidation rules and time stops
       compute stop and target updates, carrying each through C8 into the next
       run setup detection
4. Set t_dec = now. P_dec = close of the last completed 1m bar. Commit all decisions to the ledger.
5. Entries and close-based exits fill at the open of the first 1m bar with open_time >= t_dec + latency.
   If that bar does not exist yet, wait up to 2 minutes, otherwise the next run resolves it.
6. New stops and targets take effect from t_dec + latency.
```

**Timing consequences.**

- An update computed from the bar closing at `t_b` is knowable at `t_b`, but is computed at `t_dec` and
  acts only from `t_dec + latency`. The old stop stays in force in between. A stop is never applied
  retroactively over a period in which it did not exist. This satisfies timing contract item 12.
- `C8` gains one clamp under `CYCLE`, since price may have moved after the close:
  `S_new = max(S_old, min(S_cand, C_b - 0.10*ATR_b, P_dec - 0.10*ATR_b))` for a long, mirrored for a short.
  Stops still only tighten.
- Update schedules stay on `T_d` closes, the same as `IDEAL`. On a 4h strategy, the three runs between 4h
  closes only resolve touches. They do not compute updates.
- A close-based exit fills after the run that noticed it. A late run makes the exit later, and this is
  recorded and never hidden. It does not extend the time stop rule: the decision is still due at the same bar.
- `n`, trailing lows and highest highs are based on `T_d` bars. Highest high since entry counts only 1m bars
  at or after the fill.

**Time fields on every event.**

| Field | Meaning |
|---|---|
| `knowable_time` | When the input became knowable, usually a bar close |
| `event_time` | Close time of the 1m bar in which a touch or fill happened, or `t_dec` for a decision |
| `detection_time` | Start of the run that found it |
| `effective_from` | When a new stop or target starts to act |
| `lateness` | `detection_time - knowable_time` |

**Late entries.** A setup is detected at `t_dec`, up to an hour or more after its trigger bar closed at
`t_k`. The trigger, `S0` and targets stay as computed at `t_k`, and are not recomputed for the later price.
Before deciding `ENTER`, all of these must pass, or the setup is logged as `STALE_SETUP` with its reason and
its `V0` `IDEAL` counterfactual:

| Check | Rule |
|---|---|
| Age | `t_dec - t_k <= A_max`, given per strategy |
| Path | No 1m bar between `t_k` and `t_dec` touched `S0` or `T1`, and no `T_d` close in that span fired the strategy's invalidation |
| Chase | `abs(P_dec - C_k) <= chase * ATR_k`, given per strategy |
| Risk | `abs(P_dec - S0)` is at least the setup's `R_min` and at most the strategy's stop cap |
| Reward | `(T1 - P_dec) >= RR_late * (P_dec - S0)` for a long, given per strategy |
| Thesis | Strategy-specific: the price must still be on the correct side of the level or zone |

At fill, the C6 rule that the fill reference must not be at or beyond `S0` still applies, and if it fails the
entry is cancelled. `R = abs(fill - S0)`, fixed from there. Size is sent using `abs(P_dec - S0)`.

**Flow under `CYCLE`.** A gate may only use what a run can see: closed bars and trades since the last run.
It is evaluated at runs only, so `WAIT` means the next run, up to `expiry` and `A_max`. Flow exits follow
step 5 and flow tightening follows step 6.

**Backtest reproduction.** Every live-eligible strategy reports both `IDEAL` and `CYCLE`. `CYCLE` must:

1. Call the same run function as live, one simulated run at a time, on a dataset truncated at `t_dec`.
2. Show the run data only up to `t_dec`, minus a declared data-availability allowance.
3. Build `T_d` bars from 1m bars, and check them against the venue's own bars at gate G1.
4. Draw run times from a declared, seeded scenario:

| Scenario | Delay after the nominal minute | Dropped runs | Use |
|---|---|---|---|
| `C-FAST` | 2 minutes, fixed | None | Upper bound for comparison |
| `C-LATE` | Uniform, 2 to 45 minutes | 5 percent | **Parameter selection** and the headline `CYCLE` result, until measured data replaces it |
| `C-BAD` | Uniform, 2 to 60 minutes | 15 percent | Stress report |
| `C-MEASURED` | Empirical, from real run logs, once at least 30 days exist | Empirical | Replaces `C-LATE` as a new, visibly labelled configuration |

These delay values are my assumptions and are not GitHub figures. Report at least 5 seeds for each random
scenario, with the spread. Selecting a seed is forbidden.

5. For gate G8, replay the live period with the **actual** run timestamps. The trade list must match the
   ledger exactly, and each mismatch goes in the paper versus simulation report.
6. Report the `IDEAL` minus `CYCLE` difference in `R` per trade as the cost of the cycle.

A backtest result quoted beside a live record must be the `CYCLE` one. `IDEAL` is a research measure of the
idea and is never compared with live results.

**Worked timeline.** A 1h setup bar closes at 13:00. The last good run was the 12:07 one. The 13:07 run is
dropped. The 14:07 run starts at 14:21. It walks 1m bars from about 12:07 onward using the stops active since
that run, then processes the 13:00 and 14:00 closes in order. The setup has `lateness` 81 minutes, and passes
or fails the checks using `P_dec` at 14:21. If it passes, the fill is the open of the 14:22 1m bar. A position's
stop update computed from the 13:00 close acts only from about 14:21, not from 13:00.

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
  should confirm and map this.
- **All statements in sections 9 and 13 of each document about typical BTC and ETH behaviour and
  typical stop sizes.** These are my trading judgement unless a source is linked. They are not measured.

## 8. Open questions for the project manager and leak auditor

1. **Timing contract item 10.** It says normalisers and thresholds are fitted on past data and frozen before
   the block. Read literally, a rolling `VR`, `SRV` or percentile rank would break it, because it updates
   inside the block. I treat these as causal indicators under [C12](#c12-rolling-indicators-and-fitted-objects).
   I think that is the right reading, since freezing `ATR` would make no sense, but it should be ruled on.
2. **Charter section 7, rule 4.** Size comes from the initial stop, but the fill is not known when size is
   sent. I split this: size uses `abs(C_k - S0)` and `R` uses the fill. See [C6](#c6-entry-fill-r-and-size).
3. **`V0S`.** The charter gives it a fixed stop and target only. Without a time limit some control trades
   would stay open for a very long time, so I added a fixed maximum hold set at entry. It does not move.
4. **`VWAP` data tier.** The charter places VWAP in tier `T1`. S07 needs `T1` for its true value and allows
   a labelled `T0-APPROX` for cross-checks only.
5. **Paper stops between runs.** The cycle resolves a touched stop or target from 1m bars at its exact level,
   as if a resting order had been working. No such order exists on the paper system. This is fair only if a
   future real system would hold exchange-side stops and targets. Otherwise the live paper record overstates
   what an hourly job could achieve, and should be labelled accordingly.
6. **Charter section 2, layer 2 and tiers `T2` and `T3`.** With no live book, book features can be tested in
   research but cannot gate a live position. `feature-integrator` should mark them as backtest-only.
7. **Charter section 8.** The live view and channel posts were written with timely events in mind. Under the
   cycle every post is at least one run late, and a post may report a stop already hours old. Posts should
   show `event_time` and `detection_time` side by side.
8. **Scheduled job continuity.** GitHub's documentation says scheduled workflows in public repositories are
   disabled after 60 days with no repository activity. `app-builder` should confirm that ledger commits keep
   the schedule alive, and should alert if a run has not happened.
9. **State between runs in a public repository.** Rule 7 in `CLAUDE.md` forbids market data in git. S07 and S08
   need running trade totals or a day's trades across runs, and every strategy needs recent 1m bars. Running
   VWAP totals and profile bins are derived from market data, so `data-steward` should rule on whether they may
   be committed. If not, they must live in a cache, and a run must be able to rebuild them deterministically
   from the venue after a cache miss, or else log `DATA_GAP`.
10. **Role file.** `.claude/agents/strategy-architect.md` lists 13 sections. The owner's requirement adds a
    fourteenth, "Live on an hourly cycle", which every document here has. That file is outside what I may edit.
