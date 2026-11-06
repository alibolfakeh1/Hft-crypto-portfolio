# Strategy feature matrix

Status: revised after [the leak audit of 2026-11-04](../reviews/leak/features_2026-11-04.md), and awaiting re-audit. No verdict is claimed here. Date: 2026-11-05. Owner: `feature-integrator`. Section 7.6, pooled `N` for class tests (H5), is new and awaits `leak-auditor`.

For each strategy, this document names the small set of features to test first, the hypothesis, the expected sign, what result would reject it, and its live-eligible (`.L`) and research-only (`.R`) forms.

**Nothing here has been tested.** Every row is a hypothesis, and every frequency is a design estimate from the strategy documents, not a measurement. Passing a test here is evidence for continuing research, not a claim that a feature works.

Inputs: [strategy index](../01_strategies/00_INDEX.md) and all ten strategy documents, [data sources](../03_DATA_SOURCES.md), [triage](FEATURE_TRIAGE.md), [decision point map](DECISION_POINT_MAP.md), [gate specification](GATE_SPEC.md).

## 1. The short version

- **Nothing here can run yet.** The source under `D-22` is Kraken spot, BTC/USD and ETH/USD, subject to written permission that has not been requested, with Bitstamp as the fallback. All sources stay disabled.
- **Every row depends on check D2.** Kraken's pages show `b` or `s` on trades without saying this is the taker's side. Every row below reads the taker's side, so all are `UNVERIFIED` until that check passes on both REST and the bulk files. If the side cannot be proved, no row runs. The risk check in C-4 is the one question that survives, since `F41-X1` and `F39-X2` read no side.
- **No live strategy's entry gate question is likely to be answerable on its own.** With the design frequencies, the smallest detectable difference between kept and vetoed setups is about 0.26 at best and over 0.5 at worst, in units of the risk budget, on an assumed sample. The prediction for every live strategy, one at a time, is `INCONCLUSIVE`. Section 4 has the numbers.
- **Three questions can probably be answered, all pooled:** whether aligned flow helps continuation setups, whether flow exits help on a paired basis, and, in research only, whether opposing flow that made progress hurts reversal setups once S01 and S06 are included. Section 6 has them.
- **The owner's order imbalance question (F16) has no test on this path.** Kraken has no free book history, so every book row is gone. It is `LATER`, and paid book history stays a later owner decision. No row, count or plan here assumes it will run.
- **Burst rows are conditional.** `F25-X1` and `F26-X1` need millisecond or finer match stamps on both endpoints (check D14). They are marked `FP*` or `*`, and they do not run if that check fails.
- **Cost may decide this before flow does.** The base-tier Kraken Pro spot taker fee read on 2026-11-04 implies a round trip of about 160 bps. That is far above what the strategy documents assumed. [Section 5.5 of the triage](FEATURE_TRIAGE.md#55-how-do-taker-fees-compare-with-the-effect-being-sought) has the arithmetic, and the owners have the decision.
- **Spot changes the strategies' premises.** C1 still says one linear perpetual, funding does not apply, and how shorts are simulated on spot is `UNVERIFIED`. These belong to `strategy-architect` and `project-manager`, and [section 15 of the gate specification](GATE_SPEC.md#15-open-items) lists them.

## 2. Reading the tables

### 2.1 Notation

| Term | Meaning |
|---|---|
| `s` | Setup side, +1 long, -1 short |
| `A` | Aligned score of a signed feature, `s * (2 * pct(x) - 1)`, in `(-1, 1)`. See [normalisation](GATE_SPEC.md#4-normalisation) |
| `e` | Expected sign. `e = +1` means higher `A` should be better for the setup. `e = -1` means the opposite |
| `BLOCK` | First-pass rule: `e * A <= -0.6`, which is the worst 20% for the hypothesis. A constant, not fitted. Section 3.3 |
| `PASS` | `e * A >= 0`, used by `.T` only. `tau_p = 0` is a declared constant |
| `Result_B` | Money P&L divided by the risk budget, under C10. The measure for gates, placebos and variant comparisons, under charter section 7 rule 4 |
| `D` | Mean `Result_B` of kept setups minus that of blocked setups, per setup on a shadow `V0` trade, under [the evaluation rules](GATE_SPEC.md#11-evaluation-requirements). **The primary statistic.** A random veto has `D` near 0 in expectation, so `D > 0` is what beating a random veto means |
| `D_x` | For exits: mean `Result_B` per trade with the flow ladder minus the same trade under the model alone. Paired |

Thresholds below on `D` and `D_x` are in units of the risk budget.

**Windows.** `Bar` is one `T_d` bar. On `.L` it is `(t_cut - W, t_cut]`, so it includes the minutes between the setup close and the run. On `.R` it is `(u - W, u]` at the look time `u`. `Anchored` is tied to a strategy object, such as the three acceptance closes, and ends at that object's own knowable time, which is at or before `t_cut`. Exit windows are 60 minutes on `.L` and [as listed](GATE_SPEC.md#10-research-only-variants) on `.R`.

**Response states.** `D-RR18-X1` is used through these states, with `F_s = s * NS_W`. Each `RR` is ranked on the [section 4 grid](GATE_SPEC.md#4-normalisation), valid members only, excluding the ranked window. The 0.5 and 0.25 cuts are declared constants, not fitted. `v_min` is fitted on the training span with no outcome.

| State | Condition | Plain meaning |
|---|---|---|
| `ALIGN_PROGRESS` | `F_s > 0`, `RR` rank at or above 0.5 | Flow with the setup moved price normally or better |
| `ALIGN_ABSORBED` | `F_s > 0`, `RR` rank at or below 0.25 | Flow with the setup did not move price |
| `OPP_PROGRESS` | `F_s < 0`, `RR` rank at or above 0.5 | Flow against the setup moved price normally or better |
| `OPP_ABSORBED` | `F_s < 0`, `RR` rank at or below 0.25 | Flow against the setup did not move price |
| `NO_FLOW` | `abs(NS_W) < v_min` | Not enough flow to say anything. The vote is `NEUTRAL`, which is different from missing data |

**Exit rows.** `F37-X1` on `F24-X1`, with the middle ladder `(0.4, 0.6, 0.8)` fixed for the first pass. `TIGHTEN` follows the C8 ratchet with the C17 clamp. Flow can only reduce risk: it may never widen a stop, extend a time stop or extend a target.

**Timing.** `VE.T.L` is not a per-strategy test, for the reason in [how `WAIT` works](GATE_SPEC.md#54-how-wait-works-when-the-next-look-may-be-an-hour-away). Each strategy's timing hook is answered, if at all, by one `VE.T.R` run. A `.T` target never moves further away because of the wait: see [section 5.5 of the gate specification](GATE_SPEC.md#55-after-enter).

**First-pass marks.** `FP` is first pass. `FP*` is first pass only if check D14 allows burst features. `*` on a later row means the same condition applies. If D14 fails, the row is recorded as not run, and no substitute is chosen, with one declared exception in S06.

### 2.2 Where `.L` and `.R` differ

| | `.L` | `.R` |
|---|---|---|
| Clock | `CYCLE` under C17, headline `C-LATE`, at least 5 declared seeds | `IDEAL-1M`, with the look grid in [section 10 of the gate specification](GATE_SPEC.md#10-research-only-variants). Labelled `RESEARCH-ONLY` |
| Flow source | The approved source | **The same approved source.** A second venue would confound venue with clock |
| Book features | None | **None on this path.** See section 1 |
| Baseline | `V0.L` | `V0.R` |
| Frozen artifacts | Fitted under `.L`, keyed by `(kind, source)` | Fitted under `.R`, the same key |

A run on the hourly clock before the source has passed check D9 and the source card is `.R`, not `.L`, and cannot be quoted beside the live record. A vendor archive with no proved match to its poll source is also `.R`.

**Order of reading.** Every `.L` recipe below is frozen here, before any `.R` result exists. A new `.L` recipe written after reading `.R` on a block counts that block as used, under section 3.1. Reading across the two kinds is allowed only for R5 and the cost of the cycle.

## 3. Rejection rules

These apply to every row. The tables add only what is specific to that row.

### 3.1 Outcomes

Decided on out-of-sample blocks only, on the configuration [frozen for each block](GATE_SPEC.md#83-what-may-read-outcomes-before-the-blocks). The locked block is read by nothing before the final verdict.

| Outcome | Condition | What happens next |
|---|---|---|
| `SUPPORTED` | All of: 95% CI of `D` excludes 0 in the expected direction; `D` minus the mean of the C15 placebo draws exceeds one standard error; beats the shifted-flow placebo; survives the control in R4; `D > 0` at 2x cost and, for `.L`, as the mean over declared seeds under `C-BAD`. Scored on blocks not yet read for this question | Evidence for continuing research. May be proposed for the live variant at G4. Not a claim that it works |
| `REJECTED` | Any of R1 to R5 | Retained in the trial registry with its failure. No replacement without a new pre-registered hypothesis on later data |
| `INCONCLUSIVE` | Neither | **A useful result, reported as such.** The recipe is not tuned and does not act on live positions. It may run as a shadow beside `V0.L`, under the shadow rule below |
| `EXPLORATORY` | A label, not a result: any later row, grid or sensitivity scored on blocks read before the date of the verdict that led to it | **Cannot earn `SUPPORTED`.** See below |

CIs use a UTC-week block bootstrap, with setups assigned to weeks by `created_at`.

**Test blocks are not reused.** Each first-pass verdict is recorded with its date. A later row, grid or sensitivity on blocks read before that date is `EXPLORATORY`, however good it looks, since the outcome of those blocks chose it. A refinement earns `SUPPORTED` only on blocks after that date, or once on the locked block. An earlier test block may join the training of later blocks only. [Section 8.6 of the gate specification](GATE_SPEC.md#86-test-blocks-are-not-reused-for-selection) has this rule, and asks `project-manager` to add it to item 11 of the timing contract.

**Shadows.** A shadow is a registered, counted trial. Its readout date and rule are fixed when it starts, and its decisions are appended at `t_dec`, as in [the decision record](GATE_SPEC.md#14-decision-record).

### 3.2 Reasons to reject

| # | Reason | Rule |
|---|---|---|
| R1 | No useful effect, or the wrong sign | The upper bound of the 95% CI of `D` is below `D_min = 0.1`. For exits, the upper bound of `D_x` is below `0.05`. Declared values, in units of the risk budget. They were set against costs far lower than the fee read for this source, which the owners may wish to revisit before any run. A change after results is a new trial |
| R2 | **Fails the C15 placebo** | The same recipe with the same thresholds on the strategy's [C15 placebo](../01_strategies/00_INDEX.md#c15-placebo-control), with at least 100 draws declared in advance and no redraws, gives a mean `D_C15 >= D`. The distribution is shown. For level strategies, the distance distribution comes only from earlier blocks, so the first block has no placebo. For S03 and S10 these are random entry bars. For S07, random anchors. For S09, a window shift. Under `.L` the draws pass through the same run function and run times. If flow does as well on random setups, it says nothing about this strategy's mechanism. The row is rejected, and the result may only feed the class-level test in section 6 |
| R3 | Seasonal, not flow | The shifted-flow placebo, the same feature from the same hour one week earlier, gives `D_shift >= D` |
| R4 | Re-reading the candle | With controls for the return over the same window, `F42-X1` and hour of week, `D` falls by more than half or loses its sign. Reported by [trigger-bar overlap band](GATE_SPEC.md#32-windows-on-the-cycle) |
| R5 | Fragile to the cycle, `.L` only | `D <= 0` as the seed mean under `C-BAD`, or `.R` is positive and `.L` under `C-LATE` is not, with `.R` run on the `.L` source's archive. The idea stays open in research, but live use is rejected. This is the only rejection that may read across kinds |

**Prerequisite, on the first training span only.** A strategy's `V0` is compared with its C15 placebo for flow purposes on that span alone, and each reading is a counted trial. If `V0` does not beat it, a gate result cannot be read as improving a strategy with no demonstrated setup. Its setups may stay in the class pool, labelled.

**A reversed result is never adopted.** If a feature predicts with the opposite sign, the stated hypothesis is rejected. Flipping the sign needs a new pre-registered trial on data after that block. The same applies if a side mapping changes after results.

**Removing one member of a recipe** is ablation. It is pre-registered and decided on training spans, and each removal is counted, as in [section 8.8 of the gate specification](GATE_SPEC.md#88-ablation). "No gain beyond row 1" is scored on identical setups, and such a row is `EXPLORATORY` unless it stands on later blocks.

### 3.3 Fixed thresholds in the first pass

Sample sizes here cannot support fitting a threshold per strategy. The training rule of [the gate specification](GATE_SPEC.md#8-fitting-and-freezing) needs at least 30 rejected setups, and with a 20% veto in an 18-month first training span, S03, S05, S07 and S10 mostly fall short. The figures below use the documents' design frequencies, written for a perpetual, and are `UNVERIFIED` for Kraken spot.

| Strategy | Setups in the first 18 months, design estimate | Rejected at 20% |
|---|---|---|
| S02 | 120 to 240 | 24 to 48 |
| S03 at 1h, S10 at 1h | 60 to 150 | 12 to 30 |
| S04, S08, S09 | 90 to 225 | 18 to 45 |
| S05 | 45 to 120 | 9 to 24 |
| S07 | 75 to 180 | 15 to 36 |
| S10 at 4h | 15 to 45 | 3 to 9 |

So the first pass uses one declared constant for every feature and fits nothing to outcomes. This costs some power and removes a large source of overfitting. The grid in the gate specification is for class-level tests and survivors only, and is scored under section 3.1.

## 4. Can each gate question be answered?

**Detectable difference.** From [the power formula](GATE_SPEC.md#11-evaluation-requirements), with `p = 0.7` and an **assumed** `sigma = 1.2` in `Result_B`, the smallest `D` detectable at two-sided 5% and 80% power is about `7.33 / sqrt(n)`.

**Sample.** `n` is out-of-sample setups: the design frequency in each strategy's section 13, times the span of test blocks. **That span is `UNVERIFIED`**, because `T_start` comes from the [coverage rule](GATE_SPEC.md#82-fold-plan-frozen-before-any-outcome), which needs the approved source's data. The table uses **5 years, an illustrative assumption, not a measurement.** It is roughly what a `T_start` near the start of 2019 would leave. A shorter span scales every figure by `sqrt(5 / years)`, so 3 years raises them by about 29%. These are best cases:

- Design frequencies were written with perpetuals in mind, and nothing about Kraken spot's activity is known.
- At the fee read for this source, the C9 floor would widen stops greatly, which changes setups and frequencies. See [section 5.5 of the triage](FEATURE_TRIAGE.md#55-how-do-taker-fees-compare-with-the-effect-being-sought).
- `STALE_SETUP` removes further setups under `CYCLE`, and BTC and ETH setups overlap, so effective `n` is lower.
- A first-pass veto keeps about 80%, not 70%, which raises the figures by about 15%.
- A Bonferroni correction over the 124 lines in section 7 would raise them by about 55%.

| Strategy | Live | Setups a year, design | `n` at 5 years | Detectable `D` | Prediction, alone |
|---|---|---|---|---|---|
| S01 | No | 200 to 400 | 1,000 to 2,000 | 0.16 to 0.23 | **Answerable for a large effect.** Research only |
| S02 | 1h | 80 to 160 | 400 to 800 | 0.26 to 0.37 | Only a large effect. **Expect `INCONCLUSIVE`** |
| S03 | 1h | 40 to 100 | 200 to 500 | 0.33 to 0.52 | **Expect `INCONCLUSIVE`** |
| S03 | 4h | 13 to 33 | 65 to 165 | 0.57 to 0.91 | **Not answerable** |
| S04 | 1h | 60 to 150 | 300 to 750 | 0.27 to 0.42 | Only a large effect. **Expect `INCONCLUSIVE`** |
| S04 | 4h | Fewer, not estimated | - | Worse than 1h | **Not answerable** |
| S05 | 1h | 30 to 80 | 150 to 400 | 0.37 to 0.60 | **Expect `INCONCLUSIVE`** |
| S05 | 4h | Fewer, not estimated | - | Worse than 1h | **Not answerable** |
| S06 | No | 100 to 250 | 500 to 1,250 | 0.21 to 0.33 | Possible for a large effect. Research only |
| S07 | 1h | 50 to 120 | 250 to 600 | 0.30 to 0.46 | **Expect `INCONCLUSIVE`** |
| S08 | 1h, both branches | 60 to 150 | 300 to 750 | 0.27 to 0.42 | Only a large effect, if branches agree |
| S08 | 1h, each branch | About half | 150 to 375 | 0.38 to 0.60 | **Expect `INCONCLUSIVE`** |
| S09 | 1h | 60 to 150 | 300 to 750 | 0.27 to 0.42 | Only a large effect. **Expect `INCONCLUSIVE`** |
| S10 | 4h, default | 10 to 30 | 50 to 150 | 0.60 to 1.04 | **Not answerable** |
| S10 | 1h | 40 to 100 | 200 to 500 | 0.33 to 0.52 | **Expect `INCONCLUSIVE`** |

**What "a large effect" means here.** The strategy documents use a gross expectancy of about +0.2 R in their cost examples. A gate difference of 0.25 would be larger than that whole assumed gross edge. I do not expect one, which is why the default prediction is `INCONCLUSIVE`. It means a single strategy's gate should not be judged on its own, and research effort should go to section 6.

**Exits may be more answerable than entries.** `D_x` is paired on the same trades, so noise shared by both versions cancels. The required sample is `n >= (2.8 * sigma_d / D_x)^2`. `sigma_d` is unmeasured. At an **assumed** `sigma_d = 0.6`, 0.1 needs about 280 trades that reach a flow look. The hourly cycle may make the effect itself small, and check D11 measures how many trades reach a look.

## 5. The strategies

Order within each table is test order. Rows after the first pass run only under section 3.1. Each row is one line in [section 7](#7-trial-count), which also holds the symbol rule. Splits by symbol and side are reports, not selections.

Each row runs on the `V0` configuration chosen per fold from training only, under C18. Under `.L`, each row keeps its window, sign and threshold as frozen here. Design values for `R` below come from the strategy documents and are `UNVERIFIED` for Kraken spot. Cost in `R` is not restated per strategy, since it depends on the `RT` still to be declared.

Book rows, funding reports and the second-venue row of the earlier draft are removed. S01 and S06 carry the labels their documents require on every chart.

### S01 Floor pivot rejection

**Backtest only, at every timeframe.** Default 15m, selected under `IDEAL-1M`. Reversal at a level. `R` about 50 to 60 bp.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `D-RR18-X1` | Entry `VETO` | A rejection bar where sellers were still moving price in the last 15 minutes fails more often than one where selling stopped making progress | `BLOCK` on `OPP_PROGRESS`. `D > 0` | `OPP_ABSORBED` does no better than `OPP_PROGRESS` | None | `VE.F.R`, `Bar` 15 min. Single sensitivity 5 min |
| 2 `FP*` | `F26-X1`, event form | Entry `VETO` | A touch made by a one-way sweep is a cascade, which the strategy expects to fail | `e = +1` on aligned sweep notional, ranked among nonzero members. `BLOCK` on `A <= -0.6`. No sweep is `NEUTRAL`. `D > 0` | Swept and unswept touches do not differ | None | `VE.F.R`, sweeps in the last 15 min |
| 3 `FP` | `F24-X1` | Entry timing | After the rejection close, taker buying that continues marks the better entries | `e = +1`, `tau_p = 0`. `VE.T.R` beats `VE.F.R` | Waiting loses more in missed setups than it gains in price | None | `VE.T.R`, 5 min window, 60 s looks to `expiry` |
| 4 `FP` | `F37-X1` | Early exit, stop tightening | Flow turning against the position during the reaction clock comes before worse outcomes | `D_x > 0` | Cuts winners more than it saves on losers | None | `VX.R`, 5 min window, two ticks |

**Answerable?** The best-powered entry question in the project, and it cannot reach live. The strategy document says flow gating is the most likely way it could ever earn a place. So a `SUPPORTED` result here would be a real argument for `D-04`. The sign contrast with S06 is deliberate: see S06 row 1.

**Hooks left open.** None, in research. All are unavailable live.

### S02 Pivot breakout, acceptance, retest

**Live at 1h.** `A_max` 90 min, expiry 4 bars, `T1` by `n = 24`. Continuation, entered on a retest. `R` about 80 to 120 bp.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `D-RR18-X1` | Entry `VETO` | A retest where sellers still move price is failing. One where selling is absorbed above the level is holding | `BLOCK` on `OPP_PROGRESS`. `D > 0` | `OPP_ABSORBED` does no better than `OPP_PROGRESS` | `VE.F.L`, `Bar` 60 min, at the first run | `VE.F.R`, `Bar` 60 min. Single sensitivity 15 min |
| 2 `FP` | `F24-X1` | Setup qualification | Acceptance carried by net aggressive buying holds better than acceptance without it | `e = +1`, `Anchored` on the three acceptance closes. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, computed at the object's knowable time and kept in state | `VE.F.R`, same window |
| 3 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position over the last hour comes before a close-based invalidation | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, 15 min window, two ticks |
| 4 `*` | `F25-X1` | Setup qualification, after row 2 | Acceptance carried by a few large prints is weaker than broad flow. Low confidence: large prints could equally be informed | `e = -1` on aligned large share. `D > 0` | Sign reversed | `VE.F.L`, from stored burst summaries | `VE.F.R` |

**Timing hook** ("does taker flow turn positive during the retest bar?"): one `VE.T.R` run, `F24-X1` over 15 min. Not answerable live.

**Answerable?** Not alone unless the effect is large. Expect `INCONCLUSIVE`. Contributes to both class tests: the retest entry to the response question, and the setup direction to the continuation question.

### S03 Market structure, BOS and CHoCH

**Live at 1h or 4h.** `A_max` 90 or 150 min, expiry 3 bars, stall exit at `n = 30` or 12. Trend following, held for days. `R` about 150 to 250 bp at 1h.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Entry `VETO` | A break of structure on net aggressive buying holds, and a thin push does not | `e = +1`, `Bar`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, 60 or 240 min | `VE.F.R`. Single sensitivity one quarter of the bar |
| 2 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position comes before the `CHoCH` close can be seen | `D_x > 0` | Cuts winners more than it saves on losers. Multi-day winners are the risk | `VX.L`, each run, including runs between 4h closes | `VX.R`, two ticks |
| 3 | `F24-X1` | Setup qualification, after row 1 | A pullback that formed the higher low on weak selling marks a stronger trend | `e = +1`, `Anchored` on the pullback. `D > 0` | No gain beyond row 1 | `VE.F.L`, computed at the object's knowable time and kept in state | `VE.F.R` |
| 4 `*` | `F25-X1` | Entry `VETO`, after row 1 | A break carried by a few large prints is a stop run rather than a trend. Low confidence | `e = -1`. `D > 0` | Sign reversed | `VE.F.L`, from stored burst summaries | `VE.F.R` |

**Exhaustion hook** ("does a climax bar coincide with forced flow?"): deferred. A forced-flow measure has no source on spot here, and `F26-X1` is only a rough proxy.

**Answerable?** At 1h, expect `INCONCLUSIVE`. At 4h, not answerable. Flow exit is the better question here: holds are long, so most trades should reach a look, and at an **assumed** `sigma_d = 0.6` the paired test could detect about 0.08 to 0.12 at 1h, on the 5-year assumption. C15 for this strategy uses random entry bars.

### S04 Supply and demand zones

**Live at 1h or 4h.** `A_max` 75 or 150 min, expiry 4 bars, reaction test at `n = 3`. Reversal at a zone. `R` about 60 to 120 bp. The strategy document calls this the most delay-sensitive of the 1h strategies.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `D-RR18-X1` | Entry `VETO` | A zone where opposing flow is still moving price is failing | `BLOCK` on `OPP_PROGRESS`. `D > 0` | `OPP_ABSORBED` does no better than `OPP_PROGRESS` | `VE.F.L`, `Bar` | `VE.F.R`. Single sensitivity one quarter of the bar |
| 2 `FP` | `F24-X1` | Setup qualification | A departure carried by broad net aggressive flow leaves a better zone than a burst | `e = +1`, `Anchored` on the departure, knowable at `t_e`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, computed at `t_e` and kept in state, since a departure can be up to 14 days old. If not held, `flow_blind` | `VE.F.R` |
| 3 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position in the first six bars comes before the close below `mid` | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, two ticks |
| 4 | `F27-X1` | Setup qualification, after row 1 | Anchoring absorption to the zone itself adds to the window measure. One family with row 1, never a second vote. The episode starts no earlier than the zone's knowable time, and `AE` ranks only against earlier setups knowable before the look, with at least 30 of them | `D > 0` beyond row 1 | No gain over row 1 on identical setups | `VE.F.L`, after the fact | `VE.F.R` |

**Timing hook** ("does taker flow turn positive before or after the rejection close?"): one `VE.T.R` run. Not answerable live. The hook "as price enters the zone" can be answered live only after the fact.

**Answerable?** Not alone unless the effect is large, and the cycle may also remove what this row measures: the strategy expects a noticeable gap between its research modes and `CYCLE`. R5 is the likeliest rejection here. At 4h, not answerable.

### S05 Zone polarity flip

**Live at 1h or 4h.** `A_max` 90 or 150 min, expiry 4 bars, inventory clock at `n = 9`. Continuation from a failed zone. `R` about 80 to 150 bp.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Entry `VETO` | At the retest, trapped participants cover, so aggressive buying should be visible. Its absence means the story is wrong | `e = +1`, `Bar`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, 60 or 240 min | `VE.F.R`. Single sensitivity one quarter of the bar |
| 2 `FP` | `F37-X1` | Early exit, stop tightening | Flow fading in Stage A, before `X`, comes before a failed move | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, two ticks |
| 3 `*` | `F26-X1` | Setup qualification, after row 1 | A break bar that traded through resting offers makes a real flip | `e = +1` on aligned sweep notional, ranked among nonzero members, `Anchored` on the break bar. `D > 0` | No gain beyond row 1 | `VE.F.L`, from stored burst summaries | `VE.F.R` |

**Timing hook** ("does taker flow turning positive inside the zone mark better entries than after price has left?"): one `VE.T.R` run, `F24-X1` over 15 min, 60 s looks. Rejected if waiting loses more than it gains. Not answerable live.

**Answerable?** Expect `INCONCLUSIVE` at 1h, and not answerable at 4h. The strategy document already notes that its statistical problem comes before its cost problem. Run the first-pass rows only, then let its setups feed the class test. Row 1 differs from S02's reading of a retest: S02 looks for selling absorbed, while S05 looks for buying visible. That difference is the mechanism test between them, and may bear on whether S05 should be retired.

### S06 Liquidity sweep and reclaim

**Backtest only, at every timeframe.** Default 15m, selected under `IDEAL-1M`. Failed breakout reversal. `R` about 50 to 70 bp.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP*` | `F26-X1`, event form | Setup qualification | A reclaim after a real one-way sweep beats a reclaim after ordinary trading. **Opposite in sign to S01 row 2** | `BLOCK` when the window holds no opposing sweep. So the share blocked equals the share of reclaims with no opposing sweep, which can be far above half, and it is reported. The minimum of 30% kept and the 30 rejected in the grid rules do not apply to this declared first-pass row. `D > 0` | Swept and unswept reclaims do not differ | None | `VE.F.R`, sweep bar through reclaim |
| 2 `FP` | `F24-X1` | Entry `VETO` | At the reclaim, selling has stopped rather than paused | `e = +1`, 5 min. `D > 0` | Top half of `A` no better than bottom half | None | `VE.F.R`, 5 min |
| 3 `FP*` | `F37-X1` on `F26-X1` | Early exit | A second wave of opposing sweeps comes before a close confirms it | `D_x > 0` | Cuts winners more than it saves on losers | None | `VX.R`, event form |
| 4 | `F37-X1` on `F24-X1` | Stop tightening | After the reclaim lock, flow into the opposing pool weakens first | `D_x > 0` | No gain beyond row 3 | None | `VX.R`, 5 min, two ticks |

**Declared exception.** If check D14 fails, rows 1 and 3 do not run, and row 4 is the first-pass exit row. This is declared now, before any outcome.

**Answerable?** Possibly, for a large effect, and research only. S01 row 2 and S06 row 1 ask opposite things of the same event, which is why both are registered: at most one reading can be right for a given class of touches.

**Hooks left open.** "Did resting bids absorb the sweep?" and "did the book refill?" both need book data, so they are `LATER`. Real absorption needs `T3`.

### S07 Anchored VWAP pullback

**Live at 1h. Tier `T1`.** `A_max` 90 min, expiry 4 bars, `T1` by `n = 24`. Trend pullback. `R` about 80 to 150 bp. Flow adds no new data dependency here. `T0-APPROX` is not allowed on the cycle. C15 uses random anchors.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Entry `VETO` | A pullback on aggressive, persistent selling breaks the line. One on fading selling holds | `e = +1`, `Bar`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, 60 min | `VE.F.R`. Single sensitivity 15 min |
| 2 `FP` | `D-RR18-X1` | Entry `VETO` | Selling that still moves price toward the line is worse than selling absorbed at it | `BLOCK` on `OPP_PROGRESS`. `D > 0` | No gain beyond row 1 | `VE.F.L`, 60 min | `VE.F.R` |
| 3 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position comes before the second close below `A`. Buying fading at a band comes before a stop | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, two ticks |
| 4 `*` | `F25-X1` | Setup qualification, after row 1 | A leg since the anchor carried by a few large prints is weaker than one with broad volume. Low confidence | `e = -1`, `Anchored` on the leg. `D > 0` | Sign reversed | `VE.F.L`, from stored burst summaries, as [section 3.7 of the gate specification](GATE_SPEC.md#37-state-each-feature-needs) declares | `VE.F.R` |

**Timing hook** ("does taker flow turn positive before or after the close back above `A`?"): one `VE.T.R` run. Not answerable live.

**Answerable?** Expect `INCONCLUSIVE`. A high `RR_LATE` share in `V0.L` would also mean the strategy depends on entering closer to the line than an hourly job can. Whether S07 has `IDEAL` results is open with `leak-auditor`. No flow row here reads `IDEAL`, so these rows are not affected.

### S08 Volume profile value area

**Live at 1h only. 30m is backtest only. Tier `T1`.** `A_max` 75 min, expiry 3 bars, and a UTC roll voids a setup. Two branches, reported separately. `R` about 60 to 120 bp.

| # | Feature | Branch and point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `D-RR18-X1` | Rejection, entry `VETO` | At re-entry, sellers still moving price mean the rejection is not real | `BLOCK` on `OPP_PROGRESS`. `D > 0` | `OPP_ABSORBED` does no better than `OPP_PROGRESS` | `VE.F.L`, `Bar` | `VE.F.R`. Also at 30m, one more line |
| 2 `FP` | `F24-X1` | Acceptance, setup qualification | Net aggressive flow during the excursion marks real acceptance | `e = +1`, `Anchored` on the excursion. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, computed at the object's knowable time and kept in state | `VE.F.R`. Also at 30m, one more line |
| 3 `FP` | `F37-X1` | Both, early exit, stop tightening | Flow against the position comes before value stops migrating or before `T1` | `D_x > 0`, by branch, one line each | Cuts winners more than it saves on losers | `VX.L`, each run | `VX.R`, two ticks |
| 4 | `F24-X1` | Classification, descriptive | Flow during an excursion separates later rejection from acceptance before the closes do | Top and bottom `A` differ in later classification | No separation beyond the closes themselves | **Not a gate.** Layer 1 stays candle-only | Report, logged as a trial |

**30m lines** use the configuration chosen per fold from training among S08's 30m runs, under `IDEAL-1M`. They are a comparison report and cannot be selected for live.

**Timing hook** ("on the acceptance pullback, does aggressive selling shrink?"): one `VE.T.R` run, on 30m. Not answerable live.

**Answerable?** Each branch: expect `INCONCLUSIVE`. Pooling the two would mix opposite readings, so it is not done. The branches feed different class tests. Whether S08 has `IDEAL` results is open with `leak-auditor`, and these rows do not read `IDEAL`.

### S09 UTC session range breakout

**Live at 1h.** Default now 1h. `A_max` 75 min, expiry 3 bars, hard flat at `T_flat`, checks at `n = 2` and `n = 4`. Clock-driven breakout. `R` about 60 to 120 bp. C15 uses a window shift.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Entry `VETO` | A break on net aggressive buying during the seasonal volume rise holds better | `e = +1`, `Bar`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, 60 min | `VE.F.R`. Single sensitivity 15 min |
| 2 `FP*` | `F25-X1` | Entry `VETO` | A break from a few large prints is weaker than a broad one. Low confidence | `e = -1`, ranked among nonzero members. No large burst is `NEUTRAL`. `D > 0` | Sign reversed | `VE.F.L`, from stored burst summaries | `VE.F.R` |
| 3 `FP` | `F37-X1` | Early exit, stop tightening | In the first two hours, trade flow against the position comes before the volume check fails. After `h_peak`, it comes before the stop | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run. A first look comes near `n = 2` at best | `VX.R`, two ticks |

**Removed:** a row reading a second venue. No second free source exists on this path, so it is `LATER`, and if a source is ever added it starts as a new counted family on later data.

`F42-X1` is a control here and not a gate input, because the strategy already conditions on `SRV`, which is nearly the same quantity.

**Answerable?** Not alone unless the effect is large. Expect `INCONCLUSIVE`. Report late hard-flat exits, as the strategy requires.

### S10 Volatility compression expansion

**Live at 1h or 4h. 4h is the default and the better fit.** `A_max` 150 or 90 min, expiry 2 bars, thesis check at `n = 6` or 12. State-driven breakout, held for days. `R` about 150 to 300 bp at 4h.

| # | Feature | Point | Hypothesis | Expected sign | Rejected if, beyond section 3 | `.L` | `.R` |
|---|---|---|---|---|---|---|---|
| 1 `FP` | `F24-X1` | Setup qualification | Flow building on the breakout side during compression marks real breakouts. **It filters a side already set by candles, and never chooses a side** | `e = +1`, `Anchored` on the box window, ending at `k - 1`. `D > 0` | Top half of `A` no better than bottom half | `VE.F.L`, computed at the object's knowable time and kept in state | `VE.F.R` |
| 2 `FP` | `F37-X1` | Early exit, stop tightening | Flow against the position comes before the thesis check at `n = 6` | `D_x > 0` | Cuts winners more than it saves on losers | `VX.L`, each run, including runs between 4h closes | `VX.R`, two ticks |
| 3 | `F24-X1` | Entry `VETO`, after row 1 | The breakout bar itself on net aggressive flow holds better | `e = +1`, `Bar`. `D > 0` | No gain beyond row 1 | `VE.F.L`, 240 min | `VE.F.R` |
| 4 `*` | `F25-X1` | Entry `VETO`, after row 1 | A breakout from a few large prints is weaker than a broad one. Low confidence | `e = -1`. `D > 0` | Sign reversed | `VE.F.L`, from stored burst summaries | `VE.F.R` |

**Answerable?** At 4h, **not answerable**. About 50 to 150 setups cannot detect anything short of an enormous effect, and one dropped run can change a large part of the sample. At 1h, expect `INCONCLUSIVE`. Report the spread across seeds. Flow exit is the better question, since holds are long, though even paired it is thin at 4h: about 0.14 to 0.24 at an **assumed** `sigma_d = 0.6`. C15 for this strategy uses random entry bars.

## 6. Class-level questions

These pool setups from several strategies, so each can answer what no single strategy can. Each one is a separate logged family, with its lines in section 7 and its `N` in [section 7.6](#76-pooled-n-for-class-tests-h5). **They answer "does this help this kind of setup", not "does this help S04".** Setups from BTC/USD and ETH/USD overlap, and strategies are correlated, so these figures are optimistic. They use the design frequencies at their midpoints, S10 at 4h, and the same 5-year assumption as section 4.

| ID | Question | Strategies | `n` | Detectable | Prediction |
|---|---|---|---|---|---|
| C-1 | Does aligned flow (`F24-X1`, `e = +1`) help continuation setups? | S02, S03, S05, S07, S08 acceptance, S09, S10. `.L` | About 2,500 | About 0.15 | **Answerable** for a moderate effect |
| C-2 | Does opposing flow that made progress (`D-RR18-X1`, `OPP_PROGRESS`) hurt reversal setups, live-eligible? | S04, S08 rejection. `.L` | About 790 | About 0.26 | Only a large effect |
| C-3 | The same, in research | C-2 plus S01, S06. `.R` | About 3,150 | About 0.13 | **Answerable** for a moderate effect. Mixes timeframes |
| C-4 | Do the risk checks (`F41-X1`, `F39-X2`) improve what remains, beyond `VR` already in the strategies? **These read no trade side, so this question does not depend on check D2** | All live. `.L` | About 3,300, but only 5% or fewer are blocked | About 0.27 | Only a large effect, though stress losses may be large |
| C-5 | Do flow exits help, paired? | All live. `.L` | Up to 3,300 trades, times the share reaching a look | About 0.03 to 0.04, at an **assumed** `sigma_d = 0.6` | **Answerable**, if check D11 finds enough trades reaching a look |

**C15 applies here too.** Each class test is repeated on the pooled placebo setups. If `D_C15 >= D`, flow is at best a general market filter, unrelated to these mechanisms. That is worth knowing, but it is a different finding, and it goes in the report as such.

**Grids here are scored under section 3.1.** The grid is chosen inside training spans. A class test whose choice used earlier-read blocks is `EXPLORATORY` on those blocks.

**Before any of this, on the first training span only:** a setup-free screen of the first-pass features against forward returns on the hourly grid, at 1h and 4h horizons. It has far more power for the question "is there any information at all?". It is built from trades, because Kraken's candle files are not stated to carry taker volume. Each line is a counted trial, and it does not by itself justify a gate.

## 7. Trial count

This replaces the earlier total of 64. **The total was too low.** This is a bottom-up list of every run these documents ask for, one line per grid setting.

**Symbol rule, stated here and only here.** A line pools BTC/USD and ETH/USD, and it is one decision. For the deflated Sharpe ratio it counts as **two**, because index section 4 says each symbol multiplies the count, and that is the conservative reading. Splits by symbol or side are reports, and add nothing further. The registry keeps lines and symbol runs, so either count can be read. `project-manager` confirmed this in [section 6 of the fold plan](../decisions/FOLD_PLAN_2026-11-05.md#6-rulings), and replaced the index's "each flow variant multiplies" with these lines on one frozen configuration.

**`N` for a flow result** is `2 * (the strategy's V0 grid + every flow line run so far)`. Selection in `V0` carries into every row that runs on it, so it is not separate. This is for a row of one strategy. A line that pools strategies uses [section 7.6](#76-pooled-n-for-class-tests-h5). At the end of the first pass:

| Strategy | `V0` grid | Flow lines | `N` |
|---|---|---|---|
| S02, S05, S07, S09 | 4 | 124 | 256 |
| S01, S03, S04, S06, S08, S10 | 8 | 124 | 264 |

Every later row, grid and sensitivity raises it.

### 7.1 Lines that run regardless of results

| Family | Lines | Detail |
|---|---|---|
| **A. `V0` grid** | **64** | S01 8, S02 4, S03 8, S04 8, S05 4, S06 8, S07 4, S08 8 including its 30m runs, S09 4, S10 8. From index section 4. Not in the flow total |
| B. `.L` first pass | 21 | S02 3, S03 2, S04 3, S05 2, S07 3, S08 3, S09 3, S10 2. Of these, S09 row 2 is `FP*` |
| C. `.R` first pass, same recipes | 21 | Needed to measure the cost of the cycle on the same source |
| D. `.R` first pass, S01 and S06 | 7 | S01 4, S06 3. Of these, S01 row 2 and S06 rows 1 and 3 are `FP*` |
| E. S08 additions | 4 | Row 3 by branch, one more line each on `.L` and `.R`. Rows 1 and 2 at 30m on `.R` |
| F. `VEX` | 18 | One run per strategy per kind: row 1 entry plus the first-pass exit row, except S06, which uses row 2 because its row 1 is `FP*`. 8 `.L` and 10 `.R` |
| G. Timing | 6 | One `VE.T.R` each for S02, S04, S05, S07, S08. One `VE.T.L`, pooled across the `A_max = 90` strategies |
| H. Class tests, with their grids | 15 | C-1 to C-3 and C-5 at 3 settings each. C-4 as `F41-X1`, `F39-X2` and both |
| I. Screen | 12 | `F24-X1`, `D-RR18-X1`, `F25-X1`, `F26-X1`, `F41-X1` and `F39-X2`, at 1h and 4h. First training span only. The two unsigned features are read against absolute returns |
| J. Quintile table | 2 | `F24-X1` by aligned-flow quintile, one table per class. First training span only |
| K. Diagnostics that read outcomes | 18 | Check D11, 8 lines, one per live strategy. `V0` against C15, 10 lines, one per strategy. First training span only |
| **Flow total, B to K** | **124** | |
| **All lines, A to K** | **188** | **376 symbol runs** |

If check D14 fails, the `FP*` lines fall away: S01 1, S06 1 after row 4 moves up, S09 2, and 4 screen lines. The flow total becomes 116.

### 7.2 Lines that run only if chosen

Each is logged when run, and it adds to `N`. Each is `EXPLORATORY` under section 3.1 on blocks already read.

| Family | Lines | Detail |
|---|---|---|
| Later rows | 18 | S02 2, S03 4, S04 2, S05 2, S06 1, S07 2, S08 1, S10 4, counting `.L` and `.R` |
| Grids on a survivor | 3 `.F`, 6 `.T`, 3 exit | Per survivor, under [section 8.5 of the gate specification](GATE_SPEC.md#85-grid-for-class-tests-and-survivors-only) |
| Window length | 1 per row, per kind | The "single sensitivity" named in a row, or in [section 3.2 of the gate specification](GATE_SPEC.md#32-windows-on-the-cycle) |
| `FAIL_OPEN` | 1 per row | Section 5.3 of the gate specification |
| Feature definitions | 6 in all | `F19-X1` at 6 h, `F41-X1` at 6 h, `F26-X1` walk at 5 bps, count-based `F24-X1`, `F42-X1` reset at 00:00 UTC, New York local hour |
| Profile length | 2 | 4 and 26 weeks |
| Ablation | 1 per removal | Section 3.2 |
| Reselection on `C-MEASURED` | 1 per strategy | Later blocks only |
| Shadow | 1 per shadow | Section 3.1 |

### 7.3 Lines that do not exist on this path

| Family | Lines | Why |
|---|---|---|
| Book rows and C-6 | 0 | `LATER`. Each would be a new family if paid book history is ever approved |
| Venue tests, second-venue rows | 0 | No second free source. A source added later starts a new counted family on later data |

### 7.4 What is not a trial

Controls stay labelled as controls, and are logged: `V0S`, `V0.L` and `V0.R` on a frozen configuration, every placebo draw, and the reversed-sign and shifted-flow runs. Seeds, cost multiples, delay scenarios and the cache-loss stress are reports on a recipe, as the strategy index states. Selecting a seed is forbidden. Check D12 reads no outcome and is a report.

### 7.5 Reconciled with the audit

The audit counted about 110 on the old plan, before its venue, quintile and wave 1d items. Its parts, and what each became:

| Item | Audit | Now | Why it changed |
|---|---|---|---|
| `.L` and `.R` first pass, S01 and S06, timing | 56 | 55 | S06's row on `F28-X1` is gone, since it was a book row. The old 64 was these 56, plus 6 class lines and 2 screen lines |
| `VEX` | 18 | 18 | |
| S08 at 30m and by branch | 4 | 4 | |
| Class tests with their grids | up to 18 | 15 | C-6 was a book question |
| Screen | about 16 | 12 | Book features removed. The list is now stated |
| **Subtotal** | **112, which the audit gives as about 110** | **104** | |
| Quintile tables | Not counted | 2 | |
| D11 and `V0` against C15 readings | Not counted | 18 | Under the audit's requirement that each outcome reading counts |
| Venue family, wave 1d | Not counted | 0 | No second source. `F26-X1` has no separate `.L` first-pass row |
| **Flow total** | | **124** | |

**Why this is a lot.** 124 flow lines on samples this small will produce false positives. Family-wise correction will push most single-strategy results to `INCONCLUSIVE`, which agrees with the prediction in section 4.

### 7.6 Pooled `N` for class tests (H5)

This answers condition 1 of H5 in [the feature re-audit](../reviews/leak/features_recheck_2026-11-05.md), which is part 5 of [the C-5 checklist](../decisions/FOLD_PLAN_2026-11-05.md#11-the-c-5-checklist). The formula at the top of this section names one strategy's `V0` grid, and a class test pools several, so it needs its own rule.

**Fixed here, before any outcome on market data.** No strategy has read market data (`D-42`), and stage 1 runs no flow line (fold plan section 11, part 5). It is written now and not after stage 1, because the re-audit makes it due before the first counted line, which is stage 1's first `V0` run, and because a rule written after sight of candle outcomes could be shaped by them.

**What counts as one trial.** A class line: one class, one kind, one grid setting, run on the configuration frozen for each block. Family H in 7.1 is these lines, 15 in all.

- **Two per line, for the symbols.** A line pools both symbols and counts two symbol runs, as section 6 of the fold plan rules. Family H is 30 symbol runs. The registry holds each class line with its class, kind, setting and member strategies.
- **Not one per member strategy or per member's gate.** A line applies one recipe and gives one `D`, so it is one decision. A split by strategy, symbol or side is a report. Proposing one member's gate from such a split is a new line, `EXPLORATORY` on every block already read (section 3.1).
- **Controls add nothing.** The C15 repeat on pooled placebo setups, the random veto, shifted flow and reversed sign belong to the line's own verdict (section 7.4). Seeds, cost multiples and delay scenarios are reports.
- **No `.R` twin in the first pass.** Family H holds none for the `.L` classes. R5's cross-kind clause binds only where `.L` under `C-LATE` is not positive, so its absence cannot help a class line to `SUPPORTED`. R5's `C-BAD` clause still applies. A twin run later is its own line, because a decision reads both kinds (fold plan section 6), and it is registered before the `.L` line is read.
- The pooled `VE.T.L` in family G is counted the same way.

**`N` for a class result.** The deflated Sharpe ratio of a class line uses the whole project's count, not only the pooled strategies' grids:

```text
N_class = symbol runs of every counted line and reading on market data, candle and flow,
          both stages, as of the verdict
        + symbol runs of every line in 7.1 still due (a line recorded as not run under D14 is not due)
        + 2 for D-32, counted outside the registry
```

Why the whole count and not the sum of pooled grids:

1. **A pool's edges can move with outcomes.** A strategy that fails the `V0` against C15 prerequisite may stay in the pool, labelled (section 3.2). "All live" in C-4 and C-5 changes if a strategy is retired under C18. S08's one grid feeds two classes. A count tied to membership could be argued after a result. The whole count cannot.
2. **Candles are already counted whole.** `D-32` adds its never-selectable family to the stage's total, 106 and not 104, and stage 1's lines stay in `N` at stage 2 (fold plan sections 5 and 9).
3. **Reading early gains nothing.** Lines that run regardless of results count from the start.
4. **It costs little.** It is never below the per-pool figures in the re-audit, 280 to 344. Against those, the figure below raises the rough `sqrt(2 ln N)` for the expected best of `N` trials, the scale used in [section 13.2 of the data center recheck](../reviews/leak/data_center_recheck_2026-11-04.md), by about 3% to 5%.

**Beside stage 1.** Stage 1 runs no class test. What it counts enters every `N_class` as it stands. A design count at the end of the first flow pass, not a result:

| Item | Symbol runs |
|---|---|
| Stage 1 `V0` grid, 52 lines on candles | 104 |
| `D-32` | 2 |
| Stage 1 `V0` against C15 readings, 8. Each pools both symbols, so each counts two here. The printed count lists them as 8 readings | 16 |
| Stage 2 `V0` grid, family A, 64 lines | 128 |
| Flow, families B to K, 124 lines, or 116 if D14 fails. Family K's readings are new ones on bars from trades, because flow is compared only with `V0` on the same bars (fold plan section 9, item 4) | 248, or 232 |
| **`N_class`** | **498, or 482** |

Every later line, reading, rerun or shadow adds its symbol runs.

**No reduction for overlap.** Lines share setups, so fewer than `N` trials are independent. No clustered or effective `N` is used, because that would be a fitted choice.

**Recorded with the verdict.** Each class verdict records its `N` and its date. A later report on the same line prints the `N` of its own date, which can only be higher.

**What stays fixed.** This rule enters the C-5 commit. Afterwards a change is a dated decision under the fold plan's rule, and may only raise `N`. It does not change the rejection rules in section 3. The deflated Sharpe ratio's other inputs, such as the spread of Sharpe ratios across trials, are not set here. The deflated Sharpe ratio is not built yet ([engine review](../reviews/code/engine_review_2026-11-05.md)), and those inputs are fixed in the same way before any flow outcome.
