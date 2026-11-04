# S03 Market structure, BOS and CHoCH

Status: revised after the leak audit of 2026-11-04, awaiting re-audit. Not tested. Tier `T0`. Default `T_d` 1h. Long and
short. Live-eligible at 1h and 4h, see section 14.
Common rules C1 to C18 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

An uptrend is a sequence of higher highs and higher lows. A close above the last confirmed swing high extends
it, a break of structure (BOS). A close below the last confirmed higher low is the first evidence that it has
ended, a change of character (CHoCH). This is old Dow Theory in current vocabulary.

**Who is on the other side.** Traders fading the trend, whose stops sit just beyond the last swing high.
Perpetual futures add forced flow: a study of BitMEX perpetuals put average daily forced liquidation at 3.51
percent of open interest for longs and 1.89 percent for shorts, with very high implied leverage among those
liquidated ([Cheng et al.](https://ar5iv.labs.arxiv.org/html/2102.04591)). A break of an obvious swing may
therefore push out leveraged positions and extend the move for a while.

**How much of this is folklore.** The vocabulary is mostly vendor material. Every chart looks structured in
hindsight, because swing points are chosen after the fact. A causal version must wait for confirmation, enter
late, and accept a stop far from the entry. The case for this strategy is only the general persistence of
trends, and that case is weak for BTC at short horizons.

## 2. Evidence

**Grade for the rule: `NONE`.** My search returned only vendor indicator pages. None had a random baseline, a
significance test or an out-of-sample test.

| Source | What it shows | Limits |
|---|---|---|
| [Smart Money Concepts, BOS and CHoCH](https://smartmoney.gitbook.io/smart-money-concepts/definitions/bos-and-choch) | Definitions: BOS continues the trend, and CHoCH needs a body close beyond the higher low | No test or statistics. Recommends a commercial indicator |
| [Brown, Goetzmann, Kumar](https://econpapers.repec.org/RePEc:fth:nystfi:98-013) (adjacent) | Hamilton's Dow Theory timing, 1902 to 1929, showed positive risk-adjusted returns on re-analysis | US stocks, editorial calls, daily or slower. Abstract only |
| [Zarattini, Pagani, Barbon, via CXO](https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/) (adjacent) | A long-only ensemble of daily close breakouts with a midpoint trailing stop is reported positively on crypto | Long only, daily, multi-asset. I read a secondary summary only, and in-sample status is unclear |
| [Hudson and Urquhart](https://ideas.repec.org/a/spr/annopr/v297y2021i1d10.1007_s10479-019-03357-1.html) (adjacent) | Of nearly 15,000 daily rules, none showed predictability for Bitcoin in the out-of-sample period, though other coins did | Daily rules. Abstract only. Directly unfavourable for BTC |
| [Shen, Urquhart, Wang](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/) (adjacent) | Bitcoin's first half-hour return, by volume clock, predicts the last half-hour | A different mechanism. Abstract only |
| [Sullivan et al.](https://ideas.repec.org/p/fmg/fmgdps/dp303.html), [Bajgrowicz and Scaillet](https://econpapers.repec.org/RePEc:eee:jfinec:v:106:y:2012:i:3:p:473-491) | Multiple testing and low costs remove most of the apparent value of simple rules | Daily DJIA. Abstracts only |

**Reading.** Trend following has some support at daily and slower horizons on some assets, and BTC out-of-sample
evidence is poor. Nothing tests swing-based BOS rules at 1h or 4h.

## 3. Definitions

**Swings.** `Sigma(Lf, Rt, a)` from [C4](00_INDEX.md#c4-swing-pivots-and-registers), default `Lf = 5`, `Rt = 3`, `a = 1.0`, on
`T_d`. The higher-timeframe list `Sigma_H` uses the same parameters on 4h bars if `T_d = 1h`, and on UTC daily
bars if `T_d = 4h`. Each list's amplitude test uses `ATR` on that list's own timeframe, at the confirmation bar. Both
lists are read as of the time in question, under C4.

**Break band.** `b_k = 0.10 * ATR_k`. Breaks are close-based, and a wick never breaks structure.

**Structure state machine.** Run at each close, after adding any swing confirmed at that close:

```text
SH = latest swing high in Sigma as of t_k, if it has no broken_at
SL = latest swing low in Sigma as of t_k, if it has no broken_at

if SH exists and C_k > SH.price + b_k:
    SH.broken_at = t_k
    if state == UP: event = BOS_UP; bos_count = bos_count + 1
    else:           event = CHoCH_UP; state = UP; bos_count = 0

if SL exists and C_k < SL.price - b_k:
    SL.broken_at = t_k
    if state == DOWN: event = BOS_DOWN; bos_count = bos_count + 1
    else:             event = CHoCH_DOWN; state = DOWN; bos_count = 0
```

Initial `state` is `NONE`, and the first break of either kind is treated as a CHoCH, with no trade.

**Higher low.** `SL_last` and `SL_prev` are the two latest swing lows in `Sigma` as of `t_k`, whether broken or not. A higher
low means `SL_last.price > SL_prev.price`, with `SL_last` confirmed before the BOS bar.

**Leg.** `Leg = SH.price - SL_last.price`, where `SH` is the swing high just broken.

**Chop count.** The number of CHoCH events, either direction, in the 72 bars ending at `k`.

## 4. Knowable times

| Object | Knowable at |
|---|---|
| Swing at bar `i` | `t_(i+Rt)`, never `t_i` |
| Entry in `Sigma`, including replacements | `valid_from` is its confirmation time. A replacement sets the old entry's `valid_to` to that time and changes nothing earlier |
| BOS, CHoCH, `state` | The close that causes them |
| `Sigma_H` swing | Confirmation on that higher timeframe's closed bars |
| `Leg`, `T1`, `T2` | `t_k`, recomputed at each later BOS close |
| Stop steps | The confirmation or BOS close, effective next bar |

## 5. Setup rules

**Long.** At `t_k`, all of the following:

| # | Condition |
|---|---|
| a | `BOS_UP` on bar `k`, with `bos_count <= max_bos` (default 2) since the last `CHoCH_UP` |
| b | Higher low exists |
| c | `H_k - L_k <= 3.0 * ATR_k`: do not chase a climax bar |
| d | `C_k - SL_last.price <= 3.5 * ATR_k`: not too extended |
| e | Chop count is at most 2 |
| f | `VR_k <= 2.0` |

**Short.** The exact mirror, using `BOS_DOWN`, lower high and `SH_last`. No asymmetry in `V0`, although crypto's
long-run drift is upward and this should be reported per side.

A `CHoCH` alone is not an entry. It flips the state and enables the next BOS. This gives up the best price, on
purpose, because most such flips are noise.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | Broken `SH` and `SL_last` |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 3 bars after `t_k` |

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency` on the BOS close, per [C6](00_INDEX.md#c6-entry-fill-r-and-size).

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
k_s      = 0.30 * clip(VR_k, 0.8, 1.5)
S_struct = SL_last.price - k_s * ATR_k
S0       = min(S_struct, C_k - R_min(1.0))
```

Skip if `C_k - S0 > 4.0 * ATR_k`.

### 7.2 Stop updates

Schedule: only at `T_d` closes, when the event below occurs. All go through
[C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Rule | When | `S_cand`, long |
|---|---|---|
| Higher-low step | A swing low confirmed at this close, above the previous swing low | `SL_new.price - 0.30 * clip(VR_b, 0.8, 1.5) * ATR_b` |
| BOS lock | `BOS_UP` at this close, broken swing `SH` | `SH.price - 1.0 * ATR_b` |
| Climax tighten | `H_b - L_b >= 3.0 * ATR_b` and `CLV_b >= 0.80` | `L_b - 0.25 * ATR_b` |
| Break-even | `T1` filled | `BE+` |

### 7.3 Target logic

Candidates at `t_k`: the measured move `MM = SH.price + 1.618 * Leg`, and the nearest unbroken swing high in
`Sigma_H` above `C_k`, read as of `t_k`. A swing in `Sigma_H` gets its `broken_at` at a close of that list's own timeframe beyond its price by
`0.10 * ATR` on that timeframe.

- `T1` is the lowest candidate at or above `C_k + 1.25 * (C_k - S0)`. If there is none,
  `T1 = C_k + 1.5 * (C_k - S0)`.
- `T2 = SH.price + 2.618 * Leg`.

**Recompute** at each `BOS_UP` close after entry, using the new `SH` and `Leg`. The threshold for `T1`, if unfilled,
becomes `fill + 1.25 * R`. `T2` is never set below `C_b + 0.5 * ATR_b`. Targets may move in either direction. The
Fibonacci ratios have no evidential standing. They are only pre-declared distances in units of the last leg.

### 7.4 Scale-out

30 percent at `T1`, the rest at `T2`. A small first scale-out suits a trend trade, because most of the result, if
any, comes from the few long runs.

### 7.5 Regime scaling

- Stop buffers scale with `VR`, as in 7.1 and 7.2.
- A chop count above 2, or `VR_k > 2.0`, blocks new entries.
- Swing amplitude `a * ATR` adapts the definition of a swing to the current volatility, so a quiet market does not
  produce a flood of tiny swings.

### 7.6 Floors

`R_min(1.0)` from [C9](00_INDEX.md#c9-floors). It rarely binds here because structure stops are wide.

### 7.7 Time stop

| `T_d` | Stall exit: no BOS since entry and `C_b < fill + 1R` at | Absolute limit | `V0S` `H` |
|---|---|---|---|
| 1h | `n = 30` | `n = 240` | 120 |
| 4h | `n = 12` | `n = 60` | 30 |

### 7.8 Invalidation

`CHoCH_DOWN` at a close: exit at the next open. The close breaks the same swing that the stop sits behind, so this
usually acts before the stop. The stop remains for intrabar shocks.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both stop and target, the stop is taken. A swing
confirmed at a close never acts on any earlier bar, even though the swing's extreme lies several bars back.

### 7.10 `V0S` control

`S0` from 7.1, `m = 3.0`, `H` from the table in 7.7.

### 7.11 Why this model suits this strategy

A trend trade fails when the trend ends, and the definition of that end is already written in the entry logic: a
close below the last confirmed higher low. So the stop steps to each confirmed higher low, in the same units as the
thesis. Confirmation lag is the weakness, because the real low is `Rt` bars old before it can be used. The BOS lock
covers that gap with a level that is known at once. The climax rule exists because crypto trends often end in a
vertical squeeze, where the stop at the last swing would give back far too much. A distant target lets the rare long
run pay for the many small failures, and recomputing it at each BOS keeps it tied to the current leg.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. `T_d = 1h`, `ATR = 300`, `VR = 1.0` held flat, so `b = 30` and
the stop buffer is 90.

Earlier confirmed history: `CHoCH_UP` at 10:00 closed above a lower high. Swing high `SH = 66,500`. Swing low
`SL_last = 65,650`, above `SL_prev = 64,900`. Trigger bar closes 23:00: `O 66,380, H 66,600, L 66,360, C 66,560`, above
66,530, so `BOS_UP` with `bos_count = 1`. `C - SL_last = 910`, within 1,050.

- `S0 = 65,650 - 90 = 65,560`. `C - S0 = 1,000`. `R_min = max(300, 319.5)`, so the structure stop stands.
- `Leg = 850`. `MM = 67,875.3`. `Sigma_H` swing high 67,900. The threshold is 67,810, so `T1 = 67,875.3`.
  `T2 = 68,725.3`.
- `R_dec = 1,000`. The collar is 66,710, and the next open of 66,565 is inside it.
- So `fill = 66,571.7`, `R = 1,011.7`, `BE+ = 66,651.5`.

| `n` | Close | O | H | L | C | Event at this close | Stop after close | `T1` | `T2` |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 00:00 | 66,565 | 66,690 | 66,520 | 66,640 | | 65,560.0 | 67,875.3 | 68,725.3 |
| 2 | 01:00 | 66,640 | 66,820 | 66,610 | 66,790 | | 65,560.0 | 67,875.3 | 68,725.3 |
| 3 | 02:00 | 66,790 | 66,950 | 66,740 | 66,900 | | 65,560.0 | 67,875.3 | 68,725.3 |
| 4 | 03:00 | 66,900 | 67,060 | 66,850 | 66,980 | | 65,560.0 | 67,875.3 | 68,725.3 |
| 5 | 04:00 | 66,980 | 67,100 | 66,870 | 66,930 | Extreme of a swing high, not yet known | 65,560.0 | 67,875.3 | 68,725.3 |
| 6 | 05:00 | 66,930 | 66,950 | 66,680 | 66,720 | | 65,560.0 | 67,875.3 | 68,725.3 |
| 7 | 06:00 | 66,720 | 66,760 | 66,560 | 66,610 | | 65,560.0 | 67,875.3 | 68,725.3 |
| 8 | 07:00 | 66,610 | 66,700 | 66,530 | 66,660 | Swing high 67,100 confirmed. Low 66,530 printed, not yet known | 65,560.0 | 67,875.3 | 68,725.3 |
| 9 | 08:00 | 66,660 | 66,760 | 66,620 | 66,740 | | 65,560.0 | 67,875.3 | 68,725.3 |
| 10 | 09:00 | 66,740 | 66,830 | 66,700 | 66,800 | | 65,560.0 | 67,875.3 | 68,725.3 |
| 11 | 10:00 | 66,800 | 66,930 | 66,770 | 66,900 | Swing low 66,530 confirmed. Step: `66,530 - 90` | 66,440.0 | 67,875.3 | 68,725.3 |
| 12 | 11:00 | 66,900 | 67,090 | 66,880 | 67,060 | | 66,440.0 | 67,875.3 | 68,725.3 |
| 13 | 12:00 | 67,060 | 67,240 | 67,030 | 67,210 | `BOS_UP` over 67,100. Lock: `67,100 - 300`. `Leg = 570`. `T1`: lowest of 67,900 and 68,022.3 above 67,836.3 | 66,800.0 | 67,900.0 | 68,592.2 |
| 14 | 13:00 | 67,210 | 67,420 | 67,180 | 67,390 | | 66,800.0 | 67,900.0 | 68,592.2 |
| 15 | 14:00 | 67,390 | 67,640 | 67,350 | 67,610 | | 66,800.0 | 67,900.0 | 68,592.2 |
| 16 | 15:00 | 67,610 | 67,930 | 67,580 | 67,880 | `H > T1`: 30% out at 67,900 (`+1.31R`). `BE+` is below the stop | 66,800.0 | filled | 68,592.2 |
| 17 to 21 | 16:00 to 20:00 | | 68,520 max | | 67,870 at 20:00 | The high of 68,520 is bar 19, 18:00 close | 66,800.0 | | 68,592.2 |
| 22 | 21:00 | 67,870 | 68,000 | 67,790 | 67,960 | Swing high 68,520 confirmed | 66,800.0 | | 68,592.2 |
| 23 | 22:00 | 67,960 | 68,060 | 67,920 | 68,030 | | 66,800.0 | | 68,592.2 |
| 24 | 23:00 | 68,030 | 68,130 | 67,990 | 68,090 | | 66,800.0 | | 68,592.2 |
| 25 | 00:00 | 68,090 | 68,210 | 68,060 | 68,180 | Swing low 67,790 confirmed. Step: `67,790 - 90` | 67,700.0 | | 68,592.2 |
| 26 | 01:00 | 68,180 | 68,230 | 67,860 | 67,900 | | 67,700.0 | | 68,592.2 |
| 27 | 02:00 | 67,900 | 67,950 | 67,720 | 67,740 | `C < 67,760`: `CHoCH_DOWN`. Stop 67,700 not touched. Exit pending | exit next open | | |
| 28 | 03:00 | 67,735 | | | | Pending exit is first in the loop: 70% out at 67,735 (`+1.15R`), whatever the bar does later | closed | | |

Bars 17 to 21, for checking the swings: opens 67,880, 68,140, 68,380, 68,290, 68,060. Highs 68,180, 68,420, 68,520,
68,330, 68,120. Lows 67,850, 68,090, 68,220, 68,010, 67,820. Closes 68,140, 68,380, 68,290, 68,060, 67,870.

Result before costs: `0.3 * 1.31 + 0.7 * 1.15 = 1.20R`. `Result_B = (0.3 * 1,328.3 + 0.7 * 1,163.3) / 1,000 = 1.21`. `R` stayed
1,011.7 throughout. This path was chosen to
exercise the rules and does not represent a typical outcome. Notice bar 8: the low that will become the new stop has
printed, yet the stop stays at 65,560 until bar 11. Any rule that moved it earlier would be a repaint.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `T_d` | 1h, 4h | The strategy's holding time suits both. 4h has fewer false swings and less cost in `R` |
| `(Lf, Rt)` | (5, 3), (8, 4) | Faster and slower swings. A larger `Rt` means later knowledge |
| `max_bos` | 1, 2 | Whether the second BOS adds trades or only adds late entries |

Total: 8 configurations. Amplitude `a` and all stop and target constants are frozen.

## 9. BTC and ETH notes

- Definitions scale with `ATR`, so the same constants apply.
- ETH often makes its structure break after BTC, in my judgement. A BTC `BOS_UP` followed by an ETH `BOS_UP` a few
  hours later is largely the same bet, and layer 5 should treat it so.
- The evidence for BTC is the weaker: Hudson and Urquhart found no out-of-sample predictability for Bitcoin while
  finding it in other coins. Report BTC and ETH separately and do not pool them to hide a BTC failure.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Sustained multi-day trends | Should work, if it works anywhere | Result concentrated in a few long trades |
| Ranges | Should fail by whipsaw | Chop count high, many `CHoCH` exits near `-1R` or less |
| V-shaped reversals | Should fail: no higher low exists until well after the turn | Trade starts late in a move that is ending |
| Squeeze tops | Partly handled by the climax rule | Compare exits on climax tighten against the counterfactual without it |
| Any regime | Should beat random entries, drawn over bars that pass the non-signal filters c, d, e and f with the block's real long and short share, with the stop from the list as of that bar. No swing was just broken at such a bar, so `SH` and `Leg` do not exist, and the placebo's targets are `T1 = C_k + 1.5 * (C_k - S0)`, the fallback in 7.3, and `T2 = C_k + 3.0 * (C_k - S0)`. They are recomputed as usual if a real `BOS_UP` then occurs. A placebo long may be open while `state` is `DOWN`, so its 7.8 exit fires on either `CHoCH_DOWN` or `BOS_DOWN` | [Placebo](00_INDEX.md#c15-placebo-control) |

## 11. Flow hooks

Questions for `feature-integrator`.

- **Entry gate:** did the BOS close come with sustained aggressive buying, or with a thin push that swept a few stops?
- **Entry gate:** did the pullback that formed the higher low have weak selling flow?
- **Early exit:** does flow turn against the trade before the `CHoCH` close can be seen?
- **Stop tightening:** between a real low and its confirmation, can flow justify tightening earlier? Tightening is
  allowed, and it needs no future data, as flow is knowable at the time.
- **Exhaustion:** does a climax bar coincide with one-sided forced flow that then stops?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Swing used at its extreme | At 07:00 in the example, using the 66,530 low as support | Knowable at 10:00, the confirmation close |
| Repainted `Sigma` | A later, more extreme swing replacing an earlier one, then used on bars before that replacement. A final list joined by knowable time also loses the replaced swing on those bars, and passes the timestamp audit | Replacements take effect at their confirmation time, and every read is `valid_from <= t < valid_to`. A final list is forbidden as an input, and truncation invariance is required |
| Stop on the confirmation bar | Stop raised at the 10:00 close acting inside the bar closing 10:00 | Effective from the next bar |
| Higher-timeframe swing merged early | A 4h swing used before its 4h confirmation | Uses only closed bars of that timeframe, with the same as-of read |
| Wick break counted | Using `H > SH` to declare BOS | Close-based only, with band |
| Fitting amplitude after seeing trends | Re-tuning `a` | Frozen and not in the grid |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 40 to 100 trades per year across BTC and ETH at 1h, and about a
third of that at 4h.

**Cost.** Typical `R` about 150 to 250 bp at 1h, and 300 to 500 bp at 4h, by my judgement. At the illustrative
`RT = 12 bp`, cost is about `0.05R` to `0.08R` at 1h and less at 4h. Fees are not what kills this. It dies on hit
rate and on the late entry, since entering at a BOS close with the stop behind a confirmed swing often puts `T1` only
about `1.3R` away. Funding does matter, because holding periods cross many settlements, every 8 hours on a schedule such
as Binance's default. Report funding separately for this strategy.

## 14. Live on an hourly cycle

**Verdict: eligible. Lowest live-eligible `T_d`: 1h. 4h also eligible.** Confirmation lag already makes this a slow
strategy, and a trend thesis held for days can absorb a late hour.

**Late entries.** General checks are in [C17](00_INDEX.md#c17-hourly-live-cycle). Values for this strategy:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 90 minutes at 1h, 150 minutes at 4h, after the BOS close |
| Path | `S0` or `T1` touched, or a `CHoCH_DOWN` close since `t_k`, voids the setup |
| Chase | `abs(P_dec - C_k) <= 1.0 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(1.0)` and `4.0 * ATR_k` |
| Extension | `P_dec - SL_last.price <= 3.5 * ATR_k`, the same limit as setup rule d, now at the live price |
| `RR_late` | `T1 - P_dec >= 1.0 * (P_dec - S0)` |
| Thesis | `P_dec > SH.price`: the broken level must still be below the price |

Using the example in 7.12, with `C_k = 66,560`, `S0 = 65,560`, `SL_last = 65,650`, `T1 = 67,875.3`, `ATR = 300`:

- `P_dec = 66,700`: chase 140, risk 1,140 against 1,200, extension 1,050 against 1,050, reward 1,175. All pass.
- `P_dec = 66,800`: risk 1,240 exceeds 1,200. Result: `STALE_SETUP`, reason `RISK`.

**Stops and targets between runs.**

- Touches between runs are resolved from 1m bars at the next run, with both `event_time` and `detection_time`
  recorded. Inside one 1m bar, the stop is first.
- Swing confirmation lag and cycle lag add up. In the example, the 66,530 low is confirmed at the 10:00 close, and the
  new stop acts only from the `effective_from` of the run that processes it, for example 10:21. The earlier stop of 65,560
  remains in force during that gap, and nothing is applied retroactively.
- Steps, BOS locks, climax tightens and target recomputes are computed at each processed `T_d` close, in time order,
  and act from `effective_from`. A dropped run can bring two closes together, and both go through the ratchet.
- A `CHoCH_DOWN` exit fills after the run that saw it. On a late run the price may have fallen further by then. If it
  touched the stop first, the walk in C17 has already closed the trade at the stop.
- At 4h, the runs between closes resolve touches and compute no model update. Flow may still act at them, under C17.
- The `fill + 1.25 * R` threshold in 7.3 is fill-based, so under `.T` it follows the
  [rule against a later fill raising a target](00_INDEX.md#c17-hourly-live-cycle).
- Stops only tighten: the `P_dec` clamp in C17 can reduce a candidate, and the ratchet then keeps the old stop.

**Backtest reproduction.** `CYCLE` under [C17](00_INDEX.md#c17-hourly-live-cycle), with `C-LATE` for selection. Closes are
processed in time order during each simulated run, and `Sigma` uses values at `t_(i+Rt)`, including `ATR` for the amplitude
test, so the list never depends on run timing. Report counts by
`STALE_SETUP` reason, and compare `IDEAL` and `CYCLE` on the share of exits by `CHoCH` and by stop. I expect a small cycle
cost at 4h, and a larger one at 1h from extension rejections. That is untested.
