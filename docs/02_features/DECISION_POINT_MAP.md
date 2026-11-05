# Decision point map

Status: revised after [the leak audit of 2026-11-04](../reviews/leak/features_2026-11-04.md), and awaiting re-audit. No verdict is claimed here. Date: 2026-11-05. Owner: `feature-integrator`.

This document states which features apply at which decision point, why, and which of those uses can reach a live paper position. Nothing here has been tested, and every "why" is a hypothesis. Feature decisions and derived IDs are in the
[triage](FEATURE_TRIAGE.md). Mechanics are in the [gate specification](GATE_SPEC.md), and where this map and that document differ, that document governs. What to test first for each strategy is in the [matrix](STRATEGY_FEATURE_MATRIX.md).

## 1. How to read this

**Every use is either live-eligible or research-only.** Everything runs on GitHub with no server (`D-15`), so a live decision happens at an hourly run and can see only `T1` signed trades polled by REST, plus candles built from them. Under `D-22` the source is Kraken spot, subject to written permission that has not been requested, with Bitstamp as the fallback. All sources stay disabled. There is no free book history on this path, so **no book feature has a use below.**

| Kind | Suffix | Clock | Inputs | Timeframes |
|---|---|---|---|---|
| Live-eligible | `.L` | `CYCLE` under C17 of the strategy conventions | `T1` and candles from the approved source, as a run would hold them | 1h, 4h |
| Research-only | `.R` | `IDEAL-1M`, with a finer look grid | `T1` from the same source's archive | 5m to 4h |

A `.R` result is never evidence that a live position would behave the same way. No flow variant runs in `IDEAL`.

**Every signed feature below waits on check D2,** since Kraken's pages do not state that `b` or `s` is the taker's side. `F41-X1`, `F39-X2` and `F42-X1` read no side. `F25-X1` and `F26-X1` also wait on check D14.

**Layers stay separate.** The [decision stack](../00_CHARTER.md#2-decision-stack) keeps Layer 1 candle-only, so that `V0` is a true baseline. Flow therefore never creates, changes or removes a setup in Layer 1. "Regime filter" and "setup qualification" below
are checks in Layer 2. The setup is still recorded, and if rejected it stays in the record with its counterfactual (`F35-X1`). A purely candle-based regime rule, such as the `VR` limit in the strategy documents, belongs to the strategy and is not a flow decision.

**Verdict on the hourly cycle.** One word per decision point, explained in each section:

| Decision point | Layer | Live verdict |
|---|---|---|
| Regime filter | 2 | Survives |
| Setup qualification | 2 | Survives after the fact |
| Entry `ENTER`, `WAIT`, `VETO` | 2 | `VETO` survives, `WAIT` mostly does not |
| Entry timing | 2 | Destroyed at 1h, weak at 4h |
| Order style | 3 | No live decision |
| Early exit | 4 | Slow conflict only |
| Stop tightening | 4 | Slow conflict only |
| Risk gate | 2 and 4 | Partly survives |

**Mechanism classes.** The strategies fall into two groups for flow purposes, and they want opposite readings. Each strategy's features and signs are in the [matrix](STRATEGY_FEATURE_MATRIX.md).

| Class | Strategies | Flow reading, as a hypothesis |
|---|---|---|
| Reversal at a level | S01, S04, S06, S08 rejection branch | Flow pushed into the level and made little progress |
| Continuation or breakout | S02, S03, S05, S07, S08 acceptance branch, S09, S10 | Flow agrees with the direction and made normal or better progress |

S01 and S06 can run only as `.R`, at every timeframe. S02, S07, S08 and S09 are live at 1h. S03, S04, S05 and S10 are live at 1h or 4h.

## 2. Regime filter

**Question.** Is the market in a state where this setup's mechanism is even eligible?

**When.** At each look, as rule 3 of [the evaluation order](GATE_SPEC.md#53-evaluation-at-each-look), after the expiry and late-entry rules.

**Action allowed.** `VETO` with reason `stress`. On `.T`, `WAIT` with that reason, if a look remains. Direction plays no part.

| Feature | Kind | Why | Notes |
|---|---|---|---|
| `F39-X2` stress, `T1` | `.L` | Stress may invalidate level-based mechanisms | Same family as `F41-X1` for evidence. Compared with a frozen limit |
| `F41-X1` jump score | `.L` | A recent discontinuity suggests an out-of-distribution state | `JSmax_60` on the cycle. Compared with a frozen limit |
| `F19-X1` lambda level | `.L`, second wave | High impact per unit of flow may mark fragile liquidity | Same family as `D-RR18-X1` |

**`F42-X1` is not on this list.** It is a control across the gate, never a gate input, as the triage states.

**On the hourly cycle.** These states move slowly, so this decision point loses little. It is the most natural use of flow data on this setup.

**Later.** F40 if stress losses remain unexplained. F44 once two features survive. F02, F14 and `F39-X1` need paid book history.

## 3. Setup qualification

**Question.** Does the flow around the setup fit the mechanism the setup claims?

**When.** At the first look after the setup becomes knowable. On the cycle that is a look at flow that has already happened.

**Action allowed.** `VETO` with reason `flow_block:<feature>`.

| Feature | Kind | Why | Expected reading, by class |
|---|---|---|---|
| `D-RR18-X1` with `F18-X1`, `F19-X1` | `.L` | Separates flow that moved price from flow that did not | Reversal: strong flow into the level with low response. Continuation: aligned flow with normal or high response |
| `F24-X1`, `Anchored` | `.L` | Flow over the object that made the setup, such as a departure or an excursion | Continuation: flow with the setup. Reversal: a departure carried by broad flow |
| `F27-X1` zone absorption | `.L`, second wave | Anchors the same idea to the setup's zone | Reversal only. One family with `D-RR18-X1`, so never a second vote |
| `F26-X1` sweep summary | `.L`, second wave, if D14 allows | A sweep within the last hour on the relevant side | Reversal: a sweep into the level may be the setup's fuel. Continuation: a sweep with the setup may confirm it. Weak form on the cycle |
| `F26-X1` as an event | `.R`, if D14 allows | S06 row 1 asks this directly | Reversal only |

**On the hourly cycle.** A look at the last 60 or 240 minutes can still say whether flow pushed and made progress. It cannot say what was happening when price touched the level. The strategy documents phrase several hooks as "while price is at the level", and those cannot
be answered live. Only "looking back at the last hour, did it?" can.

**Later.** F29 and F30 after `F27-X1`. F09 and F12 need `T3`. F20 and F22 after the response family.

## 4. Entry `ENTER`, `WAIT`, `VETO`

**Question.** At this look, should this setup become a trade?

**When.** At each look while the setup is live, in step 3b of `decide`. Mechanics are in [the entry gate](GATE_SPEC.md#5-entry-gate-on-the-cycle).

| Feature | Kind | Why | Role |
|---|---|---|---|
| `F24-X1` volume balance | `.L` | Is aggressive flow with or against the setup? The simplest measure, and the bar for all others | Primary |
| `D-SV18-X1` signed notional | `.L` | Raw form and control | Same family as `F24-X1` |
| `D-RR18-X1` | `.L` | Distinguishes the flow that matters from the flow that merely re-measures the bar | Primary |
| `F25-X1` large burst | `.L`, if D14 allows | Do unusually large takers agree? | First pass in S09 only, second wave elsewhere |
| `F26-X1` as an event | `.R`, if D14 allows | Block entries against a recent sweep | Veto only |

**Removed:** book imbalance rows. The owner's core imbalance question (F16) is `LATER`, pending a paid-data decision.

**On the hourly cycle.**

- **`VETO` survives.** A filter that rejects a setup at the first look loses little from the cycle, because 1-hour and 4-hour setups already wait for a bar close. This is the realistic live function of the gate.
- **`ENTER` is not a timing decision.** It means "the first run after the setup, if no block". At 1h that is usually the only look that passes the late-entry checks.
- **`WAIT` means something different.** Under C17 it means the next run, up to `expiry` and `A_max`. It is available by [a rule that never reads a realised next run](GATE_SPEC.md#54-how-wait-works-when-the-next-look-may-be-an-hour-away): `looks_used < looks_max`, and the next nominal time plus the scenario's declared minimum delay is within both limits. A `WAIT` whose next run fails Age closes as `STALE_SETUP`, charged to the gate. At 1h under `C-LATE`, the next run passes Age for about 16% of setups where `A_max` is 75 minutes, and about 49% where it is 90. At 4h, about 95% at the second look and about 49% at the third, on far fewer setups. Those shares are arithmetic for reporting, on assumed delays. The live variant is therefore filter only (`VE.F.L`). The timing variant (`VE.T.L`) runs once, pooled, to confirm or refute this expectation, not because I expect value.

**Later.** F17 and F10 condition trust in imbalance, and neither applies unless `F16-X1` is revived and shows value. F11 needs `T3`.

## 5. Entry timing

**Question.** Given a setup that will be taken, when within its life is the better moment?

**When.** Between `created_at` and `expiry`.

| Feature | Kind | Why | Role |
|---|---|---|---|
| `F24-X1` over a short window | `.R` | Wait for flow to turn with the setup | Primary in research |
| `F26-X1` as an event | `.R`, if D14 allows | Wait for a sweep to finish | Second wave |
| `F23-X1` | `.R` | Has one-sided flow run on for several minutes? | Second wave |
| `F24-X1` at the looks after a 4h close | `.L` | The only timing left on the cycle | `VE.T.L`, too few setups to read per strategy |

**On the hourly cycle: destroyed at 1h, weak at 4h.** Timing needs many looks inside the setup's life, and the mechanisms it relies on play out over seconds to minutes. An hourly look samples them at random. **This is the largest single loss from the hourly cycle, together with fast exits.** `.R` keeps the question alive as research.

**Target rule.** A later fill must not raise a target. Under `.T`, each fill-based target term uses the less distant of its actual value and its value at the first look's `P_dec`. See [section 5.5 of the gate specification](GATE_SPEC.md#55-after-enter).

**Later.** F21 needs `F26-X1` events, and it would be research only. F28 needs paid book history.

## 6. Order style

**Question.** How is the entry sent?

| Input | Kind | Why | Role |
|---|---|---|---|
| Fees and slippage configuration, as declared constants | Both | Charter section 6, C9, C12 | Required. See [the triage](FEATURE_TRIAGE.md#55-how-do-taker-fees-compare-with-the-effect-being-sought) |
| `F35-X1` | Metric | What rejected setups would have made | Evaluation only |

**Default for every variant: taker.** The strategy conventions already use taker entries only. This avoids any fill or queue model, so gate G5's passive-fill test is not needed. F33 stays `LATER`, for a passive-entry variant that nobody has registered.

**On the hourly cycle: no live decision at this point.** The paper fill is the open of the first 1m bar with `open_time >= t_dec + latency` that has a price, per C17, under the collar in C6. **No book input reaches a decision.** A book snapshot, if the source's permission covers it, is optional and written to the record by a separate writer after the commit. Its only use is to check whether the assumed slippage is realistic. See [section 5.8 of the triage](FEATURE_TRIAGE.md#58-does-the-book-snapshot-at-poll-time-have-any-use).

**A resting entry would need thinking through.** Reversal strategies might prefer a resting limit at the level, since the cycle cannot react at the touch, and the maker fee read for this venue is half its taker fee. That would mean a passive-fill model, which G5 must test, and it would be a strategy decision. It is not part of this design.

## 7. Early exit

**Question.** Has flow turned against an open position by enough to leave before the model does? **Flow can only reduce risk.**

**When.** At each run, in step 3b of `decide`, after stops and targets are resolved, for positions with no exit pending. Mechanics are in [the flow exit](GATE_SPEC.md#6-flow-exit-on-the-cycle).

**Action allowed.** `SCALE_OUT` or `EXIT`, from one ladder on one conflict value `C`, plus one risk trigger. Both pay `slip` as taker fills.

| Feature | Kind | Why | Role |
|---|---|---|---|
| `F37-X1` on `F24-X1` | `.L` | Flow against the position over the last hour | **The first-pass value of `C`** |
| `F37-X1` on `D-RR18-X1` or `F23-X1` | `.L`, second wave | Flow against the position that also makes progress, or that persists | An alternative input to `C` in a later recipe, never a further trigger |
| `F41-X1`, adverse | `.L` | A jump beyond the frozen limit, with the signed return of the bar that set it against the position | **Goes straight to `EXIT`.** The one trigger outside `C` |
| `F37-X1` on `F26-X1` as an event | `.R`, if D14 allows | A sweep against the position, seen within a minute | **Cannot go live in this form** |

**On the hourly cycle: only slow conflict is left.** A sweep or fast reversal is seen up to an hour or more later, and by then the stop has probably fired or the move has played out. Three plain consequences:

- A trade that closes between runs never gets a flow look. Check D11 in the triage measures how many do, on the first training span only, and each reading is a counted trial. If most do, flow exit is untestable for that strategy, and that is reported rather than tested.
- Strategies with short holding periods get nothing. Multi-day holders may get something.
- Flow exits have the lowest fee hurdle, as the triage shows, but the hourly cycle takes most of that advantage away, since a late exit often gives up what it was meant to save.

**Later.** F11 and F12 need `T3`.

## 8. Stop tightening

**Question.** Should the stop move closer because of flow? **It may only move toward the market. Flow may never widen a stop, extend a time stop or extend a target.**

**When.** At each run, in step 3b. Every change goes through the stop ratchet in the strategy conventions (C8) with the C17 clamp. It starts from the stop after step 3, including any model stop pending from this run. The stop that takes effect is the tightest of the pending model stop and the flow stop. It acts from the first 1m bar with `open_time >= t_dec + latency`, and the bar straddling that instant keeps the old stop.

**Action allowed.** `TIGHTEN`.

| Feature | Kind | Why | Role |
|---|---|---|---|
| `F37-X1`, the same `C` as early exit, at `c1` | `.L` | A milder conflict earns a smaller response | **The only trigger** |
| `F37-X1` on `F24-X1` | `.R` | The same, at finer windows | Research |

**`F39-X2` and `F41-X1` do not tighten.** The earlier draft listed them, and the ladder in the gate specification has one `C`. `F39-X2` blocks new entries only. An adverse `F41-X1` goes to `EXIT`.

**On the hourly cycle.** The same limit as early exit. Tightening is cheap and easy to apply at a run, and it does not add a fee by itself. The risk is stopping out on ordinary noise, which the strategies' floors limit. A tighten that would breach a floor is logged and skipped.

## 9. Risk gate

**Question.** Should new risk be blocked, or existing risk reduced, because of market state or the state of our own data?

**When.** At each run. This has two parts, which must not be confused.

**Flow risk check, for flow variants only.** `VE`, `VEX` and flow-managed exits. It does not apply to `V0`, because `V0` is candle-only.

| Feature | Kind | Why | Action |
|---|---|---|---|
| `F41-X1` | `.L` | Discontinuity, out-of-distribution state | Block entry. Adverse on an open position: `EXIT` |
| `F39-X2` | `.L` | Stress state | Block entry |

**Run health check, for every variant.** Defined in [the gate specification](GATE_SPEC.md#34-run-health). It decides whether any decision can be made at all. It reads no book. F43 was the natural watchdog for a feed, and with no feed it has nothing to watch, so it is `LATER`.

**Portfolio limits (Layer 5)** are separate, use no flow, and apply equally to all variants.

**On the hourly cycle: partly survives.** It can block new entries once stress is visible at a run. It cannot pre-empt anything inside the hour, and a cascade that begins just after a run goes unseen until the next one. Stops on open positions are modelled as resting orders between runs, which is an assumption stated in the
[timing contract](../00_CHARTER.md#3-timing-contract), item 13, and it would have to be true if real orders ever ran on this setup.

## 10. Feature by decision point

Columns: **RF** regime filter, **SQ** setup qualification, **G** `ENTER`, `WAIT`, `VETO`, **T** entry timing, **O** order style, **X** early exit, **S** stop tightening, **RK** risk gate.

Codes: **L1** live-eligible, first wave. **L2** live-eligible, second wave. **R1** research-only, first wave. **R2** research-only, second wave. **C** control. **F** frame. **E** evaluation only. A dash means no use. `*` means only if check D14 allows.

`LATER` and `DROP` features have no codes. A `LATER` feature's intended point is in the last column, as a note only.

| ID | Title | Decision | RF | SQ | G | T | O | X | S | RK | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F01 | Spread State | `LATER` | - | - | - | - | - | - | - | - | Paid book. Would go to O, research. Never a live decision input |
| F02 | Relative Touch Depth | `LATER` | - | - | - | - | - | - | - | - | Paid book. Would go to RF, research |
| F03 | Depth Concentration | `LATER` | - | - | - | - | - | - | - | - | Paid book. Would go to SQ |
| F04 | Depth Entropy | `DROP` | - | - | - | - | - | - | - | - | |
| F05 | Liquidity Gap | `LATER` | - | - | - | - | - | - | - | - | Paid book. Would go to O, research |
| F06 | Bid–Ask Gap Asymmetry | `DROP` | - | - | - | - | - | - | - | - | |
| F07 | Average Order Size | `LATER` | - | - | - | - | - | - | - | - | Needs `T3` |
| F08 | Order-Size Concentration | `LATER` | - | - | - | - | - | - | - | - | Needs `T3` |
| F09 | Persistence-Weighted Depth | `LATER` | - | - | - | - | - | - | - | - | Needs `T3`. Would go to SQ |
| F10 | Fleeting Liquidity Ratio | `LATER` | - | - | - | - | - | - | - | - | Needs `T3`. Would go to G |
| F11 | Cancel-to-Add Ratio | `LATER` | - | - | - | - | - | - | - | - | Needs `T3`. Would go to G, X |
| F12 | Cancel-to-Trade Ratio | `LATER` | - | - | - | - | - | - | - | - | Needs `T3`. Would go to SQ |
| F13 | Queue Survival Probability | `LATER` | - | - | - | - | - | - | - | - | Needs `T3` |
| F14 | Queue Half-Life | `LATER` | - | - | - | - | - | - | - | - | Paid book. Would go to RF |
| F15 | Queue Churn | `LATER` | - | - | - | - | - | - | - | - | Needs `T3` |
| F16 | Imbalance Persistence | `LATER` | - | - | - | - | - | - | - | - | Paid book. Would go to SQ, G, X, research only |
| F17 | Imbalance Flip Rate | `LATER` | - | - | - | - | - | - | - | - | Paid book. Would go to G, research |
| F18 | Price Response per Signed Volume | `ADAPT` | - | L1 | L1 | - | - | L2 | L2 | - | Via `D-RR18-X1` |
| F19 | Local Kyle Lambda | `ADAPT` | L2 | L1 | L1 | - | - | L2 | L2 | - | Via `D-RR18-X1` |
| F20 | Impact Surprise | `LATER` | - | - | - | - | - | - | - | - | Would go to SQ |
| F21 | Post-Trade Relaxation | `LATER` | - | - | - | - | - | - | - | - | Would go to T, research |
| F22 | Flow Saturation | `LATER` | - | - | - | - | - | - | - | - | Would go to SQ |
| F23 | Trade Run Length | `ADAPT` | - | - | - | R2 | - | L2 | L2 | - | Minute bars. An input to `C`, never a further trigger |
| F24 | Trade-Sign Entropy | `ADAPT` | - | L1 | L1 | R1 | - | L1 | L1 | - | Balance only. Timing at 4h is `.L` too |
| F25 | Large-Trade Surprise | `ADAPT` | - | L2* | L1* | - | - | - | - | - | Summary form. First pass in S09 only |
| F26 | Sweep Penetration | `ADAPT` | - | L2*, R1* | R1* | R2* | - | R1* | R1* | - | Summary live, event form research only. No `.L` first-pass row |
| F27 | Absorption Efficiency | `ADAPT` | - | L2 | - | - | - | - | - | - | After the fact, live. S04 row 4 |
| F28 | Refill Elasticity | `LATER` | - | - | - | - | - | - | - | - | Paid book. Would go to T, research |
| F29 | Absorption Duration | `LATER` | - | - | - | - | - | - | - | - | Would go to SQ |
| F30 | Breakout after Absorption Failure | `LATER` | - | - | - | - | - | - | - | - | Would go to SQ |
| F31 | Momentum–Reversal Score | `DROP` | - | - | - | - | - | - | - | - | |
| F32 | Queue Value | `LATER` | - | - | - | - | - | - | - | - | Needs `T3` |
| F33 | Fill-to-Adverse-Move Race | `LATER` | - | - | - | - | - | - | - | - | Needs `T3`. Would go to O |
| F34 | Cancel Success Probability | `DROP` | - | - | - | - | - | - | - | - | |
| F35 | Opportunity Cost of Not Filling | `ADAPT` | - | - | E | E | E | - | - | - | Never an input |
| F36 | Inventory-Adjusted Fair Value | `DROP` | - | - | - | - | - | - | - | - | |
| F37 | Inventory–Flow Conflict | `ADAPT` | - | - | - | - | - | F | F | - | Frame on its input |
| F38 | Quote Edge Buffer | `DROP` | - | - | - | - | - | - | - | - | |
| F39 | Liquidity Stress Index | `ADAPT` | L1 | - | - | - | - | - | - | L1 | `F39-X2` only. Blocks entries, no exit action. `F39-X1` is `LATER` |
| F40 | Volatility of Volatility | `LATER` | - | - | - | - | - | - | - | - | Would go to RF |
| F41 | Jump Score | `ADAPT` | L1 | - | - | - | - | L1 | - | L1 | `JSmax_60` on the cycle. Adverse goes to `EXIT` |
| F42 | Volume-Time Position | `ADAPT` | C | C | C | C | - | C | C | C | Control throughout, never a gate input |
| F43 | Time Since Last Midpoint Change | `LATER` | - | - | - | - | - | - | - | - | Needs a live stream |
| F44 | Regime-Conditional Feature Reliability | `LATER` | - | - | - | - | - | - | - | - | After two features survive |

## 11. Reading across

- **The live function of this project's flow layer is narrow:** a filter at the first look, and a slow risk reduction on trades held for many hours.
- **Every flow input that can go live comes from a single source: `T1` signed trades,** so features at the same decision point overlap heavily. They must be tested as families and never counted as confirming votes.
- **Ablation means removing one member of a recipe to see what it adds.** It is pre-registered per recipe, decided on training spans, and each removal is a counted trial. On test blocks only a frozen recipe is reported. See [section 8.8 of the gate specification](GATE_SPEC.md#88-ablation).
- **Everything about the book is `LATER`,** which includes the owner's direct interest in order imbalance. Nothing plans on it. Paid history would let it be backtested as research, and is a later owner decision. It would still not reach live without an always-on machine (`D-04`).
- **Most of these questions cannot be answered one strategy at a time.** The [matrix](STRATEGY_FEATURE_MATRIX.md#4-can-each-gate-question-be-answered) predicts `INCONCLUSIVE` for the entry gate of each live strategy on its own, and sets out the class-level questions that can be answered.
