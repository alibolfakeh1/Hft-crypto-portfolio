# S09 UTC session range breakout

Status: draft for leak audit. Not tested. Tier `T0`. Default `T_d` 1h. Long and short. Live-eligible at 1h, see section 14.
Common rules C1 to C17 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

Crypto trades all day, but not evenly. Volume and volatility follow a repeating daily pattern: published work on BTC and ETH finds spikes around
00:00 and 16:00 UTC, a low in volatility near 05:00 UTC, and weaker weekends ([Hansen et al.](https://ar5iv.labs.arxiv.org/html/2109.12142)). This
strategy does not borrow an equity market open. It finds the quietest stretch of the day from the volume data itself, builds a range there, and trades
the first decisive break as the seasonal volume arrives.

**Who is on the other side.** Range traders who were selling the top of a quiet market, whose stops sit just above it, and who meet a much larger volume of
participants arriving in the next hours.

**How much of this is folklore.** The volume seasonality is a measured fact, and it is the most reliable input in the whole set. The trading rule on top is
a different matter. Published work finds time-of-day *return* anomalies in Bitcoin that do not persist, while the *activity* patterns do
([Baur et al.](https://econpapers.repec.org/RePEc:eee:finlet:v:31:y:2019:i:c:p:78-92)). So time of day is used here only as a condition on when a break means
something, and never as a directional signal. Whether it adds anything is unknown.

## 2. Evidence

**Grade for the rule: `LITERATURE`, in other markets.** Opening range breakouts have been tested elsewhere, and none of those tests is on a crypto volume-defined range.

| Source | What it shows | Limits |
|---|---|---|
| [Holmberg, Lönnbark, Lundström](https://swopec.hhs.se/umnees/abs/umnees0845.htm) | An opening range breakout rule is reported with returns significantly above zero and a success rate above a fair game | Keywords point to crude oil futures. Abstract only |
| [Zarattini, Barbon, Aziz](https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/) | A 5-minute opening range breakout on US stocks in play, with strong reported results | Authors' summary page, promotional in tone. Depends on stock selection. Gives no cost assumptions |
| [Replication on five index CFDs](https://www.mql5.com/en/blogs/post/776235) | The gross result reproduced on NQ. After spread and slippage, no market was distinguishable from zero | Not peer reviewed, but it is the honest warning: **the gross edge was about the size of the costs** |
| [Hansen et al.](https://ar5iv.labs.arxiv.org/html/2109.12142) (adjacent) | Hour-of-day and weekend patterns in volatility and volume for BTC and ETH, stronger over time, with funding times as a conjectured cause | Main sample ends in 2021, so patterns may have shifted since. It is why this strategy refits by block |
| [Baur et al.](https://econpapers.repec.org/RePEc:eee:finlet:v:31:y:2019:i:c:p:78-92) (adjacent) | Activity patterns persist, and return anomalies do not | Abstract only |
| [Shen, Urquhart, Wang](https://research.birmingham.ac.uk/en/publications/bitcoin-intraday-time-series-momentum/) (adjacent) | With volume as a proxy for market time, Bitcoin's first half-hour predicts the last, and the authors attribute this to liquidity provision | Abstract only. A different rule |

## 3. Definitions

**Seasonal profile: the only fitted object in this folder.** At the start of each walk-forward block, on the prior 90 days of weekday data for that symbol and venue:

```text
m_h     = mean log(volume in UTC hour h), for h = 0, ..., 23
h_s     = start hour of the W contiguous hours (wrapping at 24) with the lowest sum of m_h
h_end   = h_s + W
h_peak  = hour with the highest m_h in the 8 hours from h_end
T_flat  = h_end + 11
```

These are frozen for the block, per timing contract item 10. Hours are written as clock times, so `h_peak = 16:00` means the bar closing at 16:00 starts that schedule step. My expectation from Hansen et al.
is `h_s` near 04:00 and `h_peak` near 16:00, and the example uses those with `W = 8`. Nothing in the rule depends on that expectation.

**Daily range.** From the `T_d` bars in the window `[h_s, h_end)` on one day:

```text
RH = max(H)    RL = min(L)    RW = RH - RL    RM = (RH + RL) / 2
```

**Expected range and compression ratio.** `ER = ATRD * sqrt(W / 24)` and `CR = RW / ER`. The range qualifies if `0.35 <= CR <= 1.00`.

**Trading day.** Only days whose `h_end` falls on Monday to Friday UTC. A weekend has its own, much weaker, volume pattern.

**Break, long.** On the first close in the 8 hours after `h_end` with `C_k > RH + 0.10 * ATR_k`, `SRV_k >= SRV_min` (default 1.0) and `C_k - O_k >= 0.5 * (H_k - L_k)`.

**Mean volume since entry.** `mean_SRV_b` is the mean `SRV` of all bars from `n = 1` to `b`.

## 4. Knowable times

| Object | Knowable at |
|---|---|
| Profile, `h_s`, `h_peak`, `T_flat` | Frozen at the block start, from data before the block |
| `RH`, `RL`, `RW`, `CR` | The close of the last bar in the range window, which is `h_end` |
| `ATRD` | The last completed UTC day before `h_end` |
| Break, `S0`, targets | `t_k` |
| Schedule step | The close of the bar ending at the scheduled hour, using that bar's close time and never the run's start time |

## 5. Setup rules

**Long,** at `t_k`: a trading day, a qualifying range, a break, `VR_k <= 2.0`, and valid `S0`.

**Short.** The exact mirror, with `C_k < RL - 0.10 * ATR_k` and `O_k - C_k >= 0.5 * (H_k - L_k)`.

One trade per day per symbol, on whichever side breaks first. A later break on the other side is logged and not traded.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | `RH`, `RL`, `RM`, `RW` |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 3 bars after `t_k` |

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency` on the break close, per [C6](00_INDEX.md#c6-entry-fill-r-and-size).

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
S_struct = RM - 0.25 * clip(VR_k, 0.8, 1.5) * ATR_k
S0       = min(S_struct, C_k - R_min(1.0))
```

Skip if `C_k - S0 > 3.0 * ATR_k`. The range midpoint is the stop basis, because a break that falls back through half the quiet range has failed.

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Rule | When | `S_cand`, long |
|---|---|---|
| Volume-arrival check | At `n = 2`, `mean_SRV_b < 1.0` | `RH - 0.25 * ATR_b` |
| Break-even | `C_b >= fill + 1R` | `BE+` |
| Session chandelier | From the first `C_b >= fill + 1R` onward | `HH_b - k(t_b) * ATR_b` |

`HH_b` is the highest high since entry. The session clock `k(t_b)` is set by the close time of the bar:

| `t_b` | `k` |
|---|---|
| Before `h_peak` | 3.0 |
| From `h_peak` to before `h_peak + 4` | 2.0 |
| From `h_peak + 4` onward | 1.25 |

### 7.3 Target logic

At `t_k`, with `D = C_k - S0`:

```text
T1 = max(RH + 1.0 * RW, C_k + 1.25 * D)
T2 = max(RH + 2.0 * RW, C_k + 2.50 * D)
```

**Recompute:**

- Once at the close `t_b = h_peak`, if `mean_SRV_b >= 1.5`: `T2 = max(T2, RH + 3.0 * RW)`. A break met by strong volume has a larger range to work with.
- At each close from `h_peak + 4` onward: `T2 = min(T2, HH_b + 1.0 * ATR_b)`, as the volume is fading.

### 7.4 Scale-out

50 percent at `T1`, the rest at `T2`.

### 7.5 Regime scaling

- `CR` filters out ranges that are too narrow to clear costs, or that have already expanded.
- The buffer in 7.1 scales with `VR`, and `VR_k > 2.0` blocks setups.
- Weekend days are excluded.
- The chandelier multiplier falls as seasonal volume falls, which is a form of liquidity scaling tied to the clock.

### 7.6 Floors

`R_min(1.0)` from [C9](00_INDEX.md#c9-floors).

### 7.7 Time stop

- At the close of `n = 4`, if `C_b < fill + 0.5 * R`, exit at the next open.
- **Hard flat.** At the close of the bar ending `T_flat` (23:00 in the example), exit at the next open. This is about an hour before the 00:00 UTC funding settlement on venues with that schedule.

### 7.8 Invalidation

For `n <= 3`, if `C_b < RH - 0.25 * RW`, the break has fallen back into the range: exit at the next open.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both the stop and a target, the stop is taken. A schedule step at a close applies from the next bar.

### 7.10 `V0S` control

`S0` from 7.1, `m = 2.0`, with `H` replaced by the same hard flat at `T_flat`.

### 7.11 Why this model suits this strategy

Everything here depends on whether volume actually arrives. A break that gets no follow-through in the first two hours is a quiet market drifting, so the stop moves to the edge of the range even if the price has not fallen.
A break that does get volume deserves room while seasonal volume is rising. Past the peak, the same distance is too generous, as the market that carried the move is leaving, so the chandelier tightens by the clock. The target moves
by the same logic: further if volume was strong at the peak, and closer as it fades. The hard flat exists because the idea is a session idea, and nothing in it justifies holding into the next day's unknown range and paying funding.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. BTC, `T_d = 1h`, `ATR = 260`, `VR = 1.0` held flat. Frozen profile: `h_s = 04:00`, `h_end = 12:00`, `h_peak = 16:00`, `T_flat = 23:00`.

- Range: `RH = 67,480`, `RL = 66,980`, `RW = 500`, `RM = 67,230`. `ATRD = 1,600`, so `ER = 923.8` and `CR = 0.54`.
- Break bar closes 14:00: `O 67,360, H 67,620, L 67,330, C 67,590`. Above 67,506, `SRV = 1.6`, body is 79 percent of range.
- `S_struct = 67,230 - 65 = 67,165`. `R_min = max(260, 324.4)`. `D = 425`. So `S0 = 67,165`.
- `T1 = max(67,980, 68,121.25) = 68,121.2`. `T2 = max(68,480, 68,652.5) = 68,652.5`.
- Next open 67,595, so `fill = 67,601.8`, `R = 436.8`, `fill + 1R = 68,038.6`, `BE+ = 67,682.9`.

| `n` | Close | O | H | L | C | Event at this close | Stop after close | Next target |
|---|---|---|---|---|---|---|---|---|
| 1 | 15:00 | 67,595 | 67,760 | 67,540 | 67,720 | | 67,165.0 | `T1` 68,121.2 |
| 2 | 16:00 | 67,720 | 67,930 | 67,680 | 67,890 | Volume check passes. At `h_peak`, `mean_SRV = 1.7`: `T2` raised to 68,980. `k` becomes 2.0 | 67,165.0 | `T1` 68,121.2 |
| 3 | 17:00 | 67,890 | 68,090 | 67,850 | 68,060 | `C >= fill + 1R`: `BE+`. Chandelier `68,090 - 520` is lower | 67,682.9 | `T1` 68,121.2 |
| 4 | 18:00 | 68,060 | 68,210 | 68,020 | 68,180 | `H > T1`: 50% out at 68,121.2 (`+1.19R`). Chandelier `68,210 - 520` | 67,690.0 | `T2` 68,980 |
| 5 | 19:00 | 68,180 | 68,340 | 68,140 | 68,310 | Chandelier | 67,820.0 | `T2` 68,980 |
| 6 | 20:00 | 68,310 | 68,420 | 68,250 | 68,390 | `k` becomes 1.25. Chandelier `68,420 - 325`. `T2 = 68,420 + 260` | 68,095.0 | `T2` 68,680 |
| 7 | 21:00 | 68,390 | 68,460 | 68,280 | 68,330 | Chandelier. `T2` unchanged at the lower value | 68,135.0 | `T2` 68,680 |
| 8 | 22:00 | 68,330 | 68,360 | 68,160 | 68,200 | No new high | 68,135.0 | `T2` 68,680 |
| 9 | 23:00 | 68,200 | 68,250 | 68,090 | 68,120 | `L <= 68,135`: stop, 50% at 68,135 (`+1.22R`) | closed | |

Result before costs: `0.5 * 1.19 + 0.5 * 1.22 = 1.21R`. `R` stayed 436.8 throughout. This path was chosen to exercise the rules and does not represent a typical outcome. Had this position not been stopped at bar 9, the hard flat at the
23:00 close would have closed it at the next open.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `W` | 6, 8 hours | How long a quiet stretch has to be. Longer means a more reliable range, but fewer hours left to trade |
| `SRV_min` | 1.0, 1.5 | How strongly volume must exceed its seasonal norm at the break |

Total: 4 configurations at `T_d = 1h`. Everything else is frozen. I dropped a 15m variant, because it could never run live and because each trial has a cost.

## 9. BTC and ETH notes

- The profile is fitted per symbol and per venue, because volume patterns differ by venue. Hansen et al. report different low-volume and illiquid hours on Binance and Coinbase.
- ETH's profile may be close to BTC's. Same-day breaks in both are nearly one bet, and layer 5 should treat them so.
- `CR` uses each symbol's own `ATRD`, so the qualifying band needs no per-symbol values.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Weekdays with a macro catalyst in US hours | Should work best | Result by date, reviewed after the fact, with no calendar filter used |
| Slow range markets | Should fail with false breaks | Many volume-check tightenings and invalidations |
| Seasonal pattern changes | Should weaken | Compare how `h_s` and `h_peak` move between blocks, and how `SRV` at breaks behaves |
| Any regime | Should beat its [placebo](00_INDEX.md#c15-placebo-control) | The same rule with a range window at a random hour. If the quiet window adds nothing, the seasonal idea has failed |

## 11. Flow hooks

Questions for `feature-integrator`. Trades are available to live runs, so trade-based answers can be used live. Book-based ones cannot.

- **Entry gate:** at the break, is aggressive buying broad, or from a few large prints?
- **Entry gate:** is the break supported by the venue that usually leads, or only by this venue?
- **Early exit:** in the first two hours, does trade flow confirm the volume check, or contradict it?
- **Stop tightening:** after `h_peak`, is flow in the trade's direction fading faster than the seasonal norm?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Seasonal profile on the full sample | Using 2024 volumes to choose `h_s` for 2022 | Fitted before each block, on prior data, and frozen |
| `SRV` with future slots | Median across weeks after the bar | Previous 8 weeks only |
| Range known before its end | Trading a break at 11:00 of a range that ends at 12:00 | `RH` and `RL` are knowable only at `h_end`, and no earlier |
| Choosing the first side with hindsight | Picking whichever side worked | The first qualifying close, in time order |
| Time-of-day picked after a test | Moving the window after seeing results | `h_s` comes from volume alone, by a formula |
| Clock from run time | Using a late run's start time for `k` | Uses the bar's close time |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 60 to 150 trades per year across BTC and ETH: about 260 weekdays, 2 symbols, and perhaps one day in four or five qualifying.

**Cost.** Typical `R` about 60 to 120 bp, by my judgement, and the floor often binds. At the illustrative `RT = 12 bp`, about `0.10R` to `0.20R` at 1x. A gross `+0.2R` on an 80 bp stop dies at `RT = 16 bp`. The opening-range replication above is the warning:
gross results there were about the size of the costs. Stop slippage during the volume rise will also be worse than average, and needs its own measurement.

## 14. Live on an hourly cycle

**Verdict: eligible. Lowest live-eligible `T_d`: 1h.** The session idea is about hours, and a range of 8 hours with a trade window of 8 hours sits naturally on an hourly cycle. This is why I set the default to 1h.

**Late entries.** General checks are in [C17](00_INDEX.md#c17-hourly-live-cycle). Values for this strategy:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 75 minutes after the break close |
| Path | `S0` or `T1` touched since `t_k`, or a `T_d` close below `RH - 0.25 * RW`, voids the setup |
| Chase | `abs(P_dec - C_k) <= 1.0 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(1.0)` and `3.0 * ATR_k` |
| `RR_late` | `T1 - P_dec >= 0.75 * (P_dec - S0)` |
| Thesis | `P_dec > RH`: price must still be outside the range |
| Clock | `t_dec` must be at least 2 hours before `T_flat`. A setup found later than that is void |

Using the example in 7.12, with `C_k = 67,590`, `S0 = 67,165`, `T1 = 68,121.2`, `ATR = 260`:

- `P_dec = 67,800`: chase 210 passes against 260, risk 635 against 780, but reward 321.2 is below 476.3. Result: `STALE_SETUP`, reason `RR_LATE`.
- `P_dec = 67,650`: chase 60, risk 485, reward 471.2 against 363.8. All pass.

**Stops and targets between runs.**

- Touches between runs are resolved from 1m bars at the next run, with `event_time` and `detection_time` recorded. Inside one 1m bar, the stop is first.
- The session clock uses `t_b`, the bar close time, and not the run's start. A late run therefore computes the same `k`, and the same recomputed `T2`, as an on-time run would have. They then act from `t_dec + latency`.
- `n = 2` and `n = 4` checks are based on `T_d` closes, whatever time the run processes them.
- **Hard flat under the cycle.** The decision belongs to the first run that processes the `T_flat` close. Normally that is minutes after 23:00, and the fill comes well before 00:00. If that run is dropped, the next run exits, after 00:00, and funding at 00:00 is charged at its actual time. Nothing hides this: the
  exit shows `lateness` and funding shows separately.
- Stops only tighten: the `P_dec` clamp in C17 can reduce a candidate, and the ratchet then keeps the old stop.
- The frozen profile for live comes from the same block calendar as research. A profile refresh is a logged event, and only applies from the block start.

**Backtest reproduction.** `CYCLE` under [C17](00_INDEX.md#c17-hourly-live-cycle), with `C-LATE` for selection. It must use the same block calendar for the profile, and a dropped run around `T_flat` must carry the position past funding, exactly as live would. Report the share of hard-flat
exits that were late, and the funding they paid. Report `STALE_SETUP` by reason.
