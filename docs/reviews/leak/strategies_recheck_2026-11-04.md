# Leak re-audit: candle strategy documents

Date: 2026-11-04. Auditor: `leak-auditor`. Re-audit of `docs/reviews/leak/strategies_2026-11-04.md`, findings L-01 to L-37.

Read: `docs/01_strategies/CHANGES_2026-11-04.md`, `00_INDEX.md` in full, the diff between commits `47a81f4` and `05cedfd` for all of
`docs/01_strategies`, and the charter's current text. I did not take the change table's word for any row. All prices here are invented or synthetic.
`GATE_SPEC.md` is out of scope, and is mentioned only where this folder depends on it.

## 1. Verdict

**Overall: `PASS WITH CONDITIONS`.** All three `HIGH` findings are fixed, and the probes confirm it. Of the 37 findings, 33 are fixed, 4 are partly
fixed, and none is unfixed. The fixes added no `HIGH` finding. They raise 5 new `MEDIUM` and 10 new `LOW` findings, all text edits or decisions that can be
tied to a point in time. Section 7 lists every condition and when it falls due. Two conditions must be met before `decide` and `settle` are coded.

| Document | Verdict | Conditions of its own |
|---|---|---|
| `00_INDEX.md` | `PASS WITH CONDITIONS` | C-1 to C-10 in section 7 |
| `S01` | `PASS` | None |
| `S02` | `PASS` | None |
| `S03` | `PASS WITH CONDITIONS` | C-6 (placebo targets) and C-9 (`Sigma_H` `broken_at`) |
| `S04` | `PASS` | None |
| `S05` | `PASS` | None |
| `S06` | `PASS` | None |
| `S07` | `PASS WITH CONDITIONS` | C-6 (placebo anchor count) and C-10 (trade source values) |
| `S08` | `PASS WITH CONDITIONS` | C-10 (trade source values) |
| `S09` | `PASS WITH CONDITIONS` | C-6 (placebo shift) |
| `S10` | `PASS` | None |

`PASS` means the document's own text has no open condition. The index applies throughout every strategy, so each one still inherits the index's conditions
when they fall due. No strategy may run on market data before the "first run" conditions are met.

**Severity** is used as in the first audit. `HIGH`: a faithful reading makes a decision or fill depend on data not available at that time. `MEDIUM`: one
plausible reading leaks, or a selection, fill or accounting rule favours the strategy. `LOW`: no future data enters on any reading I found, or the effect
is small, but the rule is ambiguous, not reproducible, or leaves a wrong audit trail.

## 2. Original findings

| ID | Status | Evidence, and what remains |
|---|---|---|
| L-01 | **Fixed** | C6 now sends a collar fixed at the decision. Size, `R_dec` and the limit use only `P_D`. Perturbing everything after `t_k` changed 0 of 177,167 decisions in `IDEAL`. Perturbing everything after `t_cut` changed 0 of 60 `decide` outputs under `CYCLE`, on data with first-print jumps. Favourable gaps cancelled: 0. The old guard would have cancelled 256 of them in the same data. `ENTRY_COLLAR` and `ENTRY_THROUGH_STOP` both fire in the `CYCLE` prototype. The C7 exemption is gone |
| L-02 | **Fixed** | C18 purges on `t_k + H_max`, with values matching each document's absolute limit, and charter item 11 agrees. Residual: N-08 |
| L-03 | **Fixed** | C4 is event-sourced, with an as-of read. As-of read against forward replay: 0 mismatches at 19,700 closes, 646 entries replaced. Truncation: 0 mismatches in 300 cuts. S06-like rule: the trade list is identical to forward replay (2,724 trades, 6 seeds). S03 section 12 no longer says "joined by `knowable_time`" |
| L-04 | **Fixed** | The header is limited to descriptive figures. C12 forbids a whole-history value. The open choice is ruled on in section 5 |
| L-05 | **Fixed** | `effective_from` is the first 1m bar with `open_time >= t_dec + latency`, and the walk reads a stored history. Deterministic cases: a dip and a spike before `effective_from` no longer stop the trade or fill the target, while the old rule did both. With a tight trailing rule, 329 of 1,174 common trades changed. Mean `Result_B` went from -0.0320 to -0.0353, within noise (s.e. 0.016), so this shows the rule matters, not a measured gain |
| L-06 | **Fixed** | Step 3 reads state as of `t_b`, and charter rule 7's text is honoured. In the prototype, the old reading cancelled 7 due time stops by later `T1` fills in 785 trades, and the new reading fires them. `knowable_time` for a fill-dependent event is now the fill's time |
| L-07 | **Fixed** | `decide` and `settle` are separate, and `settle` receives decisions it cannot change. A read guard on `decide` raised no read past `t_cut` in any run. One cut-off. Note: see section 8 on held state |
| L-08 | **Fixed** | `t_cut` set first, `P_dec` set in step 1 before the clamp, `t_dec` used only for fills and `effective_from`, `D_run` in backtests. The clock is judged in section 3. Residuals: N-02 and N-06 |
| L-09 | **Fixed** | The pending exit is the first line of the C7 loop, and S03 7.12 bar 28 says so. Time stops and `V0S` are covered |
| L-10 | **Fixed** | `IDEAL` is labelled zero latency and zero allowance, and `IDEAL-1M` is required everywhere. One fill model per mode. "If finer data exists" is gone. S07 and S08 section 4 have the allowance |
| L-11 | **Fixed** | C7: 1m bars are always used when both levels are inside a bar. Where they are missing, the stop is first and the bar is counted |
| L-12 | **Partly fixed** | The leak is fixed: draws are made at the knowable time, in `ATR` units, from earlier blocks, with the whole level set replaced, at least 100 draws and no redraws. Not defined yet: S03 placebo targets, the S09 shift, the S07 anchor count. See N-04 |
| L-13 | **Fixed** | C18 logs the data behind each drop or retire decision, limits configuration picks to training folds, and keeps retired streams to their retirement date. S01, S04, S05 and S06 now point to it |
| L-14 | **Fixed** | C14 has `CF_CYCLE` and `CF_IDEAL`, and a counterfactual result is a later event at maturity. Mode is on every event. Note: item 7's `IDEAL` minus `CYCLE` needs naming as the exception to "refuses to combine modes" |
| L-15 | **Fixed** | C18 and S08: selection is within one mode, and 30m cannot be selected. Extension judged in section 3 |
| L-16 | **Partly fixed** | Funding is in what a run sees and in step 2, and the boundary rule is stated. Remaining: the step 5 walk and a rate that never arrives. See N-09 |
| L-17 | **Fixed** | C7 and step 5 charge `slip` on close-based and time exits. C10's cost term holds fees and funding only. C16 states what examples show |
| L-18 | **Fixed** | The waiver covers entries only. Targets are passive fills, with two declared G5 stress cases |
| L-19 | **Partly fixed** | `IDEAL` is fixed, reported both ways. The `CYCLE` close rule is acceptable. Remaining: a hole that never fills. See N-03 |
| L-20 | **Fixed** | `R_dec` and `Result_B` are defined and used for gates, placebo comparisons and mode comparisons. All ten examples recompute. Residual: N-10 |
| L-21 | **Fixed** | C12 declares the estimation calendar before any run. S09 states what happens across a refit. The wider fold plan is N-05 |
| L-22 | **Fixed** | The older zone is valid to `superseded_at`, and both stay in the register. As-of read against truncated run: 0 mismatches in 10 cuts, though with only 4 displacements in 163 zones, so power is limited |
| L-23 | **Fixed** | C12 lists estimated values, selected thresholds and declared constants. The S09 heading is corrected |
| L-24 | **Fixed** | Steps 2 and 5 walk every 1m bar before the fill bar. Deterministic case: a touch stands and the pending exit is superseded. One such case arose in 853 entered trades on data with jumps |
| L-25 | **Fixed** | C2 states the rule, and S01, S02, S06 and S08 follow it |
| L-26 | **Fixed** | S02 7.2 and the new row at bar 8 agree with each other and with C2. Departure judged in section 3 |
| L-27 | **Fixed** | S01 7.3 now matches its table |
| L-28 | **Fixed** | S10 7.3 states the exception to C7 |
| L-29 | **Fixed** | Default `Q_min` is 60, a grid value. No example is affected |
| L-30 | **Partly fixed** | Minute, latency, `A`, `D_run` and fill wait are frozen, and selection uses training folds. Remaining: seed count and list (N-07), and trade source values kept outside this folder (N-15) |
| L-31 | **Fixed** | S01 and S06 list every check value for their control runs |
| L-32 | **Fixed** | C4 gives an order that uses only bar `i` |
| L-33 | **Fixed** | C4 uses the list's own timeframe. S04's base value is renamed everywhere it belongs, and `ATR_b` stays the current bar |
| L-34 | **Fixed** | Warm-up, re-seed and minimum counts are stated, and filling is forbidden. New issue from the fix: N-12 |
| L-35 | **Fixed** | S03 section 14 uses values at `t_(i+Rt)` |
| L-36 | **Fixed** | One definition of `touches_before` and `age`, and the example agrees |
| L-37 | **Fixed** | `A0` is frozen by id. Condition f fails until 6 bars after `t_c` |

## 3. Departures and extensions

| Item | Ruling | Reason |
|---|---|---|
| **L-08 clock.** `t_poll[source]` is the time the fetch began, `t_cut = floor_1m(min(t_poll) - A)` | **Accepted, with conditions** | It is stricter than my proposal and causal when `A` is right: any bar at or before `t_cut` closed at least `A` before the fetch began, and anything later in the fetch is discarded. 0 violations of `t_cut + A <= t_poll` in 2,000 random starts. A stale feed reaches the run undetected, though, because the gap check finds missing bars and not partial ones. So the clock needs a completeness check (N-02). It also needs a named clock, with skew inside `A` (N-02), and one `t_cut` per run (N-06). `A` must be measured (C-4) |
| **L-19.** `GAP_CLOSE` fills after that run's `t_dec + latency` | **Accepted** | The author is right and my wording was wrong. A fill at the first available open could come before its own decision, against item 7. The worst-case reading is still missing for a hole that never fills (N-03) |
| **L-26.** Ladder closes must come from bars opening at or after the rung's knowable time | **Accepted** | It follows from C2, is stricter than I asked, and cannot add information. Stops and the result are unchanged, and bar 8 recomputes (3,505.33, below the stop) |
| **L-06.** `SKIPPED_OPEN` judged on state committed at `t_dec` | **Accepted** | Committed state comes from a walk to `t_cut`, so nothing past `t_cut` is read. The pending exit counts as open, which is the conservative side |
| **L-15 extension.** S01 and S06 select under `IDEAL-1M` | **Accepted** | Selection stays within one mode, and `IDEAL-1M` is the feasible one: `P_D` is knowable before its fill bar. Better than `IDEAL` for this purpose |
| **L-27 extension.** Same wording in S02 | **Accepted** | Same gap, causal, and it does not affect S02's example, where `T1` is unfilled at the roll |
| **L-20 extension.** Selection on `Result_B` | **Accepted** | The denominator is fixed at the decision, so selection no longer depends on a post-decision scale. C10 says the charter requires this, but rule 4 names gates, placebo comparisons and variant comparisons, not selection. The choice is sound and the attribution needs correcting (N-10) |

## 4. New findings

| ID | Location | Leak class | Scenario with times | Severity | Fix |
|---|---|---|---|---|---|
| N-01 | `00_INDEX` C17 "Flow under `CYCLE`", timing consequences, order of work, C8 | Flow placed where later data is readable. Higher-timeframe value before its close | S10 at 4h, run at 13:09:05, `t_cut` 13:08, last 4h close 12:00. The order of work has no flow step, and the text says flow exits "follow step 5" and tightening "follows step 6". Those steps are in `settle`, which may read to `t_dec + latency + fill wait`. A check placed there at 13:10 reads trades after `t_cut`. Also, C8's clamp needs `C_b` and `ATR_b`, and no bar closed at this run. Computing them from the running 4h bar breaks timing item 1 | `MEDIUM` | Add a flow step to `decide`, after step 3. It uses data at or before `t_cut`, with position state as of `t_cut`, and is committed at step 4. Steps 5 and 6 only execute it. Between closes, C8 uses `C_b` and `ATR_b` of the last closed `T_d` bar, plus the `P_dec` clamp. No partial `T_d` bar is ever read. See the ruling in section 5 |
| N-02 | `00_INDEX` C17 run clock, gap rule | Backtest sees more than the run | A run starts 14:21:15, so `t_cut` is 14:21:00. That minute the source lags 20 s, and the fetch returns trades only to 14:20:52. The 14:21 bar exists, so the gap check passes, but its high, low and close are partial. Live, `P_dec`, Path and any `T_d` close are built from a partial bar, while the backtest reads the full bar from the archive. A runner clock 15 s fast does the same with no lag at all | `MEDIUM` | For each source the run must hold evidence of completeness through `t_cut`: a record stamped after `t_cut`, or a server time at or after `t_cut + A`. Otherwise `t_cut` moves back one minute, or the run logs `DATA_GAP`. Name the clock for `t_poll`, and state that `A` includes clock skew. Log `t_poll` and the skew on each run |
| N-03 | `00_INDEX` C17 gaps, `C-GAP` row, against C2 | Gap hides a stop | Long, stop 66,900. 1m bars for `(13:00, 14:30]` never arrive. The second run closes at 67,000, logged `GAP_CLOSE`. No later bar exists to show a touch, so the record shows no stop, though a resting stop may have filled at 66,900 or worse. `IDEAL` reports this both ways, with the worse as headline, and `CYCLE` has no equivalent. `C-GAP` also does not say whether the hidden bars arrive later, so a stress run can hide the stop every time | `MEDIUM` | Add a deadline. A hole still unfilled at it is marked `GAP_UNRESOLVED` and reported both ways, with the worse as headline, as in C2, by an appended event. `C-GAP` states when hidden bars arrive, and reports a never-arrive case |
| N-04 | `00_INDEX` C15. S03, S07, S09 section 10 | Placebo not fully defined, chosen after results | S03: at a random bar no swing was just broken, so `SH` and `Leg` in 7.3 do not exist and `T1` and `T2` cannot be computed. A developer would choose them after seeing the result. S09: "a random whole number of hours" allows 0, which is the real rule, and if drawn per draw there are only 24 distinct paths, so 100 draws repeat. S07: the number of random anchors per block is not stated, and it changes trade count and overlap | `MEDIUM` | S03: placebo `T1 = C_k + 1.5 * (C_k - S0)`, its own fallback, and `T2 = C_k + 3.0 * (C_k - S0)`, recomputed as usual if a real `BOS_UP` then occurs. S09: draw the shift per day from 1 to 23, independently. S07: as many anchors per side as the block's real major swings |
| N-05 | `00_INDEX` C18, C12, C15, open question 4. Charter item 11 | Fold plan may be chosen on results | C18's "test block", the freeze of selected thresholds and C15's "earlier blocks" all need a fold plan. The index says it "should be fixed before the first `V0` run", while the only plan is marked to be confirmed once `V0` results exist. If quarterly tests are moved to half-yearly after seeing `V0`, the selected thresholds and every test result depend on that choice. Item 11 also says test blocks are "never reused for selection", which an expanding training window does reuse | `MEDIUM` | Change "should" to "must", and freeze the plan before the first `V0` run: spans, block length, the locked final block. `project-manager` rules on whether earlier test blocks may enter later training, and item 11 is worded to match. A later change is a counted trial |
| N-06 | `00_INDEX` C17 run clock | Variants not on one clock | The text lets each strategy use only its own sources. Live, trades are fetched at 14:21:05 and candles at 14:21:20. `V0` then gets `t_cut` 14:21:00 and `VE` 14:20:00, so paired variants see different `P_dec` and Path. The backtest, with offset 0 for candles, always gives them the same value. Not a future read, but the live comparison differs from the simulated one | `LOW` | One `t_cut` per run and symbol, the minimum over all sources fetched for that symbol, shared by all strategies and variants. A retried fetch uses the start of the attempt that delivered the data. Say "trades with time at or before `t_cut`", since trades have no close time |
| N-07 | `00_INDEX` C17 scenarios, C18 | Optional stopping on seeds | "At least 5 seeds" lets a run be repeated with more seeds until a comparison looks better, without selecting any one seed. C15 requires its count "declared in advance", and this does not | `LOW` | Declare the seed count and list in configuration before the first run. A change is a counted trial |
| N-08 | `00_INDEX` C18 | Label reaches the test block despite the purge | The allowance is `A_max` plus 2 h for one dropped run. Two dropped runs in a row, 0.25 percent of hours under `C-LATE`, put an exit about 176 minutes after its due close against the 120 allowed. It was not observed in 1,516 prototype trades, so it is rare | `LOW` | End each training simulation's data at the test block's start. A trade still open then is removed from selection and counted. The engine then cannot read test data at all |
| N-09 | `00_INDEX` C17 step 5, step 2, C10 | Funding omitted | `C-BAD` or a late live run: `t_cut` 23:58, `t_dec` 23:59:30, exit fill bar opens 00:00. The boundary rule says the 00:00 funding is owed. Step 2 charged only to `t_cut`, step 5 does not mention funding, and the next run does not walk a closed position, so it is never charged. Separately, a rate that never arrives stays `DATA_GAP` with no later step, while a backtest always has it | `LOW` | Step 5's walk charges funding as step 2 does. A missing rate stays open as a reported liability, and is settled by an appended event when it arrives |
| N-10 | `00_INDEX` C6, C10 | Statistic drops the worst trades | No `Result_R` is reported for `ENTRY_THROUGH_STOP`, and reports may show `Result_R` beside `Result_B`. A mean `Result_R` then silently excludes the trades that gapped through the stop | `LOW` | Every `R` statistic prints the count excluded, and `Result_B` always includes them. C10: say that rule 4 names gates, placebo and variant comparisons, and that selection is added here |
| N-11 | S03 7.3 | State event with no rule | "Nearest unbroken swing high in `Sigma_H`", but the state machine runs only on `Sigma`. Whether a 4h swing is broken by a 1h close, a 4h close or a wick is unstated, and it changes `T1`. Each reading is causal when read as of `t_k`, but the choice is free and uncounted | `LOW` | `broken_at` for `Sigma_H` is the close of that list's timeframe beyond the price by `0.10 * ATR` on that timeframe |
| N-12 | `00_INDEX` C3 | Exit rule fails open after a gap | S03 at 1h. The 13:00 bar is missing, so `ATR` is undefined for the next 14 complete bars, 56 hours at 4h. "Any condition using an undefined value fails", so `C_k < SL.price - b_k` cannot fire and the `CHoCH` exit is off, and `broken_at` is not logged either. The same holds for the S01, S02 and S05 invalidation lines. The rule suits setups but not exits. Under `C-GAP` this recurs every 30 days. Direction not fixed: it can also avoid a whipsaw | `LOW` | For an open position's exit rules only, use the last defined `ATR`, frozen and logged, until the re-seed. Setups still fail. This fills no bar |
| N-13 | `00_INDEX` C2 against C17. S07, S08 section 14 | Live and backtest bar source unclear | C2: in every mode 1m bars come from trades. C17: a candle-only strategy uses "its one candle source", and S07 treats 1m bars as complete when trades are missing. If live reads venue bars and the backtest reads trade-built bars, `08_DATA_CENTER.md` section 4 shows they differ at minute boundaries, so G8's exact match cannot hold. A minute with no trades also has no bar, so it would log `DATA_GAP`, or tempt a forward fill | `LOW` | State the live source for each tier. Define a minute with no trades, when the source shows it is complete, as a bar with zero volume that can touch nothing, kept apart from a gap |
| N-14 | `00_INDEX` C17 constants, `C-MEASURED` row | Backtest fills earlier than live | `D_run` is 60 s for tier `T0`. A real run lasting 150 s fills a minute or two later than simulated, in the burst minutes C6 warns about. `C-MEASURED` replaces delays and drops, but not `D_run` or fetch offsets | `LOW` | `C-MEASURED` also replaces `D_run` and fetch offsets with values from real logs |
| N-15 | `00_INDEX` C17 fetch offset, backtest item 3. S07, S08 | Constants held in a document known not to conform | Trade source offset, page size, rate limit and retention are "in `GATE_SPEC.md`". S07 and S08 need them for `V0` under `CYCLE`, even with no gate, and item 3 needs them to model a fetch failure. Without them a backtest assumes every fetch succeeds | `LOW` | Declare them for `V0` in this folder, or hold the first S07 and S08 `CYCLE` run until `GATE_SPEC.md` conforms and is audited |

## 5. Rulings

**Flow at runs between 4h closes: is the new C17 wording correct?** **Yes on substance, but incomplete.** Model updates only at `T_d` closes is the right rule, as it keeps a late
run's values identical to an on-time run's. Flow acting at any run is also sound: flow reads closed trades, charter rule 3 limits it to reducing risk, and acting between closes
is what an hourly job can do. What the wording leaves open is where the flow check runs and which bar values it reads. Both must be fixed, as in N-01, before `decide` and `settle` are
coded. Then a flow stop enters the stored history, and the next `T_d` close passes through C8 from it, so it can never be undone. Flow does not change `n` or any time stop. Comparing
`VX` with `V0` needs the same run times and seeds.

**`RT` and stop slippage in C12: must the choice be settled before the document can pass?** **No. It may wait until the source is chosen, and must be settled before the first run.** The rule that
prevents the leak is already in the text: both options are causal, and a value measured over a whole history and applied to it is forbidden. The values depend on a venue not yet chosen under
`D-01` and `D-17`, and fixing one now would only force a counted change later. The wait has these limits:

- "First run" means the first simulation of any strategy, control or placebo on any market data from any source. Synthetic engineering tests do not count.
- The choice and its value or estimator are logged in the trial registry first, and a run refuses to start without them.
- The choice is made without sight of any strategy result.
- A declared constant states its basis. A value measured from market data may not apply to the span it was measured on. That is the back door to a whole-history value.
- If estimated, the first block needs a declared starting value or a burn-in with no trades, as no earlier data exists for it.

## 6. New values: could their choice depend on outcomes?

**On the text, no.** I found nothing that ties any value below to a result. The repository has no trial registry, no strategy engine, no strategy results and no market data files that I could find. Its one report on prices is a buy and hold benchmark, which states that it is not a strategy result. The only market data
the documents describe is one day of data-quality checks (charter section 4, `08_DATA_CENTER.md` section 4), and no strategy constant refers to them. That is consistent with the claim that no market
data has been used in strategy work, but absence from the text is not proof. Condition C-5 makes it checkable.

| Value | Affects the trade list | Basis in the text | Ruling |
|---|---|---|---|
| Nominal minute 7 | Yes, under `CYCLE` | Named in the first draft, "avoids the top of the hour" | Accepted, frozen |
| `latency` 500 ms | Yes, at a bar boundary | Assumption | Accepted, frozen |
| `A` 10 s | Yes, through `t_cut` | `UNVERIFIED` assumption | Accepted only until measured (C-4). Set it from feed logs and never from results |
| `D_run` 60 s and 180 s | Yes, through fills | Assumption | Accepted. See N-14 |
| Fetch offset 0 s, fill wait 2 min | Offset yes, wait no | Assumption | Accepted. See N-15 for other sources |
| Quarterly refits | S09 only | Author's choice, declared before any result | Accepted, frozen |
| 2 bp trade-through | No, stress report only | Assumption | Accepted |
| `C-GAP`, 90 minutes per 30 days | No, stress report only | Assumption. Real outages may cluster in volatile times, so random holes may understate them | Accepted as a stress, until real logs replace it |
| `Q_min` default 60 | Default only, grid decides | Grid value | Accepted |
| S01 and S06 control check values | Control only | Declared before any result | Accepted |

## 7. Conditions

| ID | Condition | Findings | When it must be met | Owner |
|---|---|---|---|---|
| C-1 | Add the flow step to `decide`, and fix the bar values used between closes | N-01 | Before `decide` and `settle` are coded | `strategy-architect` |
| C-2 | Add the completeness check, name the `t_poll` clock, use one `t_cut` per run and symbol | N-02, N-06 | Before `decide` and `settle` are coded | `strategy-architect` |
| C-3 | Settle `RT` and stop slippage under the limits in section 5 | L-04 | Before the first run. May wait for the source | `project-manager` |
| C-4 | Measure `A` from a runner on the chosen source, with skew, at a high percentile, from feed logs only | L-08, N-02 | Before the first `CYCLE` run | `data-steward` |
| C-5 | Record the commit that holds the frozen documents and constants, before any market data is used for a strategy | Section 6 | Before the first run | `project-manager` |
| C-6 | Define S03 placebo targets, the S09 shift and the S07 anchor count | N-04 | Before the first placebo run | `strategy-architect` |
| C-7 | Freeze the fold plan, and rule on item 11 and expanding training | N-05 | Before the first `V0` run | `project-manager` |
| C-8 | Add the hole deadline and the `C-GAP` arrival rule | N-03 | Before the first `CYCLE` run | `strategy-architect` |
| C-9 | Make the `LOW` text fixes N-07 to N-14 | N-07 to N-14 | In the same edit as C-1 and C-2, and before the affected code. N-07 no later than the first run | `strategy-architect` |
| C-10 | Declare trade source values for `V0` | N-15 | Before the first S07 or S08 `CYCLE` run | `strategy-architect`, or `feature-integrator` if kept in `GATE_SPEC.md` |

Code review remains required as C17 and C4 state: truncation invariance on every register, future perturbation, the shift test, and the timestamp audit. C-1, C-2 and the text in C-6, C-8 and C-9 need a re-audit of the
changed lines only.

## 8. Probes and what they show

All are on synthetic bars, and test timing logic only. They say nothing about any market or any strategy's merit. The `CYCLE` prototype uses a generic rule set, and the scripts are throwaway and not in the repository.

| Test | Result |
|---|---|
| L-01, `IDEAL`: perturb all data after `t_k`, 60 cuts | 0 of 177,167 decisions changed. Favourable gaps cancelled: 0 |
| L-01, `CYCLE`: replace every bar after `t_cut`, re-simulate all runs up to it | 0 of 80 runs changed on continuous data, 0 of 60 with jumps. Under `C-BAD`, 0 of 80 |
| Collar outcomes, 10 seeds with jumps | 853 entered, 4 `ENTRY_COLLAR`, 1 `ENTRY_THROUGH_STOP`. Few fired, so the deterministic cases carry most of this check: all four outcomes behave as C6 states |
| L-03, as-of read | 0 mismatches at 19,700 closes, 0 in 300 truncation cuts, identical S06-like trade list |
| L-22, as-of register | 0 mismatches in 10 cuts, 4 displacements in 163 zones |
| L-05, tight trailing rule | 329 of 1,174 common trades differ, mean `Result_B` within noise |
| L-05, generic rule set | Same trade count and mean under both rules, so that run had no power |
| L-06 | Old reading cancelled 7 due time stops in 785 trades |
| L-24 | Deterministic case passes. 1 superseded exit with jumps, 0 of 293 without |
| Run clock | 0 violations in 2,000 starts. Worked timeline recomputes: `t_cut` 14:20:00, age 80, `lateness` 81, fill bar 14:23 |
| Added example numbers | All ten collars, `R_dec` and `Result_B` recompute. Stops and results in `R` are unchanged |

**Held state.** In a backtest, one run's `settle` can write a fill dated after the next run's `t_cut`, which `decide` would then read from state. It needs two runs about 2 minutes apart, so only `C-BAD` or a late live run allows it. I counted 0 such
pairs in 1,827 `C-BAD` runs and 0 in 2,049 `C-LATE` runs, and at 1h or 4h the second run has no new `T_d` close to act on. Not a finding, but the required truncation test must hold state as of `t_cut`, and treat such a fill as still pending.

## 9. Notes, not findings

- **Placebo side share.** C15 draws the side at the block's real long and short share, which is same-block information. That was my own proposed wording, and it holds. It gives the placebo the block's direction, which can only make it harder to beat, and so favours no strategy. Reports should say so.
- **C14 against item 7.** "Refuses to combine modes in one statistic" needs `IDEAL` minus `CYCLE` named as the one exception.
- **S04 stack zones.** Whether the overlap rule applies between stack zones and entry zones is not stated. It is causal either way, but it can change trades, so it should be stated.
- **S10 and C13 targets set at the fill** act on the fill's own 1m bar, a moment before item 12's `latency`. A target 2 `R` away makes this negligible, and stop-first applies in that bar.
- **Venue wording.** Binance schedules are now examples, and bar labels are left to G1. Still undecided under `D-01` and `D-17`.
- **Index open question 5** is covered by C-5, and question 4 by C-7.

## 10. What I could not check

- Any behaviour on real data, so no effect size on real prices is known.
- That no constant was set with sight of outcomes. Section 6 is limited to the text.
- The size of `A`, feed lag, clock skew and real run durations, as no runner test exists.
- `C-GAP`, `GAP_CLOSE` and corrections were reasoned through and not simulated. Flow was not simulated.
- The prototype is not the production engine, and its walk, as-of state and collar only test whether the text can be implemented causally. S01 to S10 rule sets were not built as full `CYCLE` engines.
- Whether exchange-side stops and targets would behave as item 13 assumes, on a venue not yet chosen.
- `GATE_SPEC.md`, `src/`, `tests/` and layer 5 are out of scope.
