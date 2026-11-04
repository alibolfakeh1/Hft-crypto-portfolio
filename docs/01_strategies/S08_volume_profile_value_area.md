# S08 Volume profile value area

Status: draft for leak audit. Not tested. **Tier `T1`**: profiles need trades. Default `T_d` 1h. Long and short. Live-eligible at
1h only, and 30m is backtest only, see section 14.
Common rules C1 to C17 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

Auction market theory treats the area of heaviest trading in a period as the market's agreed value. When the next period's price
leaves that area, one of two things happens. Either the excursion finds no follow-through and price returns, often rotating across
the area, or trade continues outside and value migrates. This strategy watches each excursion from the prior UTC day's value area and
classifies it. A rejection is traded back into value, and an acceptance is traded onward, after a pullback.

**Who is on the other side.** In a rejection, traders who chased the break of value and are now trapped outside. In an acceptance,
traders who faded the excursion on the expectation of a return.

**How much of this is folklore.** Almost all of it, as far as evidence goes. The theory comes from pit-traded futures with a defined
session. The usual claim, the "80 percent rule", has no source that I could read. In crypto there is no regular session, so a 24-hour
profile is weighted toward the hours with most volume, a known seasonal pattern
([Hansen et al.](https://ar5iv.labs.arxiv.org/html/2109.12142)). "Value" here is a statistical description of the last day, nothing more.

## 2. Evidence

**Grade for the rule: `NONE`.** I found no published test. Searches returned vendor documentation and forum posts only.

| Source | What it shows | Limits |
|---|---|---|
| [CQG, market profile value areas](https://help.cqg.com/cqgic/25/Documents/marketprofilevalueareasmpva.htm) | The construction used below: start at the point of control and expand toward the larger adjacent price until 70 percent is covered. A tie for point of control goes to the price nearest the range middle | Time-based TPO counts, while this document uses volume. Vendor documentation |
| [El Trader Financiado](https://www.eltraderfinanciado.com/en/blog/volume-profile) | States that forum tests of the 80 percent rule hover around 60 percent and depend on how acceptance is defined. Warns that thin sessions and gaps produce false re-entries | Gives no sample or method |
| [Elite Trader thread](https://elitetrader.com/et/threads/trading-with-market-profile.9727/post-598444) | Claims of 70 and 80 percent appear in the thread, along with a single counterexample and no actual test | Forum |
| [Cong et al.](https://nber.org/papers/w30783) | Wash trading averaged over 70 percent of reported volume on unregulated exchanges | A profile from such a venue describes fake trading. Venue choice is not a detail here |
| [Makarov and Schoar](https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:2:p:293-319) | A common component of signed volume explains about 80 percent of Bitcoin returns | One venue's profile only estimates the market's |

`UNVERIFIED`: Steidlmayer's and Dalton's original works were not available to me. I know the 80 percent rule only through the secondary
pages above. **I make no claim about its success rate.**

## 3. Definitions

**Profile,** for a completed UTC day (or composite of completed days), from all trades in that period:

```text
w     = max(tick, 0.0002 * O_day)           # bin width, using the period's first open
bin i = [i*w, (i+1)*w)                      # every trade's quantity goes in its bin
POC   = centre of the bin with the most volume. Tie: nearest the middle of the period's range
```

**Value area.** Start with the `POC` bin. Repeatedly compare the volume of the next bin above and the next bin below the current area, and
add the larger. A tie adds both. If one side has run out, add the other. Stop once the area holds at least 70 percent of the period's volume.
`VAH` is the upper edge of the highest bin, `VAL` is the lower edge of the lowest bin, and `VAW = VAH - VAL`.

**Developing profile.** The same calculation over the current UTC day's trades, up to the current bar close, gives `dPOC`, `dVAH`, `dVAL`. They
are usable only if at least 6 hours of the UTC day have passed.

**Band.** `b_k = 0.10 * ATR_k`.

**Excursion state machine,** for the side below `VAL`. It resets at each UTC roll, and the mirror runs for `VAH`.

```text
INSIDE:
    if C_k < VAL - b_k:
        state = EXCURSION; start = k; x_low = L_k; closes_out = 1; run_out = true

EXCURSION, at each later close:
    x_low = min(x_low, L_k)
    if C_k < VAL - b_k and run_out: closes_out += 1
    else: run_out = false
    if C_k >= VAL + b_k and C_(k-1) >= VAL + b_(k-1) and k - start <= M:
        REJECTION trigger, long. state = DONE
    elif closes_out >= A and mean SRV of those closes >= 1.0:
        state = ACCEPTED; accepted_at = k
    elif k - start > M:
        state = DONE

ACCEPTED, at each close for up to RW bars after accepted_at:
    if H_k >= VAL - 0.25*ATR_k and H_k <= VAL + 0.50*ATR_k and C_k < VAL - b_k and CLV_k <= 0.50:
        ACCEPTANCE trigger, short. state = DONE
    if the window has ended: state = DONE

DONE: no further trade on this side until the UTC roll
```

An excursion gives at most one trade. Once `ACCEPTED`, it cannot produce a rejection trade, even if price later returns.

**Bar counts by timeframe.**

| Constant | 1h | 30m |
|---|---|---|
| `M`, excursion time limit | 4 | 8 |
| `A`, closes outside to accept | 3 | 3 |
| `RW`, pullback window | 8 | 16 |
| `T1` time stop, rejection | 8 | 16 |
| `T1` time stop, acceptance | 12 | 24 |
| Absolute limit | 24 | 48 |
| `V0S` `H` | 8 | 16 |
| `K`, `T2` decay length | 6 | 12 |

## 4. Knowable times

| Object | Knowable at |
|---|---|
| `POC`, `VAH`, `VAL`, `VAW` | 00:00 UTC, at the end of the completed day, plus the data-availability allowance for trades |
| `dPOC`, `dVAH`, `dVAL` | Each bar close, using trades up to that close, from 06:00 UTC onward |
| Excursion, acceptance, triggers | The close that completes them |
| `SRV` | Each close, from the previous 8 weeks only |
| Recomputed targets | Each close, effective next bar |

## 5. Setup rules

**Long by rejection (excursion below `VAL`):** a `REJECTION` trigger, `VAL - x_low <= 1.5 * ATR_k`, `VR_k <= 2.0`, and `POC - C_k >= 0.75 * (C_k - S0)`.

**Short by rejection.** The mirror, from an excursion above `VAH`.

**Long by acceptance (excursion above `VAH`):** the mirror of the acceptance trigger above: `L_k <= VAH + 0.25 * ATR_k`, `L_k >= VAH - 0.50 * ATR_k`,
`C_k > VAH + b_k`, `CLV_k >= 0.50`, and `VR_k <= 2.0`.

**Short by acceptance.** As in the state machine.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | Branch, `POC`, `VAH`, `VAL` |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 3 bars after `t_k` |

The state machine allows at most one trade per side per UTC day, per symbol. The two branches are reported separately.

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency`, per [C6](00_INDEX.md#c6-entry-fill-r-and-size). The two closes inside the value area in the rejection branch are the classic
filter against a single wick being taken as a re-entry.

## 7. Dynamic stop and target model

The long side is shown for both branches.

### 7.1 Initial stop

| Branch | `S_struct` | Floor | Skip if |
|---|---|---|---|
| Rejection | `x_low - 0.25 * clip(VR_k, 0.8, 1.5) * ATR_k` | `R_min(0.75)` | `C_k - S0 > 2.5 * ATR_k` |
| Acceptance | `min(L_k, VAH) - 0.25 * clip(VR_k, 0.8, 1.5) * ATR_k` | `R_min(0.75)` | `C_k - S0 > 2.5 * ATR_k` |

`S0 = min(S_struct, C_k - R_min(0.75))`.

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Branch | Rule | When | `S_cand` |
|---|---|---|---|
| Rejection | Value lock | `C_b >= fill + 1R` | `VAL - 0.25 * ATR_b` |
| Acceptance | Value lock | `C_b >= fill + 1R` | `VAH - 0.25 * ATR_b` |
| Both | Break-even | `T1` filled | `BE+` |
| Both | Value migration | `T1` filled, developing profile usable | `dVAL_b - 0.25 * ATR_b` |

### 7.3 Target logic

**Rejection.** `T1 = POC`. `T2` starts at `VAH`, and after `T1` decays with time, since a rotation that stalls is unlikely to finish. With `q` bars since `T1` filled,
at most `K`:

```text
T2_b = VAH - (q / K) * 0.5 * (VAH - POC)
```

At the UTC roll, at the close of the bar ending 00:00: if the new day's `VAH` is at least `0.5 * ATR_b` above `C_b`, then `VAH`, `POC` and `T2` come from the new profile
and `q` restarts at 0. If not, nothing changes.

**Acceptance.** `T1 = VAH + 0.5 * VAW`. `T2 = VAH + 1.0 * VAW`. Once only, when `dPOC_b > VAH` and the developing profile is usable: `T2 = VAH + 1.5 * VAW`, as today's
value has formed above yesterday's. Prior-day values stay frozen at entry for this branch.

### 7.4 Scale-out

50 percent at `T1`, the rest at `T2`, for both branches.

### 7.5 Regime scaling

- The stop buffer scales with `VR`.
- `VR_k > 2.0` blocks new setups.
- `VAW` scales the acceptance targets with how wide the prior day actually traded.
- The acceptance condition uses `SRV`, so seasonal quiet hours are not mistaken for weak acceptance.

### 7.6 Floors

`R_min(0.75)` from [C9](00_INDEX.md#c9-floors).

### 7.7 Time stop

The bar counts are in section 3. If `T1` is not hit in time, exit at the next open. The absolute limit always applies.

### 7.8 Invalidation

- **Rejection, before `T1`.** `C_b < VAL - b_b`. Price is back outside value, so the rejection was wrong. Exit at the next open.
- **Acceptance, before `T1`.** `C_b < VAH - b_b`. Price is back inside value, so the acceptance was wrong. Exit at the next open.

These lines use the entry day's values and do not change at the roll.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both the stop and a target, the stop is taken. A developing value computed from a bar's trades never governs that bar.

### 7.10 `V0S` control

`S0` from 7.1, for each branch. `m = 2.0`, `H` from section 3.

### 7.11 Why this model suits this strategy

Both branches have a single, price-defined failure: a rejection that goes back outside value, or an acceptance that comes back in. So the invalidation lines sit exactly there,
and they act before a more distant stop. Once the trade is working, the question changes from "was the excursion rejected?" to "is value moving with the position?". The developing
value area answers that directly and from trades, so it trails the stop instead of a price multiple. It also rests on real trading activity, so it does not tighten simply because
of a short spike. A rotation runs out of energy with time, so the far target decays. An accepted move that builds today's value above yesterday's has earned a further target. This
is the only strategy in the set whose exit is built from volume-at-price.

### 7.12 Worked example, long, rejection branch

Invented numbers, for checking arithmetic only. BTC, `T_d = 1h`, `ATR = 350`, `VR = 1.0` held flat. Prior day: `POC = 67,200`, `VAH = 67,900`, `VAL = 66,500`. `b = 35`.

- Close at 03:00 of 66,440 is below 66,465, so an excursion starts. The bar closing 04:00 sets `x_low = 66,180`.
- Closes at 05:00 (66,560) and 06:00 (66,610) are both at or above 66,535. Trigger at 06:00, with `k - start = 3`, within `M = 4`. Depth 320 is within 525.
- `S_struct = 66,180 - 87.5 = 66,092.5`. `R_min = max(262.5, 319.7)`, so the structure stop stands, and `C - S0 = 517.5`.
- `T1 = POC = 67,200`, 590 away, against 388 required. `T2 = VAH = 67,900`.
- Next open 66,615, so `fill = 66,621.7`, `R = 529.2`, `fill + 1R = 67,150.9`, `BE+ = 66,701.6`.

Developing `dVAL` values are invented for the example, as they would come from trades.

| `n` | Close | O | H | L | C | `dVAL` | Event at this close | Stop after close | `T2` |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 07:00 | 66,615 | 66,760 | 66,570 | 66,730 | | | 66,092.5 | 67,900.0 |
| 2 | 08:00 | 66,730 | 66,900 | 66,700 | 66,860 | | | 66,092.5 | 67,900.0 |
| 3 | 09:00 | 66,860 | 67,050 | 66,820 | 67,010 | | | 66,092.5 | 67,900.0 |
| 4 | 10:00 | 67,010 | 67,190 | 66,960 | 67,170 | | `C >= fill + 1R`: value lock, `VAL - 87.5` | 66,412.5 | 67,900.0 |
| 5 | 11:00 | 67,170 | 67,310 | 67,130 | 67,280 | 66,540 | `H > T1`: 50% out at 67,200 (`+1.09R`). `BE+` | 66,701.6 | 67,900.0 |
| 6 | 12:00 | 67,280 | 67,400 | 67,220 | 67,370 | 66,640 | Migration 66,552.5 is lower, no change. `q = 1` | 66,701.6 | 67,841.6 |
| 7 | 13:00 | 67,370 | 67,470 | 67,300 | 67,440 | 66,780 | Migration 66,692.5 is lower. `q = 2` | 66,701.6 | 67,783.3 |
| 8 | 14:00 | 67,440 | 67,520 | 67,360 | 67,400 | 66,900 | Migration `dVAL - 87.5`. `q = 3` | 66,812.5 | 67,725.0 |
| 9 | 15:00 | 67,400 | 67,450 | 67,250 | 67,290 | 66,990 | Migration. `q = 4` | 66,902.5 | 67,666.6 |
| 10 | 16:00 | 67,290 | 67,340 | 67,120 | 67,170 | 67,060 | Migration. `q = 5` | 66,972.5 | 67,608.3 |
| 11 | 17:00 | 67,170 | 67,220 | 66,940 | 66,990 | | `L <= 66,972.5`: stop, 50% at 66,972.5 (`+0.66R`) | closed | |

Result before costs: `0.5 * 1.09 + 0.5 * 0.66 = 0.88R`. `R` stayed 529.2 throughout. This path was chosen to exercise the rules and does not represent a typical outcome.

**Acceptance branch, in brief.** Same prior day. Three closes above `VAH + b` with mean `SRV` of 1.2, then a pullback bar with `L = 67,880`, `C = 67,990`. `S_struct = min(67,880, 67,900) - 87.5 = 67,792.5`, only
197.5 away. `R_min = max(262.5, 326.4)`, so the floor binds: `S0 = 67,663.6`. `T1 = 67,900 + 700 = 68,600`, `T2 = 69,300`. A close below 67,865 before `T1` exits at the next open.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `T_d` | 1h, 30m | 1h is the live configuration. 30m is the classical period and measures what the hourly cycle gives up |
| Profile | 1 completed UTC day, composite of 3 days | A single day is the classic. A composite may be steadier |

Each configuration has two branches, reported separately: rejection and acceptance. Total: 8 trials. All stop, target and state machine constants are frozen.

## 9. BTC and ETH notes

- Same rules. Bin width is a percentage of price, so it scales with each symbol.
- ETH trade volume can be a smaller and more concentrated sample, which can make `POC` jump between days. Report how far `POC` moves per day, by symbol.
- Build the profile on one venue only. Profile shape differs between venues, and a low-quality venue would describe fake trading.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Balanced days following balanced days | Rejection should do best | Result by prior-day range and by whether the current day overlaps value |
| Trend days and strong migration | Acceptance should do best, rejection should fail | Results by branch and day type measured afterwards |
| Thin weekends | Profiles are based on less volume, and may be less meaningful | Result by day of week of the profile |
| Both branches losing together | The classifier adds nothing | Compare each branch with its [placebo](00_INDEX.md#c15-placebo-control), using a random band of the same width |

## 11. Flow hooks

Questions for `feature-integrator`. Trades are available to live runs, so trade-based answers can be used live. Book-based ones cannot.

- **Classification:** does trade flow during the excursion distinguish rejection from acceptance before the closes do?
- **Entry gate:** at the re-entry, are aggressive sellers still pressing, or have they stopped?
- **Entry timing:** on the acceptance pullback, does aggressive selling shrink?
- **Early exit:** does flow in the developing profile suggest that value has stopped migrating?
- **Stop tightening:** near `T1`, does the flow weaken?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Profile from the running day | Using today's trades in "prior" value | Prior profile changes only at 00:00 UTC, from a completed period |
| Developing value with later trades | `dVAL` at 11:00 using trades to 12:00 | Trades at or before the bar close only |
| Bin width from the day's range | `w` scaled by a range not yet known in the developing profile | `w` uses the first open only |
| `POC` tie rule on a developing profile | Using the final range to break a tie | Range so far |
| Choosing a branch after the fact | Calling a trade a rejection because it returned | The state machine classifies in time order, and each close's state is final |
| Trade timestamps | Using exchange time with no availability allowance | Declared allowance, per timing contract item 6 |
| Roll applied to invalidation | Moving the invalidation line to the new day | The entry day's values are fixed for invalidation |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 60 to 150 trades per year across BTC and ETH at 1h, both branches together.

**Cost.** Typical `R` about 60 to 120 bp at 1h, by my judgement. At the illustrative `RT = 12 bp`, about `0.10R` to `0.20R` at 1x. A gross `+0.2R` on an 80 bp stop dies at `RT = 16 bp`. The rejection branch has the nearer
target, which makes it more cost-sensitive than the acceptance branch. Testable history is limited by `T1`, still to be confirmed per venue.

## 14. Live on an hourly cycle

**Verdict: eligible at 1h only. Lowest live-eligible `T_d`: 1h.** 30m stays backtest only. A run would see two 30m closes at once, and nothing would be gained except a worse entry. The value area lasts all day, and a rotation across it takes
hours, so 1h can work, though it enters later than the classic rule. Live runs see trades since the last run, which this needs.

**Late entries.** General checks are in [C17](00_INDEX.md#c17-hourly-live-cycle). Values for this strategy:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 75 minutes after the trigger close |
| Roll | If a UTC roll lies between `t_k` and `t_dec`, the setup is void: its reference profile has been replaced |
| Path | `S0` or `T1` touched since `t_k`, or a `T_d` close that fires the branch's invalidation, voids the setup |
| Chase | `abs(P_dec - C_k) <= 0.75 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(0.75)` and `2.5 * ATR_k` |
| `RR_late` | `T1 - P_dec >= 0.75 * (P_dec - S0)` |
| Thesis | Rejection: `P_dec >= VAL + b_k`. Acceptance: `P_dec > VAH + b_k` |

Using the example in 7.12, with `C_k = 66,610`, `S0 = 66,092.5`, `T1 = 67,200`, `ATR = 350`:

- `P_dec = 66,800`: chase 190 passes against 262.5, risk 707.5 against 875, but reward 400 is below 530.6. Result: `STALE_SETUP`, reason `RR_LATE`.
- `P_dec = 66,650`: chase 40, risk 557.5, reward 550 against 418. All pass.

**Stops and targets between runs.**

- Touches between runs are resolved from 1m bars at the next run, with `event_time` and `detection_time` recorded. Inside one 1m bar, the stop is first.
- `dVAL`, `dVAH` and `dPOC` are computed for each processed 1h close, from trades at or before that close and not from trades up to the run. Late runs therefore produce the same values, and they act from `t_dec + latency`.
- `q` counts `T_d` closes since the `T1` fill, so the decay in 7.3 does not depend on when runs happen.
- The prior profile changes when a run first processes the 00:00 close. A late or dropped run around 00:00 delays the roll updates only.
- If any trades in the span are missing, the run logs `DATA_GAP` for this symbol and computes no partial profile. Touches are still resolved if 1m bars are complete.
- Stops only tighten: the `P_dec` clamp in C17 can reduce a candidate, and the ratchet then keeps the old stop.

**Backtest reproduction.** `CYCLE` under [C17](00_INDEX.md#c17-hourly-live-cycle) at 1h, with `C-LATE` for selection, with profiles rebuilt the same way as live and trades cut off at the simulated run. Report the branches separately, and also report the
30m `IDEAL` result beside the 1h `CYCLE` result, labelled, as a direct measure of the classical rule against what can actually run.
