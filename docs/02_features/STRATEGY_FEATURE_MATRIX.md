# Strategy feature matrix

Status: draft for leak audit. Date: 2026-11-04. Owner: `feature-integrator`.

For each strategy, this document names the small set of features to test first, the hypothesis, the expected sign, what result would reject it, and its live-eligible (`.L`) and research-only (`.R`) forms.

**Nothing here has been tested.** Every row is a hypothesis, and every frequency is a design estimate from the strategy documents, not a measurement. Passing a test here is evidence for continuing research, not a claim that a feature works.

Inputs: [strategy index](../01_strategies/00_INDEX.md) and all ten strategy documents, [triage](FEATURE_TRIAGE.md), [decision point map](DECISION_POINT_MAP.md), [gate specification](GATE_SPEC.md).

## 1. The short version

- **No live strategy's entry gate question is likely to be answerable on its own.** With the design frequencies, the smallest detectable difference between kept and vetoed setups is about 0.25 R at best and over 0.5 R at worst. The prediction for every live strategy, one at a time, is `INCONCLUSIVE`, unless the effect is larger than the gross edge the strategy documents use in their own examples. Section 4 has the numbers.
- **Four questions can probably be answered, all pooled:** whether aligned flow helps continuation setups as a class, whether flow exits help on a paired basis, and, in research only, whether opposing flow that made progress hurts reversal setups once S01 and S06 are included, and whether book imbalance adds to trade flow. Section 6 has them.
- **Every `.L` row is a specification until check D9 names a poll source.** None is confirmed today. Binance USD-M REST refused my tool on legal grounds, and the Binance spot host is not a candidate unless the owner confirms it under `D-01`. If no source passes, `VE.L`, `VX.L` and `VEX.L` cannot run, and live paper is `V0.L` only.
- **S07 and S08 depend on check D9 for more than their gates.** They are `T1` strategies, so without a pollable signed trade source they cannot run live at all.
- **The owner's order imbalance question (F16) is research only in every strategy.** No book feature can gate a live position.

## 2. Reading the tables

### 2.1 Notation

| Term | Meaning |
|---|---|
| `s` | Setup side, +1 long, -1 short |
| `A` | Aligned score of a signed feature, `s * (2 * pct(x) - 1)`, in `(-1, 1)`. See [normalisation](GATE_SPEC.md#4-normalisation) |
| `e` | Expected sign. `e = +1` means higher `A` should be better for the setup. `e = -1` means the opposite |
| `BLOCK` | First-pass rule: `e * A <= -0.6`, which is the worst 20% for the hypothesis. A constant, not fitted. Section 3.3 |
| `D` | Mean net `R` of kept setups minus mean net `R` of blocked setups, on identical setups. **The primary statistic.** A random veto has `D` near 0 in expectation, so `D > 0` is what beating a random veto means |
| `D_x` | For exits: mean net `R` per trade with the flow ladder minus the same trade under the model alone. Paired |

**Windows.** `Bar` is one `T_d` bar. On `.L` it ends at the last completed 1m bar before `t_dec`, so it includes the minutes between the setup close and the run. On `.R` it ends at `t_k`. `Anchored` is tied to a strategy object, such as the three acceptance closes, and ends at that object's own knowable time. Exit windows are 60 minutes on `.L` and [as listed](GATE_SPEC.md#10-research-only-variants) on `.R`.

**Response states.** `D-RR18-X1` is used through four states, with `F_s = s * NS_W`. They are rolling percentile cuts, not fitted values.

| State | Condition | Plain meaning |
|---|---|---|
| `ALIGN_PROGRESS` | `F_s > 0`, `RR >= ` rolling median | Flow with the setup moved price normally or better |
| `ALIGN_ABSORBED` | `F_s > 0`, `RR <= ` rolling 25th percentile | Flow with the setup did not move price |
| `OPP_PROGRESS` | `F_s < 0`, `RR >= ` rolling median | Flow against the setup moved price normally or better |
| `OPP_ABSORBED` | `F_s < 0`, `RR <= ` rolling 25th percentile | Flow against the setup did not move price |
| `NO_FLOW` | `abs(NS_W) < v_min` | Not enough flow to say anything. The vote is `NEUTRAL`, which is different from missing data |

**Exit rows.** `F37-X1` on `F24-X1`, with the middle ladder `(0.4, 0.6, 0.8)` fixed for the first pass. `TIGHTEN` follows the C8 ratchet with the C17 clamp. Flow can only reduce risk: it may never widen a stop, extend a time stop or extend a target.

**Timing.** `VE.T.L` is not a per-strategy test, for the reason in [how `WAIT` works](GATE_SPEC.md#54-how-wait-works-when-the-next-look-may-be-an-hour-away). Each strategy's timing hook is answered, if at all, by one `VE.T.R` run.

### 2.2 Where `.L` and `.R` differ

| | `.L` | `.R` |
|---|---|---|
| Clock | `CYCLE` under C17, headline `C-LATE`, at least 5 seeds | `IDEAL` under C5 to C7. Labelled `RESEARCH-ONLY` |
| Flow source | The poll source chosen by check D9 | Binance USD-M archive, Bybit as a cross-check, as the charter allows for research |
| Book features | None | Allowed, from next-day archives |
| Baseline | `V0.L` | `V0.R` |

A run on the hourly clock using an archive whose REST source has not passed check D9 is `.R`, not `.L`, and cannot be quoted beside the live record.

## 3. Rejection rules

These apply to every row. The tables add only what is specific to that row.

### 3.1 Three outcomes

Decided on out-of-sample blocks only.

| Outcome | Condition | What happens next |
|---|---|---|
| `SUPPORTED` | All of: 95% CI of `D` excludes 0 in the expected direction; `D - D_C15` exceeds one standard error; beats the shifted-flow placebo; survives the control in R4; `D > 0` at 2x cost and, for `.L`, under `C-BAD` | Evidence for continuing research. May be proposed for the live variant at G4. Not a claim that it works |
| `REJECTED` | Any of R1 to R5 | Retained in the trial registry with its failure. No replacement without a new pre-registered hypothesis on later data |
| `INCONCLUSIVE` | Neither | **A useful result, reported as such.** The recipe is not tuned and does not act on live positions. It may be logged beside `V0.L` as a frozen shadow decision, which adds forward sample at no trial cost |

CIs use a UTC-week block bootstrap.

### 3.2 Reasons to reject

| # | Reason | Rule |
|---|---|---|
| R1 | No useful effect, or the wrong sign | The upper bound of the 95% CI of `D` is below `D_min = 0.1 R`. For exits, the upper bound of `D_x` is below `0.05 R`. These are declared values, set against typical costs of 0.05 R to 0.25 R |
| R2 | **Fails the C15 placebo** | The same recipe with the same thresholds on the strategy's [C15 placebo](../01_strategies/00_INDEX.md#c15-placebo-control) gives `D_C15 >= D`. For level strategies these are setups at random levels of the same distance distribution. For S03 and S10 they are random entry times with the same stop and target geometry. If flow does as well on random setups, it says nothing about this strategy's mechanism. The row is rejected, and the result may only feed the class-level test in section 6 |
| R3 | Seasonal, not flow | The shifted-flow placebo, the same feature from the same hour one week earlier, gives `D_shift >= D` |
| R4 | Re-reading the candle | With controls for the return over the same window, `F42-X1` and hour of week, `D` falls by more than half or loses its sign |
| R5 | Fragile to the cycle, `.L` only | `D <= 0` under `C-BAD`, or `.R` is positive and `.L` under `C-LATE` is not. The idea stays open in research, but live use is rejected |

**Prerequisite.** A strategy's `V0` is compared with its C15 placebo at gate G3. If `V0` does not beat it, a gate result cannot be read as improving a strategy with no demonstrated setup. Its setups may stay in the class pool, labelled.

**A reversed result is never adopted.** If a feature predicts with the opposite sign, the stated hypothesis is rejected. Flipping the sign needs a new pre-registered trial on data after that block.

### 3.3 Fixed thresholds in the first pass

Sample sizes here cannot support fitting a threshold per strategy. The training rule of [the gate specification](GATE_SPEC.md#8-fitting-and-freezing) needs at least 30 rejected setups, and with a 20% veto in an 18-month first fold, S03, S05, S07 and S10 mostly fall short:

| Strategy | Setups in the first 18 months, design estimate | Rejected at 20% |
|---|---|---|
| S02 | 120 to 240 | 24 to 48 |
| S03 at 1h, S10 at 1h | 60 to 150 | 12 to 30 |
| S04, S08, S09 | 90 to 225 | 18 to 45 |
| S05 | 45 to 120 | 9 to 24 |
| S07 | 75 to 180 | 15 to 36 |
| S10 at 4h | 15 to 45 | 3 to 9 |

So the first pass uses one declared constant for every feature and fits nothing. This costs some power and removes a large source of overfitting. The grid in the gate specification is for class-level tests and survivors only.

## 4. Can each gate question be answered?

**Detectable difference.** From [the power formula](GATE_SPEC.md#11-evaluation-requirements), with `p = 0.7` and an **assumed** `sigma = 1.2 R`, the smallest `D` detectable at two-sided 5% and 80% power is about `7.33 / sqrt(n)`.

**Sample.** `n` is out-of-sample setups on `T1`: the design frequency in each strategy's section 13, times 5.3 years. That assumes a source with about 6.8 years of history passes check D9. A shorter source shrinks `n` in proportion. These are best cases:

- `STALE_SETUP` removes further setups under `CYCLE`, and BTC and ETH setups overlap, so effective `n` is lower.
- A first-pass veto keeps about 80%, not 70%, which raises the figures by about 15%.
- Nine trials with a Bonferroni correction would raise them by about 30%.
- `T2` has 2.8 years rather than 5.3, which raises them by about 38%.

| Strategy | Live | Setups a year | `n` | Detectable `D` | Prediction, alone |
|---|---|---|---|---|---|
| S01 | No | 200 to 400 | 1,060 to 2,120 | 0.16 to 0.23 R | **Answerable for a large effect.** Research only |
| S02 | 1h | 80 to 160 | 424 to 848 | 0.25 to 0.36 R | Only a large effect. **Expect `INCONCLUSIVE`** |
| S03 | 1h | 40 to 100 | 212 to 530 | 0.32 to 0.50 R | **Expect `INCONCLUSIVE`** |
| S03 | 4h | 13 to 33 | 71 to 177 | 0.55 to 0.87 R | **Not answerable** |
| S04 | 1h | 60 to 150 | 318 to 795 | 0.26 to 0.41 R | Only a large effect. **Expect `INCONCLUSIVE`** |
| S04 | 4h | Fewer, not estimated | - | Worse than 1h | **Not answerable** |
| S05 | 1h | 30 to 80 | 159 to 424 | 0.36 to 0.58 R | **Expect `INCONCLUSIVE`** |
| S05 | 4h | Fewer, not estimated | - | Worse than 1h | **Not answerable** |
| S06 | No | 100 to 250 | 530 to 1,325 | 0.20 to 0.32 R | Possible for a large effect. Research only |
| S07 | 1h | 50 to 120 | 265 to 636 | 0.29 to 0.45 R | **Expect `INCONCLUSIVE`** |
| S08 | 1h, both branches | 60 to 150 | 318 to 795 | 0.26 to 0.41 R | Only a large effect, if branches agree |
| S08 | 1h, each branch | About half | 159 to 398 | 0.37 to 0.58 R | **Expect `INCONCLUSIVE`** |
| S09 | 1h | 60 to 150 | 318 to 795 | 0.26 to 0.41 R | Only a large effect. **Expect `INCONCLUSIVE`** |
| S10 | 4h, default | 10 to 30 | 53 to 159 | 0.58 to 1.01 R | **Not answerable** |
| S10 | 1h | 40 to 100 | 212 to 530 | 0.32 to 0.50 R | **Expect `INCONCLUSIVE`** |

**What "a large effect" means here.** The strategy documents use a gross expectancy of about +0.2 R in their cost examples, and costs of 0.05 R to 0.25 R. A gate difference of 0.25 R would be larger than that whole assumed gross edge. I do not expect one, which is why the default prediction is `INCONCLUSIVE`. That is not pessimism for its own sake. It means a single strategy's gate should not be judged on its own, and the research money should go to section 6.

**Exits may be more answerable than entries.** `D_x` is paired on the same trades, so noise shared by both versions cancels. The required sample is `n >= (2.8 * sigma_d / D_x)^2`. `sigma_d` is unmeasured. At an **assumed** `sigma_d = 0.6 R`, 0.1 R needs about 280 trades that reach a flow look. The hourly cycle may make the effect itself small, and check D11 measures how many trades reach a look.

## 5. The strategies

Order within each table is test order. Rows after the first pass run only if an earlier row in that family gives something to refine. Each row is one trial, pooled across BTC and ETH. Splits by symbol and side are reports, not selections.

**First-pass rows are marked `FP`.**

### S01 Floor pivot rejection

**Backtest only, at every timeframe.** Default 15m. Reversal at a level. `R` about 50 to 60 bp, cost about 0.2 R to 0.25 R. Every chart is labelled `IDEAL, NOT LIVE-COMPARABLE`.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `D-RR18-X1` | Entry `VETO` | A rejection bar where sellers were still moving price in the last 15 minutes fails more often than one where selling stopped making progress | `BLOCK` on `OPP_PROGRESS`. `D > 0` | `OPP_ABSORBED` does no better than `OPP_PROGRESS` | None | `VE.F.R`, `Bar` 15 min. Single sensitivity 5 min |
| 2 `FP` | `F26-X1`, event form | Entry `VETO` | A touch made by a one-way sweep is a cascade, which the strategy expects to fail | `e = +1` on aligned sweep notional. `BLOCK` on `A <= -0.6`. `D > 0` | Swept and unswept touches do not differ | None | `VE.F.R`, sweeps in the last 15 min |
| 3 `FP` | `F24-X1` | Entry timing | After the rejection close, taker buying that continues marks the better entries | `e = +1`. `VE.T.R` beats `VE.F.R` | Waiting loses more in missed setups than it gains in price | None | `VE.T.R`, 5 min window, 60 s looks to `expiry` |
| 4 `FP` | `F37-X1` | Early exit, stop tightening | Flow turning against the position during the reaction clock comes before worse outcomes | `D_x > 0` | Cuts winners more than it saves on losers | None | `VX.R`, 5 min window, two ticks |
| 5 | `F16-X1` | Entry `VETO` | A book leaning with the setup over the last 15 minutes supports it | `e = +1`. `D > 0` | No gain beyond row 1 | None | `VE.F.R`, 1 s grid. `T2`, so 2.8 years |

**Answerable?** The best-powered entry question in the project, and it cannot reach live. The strategy document says flow gating is the most likely way it could ever earn a place. So a `SUPPORTED` result here would be a real argument for `D-04`. The sign contrast with S06 is deliberate: see S06 row 1.

**Hooks left open.** None, in research. All are unavailable live.

### S02 Pivot breakout, acceptance, retest

**Live at 1h.** `A_max` 90 min, expiry 4 bars, `T1` by `n = 24`. Continuation, entered on a retest. `R` about 80 to 120 bp, cost about 0.10 R to 0.15 R.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `D-RR18-X1` | Entry `VETO` | A retest where sellers still move price is failing. One where selling is absorbed above the level is holding | `BLOCK` on `OPP_PROGRESS`. `D > 0` | `OPP_ABSORBED` does no better than `OPP_PROGRESS` | `VE.F.L`, `Bar` 60 min, at the first run | `VE.F.R`, `Bar` 60 min. Single sensitivity 15 min |
| 2 `FP` | `F24-X1` | Setup qualification | Acceptance carried by net aggressive buying holds better than acceptance without it | `e = +1`, `Anchored` on the three acceptance closes. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, computed from cached bars | `VE.F.R`, same window |
| 3 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position over the last hour comes before a close-based invalidation | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, 15 min window, two ticks |
| 4 | `F25-X1` | Setup qualification, after row 2 | Acceptance carried by a few large prints is weaker than broad flow. Low confidence: large prints could equally be informed | `e = -1` on aligned large share. `D > 0` | Sign reversed | `VE.F.L`, summary | `VE.F.R` |
| 5 | `F16-X2` | Entry `VETO` | A book leaning with the setup at the retest supports it | `e = +1`. `D > 0` | No gain beyond row 1 | **None, no live book** | `VE.F.R`, 60 min, 30 s grid |

**Timing hook** ("does taker flow turn positive during the retest bar?"): one `VE.T.R` run, `F24-X1` over 15 min. Not answerable live.

**Answerable?** Not alone unless the effect is large. Expect `INCONCLUSIVE`. Contributes to both class tests: the retest entry to the response question, and the setup direction to the continuation question.

### S03 Market structure, BOS and CHoCH

**Live at 1h or 4h.** `A_max` 90 or 150 min, expiry 3 bars, stall exit at `n = 30` or 12. Trend following, held for days. `R` about 150 to 250 bp at 1h, cost about 0.05 R to 0.08 R. Funding is reported separately.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Entry `VETO` | A break of structure on net aggressive buying holds, and a thin push does not | `e = +1`, `Bar`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, 60 or 240 min | `VE.F.R`. Single sensitivity one quarter of the bar |
| 2 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position comes before the `CHoCH` close can be seen | `D_x > 0` | Cuts winners more than it saves on losers. Multi-day winners are the risk | `VX.L`, each run, including runs between 4h closes | `VX.R`, two ticks |
| 3 | `F24-X1` | Setup qualification, after row 1 | A pullback that formed the higher low on weak selling marks a stronger trend | `e = +1`, `Anchored` on the pullback. `D > 0` | No gain beyond row 1 | `VE.F.L`, from cached bars | `VE.F.R` |
| 4 | `F25-X1` | Entry `VETO`, after row 1 | A break carried by a few large prints is a stop run rather than a trend. Low confidence | `e = -1`. `D > 0` | Sign reversed | `VE.F.L`, summary | `VE.F.R` |
| 5 | `F16-X2` | Entry `VETO` | A book leaning with the break supports it | `e = +1`. `D > 0` | No gain beyond row 1 | **None, no live book** | `VE.F.R`, 30 s grid |

**Exhaustion hook** ("does a climax bar coincide with forced flow?"): deferred. A forced-flow measure needs a stream this setup cannot record, and `F26-X1` is only a rough proxy.

**Answerable?** At 1h, expect `INCONCLUSIVE`. At 4h, not answerable. Flow exit is the better question here: holds are long, so most trades should reach a look, and at an **assumed** `sigma_d = 0.6 R` the paired test could detect about 0.07 to 0.12 R at 1h. C15 for this strategy uses random entry times.

### S04 Supply and demand zones

**Live at 1h or 4h.** `A_max` 75 or 150 min, expiry 4 bars, reaction test at `n = 3`. Reversal at a zone. `R` about 60 to 120 bp, cost about 0.10 R to 0.20 R. The strategy document calls this the most delay-sensitive of the 1h strategies.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `D-RR18-X1` | Entry `VETO` | A zone where opposing flow is still moving price is failing | `BLOCK` on `OPP_PROGRESS`. `D > 0` | `OPP_ABSORBED` does no better than `OPP_PROGRESS` | `VE.F.L`, `Bar` | `VE.F.R`. Single sensitivity one quarter of the bar |
| 2 `FP` | `F24-X1` | Setup qualification | A departure carried by broad net aggressive flow leaves a better zone than a burst | `e = +1`, `Anchored` on the departure, knowable at `t_e`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, from cached bars, if still within the cache | `VE.F.R` |
| 3 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position in the first six bars comes before the close below `mid` | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, two ticks |
| 4 | `F27-X1` | Entry `VETO`, after row 1 | Anchoring absorption to the zone itself adds to the window measure. One family with row 1, never a second vote | `D > 0` beyond row 1 | No gain over row 1 on identical setups | `VE.F.L`, after the fact | `VE.F.R` |
| 5 | `F16-X1` | Entry `VETO` | A book leaning with the zone as price arrives supports it | `e = +1`. `D > 0` | No gain beyond row 1 | **None, no live book** | `VE.F.R`, 1 s grid, `T2` |

**Timing hook** ("does taker flow turn positive before or after the rejection close?"): one `VE.T.R` run. Not answerable live. The hook "as price enters the zone" can be answered live only after the fact.

**Answerable?** Not alone unless the effect is large, and the cycle may also remove what this row measures: the strategy expects a noticeable `IDEAL` minus `CYCLE` gap. `R5` is the likeliest rejection here. At 4h, not answerable.

### S05 Zone polarity flip

**Live at 1h or 4h.** `A_max` 90 or 150 min, expiry 4 bars, inventory clock at `n = 9`. Continuation from a failed zone. `R` about 80 to 150 bp, cost about 0.08 R to 0.15 R.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Entry `VETO` | At the retest, trapped participants cover, so aggressive buying should be visible. Its absence means the story is wrong | `e = +1`, `Bar`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, 60 or 240 min | `VE.F.R`. Single sensitivity one quarter of the bar |
| 2 `FP` | `F37-X1` | Early exit, stop tightening | Flow fading in Stage A, before `X`, comes before a failed move | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, two ticks |
| 3 | `F26-X1` | Setup qualification, after row 1 | A break bar that traded through resting offers makes a real flip | `e = +1` on aligned sweep notional, `Anchored` on the break bar. `D > 0` | No gain beyond row 1 | `VE.F.L`, from stored summary | `VE.F.R` |
| 4 | `F24-X1` | Entry timing | Taker flow turning positive inside the zone marks better entries than after price has left | `VE.T.R` beats `VE.F.R` | Waiting loses more than it gains | None, not answerable live | `VE.T.R`, 15 min, 60 s looks |
| 5 | `F16-X2` | Entry `VETO` | A book leaning with the setup at the retest supports it | `e = +1`. `D > 0` | No gain beyond row 1 | **None, no live book** | `VE.F.R`, 30 s grid |

**Answerable?** Expect `INCONCLUSIVE` at 1h, and not answerable at 4h. The strategy document already notes that its statistical problem comes before its cost problem. Run the first-pass rows only, then let its setups feed the class test. Row 1 differs from S02's reading of a retest: S02 looks for selling absorbed, while S05 looks for buying visible. That difference is the mechanism test between them, and may bear on whether S05 should be retired.

### S06 Liquidity sweep and reclaim

**Backtest only, at every timeframe.** Default 15m. Failed breakout reversal. `R` about 50 to 70 bp, cost about 0.17 R to 0.25 R. Every chart is labelled `IDEAL, NOT LIVE-COMPARABLE`.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F26-X1`, event form | Setup qualification | A reclaim after a real one-way sweep beats a reclaim after ordinary trading. **Opposite in sign to S01 row 2** | `e = -1` on aligned sweep notional. `BLOCK` when no opposing sweep: `A >= 0`, which blocks about half. `D > 0` | Swept and unswept reclaims do not differ | None | `VE.F.R`, sweep bar through reclaim |
| 2 `FP` | `F24-X1` | Entry `VETO` | At the reclaim, selling has stopped rather than paused | `e = +1`, 5 min. `D > 0` | Top half of `A` no better than bottom half | None | `VE.F.R`, 5 min |
| 3 `FP` | `F28-X1` | Entry timing | After the sweep, a book that refilled the swept prices marks a stronger reversal | Higher refill is better. `D > 0` | Low-refill and high-refill reclaims do not differ | **None, no live book** | `VE.T.R`, landmark 30 s, sensitivity 2 min. `T2`, so 2.8 years |
| 4 `FP` | `F37-X1` on `F26-X1` | Early exit | A second wave of opposing sweeps comes before a close confirms it | `D_x > 0` | Cuts winners more than it saves on losers | None | `VX.R`, event form |
| 5 | `F37-X1` on `F24-X1` | Stop tightening | After the reclaim lock, flow into the opposing pool weakens first | `D_x > 0` | No gain beyond row 4 | None | `VX.R`, 5 min, two ticks |

**Answerable?** Possibly, for a large effect, and research only. `F28-X1` has less sample: about 0.28 to 0.44 R detectable. S01 row 2 and S06 row 1 ask opposite things of the same event, which is why both are registered: at most one reading can be right for a given class of touches.

**Hooks left open.** "Did resting bids absorb the sweep?" is approximated by row 3. Real absorption needs `T3`.

### S07 Anchored VWAP pullback

**Live at 1h. Needs `T1` itself, so it depends on check D9 to run at all.** `A_max` 90 min, expiry 4 bars, `T1` by `n = 24`. Trend pullback. `R` about 80 to 150 bp, cost about 0.08 R to 0.15 R. Flow adds no new data dependency here, since the strategy already polls trades. `T0-APPROX` is not allowed on the cycle.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Entry `VETO` | A pullback on aggressive, persistent selling breaks the line. One on fading selling holds | `e = +1`, `Bar`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, 60 min | `VE.F.R`. Single sensitivity 15 min |
| 2 `FP` | `D-RR18-X1` | Entry `VETO` | Selling that still moves price toward the line is worse than selling absorbed at it | `BLOCK` on `OPP_PROGRESS`. `D > 0` | No gain beyond row 1 | `VE.F.L`, 60 min | `VE.F.R` |
| 3 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position comes before the second close below `A`. Buying fading at a band comes before a stop | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, two ticks |
| 4 | `F25-X1` | Setup qualification, after row 1 | A leg since the anchor carried by a few large prints is weaker than one with broad volume. Low confidence | `e = -1`, `Anchored` on the leg. `D > 0` | Sign reversed | `VE.F.L`, from stored totals, if `data-steward` allows it (open question 9 of the index) | `VE.F.R` |
| 5 | `F16-X2` | Entry `VETO` | A book leaning with the trend at the line supports it | `e = +1`. `D > 0` | No gain beyond row 1 | **None, no live book** | `VE.F.R`, 30 s grid |

**Timing hook** ("does taker flow turn positive before or after the close back above `A`?"): one `VE.T.R` run. Not answerable live.

**Answerable?** Expect `INCONCLUSIVE`. A high `RR_LATE` share in `V0.L` would also mean the strategy depends on entering closer to the line than an hourly job can.

### S08 Volume profile value area

**Live at 1h only. 30m is backtest only. Needs `T1` itself, so it depends on check D9 to run at all.** `A_max` 75 min, expiry 3 bars, and a UTC roll voids a setup. Two branches, reported separately. `R` about 60 to 120 bp, cost about 0.10 R to 0.20 R.

| # | Feature | Branch and point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `D-RR18-X1` | Rejection, entry `VETO` | At re-entry, sellers still moving price mean the rejection is not real | `BLOCK` on `OPP_PROGRESS`. `D > 0` | `OPP_ABSORBED` does no better than `OPP_PROGRESS` | `VE.F.L`, `Bar` | `VE.F.R`. Also at 30m |
| 2 `FP` | `F24-X1` | Acceptance, setup qualification | Net aggressive flow during the excursion marks real acceptance | `e = +1`, `Anchored` on the excursion. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, from cached bars | `VE.F.R`. Also at 30m |
| 3 `FP` | `F37-X1` | Both, early exit, stop tightening | Flow against the position comes before value stops migrating or before `T1` | `D_x > 0`, by branch | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, two ticks |
| 4 | `F24-X1` | Classification, descriptive | Flow during an excursion separates later rejection from acceptance before the closes do | Top and bottom `A` differ in later classification | No separation beyond the closes themselves | **Not a gate.** Layer 1 stays candle-only | Report, logged as a trial |
| 5 | `F16-X2` | Both, entry `VETO` | A book leaning with the setup supports it | `e = +1`. `D > 0` | No gain beyond rows 1 and 2 | **None, no live book** | `VE.F.R`, 30 s grid |

**Timing hook** ("on the acceptance pullback, does aggressive selling shrink?"): one `VE.T.R` run, on 30m. Not answerable live.

**Answerable?** Each branch: expect `INCONCLUSIVE`. Pooling the two would mix opposite readings, so it is not done. The branches feed different class tests.

### S09 UTC session range breakout

**Live at 1h.** Default now 1h. `A_max` 75 min, expiry 3 bars, hard flat at `T_flat`, checks at `n = 2` and `n = 4`. Clock-driven breakout. `R` about 60 to 120 bp, cost about 0.10 R to 0.20 R.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Entry `VETO` | A break on net aggressive buying during the seasonal volume rise holds better | `e = +1`, `Bar`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, 60 min | `VE.F.R`. Single sensitivity 15 min |
| 2 `FP` | `F25-X1` | Entry `VETO` | A break from a few large prints is weaker than a broad one. Low confidence | `e = -1`. `D > 0` | Sign reversed | `VE.F.L`, summary | `VE.F.R` |
| 3 `FP` | `F37-X1` | Early exit, stop tightening | In the first two hours, trade flow against the position comes before the volume check fails. After `h_peak`, it comes before the stop | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run. A first look comes near `n = 2` at best | `VX.R`, two ticks |
| 4 | `F24-X1`, second venue | Entry `VETO` | A break also supported on another venue holds better than one seen on this venue alone | `e = +1` on the other venue. `D > 0` | No gain beyond row 1 | Only if two sources pass check D9 | `VE.F.R`, Binance USD-M and Bybit archives |
| 5 | `F16-X2` | Entry `VETO` | A book leaning with the break supports it | `e = +1`. `D > 0` | No gain beyond row 1 | **None, no live book** | `VE.F.R`, 30 s grid |

`F42-X1` is a control here and not a gate input, because the strategy already conditions on `SRV`, which is nearly the same quantity.

**Answerable?** Not alone unless the effect is large. Expect `INCONCLUSIVE`. Report late hard-flat exits and funding, as the strategy requires.

### S10 Volatility compression expansion

**Live at 1h or 4h. 4h is the default and the better fit.** `A_max` 150 or 90 min, expiry 2 bars, thesis check at `n = 6` or 12. State-driven breakout, held for days. `R` about 150 to 300 bp at 4h, cost about 0.04 R to 0.08 R. Funding is reported separately.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Setup qualification | Flow building on the breakout side during compression marks real breakouts. **It filters a side already set by candles, and never chooses a side** | `e = +1`, `Anchored` on the box window, ending at `k - 1`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, from cached bars | `VE.F.R` |
| 2 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position comes before the thesis check at `n = 6` | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run, including runs between 4h closes | `VX.R`, two ticks |
| 3 | `F24-X1` | Entry `VETO`, after row 1 | The breakout bar itself on net aggressive flow holds better | `e = +1`, `Bar`. `D > 0` | No gain beyond row 1 | `VE.F.L`, 240 min | `VE.F.R` |
| 4 | `F25-X1` | Entry `VETO`, after row 1 | A breakout from a few large prints is weaker than a broad one. Low confidence | `e = -1`. `D > 0` | Sign reversed | `VE.F.L`, summary | `VE.F.R` |
| 5 | `F16-X2` | Entry `VETO` | A book leaning with the breakout supports it | `e = +1`. `D > 0` | No gain beyond row 1 | **None, no live book** | `VE.F.R`, 30 s grid |

**Answerable?** At 4h, **not answerable**. About 53 to 159 setups cannot detect anything short of an enormous effect, and one dropped run can change a large part of the sample. At 1h, expect `INCONCLUSIVE`. Report the spread across seeds. Flow exit is the better question, since holds are long, though even paired it is thin at 4h: about 0.13 to 0.23 R at an **assumed** `sigma_d = 0.6 R`. C15 for this strategy uses random entry times.

## 6. Class-level questions

These pool setups from several strategies, so each can answer what no single strategy can. Each one is a separate logged trial. **They answer "does this help this kind of setup", not "does this help S04".** Setups from BTC and ETH overlap, and strategies are correlated, so these figures are optimistic.

| ID | Question | Strategies | `n` | Detectable | Prediction |
|---|---|---|---|---|---|
| C-1 | Does aligned flow (`F24-X1`, `e = +1`) help continuation setups? | S02, S03, S05, S07, S08 acceptance, S09, S10. `.L` | About 2,700 | About 0.14 R | **Answerable** for a moderate effect |
| C-2 | Does opposing flow that made progress (`D-RR18-X1`, `OPP_PROGRESS`) hurt reversal setups, live-eligible? | S04, S08 rejection. `.L` | About 830 | About 0.25 R | Only a large effect |
| C-3 | The same, in research | C-2 plus S01, S06. `.R` | About 3,350 | About 0.13 R | **Answerable** for a moderate effect. Mixes timeframes |
| C-4 | Do the risk checks (`F41-X1`, `F39-X2`) improve what remains, beyond `VR` already in the strategies? | All live. `.L` | About 3,500, but only 5% or fewer are blocked | About 0.26 R | Only a large effect, though stress losses may be large |
| C-5 | Do flow exits help, paired? | All live. `.L` | Up to 3,500 trades, times the share reaching a look | About 0.03 to 0.04 R, at an **assumed** `sigma_d = 0.6 R` | **Answerable**, if check D11 finds enough trades reaching a look |
| C-6 | Does book imbalance (`F16-X2`) add to `F24-X1`? | All ten, `T2`, 2.8 years. `.R` only | About 3,200 | About 0.13 R | **Answerable** for a moderate effect. Mixes timeframes. **Cannot reach live.** It is evidence for `D-04`, not for a live gate |

**C15 applies here too.** Each class test is repeated on the pooled placebo setups. If `D_C15 >= D`, flow is at best a general market filter, unrelated to these mechanisms. That is worth knowing, but it is a different finding, and it goes in the report as such.

**Before any of this:** a setup-free screen of `F24-X1` against forward returns on the hourly grid, at 1h and 4h horizons. It has far more power for the question "is there any information at all?", and it can use official candles with taker-buy volume at almost no cost. It is logged as a trial, and it does not by itself justify a gate.

## 7. Trial count

Under the budget in [the gate specification](GATE_SPEC.md#8-fitting-and-freezing). The `V0` grid of 64 configurations is separate. Each row below runs on the configuration `V0` selected.

| Group | Trials | Notes |
|---|---|---|
| `.L` first pass, per strategy | 21 | S02 3, S03 2, S04 3, S05 2, S07 3, S08 3, S09 3, S10 2 |
| `.R` first pass, same recipes, for the cost of the cycle | 21 | Needed to measure `.R` minus `.L` |
| `.R` first pass, S01 and S06 | 8 | Four rows each |
| Timing, one `VE.T.R` each | 5 | S02, S04, S05, S07 and S08, the live strategies with a timing hook |
| Timing, `VE.T.L` | 1 | Pooled across the `A_max = 90` strategies, to check the expectation in the gate specification |
| Class tests | 6 | C-1 to C-6 |
| Screen | 2 | `F24-X1` at 1h and 4h |
| **First pass, total** | **64** | Every run is logged, including those whose result is `INCONCLUSIVE` |
| Later rows | Up to about 30 | Only after an earlier row gives something to refine |

Seeds, cost multiples and delay scenarios are reports on a recipe, not new trials, as the strategy index states. Selecting a seed is forbidden.

**Why this is still a lot.** 64 first-pass trials on samples this small will produce false positives. Family-wise correction will push most single-strategy results to `INCONCLUSIVE`, which agrees with the prediction in section 4.
