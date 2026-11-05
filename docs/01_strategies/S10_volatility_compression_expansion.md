# S10 Volatility compression expansion

Status: revised after the leak audit of 2026-11-04, awaiting re-audit. Not tested. Tier `T0`. Default `T_d` 4h. Long and short.
Live-eligible at 4h and 1h, see section 14.
Common rules C1 to C18 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

Volatility clusters. Quiet periods tend to be followed by quiet periods, but volatility also returns to its normal level, and when it does the move can be large. In BTC, autocorrelation of absolute returns decays slowly and stays clearly positive
([de Sousa Filho et al.](https://ar5iv.labs.arxiv.org/html/2004.05870)). This strategy finds a statistically unusual quiet state, draws the box that state left behind, and takes the first close out of the box.

**Who is on the other side.** Range sellers and option-like premium collectors who have grown used to a low-volatility range, with stops beyond its edges. In perpetuals, leverage tends to build during quiet periods, which can add forced flow to the first real move. That last
point is my judgement, not a finding.

**Why this instead of a fair value gap.** See [the index](00_INDEX.md#why-ten-and-why-compression-rather-than-the-fair-value-gap). In short, this is the only candidate whose reason to trade is a volatility state and not a price level.

**How much of this is folklore.** Compression and later expansion is real as a statement about volatility. It says nothing about direction, and clustering actually argues that a quiet market usually stays quiet for some time. The classic "squeeze" trading rule has been tested, and the result is
not flattering.

## 2. Evidence

**Grade for the rule: `LITERATURE`, in other markets, and unfavourable in recent data.**

| Source | What it shows | Limits |
|---|---|---|
| [Fang, Jacobsen, Qin, via CXO Advisory](https://www.cxoadvisory.com/big-ideas/when-bollinger-bands-snapped/) | On 14 stock indexes back to as early as 1885, Bollinger breakout and squeeze signals had information in the full sample. It decayed over time: after 2001 the average squeeze spread was about `-0.07%` per day, against `+0.01%` for the market. The authors attribute this to adaptation by the market | I read a secondary summary, not the paper. Stock indexes, daily. **Directly unfavourable** |
| [de Sousa Filho et al.](https://ar5iv.labs.arxiv.org/html/2004.05870) (adjacent) | Volatility clustering in Bitcoin on 5-hour returns, 2013 to 2020, with lag-1 autocorrelation of absolute returns about 0.39, and very heavy tails | Says nothing about direction |
| [Zarattini, Pagani, Barbon, via CXO](https://www.cxoadvisory.com/technical-trading/crypto-asset-trend-following-strategies/) (adjacent) | A long-only ensemble of daily close breakouts with a midpoint trailing stop and volatility sizing is reported positively on crypto | Long only, no compression condition. I read a secondary summary, and in-sample status is unclear |
| [Hudson and Urquhart](https://ideas.repec.org/a/spr/annopr/v297y2021i1d10.1007_s10479-019-03357-1.html) (adjacent) | No predictability for Bitcoin out of sample across nearly 15,000 daily rules | Daily, abstract only |
| [Hansen et al.](https://ar5iv.labs.arxiv.org/html/2109.12142) (adjacent) | Weekend volatility and volume are lower | Means compression has to be measured with care across weekends |

**Reading.** Compression predicts that volatility will rise eventually. Nothing here supports the direction call. The rule takes the first close out of the box because that is the only thing the price offers, and the exit is built to survive being wrong often.

## 3. Definitions

**Band width.** With `sd_k` the population standard deviation of the last 20 closes, and `SMA_k` their mean:

```text
BBW_k = 4 * sd_k / SMA_k
PR_k  = share of BBW values in the last 30 days of bars (including k) that are <= BBW_k
CF_k  = PR_k <= PR_max                 # compression flag, default PR_max = 0.10
```

`PR_k` is undefined with fewer than half of the 30-day window's values, in the same way as `VR` in
[C3](00_INDEX.md#c3-indicators). A condition using an undefined value fails, and nothing is filled.

**Box.** Over the `B` bars ending at `k - 1` (default `B = 12`):

```text
BH = max(H)    BL = min(L)    BoxH = BH - BL    BM = (BH + BL) / 2
```

**Armed.** The box is valid when at least 3 of the bars `k - 6, ..., k - 1` have `CF`, and `BoxH <= 4.0 * ATR_(k-1)`.

**Breakout, long, at bar `k`.**

| # | Condition |
|---|---|
| a | Armed |
| b | `C_k > BH + 0.10 * ATR_(k-1)` |
| c | `TR_k >= 1.0 * ATR_(k-1)` |
| d | `SRV_k >= 1.0`, or `>= 1.25` on Saturday and Sunday UTC |

**Re-arm.** After any breakout, traded or not, this state is spent until 12 bars have passed and the armed condition is met again.

**Entry volatility.** `ATR_e = ATR_k` at the breakout bar. `VRe_b = ATR_b / ATR_e`.

## 4. Knowable times

| Object | Knowable at |
|---|---|
| `BBW_k`, `PR_k`, `CF_k` | `t_k`, from closes at or before `k` |
| Box | `t_(k-1)`. It excludes the breakout bar, so a breakout cannot widen its own box |
| Breakout, `S0` | `t_k` |
| `ATR_e` | `t_k`, frozen at that value |
| `VRe_b`, `HH_b`, chandelier | `t_b`, effective next bar |

## 5. Setup rules

**Long,** at `t_k`: a breakout, `S0` valid under 7.1.

**Short.** The exact mirror: `C_k < BL - 0.10 * ATR_(k-1)`, same other conditions. Neither side is favoured in `V0`. Crypto's upward drift means results should be split by side.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | `BH`, `BL`, `BM` |
| `invalidation` | `S0` |
| `targets` | `T1` at the setup, then as in 7.3 |
| `expiry` | 2 bars after `t_k` |

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency` on the breakout close, per [C6](00_INDEX.md#c6-entry-fill-r-and-size).

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
S_struct = BM - 0.25 * ATR_k
S0       = min(S_struct, C_k - R_min(1.25))
```

If `C_k - S0 > 3.0 * ATR_k`, then `S0 = C_k - 3.0 * ATR_k`, as long as this is still beyond the floor. Otherwise skip. The buffer has no `VR` term here because `VR` is by construction low at compression.

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Rule | When | `S_cand`, long |
|---|---|---|
| Box lock | First `C_b >= fill + 1R`, and from then on | `BH - 0.50 * ATR_b` |
| Volatility chandelier | First `C_b >= fill + 1R`, and from then on | `HH_b - k_b * ATR_b` |

```text
k_b = clip(4.5 - VRe_b, 2.0, 3.5)
```

The multiple falls from 3.5 toward 2.0 as `ATR` expands from its level at entry to 2.5 times that level. Because `ATR` rises at the same time, the distance `k_b * ATR_b` does not shrink quickly, and the ratchet stops it loosening.

### 7.3 Target logic

- `T1 = max(BH + BoxH, fill + 2.0 * R)`, set at the fill. At `t_k`, before a fill exists, `C_k` and `C_k - S0` stand in for `fill` and `R`.
- **Exception to C7.** [C7](00_INDEX.md#c7-exit-engine) uses the setup's targets on the fill bar. Here the fill bar uses the `T1` set at the fill, in the same way as C13 does for `V0S`.
- After `T1` fills, a climax target is recomputed at each close, and moves every bar:

```text
T2_b = max(HH_b + 2.0 * ATR_b, fill + 3.0 * R)
```

It means: sell into a bar that runs two full `ATR` beyond the highest high so far, and otherwise let the chandelier decide. Under `.T`, the `fill + x * R` terms in `T1` and `T2_b` follow the
[rule against a later fill raising a target](00_INDEX.md#c17-hourly-live-cycle).

### 7.4 Scale-out

25 percent at `T1`, the rest at `T2` or by the stop. The scale-out is small because any result in this kind of trade comes from the fat right tail.

### 7.5 Regime scaling

- `k_b` is the regime scaling: it responds directly to how much volatility has changed since entry.
- Compression is measured against the last 30 days, so what counts as quiet adapts to the market.
- The `SRV` requirement rises at weekends, when a quiet tape is normal and a break means less.

### 7.6 Floors

`R_min(1.25)` from [C9](00_INDEX.md#c9-floors). `a = 1.25` because the compressed `ATR` understates what the next bars may do.

### 7.7 Time stop

| `T_d` | Thesis check at | Stall exit: `C_b < fill + 1R` at | Absolute limit | `V0S` `H` |
|---|---|---|---|---|
| 4h | `n = 6` | `n = 18` | `n = 60` | 36 |
| 1h | `n = 12` | `n = 36` | `n = 120` | 72 |

### 7.8 Invalidation

- **Thesis check.** At the bar in the table, if `VRe_b < 1.10` and the largest `TR` since entry is below `1.25 * ATR_e`, volatility has not expanded. Exit at the next open, whatever the P&L.
- **Back in the box.** `C_b < BM`: exit at the next open.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both the stop and a target, the stop is taken. A chandelier computed from bar `b` never applies to bar `b`.

### 7.10 `V0S` control

`S0` from 7.1, `m = 4.0`, `H` from the table in 7.7.

### 7.11 Why this model suits this strategy

This is the only strategy here whose thesis is about volatility itself, so it has an exit for that specific failure: a break that drifts with no volatility expansion is closed even if it is not losing. Its second failure is ordinary: price falls back into the box. Once it works, the
main risk is that expansions exhaust themselves. Volatility clusters, but very high readings also tend to come with sharp reversals, so the trail multiple tightens as volatility rises. A plain fixed multiple of `ATR` would do the reverse, loosening just as the move grows wildest. The
scale-out is small and the climax target far away, because this is a low hit rate, high payoff design, and cutting the right tail would remove the reason to trade it.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. ETH, `T_d = 4h`. Box: `BH = 3,180`, `BL = 3,090`, `BoxH = 90`, `BM = 3,135`. Breakout bar closes 08:00: `O 3,172, H 3,204, L 3,168, C 3,198`, `ATR_e = 28`, `SRV = 1.4`.

- `S_struct = 3,135 - 7 = 3,128`. `C - S_struct = 70`. `R_min = max(35, 15.4) = 35`, and the cap is 84. So `S0 = 3,128`.
- At the setup, `T1 = max(3,270, 3,198 + 140) = 3,338`.
- `R_dec = 70`. The collar is 3,212, and the next open of 3,199 is inside it.
- So `fill = 3,199.32`, `R = 71.32`. Then `T1 = max(3,270, 3,341.96) = 3,341.96`, which also rules the fill bar. `fill + 1R = 3,270.64`. `fill + 3R = 3,413.28`.

`ATR` is computed from `TR` in this table, not held flat.

| `n` | Close | O | H | L | C | `TR` | `ATR` | `VRe` | `k` | Event at this close | Stop after close | Next target |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 12:00 | 3,199 | 3,226 | 3,192 | 3,220 | 34 | 28.43 | 1.02 | | | 3,128.00 | `T1` 3,341.96 |
| 2 | 16:00 | 3,220 | 3,256 | 3,214 | 3,250 | 42 | 29.40 | 1.05 | | | 3,128.00 | `T1` 3,341.96 |
| 3 | 20:00 | 3,250 | 3,272 | 3,240 | 3,262 | 32 | 29.59 | 1.06 | | | 3,128.00 | `T1` 3,341.96 |
| 4 | 00:00 | 3,262 | 3,302 | 3,258 | 3,296 | 44 | 30.62 | 1.09 | 3.41 | `C >= fill + 1R`. Box lock 3,164.69 is lower than chandelier `3,302 - 104.30` | 3,197.70 | `T1` 3,341.96 |
| 5 | 04:00 | 3,296 | 3,338 | 3,290 | 3,332 | 48 | 31.86 | 1.14 | 3.36 | Chandelier | 3,230.88 | `T1` 3,341.96 |
| 6 | 08:00 | 3,332 | 3,360 | 3,326 | 3,351 | 34 | 32.01 | 1.14 | 3.36 | `H > T1`: 25% out at 3,341.96 (`+2.00R`). Thesis check passes at 1.14. Chandelier | 3,252.55 | `T2` 3,424.02 |
| 7 | 12:00 | 3,351 | 3,412 | 3,345 | 3,405 | 67 | 34.51 | 1.23 | 3.27 | Chandelier. Target moves | 3,299.24 | `T2` 3,481.02 |
| 8 | 16:00 | 3,405 | 3,470 | 3,396 | 3,462 | 74 | 37.33 | 1.33 | 3.17 | Chandelier | 3,351.78 | `T2` 3,544.66 |
| 9 | 20:00 | 3,462 | 3,538 | 3,450 | 3,525 | 88 | 40.95 | 1.46 | 3.04 | Chandelier | 3,413.61 | `T2` 3,619.90 |
| 10 | 00:00 | 3,525 | 3,560 | 3,480 | 3,498 | 80 | 43.74 | 1.56 | 2.94 | Chandelier | 3,431.50 | `T2` 3,647.48 |
| 11 | 04:00 | 3,498 | 3,512 | 3,440 | 3,452 | 72 | 45.76 | 1.63 | 2.87 | Candidate 3,428.87 is lower, the ratchet holds. Target moves up | 3,431.50 | `T2` 3,651.52 |
| 12 | 08:00 | 3,452 | 3,470 | 3,418 | 3,430 | | | | | `L <= 3,431.50`: stop, 75% at 3,431.50 (`+3.26R`) | closed | |

Result before costs: `0.25 * 2.00 + 0.75 * 3.26 = 2.94R`. `Result_B = (0.25 * 142.64 + 0.75 * 232.18) / 70 = 3.00`. `R` stayed 71.32 throughout. This path was chosen to exercise the rules and does not represent a typical outcome. The usual outcome for this design is a small loss or a thesis exit. Bar 11 shows the ratchet at
work: `ATR` rising pulled the candidate down, and the stop refused to follow.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `T_d` | 4h, 1h | 4h is slower and clearer. 1h adds trades, and this strategy needs them |
| `PR_max` | 0.10, 0.20 | Strict and loose. A strict limit means few trades |
| `B` | 12, 24 bars | How long a quiet box must be |

Total: 8 configurations. Band window, percentile window and all stop and target constants are frozen.

## 9. BTC and ETH notes

- Same rules. `PR` is a rank against each symbol's own history.
- BTC and ETH compress together much of the time, so same-week breakouts in both are close to one bet.
- ETH has a larger typical `ATR` in percent, which keeps it further from the cost floor, in my judgement.
- Weekend compression is common and may not mean what weekday compression means. Report results by the weekday of the breakout.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| After long quiet periods, before a macro move | Should work best if it works at all | Result by length of compression, and by whether it preceded a large `ATRD` change |
| Quiet markets that stay quiet | Should fail by thesis exit | A high share of thesis exits, near small losses |
| False breaks | Should fail by back-in-the-box | Share of those exits |
| Market-wide adaptation | Should decay, as Fang et al. describe for stock indexes | Rolling results over time, reported by year |
| Any regime | Should beat its [placebo](00_INDEX.md#c15-placebo-control) | Entry bars drawn uniformly over bars passing the non-signal condition `CF` count and `BoxH` limit, with the side random at the block's real long and short share, and the same stop and target model from the box as of that bar. A named extra is an unconditional breakout with no compression filter |

## 11. Flow hooks

Questions for `feature-integrator`. Trades are available to live runs, so trade-based answers can be used live. Book-based ones cannot.

- **Entry gate:** during compression, is aggressive flow building on one side? This could offer the direction that candles cannot.
- **Entry gate:** does the breakout close come with broad aggressive flow, or a few large prints?
- **Early exit:** does flow confirm the thesis check, or contradict it, before bar 6?
- **Stop tightening:** when `VRe` is high, is one-sided flow running out?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Rank on the full sample | `PR` against all history, including the future | Last 30 days of bars, ending at `k` |
| Box including the breakout | `BH` over a window ending at `k` | Window ends at `k - 1` |
| Compression judged after the break | Checking `CF` at `k` after the breakout bar's volatility is known, or later still | The armed test uses bars through `k - 1` only |
| `ATR_e` updated | Using a later `ATR` for `VRe`'s base | Frozen at `t_k` |
| Chandelier from a running bar | Using `HH` that includes the current bar on that bar | Effective next bar |
| Weekend seasonal handling | `SRV` built with future slots | Previous 8 weeks only |
| Too few trades | Choosing a configuration that had a few lucky trades | Declare it now: at 4h the trade count is low, and any result needs a very cautious deflated Sharpe ratio |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 10 to 30 trades per year across BTC and ETH at 4h, and about 40 to 100 at 1h. At 4h this is not enough for quick statistical judgement, which is the strongest reason for the 1h entry in the grid.

**Cost.** Typical `R` about 150 to 300 bp at 4h, by my judgement. At the declared `RT = 12 bp`, about `0.04R` to `0.08R` at 1x. Fees cannot kill this at 4h. A gross `+0.1R` on a 200 bp stop only dies at `RT = 20 bp`. The killers are the base rate of false breaks and multi-day funding, which is why funding must
be reported separately. A stop exit pays `stop_slip` in place of `slip`, so 16 bp in all at 1x, under [C16](00_INDEX.md#c16-rounding-and-arithmetic-in-examples).

## 14. Live on an hourly cycle

**Verdict: eligible. Lowest live-eligible `T_d`: 1h. 4h is the default, and the better fit.** A 4h bar only closes every fourth run, so one late hour is a small part of the decision timescale, and holding periods of days are not affected by minutes of delay.

**Late entries.** General checks are in [C17](00_INDEX.md#c17-hourly-live-cycle). Values for this strategy:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 150 minutes at 4h, 90 minutes at 1h, after the breakout close |
| Path | `S0` or the setup's `T1` touched since `t_k`, or a `T_d` close below `BM`, voids the setup |
| Chase | `abs(P_dec - C_k) <= 0.5 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(1.25)` and `3.0 * ATR_k` |
| `RR_late` | Not applicable, because `T1` is set from the real fill by 7.3. Under `.T` the rule in C17 limits it |
| Thesis | `P_dec > BH`: price must still be outside the box |

Using the example in 7.12, with `C_k = 3,198`, `S0 = 3,128`, `ATR = 28`:

- `P_dec = 3,210` on a run an hour late: chase 12 passes against 14, risk 82 against 84. All pass. If the next 1m open is 3,210, then `fill = 3,210.32`, `R = 82.32` and `T1 = max(3,270, 3,374.96)`.
- `P_dec = 3,214`: chase 16 exceeds 14. Result: `STALE_SETUP`, reason `CHASE`.

**Stops and targets between runs.**

- Touches between runs are resolved from 1m bars at the next run, with `event_time` and `detection_time` recorded. Inside one 1m bar, the stop is first.
- At 4h, the runs between 4h closes resolve touches and compute no model update. Only a run that processes a 4h close computes model updates, and these act from `effective_from`. Flow may still act at the other runs, under C17. A dropped run at a 4h close means a stop can be stale for five hours. This is a real cost at this timeframe, and it appears in the record.
- `HH_b` for the fill bar uses only 1m bars at or after the fill. Later bars use the whole `T_d` bar.
- `VRe_b` and `k_b` use `T_d` closes only, so they do not depend on run timing.
- `T2_b` stays at its last value between closes, and is not recomputed at runs between 4h closes.
- The thesis check and the back-in-the-box exit fill after the run that processes the relevant close.
- Stops only tighten: the `P_dec` clamp in C17 can reduce a candidate, and the ratchet then keeps the old stop.

**Backtest reproduction.** `CYCLE` under [C17](00_INDEX.md#c17-hourly-live-cycle), with `C-LATE` for selection. It must simulate every hourly run, including those between 4h closes, because they resolve touches. Report `STALE_SETUP` by reason. With few trades at 4h, report the spread across seeds as well as the mean: a single dropped run can change a large part of
a small sample. On the candle stage (`D-31`) no `CYCLE` run may start, so this selection does not run there, under [C18](00_INDEX.md#c18-selection-purge-and-retirement).
