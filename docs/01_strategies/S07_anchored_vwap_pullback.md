# S07 Anchored VWAP pullback

Status: draft for leak audit. Not tested. **Tier `T1`**: true VWAP needs trades. Default `T_d` 1h. Long and short.
Live-eligible at 1h, see section 14.
Common rules C1 to C17 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

A VWAP anchored at a swing low is the average price paid by everyone who has traded since that low. While price is above
it, the average buyer of the leg is in profit. When price comes back to it, that average buyer is at about break-even. This
strategy buys that moment, in a rising leg, on the view that holders who are not yet losing do not need to sell, and that
those who missed the leg can buy at a known average cost.

**Who is on the other side.** Short-term sellers taking profit on the pullback, and shorts who sold the top of the leg, whose
targets are often near this line.

**Why it differs from price geometry.** All the other level strategies use prices. This one uses where the volume traded, so
two legs with the same shape can have different lines.

**How much of this is folklore.** The reference-price idea has real research behind it, on stocks over long horizons. Anchored
VWAP as a trading line is a practitioner idea, and I found no test of it. Its anchors are also usually drawn by hand after the
fact. Requiring a causally confirmed swing removes that advantage, and the honest result may look much worse than what the
charts suggest.

## 2. Evidence

**Grade for the rule: `PRACTITIONER`,** and only for a distant relative. There is no test of this rule.

| Source | What it shows | Limits |
|---|---|---|
| [Zarattini and Aziz, VWAP](https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/) | A rule of long above VWAP, short below, on QQQ and TQQQ from 2018 to 2023, reported net of commissions | Not anchored, not a pullback rule, and a different market. I read the authors' summary page, which gives no slippage assumption or out-of-sample test |
| [Thinkorswim, anchored VWAP](https://toslc.thinkorswim.com/center/reference/Tech-Indicators/studies-library/A-B/AnchoredVWAP) | The indicator exists, with deviation bands and a chosen anchor | Vendor documentation. Gives no formula and no test |
| [Grinblatt and Han](https://ideas.repec.org/a/eee/jfinec/v78y2005i2p311-339.html) (adjacent) | A reference-price proxy for unrealised gains explains cross-sectional stock momentum | Stocks, long horizons. Abstract only. Secondary sources I saw report mixed replications |
| [Schatzmann and Haslhofer](https://ar5iv.labs.arxiv.org/html/2010.12415) (adjacent) | A disposition effect in Bitcoin, not consistently present | On-chain holders, and counts transactions only |
| [Cong et al.](https://nber.org/papers/w30783) | Wash trading averaged over 70 percent of reported volume on unregulated exchanges in their sample | Means "average cost" is only meaningful on a venue with real volume |
| [Makarov and Schoar](https://econpapers.repec.org/RePEc:eee:jfinec:v:135:y:2020:i:2:p:293-319) | A common component of signed volume across exchanges explains about 80 percent of Bitcoin returns | One venue's VWAP is still only an estimate of the market's cost basis |

`UNVERIFIED`: Brian Shannon's book on anchored VWAP is the usual practitioner reference. I could not read it and do not rely on it.

## 3. Definitions

**Anchors.**

- **Major list:** `Sigma(10, 5, 2.0)` on `T_d`. For a long, the anchor is the latest swing low in this list, while no close has
  been below its price since the extreme, and its age is at most 21 days.
- **Minor list:** `Sigma(3, 3, 1.0)` on `T_d`. Used for the stop stack only, never for entries.
- **Start of the sum.** With `T1`, the first trade in bar `i` at the swing's extreme price. In the `T0-APPROX` cross-check, the
  whole of bar `i`.

**Anchored VWAP and bands.** Summed over all trades from the start of the anchor through time `t`, with price `p` and quantity `q`:

```text
N_t     = sum(q)
A_t     = sum(p*q) / N_t
sigma_t = sqrt( sum(p*p*q) / N_t - A_t*A_t )
```

Evaluate at `T_d` closes, using running totals per bar. Quantity is in base asset. The `T0-APPROX` version uses
`p = (H + L + C) / 3`, and `q = V` per bar, and must be labelled as such.

**Excursion flag, long.** At least one close at or above `A + sigma` since the anchor's confirmation, and since the last trigger for
this anchor.

**Cushion.** `cush_t = max(0.5 * sigma_t, 0.5 * ATR_t)`.

**Pullback bar, long, at bar `k`.**

| # | Condition |
|---|---|
| a | Excursion flag is set |
| b | `L_k <= A_k + 0.25 * sigma_k` |
| c | `L_k >= A_k - 0.50 * sigma_k` |
| d | `C_k > A_k` |
| e | `CLV_k >= 0.50` |
| f | `A_k >= A_(k-6)`: the line is flat or rising |
| g | `sigma_k >= 0.75 * ATR_k`: bands from a very young anchor are too narrow to mean anything |

## 4. Knowable times

| Object | Knowable at |
|---|---|
| Swing anchor | Its confirmation close, `t_c`, which is `Rt` bars after the extreme |
| `A_t`, `sigma_t` | Only from `t_c`, using trades already complete at `t`. The sum starts earlier but no value exists before `t_c` |
| Excursion flag | Each close at or after `t_c` |
| Trigger, `S0`, targets | `t_k` |
| Minor anchor in the stack | Its own confirmation close, effective next bar |
| Band targets | Each close, effective next bar |

## 5. Setup rules

**Long,** at `t_k`: a pullback bar, `VR_k <= 2.0`, this anchor has given fewer than `max_touch` triggers (default 2), and `S0` is valid.

**Short.** The exact mirror, anchored at the latest major swing high. If a long and a short trigger on one bar, take neither.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | Anchor id, `A_k`, `sigma_k` |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 4 bars after `t_k` |

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency` on the pullback close, per [C6](00_INDEX.md#c6-entry-fill-r-and-size).

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
buf      = 0.25 * clip(VR_k, 0.8, 1.5) * ATR_k
S_struct = min(L_k, A_k - cush_k) - buf
S0       = min(S_struct, C_k - R_min(1.0))
```

Skip if `C_k - S0 > 2.5 * ATR_k`.

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be).

| Rule | When | `S_cand`, long |
|---|---|---|
| Entry anchor | Always | `A0_b - cush0_b - buf_b` |
| Stack anchor | For each minor swing low confirmed after entry, above the previous one | `Ai_b - cushi_b - buf_b`, using that anchor's own VWAP and bands |
| Break-even | `T1` filled | `BE+` |

`S_cand` is the tightest of all of these. As each VWAP rises, the stop rises with it. When a VWAP falls, the ratchet holds.

### 7.3 Target logic

Recomputed at every `T_d` close, and targets may move either way:

```text
T1_b = max(A0_b + 1.5 * sigma0_b, fill + 1.0 * R)
T2_b = max(A0_b + 3.0 * sigma0_b, fill + 2.0 * R)
```

Neither may be set below `C_b + 0.25 * ATR_b`. At `t_k`, before a fill exists, `C_k` and `C_k - S0` stand in for `fill` and `R`.

### 7.4 Scale-out

50 percent at `T1`, the rest at `T2`.

### 7.5 Regime scaling

- `buf` scales with `VR`.
- `sigma` itself is a regime measure: it widens as trading spreads out, which widens both cushion and targets.
- `VR_k > 2.0` blocks new setups, because a shock can move the line and its bands faster than the trade can react.

### 7.6 Floors

`R_min(1.0)` from [C9](00_INDEX.md#c9-floors), and the cushion floor of `0.5 * ATR` keeps young anchors from placing a stop in noise.

### 7.7 Time stop

If `T1` is not hit by the close of `n = 24`, exit at the next open. Absolute limit `n = 120`.

### 7.8 Invalidation

Two consecutive closes below `A0`: exit at the next open. The average participant in the leg is now losing, and the thesis has gone.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both the stop and a target, the stop is taken. A VWAP value that includes
bar `b` never governs bar `b`.

### 7.10 `V0S` control

`S0` from 7.1, `m = 2.0`, `H = 48` bars.

### 7.11 Why this model suits this strategy

The stop here is the thesis. If the average buyer of the leg is underwater, the reason for the trade has gone. So the stop follows that
line, not a price multiple. A single anchor grows slow as volume accumulates, so a long leg would leave the stop far behind. Each new
higher low creates a younger average cost that is closer to price, and holding a stack lets the stop use whichever is tightest. Targets
are band multiples because `sigma` measures how far trading has actually spread around that cost, and they need to move because the line
and the bands both do. The `R`-based minimums keep a thin band from setting a target inside the cost of the trade.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. BTC, `T_d = 1h`, `ATR = 380`, `VR = 1.0` held flat, so `buf = 95` and `0.5 * ATR = 190`. For
readability every bar has `q = 300`, and the table gives each bar's VWAP.

At the trigger close (12:00): the entry anchor has `N = 12,000`, `A = 63,800`, `sigma = 520`, and the excursion flag is set. Trigger bar:
`O 64,050, H 64,120, L 63,760, C 64,010`.

- `L` is at or below 63,930 and at or above 63,540. `CLV = 0.69`.
- `cush = 260`. `S_struct = min(63,760, 63,540) - 95 = 63,445`. `R_min = max(380, 307.2)`. So `S0 = 63,445`.
- Next open 64,015, so `fill = 64,021.4`, `R = 576.4`, `fill + 1R = 64,597.8`, `fill + 2R = 65,174.2`, `BE+ = 64,098.2`.

One update in full, bar 1, with VWAP 64,090:
`A = (12,000*63,800 + 300*64,090) / 12,300 = 63,807.07`. The running second moment gives `sigma = 515.56`.
`S_cand = 63,807.07 - 257.78 - 95 = 63,454.29`, rounded down to 63,454.2. `T1 = max(64,580.4, 64,597.8) = 64,597.8`.

| `n` | Close | O | H | L | C | Bar VWAP | `A0` | `sigma0` | Event at this close | Stop after close | `T1` | `T2` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 13:00 | 64,015 | 64,190 | 63,980 | 64,150 | 64,090 | 63,807.07 | 515.56 | Entry anchor rises | 63,454.2 | 64,597.8 | 65,353.7 |
| 2 | 14:00 | 64,150 | 64,330 | 64,120 | 64,300 | 64,230 | 63,817.14 | 513.45 | Entry anchor | 63,465.4 | 64,597.8 | 65,357.5 |
| 3 | 15:00 | 64,300 | 64,520 | 64,270 | 64,480 | 64,400 | 63,830.70 | 515.00 | Entry anchor. Band now sets `T1` | 63,478.2 | 64,603.1 | 65,375.6 |
| 4 | 16:00 | 64,480 | 64,650 | 64,440 | 64,620 | 64,560 | 63,847.27 | 520.58 | `H > T1`: 50% out at 64,603.1 (`+1.01R`). `BE+` | 64,098.2 | filled | 65,409.0 |
| 5 | 17:00 | 64,620 | 64,700 | 64,480 | 64,530 | 64,590 | 63,863.78 | 526.28 | | 64,098.2 | | 65,442.6 |
| 6 | 18:00 | 64,530 | 64,560 | 64,240 | 64,330 | 64,400 | 63,875.43 | 526.37 | Low of a minor swing, not yet known | 64,098.2 | | 65,454.5 |
| 7 | 19:00 | 64,330 | 64,520 | 64,290 | 64,490 | 64,420 | 63,887.02 | 526.64 | | 64,098.2 | | 65,466.9 |
| 8 | 20:00 | 64,490 | 64,680 | 64,450 | 64,640 | 64,570 | 63,901.25 | 530.17 | | 64,098.2 | | 65,491.7 |
| 9 | 21:00 | 64,640 | 64,850 | 64,610 | 64,810 | 64,740 | 63,918.37 | 537.97 | Minor swing low 64,240 confirmed. New anchor `A1 = 64,532.5`, stack stop `A1 - 190 - 95` | 64,247.5 | | 65,532.2 |
| 10 | 22:00 | 64,810 | 65,010 | 64,780 | 64,970 | 64,900 | 63,938.00 | 550.01 | `A1 = 64,606.0` | 64,321.0 | | 65,588.0 |
| 11 | 23:00 | 64,970 | 65,180 | 64,940 | 65,140 | 65,060 | 63,960.00 | 566.37 | `A1 = 64,681.67` | 64,396.6 | | 65,659.1 |
| 12 | 00:00 | 65,140 | 65,300 | 64,980 | 65,020 | 65,130 | 63,982.50 | 583.46 | `A1 = 64,745.71` | 64,460.7 | | 65,732.8 |
| 13 | 01:00 | 65,020 | 65,040 | 64,700 | 64,760 | 64,850 | 63,998.87 | 589.86 | `A1 = 64,758.75` | 64,473.7 | | 65,768.4 |
| 14 | 02:00 | 64,760 | 64,800 | 64,440 | 64,480 | | | | `L <= 64,473.7`: stop, 50% at 64,473.7 (`+0.78R`) | closed | | |

Result before costs: `0.5 * 1.01 + 0.5 * 0.78 = 0.90R`. `R` stayed 576.4 throughout. This path was chosen to exercise the rules and does not
represent a typical outcome. On bar 9 the entry anchor would allow a stop near 63,554, and the younger anchor allows 64,247.5, which shows
why the stack exists.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| Major swing `(Lf, Rt, a)` | (10, 5, 2.0), (20, 5, 3.0) | Medium and large legs. Which participants count as "the leg" is unknown |
| `max_touch` | 1, 2 | The first pullback is the classic one. A second may be weaker |

Total: 4 configurations at `T_d = 1h`. Everything else is frozen.

## 9. BTC and ETH notes

- Same rules on both. Build VWAP per symbol on one venue, and never merge volume across venues. Inflated volume on some venues would distort
  the line and is the reason for [C1](00_INDEX.md#c1-instrument-and-venue).
- Perpetual volume includes a lot of short-term positioning, so "average cost" is a looser idea here than in a cash stock. This limit applies
  equally to both symbols.
- Funding can matter on multi-day holds. Report it separately.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Orderly trending legs with pullbacks | Should work best if it works at all | Result by leg type, measured afterwards |
| Ranges | Should fail, since the line becomes a midpoint | Many invalidations, with `A` slope near zero |
| V-shaped moves | Few trades, as the excursion needs a confirmed anchor | Count of triggers per anchor |
| High-volume shocks | The line jumps, and stops ride up fast | Compare stop exits on days with `VR` above 2 |
| Any regime | Should beat the [placebo](00_INDEX.md#c15-placebo-control) | The same rules with `A` replaced by an unweighted average price from the same anchor. A difference here is what shows volume weighting matters |

## 11. Flow hooks

Questions for `feature-integrator`. Trades are available to live runs, so trade-based answers can be used live.

- **Entry gate:** on the pullback to `A`, is selling aggressive and persistent, or is it fading?
- **Entry timing:** does taker flow turn positive before or after the close back above `A`?
- **Setup qualification:** was the leg since the anchor driven by broad volume, or by a small number of very large prints?
- **Early exit:** when price first closes below `A`, is flow confirming it before the second close?
- **Stop tightening:** when price reaches an upper band, is buying running out?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| VWAP used before confirmation | A swing low at 08:00 confirmed at 13:00, with its VWAP used at 10:00 | No value exists before `t_c`, even though the sum begins at the extreme |
| Anchor chosen with hindsight | Picking the leg's true low, or the "most obvious" one | Only the latest confirmed swing in the list, by rule |
| Trades after the close | Including trades stamped after `t_k` in `A_k` | Trades with time at or before `t_k` only |
| Bands from future dispersion | `sigma` over the full leg | Running totals to `t` only |
| Stack anchor used early | A minor swing low used before its confirmation | From its own confirmation, effective next bar |
| Same-bar VWAP stop | The close's VWAP applied inside that bar | Effective from the next bar |
| `T0-APPROX` reported as true | Candle approximation presented as `T1` | Labelled on every output |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 50 to 120 trades per year across BTC and ETH.

**Cost.** Typical `R` about 80 to 150 bp, by my judgement. At the illustrative `RT = 12 bp`, about `0.08R` to `0.15R` at 1x. A gross `+0.2R` on a
100 bp stop dies at `RT = 20 bp`. Testable history is limited by `T1`, which is still to be confirmed per venue. This may be the tighter limit.

## 14. Live on an hourly cycle

**Verdict: eligible. Lowest live-eligible `T_d`: 1h.** The line moves slowly at this scale, and a pullback to a slow line stays a pullback for a
while, so one late hour is tolerable. Live runs see trades since the last run, which is what this needs. There is no live `T0-APPROX` fallback.

**Late entries.** General checks are in [C17](00_INDEX.md#c17-hourly-live-cycle). Values for this strategy:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 90 minutes after the trigger close |
| Path | `S0` or `T1` touched, or two `T_d` closes below `A` since `t_k`, voids the setup |
| Chase | `abs(P_dec - C_k) <= 0.75 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(1.0)` and `2.5 * ATR_k` |
| `RR_late` | `T1 - P_dec >= 0.5 * (P_dec - S0)`, using the setup's `T1` |
| Thesis | `A_k < P_dec <= A_k + sigma_k`: price must still be above the line, and not already out at the band |

The limit is lower than in other documents because this setup starts near `1R` of reward at best, and its `T1` is reset from the real fill by 7.3. Using
the example in 7.12, with `A = 63,800`, `sigma = 520`, `C_k = 64,010`, `S0 = 63,445`, `T1 = 64,580` at the setup and `ATR = 380`:

- `P_dec = 64,300`: chase 290 exceeds 285. Result: `STALE_SETUP`, reason `CHASE`.
- `P_dec = 64,250`: chase 240, risk 805 against 950, thesis passes, but reward 330 is below 402.5. Result: `STALE_SETUP`, reason `RR_LATE`.
- `P_dec = 64,200`: chase 190, risk 755, thesis passes, reward 380 against 377.5. All pass.

**Stops and targets between runs.**

- Touches between runs are resolved from 1m bars at the next run, with `event_time` and `detection_time` recorded. Inside one 1m bar, the stop is first.
- `A`, `sigma` and the stack are computed for each processed `T_d` close, using only trades at or before that close and not all trades up to the
  run. The result is then the same whether the run was on time or late. New stops and targets act from `t_dec + latency`.
- A band target between runs stays at the last value set, however far the true band has moved. It does not float between runs.
- Two closes below `A0` are read at the run that processes the second. The exit fills after that run.
- If any trades in the span are missing, the run logs `DATA_GAP` for this symbol, and does not compute a partial VWAP. Touches are still resolved from
  1m bars if those are complete.
- Stops only tighten: the `P_dec` clamp in C17 can reduce a candidate, and the ratchet then keeps the old stop.

**Backtest reproduction.** `CYCLE` under [C17](00_INDEX.md#c17-hourly-live-cycle), with `C-LATE` for selection, and running VWAP totals rebuilt in the same
way as live, so rounding and start-of-sum handling match. `T0-APPROX` is not allowed in `CYCLE`. Report the share of `STALE_SETUP` by reason. A high
`RR_LATE` share means the strategy depends on entering very close to the line, which an hourly job cannot do reliably.
