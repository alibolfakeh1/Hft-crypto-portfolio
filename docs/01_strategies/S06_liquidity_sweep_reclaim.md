# S06 Liquidity sweep and reclaim

Status: revised after the leak audit of 2026-11-04, awaiting re-audit. Not tested. Tier `T0`. Default `T_d` 15m. Long and
short. Backtest only: not eligible for the hourly live cycle, see section 14.
Common rules C1 to C18 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

Stops and breakout orders collect just beyond obvious highs and lows. A move through such a level triggers them. If that
flow is the only thing pushing price, and it runs out, price returns inside the old range and the traders who were
triggered are left on the wrong side. This strategy buys the reclaim of a swept low, and sells the reclaim of a swept high.

**Who is on the other side.** Stopped longs, who sold at the low, and breakout shorts who sold under it and now need to
cover. In BTC and ETH perpetuals, the flow can also be forced: high implied leverage makes liquidation a real source of
one-way flow ([Cheng et al.](https://ar5iv.labs.arxiv.org/html/2102.04591)).

**How much of this is folklore.** The fuel is documented, and the reversal is not. In the one published order data set I read,
stops cluster beyond round numbers and *propagate* moves, for hours
([Osler 2002](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.html)). That is an argument for the
break to continue, which is the opposite of this trade. The theoretical support for a snap-back is that forced selling can
push price past fair value, and that others who sell into it later buy back
([Brunnermeier and Pedersen](https://econpapers.repec.org/RePEc:bla:jfinan:v:60:y:2005:i:4:p:1825-1863)). The "smart money
hunts stops" story, with intent attached, is folklore. This rule does not need intent, only exhausted flow.

## 2. Evidence

**Grade for the rule: `NONE`.** I found no test with a stated sample and method.

| Source | What it shows | Limits |
|---|---|---|
| [Osler 2001](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html) (adjacent) | 9,667 FX conditional orders. Stop-loss sells cluster just below round numbers, and stop-loss buys just above | FX, one bank. Supports where the fuel sits |
| [Osler 2002](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.html) (adjacent) | Trends are unusually fast at stop clusters, and the response lasts longer than for take-profit orders. Significant for hours, not days | FX. **Cuts against reversal in the first hours** |
| [Brunnermeier and Pedersen](https://econpapers.repec.org/RePEc:bla:jfinan:v:60:y:2005:i:4:p:1825-1863) (adjacent) | Theory: when a trader must sell, others sell and buy back, so price overshoots. Liquidity is thinnest when most needed | Theory. Abstract only |
| [Garcia Seuma](https://ideas.repec.org/p/arx/papers/2608.03616.html) (adjacent) | Seven crypto perpetual cascades, 2022 to 2025: about 88 percent of post-onset forced selling came within thirty minutes, with price impact spiking and open interest falling 25 to 70 percent | Large events only. Abstract only. Suggests that forced flow is short |
| [Urquhart 2017](https://econpapers.repec.org/RePEc:eee:ecolet:v:159:y:2017:i:c:p:145-148) (adjacent) | Bitcoin prices cluster at round numbers, with **no significant return pattern after them** | Abstract only |
| [LuxAlgo, liquidity sweep](https://www.luxalgo.com/library/concept/liquidity-sweep.md) | Definitions, and it notes that many runs through a level simply continue | No statistics |

`UNVERIFIED`: a search snippet of a TradingView indicator page reported that a raw sweep had no reliable reversal edge out of
sample on top coins at 1h to 1D, and leaned toward continuation. I could not open that text in full or see a sample size. I
note it because it is the only outcome claim I saw, and it is unfavourable.

## 3. Definitions

**Liquidity pools, for a long (below price).**

| Pool | Definition |
|---|---|
| `PDL` | Low of the last completed UTC day, in force from the bar that opens at the roll, so a bar cannot sweep a low it set itself |
| `PWL` | Low of the last completed UTC week, on the same terms |
| Swing low | In `Sigma(5, 3, 1.0)` on 1h bars with 1h `ATR`, unswept, age at most 7 days, and knowable at least 8 `T_d` bars before the sweep |

A pool is consumed by its first sweep or by any close beyond it, logged as `consumed_at`, and gives at most one trade. Pools are a register
under [C4](00_INDEX.md#c4-swing-pivots-and-registers), read as of the sweep. A swing pool is therefore visible while `valid_from <= t < valid_to`,
even if a later, lower swing replaces it after the trade. Equal lows and nearby round numbers (multiples of 1,000 for BTC and 100 for ETH,
within `0.25 * ATR` on 1h) are logged as tags and are not filters.

**Sweep, long, of pool `l`, at bar `s`.**

| # | Condition |
|---|---|
| a | `C_(s-1) >= l` |
| b | `L_s < l - 0.10 * ATR_s` |
| c | `L_s >= l - 1.50 * ATR_s` |
| d | `H_s - L_s <= 4.0 * ATR_s`: a larger bar is an active cascade |
| e | `SRV_s >= 1.0`, or `>= 1.5` on Saturday and Sunday UTC |

**Reclaim.** At a bar `r` in `s, ..., s + N_r` (default `N_r = 2`), `C_r > l + 0.10 * ATR_r` and `CLV_r >= 0.60`. No bar in
between may have a low below `l - 1.50 * ATR`. `sweep_low` is the lowest low from `s` to `r`. If several pools were swept, `l`
is the highest one that the close reclaimed.

**Day-move filter, long.** `DayOpen - C_r <= 1.25 * ATRD`, with `ATRD` from C3.

**Opposing pools, for targets.** `PDH`, `PWH` and swing highs, as the mirror of the table above.

**Pre-sweep high.** `PSH` is the highest high in the 12 bars before `s`.

## 4. Knowable times

| Object | Knowable at |
|---|---|
| `PDL`, `PDH` | 00:00 UTC, from the completed day. They first act on the bar that opens at 00:00 |
| `PWL`, `PWH` | Monday 00:00 UTC. They first act on the bar that opens then |
| Swing pool | Its 1h confirmation close, and tradable 8 `T_d` bars later |
| Sweep | Close of `s`. A touch alone is not a sweep |
| Reclaim, `S0`, targets | `t_r` |
| Linger count | Each close |
| Recomputed targets | At each UTC roll and each newly confirmed 1h swing, effective next bar |

## 5. Setup rules

**Long,** at `t_r`: a sweep, a reclaim, the day-move filter, `VR_r <= 1.75`, and valid `S0` and `T1`.

**Short.** The exact mirror: a sweep of a high, with reclaim by a close below it. Crypto's squeeze behaviour may make this side
behave differently, so results are reported per side. No rule differs.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | Pool id and `l`, `sweep_low` |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 3 bars after `t_r` |

## 6. Entry trigger for `V0`

Taker entry at `t_r + latency` on the reclaim close, per [C6](00_INDEX.md#c6-entry-fill-r-and-size). Buying during the sweep
would be catching a falling price, and any fill there depends on the thing we are trying to find out.

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
k_s      = 0.25 * clip(VR_r, 0.8, 1.5)
S_struct = sweep_low - k_s * ATR_r
S0       = min(S_struct, C_r - R_min(0.75))
```

Skip if `C_r - S0 > 2.25 * ATR_r`, or log `COST_VETO` if `R_min(0.75) > 3.0 * ATR_r`.

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Rule | When | `S_cand`, long |
|---|---|---|
| Reclaim lock | `C_b >= fill + 1R` | `l - 0.25 * ATR_b` |
| Break-even | `T1` filled | `BE+` |
| Trail | `T1` filled | Lowest low of the last 5 bars, minus `0.50 * ATR_b` |

### 7.3 Target logic

At `t_r`, with `D = C_r - S0`:

- `T1 = PSH` if `PSH >= C_r + 1.0 * D`, otherwise `T1 = C_r + 1.25 * D`.
- `T2` is the nearest opposing pool above `T1` and at least `C_r + 2.0 * D`. If none exists, `T2 = C_r + 3.0 * D`.

**Recompute `T2`** at each UTC roll, when the opposing pools change, and when a new 1h swing high is confirmed: it becomes the
nearest opposing pool at least `0.5 * ATR_b` above `C_b`, if one exists. `T1` is never recomputed.

### 7.4 Scale-out

50 percent at `T1`, the rest at `T2`.

### 7.5 Regime scaling

- `k_s` scales with `VR`, and `VR_r > 1.75` blocks setups.
- The `SRV` requirement rises at weekends, when thin trading makes a sweep less meaningful.
- The day-move filter stops longs on days already falling hard, when a low is likelier to be a real break.

### 7.6 Floors

`R_min(0.75)` from [C9](00_INDEX.md#c9-floors). At 15m, and especially 5m, the cost term usually binds. This is the main limit
on this strategy.

### 7.7 Time stop

| `T_d` | `T1` not hit by | Absolute limit | `V0S` `H` |
|---|---|---|---|
| 15m | `n = 12` | `n = 48` | 16 |
| 5m | `n = 24` | `n = 96` | 32 |

### 7.8 Invalidation

Each of these exits at the next open:

- **Reclaim lost.** For `n <= 4`, `C_b < l - 0.10 * ATR_b`.
- **Linger.** At the close of `n = 6`, at least 4 of the 6 closes lie within `0.25 * ATR` of `l`.
- **Aftershock.** Before `T1`, a bar with `H_b - L_b >= 3.0 * ATR_b` and `C_b < O_b`.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both the stop and `T1`, the stop is taken. An aftershock bar that
also touches the stop is a stop.

### 7.10 `V0S` control

`S0` from 7.1, `m = 2.0`, `H` from the table in 7.7.

### 7.11 Why this model suits this strategy

If the forced flow really was exhausted, the return should be fast, and that is a stronger test than any price target. A
sweep that fails either falls back under the reclaimed line, or lingers at the line while someone absorbs buying, or gets hit
by a second wave of forced flow. Each of those has its own exit, and all act before the distant stop. The sweep low is a hard
limit because a new low there means the flow was not exhausted. Published work on cascades suggests most forced selling is
over in about thirty minutes, so a three-hour time stop is already generous. Targets are the opposite pools because the
mechanism says the next fuel sits there.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. `T_d = 15m`, ETH. `ATR = 9`, `VR = 1.0` held flat. `PDL = l = 3,300`. A 1h swing
high at 3,352 is the nearest opposing pool, and `PSH = 3,325`.

- Sweep and reclaim on one bar, closing 22:15: `O 3,306, H 3,309, L 3,292, C 3,302.5`. Depth 8, `CLV = 0.62`, `SRV = 1.4`.
- `S_struct = 3,292 - 2.25 = 3,289.75`. `R_min = max(6.75, 15.85) = 15.85`, so the floor binds: `S0 = 3,286.64`. `D = 15.86`.
- `T1 = PSH = 3,325`, at least 15.86 above `C`. `T2 = 3,352`, at least 31.7 above `C`.
- `R_dec = 15.86`. The collar is 3,307, and the next open of 3,303 is inside it.
- So `fill = 3,303.33`, `R = 16.69`, `BE+ = 3,307.29`.

| `n` | Close | O | H | L | C | Event at this close | Stop after close | Next target |
|---|---|---|---|---|---|---|---|---|
| 1 | 22:30 | 3,303 | 3,309 | 3,300.5 | 3,307 | Reclaim held | 3,286.64 | `T1` 3,325 |
| 2 | 22:45 | 3,307 | 3,312 | 3,304 | 3,310 | | 3,286.64 | `T1` 3,325 |
| 3 | 23:00 | 3,310 | 3,316 | 3,308 | 3,314 | | 3,286.64 | `T1` 3,325 |
| 4 | 23:15 | 3,314 | 3,321 | 3,312 | 3,320.5 | `C >= fill + 1R`: reclaim lock, `l - 2.25` | 3,297.75 | `T1` 3,325 |
| 5 | 23:30 | 3,320.5 | 3,327 | 3,318 | 3,325 | `H > T1`: 50% out at 3,325 (`+1.30R`). `BE+` beats trail 3,296 | 3,307.29 | `T2` 3,352 |
| 6 | 23:45 | 3,325 | 3,331 | 3,322 | 3,329 | Linger count 0. Trail 3,299.5 is lower, no change | 3,307.29 | `T2` 3,352 |
| 7 | 00:00 | 3,329 | 3,334 | 3,324 | 3,330 | Trail 3,303.5, no change. UTC roll: new `PDH = 3,345` is nearer | 3,307.29 | `T2` 3,345 |
| 8 | 00:15 | 3,330 | 3,337 | 3,327 | 3,335 | Trail `3,312 - 4.5` | 3,307.50 | `T2` 3,345 |
| 9 | 00:30 | 3,335 | 3,342 | 3,331 | 3,339 | Trail `3,318 - 4.5` | 3,313.50 | `T2` 3,345 |
| 10 | 00:45 | 3,339 | 3,346 | 3,336 | 3,344 | `H > T2`: 50% out at 3,345 (`+2.50R`) | closed | |

Result before costs: `0.5 * 1.30 + 0.5 * 2.50 = 1.90R`. `Result_B = (0.5 * 21.67 + 0.5 * 41.67) / 15.86 = 2.00`. `R` stayed 16.69
throughout. This path was chosen to exercise the rules
and does not represent a typical outcome. Had bar 2 closed at 3,298, below `l - 0.9`, the position would have exited at the next
open by "reclaim lost", at about `-0.3R`.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `T_d` | 5m, 15m | 5m sees the event more clearly, and pays far more in cost relative to `R`. The charter's lowest timeframe is 5m |
| `N_r` | 0, 2 | Same-bar reclaim, or allow two more bars. Practitioners disagree |
| Pools | Period highs and lows only, plus 1h swings | Period levels are the most widely seen, and swings add more trades |

Total: 8 configurations. All stop and target constants are frozen. The default line under [C18](00_INDEX.md#c18-selection-purge-and-retirement) is 15m, `N_r` 2, period highs and lows plus 1h swings.

## 9. BTC and ETH notes

- Same rules. Round-number tags use different multiples, and are for later analysis only.
- A sweep of a BTC level usually drags ETH down at the same time. ETH may sweep a level of its own as a side effect, which is
  a weaker signal than a sweep on its own flow. This is my judgement, to be measured.
- Liquidation-driven sweeps carry more stop slippage on both, and likely more on ETH. Use a separate stop slippage value per symbol.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Ranges, with visible prior highs and lows | Should work best if it works at all | Result by `VR` band and day type measured afterwards |
| Trend days | Should fail: the sweep is a real break | Share of "reclaim lost" exits, and the day-move filter's counterfactual |
| Liquidation cascades | Filtered partly, by the 4-`ATR` rule and the aftershock rule | Counterfactual of filtered setups, and stop slippage |
| Any regime | Reversal must beat continuation, and must beat [random levels](00_INDEX.md#c15-placebo-control) | Compare with both a placebo and the opposite-direction trade |

## 11. Flow hooks

Questions for `feature-integrator`. These hooks can only be tested in research, since this strategy does not run live.

- **Setup qualification:** was the sweep dominated by aggressive one-way flow that then stopped abruptly?
- **Entry gate:** at the reclaim, has aggressive selling actually stopped, or only paused?
- **Entry gate:** did resting bids absorb the sweep, or did the book empty and refill?
- **Early exit:** does a second wave of aggressive selling appear before a close confirms it?
- **Stop tightening:** after the reclaim lock, is flow into the opposing pool weakening?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Pool from a swing not yet confirmed | A low at 10:00 treated as a pool at 11:00, with confirmation at 13:00 | Knowable at confirmation, tradable 8 bars later |
| Prior-day level from the current day | `PDL` updating intraday | Only at 00:00 UTC |
| `sweep_low` extended after entry | Moving the structure stop to a lower low made later | `S0` is frozen at `t_r`, and a lower low is a stop or an exit |
| Reclaim chosen by hindsight | Taking the best of the bars in `s..s+N_r` | First qualifying close, in time order |
| Opposing pool not yet known | A swing high confirmed after entry used as `T2` at entry | Only at its own close, by the recompute rule |
| Touch counted as consumption retroactively | Removing a pool from history once it is known to break | The register changes only at the close of the bar that consumes it |
| Pool lost to a later replacement | A pool at 3,300 is swept and reclaimed at 22:15, and the sweep low is confirmed as a swing at 02:00 and replaces it. In a final list the pool never existed at 22:15, so the trade disappears | As-of read, `valid_from <= t < valid_to`. A final list is forbidden as an input, and truncation invariance is required |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 100 to 250 trades per year across BTC and ETH at 15m. More at 5m.

**Cost.** `R` sits near the cost floor at about 50 to 70 bp at 15m, by my judgement. At the declared `RT = 12 bp`, cost is
`0.17R` to `0.25R` at 1x and `0.5R` to `0.75R` at 3x. A gross `+0.2R` on a 60 bp stop dies at `RT = 12 bp`, the declared value
itself. Extra stop slippage in the events this strategy trades makes it worse. At 5m the floor binds almost always, and the
stop no longer reflects structure at all. Together with S01, this is the most cost-exposed idea in the set. A stop exit pays `stop_slip` in place of `slip`, so 16 bp in all at 1x, under [C16](00_INDEX.md#c16-rounding-and-arithmetic-in-examples).

## 14. Live on an hourly cycle

**Verdict: not eligible. Backtest only.** No live-eligible timeframe, including 1h.

**Why.** Everything this strategy tests happens faster than the cycle. Published work on large cascades places most forced selling
within about thirty minutes. The first invalidation looks at the first four 15m bars, the linger test ends at 90 minutes, and the
time stop is 3 hours. A run that starts an hour late sees a reclaim after the reversal has already happened, and has already
missed most of `T1`. A 1h version would be possible, but it would be a different trade, a slower failed-breakout pattern with wider
stops and no connection to this mechanism. The mechanism would no longer be what is being tested, so I do not offer it.

**Late entries.** None are taken live. Hourly runs do not create S06 positions.

**Stops and targets between runs.** There are no live S06 positions. In research, [C7](00_INDEX.md#c7-exit-engine) applies, on `T_d` bars
in `IDEAL` and on 1m bars in `IDEAL-1M`, with 1m bars always settling same-bar conflicts. At 5m that settling step matters often.

**Backtest reproduction.** S06 reports `IDEAL` and `IDEAL-1M`, selects under `IDEAL-1M`, and every chart and table carries the label
`NOT LIVE-COMPARABLE`. One control run is required: the 15m default through [`C-LATE`](00_INDEX.md#c17-hourly-live-cycle), recorded in the
trial registry as a control. Its check values are declared here, before any result:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 90 minutes after the reclaim close |
| Path | `S0` or `T1` touched, or a `T_d` close below `l - 0.10 * ATR`, voids the setup |
| Chase | `abs(P_dec - C_r) <= 0.75 * ATR_r` |
| Risk | `P_dec - S0` between the setup's `R_min(0.75)` and `2.25 * ATR_r` |
| `RR_late` | `T1 - P_dec >= 1.0 * (P_dec - S0)` |
| Thesis | `P_dec > l + 0.10 * ATR_r` |

The control measures how much of any research result would survive the cycle, and so tests this verdict. A surprising result would justify a
new document version, which counts as new trials under [C18](00_INDEX.md#c18-selection-purge-and-retirement), and not a live run.
