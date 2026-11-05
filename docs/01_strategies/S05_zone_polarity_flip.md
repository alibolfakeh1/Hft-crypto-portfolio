# S05 Zone polarity flip

Status: revised after the leak audit of 2026-11-04, awaiting re-audit. Not tested. Tier `T0`. Default `T_d` 1h. Long and
short. Live-eligible at 1h and 4h, see section 14.
Common rules C1 to C18 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

A supply zone that fails has done something specific. Traders sold there, the market went through, and they now hold
losing shorts with a known average price, which is inside the zone. When price comes back to it, some of them cover at
about break-even. That buying is the reason a broken supply zone may act as support.

**Who is on the other side.** Those trapped shorts, buying to close at the retest, plus anyone who sells the retest
expecting the old zone to hold.

**Why this is not S02.** S02 trades a formula level, where nobody is known to hold a position. S05 requires a zone where
trading demonstrably took place and then failed. If both look the same in the results, this one is the first candidate
to retire, decided and logged under [C18](00_INDEX.md#c18-selection-purge-and-retirement).

**How much of this is folklore.** The "role reversal" idea is ancient chart lore. The nearest research concerns
reference prices: holding on to losers and reacting to one's cost basis. It does not show covering at break-even at a
candle-defined zone, and in Bitcoin the behavioural effect is not even stable over time. The trapped-trader story may be
wrong, and even if true may be too small to matter.

## 2. Evidence

**Grade for the rule: `NONE`.** I found no test of polarity flips. The S/R studies I read define outcomes as a bounce or a
penetration and stop at that point, without testing what the level does afterwards.

| Source | What it shows | Limits |
|---|---|---|
| [Schatzmann and Haslhofer](https://ar5iv.labs.arxiv.org/html/2010.12415) (adjacent) | Evidence of a disposition effect in Bitcoin from on-chain transfers to exchanges, not consistently present, and strongest from 2017. Selling skews to gains in rising markets and to losses in falling ones | On-chain long-horizon holders, not perpetual traders. Counts transactions, not amounts |
| [Grinblatt and Han](https://ideas.repec.org/a/eee/jfinec/v78y2005i2p311-339.html) (adjacent) | Reference-price behaviour and unrealised gains explain stock momentum in cross-sectional tests | Stocks, long horizons. Abstract only |
| [Osler 2001](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html), [Osler 2002](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.html) (adjacent) | Stops just beyond levels intensify moves after crossing, for hours | FX. Supports the break, not the retest |
| [Chung and Bellotti](https://ar5iv.labs.arxiv.org/html/2101.07410) (adjacent) | Defines penetration, but tests only bounce probability | Silent on role reversal |

**Reading.** The break has adjacent support. The retest has none. This strategy is a hypothesis about trapped inventory.

## 3. Definitions

**Zones.** The S04 engine, exactly as in [S04 section 3](S04_supply_demand_zones.md#3-definitions), including the quality
score. Written for the long case, which uses a supply zone with `prox` as its lower edge and `dist` as its upper edge.

**Eligible zone.** A supply zone, active, with `Q >= 45` and at most 1 touch at the time of the break.

**Break bar.** A close `k_b` with all of:

| # | Condition |
|---|---|
| a | `C > dist + 0.25 * ATR` |
| b | `C - O >= 0.75 * ATR` |
| c | `SRV >= 1.2` |
| d | `H - L <= 4.0 * ATR`. A larger bar is likely forced flow and does not create a flip |

**Flip object,** knowable at `t_(k_b)`:

```text
top    = dist                  # upper edge of the old supply zone
bottom = prox                  # lower edge
mid    = (top + bottom) / 2
X      = highest high from k_b through the trigger, updated at each close
```

**Travel.** `X - top >= 1.0 * ATR`, needed before a retest can count.

**Retest window.** `RW` bars after `k_b` (default 48). The first bar after the one that completes travel, with `L <= top`, opens the retest, because one bar does not show whether its high or its low came first. A trigger
may occur on that bar or on the next 2 bars. After those 3 bars, no trade comes from that flip.

**Flip death.** Any close below `bottom - 0.25 * ATR`, any close below `mid` during the retest, including the bar that opens it, or the end of the window.
This is logged as `dead_at`, and during a re-seed its `ATR` is the last defined value, under
[C3](00_INDEX.md#c3-indicators). Flips are a register under [C4](00_INDEX.md#c4-swing-pivots-and-registers), read as of a time, and a
dead flip stays in it.

**Stage A and Stage B.** A trade is in Stage A from entry until `T1` fills or `C_b > X`, whichever comes first, and in Stage B
after that.

## 4. Knowable times

| Object | Knowable at |
|---|---|
| Zone and score | As in S04, `t_e` at the earliest |
| Break bar, flip object | `t_(k_b)` |
| `X` | Each close, and frozen at the trigger for targets |
| Trigger, `S0`, targets | `t_k` |
| Later swings used by stops and `T2` | Their confirmation closes, effective next bar |
| Stage change | The close at which it is seen, or at the `T1` fill. Its stop rules are computed at the next close |

## 5. Setup rules

**Long,** at `t_k`, during the retest:

| # | Condition |
|---|---|
| a | `L_k >= bottom - 0.25 * ATR_k` |
| b | `C_k > top` |
| c | `CLV_k >= 0.50` |
| d | `VR_k <= 2.0` |
| e | `X - C_k >= 0.75 * (C_k - S0)` |

**Short.** The exact mirror: a demand zone broken downward, retested from below.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | Flip id, `top`, `bottom`, `mid`, `X` |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 4 bars after `t_k` |

One trade per flip. If two flips trigger on one bar, use the one whose `top` is nearest the close.

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency`, per [C6](00_INDEX.md#c6-entry-fill-r-and-size).

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
S_struct = bottom - 0.25 * clip(VR_k, 0.8, 1.5) * ATR_k
S0       = min(S_struct, C_k - R_min(0.75))
```

Skip if `C_k - S0 > 2.5 * ATR_k`.

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Stage | Rule | When | `S_cand`, long |
|---|---|---|---|
| A | Inventory clock | `T1` not hit at `n = 9` | `mid - 0.25 * ATR_b` |
| B | Zone must hold | `T1` filled | `top - 0.25 * ATR_b` |
| B | Break-even | `C_b > X` | `BE+` |
| B | Higher-low step | A swing low in `Sigma(3, 2, 1.0)` confirmed after entry, above the current stop | `swing low - 0.25 * ATR_b` |

### 7.3 Target logic

At `t_k`, `L_r` is the lowest low from the retest's first bar through `k`.

```text
T1 = X
T2 = X + (X - L_r)
```

**Recompute `T2`** once in Stage B, when the first swing low in `Sigma(3, 2, 1.0)` above the flip is confirmed after a swing
high above `X` has also been confirmed:

```text
T2 = max(SH_new + (SH_new - SL_new), C_b + 1.0 * ATR_b)
```

This re-bases the second leg on the actual pullback. If an active opposing zone with `Q >= 45` is born between `C_b + 0.5 * ATR_b`
and `T2`, then `T2` moves to its `prox`.

### 7.4 Scale-out

One third at `T1`, the rest at `T2`.

### 7.5 Regime scaling

- The stop buffer scales with `VR`, as in 7.1.
- `VR_k > 2.0` blocks new setups.
- A break bar over `4 * ATR` creates no flip, because a forced move through a zone says little about acceptance beyond it.

### 7.6 Floors

`R_min(0.75)` from [C9](00_INDEX.md#c9-floors).

### 7.7 Time stop

| `T_d` | `T1` not hit by | Absolute limit | `V0S` `H` |
|---|---|---|---|
| 1h | `n = 18` | `n = 72` | 48 |
| 4h | `n = 9` | `n = 36` | 24 |

### 7.8 Invalidation

- Stage A: `C_b < mid`, exit at the next open. Trapped covering has not held the zone.
- Stage B: `C_b < top - 0.25 * ATR_b`, exit at the next open. The zone was re-entered after the flip had been confirmed.

The stage used at a close is the stage as of that close. Stage B invalidation therefore applies only from the first close
at or after Stage B began.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both the stop and `T1`, the stop is taken and Stage B does not
begin.

### 7.10 `V0S` control

`S0` from 7.1, `m = 2.5`, `H` from the table in 7.7.

### 7.11 Why this model suits this strategy

The thesis has a clear clock. The trapped shorts exit around the first retest, and after that the supply they represent
is gone. So in Stage A the question is whether price can return to the break extreme `X`, soon. If it cannot, the inventory
clock tightens and a close below `mid` ends the trade. Reaching `X` confirms the flip, and only then does the top of the zone
become a line that must hold. A retest of a flipped zone can be used once, so re-entering it after confirmation is treated
as failure, not as another chance. The second target is re-based on the real pullback, since the first projection was made
before any of the second leg existed.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. `T_d = 1h`, BTC. `ATR = 280`, `VR = 1.0` held flat.

- Supply zone: `prox 66,100`, `dist 66,350`, `Q = 62`, 1 touch. Break bar closes 10:00: `O 66,240, C 66,560`. `C > 66,420`, body
  320 above 210, `SRV = 1.6`.
- Flip: `top 66,350`, `bottom 66,100`, `mid 66,225`. By 15:00, `X = 66,900`, so travel is 550 above 280.
- Trigger bar closes 20:00: `O 66,480, H 66,510, L 66,300, C 66,440`. `L` is at or below `top`, `C > top`, `CLV = 0.67`.
- `S0 = 66,100 - 70 = 66,030`. `C - S0 = 410`. `R_min = max(210, 318.9)`, so the structure stop stands.
- `T1 = X = 66,900`. `L_r = 66,300`, so `T2 = 67,500`.
- `R_dec = 410`. The collar is 66,580, and the next open of 66,445 is inside it.
- So `fill = 66,451.6`, `R = 421.6`, `BE+ = 66,531.3`.

| `n` | Close | O | H | L | C | Event at this close | Stop after close | Next target |
|---|---|---|---|---|---|---|---|---|
| 1 | 21:00 | 66,445 | 66,520 | 66,420 | 66,500 | Stage A | 66,030.0 | `T1` 66,900 |
| 2 | 22:00 | 66,500 | 66,610 | 66,470 | 66,580 | | 66,030.0 | `T1` 66,900 |
| 3 | 23:00 | 66,580 | 66,700 | 66,560 | 66,680 | | 66,030.0 | `T1` 66,900 |
| 4 | 00:00 | 66,680 | 66,760 | 66,640 | 66,720 | | 66,030.0 | `T1` 66,900 |
| 5 | 01:00 | 66,720 | 66,850 | 66,700 | 66,820 | | 66,030.0 | `T1` 66,900 |
| 6 | 02:00 | 66,820 | 66,930 | 66,790 | 66,900 | `H > T1`: one third out at 66,900 (`+1.06R`). Stage B: `top - 70` | 66,280.0 | `T2` 67,500 |
| 7 | 03:00 | 66,900 | 67,020 | 66,880 | 67,000 | `C > X`: `BE+` | 66,531.3 | `T2` 67,500 |
| 8 | 04:00 | 67,000 | 67,060 | 66,850 | 66,880 | | 66,531.3 | `T2` 67,500 |
| 9 | 05:00 | 66,880 | 66,930 | 66,780 | 66,830 | | 66,531.3 | `T2` 67,500 |
| 10 | 06:00 | 66,830 | 66,950 | 66,810 | 66,930 | Swing high 67,060 at bar 8 confirmed | 66,531.3 | `T2` 67,500 |
| 11 | 07:00 | 66,930 | 67,080 | 66,900 | 67,060 | Swing low 66,780 at bar 9 confirmed. Stop `66,780 - 70`. `T2 = max(67,340, 67,340)` | 66,710.0 | `T2` 67,340 |
| 12 | 08:00 | 67,060 | 67,240 | 67,040 | 67,210 | | 66,710.0 | `T2` 67,340 |
| 13 | 09:00 | 67,210 | 67,390 | 67,180 | 67,360 | `H > T2`: two thirds out at 67,340 (`+2.11R`) | closed | |

Result before costs: `(1/3) * 1.06 + (2/3) * 2.11 = 1.76R`. `Result_B = ((1/3) * 448.4 + (2/3) * 888.4) / 410 = 1.81`. `R` stayed
421.6 throughout. This path was chosen to exercise the
rules and does not represent a typical outcome. Had bar 2 closed at 66,200, below `mid`, the position would have exited at
the next open, at about `-0.6R`, without waiting for the stop at 66,030.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `T_d` | 1h, 4h | Same engine and same reasoning as S04 |
| `RW` | 24, 48 bars | Trapped traders act early, so a short window fits the story. The long one tests that claim |

Total: 4 configurations. Everything else is frozen. The `Q` threshold is fixed, and is deliberately lower than S04's, since
a weak zone can still trap someone. It is not a search dimension.

## 9. BTC and ETH notes

- Same rules. Break quality uses `ATR` and `SRV`.
- Shorts trapped on perpetuals pay or receive funding while waiting. A positive funding environment penalises holding
  shorts, so the covering pressure could be stronger when funding is high. I have no evidence for this, and it is not used.
- Report BTC and ETH separately. This trade relies on a behavioural story that may differ with the mix of participants.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Trend resuming after a pause | Should work best | Result by whether the UTC day extended in the trade's direction, measured afterwards |
| Ranges | Should fail: the break was noise | Many Stage A invalidations |
| Liquidation-driven breaks | Excluded by the 4-`ATR` rule | Counterfactual of excluded flips |
| Any regime | Should differ from S02 | Trade-level correlation with S02 at G4. If high, this is the first candidate to retire, under [C18](00_INDEX.md#c18-selection-purge-and-retirement) |
| Any regime | Should beat [random levels](00_INDEX.md#c15-placebo-control) | A flip built from a random band of the same width, drawn at the break's knowable time, with `X` and the targets from the placebo path |

## 11. Flow hooks

Questions for `feature-integrator`.

- **Setup qualification:** did the break bar show aggressive buying and an actual trade-through of resting offers?
- **Entry gate:** at the retest, is there visible aggressive buying, which is what covering would look like?
- **Entry timing:** does taker flow turn positive inside the zone or only after price has left it?
- **Early exit:** in Stage A, does flow fade before price reaches `X`?
- **Stop tightening:** when `X` is approached, is the flow still one-sided?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Inheriting S04's leaks | Any zone dated by its base | Same `t_e` rule |
| Flip known before the break closes | Treating a wick above `dist` as a flip | Close-based, at `t_(k_b)` |
| `X` from after the trigger | Using the eventual high as `T1` | `X` frozen at `t_k` |
| Choosing retests that held | Discarding flips that died | Every flip stays in the register with its fate |
| Stage change applied too early | Stage B stop acting in the bar where `T1` filled | Computed at that bar's close, effective next bar |
| Swing used early | A swing low at bar 9 used at bar 10 | Knowable at bar 11, with `Rt = 2` |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 30 to 80 trades per year across BTC and ETH at 1h.

**Cost.** Typical `R` about 80 to 150 bp, by my judgement, since `R` spans the whole zone. At the declared `RT = 12 bp`,
about `0.08R` to `0.15R` at 1x. A gross `+0.2R` on a 100 bp stop dies at `RT = 20 bp`. With so few trades the statistical
problem comes before the cost problem: a low trial count here means the deflated Sharpe ratio will need many months of data. A stop exit pays `stop_slip` in place of `slip`, so 16 bp in all at 1x, under [C16](00_INDEX.md#c16-rounding-and-arithmetic-in-examples).

## 14. Live on an hourly cycle

**Verdict: eligible. Lowest live-eligible `T_d`: 1h. 4h also eligible.** A retest develops over hours, and the rule waits for
a close above the zone, so one late hour is tolerable.

**Late entries.** General checks are in [C17](00_INDEX.md#c17-hourly-live-cycle). Values for this strategy:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 90 minutes at 1h, 150 minutes at 4h, after the trigger close |
| Path | `S0` or `T1` touched, or a `T_d` close below `mid` since `t_k`, voids the setup |
| Chase | `abs(P_dec - C_k) <= 0.75 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(0.75)` and `2.5 * ATR_k` |
| `RR_late` | `T1 - P_dec >= 0.75 * (P_dec - S0)` |
| Thesis | `P_dec > top`: price must still be above the flipped zone |

Using the example in 7.12, with `C_k = 66,440`, `S0 = 66,030`, `X = T1 = 66,900`, `ATR = 280`:

- `P_dec = 66,600`: chase 160 passes against 210, risk 570 against 700, but reward 300 is below 427.5. Result: `STALE_SETUP`,
  reason `RR_LATE`.
- `P_dec = 66,480`: chase 40, risk 450, reward 420 against 337.5. All pass.

**Stops and targets between runs.**

- Touches between runs are resolved from 1m bars at the next run, with `event_time` and `detection_time` recorded. Inside one
  1m bar, the stop is first.
- **Position state is as of each close.** A `T1` fill between runs starts Stage B at its `event_time`. A close before that time is
  evaluated in Stage A, with `T1` unfilled, even if the run that processes it has already walked the fill. So a time stop due at the
  `n = 18` close still fires when `T1` fills after that close and before the run. The fill stands, and the exit applies to the
  quantity that remains. Stage B's rules first apply at the first close at or after the fill, and they act from `effective_from`, so
  the position may carry the Stage A stop for up to about two hours after `T1`.
- Swing confirmations, the inventory clock at `n = 9` and the `T2` re-base are computed at processed closes, in time order.
- Invalidation exits fill after the run that saw them, using the stage as of the close that fired them.
- Stops only tighten: the `P_dec` clamp in C17 can reduce a candidate, and the ratchet then keeps the old stop.

**Backtest reproduction.** `CYCLE` under [C17](00_INDEX.md#c17-hourly-live-cycle), with `C-LATE` for selection, and the flip register
replayed by simulated run in time order. Report the count of `STALE_SETUP` by reason, and the time between a `T1` fill and the
Stage B stop taking effect. I expect the delay to hurt Stage A entries most, since a good retest leaves quickly. That is untested. On the candle stage (`D-31`) no `CYCLE` run may start, so this selection does not run there, under [C18](00_INDEX.md#c18-selection-purge-and-retirement).
