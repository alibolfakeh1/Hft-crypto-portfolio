# Leak re-audit: feature documents

Date: 2026-11-05. Auditor: `leak-auditor`, independent of the author.

Target: `GATE_SPEC.md`, `STRATEGY_FEATURE_MATRIX.md`, `FEATURE_TRIAGE.md` and `DECISION_POINT_MAP.md` in `docs/02_features/`, at commit `3f0db56` on `pipeline/first-data-run`. Earlier audit: [features_2026-11-04.md](features_2026-11-04.md), unchanged.

**Scope.** The research source is open again, and the primary route in `D-22` no longer stands. Everything tied to the named source is marked `PENDING SOURCE`. It was not audited in depth, and section 7 says what must be rechecked. Text that still names the earlier source is a correction pending, not a leak.

## Ruling on the H5 conditions at `481f6a1`, 2026-11-06

**`PASS WITH CONDITIONS`.** I read `481f6a1`'s diffs of the matrix (7.6, the new 7.7, the symbol rule and the single-strategy formula), of index section 4, and of the change record. I checked each against the rows that a run's output already holds. Nothing ran. The H5 ruling below stands as written.

| Item | Verdict | Why |
|---|---|---|
| B: the single-strategy `N` may only rise | `PASS` | It is in the text, and the form stays as written. Read 7.6's first condition, "every class line at once", as every result under the rule in question, for this `N` and for 7.7. Whether to count lines still due is open until the first flow verdict. Under this rule it can only be decided upward |
| The only-rise rule's three conditions | `PASS` | All three are in 7.6. A verdict keeps its `N` and date, and a later report prints its own beside it |
| The `.R` twin | `PASS` | It is recorded as "not evaluated", never as passed |
| C, flow half (matrix 7.6) | `PASS WITH CONDITIONS` | The set follows the result's own `N`, and a stream is left out only for a reason fixed now: it has no stream of its own, its output is sealed, or its Sharpe ratio is undefined, and the number left out is printed. None of these depends on an outcome. Narrower than my example, but I accept it. A trial with no return stream has no Sharpe ratio to give without a new read. Conditions C1 and C2 below. Also, lines still due count in `N_class`, and like the index, 7.6 should say they are left out of the spread |
| C, candle half (index section 4) | `PASS WITH CONDITIONS` | The same principle over 7.7's `N`. It names lines not yet run, and controls are in neither. Conditions C1 and C2 |
| 7.7: `N` for a candle-only `V0` result | `PASS WITH CONDITIONS` | The whole count is right. One strategy's grid would leave out the search beside it. 122 recomputes as 104 + 16 + 2. A stage's own declared lines counting from its first verdict means reading one strategy early gains nothing. **Condition E:** stage 1 gives no verdict in the gate sense. Matrix 3.1 decides on out-of-sample blocks only, and the guard holds at 2023-12-31 through all of stage 1 (fold plan section 9). So "the first verdict on stage 1" should read "the first figure printed on stage 1, which is in-sample description (fold plan section 5)", and keep `N_V0` at 122 |
| D, the text part | `PASS` | The index's "multiplies" sentence is now a pointer to fold plan section 6 and matrix 7.6 and 7.7, so the frozen texts no longer disagree. The rest of section 4 is unchanged. It is wording, and cites no result |

**C1. Name the Sharpe ratio each symbol run gives.** "As its own run recorded it" is not one figure. A run records Sharpe ratios on more than one basis:

- for each line and symbol, for both symbols together, by side, and for S08 by branch, which is S08's unit of trial;
- under `IDEAL-1M`, and under `IDEAL` if ruling 7 condition 2 holds;
- for a test-block run, over a range that starts at `T_start`, while only the block itself is judged (fold plan section 6, R-03).

Choosing among these after the first `V0` run has printed them would be a choice made on its Sharpe ratios. So name the figure now, for both halves. For example: the `sharpe` field of the line's strategy-asset row, net at 1x cost, from daily equity returns, under the headline mode and scenario, over the range that is judged. Owners: `feature-integrator` for flow, `strategy-architect` for candles.

**C2. After the C-5 commit, a change to the spread rule may not lower the bar.** The only-rise rule protects `N`. A different set of trials can move the spread either way, so the spread rule needs its own guard. A change made after the Sharpe ratios are shown could pick a smaller spread for every result at once. So any later change computes the deflated Sharpe ratio's benchmark under both rules, and uses the higher, for every result at once. A recorded verdict keeps its own. Same owners.

**C-5 part 5 is not closed by A and D's count alone.** It closes once these are in the C-5 commit:

- A and D's count, with `project-manager`;
- C1 and C2, which are a sentence each;
- E;
- the 7.6 wording on lines still due.

**The first `V0` run: no change to my verdict at `d888254`.** 7.7 raises `N` for candle results, which errs high, and stage 1 gives no gate verdict. C changes nothing either, because the C-5 commit comes before the first run. If C1 and C2 were not in it, which figure enters the spread, and any later change to the set, could follow the first run's Sharpe ratios.

## Ruling on H5's pooled `N`, matrix section 7.6 at `80ec7b8`, 2026-11-06

**`PASS WITH CONDITIONS`. Section 7.6 closes H5 condition 1, and with the conditions below it closes C-5 part 5.** I read `80ec7b8`'s diff of `STRATEGY_FEATURE_MATRIX.md` (section 7.6 and the four edits), section 3 of the matrix, sections 5, 6, 9, 10 and 11 of the fold plan, and index section 4. Nothing ran, and no market data was read. The sections below stand as written.

| # | Question | Verdict | Why |
|---|---|---|---|
| 1 | Does the whole-project count close H5 condition 1? | `PASS` | I asked for the sum of pooled grids, or a reason not to use it. The reason holds: a pool's members can change with outcomes (a strategy kept in the pool after failing its C15 prerequisite, a strategy retired under C18), so a count tied to membership could be argued after a result, and the whole count cannot. It is never below my per-pool figures of 280 to 344. 498, or 482 if D14 fails, recompute, and the rise in `sqrt(2 ln N)` over those figures is 2.8% to 5.0%. Counting lines still due stops a line read early from getting a smaller `N`. D14 is a source-wide check made before any run, so the 16 lines it can drop cannot follow a result. No discount for overlap, which would be a fitted choice. Counting more than the independent trials errs high |
| 2 | Does this text close C-5 part 5? | `PASS WITH CONDITIONS` | H5 condition 2 is closed by fold plan section 6. Condition 1 is closed by item 1 above. Part 5 closes once conditions A to D below are in the C-5 commit |
| 3 | Do the 8 stage 1 C15 readings count as 16? | `PASS` | Matrix 3.2 makes each reading a counted trial, since it labels a strategy. Each pools both symbols, so the symbol rule gives two. A reading re-reads the default line's trades, so it is partly counted already, which errs high. They are not the readings of family K, which are new ones on bars from trades, so they are not counted twice. Condition D makes the printed count show both figures |
| 4 | Is the argument for the missing `.R` twins sound? | `PASS WITH CONDITIONS` | Yes. `SUPPORTED` needs the 95% CI of the `.L` line's `D`, under its headline scenario `C-LATE` (gate specification P2), to exclude 0 in the expected direction, so R5's cross-kind clause binds only where `.L` under `C-LATE` is not positive, which is where `SUPPORTED` is already out of reach. The twin's absence cannot help a line to `SUPPORTED`. It can only spare a weak line the R5 label. **Condition:** a class verdict with no twin records R5's cross-kind clause as not evaluated, never as passed. A twin is registered before its `.L` line is read, as written |
| 5 | Does "after C-5, `N` may only rise" sit inside the fold plan's rule for changes? | `PASS WITH CONDITIONS` | Yes. It is the same rule, a dated decision that states its reason and cites no result, with a direction added, as a stop may only tighten. **Conditions:** a change applies to the rule for every class line, never to one line or one verdict. A recorded verdict keeps its `N` and date. A line dropped after C-5 for any reason other than D14 stays in `N`, which "may only rise" already implies |
| 6 | Must the C-5 diff audit, part 3, include this change? | `PASS` | Yes. The matrix is anchored at `747a37a`, and section 10's row for the four feature documents still reads "`3f0db56` 11:46, with more due". `80ec7b8` goes in that row, stating whether its writer saw `D-32`'s output. Either way I accept it: its reason is H5, it cites no result, and a rule that can only raise `N` cannot be used to favour one |

**Conditions for C-5 part 5,** all in the C-5 commit, which comes before the first `V0` outcome.

| | Condition | Owner |
|---|---|---|
| A | Section 10's anchor row for the feature documents names `80ec7b8`, and says whether its writer saw `D-32`'s output | `project-manager` |
| B | The one-way rule also covers the single-strategy `N` at the top of matrix section 7: after C-5 it may only rise | `feature-integrator` |
| C | The trial set for the cross-trial spread of Sharpe ratios, the deflated Sharpe ratio's other input that depends on choice, is fixed now: every trial counted in `N`, or another set stated now. The estimators may follow | `feature-integrator` |
| D | Index section 4 still says "each symbol and each flow variant multiplies this count". It points to fold plan section 6, which replaced the second half, so two frozen texts do not disagree. The count printed beside a run (part 6) shows the 8 readings as 16 symbol runs | `strategy-architect`, `project-manager` |

**Must the single-strategy formula or the other inputs be settled before the first `V0` run?**

- **The single-strategy formula: no change is needed, only condition B.** It is already written, and it enters the C-5 commit. Stage 1 gives no flow result, so nothing reads it yet. One point for later, not now: it counts flow lines "run so far", so a row given its verdict before the rest of its family runs takes a smaller `N`. Section 7.6's own third reason applies to it. Under condition B the fix can only raise `N`, so it may wait until before the first flow verdict.
- **The other inputs: their values no, but condition C yes.** Stage 1's lines are trials in `N`, so the first `V0` run shows Sharpe ratios that would enter the cross-trial spread. Choosing after that which trials enter, for example leaving out the candle lines, would be a choice made after seeing them. Skew, kurtosis and sample length come from the line's own returns and block, so they can be fixed before any flow outcome, as 7.6 says.

## 1. Verdict

**Overall, for the source-independent parts only: `PASS WITH CONDITIONS`.** This covers the clock, windows, outcomes before freezing, block reuse, the trial count, gates and purge. It says nothing about any source-tied part, and it is not a verdict on the documents as a whole.

All five high findings are closed in design, on the source-independent side. No faithful implementation of this text now leaks at high severity. Six new medium or lower problems came with the rewrite, and the conditions in section 6 must be met in the order given there.

This is a verdict on text. All sources stay disabled, and nothing has run.

| Document, source-independent parts | Verdict | Conditions |
|---|---|---|
| `GATE_SPEC.md` | `PASS WITH CONDITIONS` | N1 to N6, H5 |
| `STRATEGY_FEATURE_MATRIX.md` | `PASS WITH CONDITIONS` | N1 to N5, H5 |
| `FEATURE_TRIAGE.md` | `PASS WITH CONDITIONS` | N2, N6 |
| `DECISION_POINT_MAP.md` | `PASS` | None. It sets no timing, and states that the gate specification governs where they differ |

Finding verdicts below: `FIXED`, `FIXED WITH CONDITIONS`, `NOT FIXED`, `PENDING SOURCE`. No finding is `NOT FIXED`.

## 2. The four places the author departed from my wording

I checked each against the later ruling. **All four are accepted, and my wording is withdrawn in each.**

| Finding | Author's reading | Ruling | Why |
|---|---|---|---|
| H1 | `t_poll` is C17's runner clock at the start of the fetch attempt, not server time at the last page | **Accepted** | It is earlier than the end of the last page, so the cut is earlier and only freshness is lost. A clock running behind moves the cut earlier. One running ahead moves the cut past the data, and the completeness check then fails. The backtest and the run compute the same cut. `t_cut + A <= t_poll <= t_dec` holds by construction, and I10 tests it |
| H2 | Over budget gives `DATA_GAP`, not `flow_blind` | **Accepted** | Under `D-12` and C2, the same trades build the bars, so a failed poll removes the bars too. `V0.L` and flow variants therefore lose the same runs, which is fairer than my wording. It holds only while one feed serves both, so it must be rechecked on the chosen source |
| M15 | `.R` fills follow `IDEAL-1M`, and no flow variant runs in `IDEAL` | **Accepted** | A look at `u` fills at the first 1m bar with `open_time >= u + max(latency, A)`, later than the first trade I asked for. `IDEAL` reads only `settled_*` volume, so flow cannot run in it. With `A >= fill_span_allowance_ms`, a record stamped by `u` has printed before the fill |
| M16 | Purge uses `H_max`, not label end | **Accepted** | My label-end rule made removal depend on the outcome, which item 11 now forbids. My scenario is still covered: a stop touched at 23:50 and detected at 00:12 is a trade still open when the training simulation's data ends at 00:00, so it is removed and counted |

## 3. The author's declared values

| Value | Ruling | Detail |
|---|---|---|
| **Trial count:** 124 flow lines, 188 lines, 376 symbol runs, `N` of 256 or 264 | **The arithmetic holds, on conditions** | All recompute, as does 116 if D14 fails. The later-row list of 18 matches the tables. The reconciliation to my figure is correct: my 112 was 56 + 18 + 4 + 18 + 16, and each part is traced. See H5 for the two conditions |
| **Fold plan: structure** (locked by date, 18-month first span, coverage-only start, quarters) | **Accepted, on conditions** | 18 months and the quarter calendar use no data and match C12. See N4 for what "read" means, and the first item below for a late failing quarter |
| **Fold plan: dates** (research data end, locked block 2025-10-01 to 2026-09-30, `T_start`) | `PENDING SOURCE` | They rest on one source's file end and coverage. Freeze new dates before any outcome on the chosen source |
| **Cache-loss stress:** one loss per 90 days, state back after the full horizon until rebuild time is measured | **Rule accepted. Values not usable as they stand** | With 84 days to recover, a feature is in `WARMUP` for 61% of the time if losses are Poisson, or 80% with one loss in each 90-day block. See N3 |
| **Numeric R6** (unproved empty minutes under 1%, at least 100 trades in each of 90% of hours) | `PENDING SOURCE` | Not audited in depth. Section 7 lists three arithmetic points to recheck |

**A late failing quarter has no declared handling.** `T_start` is the first quarter from which *every* later quarter meets the coverage rule. If one quiet quarter such as 2024-Q3 fails, `T_start` becomes 2024-Q4, and an 18-month span ends on 2026-03-31, inside the locked block, leaving no test block. Fix: before reading any coverage, declare the minimum number of test quarters, and what happens below it. No outcome is involved, so this is not a leak, but deciding it after the G1 report is out is a choice with hindsight.

## 4. Verdict per finding

### High

| ID | Verdict | Evidence, and what remains |
|---|---|---|
| H1 | `FIXED`. Value of `A` is `PENDING SOURCE` | One `t_cut` per run and symbol, `P_dec`, all windows and rule 1 read it. `t_dec` is used only for fills and `effective_from`. The poll offset test is added, and D10 now compares a bar as first seen at a run |
| H2 | `FIXED`. Capacity values are `PENDING SOURCE` | The modelled fetch in 3.6, P5 and the capacity test are source-independent, and a backlog carries forward. An unknown value must not relabel the result: see N2 |
| H3 | `FIXED WITH CONDITIONS` | Dated verdicts and `EXPLORATORY` are in GATE_SPEC 8.6 and matrix 3.1. Condition: N4. Item 11 still does not say that an earlier test block may join later training, and section 15 correctly asks for it |
| H4 | `FIXED WITH CONDITIONS`. Dates are `PENDING SOURCE` | Fold plan frozen before outcomes, `V0` chosen per fold under C18, and pre-block readings limited to the first training span and counted. Conditions: N1, N4, N6 |
| H5 | `FIXED WITH CONDITIONS` | A bottom-up list, with the symbol rule in one place. Two conditions follow |

**H5 conditions.**

1. **`N` is undefined for a pooled class test.** The formula names "the strategy's `V0` grid", but C-1 to C-5 pool strategies, each carrying its own selection. Using the sum of pooled grids, `N` is 328 for C-1, 280 for C-2, 312 for C-3, and 344 for C-4 and C-5. Fix: state this, or state a reason not to.
2. **Half of the index sentence is unresolved.** Index section 4 says each symbol *and each flow variant* multiplies the count. The matrix adopts the first half and asks about it, while replacing the second with lines on one frozen configuration. That is reasonable, but `project-manager` must rule on both halves.

### Medium

| ID | Verdict | Evidence, and what remains |
|---|---|---|
| M1 | `FIXED` | Availability uses the declared minimum delay, a test covers the next run, and no decision reads a realised run. The realised table recomputes as 16%, 49%, 95%, 49% under `C-LATE`. See L7 for a rounding slip under `C-BAD` |
| M2 | `FIXED` | GATE_SPEC 5.3 and 11 and `F35-X1` agree. `WAIT` carried into `STALE_SETUP` counts 0 against `CF_CYCLE` under `VE.F`. `CF_IDEAL` is excluded from `D` |
| M3 | `FIXED` | Shadow `V0` per setup, P6 shares run times, the seed mean is the statistic, and `blocked` is rules 3 and 4. See L7 on `ENTRY_COLLAR` |
| M4 | `FIXED` | `S` includes the pending model stop, the tightest takes effect, and I1 and its test are extended |
| M5 | `FIXED` | C17, 5.5, I2 and a test. **Time stops are also clean:** under `.T`, `n` counts from the trade's own later fill, so the hold length is not extended |
| M6 | `FIXED` | `settle` walks every earlier 1m bar, and a touch stands and cancels the pending exit |
| M7 | `FIXED` | `effective_from` is the fill bar's open, and the straddling bar keeps the old values |
| M8 | `FIXED WITH CONDITIONS` | The state table, the 84 and 85 days and a cache-loss rule are all there. Condition: N3 |
| M9 | `FIXED` | Members use their own point-in-time values. See L7 on the wording of the test |
| M10 | `FIXED` | `tau_p = 0`, `RR` on the grid, `AE` against earlier setups with at least 30, unsigned limits in their own units, minimum scale fitted, "adverse" defined, "rising" removed. `F28-X1` is `LATER`, with its cut required before revival |
| M11 | `FIXED` | The fit runs on `(t0 - 24 h, t0]` with member fits on their own `t0`, and I11 tests it. Both sides now use a per-minute denominator, so `RR` is about 1 as claimed |
| M12 | `PENDING SOURCE` | No `T2` row runs now. D13 and the reinstatement conditions are correct as a holding rule |
| M13 | `PENDING SOURCE` | G4, the D2 requirement, the mirror-test caveat and the D14 list are sound in structure. All contents wait for a source |
| M14 | `PENDING SOURCE` | "Same source for both kinds" and "nothing reassigns `flow_venue`" are accepted. The ordered list and its trigger no longer apply |
| M15 | `FIXED` | See section 2. L7 notes one gap in the mode table |
| M16 | `FIXED` | See section 2 |
| M17 | `FIXED` | GATE_SPEC 8.8, matrix 3.2 and map 11 |
| M18 | `FIXED WITH CONDITIONS` | Draws declared, no redraws, run through the same function and run times. Condition: N1 |
| M19 | `FIXED` | Artifacts keyed by `(kind, source)`, I8 extended, `.L` recipes frozen before any `.R` result, and R5 the only cross-kind decision. See N2 for a related relabel |
| M20 | `FIXED` | A shadow is a counted trial with its readout fixed at the start |
| M21 | `FIXED`. Value of `RT` is `PENDING SOURCE` | Declared before any block, measured slippage only in reports, D12 report-only, `b` declared or from the first span if ever revived |
| M22 | `FIXED` | `decide` never receives a snapshot, I8 is reworded, the F01 `RK` code is gone, and the run-health idea in triage 5.8 is withdrawn |

### Low

| ID | Verdict | Evidence, and what remains |
|---|---|---|
| L1 | `FIXED` on `Bar` windows | Members end at or before `t_cut - W`. `Anchored` windows are not covered: see N5 |
| L2 | `FIXED` | Flow exits pay `slip` |
| L3 | `FIXED` | A reselection is counted and applies to later blocks. C17 still says `C-MEASURED` "replaces" `C-LATE`, where GATE_SPEC 9 says it "reports alongside". One wording should give way |
| L4 | `FIXED` | `decide` and `settle` are separate, and the poll offset test is added |
| L5 | `FIXED` | Overlap is logged, and R4 is reported by band |
| L6 | `FIXED` | All ten items are checked. One remnant: map section 2 lists `F19-X1` under reason `stress`, while rule 3 names only `JSmax_60` and `F39-X2`. It is second wave, and the map defers to the gate specification |

### Section 4 of the earlier audit

| Risk | Verdict | Note |
|---|---|---|
| Inverted or undefined trade sign | `PENDING SOURCE` | The rule is sound: the mirror test is stated not to check the side, and a change after results is a new trial |
| Stamp meaning or resolution | `PENDING SOURCE` | D5 and D14 have the right list |
| Bars or files stamped at period start | `PENDING SOURCE` | `knowable = label + interval` is declared, and the screen is built from trades |
| REST and archive disagreeing | `FIXED` in method | D10 compares a bar as first seen at a run. Values wait for a source |
| Throughput or retention below coverage | `FIXED` in method | H2 |
| Flagged trades | `FIXED` in method | G8 declares "all included" now, and a change after results is a new trial. D4 results wait for a source |
| Choosing a venue after results | `PENDING SOURCE` | With the list void, **nothing is registered at present**. See section 7 |
| Different venues for `.R` and `.L` | `FIXED` | Same source, in all four documents |
| Vendor archive | `FIXED` in method | It stays `.R` until shown to match the poll. See N2 on what that label may mean |
| Sampled days only | `FIXED` | Features are `WARMUP`, and are not computed on a shorter window. See N6 |

## 5. New problems in the rewrite

| ID | Document and section | Leak class | Scenario | Severity | Fix |
|---|---|---|---|---|---|
| N1 | GATE_SPEC 8.3, 11. Matrix 3.2, 7.1 family K. C15 | Control fitted with later data | C15 builds the distance distribution only on earlier blocks, so "the first block has no placebo". Family K asks for `V0` against C15 "on the first training span alone", for all ten strategies. For the six level strategies (S01, S02, S04, S05, S06, S08) no earlier block exists. To produce the line, code must draw a February level from a distribution holding May's levels, or from later blocks | Medium | Within the first span, treat calendar quarters as blocks: each quarter draws only from earlier quarters, and the first quarter has no placebo and is reported as such. Say the same for the first test block, which may use the whole first span |
| N2 | GATE_SPEC 2, 3.6, 9. Matrix 2.2. Triage 5.6, against the `.R` row in GATE_SPEC 2 and "no `CYCLE` run may start" in C17 | `.L` and `.R` separation | Capacity values are unknown, so a developer runs the hourly clock with no modelled fetch on the test quarters. The text says such a result "is `.R`". It trades hours no run could see, which is H2 again. It carries a label defined as `IDEAL-1M` while holding `CYCLE` figures, it can enter R5 as "`.R` is positive", and it reads those quarters for `.L` | Medium | Delete the relabel in all three documents. `.R` means `IDEAL-1M` only. Before the conditions hold, no `CYCLE` run exists, as C17 says. A run that fails a parity item is not a result, is logged as invalid, and its outcomes are not read |
| N3 | GATE_SPEC 3.4, 3.7, 7, 9 (P3, P6). Matrix 7.4. C3 | Backtest holding state a run would not | **P3** makes the stress a requirement, with failure meaning `.R`. **Matrix 7.4** calls it a report. As a requirement, `.L` is blind 61% to 80% of the time until rebuild is measured. As a report, the headline holds state a run may not. **`V0.L` is also treated as unaffected**, "unless the bars themselves are gone", yet the 1m bars in 3.7 are the candle bars under `D-12`, and C3 rebuilds from the canonical start. So after a loss, a backtest's `V0.L` trades hours in which a live one could not. P6 shares run times only, so loss times could differ between recipes | Medium | One sentence in both documents: the headline assumes no cache loss and says so, and the stress is a required report beside it. Apply a loss to `V0.L` too: what a run cannot rebuild for candles is `DATA_GAP` or undefined on both paths. Share seeded loss times across variants and placebos. Publish no stress figure on the full-horizon default |
| N4 | GATE_SPEC 8.2, 8.6. Matrix 3.1. Index C15, C18. Roadmap | Locked block reused or read by the back door | "Once on the locked block" can be read per refinement, so A then B each read it, and B was chosen knowing A's result. The block appears in no other document: C18, C15 and the roadmap do not mention it, so a strategy-level G3 or a portfolio report on `V0` can read it. "Read by nothing" also conflicts with the coverage rule, which reads those quarters. With a fixed data end, "blocks after that date" do not exist unless quarters are added. "Not yet read for this question" leaves "question" open | Medium | One global read at the final verdict, of every candidate frozen that day, all counted. Define "read": any price, return, flow or outcome. G1 id and empty-minute counts are not a read. C18, C15 and the roadmap adopt it. Later quarters join only as new dated blocks. Replace "for this question" with "by the verdict that led to this row" |
| N5 | GATE_SPEC 3.2 and 8.1 by reference, 4, 3.7. Matrix 2.1 | Current observation in its reference, `Anchored` | S02's acceptance window is `(17:00, 20:00]`. `A` is taken at a look with `t_cut = 23:09`. Members may end up to 20:09, so one ending 20:07 overlaps the ranked window by 173 minutes, against "never enters its own reference". No future data is involved | Low | Rank an `Anchored` value at its object's knowable time, with members ending at or before that time minus `W`, and hold the rank in state beside the value |
| N6 | Triage `H-PILOT`. GATE_SPEC 8.2. `D-22` | Locked and test dates read during the build | Sampled first-of-month files include days inside the test and locked dates. If that venue later becomes the approved source, the pipeline has read prices on those days. `H-PILOT` bars results, but not the reading | Low | Confine pilot runs to dates before the first test block, or log every day read under C-7 and compute no strategy outcome on them. C-7's list should also name the days of other venues' files opened before `D-17` |

### L7: smaller points in the rewrite

Each is `Low`, and each is a short text fix.

1. **Rounding.** Under `C-BAD`, the 90-minute second look and the 150-minute third look compute as 32.4%, and GATE_SPEC 5.4 says about 33%.
2. **"`V0` also rejected".** GATE_SPEC 11 does not say whether this covers `ENTRY_COLLAR`, which is known only after the decision. Excluding it on both sides is fine, and it should be stated.
3. **Member test.** "Recomputing a member a month later gives the identical number" holds only on the same delivered data, because C3 says a late trade changes a rebuilt bar. Add that condition.
4. **Worked example, GATE_SPEC 13.** At `run_start = 13:08:10`, `t_poll - A` is exactly 13:08:00, so C17's backtest evidence window `(t_cut, t_poll - A]` is empty, and the cut would move back to 13:07:00 unless a modelled server time exists. The example keeps 13:08:00.
5. **`E_W`.** It is defined at `hour_of_week(t)`, and neither a 240-minute nor a variable `Anchored` window says how buckets combine. Past data only, so no leak, but replay needs one definition.
6. **Mode table.** `IDEAL-1M` says "at the bar close". GATE_SPEC 10 extends it to looks at `u` between closes. The owner of the table should add this, since C14 records only the mode's name.
7. **`F23-X1`.** It is wave 2L and a map input, but has no matrix row, so no line exists if it runs.

### L8: `Anchored` state

See N5. `AE` values kept "for the life of the record" also sit in a cache that can be lost, and GATE_SPEC 3.7 gives no route to rebuild them. They should be recoverable from the append-only `decisions` record, or be `WARMUP`.

## 6. Conditions

| # | Condition | Owner | Due |
|---|---|---|---|
| 1 | N2: remove the `.R` relabel | `feature-integrator` | Before any flow code |
| 2 | N3: settle headline and report, apply loss to `V0.L`, share loss times | `feature-integrator`, `data-steward` | Before any `.L` backtest |
| 3 | N1: first-span placebo by quarter | `feature-integrator`, `strategy-architect` | Before family K runs |
| 4 | N4: one global locked read, a definition of "read", adoption in C18, C15 and the roadmap | `project-manager`, `feature-integrator` | Before the first `V0` run, with C-7 |
| 5 | Item 11: earlier test blocks may join later training only. Rule on expanding training | `project-manager` | With C-7 |
| 6 | H5: pooled `N`, and a ruling on both halves of the index sentence | `feature-integrator`, `project-manager` | Before the first counted line |
| 7 | Declare the handling of a late failing quarter, before coverage is read | `feature-integrator`, `project-manager` | Before `T_start` is computed |
| 8 | N5, N6, L3, L6 remnant, L7, L8 | `feature-integrator` | Before the fixtures for gate G2 |
| 9 | Section 7, on the chosen source | `leak-auditor` | Before the first run on that source |

## 7. `PENDING SOURCE`: what must be rechecked

| Item | Recheck |
|---|---|
| **Source named in the text** | All four documents still name the earlier source and fallback, including the header statements and the status tables. Replace them. Nothing about the choice is inferred here |
| **Venue choice (M14)** | No registered list exists now. Before any flow outcome, register an ordered list, a numeric R6 and the trigger for moving down it. A trigger must never be a result |
| **Source card, D2, D5, D14 (M13)** | Per endpoint: side meaning, stamp meaning and resolution, bar label, ids, corrections. The D2 method is written for one source's fields |
| **Poll capacity (H2), `A`, `fill_span_allowance_ms`, C-10** | Page size, rate limit, reach, trades per hour, fetch offset, and `D_run` for `T0`. Recheck that bars and flow still share one feed. If they do not, a poll failure can be flow-only, and `flow_blind` returns on that path |
| **Numeric R6, D8** | Rederive it from what `CYCLE` needs. Three points of arithmetic: at the floor of 100 trades an hour, about 19% of minutes are empty by chance. Two adjacent non-empty minutes then occur about 66% of the time, below the 70% `F19-X1` needs. And 1% of minutes unproved, if independent, puts a gap in about 45% of hours, each a `DATA_GAP`, with `GAP_CLOSE` if it stays open |
| **Fold dates** | Research data end, locked dates, `T_start`, and the fallback clause in GATE_SPEC 8.2, frozen before any outcome on that source |
| **Fee section 5.5, `RT`** | Treated as a declared constant here. The C9 floor changes setups, so it must be declared before any block |
| **`T2` status (M12)** | If paid history is chosen, `T2` features may come back. Those rows need their own audit, and D13 is required before any of them. A band source change is a new derived ID |
| **Spot-only text** | G6, 5.4 and section 6 of the triage remove funding and perpetual inputs. A different instrument would bring them back, and their timing under C10 needs auditing |
| **`FP*` lines** | 124 or 116 flow lines depends on D14 |
| **Design frequencies, power tables, `H-` table** | All restated for the chosen source. Not a leak |

## 8. Left open on purpose

Neither item is counted against the documents.

- **S07 and S08 under `IDEAL`.** The text does not depend on the outcome. No flow row reads `IDEAL`, and the cost of the cycle uses `IDEAL-1M` where no `IDEAL` exists.
- **A `gap` flag resting on a later row.** GATE_SPEC 3.3 and 3.4 defer to the ruling. One word leans on an outcome: the coverage test says a hole invalidates "exactly" the windows that cross it. If the ruling attaches the flag to a later row, that test must follow it.

## 9. Checked and clean, and what could not be checked

**Checked and clean.**

- **Flow timing.** Windows and rule 1 read `t_cut`, and `t_dec` reaches only fills and `effective_from`. Step 3b reads position state as of `t_cut`, and `settle` feeds nothing back.
- **`WAIT`.** Each look recomputes on its own `t_cut`, and no decision reads a later run.
- **Worked example.** The clock, fill, `R`, `C` and lateness recompute, apart from L7 item 4.
- **Exits.** No path found widens a stop. A pending exit blocks a second order, and C11 counts it as open.
- **Purge.** Class tests take the largest values in the pool, and counterfactuals are knowable only at maturity.
- **Derived features.** `F18-X1`, `F19-X1`, `D-RR18-X1`, `F41-X1`, `F39-X2` and `F42-X1` remain past-only as rewritten. The earlier truncation results apply, since the windows did not change in form. I did not repeat them on the new `t_cut` wording.

**Could not check.**

- Nothing has run, and no code exists. All figures here are arithmetic on assumed values, from a throwaway script that used no market data and no network.
- Whether any date in the fold plan was read during the build. That record is C-7's, and it does not exist yet.
- Every value marked `UNVERIFIED` in the documents.
- Strategy documents beyond what these four rely on. Another auditor covers them.
- Source-tied text was read but not audited in depth, as section 7 sets out.
