# S02 Pivot breakout, acceptance and retest

Status: revised after the leak audit of 2026-11-04, awaiting re-audit. Not tested. Tier `T0`. Default `T_d` 1h. Long and
short. Live-eligible at 1h, see section 14.
Common rules C1 to C18 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

This is the other side of S01. When a level is crossed and price stays beyond it for several closes, the
people who faded it are wrong and their stops sit nearby. FX order data shows stop-loss orders clustering
just beyond widely watched prices, and shows that those orders tend to intensify trends once crossed
([Osler 2001](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html),
[Osler 2002](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.html)).

**Who is on the other side.** Traders who sold the level and now hold losing shorts, and late breakout
buyers who chased the first move and get shaken out on the retest. The retest also gives anyone who missed
the break a place to buy with a defined risk.

**Why acceptance and retest.** A single close beyond a level is weak information. Three closes with normal
seasonal volume say that trading continued there. The retest then gives a location close to the failure
point, so the stop is short relative to the next level.

**How much of this is folklore.** "Acceptance" is a practitioner word with no agreed definition. The
definition below is mine, stated exactly so it can be tested. Nothing I found tests this sequence.

## 2. Evidence

**Grade for the rule: `NONE`.** I found no test of acceptance followed by a retest at pivots.

| Source | Relevance | Limits |
|---|---|---|
| [Osler 2001](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html) | In 9,667 conditional FX orders at one bank, stop-loss buys were placed about twice as often at rates ending 01 to 10 as at rates ending 90 to 99 (14.4 against 7.4 percent), so stops sit just beyond round numbers | FX round numbers, not pivots. One bank |
| [Osler 2002](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.html) | Trends are unusually fast at documented stop-loss cluster levels. Most results are significant for hours, not days | FX. I read the abstract and introduction only |
| [Osler 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html) | Reports earlier work: Curcio et al. found that trending after a level breach does not hold on average in FX, though it may hold in strong trends. Brock et al. found it holds on the S&P 500 daily, but the profit may not cover costs | Secondary account of those two studies. It cuts against an unconditional breakout |
| [Hudson and Urquhart](https://ideas.repec.org/a/spr/annopr/v297y2021i1d10.1007_s10479-019-03357-1.html) | Nearly 15,000 daily rules, with predictability in several coins but none for Bitcoin in the out-of-sample period | Daily rules. Abstract only |

**Reading.** The stop-cluster mechanism has real support in FX. Whether pivots attract such clusters in
crypto is unknown. On its best evidence the effect lasts hours, which is consistent with a 1h decision
timeframe and with an exit that does not assume a multi-week trend.

## 3. Definitions

**Levels.** The S01 formula, with two extra target-only levels:

```text
P  = (H + L + C) / 3
R1 = 2*P - L        S1 = 2*P - H
R2 = P + (H - L)    S2 = P - (H - L)
R3 = H + 2*(P - L)  S3 = L - 2*(H - P)     # used as targets only
```

**Tradable set.** Daily `{S2, S1, P, R1, R2}`, and optionally weekly `{S1, P, R1}`, from the last completed
UTC day and week. A bar is evaluated against the set in force at its open, under
[C2](00_INDEX.md#c2-bars-and-calendar).

**Band.** `b_k = 0.10 * ATR_k`.

**Upward break of `l` at bar `k`.** `C_k > l + b_k` and `C_(k-1) <= l + b_(k-1)`.

**Acceptance.** The break bar and the following bars, `acc` bars in all (default 3), all close above
`l + b`, and their mean `SRV >= 1.0`. Acceptance is reached at the close of the last of these. If any fails,
the sequence ends. `l` stays available for a new break.

**Retest, long.** A bar `k` within 12 bars after acceptance, with no close at or below `l - b` in between:

| # | Condition |
|---|---|
| a | `L_k <= l + 0.25 * ATR_k` |
| b | `L_k >= l - 0.50 * ATR_k` |
| c | `C_k > l + b_k` |
| d | `CLV_k >= 0.50` |

A sequence ends when its level's set rolls, since a bar is evaluated against the set in force at its open, so a retest on the roll bar itself still counts. If two levels retest on one bar, use the one nearest the close.

**Base level.** `l_base = l` is kept for the life of the trade, even after the roll.

## 4. Knowable times

| Object | Knowable at |
|---|---|
| Daily and weekly levels | 00:00 UTC and Monday 00:00 UTC, from completed periods only. They first act on the bar that opens at that time |
| Break | Close of the break bar |
| Acceptance | Close of the last acceptance bar, never at the break |
| `SRV` | Each bar's close, with the median from the previous 8 weeks only |
| Retest, `S0`, targets | `t_k` of the retest bar |
| Ladder acceptance during the trade | Close of the second accepted bar, effective next bar |

## 5. Setup rules

**Long.** Upward break, acceptance, retest, `VR_k <= 2.0`, and `S0` and `T1` valid under section 7.

**Short.** The exact mirror: break below, closes below `l - b`, retest with `H_k >= l - 0.25 * ATR_k`,
`H_k <= l + 0.50 * ATR_k`, `C_k < l - b_k`, `CLV_k <= 0.50`.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | `l_base` |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 4 bars after `t_k` |

If no retest comes within 12 bars, log `NO_RETEST` with the counterfactual of buying at acceptance. At most
one trade per level per UTC day. The day is that of `t_k`, so a weekly level can trade once on each day.

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency`, where `k` is the retest bar, per [C6](00_INDEX.md#c6-entry-fill-r-and-size).
Buying the acceptance close instead would be a different strategy, and is not traded in `V0`. It is
reported through the `NO_RETEST` counterfactual, so the cost of waiting can be measured.

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
k_s      = 0.50 * clip(VR_k, 0.8, 1.5)
S_struct = min(L_k, l_base) - k_s * ATR_k
S0       = min(S_struct, C_k - R_min(1.0))
```

Skip if `C_k - S0 > 2.5 * ATR_k`.

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Rule | When | `S_cand`, long |
|---|---|---|
| Level tighten | `C_b >= fill + 1.0 * R` | `l_base - 0.25 * ATR_b` |
| Participation check | At `n = 6`, mean `SRV` of bars 1 to 6 is below 0.8 | `l_base - 0.10 * ATR_b` |
| Break-even | `C_b >= fill + 1.5 * R` | `BE+` |
| `T1` reached | `T1` filled | `T1_level - 1.5 * ATR_b` |
| Ladder ratchet | A level `m` above `l_base` has two consecutive closes above `m + b` | `m - 0.50 * ATR_b` |

Rungs for the ladder are the current tradable set plus `R3`. Both closes must come from bars that open at or after
the rung's knowable time, so a close at the roll itself does not count toward a rung of the new set.

### 7.3 Target logic

- At `t_k`: `T1` is the nearest level at least `1.5 * (C_k - S0)` above `C_k`, including `R3` as a candidate.
  `T2` is the next level above that. If none exists, `T2 = T1 + (T1 - l_base)`.
- At the UTC roll, at the close of the bar ending 00:00: unfilled targets are rebuilt from the new set, with `R3` among the candidates as at `t_k`. If `T1` is
  unfilled, it becomes the nearest level at least `0.5 * ATR_b` above `C_b` and at or above `fill + 1.5 * R`, and `T2`
  is the next above. If `T1` has filled, `T2` becomes the nearest level at least `0.5 * ATR_b` above `C_b`. If none
  exists, the old target stays.

Targets may move either way, and the stop never moves back with them.

### 7.4 Scale-out

50 percent at `T1`, the rest at `T2`.

### 7.5 Regime scaling

- `k_s` scales with `VR`, as in 7.1.
- `VR_k > 2.0` blocks new setups. In a volatility shock, acceptance over three closes means little.
- The acceptance condition uses seasonal volume, so a quiet UTC hour is not penalised for its normal
  volume. Weekend bars must pass the same `SRV` test against their own weekend slots.

### 7.6 Floors

`R_min(1.0)` from [C9](00_INDEX.md#c9-floors). `a = 1.0` because a 1h retest needs room for one normal bar.

### 7.7 Time stop

If `T1` is not hit by the close of `n = 24`, exit at the next open. Absolute limit `n = 72`.

### 7.8 Invalidation

If `C_b < l_base - b_b`, acceptance has been lost: exit at the next open. It stays active for the life of
the trade.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both the stop and `T1`, the stop is taken. A
ladder step found at a close acts from the next bar.

### 7.10 `V0S` control

`S0` from 7.1, `m = 2.5`, `H = 48` bars.

### 7.11 Why this model suits this strategy

A breakout fails by re-entry: price returns below the level it was supposed to have left. So the first line
of defence is a close-based invalidation at that level, and not a volatility trail that ignores it. A
breakout that works keeps clearing further levels, and each accepted level is a new line that should hold,
so the stop climbs in the same units the thesis is written in. The participation check addresses a specific
weakness: a move that happens on thin seasonal volume is easily reversed, and this rule responds to that
even if price has not fallen yet. Literature on stop cascades points to hours rather than days, so a time
stop at one day without progress is appropriate.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. Prior UTC day: `H = 3,480`, `L = 3,320`, `C = 3,440`. So
`P = 3,413.33`, `R1 = 3,506.67`, `R2 = 3,573.33`, `R3 = 3,666.67`. `ATR = 18`, `VR = 1.0` held flat.
`b = 1.8`. `l_base = 3,506.67`.

- Closes 13:00, 14:00, 15:00 are 3,512, 3,520, 3,531, all above 3,508.47. Mean `SRV = 1.3`. Accepted at 15:00.
- Retest bar closes 18:00: `O 3,528, H 3,530, L 3,510, C 3,526`. `L` is at or below 3,511.17 and at or above
  3,497.67, `CLV = 0.80`.
- `S_struct = 3,506.67 - 9 = 3,497.66`. `R_min = max(18, 16.9) = 18`. So `S0 = 3,497.66`.
- `T1 = R2 = 3,573.33`, 47.33 away against the required 42.5. `T2 = R3 = 3,666.67`.
- `R_dec = 3,526 - 3,497.66 = 28.34`. The collar is 3,535, and the next open of 3,527 is inside it.
- So `fill = 3,527.35` and `R = 29.69`. `BE+ = 3,531.58`.

| `n` | Close | O | H | L | C | Event at this close | Stop after close | `T1` | `T2` |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 19:00 | 3,527 | 3,536 | 3,522 | 3,533 | | 3,497.66 | 3,573.33 | 3,666.67 |
| 2 | 20:00 | 3,533 | 3,541 | 3,529 | 3,538 | | 3,497.66 | 3,573.33 | 3,666.67 |
| 3 | 21:00 | 3,538 | 3,552 | 3,534 | 3,549 | | 3,497.66 | 3,573.33 | 3,666.67 |
| 4 | 22:00 | 3,549 | 3,560 | 3,544 | 3,558 | `C >= fill + 1R`: level tighten, `l_base - 4.5` | 3,502.16 | 3,573.33 | 3,666.67 |
| 5 | 23:00 | 3,558 | 3,565 | 3,551 | 3,562 | | 3,502.16 | 3,573.33 | 3,666.67 |
| 6 | 00:00 | 3,562 | 3,570 | 3,556 | 3,568 | `SRV` check passes. UTC roll: day `H 3,570, L 3,405, C 3,568`, so `R1 = 3,623.67`, `R2 = 3,679.33` | 3,502.16 | 3,623.67 | 3,679.33 |
| 7 | 01:00 | 3,568 | 3,592 | 3,563 | 3,588 | `C >= fill + 1.5R`: `BE+` | 3,531.58 | 3,623.67 | 3,679.33 |
| 8 | 02:00 | 3,588 | 3,604 | 3,584 | 3,600 | Second close above new `P + b = 3,516.13` from a bar opening after the roll. Ladder candidate 3,505.33 is below the stop, no change | 3,531.58 | 3,623.67 | 3,679.33 |
| 9 | 03:00 | 3,600 | 3,612 | 3,596 | 3,608 | | 3,531.58 | 3,623.67 | 3,679.33 |
| 10 | 04:00 | 3,608 | 3,626 | 3,603 | 3,618 | `H > T1`: 50% out at 3,623.66 (`+3.24R`). `T1_level - 27` | 3,596.66 | filled | 3,679.33 |
| 11 | 05:00 | 3,618 | 3,640 | 3,614 | 3,636 | First close above 3,625.47 | 3,596.66 | | 3,679.33 |
| 12 | 06:00 | 3,636 | 3,650 | 3,630 | 3,646 | Second close: ladder, `3,623.67 - 9` | 3,614.66 | | 3,679.33 |
| 13 | 07:00 | 3,646 | 3,655 | 3,622 | 3,628 | | 3,614.66 | | 3,679.33 |
| 14 | 08:00 | 3,628 | 3,632 | 3,609 | 3,615 | `L <= 3,614.66`: stop, 50% at 3,614.66 (`+2.94R`) | closed | | |

Result before costs: `0.5 * 3.24 + 0.5 * 2.94 = 3.09R`. `Result_B = (0.5 * 96.31 + 0.5 * 87.31) / 28.34 = 3.24`. `R` stayed
29.69 throughout. This path was chosen to
exercise the rules and does not represent a typical outcome. If instead bar 3 had closed at 3,500, below
`l_base - b = 3,504.87`, the position would have exited at the next open by invalidation, at a loss well
under `1R`.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `acc` | 2, 3 | Two closes is the shortest definition that is not a single print. Three is stricter and gives fewer trades |
| Level set | Daily only, daily plus weekly | Weekly levels are rarer and may be better watched, which is untested |

Total: 4 configurations. All stop and target constants are frozen and not searched. The default line under [C18](00_INDEX.md#c18-selection-purge-and-retirement) is `acc` 3, daily levels only.

## 9. BTC and ETH notes

- The same rules apply. Acceptance is normalised by `ATR` and `SRV`, so no symbol-specific constants exist.
- ETH breakouts often follow BTC by a short time. A BTC break and an ETH break on the same day are close to
  one bet. Layer 5 owns that limit.
- ETH has a larger percent range, so levels are further apart in percent and `T1` is often further away in
  `R`. This is my judgement, to be measured at G3.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Trending with rising seasonal volume | Should work best | Result by `SRV` tercile at acceptance, and by day type measured afterwards |
| Range-bound | Should fail through re-entry | High share of invalidation exits |
| Volatility shocks | Blocked by `VR` | Count of blocked setups and their counterfactual |
| Strong trends without pullbacks | Misses them, by design | `NO_RETEST` counterfactual against `V0` |
| Any regime | Should beat its [placebo](00_INDEX.md#c15-placebo-control) | Same sequence on random levels |

## 11. Flow hooks

Questions for `feature-integrator`.

- **Setup qualification:** during the three acceptance closes, did aggressive buying persist or was the
  move carried by a few prints?
- **Entry gate:** at the retest, is aggressive selling being absorbed above the level, or is it pushing through?
- **Entry timing:** does taker flow turn positive during the retest bar or only well after it?
- **Early exit:** does flow on a later retest of the ladder level turn clearly against the position before
  the close-based invalidation can fire?
- **Stop tightening:** does the participation check fire earlier if trade flow is measured directly rather
  than through candle volume?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Acceptance dated at the break | Treating a level as accepted at the first close, knowing that two more closes held | Acceptance knowable only at the last accepted close |
| Levels from a partial day | Rungs built from today's running high and low | Rungs change only at 00:00 UTC |
| `SRV` window including the current week's future slots | Median over a centred window | Previous 8 weeks only |
| Roll moving the base level | Invalidating against the new day's `R1` | `l_base` is fixed at entry |
| Ladder used in the bar it was confirmed | Stop raised at the close of bar 12 acting inside bar 12 | Effective from the next bar |
| Choosing retests with hindsight | Keeping only retests that held | The rule evaluates every bar in the 12-bar window in order, and a close beyond `l - b` ends it |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 80 to 160 trades per year across BTC and ETH.

**Cost.** Typical `R` of about 80 to 120 bp, by my judgement. At the declared `RT = 12 bp`, cost is about
`0.10R` to `0.15R` per trade at 1x, and `0.3R` to `0.45R` at 3x. A gross expectancy of `+0.2R` on a 100 bp stop
breaks even at `RT = 20 bp`. It is less cost-sensitive than S01, because it waits for a 1h location and pays
less in `R` terms. The real risk is the low hit rate typical of breakouts in ranges, not the fee. A stop exit pays `stop_slip` in place of `slip`, so 16 bp in all at 1x, under [C16](00_INDEX.md#c16-rounding-and-arithmetic-in-examples).

## 14. Live on an hourly cycle

**Verdict: eligible. Lowest live-eligible `T_d`: 1h.** The sequence takes hours to form and the thesis is held
for hours to days, so one late hour hurts the entry location but does not remove the idea.

**Late entries.** General checks are in [C17](00_INDEX.md#c17-hourly-live-cycle). Values for this strategy:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 90 minutes after the retest bar's close |
| Path | `S0` or `T1` touched, or a `T_d` close at or below `l_base - b` since `t_k`, voids the setup |
| Chase | `P_dec - C_k <= 0.75 * ATR_k` and `C_k - P_dec <= 0.75 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(1.0)` and `2.5 * ATR_k` |
| `RR_late` | `T1 - P_dec >= 1.0 * (P_dec - S0)` |
| Thesis | `P_dec > l_base + b_k`. Price must still be above the level |

If a UTC roll falls between `t_k` and `t_cut`, the setup's `T1` and `T2` are still the ones from `t_k`, for these checks
and after the fill. The roll rule in 7.3 acts only on a position already open at the roll close, so it first applies to
this trade at the next roll. Setups older than `A_max` are not re-armed. The level can trade again on a new break.

Using the example in 7.12, with `C_k = 3,526`, `S0 = 3,497.66`, `T1 = 3,573.33` and `ATR = 18`:

- `P_dec = 3,536` at a run 52 minutes late: chase 10 passes against 13.5, risk 38.34 passes against 45, but
  reward 37.33 is below 38.34. Result: `STALE_SETUP`, reason `RR_LATE`.
- `P_dec = 3,530`: chase 4, risk 32.34, reward 43.33. All pass. The entry goes out with its collar at 3,539, and the fill
  is the first 1m open with `open_time >= t_dec + latency`.

**Stops and targets between runs.**

- Stops and targets touched between runs are resolved from 1m bars at the next run, with both `event_time` and
  `detection_time` recorded. Inside one 1m bar, the stop is first.
- All rules in 7.2, including the `n = 6` participation check and the ladder, are computed from 1h closes during
  the run, with position state as of each close. They act from `effective_from`.
- If a run is dropped, two closes are processed at once, in time order. Ladder acceptance can complete on the
  second of them. The stop that was active before the run governs the whole gap.
- The invalidation in 7.8 and the time stops fill after the run that saw them. A long gap can therefore turn a
  small invalidation loss into a larger one, and this cost is real and must appear in `CYCLE` results.
- The stop is never lowered, even when a late close produces a candidate above `P_dec`. The `P_dec` clamp in C17
  reduces the candidate, and the ratchet holds the old stop if the candidate falls below it.
- The UTC roll is applied at the first run that processes the 00:00 close. Live flow gates may use trades only.
- The roll rule's `fill + 1.5 * R` term is fill-based, so under `.T` it follows the
  [rule against a later fill raising a target](00_INDEX.md#c17-hourly-live-cycle).

**Backtest reproduction.** `CYCLE` under [C17](00_INDEX.md#c17-hourly-live-cycle), with `C-LATE` for selection.
Report the count of `STALE_SETUP` by reason, and compare the `NO_RETEST` counterfactual under both modes. Because
this strategy waits for a retest, I expect a modest `IDEAL` minus `CYCLE` gap, mostly from `RR_LATE` rejections
and later invalidation fills. That expectation is untested. On the candle stage (`D-31`) no `CYCLE` run may start, so this selection does not run there, under [C18](00_INDEX.md#c18-selection-purge-and-retirement).
