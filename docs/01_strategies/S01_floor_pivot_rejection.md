# S01 Floor pivot rejection

Status: revised after the leak audit of 2026-11-04, awaiting re-audit. Not tested. Tier `T0`. Default `T_d` 15m. Long and short. Backtest only: not
eligible for the hourly live cycle, see section 14.
Common rules C1 to C18 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

Floor pivots are a formula applied to the prior period's high, low and close. Their only special property
is that many charts show the same numbers. In BTC and ETH most default charts use UTC days, so the
candidate coordination point is the UTC pivot set.

**Who is on the other side.** A late momentum taker pushes into a level where limit bids and take-profit
orders may sit. Published FX order data shows take-profit orders clustering at widely watched prices and
tending to reflect trends ([Osler 2001](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html)).
If some crypto traders place resting orders or take profit at pivots, a fast push into one can stall for
a short time while that interest fills.

**How much of this is folklore.** A large part. I found no data on how many crypto traders use pivots. A
UTC day has no natural meaning in a 24/7 market, since no one closes a book at 00:00. The close of that
day also prints during a known burst of volatility around 00:00 UTC, so `C` is a noisy input. The most I
would claim is a brief reaction, measured in minutes, and this strategy is designed around that limit.

## 2. Evidence

**Grade for the rule: `PRACTITIONER`.**

| Source | What it shows | Limits |
|---|---|---|
| [Bulkowski, pivot points](https://thepatternsite.com/PivotPoints.html) | On one-minute data for 55 stocks, significant turns fell in a 3-cent band around standard pivots 51 to 60 percent of the time. Fibonacci pivots scored 28 to 36 percent | Stocks, not crypto. Narrow-range days excluded. Measures a reaction, not profit. No random-level control |
| [Osler 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html) (adjacent) | FX rates bounced off levels published by firms 60.8 percent of the time, against 56.2 percent for arbitrary levels, using a 15-minute bounce test. The effect lasted at least five business days for most firms. No firm's own strength ranking was informative | FX, 1996 to 1998. Published levels, not pivots. Note the 56.2 percent base rate |
| [Chung and Bellotti](https://ar5iv.labs.arxiv.org/html/2101.07410), [Garzarelli et al.](https://ar5iv.arxiv.org/html/1110.5197) (adjacent) | Levels with more prior bounces bounce more often than shuffled controls. The effect fades over hundreds of minutes in EURUSD and Brent | Levels come from rolling extremes, not pivots. Garzarelli et al. note that costs usually remove the profit |
| [Kavajecz and Odders-White](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html) (adjacent) | Support and resistance levels coincide with peaks in limit-order depth | Stocks. Abstract only. Suggests the levels locate depth rather than create it |
| [Sullivan et al.](https://ideas.repec.org/p/fmg/fmgdps/dp303.html), [Bajgrowicz and Scaillet](https://econpapers.repec.org/RePEc:eee:jfinec:v:106:y:2012:i:3:p:473-491) | Data-snooping controls and low costs remove much of the apparent value of technical rules on daily data | Abstracts only |

**What is missing.** I found no peer-reviewed test of floor pivots, and no test on crypto. Reaction rates
of about 55 percent mean little when arbitrary levels score similarly, so the
[placebo control](00_INDEX.md#c15-placebo-control) decides whether this idea has any content.

## 3. Definitions

**Period levels.** For the last completed UTC period with high `H`, low `L`, close `C`:

```text
P  = (H + L + C) / 3
R1 = 2*P - L        S1 = 2*P - H
R2 = P + (H - L)    S2 = P - (H - L)
```

**Active level set** at time `t`: daily `{S2, S1, P, R1, R2}` from the last completed UTC day, plus weekly
`{S1, P, R1}` from the last completed UTC week. A bar is evaluated against the set in force at its open, under
[C2](00_INDEX.md#c2-bars-and-calendar). Levels are not merged. A coincidence of daily and weekly levels is logged
as `confluence`, but it is not a filter, because Osler found firms' own strength rankings uninformative.

**Band.** `b_k = 0.10 * ATR_k`.

**Role.** A level `l` acts as support at bar `k` when `C_(k-j) > l + b_(k-j)` for `j = 1, 2, 3, 4`. The
mirror condition gives resistance.

**Touch index.** The count of separate touches of `l` since it became active. A touch of support is a bar
with `L <= l + b`, and consecutive touching bars count as one. Mirror for resistance.

**Rejection bar, long, at support `l`.** All of the following on bar `k`:

| # | Condition |
|---|---|
| a | `l` has the support role at `k` |
| b | `L_k <= l + b_k` |
| c | `L_k >= l - 0.75 * ATR_k` |
| d | `C_k > l + b_k` |
| e | `CLV_k >= 0.60` |
| f | Touch index of this touch is within the configured limit (default: first touch) |

If two levels qualify on one bar, use the one nearest below `C_k`.

**Day-move filter, long.** `DayOpen - C_k <= 0.8 * ATRD`. A market already down this much on the UTC day is
more likely to be having a trend day, on which pivots are stepping stones rather than turning points.

**Next levels.** `T1` is the nearest active level above `C_k` with `T1 - C_k >= 1.2 * (C_k - S0)`. `T2` is
the next active level above `T1`. If there is none, `T2 = T1 + (T1 - l)`.

## 4. Knowable times

| Object | Knowable at |
|---|---|
| Daily pivot set | 00:00 UTC, at the close of the completed day. It first acts on the bar that opens at 00:00 |
| Weekly pivot set | Monday 00:00 UTC. It first acts on the bar that opens then |
| `ATR_k`, `CLV_k`, `VR_k` | `t_k` |
| `ATRD` | 00:00 UTC, from the completed day |
| `DayOpen` | First trade of the UTC day. Used only at closes after it |
| Touch index | Updated at the close of each touching bar |
| Rejection bar, `S0`, `T1`, `T2` | `t_k` |
| Recomputed `T1`, `T2` at the roll | At the close of the bar ending 00:00, effective from the next bar |

## 5. Setup rules

**Long.** At `t_k`: a rejection bar exists, the day-move filter passes, `VR_k <= 1.75`, `S0` and `T1` exist
under section 7, and the room condition in section 3 holds.

**Short.** The exact mirror: resistance role, `H_k >= l - b_k`, `H_k <= l + 0.75 * ATR_k`, `C_k < l - b_k`,
`CLV_k <= 0.40`, and `C_k - DayOpen <= 0.8 * ATRD`. There is no asymmetry in `V0`.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | Level id and price |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 4 bars after `t_k` |

At most one trade per level. A touch that fails to produce a setup still counts toward the touch index.

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency` on the rejection bar's close, per [C6](00_INDEX.md#c6-entry-fill-r-and-size).
The filter on the close costs some entry price compared with a resting limit at the level. It also keeps
every fill realistic, and avoids buying the many levels that simply break.

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
k_s      = 0.35 * clip(VR_k, 0.8, 1.5)
S_struct = min(L_k, l - b_k) - k_s * ATR_k
S0       = min(S_struct, C_k - R_min(0.8))          # R_min from C9
```

Skip the setup if `C_k - S_struct > 1.75 * ATR_k` (rejection too wide), or if `R_min(0.8) > 2.5 * ATR_k`
(volatility too low to pay costs, logged `COST_VETO`).

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Rule | When | `S_cand`, long |
|---|---|---|
| Reaction clock | `T1` not hit, `n >= 4`, and `MFE_R < 0.75` | `fill - R * max(0.25, 1 - 0.125 * (n - 3))` |
| Level lock | `T1` not hit, and `C_b >= fill + 0.75 * R` | `l - 0.25 * ATR_b` |
| Break-even | `T1` hit | `BE+` |
| Fast trail | `T1` hit | `min(L_(b-2), L_(b-1), L_b) - 0.25 * ATR_b` |

`MFE_R = (highest high since entry - fill) / R`. The reaction clock runs the risk down from `-0.875R` at
`n = 4` to `-0.25R` at `n = 9`, and holds there.

### 7.3 Target logic

`T1` and `T2` are from the pivot ladder, set at `t_k`. They change only at the UTC roll: at the close of
the bar ending 00:00, the current unfilled targets are rebuilt from the new daily set plus the current
weekly set, using levels at least `0.5 * ATR_b` above `C_b`. If `T1` is unfilled, the new `T1` and `T2` are the
nearest and next such levels. If `T1` has filled, the new `T2` is the nearest such level. If no such level
exists, the old target stays. Targets may move in either direction. The stop is not affected.

### 7.4 Scale-out

50 percent at `T1`, the rest at `T2`.

### 7.5 Regime scaling

- `k_s` scales with `VR`, as in 7.1.
- `VR_k > 1.75` blocks new setups. Levels mean little during a volatility shock.
- On Saturday and Sunday UTC, `T2` is dropped and the whole position exits at `T1`. Volatility and volume are
  lower at weekends, especially Saturday ([Hansen et al.](https://ar5iv.labs.arxiv.org/html/2109.12142)),
  so a full rotation is less likely.

### 7.6 Floors

`R_min(0.8)` from [C9](00_INDEX.md#c9-floors). At 15m the cost term usually binds, which is intended: it is
better to take a wider stop or no trade than a stop that only pays fees.

### 7.7 Time stop

If `T1` is not hit by the close of `n = 16` (4 hours at 15m), exit at the next open. After `T1`, exit at
`n = 48` at the latest. Neither is ever extended.

### 7.8 Invalidation

Before `T1`, if `C_b < l - 0.25 * ATR_b` then the level is lost: exit at the next open.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. A bar touching both the stop and `T1` is a stop for the full
quantity with no scale-out. A stop raised at a close acts from the next bar only.

### 7.10 `V0S` control

`S0` from 7.1, `m = 2.0`, `H = 16` bars.

### 7.11 Why this model suits this strategy

A pivot rejection fails in two ways. In the first, the level breaks with force, which the close-based
invalidation handles better than a distant stop. In the second, nothing happens: price sits near the level
while the short-lived order interest is consumed, and the odds fade. A generic trail never addresses this,
because there is no profit to trail. The reaction clock therefore charges the trade for lack of reaction.
The level lock accepts that a working rejection should not come back below the level. After `T1` the
position is a rotation between formula levels with no reason to give back much, so the trail is fast. The
targets are rebuilt at the roll because the levels themselves are replaced there.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. Prior UTC day: `H = 68,450`, `L = 66,250`, `C = 67,900`.
So `P = 67,533.33`, `R1 = 68,816.67`, `S1 = 66,616.67`. `ATR = 180` and `VR = 1.0` are held flat.
`b = 18`, `k_s = 0.35`. Trigger bar closes 21:00: `O 66,700, H 66,810, L 66,590, C 66,790`, `CLV = 0.91`.

- `S_struct = min(66,590, 66,598.67) - 63 = 66,527`. `C - S_struct = 263`.
- `R_min = max(144, 4 * 0.0012 * 66,790) = 320.6`, so the cost floor binds: `S0 = 66,469.4`.
- `T1 = P = 67,533.3`, room is 743 against the required 385. `T2 = R1 = 68,816.6`.
- `R_dec = C - S0 = 320.6`. The collar is 66,880, and the next open of 66,795 is inside it.
- So `fill = 66,801.7` and `R = 332.3`. Both `R` and `R_dec` are fixed from here on.

| `n` | Close | O | H | L | C | Event at this close | Stop after close | `T2` |
|---|---|---|---|---|---|---|---|---|
| 1 | 21:15 | 66,795 | 66,880 | 66,760 | 66,850 | | 66,469.4 | 68,816.6 |
| 2 | 21:30 | 66,850 | 66,960 | 66,830 | 66,900 | | 66,469.4 | 68,816.6 |
| 3 | 21:45 | 66,900 | 66,985 | 66,860 | 66,930 | `MFE = 0.55R` | 66,469.4 | 68,816.6 |
| 4 | 22:00 | 66,930 | 66,970 | 66,850 | 66,880 | Reaction clock: `fill - 0.875R` | 66,510.9 | 68,816.6 |
| 5 | 22:15 | 66,880 | 66,950 | 66,840 | 66,905 | Reaction clock: `fill - 0.75R` | 66,552.4 | 68,816.6 |
| 6 | 22:30 | 66,905 | 67,120 | 66,895 | 67,095 | `C >= 67,050.9`: level lock, `l - 45` | 66,571.6 | 68,816.6 |
| 7 | 22:45 | 67,095 | 67,260 | 67,060 | 67,240 | | 66,571.6 | 68,816.6 |
| 8 | 23:00 | 67,240 | 67,420 | 67,200 | 67,400 | | 66,571.6 | 68,816.6 |
| 9 | 23:15 | 67,400 | 67,560 | 67,380 | 67,510 | `H > T1`: 50% out at 67,533.3 (`+2.20R`). Trail `67,060 - 45` beats `BE+ = 66,881.8` | 67,015.0 | 68,816.6 |
| 10 | 23:30 | 67,510 | 67,640 | 67,470 | 67,600 | Trail | 67,155.0 | 68,816.6 |
| 11 | 23:45 | 67,600 | 67,690 | 67,540 | 67,650 | Trail | 67,335.0 | 68,816.6 |
| 12 | 00:00 | 67,650 | 67,720 | 67,580 | 67,700 | Trail. UTC roll: finished day `H 67,950, L 66,590, C 67,700`, new `R1 = 68,236.67` | 67,425.0 | 68,236.6 |
| 13 | 00:15 | 67,700 | 67,880 | 67,680 | 67,860 | Trail | 67,495.0 | 68,236.6 |
| 14 | 00:30 | 67,860 | 67,900 | 67,700 | 67,720 | Trail | 67,535.0 | 68,236.6 |
| 15 | 00:45 | 67,720 | 67,760 | 67,510 | 67,540 | `L <= 67,535`: stop, 50% at 67,535 (`+2.21R`) | closed | |

Result before costs: `0.5 * 2.20 + 0.5 * 2.21 = 2.20R`. `Result_B = (0.5 * 731.6 + 0.5 * 733.3) / 320.6 = 2.28`. `R`
stayed 332.3 throughout. This path was chosen to exercise every rule and does not represent a typical outcome. Had
bar 9 also traded down to the active stop of 66,571.6, 1m bars would settle the order, and if one 1m bar held both,
the stop would have been taken first and no scale-out recorded.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `T_d` | 15m, 30m | Reaction studies use minutes. 30m pays less in cost per unit of range |
| Touch limit | first touch, first two | Folklore says first touch is best. Chung and Bellotti and Garzarelli et al. find more prior bounces raise the bounce rate. The two disagree, so both are declared |
| Level set | `{P, S1, R1}` daily only, full active set | The full set adds trades and may dilute them |

Total: 8 configurations. All stop and target constants are frozen and not searched.

## 9. BTC and ETH notes

- Same rules on both. `ATR` scales distances, and the cost floor is the same in percent for both.
- ETH usually has a larger percent range, so the cost floor binds less often. This is my judgement, to be
  measured at G3.
- When BTC rejects a daily level and ETH has not reached its own, an ETH setup often comes from BTC
  moving. Both can trigger within a few bars, which counts as correlated risk at layer 5.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Rotational, `VR` near 1, range inside prior range | Should work best if it works at all | Trade results split by `VR` band and by whether the UTC day stayed inside the prior day's range |
| Trend days | Should fail, levels break in sequence | Loss clusters on days with `abs(close - open)` above `1.2 * ATRD`, which is measured after the fact and never used as a filter |
| Liquidation cascades | Should fail hard, with bad stop fills | Stop slippage far above base on those days |
| Weekends | Fewer and smaller moves, `T1` only | Compare weekend and weekday result in `R` |
| Any regime | Should beat its [placebo](00_INDEX.md#c15-placebo-control) | If rejection results match random levels, that is a case for retiring it, decided and logged under [C18](00_INDEX.md#c18-selection-purge-and-retirement) |

## 11. Flow hooks

Questions for `feature-integrator`. These are not feature choices.

- **Entry gate:** while price is at the level, is aggressive selling being absorbed without further price
  progress, or is it still making new lows on rising taker volume?
- **Entry gate:** did the touch come with one-sided liquidation-like flow, or with ordinary two-way trade?
- **Entry timing:** after the rejection close, does taker buying continue or fade over the next minutes?
- **Early exit:** during the reaction clock period, has the book or trade flow turned against the position
  before the stop tightens further?
- **Stop tightening:** after `T1`, is flow into the next level weakening?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Pivot from the current day | Using today's `H` or `L` at 15:00 | Levels change only at 00:00 UTC, from the completed period |
| Weekly pivot on a partial week | Computing on Friday with Friday's data | Levels change only on Monday 00:00 UTC |
| `ATRD` from today | Daily ATR merged at 00:00 including the running day | Last completed day only |
| Touch index with later touches | Counting touches over the level's whole life | Count only touches at or before `t_k` |
| Entry at the level | Filling at `l` when the trigger needed the close | Fill no earlier than `t_k + latency` |
| Trail from the current bar | Applying `L_b` to bar `b` | Applied from bar `b + 1` |
| Roll applied too early | New targets used during the bar ending 00:00 | Effective from the next bar |
| Day boundary in data | A daily bar from a vendor with a non-UTC boundary | `data-steward` confirms the source boundary. Build the daily bar from intraday bars |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 200 to 400 trades per year across BTC and ETH with the
full set and first touch.

**Cost.** Typical `R` is near the floor, about 50 to 60 bp. At the illustrative `RT = 12 bp`, cost is about
`0.2R` to `0.25R` per trade at 1x, and `0.6R` to `0.75R` at 3x. The kill point is a gross expectancy below
that. As a rule of thumb, the break-even `RT` equals gross expectancy in `R` times `R` in bp, so a gross
`+0.2R` on a 55 bp stop dies at 11 bp, below the illustrative taker cost. This is the most cost-sensitive
family in the set, together with S06. If it ever earns a place, it is likely to be through flow-gated
entry or a much better fee tier. Nothing here suggests that it does.

## 14. Live on an hourly cycle

**Verdict: not eligible. Backtest only.** No live-eligible timeframe, including 1h.

**Why.** The thesis is a reaction lasting minutes. Osler's bounce test looks 15 minutes after the touch, and
the reaction clock here starts at `n = 4`, one hour after entry at 15m. An hourly run can detect the rejection
up to an hour or more late, by which time the whole reaction window this strategy charges for has gone. A 1h
version would be a different strategy: a level held over a full hourly close is closer to S04 or S02 in
behaviour, and the band, the `0.75 * ATR` penetration limit and the clock would all lose their meaning. I
would rather retire that variant than dress it up, so `T_d` under 1h stays backtest-only here.

**Late entries.** None are taken live. Hourly runs do not create S01 positions. If this strategy were forced
onto the cycle, its `A_max` would have to be about 30 minutes to keep the thesis, and the cycle cannot
guarantee that.

**Stops and targets between runs.** There are no live S01 positions. In research, [C7](00_INDEX.md#c7-exit-engine)
applies, on `T_d` bars in `IDEAL` and on 1m bars in `IDEAL-1M`, with 1m bars always settling same-bar conflicts.

**Backtest reproduction.** S01 reports `IDEAL` and `IDEAL-1M`, selects under `IDEAL-1M`, and every chart and table
carries the label `NOT LIVE-COMPARABLE`. One control run is required: the default configuration through
[`C-LATE`](00_INDEX.md#c17-hourly-live-cycle), recorded in the trial registry as a control. Its check values are
declared here, before any result:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 90 minutes after the rejection close |
| Path | `S0` or `T1` touched, or a `T_d` close below `l - 0.25 * ATR`, voids the setup |
| Chase | `abs(P_dec - C_k) <= 0.75 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(0.8)` and `2.5 * ATR_k` |
| `RR_late` | `T1 - P_dec >= 1.0 * (P_dec - S0)` |
| Thesis | `P_dec > l + b_k` |

The control measures how much of any research result the cycle would destroy, and so tests this verdict. If `CYCLE`
results turned out close to `IDEAL-1M`, this section should be revisited by a new document version, which counts as new
trials under [C18](00_INDEX.md#c18-selection-purge-and-retirement), and not by running S01 live on the strength of that
one control.
