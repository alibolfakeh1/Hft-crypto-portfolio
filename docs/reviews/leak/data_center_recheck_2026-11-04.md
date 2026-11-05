# Leak recheck: data center code, fold plan and two-stage plan

Date: 2026-11-05, begun 2026-11-04. Auditor: `leak-auditor`. Code at `dafe3f2`, documents at `38d5907`, fold plan and `D-27` to `D-31` at `1e634fc`, all on `pipeline/first-data-run`. Recheck of
[the audit](data_center_2026-11-04.md), against [the developer's answer](../code/data_center_fixes_2026-11-04.md), every row of which I treated as a claim.

All data here is generated, and all prices are invented. No source was contacted and nothing was downloaded. Adapters ran on generated files only, with sources switched on in memory. Probes
and mutants ran on a clone outside the repository. All sources stay disabled in the code audited. Under `D-29` the first run is `V0` on official 1-minute candles and funding, tier `T0`, with bars from trades later. Section 5, ruling 7, covers those candles, and section 9 states the other source-dependent rulings by property.

## 1. Verdict

**Overall, for the data center code at `dafe3f2`: `FAIL`.** It is a much narrower failure than the first one.

Most of the first audit's findings are fixed, and I confirmed that with my own probes rather than the file's word. Two things stop a `PASS WITH CONDITIONS`. The fixes introduced four new leaks, each a direct failure of
truncation or future perturbation on generated data. And one of them comes from **my own wording**: ruling 2 item 4 of the audit told the developer to leave out rows "with `n_fills > 1`", and that test itself reads the future. The correction is in section 3.

| Path | Verdict | Why |
|---|---|---|
| Poll, `live_bars`, `live_trades`, `bars_for_run`, `trades_for_run`, `visible_bars` | `PASS WITH CONDITIONS` | 0 differences in 4,024 truncation and 4,024 perturbation comparisons on the grid path, 0 in 40 through real poll runs, and 0 in 320 through `derive_day`. Holes are now gaps |
| Archive bars on a source with no official candles | `PASS WITH CONDITIONS` | Same, and holes are flagged |
| Archive bars on a source with official candles | `FAIL` | DR-04: a day's last bar can be flagged by a fault up to a day later, with its knowable time unmoved |
| `IDEAL` read path: `settled_*`, `ideal_view`, `ideal_bars` | `FAIL` | DR-01, DR-02, DR-03. Dormant: every source's allowance is a placeholder, so no source can reach it today |
| Report calculations | `PASS WITH CONDITIONS` | No later bar is read. Its statistics window is selected by a data event (DR-08) |
| Fold plan, `1e634fc` | `PASS WITH CONDITIONS` | Section 13. The dates, the failing-quarter rule and the read rule hold as rules. One scheduled report could still read and publish the whole locked block (FP-01) |
| Two-stage plan, `D-31` | `PASS WITH CONDITIONS` | Section 14. Reading only the first span is right, and it is required and not merely convenient |

**`D-27` does not stand as "not a trial".** By the re-audit's words it was the first run, ahead of C-3 and C-5, and no rule text is on file to show it differs from the candidates. It is replaced by a new entry and counted (section 13.2). **The locked block stays in use with its dates, and it is no longer untouched.** Its 10 days come out at a cost of 4 to 30 percent of the block, by each strategy's `H_max`. What cannot be taken out is that whoever saw the demonstration knows how the block moved from month to month, so a locked read now counts only for what can be shown to predate the demonstration or to rest on a basis outside it (section 13.3). The first span and the test blocks hold no demonstration day.

**Injected leaks.** 105 of 115 ran. 1 of the audit's 30 passes everything, against 3, and 12 of the new ones pass what ran, 8 of them direct leaks. Section 8 says what did not run.

**Later rulings.** Section 15 gives the exact form of ruling 7 condition 2. Section 16 rules on the `D-18` listing, and the plan's verdict does not change.

**What this blocks.** Nothing here holds back building the engine and `V0` on generated data. Section 10, next, lists in order of importance what must be fixed before any of that sees market data. I did not review the new modules.

**Severity** is used as in the earlier audits. `HIGH`: a faithful reading makes a decision or fill depend on data not available at that time. The scale does not depend on size. `MEDIUM`: one plausible reading leaks, or a selection, fill or accounting rule favours the strategy. `LOW`: no future data enters, but the rule is ambiguous, not reproducible or leaves a wrong audit trail.

## 10. What must be fixed before any strategy sees market data

This section is out of numerical order on purpose, because two developers are waiting on it. Its number stays, because the roadmap and the fold plan cite it. Item numbers stay too, so new items carry a letter. In order of importance. None of this stops the engine and `V0` being built on generated data.

**First: before the source is enabled in any workflow, or unopened dates reach the disk.**

| # | Item | Who | Why it comes here |
|---|---|---|---|
| 0 | **FP-01: nothing can read an unopened date.** Unopened dates sit in their own root, which `MarketReader` and `report` cannot open, and no bars are built there. The coverage check runs there, and a schema test limits what it writes to the plan's list. The scheduled report stays off until this is in | `developer`, `data-steward` | It is the only item here that cannot be undone. One scheduled run would read and publish the whole locked block |

**Stage 1: before the first run on official candles (`D-29`, `D-31`).**

| # | Item | Who | Why it comes here |
|---|---|---|---|
| 1 | **The candle-to-bar converter and its dataset, under ruling 7,** with its tests | `developer` | No such code exists. `parse_klines` output is not a bar, and every timing fact of the first run rests on this |
| 2 | **Condition 2 of ruling 7, in the form of section 15, and the charter and C2 sentences.** Sample days from the first span, declared before they are read, and none that `D-18` touched | `data-steward`, `project-manager`, `strategy-architect` | Without them the first run breaks the contract's wording, and its volume rests on an inference. If condition 2 is not shown, `IDEAL` is not reported and nothing else stops |
| 3 | **A reader for these bars,** with `IDEAL` gated on condition 2 and `IDEAL-1M` served as of `t + max(latency, A)` | `developer` | `ideal_allowed` tests the wrong thing for these bars. S01 and S06 select under `IDEAL-1M`, which has no as-of read today |
| 3a | **The date guard, in the reader, the report, the benchmark and the portfolio view.** Bars by close time, trades by stamp, funding by settlement time. The value comes from a dated log entry, and a test compares the two. The last bar of the span stays readable, so do not guard on `knowable_time` | `developer` | The plan rests on it, and at `dafe3f2` `report.py` reads parquet directly |
| 4 | **Close the read-path holes in section 8.** A test with `t_cut` clearly earlier than `t_dec` on `trades`, `live_trades`, `live_dataset` and `trades_for_run`. One `IDEAL` test per timeframe. All four volume columns in the `IDEAL` view. A row between half the allowance and the allowance | `developer` | A run reading past its cut, or a view returning plain flow, passes the whole suite today |
| 5 | **Declared values, frozen before the first `V0` run:** `RT`, stop slippage, `candle_allowance`, the research span common to all symbols, C-5 and C-7. Also the **estimators** for the stage 2 values, though not yet their values (section 14, condition 5) | `project-manager` | Set after seeing results, they are selection |
| 5a | **The new entry for `D-27`, the file-by-file anchor for C-5, and the `D-18` search** (sections 13.2 and 16, FP-03) | `project-manager`, `data-steward` | C-5 cannot be written without them. A report seen over a stretch of `D-18` dates makes the plan `BLOCKED` |
| 6 | **DR-08: a declared span for the benchmark,** ending at the last opened date | `developer` | One fault flipped a benchmark's sign in my probe, and `V0` is reported beside it |
| 6a | **FP-05: the portfolio figure's line rule, declared before the first run,** and FP-04's note on `D-28` | `project-manager`, `developer` | Six strategies cannot select at this stage, and the figure still needs a line for each |
| 7 | **The false "frozen" wording** | `developer` | It sits where the next reader will trust it |

**Stage 2: before bars from trades (`D-12`).**

| # | Item | Why it comes here |
|---|---|---|
| 8 | **DR-03: as-of reader,** with truncation invariance on every column | Trade-built bars rest on later rows for their proof, and the candle bars do not |
| 9 | **DR-01, DR-02: settled by stamp alone, and `fill_count` out of the view** | A decision at a close can read whether a fill came after it. Aggregate rows are exactly this shape |
| 10 | **DR-04: a flag cannot rest on a later fault** | The only one of the new leaks on the normal read path, and live as soon as trades and candles are compared |
| 11 | **DR-05: flag bad boundaries only** | One long aggregate removes up to a day of setups in a backtest |
| 12 | **DR-06: one constant, a detector that can fire, a false allowance revoked** | Items 8 to 11 rest on the allowance being true |
| 13 | **The allowance, `continuity`, `max_quiet_s` and the window declared with evidence and frozen under C12.** The reconciliation rule rechecked (`D-18`) | They decide which minutes are flagged |
| 14 | **DR-13, DR-10, DR-07** | Quiet days leave statistics, `pass` overstates, and an oversized allowance settles wrongly |

**Stage 3: live path, when it has a source.** DR-09, DR-11, DR-12, `emission` on higher bars, a reader for corrections, and a poll test where the fetch takes measurable time, so a bar's knowable time must be its last page's receipt (section 8), before the first `CYCLE` run compared with live.

**Text.** Section 6 lists the sentences still to change. They can land at any time, and the `lateness` one should land before the engine writes events.

**For the engine, as interface and not as review.** These follow from the rulings in this file.

- Read market data only through `MarketReader`, and hold no root.
- Under `CYCLE`, run the C17 evidence step before `bars()`. With it `bars()` never raised in my probe, and without it, it raises on a quiet tail.
- A `gap`, a proof or a `complete` counts from its own knowable time. Do not read `knowable_time` as a bar close, since a polled bar's is its receipt.
- **Read no day-level status.** `check_status`, exclusions and `warn` are final-state values, which C4 forbids as inputs. A strategy sees minute flags only.
- No newest-unbroken-run logic. A span is declared, and holes are treated under C2.
- `IDEAL` stays off until an allowance is measured. On generated data it may be switched on in memory, and those runs say so. S07 and S08 follow section 6.1.
- **A setup left out for a read day or an unopened date is never simulated (FP-06).** The strategy counts as flat across it, so no later setup's `SKIPPED_OPEN` rests on it. Log it with its reason. Dropping rows after simulating does not meet this.
- **"Left out" uses C18's word, `reaches` (FP-07).** A setup is out when `t_k + H_max` is at or after the first unopened instant or the start of a read day.
- **Flow is compared only with `V0` on the same bars (section 14, condition 4).** No `VE` against a candle-stage `V0`.

**Re-audit needed:** items 0 to 4 before the candle run, and items 8 to 12 before bars from trades, with my probes rerun.

## 2. Verdict per finding

| ID | Verdict | Evidence | What remains |
|---|---|---|---|
| DC-01 | `PASS WITH CONDITIONS` | All four cases rerun. A failed pass: 30 of 30 minutes flagged, 1h bar `complete=False`. Tail: emission stops at the newest trade, and the 37 minutes of a later jump are all flagged. Before the first row: 1,440 of 1,440 flagged on a day in the unreachable history, gap logged. Budget end: the resume bar is flagged | DR-11: a row with a later id and an earlier stamp never comes back from a `since` source. No reader for the corrections log |
| DC-02 | `PASS WITH CONDITIONS` | A file missing 13:10 to 14:40 and all after 18:00: 451 minutes flagged, 1d `complete=False`, day `warn`. Ids skipping with the candles sharing the hole: 90 of 90 flagged, gaps recorded. `trade_id` is null where there is no sequence | The G1 report of empty minutes is not built. DR-10 |
| DC-03 | `FAIL` | Knowability is fixed: `visible_bars` and `bars_for_run` at the close return nothing inside the allowance. The `IDEAL` columns are not | DR-01, DR-02, DR-06. See section 3 |
| DC-04 | `PASS WITH CONDITIONS` | `MarketReader` exists, `live_eligible` is required and false everywhere, and a book read is refused | `decide` holding no root is still to come. `ideal_bars` is DR-03. The scanner guards four package names, so a new package name escapes: list the modules allowed to read instead |
| DC-05 | `PASS` | `received_at_us` required, no optimistic default. A bar takes its newest row's knowable time. `rebuild_day_bars` has no `knowable_time`. `derive_day` refuses received rows. `poll` and `ingest` refuse `--now` | None |
| DC-06 | `PASS` | Poll then ingest under one root, same venue and symbol: the live part is identical, and the archive holds its own values | None |
| DC-07 | `PASS WITH CONDITIONS` | At 14:21:05: `t_cut` 14:20, evidence logged, `live_bars` and archive `bars_for_run` give the same 860 rows through 14:20. Fetch length no longer moves the cut. Cron and `nominal_minute` are 7 | The modelled fetch, `decide`, `settle` and `t_dec` do not exist. A modelled fetch must run the evidence step first: without it `bars()` raises on a quiet tail (29 of 152 runs at 0.84 a minute), and with it 0 of 100. The `lateness` text is not fixed (section 6) |
| DC-08 | `PASS WITH CONDITIONS` | The audit's scenario is gone: with a 300 or 400 ms aggregate before midnight, the 480 morning bars at 08:00 are identical to the clean build on every column, and each failing day flags one bar | DR-04, DR-05, DR-08 |
| DC-09 | `PASS WITH CONDITIONS` | `compare_live_with_archive` finds 30 of 1,440 bars different and warns. `cross_venue_check` refuses one venue | DR-09: with the shipped symbol names the check silently never runs |
| DC-10 | `PASS WITH CONDITIONS` | Hash logged, `emission = rebuild` after a known lost cache, `not_applicable` on rebuilt rows | DR-12. `emission` is absent on higher bars (section 7). R1.1 is what makes the hash usable |
| DC-11 | `PASS WITH CONDITIONS` | `tests/leak` is rewritten on the real paths, every minute and every timeframe. Of the audit's 30 leaks, 19 are now caught there, including all five that passed or were caught only by accident last time, and 1 nearly harmless one passes everything (section 8) | It has no truncation test of `ideal_bars`, and its fill test varies size and never fill count, which is how DR-01 and DR-03 passed. 8 direct leaks on newer read paths pass what ran: section 10, item 4 |
| DC-12 | `PASS` | Grid and `through_close_us` are required, so the audit's partial 5m bar and its row that exists because of a later trade cannot arise by leaving an argument out | None |
| DC-13 | `PASS WITH CONDITIONS` | The allowance reaches trades, candles and funding, and configuration says what it covers | All values are placeholders, `UNVERIFIED`, and health alerts on that |
| DC-14 | `PASS` | `reconciliation_history` keeps fail then pass. Changed files are recorded and alerted. Manifests carry hashes | None |
| DC-15 | `PASS WITH CONDITIONS` | Reconciliation and poll summaries are filtered by the stated time, and the benchmark is unaffected | `health.exclusions` still holds later rows at a stated past time, and only a fixed clock reaches this. `LOW` |

## 3. Ruling 2 of the audit: batched rows, item by item

| Item | Verdict | Note |
|---|---|---|
| Row-shape table | Stands, with one addition | Rows carrying one stamp over an interval are not knowable at the stamp. Addition below |
| 1. Charter and C2 sentence | **Met** in `38d5907` | Section 6 |
| 2. Required per-source keys, no default | **Met** | Unknown keys are errors. All values are placeholders. A key alone proves nothing |
| 3. In the data | **Met** | Trades, bars, candles and funding |
| 4. `IDEAL` columns | **Not met, and my wording was wrong** | Corrected below. DR-01, DR-02 |
| 5. `A >= allowance` asserted | **Met on the poll path only** | Section 7 |
| 6. A detector that fails closed | **Not met** | DR-06 |

**Correction to item 4.** I wrote "leaving out rows with `n_fills > 1`, or in a same-stamp group". A row's fill count includes fills after the close, so testing it reads the future. **The test must use the stamp alone: a row counts in a bar's settled columns only when it was stamped at least the allowance before that bar's close.** On a source with a measured allowance of zero, nothing is deferred. `fill_count` was in my list of affected fields and missing from item 4, and it has no settled form as built, so `IDEAL` does not read it.

**Correction to ruling 7.** I wrote that once a failure no longer removes a day, only the recheck of the window remains. That was too generous: the window still decides which minutes are flagged (DR-05) and which days reach the statistics (DR-08), so it stays a declared constant under C12.

**Correction to the DC-08 fix.** I wrote "flag from the first boundary the check cannot explain". The developer did that, and it flags far too much (DR-05). The walk's own per-boundary result is already causal, so flag those boundaries only.

## 4. New findings

| ID | Location | Leak class | Scenario with times | Severity | Fix |
|---|---|---|---|---|---|
| DR-01 | `bars/core.py` `_add_settled` | Value at `t` depends on a fill after `t` | Invented numbers. Allowance 250 ms. Order stamped 11:59:59.950, 1.5 units. If nothing more prints, the row has `n_fills` 1 and stays: `settled_buy_volume` 11.5 at 12:00:00.000. If 1.5 more prints at 12:00:00.046, `n_fills` is 2, the row is deferred, and it reads 10.0. A rule `buy_volume >= 11` read in `IDEAL` enters in one world and not in the other. Removing only fills after each close moved `IDEAL` volume at 4 of 150 closes on generated fills. It is never above what had printed, so it errs low, but it still tells the reader something about the future. The project's test varies 1.5 against 9.0, with `n_fills` 2 both ways, so it cannot see this. `shared` has the same flaw | `HIGH`. Dormant | `defer = (closes - ts_us) < allowance_us`, on every row. Replace `test_a_row_of_one_fill_with_its_own_stamp_is_not_deferred`. Add a fill-level test that removes later fills |
| DR-02 | `bars/core.py` `ideal_view` | Same | `fill_count` stays in the view. Across the four cases above it reads 2, 3, 3 and 4 at the same close. It moved at 9 of 150 closes. The text says `IDEAL` reads no `fill_count` | `HIGH`. Dormant | Drop it from the view |
| DR-03 | `data/reader.py` `ideal_bars` | Standing rests on a later row, not timed | Last trade 12:03:10, read at 12:05. Next id runs on at 12:10:30: `gap` false, proof `id_run`, `knowable_time` 12:10:30. Next id skips: `gap` true. Data cut at 12:05: `gap` true, proof `none`. So the read at 12:05 differs with later data, and `knowable_time` hands the reader **the time of the next trade**. Of 40 cuts at 0.84 trades a minute, 1m reads differ on 21 and 5m reads on 9 (`gap`, `complete`, `knowable_time`, `empty_proof`). No test covers it | `HIGH`. Dormant | Ruling 4 in section 5 |
| DR-04 | `bars/reconcile.py` `flow_reliable`, `flag_last_bar`. `data/derive.py` | A flag on a bar from an event after it | Volume carried across the D-1 to D midnight, and a 400 ms aggregate at 10:00 on D. D's path breaks at 10:00, so its whole `flow_reliable` is false, so D-1 cannot confirm its carry. D-1's last bar goes to `gap=True`, with `knowable_time` still 00:00:00.250, ten hours before the fault. With no fault it is `gap=False`. A 1h or 1d bar closing at that midnight loses its setup because of 10:00 the next day. A real disagreement at a midnight has the same fault on a smaller scale: the last bar rests on the next day's first candle | `HIGH`, small. One bar per fault, and only on a source with official candles | Split into `carry_in_reliable` and `carry_out_reliable`. A day's carry in is known at its first boundary, so a later break does not touch it. Move the knowable time of a flag on the last bar to the next day's first close plus the allowance |
| DR-05 | `data/derive.py` `flagged` | Selection, causal | One 400 ms aggregate at 10:00. One boundary unexplained, and the next heals. 841 minutes flagged, 15 of 24 1h bars incomplete. With a 500 ms window, none. Under C2 that removes 14 hours of setups after a burst, in a backtest only, because the poll has no such check. This is the window still picking the sample, in minutes and not days. No future data enters: each flag rests on what came before it | `MEDIUM` | Flag the boundaries the walk marks bad, and no others. A persistent break stays bad at every boundary, so nothing is lost |
| DR-06 | `bars/reconcile.py` `_walk`. `configs/pipeline.toml`. `config.py` `ideal_allowed` | Detector cannot fire | `largest` is measured only on boundaries that are not bad. With window and allowance both 250, a row running 400 ms gives `largest_window_needed_ms` 0.0, and a `fail` that never says the allowance is false. It fires only if someone sets the window above the allowance, which is how its test does it. Nothing revokes anything: a source declared `measured` keeps `ideal_allowed` after the message | `MEDIUM` | One source-level constant. Measure on every boundary. A false allowance is a recorded state that the reader honours |
| DR-07 | `config.py` `_non_negative` | Settled wrong past a minute | Any allowance is accepted, and deferral moves a row one bar. At 90 s, a row stamped 11:59:50 that runs to 12:01:15 settles whole by 12:01:00 | `LOW` | Refuse 60,000 ms or more |
| DR-08 | `reports/report.py` `_contiguous_tail` | Sample window selected by a data event | Section 5, question 1. One fault turns a benchmark of -18.0 percent with a -25.7 percent drawdown into +3.8 percent with none | `MEDIUM` | Section 5 |
| DR-09 | `data/live_checks.py` | Silent non-check | The shipped pairs are `BTCUSD` and `BTCUSDT`. The check looks under `pair.symbol`, finds nothing, and runs only `poll_rebuild`. No row says it did not run. It looks back 3 days, so a source whose history arrives later than that is never checked | `MEDIUM` | Write `not_available` per day. Use the declared archive symbol. Set the window by what exists |
| DR-10 | `data/derive.py` `check_status` | Wrong word | A clean day on a venue with no candles reads `pass`, `reconciled` false. The charter's G1 says reconciliation is never reported as passed, and the report and raw deletion both trust that word | `LOW` | A distinct status such as `unreconciled` |
| DR-11 | `data/poll.py` `_record_correction`, `_record_gap` | Hole flagged in the wrong place | Id 105 at 13:30:30 is held. Id 106 stamped 13:20:30, price 90, is published later. A `since` cursor is past it, so it never returns. Id 107 shows a skip, flagged from 13:30:30 on. Bar 13:21 stays `gap=False`, proof `id_run`, and no correction is written. The corrections path is reachable only by rewinding the cursor, as its test does. Possible only if ids do not follow stamps, which is `UNVERIFIED` | `MEDIUM`, conditional | At G1, evidence that ids follow stamps. If they do not, a fetch overlap behind the cursor. Add a reader for corrections |
| DR-12 | `data/poll.py` `rebuilding`. `.github/workflows/live-poll.yml` | Wrong label | Cache lost and the state read fails: `gh api ... \|\| rm -f` looks like a first run, and bars come out `emission = first`. Knowable times stay honest, so this is a wrong audit trail and not a leak | `LOW` | `first` only on an explicit "no such state" answer |
| DR-13 | `data/derive.py` `_record_holes` | Market state as a status | Ids consecutive across a silence, so every minute has proof. At 14 minutes nothing happens. At 20 minutes, with the placeholder of 900 s: minutes flagged, day `warn`, day excluded from statistics. Quiet days leave the results, the mirror image of what R2.2 forbids | `MEDIUM` | Section 7.4 |

## 5. The rulings asked for

### 1. Lost history

**Yes, this is selection.** It is not a future leak, since everything used was known at the report's time. But the window starts wherever the last bad day fell, and a bad day may well be a stressed day.

| Case, 12 days, a fall of about 25 percent on the seventh | Start | Days | Total return | Max drawdown |
|---|---|---|---|---|
| No fault | 03-01 | 11 | -18.0% | -25.7% |
| Fault on the day of the fall | 03-08 | 4 | +3.8% | 0.0% |
| Fault on the third day | 03-04 | 8 | -20.4% | -25.7% |

A benchmark is what strategies get compared with, so this flatters nothing directly and misleads anyway. In the 30-day run the 25 and 29 days come from a fault the generator places on one symbol, so two symbols are reported over different spans. The only trace is a boolean, `missing_days_before_start`.

**Fix.** The span is declared in advance and common to all symbols, and it is not re-based on any failure. Excluded days stay as holes. Total return runs from the first usable open to the last usable close across holes. Volatility and Sharpe use only one-day returns between adjacent usable days, with the count shown. Drawdown uses the marks that exist. The report states days in span, days used and days excluded. The docstring's reason, that a return across a hole is not a one-day return, is right for volatility and does not need the rest. **No strategy result may ever use a newest-unbroken-run rule.**

### 2. Neighbours

**Acceptable in one case and not in the other.**

- **A real disagreement at a shared midnight:** acceptable. Neither day alone can say which is wrong, and only the bars at that boundary are flagged. It still needs the knowable-time fix in DR-04.
- **A fault away from midnight:** not acceptable. It reaches its neighbours only because `flow_reliable` is one flag for the whole day. It is also **up to three days and not two**: with volume crossing both midnights, a fault at 10:00 on D excluded D-1, D and D+1 in my probe. And the D-1 half is DR-04, a leak.

**Fix.** The split in DR-04. D-1 then passes, since D's carry in was fine at its first boundary. D+1 may warn, since D's carry out is truly unknown, and that flag is causal. The log must name the fault day, so one fault is not counted as several.

### 3. `DATA_GAP` rate

**The rule behaves as intended. The figure of 25 of 47 overstates it, and it does bias the sample, causally.**

Two things inflate the figure. **10 of the 47 runs come after the generated market has ended,** and all 10 log `DATA_GAP`. And it counts a run if either of two symbols lacks evidence. While the market has trades, it is 15 of 37 runs, and 8 and 10 of 37 per symbol. The arithmetic for one symbol is below, and real runs agree: 69 of 298 (23.2 percent) against 25.4 percent.

| Trades a minute | `DATA_GAP`, live | `DATA_GAP`, backtest window | First check fails, under `C-LATE` delays |
|---|---|---|---|
| 0.2 | 71.8% | 74.2% | 87.6% |
| 0.84 | 25.4% | 29.2% | 58.8% |
| 2 | 4.2% | 5.8% | 30.9% |
| 6 | 0.015% | 0.041% | 6.1% |
| 12 | under 0.0001% | 0.0001% | 1.1% |

It is causal, since it rests only on what was held at the run. The backtest window is stricter than live, which is the safe direction. There is no leak.

**The bias.** A lost run is a run on a quiet tape. On a tape that switches between 0.2 and 5 trades a minute, quiet hours lose 72.0 percent of runs and active hours 0.055 percent. A lost run is about an hour lost, and under `C-LATE` the setup is then older than `A_max` in 86 percent of cases at 75 minutes and 51 percent at 90. So on thin data the cycle leans toward entries on an active tape. That applies live and in a backtest alike, and C14 keeps the counterfactual. Real tapes cluster, so Poisson arithmetic is a floor. **Required:** report `DATA_GAP` by symbol and UTC hour, the share of setups delayed or staled by it, and their `CF_CYCLE` against those taken. I set no threshold. No rate here describes a real source.

### 4. The `IDEAL` reader

**`decide` must not be the one to handle it. The reader must return standing as of the read.** Leaving it to `decide` leaves `knowable_time` and `gap` in every consumer's hands.

**The rule: a `gap`, an `empty_proof` or a `complete` is a state event with its own time, as C4 says of registers. It does not exist before the row that shows it is knowable.**

- **Reader.** `ideal_bars(at)` on full data must equal `ideal_bars(at)` on data truncated at `at`, on every column. For a row whose standing rests on something later, an empty minute reads `none` and `gap=True`, and a traded minute reads as a build with no later row would give. Higher bars are aggregated from that as-of view, and not read from stored ones. `knowable_time` leaves the view.
- **`decide`.** An empty minute unproven at `t` makes the `T_d` bar closing at `t` not complete as of `t`, so no setup is created at that close. This is fail-closed, as C2 and C17 are. A later proof creates nothing retroactively.
- **A later gap** takes effect from its own knowable time. `ATR` goes undefined from there, and a position open across it becomes `GAP_UNRESOLVED` at that time. An empty minute touches nothing in a stop walk.
- **Report** the number of setups lost to an unproven tail. On a liquid market this is rare, and at 0.84 trades a minute the last minute of a bar is empty about 43 percent of the time.
- **`IDEAL-1M` has the same need and no reader.** `bars()` at `(t, t + A)` raises on a quiet tail. It needs the same as-of view at `t + max(latency, A)`.

### 5. The developer's reading of DC-01

**Correct, and required.** A minute closing at `C` is over only when a row stamped after `C` is held, and in integer microseconds the last such close is `floor_1m(newest - 1 us)`. That is C17's "a record stamped after `t_cut`" applied to each minute. Probe: a row stamped exactly 12:05:00.000000 leaves emission at 12:04. The next run brings a second row on that stamp, and the bar closes with all three of its trades. `floor_1m(newest)` would have emitted it short, and it could never be rewritten.

### 6. The `IDEAL` block on `allowance_state = "measured"`

**It holds, stricter than I ruled, and I accept it.** An unmeasured allowance says nothing about what had printed. Two conditions, because `measured` is only a word in a file:

1. It names its evidence: dates, the stressed days included, and who signed. `data-steward` signs.
2. The measurement comes from data outside any test block, and is frozen under C12. A change is a counted trial, because the allowance moves rows between bars. A value measured over a whole history would let later data decide earlier reads.

### 7. Official 1-minute candles as research bars

**Allowed, on the conditions below.** An official candle is not a leak in itself. It covers `[open, open + 60 s)`, so it holds only prints stamped before its close, and it can hold one instant less than our bar. What it breaks is the contract's wording and several assumptions in the code.

**How such a bar states its knowable time.**

- `close_time = open_time + 60 s`, computed on the grid. The file's own close field, `open + 59.999 s`, is checked and discarded. Used as an instant, it would show a bar 1 ms before its minute ended. The open label is never a knowable time, which would be a one-bar leak.
- `knowable_time = close_time + candle_allowance`. This is its own declared per-source key, because `fill_span_allowance_ms` describes trade rows. It covers the venue's time to finalise a minute's candle, and it is `UNVERIFIED` until measured. `IDEAL-1M` and `CYCLE` assert `A >= candle_allowance`. The date an archive file was published does not enter: the contract asks when a live system could have had the value.
- A higher bar is knowable at the latest of its inputs, as `aggregate_bars` already does.
- Each bar states its source and boundary: `bar_source = official_1m`, `boundary = [open, close)`. Separate dataset names, as the poll's `_live` sets have, mean it can never be read as a trade-built bar.

**What must hold.**

| # | Condition | Why |
|---|---|---|
| 1 | **Charter item 1 and C2 say it.** "A bar from official candles covers `[open, close)`. It is knowable at its close plus the source's declared candle allowance." C2's bar source bullet carves out this run | The contract is law, and it says `(open_time, close_time]` |
| 2 | **A candle holds no print from after its close, shown and not assumed.** On sample days outside any test block, compare candles with aggregate trades in the exact form of section 15, and not through `reconcile_official`'s walk. Cumulative candle volume at each boundary must never exceed cumulative trade volume stamped before it, apart from a carry that section computes and bounds. One excess falsifies the condition | That candles count each fill in its own minute is inferred from a first look. If it fails, `IDEAL` may not read their volume |
| 3 | **Last-trade candles only,** from one venue and symbol. Not mark or index | C1 |
| 4 | **A missing row is a gap.** A row with zero trades is proof of an empty minute, a third kind that C2 must name. **Its prices are set to null** if the venue carries the last close forward, which is `UNVERIFIED`. Otherwise a carried price can touch a stop, and that is a forward fill C2 forbids | Same rule, different proof. Here the proof comes from the row itself, so nothing rests on a later row and DR-03's problem does not arise on these bars |
| 5 | **Checks at the row:** checksum, 1,440 rows, the grid, `H >= max(O, C)`, `L <= min(O, C)`, taker buy at or below volume. A failure flags that minute | A candle cannot reconcile against itself, so G1 reports reconciliation as not available until trades arrive |
| 6 | **No mixing.** All modes read the same bars in a sample. Bars from trades later are a new document version with counted trials, nothing is joined across the change, and the difference at boundaries is reported | The boundary moves prices and volume between adjacent bars |
| 7 | **`IDEAL`.** Once condition 2 holds, these bars' plain columns are already settled, so `settled_*` equal them and `fill_count` is readable. The gate is condition 2 and no longer the trade rows' `allowance_state` | `ideal_allowed` looks at the source's trade rows, which is the wrong test for these bars |
| 8 | **Fill reference.** Under `IDEAL`, `O_(k+1)` can be a print stamped exactly at `t_k`, the decision's own instant. The decision did not read it, so no information leaks, and the mode is labelled zero latency. `IDEAL-1M` is unaffected | Stated so nobody reads it as a clean next print |
| 9 | **Funding.** C10's boundary stands, with a fill at a candle open timed at that open: an entry at a settlement instant pays nothing for it, and an exit at it pays | Stated for the first run, which charges funding |
| 10 | **`CYCLE` on candles declares its own completeness rule.** C17's "a record stamped after `t_cut`" could only be met by stepping back a minute on every run. A candle row is complete when it exists, so the check is that the candle closing at `t_cut` is present and known by `t_poll`. C-10's trade feed values must be re-based on this too | Until then no `CYCLE` run may start, so C18's selection under `C-LATE` is not available, and a first run that selects on `IDEAL` would break C18. The first run reports `IDEAL` and `IDEAL-1M` and selects only S01 and S06 |
| 11 | **S07 and S08 need trades.** Under `T0` they do not run as written, and `T0-APPROX` stays a labelled cross-check | Their sums need rows |

**Tests to add.** Truncation and perturbation at every minute on these bars, a bar invisible until `close + allowance`, a stamp exactly on a boundary falling in the later bar, a missing row as a gap, and a zero row with null prices.

**Code today.** `parse_klines` has the right knowable time in shape, but it uses the trade allowance, and its output is not a bar: it has no `close_time`, `gap`, `empty_proof`, `buy_volume` or `settled_*`, so `aggregate_bars` and `bars_for_run` cannot read it. The converter is new code, and it comes first in section 10.

## 6. The text in `38d5907`

| Item | Ruling |
|---|---|
| Charter item 1 | **Holds** |
| Mode table: "only" limited to volume fields | **Keep.** Prices on one-price rows are prints at or before the close. `trade_count` is readable too: it moved at 0 of 150 closes |
| `fill_count` named as not readable | **Keep.** It corrects my omission |
| C2 carry-through sentence | **Keep, with one edit.** It is needed, or section 4 of every strategy contradicts charter item 1. Read literally, a swing would not be knowable at a close under `IDEAL`. Add: "`IDEAL` reads prices at the close" |
| "does not apply on that source" | **Keep, with two edits.** The report says `IDEAL` is not available, and never omits it silently. C17 item 7's figure becomes `IDEAL-1M` minus `CYCLE` there, so the cost of the cycle stays visible. `docs/02_features` has since moved its research clock to `IDEAL-1M` at `3f0db56`, so that folder no longer depends on this |
| "rows of one shape" in C3 | **Keep.** It is right, and it bites whenever history and live rows come in two formats or from two deliverers, such as a vendor's history beside a venue's live feed |
| G8 clause in C17 item 6 | **Keep.** It is DC-10's fix |
| Mode table: `A >= fill_span_allowance_ms`, in one unit, on `IDEAL-1M` and `CYCLE`. C17 constants: nominal minute 7 and the `A` row | **Hold.** Minute 7 is settled and matches the cron and `nominal_minute`. The note that top-of-the-hour load at minute 7 is `UNVERIFIED` is right |
| C2 bar source: "read the same bars, apart from the volume fields" | **Holds, with `fill_count` and as-of standing added to the exception** |
| G1 cap at `PASS WITH CONDITIONS` | **Holds.** With no outside check, a clean `PASS` would claim what nobody tested |
| "reported as not available, never as passed" | **Holds.** The code does not match yet (DR-10) |

**Text still to change, and owners.**

| Where | Change | Owner |
|---|---|---|
| Mode table | Define settled by the corrected rule. Say standing is read as of the read, and `knowable_time` is not in the view | `strategy-architect` |
| C2 | A proof or a flag counts from its own knowable time | `strategy-architect` |
| C17 time fields | `knowable_time` still says "usually a bar close", and `lateness` subtracts it. A polled bar's is its receipt, so `lateness` would come out near zero or negative. Name a bar close time for `lateness`. This is DC-07's fix, and it is not done | `strategy-architect` |
| Charter G1 item 2 | `max_quiet_s` is measured on data outside any test block and frozen under C12. The id evidence also shows ids follow stamps | `project-manager` |
| S07, S08 | Section 6.1 | `strategy-architect` |
| `GATE_SPEC.md`, open item on S07 and S08 under `IDEAL` | Closed by section 6.1 | `feature-integrator` |

### 6.1 S07 and S08 under `IDEAL`

**The ruling goes by one property: can a row carry a print from after the close?** Under `D-29`, S07 and S08 do not run on the candle stage at all (ruling 7, condition 11). Bars from trades later use one-price aggregate rows, which is the first row of this table.

| Source | S07 and S08 under `IDEAL` |
|---|---|
| **Rows can carry an after-close print.** A row or a stamp covers an interval: aggregate rows, same-stamp groups that take time, coarse stamps, batches. **Any source not yet shown otherwise counts here,** including every source on a placeholder allowance and a vendor's history before its rows are checked | **No `IDEAL`.** Sums by stamp read fills from after the close |
| **Rows cannot.** Each row is one fill, stamped at its own print time. That means `stamp_kind = "exact"`, a measured allowance, and evidence for both | **`IDEAL` is allowed.** The sums read rows with `knowable_time` at or before `t`. With a measured allowance of zero, that is every row stamped at or before `t`. With an allowance that only covers the stamp's resolution, it leaves out rows stamped inside it, and they count at the next close |

**Evidence.** Sums by stamp, as sections 3 and 4 read them, moved at 22 of 209 closes on aggregate rows when only fills after the close changed. Sums over rows with `knowable_time` at or before the close moved at 0.

**Rows that can carry one.**

- Both options are causal, so this is about surface and not about a leak. The settled read would be sound, and it needs no new path: it is `trades` at `RunClock(t - span, t)`. I do not take it, because `IDEAL` here is never selected on and never compared with live, so it adds a read and a test for a number nobody needs.
- Fail-closed is the code's state today. When `trades` at `(t, t)` returns at all, every row is older than the allowance, so whatever it returns is causal, though it is not a defined input.
- "Loses no selection" is right. C18 selects these two under `C-LATE`, and `GATE_SPEC.md` at `3f0db56` runs its research kind on `IDEAL-1M`, so no flow variant needs this. What remains is C17 item 7's figure and S08's 30m comparison, which use `IDEAL-1M` for these two strategies, labelled. `trades` at `(t, t + A)` already serves that.
- `T0-APPROX` may not stand in for it.

**Rows that cannot.**

- Before this read exists, the reader needs an `ideal_trades(at)` that checks `ideal_allowed`, because `trades` does not look at the row shape.
- It needs ruling 4's test, on every column: the read at `t` on full data equals the read at `t` on data truncated at `t`. It also needs a fill-level test that changes only fills after `t`.
- A source's class is a declared value with evidence, and it can be revoked. If the detector shows a row running past the allowance, the source moves to the first row of the table.
- One fill model holds across a sample, so a source does not change class partway through a run.

**Section 14 of both, on every source.** "The same whether the run was on time or late" and "Late runs therefore produce the same values" hold only with no late or missing trades. Replace with: values do not depend on when a run happened, for the trades held. A trade received late enters the running totals from the first close processed after it arrived, and earlier values are not rewritten. The difference from an archive rebuild is reported, as C3 says.

## 7. Code that does not match the text, and the lifecycle rulings

### 7.1 Does each block?

| Item | Blocks? | Ruling |
|---|---|---|
| `ideal_view` passes `fill_count` | **Yes, before any source can have an `IDEAL` shape.** It does not hold back `CYCLE` | DR-02. One line, in the same edit as DR-01 |
| `emission` only on `bars_1m_live` | **No, not now.** Due with DC-10, before the first `CYCLE` run | No leak: knowable time stays honest, and a replay at an older clock raises. It is an audit trail gap. A higher bar should carry `rebuild` if any of its minutes does |
| `A >= allowance` only in the poll path | **No.** Due with the engine | `bars_for_run` and `trades_for_run` already raise at read time if `t_dec - t_cut` is under the allowance, so a second guard exists. Comparing a 10 s `UNVERIFIED` value with a 250 ms placeholder proves nothing, and must not be reported as C-4 met |
| "frozen under decision D-18" and "stays frozen at 250 ms" | **Fix the words in the next edit.** It blocks no logic | Both are false. `D-18` freezes nothing, and the roadmap has it pending. Say: placeholder, not frozen, frozen under C12 before the first `V0` run |
| Window and allowance as separate keys | **Yes, before a source is enabled** | DR-06. With one constant, raising the window to pass a day also moves every knowable time, so the knob has a cost |

### 7.2 R1.1, a digest of what a rebuild can reproduce

**Agreed, with four conditions.** It is computed over rows emitted by that run, so nothing later enters, and it holds no future.

1. **A matching range proves values only.** It never restores `first` or a receipt time, and it does not make a rebuilt row readable by a replay. A G8 replay still reads `decisions/`.
2. Encode as scaled integers and not float text, or a library upgrade reads as a mismatch.
3. Name the volume columns. After DR-01, `settled_*` are reproducible, and either way the list is written down once.
4. Nothing in `decide` reads it.

### 7.3 R3.1, watermarks on persisted zones

**Agreed.** Watermarks read sizes and no market value. One point goes with it: backfill runs newest first and stops on size, and volatile periods are larger, so how far back history reaches depends on later data, and it can differ by symbol. **The research span is declared in advance and common to all symbols. If the backfill does not reach it, the run is blocked, or the span changes by a logged decision. A run never starts where the cache happened to end.**

### 7.4 R2.2, and the size band

**I agree: a size band may only alert, and it never sets a status.** Three additions.

1. The band uses only partitions before the one checked.
2. An alert cannot lead to a day's exclusion by a person either. Size alone is never a reason, and any exclusion is logged.
3. A test holds this: bars, flags and statuses are byte-identical with the band on and off.

**The same principle already reaches code that exists.** `max_quiet_s` sets `warn` and excludes the day (DR-13), which is selection by quietness. Where ids prove continuity, C2 says the minutes are zero-volume bars. So: until G1 evidence shows ids are consecutive by design, the flag may stay as a declared constant under C12. After that, a proven silence alerts only. **A silence alone never excludes a day from statistics.** `fill_count_rel` and `bar_price_rel` also set statuses. Both are integrity checks and stay, under C12. Both need rechecking on sample days, because the rule was designed from a first look at one day of files.

## 8. The injected-leak run, whole suite

**The figure, in the audit's terms: 1 of the audit's 30 passes everything, against 3 last time, and it is nearly harmless. At most 1 is caught only by accident, against 2.** DC-11 did what it set out to do. **The holes are in what was added since.** Of the 85 new leaks, 75 ran, 63 were caught and 12 pass what ran. 8 of those 12 are direct leaks.

**What did not run.** I stopped the run to report, with 105 of 115 finished. These 10 have no result, and nothing is concluded from them: `ideal_bars` on a missing dataset skipping the row-shape check. `derive_day` with a failed check flagging nothing. `derive_day` accepting rows received after their stamp. The live against archive check never running. And six in the report and parsers: a day counted before its next file could exist, failed and warned days counted, the poll summary and the reconciliation summary not as of the stated time, statistics spanning holes, and official candles knowable at their open. The last of those is replaced by item 1's converter, whose tests must cover it.

**Limits of the run.** It stops at a mutant's first failing test, so one caught by an indirect test may have a direct one behind it. Three mutants ended in an unrelated setup error (batch 4).

A first attempt was invalid and is discarded: my harness pointed pytest at a temporary directory whose parent did not exist, so every test using `tmp_path` failed at setup and nearly every mutant looked caught. That was found by reading the results, because poll mutants were being "caught" by an unrelated reader test. The harness now creates the directory, and a control mutant that changes nothing has to pass everything. The list has 115 leaks: the audit's 30, adapted, and 85 new, centred on `data/reader.py`, the `settled_*` columns, `bars_for_run` and `trades_for_run`.

The baseline on an unmodified clone with its own `.github` and git is 832 passed, 2 skipped, and the control mutant gives the same. The developer's 41 were each run only against named tests. These run against the whole suite. A mutant caught by `tests/leak` is counted as caught, and the rest of the suite does not run for it.

**Batch 1, the audit's own 30, adapted to this commit.** Last time: 3 passed everything and 2 were caught only by accident.

| Result | Count | Injected leaks |
|---|---|---|
| Caught by `tests/leak` | 19 | Including all five that passed last time or were caught only by accident: the one-in-seven high peek, the peek on every bar of the grid path, the peek placed only in `derive_day`, the peek past a bar on 240m, and the same on 30m, 120m and 1440m |
| Caught by a focused test elsewhere | 10 | Empty minute forward filled. Poll emitting the minute in progress. A late trade repainting a bar. Polled trades knowable at their stamp. Poll gap flags dropped. Official volume replacing trade volume. Last bar not flagged. Aggregates stamped early. Archive trades knowable early. Report equity marks with no as-of filter |
| Passed the whole suite | 1 | Report daily bars read with no as-of filter. See below |

That one is nearly harmless now: a later filter, `close_time <= now - 1 day`, already holds every statistic to the past. One thing still reads the unfiltered frame, the `newest_day_provisional` boolean, which would say a newer day exists when that day is after the report's stated time. `LOW`. A test with a later day on disk, reading that field, closes it.

**Batch 2, the `settled_*` columns and the `IDEAL` view, 17 new leaks.** 13 were caught, by `test_core`, `test_reader` or the fill-level test in `tests/leak`. **4 passed the whole suite:**

| Injected | Effect | Is it a leak |
|---|---|---|
| `ideal_view` swaps only `volume`, and leaves plain `buy_volume`, `sell_volume` and `quote_volume` | Signed flow under `IDEAL` includes later fills | **Yes, direct.** The tests look only at `volume` |
| Deferral inside half the allowance only | A row stamped 200 ms before a close stays in its bar, with a 250 ms allowance | **Yes, direct.** No test sits between half the allowance and the allowance |
| `settled_buy_volume` ignores the side | Every row counts as a taker buy | No future data, but a wrong input to any signed rule. The test rows are all buys |
| `derive_day` does not carry rows from before midnight | Settled volume is lost at each midnight | No future data, and it errs low. Tested in `build_bars_1m` only, and never through `derive_day` |

**Batch 3, `data/reader.py`, 15 new leaks.** 10 were caught, all by `test_reader`. **5 passed the whole suite:**

| Injected | Effect | Is it a leak |
|---|---|---|
| `trades` cuts at `t_dec`, not `t_cut` | A run reads trades stamped after its cut | **Yes, direct.** The test calls it with `t_cut = t_dec`, so it cannot tell them apart |
| `live_trades` cuts at `t_dec`, not `t_cut` | The same on the live path | **Yes, direct.** Same reason |
| `live_dataset` reads to `t_dec`, not `t_cut` | A live gate reads rows knowable after the cut | **Yes, direct.** Same reason. Dormant, since no dataset is eligible |
| `ideal_bars` returns plain columns for a higher timeframe | Higher bars under `IDEAL` hold later fills | **Yes, direct.** Only 1m is tested |
| `_load` ignores the lower bound of `since` | A read returns days before the one asked for | No future data |

The fix is a test with `t_cut` clearly earlier than `t_dec` on each read, and one `IDEAL` test per timeframe.

**Batch 4, `bars_for_run`, `trades_for_run`, knowable times, gaps and the lifecycle, 53 new leaks.** 43 ran. 40 were caught, nearly all by a test aimed at that behaviour. **3 pass what ran:**

| Injected | Effect | Is it a leak |
|---|---|---|
| `trades_for_run` cuts at `t_dec`, not `t_cut` | A run reads trades stamped after its cut | **Yes, direct.** Its test is named for this and calls it with `t_cut = t_dec`, as the reader's tests do. So the trades path has no test of the cut against the decision time anywhere |
| `trades_for_run` drops the row stamped exactly at `t_cut` | A trade at the cut is lost | No future data. It errs low |
| Poll: a bar is knowable at the start of the attempt, not at the last page | A bar is readable before it was received, by the length of the fetch | **Yes, direct, and small.** Live path only |

These three did not finish cleanly. Each passed the focused tests, `tests/leak`, ingest and report, and then `test_workflows` stopped on a setup error in its `git init` step. That is unrelated to the injected code, and the same test errored the same way on an unmodified clone when I ran it alone under that load. A plain `git init` from a script succeeded, and I did not find the cause. **So I do not count that error as a catch.** The rest of `test_workflows` and the end-to-end test did not run for them. Neither file calls `trades_for_run`, so the first two cannot be caught there. Whether the end-to-end test could catch the poll one is `UNVERIFIED`.

**Caught only by accident.** Among the audit's 30, official volume replacing trade volume was stopped by a test about a trade at midnight. Among the new ones, a failed check flagging the whole day was stopped by a process-kill test. Each may have a direct test behind it, for the reason above.

## 9. Rulings by source property

Under `D-29` the source is one venue's public files: official candles and funding first, and aggregate trades for bars later. These properties decide what applies to that later stage and to any other source. **Every value is `UNVERIFIED` until checked on the chosen source, and I opened none.** Today's configuration rows are first values and no evidence of anything.

| Property to establish | If so | Ruling |
|---|---|---|
| **Row shape:** one fill per row, or one stamp over an interval | Prices can carry an after-close print (same-stamp groups that take time, coarse stamps, batches) | No `IDEAL` for any strategy, only `IDEAL-1M` and `CYCLE`. DR-01 and DR-02 are unreachable there. C14's `CF_IDEAL` does not exist there |
| | Only quantity can (one-price aggregates) | `IDEAL` through the settled columns once DR-01 to DR-03 are fixed and the allowance is measured. S07 and S08 report none |
| | Neither can (exact rows) | `IDEAL` once DR-03 is fixed and the allowance is measured. S07 and S08 may report it, under section 6.1 |
| **What a stamp means, and its resolution** | The stamp is a deliverer's receipt and not the match time | It is not a trade time. Bars cannot be built on it without a declared span covering the difference. A deliverer's receipt is also not this system's receipt, so it says nothing about `A` on the live path |
| | The stamp is floored | The allowance must cover the resolution. A coarse stamp is `floored`. Where a fine stamp stops being `exact` is a declared value with evidence |
| **Ids** | Consecutive by design, from the venue | `continuity = trade_id`. G1 evidence must also show they follow stamps, or DR-11 applies and needs a fetch overlap |
| | A deliverer's sequence or a row number | `continuity = none`, so every empty minute is a gap, unless evidence shows that sequence reveals a dropped row. A deliverer's own outage may show no skip at all |
| **Official candles readable** | Yes | DR-04 and DR-05 go live when they are read, so both fall due first. The reconciliation rule was designed from a first look at one day of files, so it must be rechecked on sample days, and on any other source it may not apply in the same form (`D-18`) |
| | No | G1's no-candle branch: the cap at `PASS WITH CONDITIONS`, reported as not available, and `IDEAL` on volume blocked until other evidence bounds the span |
| **History and live from one format, or two** | Two formats or two deliverers | C3's "match exactly" does not hold, by construction. DC-09's comparison measures the difference, once DR-09 lets it run, and the difference goes in the report beside any `CYCLE` result |
| **How the live feed is read** | A cursor | Late rows can fall behind it (DR-11) |
| | A time window | A late or dropped run can lose trades outright, which must log a gap. The current poll adapter assumes a cursor, so a new adapter needs this audit |
| **How often history arrives** | Later than the 3 days `run_live_checks` looks back | DR-09: that check never runs unless the window changes |
| **Can history be revised** | Yes, or unknown | DC-14's hash history applies. A backtest's manifest names what it read. A revised row keeps its original knowable time, so a change is an alert and never silent |
| **Trade rate, by symbol and hour** | Thin in any hour | Section 5, question 3. It sets the `DATA_GAP` rate, the unproven tails of ruling 4 and the empty minutes of C2 |
| **Instrument** | Spot and not a perpetual | C1 says one linear perpetual per symbol, and C10 charges funding. Neither fits. No leak, but `strategy-architect` must conform them |

**The shape where everything is live.** One-price aggregate rows with official candles, which is what bars from trades under `D-29` will be, make DR-01 to DR-06 all reachable at once. The candle-only first run reaches none of them.

**The hourly live path has no source,** and its adapter is written for one API. Whatever is chosen needs its own adapter, its declared properties and this audit.

**The private demonstration in `D-27` ran ahead of this recheck.** I have read its record and not the demonstration. Nothing here is evidence for it, or from it. Section 13.2 rules on its status.

## 11. Search tool caveat

My first audit's search of `src/` for `visible_bars`, `assert_knowable`, `forward_fill` and similar used a tool that skipped `src/hft_crypto/data/`. I repeated those searches with `git grep` at `b874055` and at `dafe3f2`. **The conclusions stand:** at `b874055` `visible_bars` was called only by the report, and `assert_knowable` and `TimingContractError` by nothing. There is no `forward_fill`, `backward_fill`, `interpolate`, `ffill`, `bfill`, `shift(` or `quantile` in `src/` at either commit. The only `fill_null` in `data/` is on text digits and a boolean. Nothing writes `raw/live`.

## 12. Probes, checked and not checked

| Probe | Result |
|---|---|
| Truncation and perturbation on the grid path, rows visible at the cut, 4 trade rates, 2 allowances, with and without ids, id skips and multi-fill rows, 8 timeframes | 0 of 4,024 and 0 of 4,024 |
| The same through real poll runs, hourly over 2 days, 4 cuts, 5 datasets | 0 of 20 and 0 of 20. No bar visible before its close |
| The same through `derive_day`, 20 cuts, 8 datasets, with id skips and multi-fill rows | 0 of 160 and 0 of 160 |
| Fill-level truth against settled columns | DR-01, DR-02. Settled is never above what had printed |
| `ideal_bars` against truncated data | DR-03 |
| Poll runs | Section 2, DC-01, DC-05, DC-07, DC-10 |
| Reconciliation, neighbours, window, detector, silence | DR-04, DR-05, DR-06, DR-13, section 5 |
| Report and benchmark | DR-08, DC-15 |
| `DATA_GAP` | Section 5, question 3 |
| Fold plan, against git history at `1e634fc` | Sections 13 and 14. No data was opened. Times are UTC, from commit headers |
| The form of condition 2, on generated fills with planted prints | Section 15 |

**Checked and clean.** Knowable time on all timeframes and both paths. No later bar in report calculations. No forward or backward fill. Official candles change no bar. First receipt stands. A failing day's earlier minutes are untouched on the same day.

**Could not check.** Any real feed: row shapes, spans, stamp resolution, publication lag, late trades, id order and trade rates on any candidate source, all `UNVERIFIED`. `decide`, `settle`, the modelled fetch, registers, `ATR`, the ledger and Telegram, which do not exist. Real GitHub behaviour. Whether long aggregates cluster in stressed periods, which the size of DR-05 and DR-08 depends on. For the fold plan: the demonstration itself, its rule, its run time and its 12 days, none of which I can reach. The dates of the `D-18` runs. The host's push times, which need network. Coverage, which `data-steward` measures. The new modules.

## 13. The fold plan, `1e634fc`

**Verdict: `PASS WITH CONDITIONS`.** The dates, the failing-quarter rule and the read rule hold as rules. What does not hold yet is the control behind the read rule and the record of the demonstration. Every time below is UTC, from commit headers. Git dates can be rewritten, so they show order and not proof.

### 13.1 Findings

| ID | Location | Leak class | Scenario with times | Severity | Fix |
|---|---|---|---|---|---|
| FP-01 | Plan section 3. `reports/report.py`, `.github/workflows/daily-pipeline.yml` at `dafe3f2` | Locked block read by a report | "The reader refuses" reaches only code that uses `MarketReader`. `report.py` reads parquet directly, and the daily workflow runs `report --published` and then publishes. Enable the source and fetch to 2026-09-30 so coverage can be counted, and the next scheduled run writes a benchmark with total return and drawdown over the test and locked dates, and publishes it. By the plan's own definition that reads every unopened date, in a public repository, and it cannot be undone | `HIGH`. One run spends the locked block | Section 10, items 0 and 3a. A test with unopened dates on disk shows every report stops at the last opened date |
| FP-02 | `D-27`. Plan section 4 | Trial run and not counted | A rule was simulated on real trades on 12 days. The record gives one latest time, 12:22 on 2026-11-05 when `D-27` was committed. If no such file was read before the entry allowing them (`D-22`), the earliest is 11:07 the same day. `D-27` calls it not a trial, with no rule text on file | `MEDIUM` | Section 13.2 |
| FP-03 | Plan section 4, "S01 to S10 and the index last changed on 2026-11-04" | Evidence for the freeze falls short | Checked in git. S01 to S10 last changed from 19:11 to 19:47 on 2026-11-04, which holds. The index last changed at 00:01 on 2026-11-05, the same UTC date as `D-27`, so "before the date" is false for it, though it precedes the 11:07 above. The sentence does not cover `3f0db56` at 11:46, which rewrote all four feature documents with the flow recipes and constants, or the cost proposal at 12:03. Both may fall after the demonstration began, and it showed trades. I found no link to its output, and I did not audit those diffs for one | `MEDIUM` | Record the run's start time. C-5 lists, per file, the last commit before it. The diff from there to the C-5 commit is published and audited: each changed rule or constant cites its reason, and none cites a result. One with no such reason is a counted trial, and those days count as used for it. This covers edits being made now, and it takes the host's push time for the anchor commits |
| FP-04 | `D-28`. Plan section 5 | Constant set after sight of the block | `D-28`, at 12:46, comes after a view of longs, shorts and the portfolio on 10 locked days. It calls its values "chosen for the first view" and says "they can change". An answer of 0.5 percent or 2x gross, given with that view in mind, shapes every portfolio figure on the locked block. The risk budget cancels out of `Result_B`, so this reaches the portfolio figure and not a strategy's own verdict | `MEDIUM` | Freeze them before any block opens, with their stated basis. Replace "they can change": a change is a counted trial, and it is `EXPLORATORY` on every block already read. The locked portfolio figure says they were set after `D-27` |
| FP-05 | Plan section 5 | Selection with no counted step | "Every grid line, not a chosen best", but also "the portfolio figure". S03 has 8 lines per symbol and cannot select at this stage. If whoever builds the figure takes the best on the first span under `IDEAL-1M`, that breaks C18 for six strategies with nothing counted, and the owner sees a portfolio of eight best lines | `MEDIUM` | Declare before the first run: S01 and S06 by their `IDEAL-1M` selection, the other six by their documents' default line or all lines at equal weight. The rule is printed on the figure. Another rule is a counted reading |
| FP-06 | Plan section 4. C11 | Outcome on a read day steers the verdict | S03 at 1h, `H_max` 10 d. A setup at 2025-11-30 20:00 touches the read day and is left out. If the engine simulates it anyway and drops the row in the report, then whether the setup at 2025-12-02 03:00, which stays in, trades or is `SKIPPED_OPEN` rests on how the first resolved on 2025-12-01. "No outcome is computed" is then false | `MEDIUM`. Dormant until the locked read, and the engine is being built now | Section 10, engine notes. A test asserts that no fill, touch or exit is evaluated on a bar inside a read day |
| FP-07 | Plan sections 3 and 4, against C18 | Fill on an unopened date | S02 at 1h, `H_max` 3 d, `t_k` 2023-12-29 00:00. `t_k + H_max` is 2024-01-01 00:00. Section 3 says "passes the last opened date", which this does not, so it stays in. C18 says "reaches", and removes it. Its time exit, decided at 00:00, fills at the first print after it, on an unopened date. Section 4's `(t_k, t_k + H_max]` has the same edge at 00:00 on a read day | `LOW`. The guard raises, and C18's data end removes it | Use C18's word in both places |
| FP-08 | Plan section 3, "Read" and "Not a read" | Definition leaves two doors | A funding rate is not a "price, return, flow or outcome" on a strict reading, and a table of 2024 rates shows which side the market paid. Separately, sizes and counts by day are "not a read", and files grow in busy periods. If the sample days of ruling 7 or the stressed days of a `measured` allowance are picked from such a table, unopened dates choose a constant with no read in the log | `LOW` | Add funding, and anything computed from these. Add: "Counts, sizes and flags on unopened dates may decide only coverage and storage. A rule, constant or sample chosen from them is a read" |
| FP-09 | Plan section 2, "applies this once". `D-31` | A rule with no case after the first outcome | Stage 1 counts coverage on candles and reaches its first outcome. Later the trades files for a test quarter turn out to have three missing days. The fallback rows are closed, since an outcome exists, and nothing says whether that quarter is read at stage 2. Someone who has seen the first span would decide | `LOW` | Apply the rule once per bar source, from counts alone, before that source's first outcome. A quarter failing on trades is not a test block for stage 2. No date moves |
| FP-10 | `D-29`, after `D-27` | Venue chosen after sight of a result | `D-29` at 13:13 picks the venue and symbols the demonstration ran on, 51 minutes after `D-27` was recorded. `D-26` put that question earlier, on licence, funding history and cost. The demonstration ran on one venue, so no comparison of results existed, and the charter fixes the assets. **I find no selection on results.** The record does not say so | `LOW` | The new entry states, from the owner, that the result of `D-27` was no reason for `D-29` |

### 13.2 Does `D-27` stand as "not a trial"?

**No. It is replaced by a new entry, since entries are not rewritten.**

- **It was the first run.** I wrote that definition: "the first simulation of any strategy, control or placebo on any market data from any source. Synthetic engineering tests do not count." A fixed rule producing longs, shorts and a portfolio on real trades is a strategy for that sentence, and "not one of S01 to S10" is not an exception to it. So C-3 and C-5, due before the first run, were missed and not avoided. They are not waived. They stay due before the first `V0` run, and the record says they came late once.
- **"Not a trial" cannot be shown.** It rests on the rule being different and staying out of the candidates. No rule text, code, cost or output is on file, so both are `UNVERIFIED`, and I have not seen any of it. The plan's own sentence, that anything from that rule entering a candidate is a counted trial, cannot be applied until the rule is written down.
- **Counting costs almost nothing, so count it.** Two symbol runs in a family of its own, never selectable, under the plan's rule that a line over two symbols counts twice. By the rough `sqrt(2 ln N)` for the expected best, moving `N` from 104 to 106 changes it by about 0.2 percent.

**The new entry holds:** the rule's text, parameters and cost assumptions, and a code hash. The first and last run times in UTC. The 12 days. Each role that saw any output, and which agents did not. A hash of the outputs, with no prices. The sentence: "A run on market data, outside the candidate family, counted as two symbol runs. It came before C-3 and C-5." **The output stays sealed.** Opening it again is a read, logged the same day, and it is never shown beside a first-span view. If the rule's text cannot be produced, "a different rule" stays `UNVERIFIED` in every report that cites it.

**C-3 after this.** The limit is that the choice is made without sight of any strategy result. `RT` of 12 bp is already in C16 at `38d5907`, ahead of the 11:07 above, so it stands. Stop slippage has no value yet, so it will be set after the demonstration. It takes a basis outside any result, set by a role that did not see the output, or it says plainly that it was not.

### 13.3 What it does to the locked block

**It stays the locked block, with its dates, and it remains worth one read. It loses three things it cannot get back.**

**1. The claim of being untouched.** The plan's label, "read on 10 listed days (`D-27`)", is required on every report naming the block.

**2. Part of its sample.** The plan's arithmetic is right: 4 percent at 12 hours and 30 percent at 10 days. By strategy, from C18's `H_max`, by calendar and not measured:

| `H_max` | Strategies | Share of the block left out for the 10 days |
|---|---|---|
| 8 to 12 h | S06, S09, S01 at 15m | About 4% |
| 24 h | S01 at 30m, S08 | 5.5% |
| 3 d | S02, S05 at 1h | 11% |
| 4 d | S04 at 1h | 14% |
| 5 d | S07, S10 at 1h | 16% |
| 6 d | S05 at 4h | 19% |
| 7 d | S04 at 4h | 22% |
| 10 d | S03, S10 at 4h | 30% |

`CYCLE` adds about half a point, and the block's own end removes a further `H_max`, as it would have anyway. **This removal is sound.** The days were set by a vendor's free calendar, so leaving them out cannot depend on an outcome. It also leaves out the same stretch around each month's turn on long holds, so the kept dates are printed. Any minimum trade count in a gate applies after the removal and is not relaxed afterwards. **Do not add a second figure with those days included,** because that hands the final read a choice of two numbers.

**3. Blindness about the block as a whole, for whoever saw the demonstration.** This is the part exclusion does not reach. Ten first-of-month prices give the block's month-to-month path, so a viewer knows roughly which way all 365 days went and when. That bears on choosing a side, a risk limit or a regime rule, and it is not confined to the 10 days. These prices are public, and the people and models writing these documents may know that history anyway, from their own reading or training. So no rule here can promise that the market's path was unknown. **What the locked read can promise is narrower: no outcome of these rules on these dates was computed before it.**

**So the weight of a locked read now rests on the freeze.**

- A rule or constant shown by FP-03 to predate the demonstration, and unchanged since, reads the block with its full argument. That is the case the plan describes for S01 to S10.
- A value set later reads it on its stated basis. A first-span measurement or a document's reason is clean by that basis. A value a person chose after sight of the output carries the note. Today that means the `D-28` limits, and stop slippage unless section 13.2 is met.
- Anything drawn from the demonstration's rule is counted, and those days count as used.

**Do not move the block.** I agree with the plan. Earlier dates are just as public, and moving it costs a year of first span or four test quarters to avoid 10 days. The first span and the test blocks hold no demonstration day, so stage 1 is not touched by this, subject to the `D-18` list.

### 13.4 The rest of the plan

| Item | Ruling |
|---|---|
| **Dates chosen from coverage** | **Holds, and the words should change.** They come from the calendar, and coverage is applied to them afterwards, which is the safer order. "Set from coverage" claims more than was done, since the plan says coverage is unmeasured. The contract dates stay `UNVERIFIED` until `data-steward` measures them. The locked dates first appear in `3f0db56` at 11:46, possibly after the demonstration began, but they follow mechanically from the last full quarter and a length of 12 months, so I see no room for a result to steer them |
| **First span of 48 months** | **Holds.** The basis uses no outcome. I checked the scaling: at 48 of 18 months, S10 at 4h (8 to 24) and the low end of S05 (24) are below 30 rejected, and every other row clears it |
| **Failing-quarter rule** | **Holds.** It was declared before any coverage was read, from counts alone, for both symbols together. Dates move only at the head of the history, or in the fallback for too few test quarters, which closes at the first outcome. It does select against outage-heavy quarters, without looking at any outcome. A failed quarter is named in every report. FP-09 adds the second source |
| **One read rule** | **Holds as a rule,** and it answers N4: one global locked read, a definition of read, nothing extending. Needs FP-01, FP-07 and FP-08. A read by mistake being logged and excluded is right. My own re-audit probes on candles stay inside the first span |
| **What the owner may see** | **Holds, with FP-04 and FP-05.** First span only, every line, every label, with the counted lines kept in `N`. The trial count shown includes `D-27`'s two runs. The demonstration's output is not reopened beside it |
| **The `D-18` runs** | **The largest open item when written. Section 16 rules on the listing made since.** Configured starts of 2024-01-01 for candles and funding and 2026-06-01 for trades fall inside test and locked dates, and these are the same venue's files. The plan's rule is right: a listing by name before C-5, each such day excluded, and `BLOCKED` if a report over a stretch was seen. The listing must also say whether the `results` branch or any workflow artifact holds a benchmark from those runs, since the workflow publishes one and I cannot look without network. Its recheck of the reconciliation rule uses days those runs did not touch |
| **Expanding training, placebo calendar** | **Hold.** The charter item 11 sentence is still due with C-7 |
| **"A later change is a counted trial"** | Edits this review requires are dated entries. No outcome exists yet, so they add no trial. Once a `V0` outcome exists, the sentence applies as written |
| **Section 7 of the plan** | The states are right and the order is right. "A log entry for official candles" is answered by `D-31` in the same commit. Add the items of section 10 above: 0, 3a, 5a and 6a |
| **Re-audit conditions** | Condition 4 (N4): met in text, adoption in C18, C15, `GATE_SPEC.md` 8.2, 8.3, 8.6 and matrix 3.1 still due before the first `V0` run. Until then `GATE_SPEC.md` 8.2 still says 18 months and names the earlier source. Condition 5: the ruling holds and the sentence is due. Condition 7: met |
| **Section 7 of the feature re-audit, on this source** | Fold dates: this section. `RT`: declared, and the C9 floor follows it. Everything else there concerns flow, so **it falls due before stage 2 and does not hold back stage 1:** a registered venue list and its trigger (M14), the source card, poll capacity, a numeric R6 for `CYCLE`, the spot-only text and the funding inputs it removed, and the restated frequencies. That audit stays open |

## 14. The two-stage plan in `D-31`

**Verdict: `PASS WITH CONDITIONS`.** I agree with both parts. The first stage reads only the first span, and a quarter read on candles is `EXPLORATORY` for the stage on bars from trades. The second follows from ruling 7 condition 6: boundaries move prices and volume between adjacent bars, so candle bars and trade bars are not one input. The first follows from the second, because a test quarter read on candles would be spent before the bars it should test exist. On the first span the label changes nothing, since that span is in-sample at both stages. **Its only force is on test quarters, and that is why they stay closed.**

Stage 1 also cannot produce candidates for six of the eight. They cannot select without `C-LATE`, and no `CYCLE` run may start. So what they show is description, and only S01 and S06 could even be frozen for a block at this stage.

**Conditions.**

| # | Condition | Scenario it stops |
|---|---|---|
| 1 | **`EXPLORATORY` reaches all ten strategies and every flow line,** and not only the eight that ran | The owner opens 2024-Q1 on candles and sees eight strategies. S07 and a flow recipe, written or frozen after that, are then chosen knowing how that quarter went. `GATE_SPEC.md` 8.6 says the same of `.R` and `.L` |
| 2 | **The guard stays at 2023-12-31 through all of stage 1.** Opening a quarter on candles takes the written route, and the request says it spends that quarter for stage 2 | "The owner's wish to see the portfolio soon" is the pressure this holds against. I agree with the plan's recommendation to open nothing until stage 2 |
| 3 | **Stage 2 runs the declared grid in full and selects again from the first span,** with stage 1's lines in `N`. Narrowing the grid to what looked good is a selection on stage 1, logged and counted | A grid of 52 lines shrinks to 10 favourites, and `N` is counted from 10 |
| 4 | **Flow is compared only with `V0` on the same bars.** CLAUDE.md rule 5's baseline at stage 2 is `V0` on bars from trades | `VE` on trade bars against `V0` on candles credits flow with the boundary difference `08_DATA_CENTER.md` section 4 describes |
| 5 | **Stage 2's constants are computed by an estimator declared before stage 1's first outcome.** That covers the allowance, `boundary_window_ms` and `max_quiet_s`, with a value computed later on the first span | Those values decide which minutes are flagged. Chosen freely after the first span's results are seen, they can drop the bars behind a bad stretch, and this is inside the span so nothing else would catch it |
| 6 | **Any rule or constant that differs between stages is a counted trial,** apart from a list written before stage 2's first run of what follows from the bar source alone | A stage 2 "new document version" carries a tuned constant in with the boundary change |
| 7 | **`D-31`'s "no `aggTrades`" covers strategy inputs.** Condition 2 of ruling 7 needs them on sample days, first span only, with a flag as the only output | Otherwise the stage either skips the check silently or reads trades without a record. If it is not run, `IDEAL` is not reported |
| 8 | **If stage 2 is dropped, that is a new decision.** `D-12` stands until then. Stage 1's figures are never presented as results on bars from trades | The size of the trades files is unmeasured, so this is a real path |

## 15. Condition 2 of ruling 7: the exact form

**Do not use `reconcile_official._walk` for this test. The wording that said to was mine, and condition 2 now points here.**

The walk asks whether a day's difference can be explained by rows near a boundary. Condition 2 asks whether a candle holds a later print. On generated fills only, with 8 quiet days and 3 busy days:

| Planted on the tested day | This form | `_walk` as written |
|---|---|---|
| Nothing, quiet days, rows running up to 400 ms | Passes 8 of 8 | Passes 2 of 8. It fails on a row longer than its 250 ms window, which is not an after-close print |
| Nothing, busy days | Passes 3 of 3 | Passes 3 of 3 |
| The next 1 or 20 fills moved into the first candle, or into a midday candle | Fails 11 of 11 in each case | Fails 11 of 11 in each case |
| Every candle reaches 50 ms past its close | Fails 11 of 11 | Fails 11 of 11 |
| The first candle holds one extra fill, never given back | Fails 8 of 11 | **Passes 5 of 11** |
| Candles built by row stamp, so a row's later fills sit in the earlier candle | `INCONCLUSIVE` 11 of 11 | **Passes 11 of 11** |

**`data-steward`'s warning is right about the form, and one part is narrower than it reads.** A print given back in the next candle was caught in every run, because the inflated carry pushes later readings over the walk's upper bound. That catch comes through a side check on a placeholder window. What really passes is an excess that is never given back, and candles built by row stamp, which is the case condition 2 exists to exclude. `eps` at today's 0.000001 sits far below one fill in my runs, whose step of 0.001 is my own choice. So that route is narrow today, but it is a configuration key, and this test has no such key.

**The form.** For each sample day `D`, each symbol, and each of volume, taker-buy volume and fill count. In integers, with no tolerance, no window and nothing fitted. It is new code, apart from `_walk`.

1. **The readings.** `S(b)` sums `D`'s rows stamped in `[midnight, b)`, so a row stamped exactly at `b` is after it. `K(b)` sums the candles closing at or before `b`. `d(b) = S(b) - K(b)`.
2. **Zero points.** `b` is a zero point if the last row stamped before it on `D` is one fill (`first_trade_id = last_trade_id`). Rows run one after another, so nothing is still printing across `b`, and `d(b)` is exactly minus the carry across midnight.
3. **Every zero point reads the same.** Call that value `d0`. With fewer than 2 zero points the day is `INCONCLUSIVE`. Different values fail the day.
4. **`d(b) >= d0` at all 1,440 boundaries.** This is the excess: candles have counted more than had been stamped before the close. One failure fails the day.
5. **The carry is computed, then bounded.** `-d0` must lie between 0 and the previous file's last row: that row's amount in this column if it has more than one fill, and 0 if it has one. That row is all the previous day supplies. Outside this range fails the day.
6. **Prices.** A traded candle's close equals the price of the last row stamped before its close.
7. **It must have been able to see a split.** `d(b) > d0` must occur somewhere on the day, or the day is `INCONCLUSIVE`. Candles built by row stamp read `d(b) = d0` everywhere, and they pass steps 3 to 6 while holding later fills.

**A day's first boundary is not special.** `d0` comes from zero points and never from the first reading, so nothing is absorbed. An excess there reads below `d0` and fails step 4. One that is never given back moves `d0` itself, and step 5 catches it.

**The result.** One of `PASS`, `FAIL` or `INCONCLUSIVE` per symbol and day, with the failing step as a fixed code and no quantity. Condition 2 is shown for a symbol only if no day fails, at least 43 of the 48 days `PASS`, and every quarter has a `PASS` day. Otherwise `IDEAL` is not reported, and nothing else stops. After a failure, a changed form is a new dated decision and does not rerun quietly. The planted cases above become its tests, on generated fills.

**Its assumptions fail safe.** It assumes a row is stamped at its first fill and that rows do not overlap. With stamps at the last fill, 4 of 4 clean days failed in my probe. Overlapping rows should fail step 3 too, which is reasoning and not a probe. Either way the cost is `IDEAL`, and no false pass.

**Limits.**

- An excess in the first candle that is never given back, and no larger than the previous file's last row, cannot be told from a carry. That is the 3 of 11 above.
- A candle that counts some rows by stamp and others by fill time passes, since step 7 needs one split a day. Aggregate rows cannot separate these.
- **A per-fill file would close both.** If the venue publishes one for these dates, which is from memory and `UNVERIFIED`, a listing settles it. The test is then that each candle's volume, taker-buy volume and count equal its own minute's fills by each fill's own stamp, exactly, and its close equals the last fill's price. That has no carry, no zero points and no first-boundary question. **If the listing shows it, use it on the same days,** decided from the listing and sizes before anything is fetched. The size may exceed the 3,109 MB declared, which is `UNVERIFIED`.

**The sample.** I accept the 15ths: they come from the calendar, with no replacements. A sample says nothing direct about other days, and `data-steward` says so about stressed ones. Before a test block opens, the same test runs on its 15ths in the check-only root, with flags alone leaving it, because `IDEAL` on that block rests on this property.

## 16. The `D-18` listing and the undated 137 MB

I read `docs/reviews/data/binance_vision_coverage_2026-11-05.md` at `aac99e2`. Its figures are its author's. I checked its arithmetic and that git here shows no `results` ref, and I reran no listing.

**The plan's verdict stays `PASS WITH CONDITIONS`. `BLOCKED` is not met on this evidence, and for the undated part it is not excluded.**

**The measured part closes most of what I called the largest open item.** 30 dates and one funding month, all after the locked block, no results branch, no artifact, and no pipeline run on the host. I accept the first two rows of section 3.4. The reconciliation table asked about in its section 3.1 **is a read of those days,** since a conclusion from it went into `08_DATA_CENTER.md` section 4. It touches no block.

**I do not read the 137 MB as small.** Section 3.2's "about 5 days" holds only for a run of the same shape as the measured one. The same document gives 124.40 MB for every candle file from 2024-01 to 2026-09 on both symbols. The plan records configured starts of 2024-01-01 for candles and funding at that time, and a light ingest exists today, though whether it did then is `UNVERIFIED`. **So 137 MB is about the size of a candles-and-funding run across every test and locked date.** I do not say that happened. Size cannot tell these apart, and it may equally be a counting difference.

**A download alone is still not a read.** Under plan section 3 this matters only if a value from those bytes reached a person, an agent, a report or a log. That is the same gap section 3.1 leaves open: a report over a root later replaced.

**What to do, in order.**

1. **Search the session logs by filter, before C-5.** `data-steward` was right not to read them, since they can hold market values. A script can print only dated file names, `--start` and `--end` values, dataset names and byte totals, with nobody reading a log line. That stays inside "not a read". Also ask who ran it.
2. **Check the count.** Section 3 keeps the other venue's files in `dl_sample` outside the Binance count and gives no size for them. If `D-18`'s 953 MB included them, and they come to about 137 MB, the gap closes with no Binance date at all. This is a guess, and names and sizes settle it.
3. **Apply the plan's rule to what is found.** A date in a test or locked block joins plan section 4 and is excluded. A report seen over a stretch makes the plan `BLOCKED`.
4. **If neither settles it,** the third row of section 3.4 stays `UNVERIFIED`, with this treatment in place of "No date can be excluded until one is named":

   "Undated. A download is not a read, and whether any value left is unknown. Stage 1 is unaffected. Every written request to open a test block or the locked block states this, and every report naming those blocks says it."

   C-5 may then proceed, because stage 1 reads only the first span. An exclusion cannot help, since no date is named. So the owner decides on each later read with this in front of them.

**Existence checks.** Another venue's 2025-06-01 falls on a test-block date, and it is recorded as existence only. If its contents were opened, it is a read of that date on that venue and joins plan section 4 like any other. I can take that no further, and it stays `UNVERIFIED`.

