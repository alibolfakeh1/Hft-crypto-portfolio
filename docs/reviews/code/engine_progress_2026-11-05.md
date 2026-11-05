# Engine progress note

Date: 2026-11-05. Author: `developer`. A working note, not a review. No reviewer has read this code and no verdict is
claimed. Everything here ran on generated data only. Nothing here says whether any strategy would make money.

## Done

| Item | State |
|---|---|
| Simulator in `IDEAL-1M`, with the timing contract in code | Runs. `src/hft_crypto/engine/` |
| `V0` of S01 to S06, S09 and S10 | Coded. Each matches its document's worked table |
| `V0` of S07 and S08 | Coded for bars from trades. On candles they give no result and log why. `T0-APPROX` is not built |
| `V0S` of all ten, under C13 and section 7.10 | A control with its own stream and its own outputs, beside `V0` and never in the portfolio |
| All 60 runs for 64 lines, default first, portfolio line as an input (`D-35`) | Runs. Nothing is ranked or picked. On market data a portfolio line off the default is refused |
| Date range checked against the fold plan's opened blocks and its read days | Runs. A run opens no file outside its range, and a range touching a read day it does not list is refused |
| Setups reaching an unopened date or a read day | Left out, never simulated, counted, with the strategy flat across them (FP-06, FP-07) |
| Risk per trade, leverage cap, gross cap | Required inputs, printed on every output. `D-39` values, stated as such in `configs/engine.toml` |
| JSON outputs, trial registry, C12 declared costs | Run. S08 counts as two lines per run on trades, and S07 and S08 as none on candles. `D-32`'s 2 runs are printed beside the count |
| C15 placebos | Run with `--placebo`. `src/hft_crypto/engine/placebo.py`, `placebo.json`, one row per strategy and symbol |
| Command | `python -m hft_crypto.engine` |

## The engine review and the author's rulings

From `docs/reviews/code/engine_review_2026-11-05.md` at `cf1880f`, and the last two sections of
`docs/01_strategies/CHANGES_2026-11-04.md`. Tests are in `tests/engine/test_review_fixes.py` unless named. Each
was shown to fail with its fix reverted in a copy of the package. The mutation section below lists them.

| Item | What changed | Test |
|---|---|---|
| E-01 | `engine/funding.py` finds each settlement with no rate from the file's own cadence. A position open across one logs `DATA_GAP`, books nothing and carries the notional as unresolved, on its trade row and in its stream's figures. The count is in the manifest and the header, and the note changes. **Not refused,** because C17 and C10 say log and report. A refusal is one line if wanted | `test_e01_*` |
| E-02 | Every settlement in `(fill, this moment]` is charged once, so one inside a hole falls at the first row after it. An exit at an open pays what fell before that open. **Also:** a stop gapped through at an open fills there, so it now pays nothing later in that minute, as a pending exit already did | `test_e02_*` |
| E-03 | A trade headlined as stopped at a gap keeps only charges up to the gap, and the choice of the worse way uses the same | `test_e03_*` |
| E-04 | `MinuteTape` emits a `gap` bar for each empty bucket on the grid. The first bar after one has no true range. Time stops in bars now count such a bar | `test_e04_*` |
| E-05 | Ruled at `3b54087`: one check at the stated `n`, and on a bar with no price it falls at the next close that has one. S03's stall, and S10's stall and thesis check | `test_e05_*` |
| E-06 | S04: a zone cannot trade on its birth bar | `test_e06_*` |
| E-07 | S05: the bar that opens the retest counts towards `mid` | `test_e07_*` |
| E-08 | S06: a swing pool is watched from confirmation, and a close or a sweep during its 8-bar wait consumes it. It can still give no trade in that wait | `test_e08_*` |
| E-09 | S06: the setup's opposing pools are stored, so a roll or new pool at the close of `n = 1` recomputes `T2` | `test_e09_*` |
| E-10 | S02: one trade per level per UTC day of `t_k`, with the bar closing at 24:00 in the day it ends | `test_e10_*` |
| E-11 | The break-even multiple is `(gross - funding) / costs` | `test_e11_*` |
| E-12 | `unrealised_pnl` and `open_r` value only what is still open | `test_e12_*` |
| E-13 | A refused trade has no exit reason on the capped row. A stop is named for the one in force, and not the newest planned | `test_e13_*` |
| E-14 | `lines_counted` on each registry and `trials.json` row: S08 two on trades, S07 and S08 none on candles, so 60 runs for 64 lines and 52 on candles | `tests/engine/test_placebo.py::test_a_run_of_all_ten*`, `test_the_registry_counts*` |
| E-15 | A sequence ends when its setup is sent, and `NO_RETEST` is logged only if no retest came. On `weekly_levels` lines this also means the next trade on a level needs a new break | `test_e15_*` |
| E-16 | S02's retest needs no `SRV` of its own. **C5, ruled:** the pick among objects on one bar is final in S02, S04 and S05. S06 was already final within a side, so it needs no change, and a test holds that. S08's two triggers come one per side and are not a pick the documents name, so it is unchanged | `test_e16_*` |
| E-17 | `CLV` is rounded to 9 places, on both sides of the mirror. Ruled fine | `test_e17_*` |
| S01, `3b54087` | A touch needs the level's role at that bar. A level first seen above the price has no touch until price holds above it for 4 closes and comes back | `test_s01_*` |
| S03, `3b54087` | No setup when the latest swing as of `t_k` was confirmed at `t_k`, and no earlier swing stands in. The recompute is unchanged | `test_s03_*` |
| S05, `3b54087` | The retest opens only on a bar after the one completing travel | `test_s05_*` |
| S06 linger, `47c0dc8` | Takes E-05's fallback. Only closes that exist count among the six, and a check whose `n` has no trade falls at the next close with one | `tests/engine/test_audit_more.py::test_s06_linger_*` |
| S09 `n = 4`, `47c0dc8` | Takes the fallback. A bar with no trade reads no carried close, and the check falls once at the next close with one | `tests/engine/test_audit_more.py::test_s09_the_n_4_check_*` |
| S07, `47c0dc8` | A bar with no trade neither counts as one of the two closes below `A0` nor breaks a run of two | `tests/engine/test_audit_more.py::test_s07_*` |
| S05, `47c0dc8` | A bar with no trade cannot open the retest, and still counts in the window and the death count | `tests/engine/test_audit_more.py::test_s05_a_bar_with_no_trade_*` |
| Confirmed as coded | S04's search, S09's schedule step, S02 `n = 6`, S04 `n = 3`, S05 `n = 9`, S09 `n = 2` and its `T2` raise, time stops, close-based exits, and the other C15 choices | None needed |
| Review's other notes | `equity_timeframe_minutes` is in the header. `not_built` lists the closed-trade equity series, the monthly and rolling tables, confidence intervals and S01's `confluence` log | `tests/engine/test_placebo.py::test_the_header_names_*` |

Each `47c0dc8` fix can change a trade list, so each has a test on a bar with no trade at the stated `n`, and each
was shown failing with its fix reverted.

## The leak audit's list

From the engine leak audit and the candle-path re-audit at `d5b5a3b`, in the order asked.

| Item | What changed | Test |
|---|---|---|
| EN-01 | The gross cap's `_open_qty` and `_finished_by` read `as_recorded_legs`, what was held, and not the C2 headline | `tests/engine/test_audit_fixes.py::test_en01_a_later_entry_s_size_does_not_rest_on_prices_after_its_decision`, two worlds that differ only after the decision |
| RA-01 | `data/derive.py` excludes a candle day only when it is a hole: the row giving its open or close is missing or failed. The day's detail states its `flagged_minutes` and `hole`. `reports/report.py` no longer gates on `USABLE_DAY_STATUSES`: it asks `day_is_usable`, so `warn` stays as an alert and gates nothing, and the stats print `minutes_flagged_in_days_used` | `tests/data/test_candle_path.py::test_ra01_*`, five tests, the auditor's case first |
| EN-02 | Covered by E-02: a settlement inside missing rows, a whole day or a whole month falls at the first row after the hole | `tests/engine/test_audit_fixes.py::test_en02_*` |
| EN-06 | An entry whose first allowed fill minute is missing, or flagged by a flag known by that minute's close plus the delay, is not filled. It logs `ENTRY_ACROSS_GAP`, is counted, and is recorded as a refused entry. A minute proved empty is not a hole, so the first print after it fills | `tests/engine/test_audit_fixes.py::test_en06_*`, five tests |
| EN-04 | `tests/leak/test_whole_run_cuts.py`: cuts at setups spread over the whole run and at random closes, truncated and perturbed, for every strategy on two seeds or more, the default line and one other, on candle-shaped rows with missing and failed rows and on bars from trades with skipped ids. Every bar of every decision timeframe is compared up to each cut. The back-door filter stays as a permanent self-test. `tests/leak/test_named_leaks.py` has one named test per survivor in section 5's second table, except the two the audit calls unreachable. Funding is read to `t_cut` with `t_cut` clearly before `t_dec`, `as_of_bars` is tested at `t + 60 s`, and S09's strict rule has three tests | See the notes on EN-04 below |
| RA-02 | `stopped` holds only `none` or `fetch_refused`. A stopped run holds no quarter, day or symbol, so it decides nothing. The same for `candle_check.json` | `tests/data/test_date_guard.py::test_ra02_*` |
| EN-07 | `configs/engine.toml` states `D-39` as the basis of the risk limits. A market run whose `portfolio_line` differs from its `default_line` is refused. Lines are counted through `lines_on`, and the count prints `D-32`'s 2 symbol runs beside it | `tests/engine/test_audit_more.py::test_en07_*`, `tests/engine/test_placebo.py` count test |
| `V0S` | Built. See below | `tests/engine/test_audit_more.py::test_v0s_*`, `tests/engine/test_placebo.py::test_v0s_has_its_own_rows_*` |
| EN-03 | A refused entry reserves its room in the gross cap from its decision until the open of the minute that refused it, scaled like any entry | `tests/engine/test_audit_fixes.py::test_en03_*`, three tests |
| EN-05 | `engine/fold_plan.py` holds the plan's read days, `READ_DAYS`. A range touching one is refused unless the configuration lists it | `tests/engine/test_audit_more.py::test_en05_*` |
| 18.2 | S01 and S06 count the setups lost to an `ATRD` restart, by a dry run that leaves no note behind, and S09 the ranges lost. Each row prints them as `atrd_restart`, with the closes the restart covered | `tests/engine/test_audit_more.py::test_18_2_*` |
| 18.3 | A test or locked block carries `D-38`'s sentence beside its `D-27` label | `tests/engine/test_audit_more.py::test_18_3_*` |
| C15 | An injected-leak batch on the placebo code. See the mutation section | `tests/leak/test_placebo_leak.py`, `tests/engine/test_placebo.py` |

**Notes on EN-04.**

- **A test bug, found and fixed.** The cut harness indexed the last setup of a run that had none, and so failed for
  S05 and S09 on an `IndexError`. The earlier mutation run counted that as a kill for both. Those two kills were
  false, and the rerun below replaces them.
- **S09 needed its holes moved.** S09 fits its profile once a quarter and fails closed on any flagged hour in the
  window, so with holes in the first quarter it never traded. Its markets put the holes and the failed rows after
  the 2000-04-01 fit. It then gives 2 to 4 setups a line.
- **S05 reaches one setup a run at most.** Of seeds 1 to 30 over 230 days with these holes, none gave more than one
  setup on a line, and its second line gave none on any. It runs on three seeds that give one each on the default
  line. A filter from the third setup cannot act on it. A dropped setup that is a run's only one leaves no event for
  a cut to land on, so for S05 the self-test reads the next bar into the stop from the first setup on. **A filter
  from the third setup is not shown for S05.**
- **One field is compared under a stated exception.** `late_gap` on a bar that is already a gap differs between a
  build at the cut and the full build. A build at the cut flags the minutes after its last trade at their own close,
  and the full build flags the same minutes when the trade that shows the skip arrives. `late_gap` resets `ATR` and
  makes a bar incomplete, and a gap bar has both already, so there it changes nothing, and nothing outside the tape
  reads it. It is compared as it is on every bar that is not a gap, and `complete`, `atr`, `atr_last` and `tr` are
  compared on every bar. `test_a_late_gap_on_a_bar_with_no_gap_is_compared` holds the exception to that. **For
  `leak-auditor`.**
- **Cost.** In the final whole-suite run, S06's cut test took 1,048 s and its self-test 273 s, mostly in the probe
  that writes S06's registers at every close. The whole suite took 3,661 s.

## `V0S` as built

`src/hft_crypto/strategies/v0s.py`, `src/hft_crypto/reports/v0s.py`, and `simulate_v0s` in
`src/hft_crypto/engine/run.py`.

- The same setups as `V0`, from the same strategy code, with one fixed target at `fill + m * R`, set at the fill, and
  no update of the stop or the target of any kind. `m` is the strategy's own.
- It holds `H` bars, counting `n`, so a bar with no trade counts and its close is not read. It closes at the next
  open. S09's `H` is the hard flat of the schedule it entered with.
- It is its own stream under C11, so a one-trade rule counts its own trades.
- `v0s.json` has a row per strategy and symbol beside `V0`'s figures, with the setups taken in both streams and those
  taken in one only. `v0s_trades.json` has its trades. It is never in the portfolio. Each stream is a control row in
  the registry, with no line counted.
- **A bug of my own, found and fixed.** The registry counted a C15 reading from any control row on market data, so
  each `V0S` run would have counted as one. Only a row with a draw counts now.
  `tests/engine/test_placebo.py::test_a_v0s_control_is_no_placebo_reading` failed before the fix.
- It runs beside every line a run holds, so an all-lines run makes 120 `V0S` streams beside its 120 `V0` streams.

## Found by the whole suite

A first whole-suite run found six failures, all from my own changes, in tests I had not rerun. It was stopped and
run again on the fixed code: 1,906 passed and 2 skipped, both because creating a symlink needs a privilege on this
machine.

- `tests/data/test_safety.py` reads any `method=` keyword in the source as an HTTP method. The placebo plan had a field
  of that name, so it is now `swap`. The output key in `placebo.json` is still `method`.
- Four tests in `tests/engine/test_command.py` predated `V0S` and `D-39`: the registry now holds a `V0S` control row
  beside each `V0` row, `not_built` no longer names `V0S`, and the market configuration's risk state is `declared`.
  Two tests in `tests/engine/test_placebo.py` predated `V0S` the same way. Each now states what it checks.
- EN-05's check ran before the check on opened dates, so a range outside the span that touched 2026-01-01 was refused
  for the read day. The opened dates are now checked first, and both refusals stand.

## C15 as built

200 draws, declared in `configs/engine*.toml`. A market configuration may not state another count. Each draw runs
through the real simulator with the real strategy's rules, and one thing swapped, as C15 and section 10 of each
document say. The seed of a draw is the first 8 bytes, big-endian, of SHA-256 of
`C15|<strategy>|<symbol>|<line>|<draw>`. Each row prints mean `Result_B` per trade, gross and net at 1x, and the
real line's gross and net rank, with the sentence on what stays real beside the rank.

| Strategies | What a draw swaps |
|---|---|
| S01, S02 | Each period's pivot set, drawn whole, at the first close that can read the period. R3 and S3 are in the set |
| S04 | Each zone at its birth, by side. A stack zone and an entry zone from one base are one band |
| S05 | Each flip at its real break, by side, and each entry zone's `prox` read as a target |
| S06 | A day's or week's low and high, drawn whole. Each swing alone, by kind |
| S08, on trades | Each profile's whole band, at the first close that can read it, so `POC` keeps its place |
| S03, S10 | The entry bars, over bars passing the non-signal filters, with the real setups' counts per quarter and side |
| S09 | Each day's whole schedule, by a shift from 1 to 23 hours |
| S07, on trades | The major swing list, by bars drawn over the quarter, with the real count per quarter and side |

Calendar quarters are the blocks. A level placebo has nothing to draw in the first quarter, and its row says so.
Nothing born on a read day enters a pool. A placebo run is a logged read, and every draw is a control row in the
registry.

## C15 choices, confirmed as coded at `47c0dc8`

| Choice | Why |
|---|---|
| A distance is measured from `ATR` on the decision timeframe, at the decision close at the knowable time, for every object including S06's 1h swings | C15 says "`ATR` units" and does not name a timeframe. Every rule these objects feed uses that `ATR` |
| A band's distance is its near edge: `prox` for a zone, `top` for a flip. S08's is the band's middle, as it has no near edge | C15 says a band keeps its width and does not say which point the distance is from |
| An object with `ATR` undefined at its birth gives no distance, and no placebo object | C3 |
| A quarter is compared only if every kind born in it has an earlier distance | The stricter reading, decided after the run, so no draw reads it |
| S04's kinds are demand and supply, for both of its lists | C15 says "a zone or flip side" |
| A draw takes the side with fewer eligible bars first | C15 says without replacement and also fixes both counts. This only matters when bars are scarce |
| S03's and S10's eligible bars must be complete, and must not reach the range's end or a read day | A setup there is lost or left out anyway, and the real count leaves those out too |
| S10's eligible bars do not need `SRV` and ignore the re-arm rule | Section 10 names only the `CF` count and `BoxH` limit |
| S03's filter d on a short uses `SH_last`, and a bar passes for one side and not the other | The mirror in section 5 |
| Rank 1 is above every draw, and a tie counts against the real line. A draw with no trade has no mean and is counted beside the rank | C15 says "rank" and no more |
| S05's swings, S07's minor list and S08's developing profile stay real | Ruled at `47c0dc8`. The sentence on what stays real is printed beside the rank |

## Mutation checks

Each fix was reverted, or each leak injected, in a copy of the package, and the named tests were run against it. A
run that only errors is not counted as a kill. Both batches ran on the final code.

| Batch | Mutants | Killed | Survived |
|---|---|---|---|
| The review's items E-01 to E-17, the `3b54087` rulings, and the C15 choices | 52 | 52 | 0 |
| The leak audit's list, the `47c0dc8` fixes, `V0S`, the auditor's survivors, the whole-run back door for each strategy, and C15's injected leaks | 70 | 69 | 1 |

**The survivor** is a filter from the third setup injected into S05. No generated S05 run reaches a third setup, so
it cannot act, as noted under EN-04. The next bar read into S05's stop from its first setup is killed.

**C15's injected leaks, all killed:** a draw reaching its own and later quarters, a placebo keeping the real level,
births on a read day entering the pool, a draw ignoring its hashed seed, entries ignoring the non-signal filters, and
the quarter table ignoring the first quarter.

**Earlier runs held false kills, and are replaced by these.** The first pass of the audit batch counted a run that
only errored as a kill: four mutants whose tests need the end-to-end fixture, which could not find its configuration
from a copy of the package, and S05's and S09's whole-run cuts, which failed on the harness's `IndexError`. The
review batch's first pass ran without the copy's version and configuration settings. All were rerun with both set,
and with errors told apart from failures. One EN-06 mutant's text did not match the code in the first pass, and was
corrected. Three mutants that survived the first audit pass are killed by stronger tests: EN-03's whole notional,
the 18.2 dry run's notes, and the S03 scan's filters. Births on a read day survived until
`test_no_distance_is_taken_from_a_read_day` was added. One review mutant, S05's travel bar, had to be rewritten to
the code as the `47c0dc8` fix left it, and was then killed.

## Run time and memory

On generated data, 4 years from 2000-01-03 to 2004-01-02, two symbols, 1m candles (`T0`), on a 6-core desktop.
Generated data, so these describe the code and no market. Each was measured once. The two runs of the final code
shared the machine with the test suite, so their wall times are upper figures. CPU time is the parent process's own.

| Run | Wall | CPU | Peak memory | Output |
|---|---|---|---|---|
| All 60 runs per symbol, with `V0S` beside each | 366 s | 339 s | 3.91 GB | 120 `V0` streams, 9,659 trades, and 120 `V0S` streams |
| The same at `3b54087`, before `V0S`, measured alone | 268 s | 219 s | 3.98 GB | 120 streams, 9,659 trades |
| 200 C15 draws of each default line, with its real and `V0S` runs, 5 worker processes, on a driftless root | 1,191 s | 142 s in the parent | 3.24 GB in the parent, 0.38 GB at most per worker, 4.80 GB at most for all at once | 16 placebo rows that ran and 4 not run, as S07 and S08 need trades |
| The same earlier today, before the audit's fixes, 8 worker processes, measured alone | 1,577 s | 116 s in the parent | 3.38 GB in the parent, 0.38 GB per worker, 4.59 GB at once | The same 20 rows |

The candle stage on market data reads the same number of 1m rows for the same span, so these scale with the span's
length. S07 and S08 need trades, which are far larger, and were not timed.

**The driftless check.** On a generated path with no drift, the real line should not stand out among its draws.
Its gross rank among 200 ran from 23 to 185 over the 16 rows, and none fell in the top or bottom 10. The final
code's 20 rows are identical, draw by draw, to the earlier run with 8 workers, so neither the fixes since, on this
data, nor the worker count changed any draw.

On this generated data the audit's fixes and the `47c0dc8` rulings change no trade, since it has no hole and every
minute trades: the 4-year run gives the same trades and events as at `3b54087`. Against the code as reviewed at
`cf1880f`, the default lines changed in trade count only where the review's fixes reach: S01 221 to 315 on one
symbol and 256 to 359 on the other, S03 2 fewer on each, S04 1 fewer on one, and S06 284 to 270 and 302 to 278.

## Not built

| Item | Why |
|---|---|
| S07's `AVERAGE-PRICE` and S10's unconditional breakout | Named extras in section 10, outside the 200 draws asked for |
| C18 selection for S01 and S06 | Left out, as the brief allows. No line is picked anywhere |
| C14 counterfactuals, `NO_RETEST` counterfactual, G5 target stress, netted portfolio, deflated Sharpe | Listed in `run.json` under `not_built` |

## Open with other owners

| Item | Owner |
|---|---|
| The `late_gap` exception in the whole-run cut test, and S05's back door read into the stop rather than a filter from the third setup | `leak-auditor` |
| E-01 logs and reports a settlement with no rate and does not refuse the run | `strategy-architect`, `leak-auditor` |
| Section 18.1's notes on a locked read and on every locked portfolio figure are not printed. No locked block can be run yet, and they were not on the list asked for | `project-manager`, `leak-auditor` |
| S06's whole-run cut test takes about 17 minutes. Its probe could store registers only at the closes a cut needs | `python-reviewer` |
| The trade path still gates a day on its status (F-04). RA-01 changed the candle path only, as the re-audit asked. The trade path is stage 2 | `leak-auditor`, `project-manager` |
| `synthetic.py` builds its generated root with a 250 ms candle allowance, and `pipeline.toml` holds 10000 for the market. The engine reads whichever the root's source states, and holds no copy | `developer` of the data layer |
| The reader leaves the next day's part shut for bars on a midnight cut, but trades and funding still read the part named by the cut's date. So a range ending before the last opened date gives up its last minute. A range ending on that date, such as the first span, reads it. No position feels this, because a setup reaching the range's end is left out under FP-07 | `developer` of the data layer |
