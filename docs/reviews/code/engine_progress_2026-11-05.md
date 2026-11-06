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

## Fixes after the rechecks at `1c2dc23`

Author: `developer`. From the code recheck (`engine_recheck_2026-11-05.md`, R-01, R-02 and section 8), the leak re-audit at the
top of `docs/reviews/leak/engine_2026-11-05.md` (item 0 and section 2), section 17.6 of the data-center leak recheck, the coverage
plan, and the coordinator's items 8 and 9 from `docs/reviews/data/venue_facts_2026-11-05.md` and the C16 and C7 text at `ecc5e49`.
Working tree only, not committed. Generated data only, and no test touches a network. No verdict is claimed.

| # | Item | What changed | Files | Tests added | What each test kills |
|---|---|---|---|---|---|
| 1 | Funding reaches net | Tests only | none | `tests/engine/test_recheck_fixes.py`: `test_a_funding_charge_reaches_net_through_the_booked_trade` and `..._through_every_row`, each for a long and a short, a positive and a negative rate. A real simulator run with no fee or slippage, so gross minus net is the funding alone, by hand: 10 units, a 0.1% settlement at a mark of 100, so 1.00 | Booked net without funding. A cash event's net without funding, which only the equity curve reads. A booked trade with its charges dropped. Rows that add funding back to net. A trade row that adds it back. Cost lines without funding |
| 2 | R-01 | A stretch counts missing settlements only when the rows on both sides state the same interval. A stretch whose rows disagree names nothing and is logged as `FUNDING_INTERVAL_CHANGED` in the manifest (`funding_interval_changes`, with both times and both intervals), and the funding note in every header says how many there are and that a position across one may owe a settlement that is not counted. Nothing reads which way the column points | `engine/funding.py`, `engine/simulator.py` (`FundingIntervalChange`, a field of `SymbolData`), `engine/run.py` | `test_r01_a_lengthening_interval_invents_no_settlement`, `test_r01_a_shortening_interval_with_a_row_missing_is_logged_not_hidden`, `test_r01_rows_that_agree_still_name_their_missing_settlements`, `test_r01_the_logged_stretch_reaches_the_manifest_and_the_note` | The old cadence from the row before. No stretch logged. The manifest dropping the log. Agreeing rows naming nothing. The note silent |
| 3 | Coverage check | A 429 stops at once, as 403 and 451 do, in `HttpFetcher`, so for every caller. A 404 on a listed file and a checksum mismatch, or a sidecar that cannot be read, stop the run instead of failing a quarter. A `FetchError` carries one fixed word, and the output has a new key, `stop_reason`: `none` when the run did not stop, and otherwise one of the eight words, held by the schema. A stopped document still holds no quarter. `code_version` already prints `<version>+<12 hex>`, so only a test was added | `data/fetch.py`, `data/coverage.py`, `tests/helpers.py` (the fake fetcher's size refusal says `size_limit`) | In `tests/data/test_date_guard.py`: `test_a_404_on_a_listed_file_stops_the_run_and_fails_no_quarter`, `test_nothing_published_stops_at_the_first_file`, `test_a_checksum_mismatch_stops_the_run_and_the_file_is_never_parsed` (two cases), `test_each_word_a_fetch_can_stop_on_reaches_the_document_and_nothing_else`, `test_a_complete_run_says_no_stop_reason`, `test_the_document_names_its_commit_by_12_hex_characters`, `test_17_6_a_stop_reason_is_one_word_of_a_fixed_list`, `test_17_6_a_stop_reason_off_the_list_or_on_a_run_that_did_not_stop_is_refused`. In `tests/data/test_source_switches.py`, 429 joins the refusal test, and each broken response and the size cap check their word | 429 retried. 404 failing its quarter. A mismatch failing its quarter. The schema not holding the word. The word not written. A timeout read as `connection` |
| 4 | S05's coverage | One long driftless market of candles for S05, seed 10 over 600 days, built a minute at a time, with volume growing with the square of each minute's move so a break can carry the volume S05 asks for. It gives 4 setups on the default line. It comes first in S05's markets. The third-setup back door now runs on S05 too, and the older next-bar read into the stop stays as its own test. **The harness now writes registers only at the closes a cut compares,** found by a first run, so every comparison is the one it was and the cost falls: S05's cut test is 42 s in all, where the probe at every close took 40 s for one run of the long market. This touches every strategy's cut test, with the same comparisons | `tests/leak/test_whole_run_cuts.py` | `test_s05_s_long_market_takes_a_line_to_a_third_setup`, `test_the_harness_catches_a_next_bar_read_into_s05_s_stop_from_its_first_setup`. The S05 case of the third-setup back door now passes | A filter in the simulator keeping an S05 setup from the third on only if the next bar agrees: the S05 cut test fails on its assertion |
| 5 | C15 eligible bars | Tests only | none | `test_c15_eligible_entry_bars_leave_out_any_whose_setup_would_reach_the_end_or_a_read_day`, S03 and S10, through `build_plan`, with a range end at day 150 and a read day at day 60, both reached by some bars | Eligible bars taken without the left-out filter |
| 6 | C15 quarters compared | Tests only | none | `test_c15_a_quarter_is_not_compared_when_a_kind_born_in_it_has_no_earlier_distance`, on hand-made births through `_level_plan` | A quarter compared though a kind born in it has no earlier distance |
| 7 | R-02 | The scarcer side draws first, and takes a bar both sides can use only while the other side can still meet its count from the bars left. Each draw records its shortfall by quarter and side, and `placebo.json` prints it per draw, summed, and as a count of draws with one | `engine/placebo.py`, `reports/placebo.py` | `test_r02_the_reviewer_s_case_meets_both_counts_on_every_seed` (500 seeds, and the old draw is shown missing on some), `test_r02_with_bars_to_spare_every_draw_is_the_one_it_was`, `test_r02_each_bar_once_and_from_its_own_side_when_shared_bars_are_scarce`, `test_r02_a_count_the_bars_cannot_meet_is_recorded_by_quarter_and_side`, `test_r02_the_shortfall_of_each_draw_reaches_placebo_json` | The old free draw. No shortfall recorded. The row leaving it out. The limit binding with room to spare |
| 8 | Dated tick, C16 and C7 at `ecc5e49` | `[ticks]` takes a number or a dated list, and `configs/engine.toml` holds BTCUSDT 0.01 from 2020-01-01 and 0.1 from 2022-02-15 03:30, and ETHUSDT 0.01, both `UNVERIFIED` until K1 to K4 pass. Unsorted or repeated rows, a tick not above zero, a `from` not in UTC, and a range starting before the first row are refused. The setup's `S0` and targets and each stop and target update are rounded with the tick at their decision close. `BE+` is kept unrounded and rounded at each close that may use it. A target from the fill is rounded with the tick at the fill. A price set earlier keeps its value. `ratchet` already rounds before it compares with the stop in force, so rule 9 holds across a change. Each target leg keeps its `tick_i`, and fills only on a trade through it by that tick, with `round_to_tick`'s tolerance of 1e-7 ticks. `MarketView.tick` is the tick at the close, and `tick_at` gives an earlier one and refuses a later one, and S08's profile reads the tick at its end. `TickTable` lives in `src/hft_crypto/ticks.py`, so the data layer can use it without the engine | `ticks.py`, `engine/config.py`, `engine/fills.py`, `engine/simulator.py`, `engine/market.py`, `engine/run.py`, `strategies/s08_volume_profile_value_area.py`, `configs/engine.toml`. `tests/engine/test_tape.py`: `tick_at` added to the view's public list | `tests/engine/test_dated_tick.py`, 37 tests: the table before, at and after the instant; rounding there; the configuration refusals; a setup at each side of the change; a stop set before it keeping its value; rule 9 in `ratchet` and across the change in the simulator; `BE+` at each decision; a target from the fill at the fill's tick, and one where fill and decision straddle a change; one tick through fills and half a tick does not, long and short; a target set at 0.01 keeping its tick after the change; a target after the change not filled 0.05 through; a moved target taking the new tick; the margin against binary error; the view; S08's profile | A setup rounded with an older tick. `BE+` left at the fill's rounding. A fill-based target with the decision's tick. The margin read from today's tick. No margin. A moved target keeping its old tick. Compare before rounding, which also trips the simulator's own guard. A stop update with an older tick. A range before the table accepted. The view giving a later tick. S08 binning at the close's tick |
| 9 | Checks after the fetch | **Where they live:** `src/hft_crypto/data/venue_checks.py`, called from `data/ingest.py`. Each Binance monthly funding or candle file of the first span is checked right after its checksum, before anything parses it, and its result joins its own manifest entry (`check_detail.venue_checks`). At the end of the run the files are added up per symbol into `IngestSummary.venue_checks` and the catalog's `venue_checks` meta. Prices are read as text and tested by their decimal places. F1, F2, F4's duplicates and K1 stop the run: the file is quarantined, the task fails, and `VenueCheckStop` ends the run as failed. A duplicate across two files stops it at the end. F3 and F5 fail and are reported, a missing settlement is counted, K3 is reported with no pass or fail, and K5 is counted. K2 to K4 read the tick tables from `configs/engine.toml`, which `hft-crypto ingest` now loads | `data/venue_checks.py`, `data/ingest.py`, `cli.py`. `tests/data/test_candle_path.py`: the RA-01 fixture's prices are now on the 0.01 grid, since K1 stops a first-span ingest with four decimals | `tests/data/test_venue_checks.py`, 18 tests: a header mismatch, an interval of 4, an offset of 15.000 s and 15.001 s, a duplicate settlement and a missing one, a settlement held by two months, a row off the 8-hour grid, a price off 0.01, prices read from text, a BTC month at 0.01 with no price off 0.1, K3's minutes after the change, an ETH month with none, K5's counts, nothing priced in the output, the manifest and the summary through `run_ingest`, and three stops through `run_ingest` | K1, F1 and F2 not stopping. A settlement in two months not a duplicate. The run going on past a stop. F3 failing at exactly 15 s. Trailing zeros not stripped. The manifest missing a file's result. K3 counting minutes at 0.01 |

**Did differently, and why.**

- **R-02.** The brief said to assign bars only one side can use before shared bars. Done literally, a side would never take a shared bar while it
  had enough of its own, on every draw, which is not C15's "drawn uniformly" over that side's bars. So the first side draws as before, uniformly,
  and is held back from shared bars only once the other side would otherwise fall short. With bars to spare nothing binds, and a test shows each
  draw identical to the draw at `1c2dc23`, number for number, so the 200-draw run measured before is unchanged where bars were not scarce. Both
  counts are met whenever the bars allow, on the reviewer's case and on a scarcer one. **For `python-reviewer`, `leak-auditor` and
  `strategy-architect`:** if the literal reading is wanted, it is a small change to `draw_entries`.
- **Item 9's place.** Not the coverage check's `candle-check` path, which reads sample days in a check root and not stage one's files. Stage one is
  `run_ingest`, and the raw text can be deleted right after a file is curated, so each file is checked as it arrives and the span is added up from
  the manifest.

**Readings, for the named owners.**

| Reading | For |
|---|---|
| `connection` is every failed transfer that is not a timeout: a refused or reset connection, a failed lookup, a short or broken response, and an HTTP status not on the list, such as 500 or 503, after its attempts. The fixed list has no other word for these | `leak-auditor`, `data-steward` |
| The 429 change is in `HttpFetcher`, so the archive ingest and the Kraken poll also stop at a 429 rather than retry. Each records a failed task or poll, which a later run tries again | `data-steward` |
| `stop_reason` is a new key in `coverage_check.json`. Plan section 7.2 does not list it yet. `candle_check.json` is unchanged | `data-steward` |
| R-01: a position open across a stretch whose rows disagree carries no flag of its own on its trade row. The stretch is in the manifest and the header note. Before the first row and after the last, the schedule still assumes the nearest row's interval holds | `python-reviewer`, `leak-auditor` |
| C16 at `ecc5e49` has no leak verdict yet. **Leak: none expected.** The tick at an instant is known at that instant, and earlier from its announcement. No price is rounded with a tick from after the moment it is set, the view refuses a tick after its close, and a leg's `tick_i` is fixed when its price is set | `leak-auditor` |
| S07's band target holds a `fill + r` term inside a `max`, computed at a close. It is rounded with that close's tick, not the fill's. S07 does not run on candles | `strategy-architect` |
| F5: a settlement is the whole hour nearest `calc_time`, and a row whose hour is not 00:00, 08:00 or 16:00 is the "other gap". F4 counts only settlements on that grid. K2 to K4 need ticks that are powers of ten | `data-steward`, `python-reviewer` |
| S05's long market was picked for its setups and for the back door showing on it, which it did on 3 of the 10 seeds tried | `leak-auditor` |

**Mutation checks.** Each fix was reverted, or each leak injected, in a copy of the package, and the named tests run against the copy. A kill
counts only when a test fails on an assertion, read from each failure's own line. **44 of 45 killed on an assertion.** The one that is not: a
stopped coverage run keeping its quarters is refused by the RA-02 schema check, which raises before anything is written. That is the guard
working, and it is not counted as a kill. In "rule 9: compare before rounding" the `ratchet` test fails on its assertion, and the simulator test
stops on the simulator's own second guard against a stop moving away. Two tests were strengthened after a first pass showed them failing on an
error: the stage-one manifest test, and S08's tick, which had no test of its own until then.

**Commands, on the working tree.**

```text
ruff check src tests                 All checks passed!
ruff format --check src tests        118 files already formatted
mypy src  (PYTHONPATH at the short junction, which holds the venv's site-packages)
                                     Success: no issues found in 72 source files
pytest tests/engine                  first run: 517 passed, 1 failed, test_tape's list of the view's members lacking tick_at
pytest the touched data files, tests/reports and tests/test_synthetic_end_to_end.py
                                     first run: 497 passed, 5 failed, the RA-01 fixture's prices off the 0.01 grid
pytest tests/engine tests/data/test_venue_checks.py tests/data/test_candle_path.py, after both fixes
                                     565 passed in 366.70s
pytest tests/leak                    217 passed in 1294.18s. S06's cut test took 147 s, where it took about 1,048 s with
                                     registers written at every close. It shared the machine with other runs
```

The full suite was not run.

## Fixes after the recheck at `be20ee7`

Author: `developer`. From the code recheck at `be20ee7` (`docs/reviews/code/fixes_recheck_2026-11-05.md`, RC2-01 to RC2-03 and the
`move_tick` item) and the leak re-audit at `be20ee7` (the top section of `docs/reviews/leak/engine_2026-11-05.md`, RB-01 to RB-03).
RC2-04 and the S01 weekend note stay as the reviewer ruled. Working tree only, not committed. Generated data only, and no test touches a
network. No verdict is claimed. The `span_flag` change is new since the leak re-audit, so its verdict does not cover it.

| # | Item | What changed | Files | Tests | What each test kills |
|---|---|---|---|---|---|
| 1 | RC2-02 | A span flag is `false` when any checked file fails it, `true` only when all 48 months have a checked file, and `null` otherwise. Each flag carries `months_checked`. F1 counts every checked month, F2 to F5 only those with F1's header. K2 to K4 count only months checked with a tick table: a month checked without one was not tested against the ticks, and before this it would have raised a `KeyError`. **A stopped file's result is kept:** before it is quarantined, the raw file is entered in the manifest with `check_status` `fail`, its facts and `venue_stop`, and then marked `quarantined`. `_venue_span` reads every status, so the span fails on it until a later fetch of that month passes and replaces the entry at the same path. The end-of-run stop acts on `false` only, not on `null` (see the ruling below) | `data/venue_checks.py`, `data/ingest.py` | In `tests/data/test_venue_checks.py`: `test_rc2_02_a_kept_failure_stops_every_run_until_its_month_passes`, the reviewer's case through `run_ingest`, and the same for K1: the stop, a run a minute later that stops on the kept result with every other flag `null`, and a run after the wait with a good file. `test_rc2_02_a_funding_flag_passes_only_when_every_month_was_checked` and `test_rc2_02_k1_and_k2_pass_only_when_every_month_was_checked`, 48 months against 10. `test_rc2_02_a_month_checked_without_a_tick_table_is_not_checked_for_k2`. The stage-one test now expects `null` with 2 of 48 months, and the F3, F4, F5, K2 and K4 tests carry `months_checked` | A flag passing on part of the span. A stopped result not kept. F4 stopping on `null`. K2 counting a month checked without a table |
| 2 | RC2-01 | A settlement outside the span is listed in F4's `outside_span` and decides nothing. A slot inside the span is matched as before: it fills its month's gap, or it is a duplicate | `data/venue_checks.py` | `test_rc2_01_a_settlement_after_the_span_is_listed_and_decides_nothing`, the reviewer's case. `test_rc2_01_an_early_stamp_at_every_boundary_inside_the_span_stays_correct`: every boundary inside the span stamped 10 ms early gives 0 missing and 0 duplicates, and the same rows held by both months give 47 duplicates | An outside slot counted as a duplicate again |
| 3 | RC2-03 | In stage one, a `FetchError` whose reason is `http_403`, `http_429` or `http_451` records its task as failed and raises `HostRefusalStop`, which `_run_tasks` lets through as it does `VenueCheckStop`. The run ends `failed` before another file is asked for. `IngestSummary.stop_reason` says why a run ended early: the host's word, or the venue check's code. It is `none` otherwise. It reaches the catalog's run row | `data/ingest.py` | In `tests/data/test_source_switches.py`, `test_rc2_03_a_refusal_ends_stage_one_at_its_first_request`: 24 monthly tasks through a real `HttpFetcher` on an offline opener. A 429, 403 or 451 makes one request with no wait, one failed task, and `stop_reason` set. A 503 takes 3 attempts on each of the 24 tasks and ends `partial`. The venue-stop test now also checks `stop_reason` | The run going on after a refusal. The reason not recorded |
| 4 | `_Scheduled.move_tick` | A target move whose `move_tick` is not a positive finite number is refused with a `ValueError`. A stop update needs no tick, so the field keeps its default and is checked when a move is present | `engine/simulator.py` | In `tests/engine/test_dated_tick.py`, `test_a_target_move_without_the_tick_it_was_set_at_is_refused`: none, 0, -0.1, NaN and infinity are refused, and 0.1 and a stop update are not | The check removed |
| 5 | RB-01 | Tests only | `tests/engine/test_dated_tick.py` (`_Script` records the view's tick at each close), `tests/leak/test_whole_run_cuts.py` (`_run` takes a tick table) | `test_rb01_an_update_before_the_change_takes_the_tick_at_its_own_close`, long and short: a trail at 02:00 and a target move at 02:30 on 2022-02-15, each on the 0.01 grid, and the view's tick 0.01 before 03:30 and 0.1 from it. `test_rb01_t2_a_setup_target_filled_after_a_change_keeps_its_decision_s_tick_as_its_margin`, long and short, on the made-up change 30 s after the 03:30 close. `test_rb01_a_tick_that_changes_at_the_cut_leaves_everything_before_it_unchanged`, for all ten strategies (see below) | T5, T6, T9 and T2, below |
| 6 | RB-03 | Tests only | new `tests/leak/test_venue_checks_reach_no_decision.py` | `test_no_module_but_stage_one_imports_the_checks_or_reads_their_results` scans every module in the package. Only `data/venue_checks.py` and `data/ingest.py` may import the checks, or name `venue_checks` as an attribute, a name, or in a string, which covers the meta key, the manifest key and a dynamic import. `test_the_scanner_finds_each_way_in` holds the scanner to ten ways in | VC1, the engine reading the meta. VC2, a strategy importing the checks |
| 7 | RB-02 | A comment on `[ticks]`: each row's `from` is the venue's published effective time only, never a check's output such as K3's last minute. K1 to K4 confirm or refute a row and never move it | `configs/engine.toml`. The engine's `config_hash` is a hash of the parsed table, so it is unchanged: `9cf8d998…d533` before and after | none | none |

**RB-01's cut test, as built.** For each strategy, its first market that is not the long one, and its default line. The cuts come from a run
at 0.01 throughout. For each kind of event that sets a price (`SETUP_CREATED`, `ENTRY`, `STOP_UPDATE`, `TARGET_UPDATE`), there is a cut at
the instant one became known, a third and two thirds through the run, and one a microsecond later. A fill counts as known once its minute
can be read. Two random decided closes are added. At each cut, a run whose table is 0.01 before the cut and 1.0 from it is compared with the
run at 0.01 throughout, using the harness's own `_compare`: every decision known by the cut, and the registers at the last close decided by
it. **154 cuts, and 143 change something after the cut.** 58 cuts have a stop update known in the day before them, and 48 a target update,
so a read a day late has room to show. It takes about 47 s for all ten. The auditor compared two dated tables, at 0.1 and at 1.0 from the
cut. The run at 0.01 throughout agrees with both before the cut, so the comparison is the same with half the runs.

**Did differently, and why.**

- **Section 4.2 is in the coverage record.** It is `docs/reviews/data/binance_vision_coverage_2026-11-05.md`, which section 2 condition 2 of
  the coverage plan cites. The plan itself has no section 4.2. The code comment cites the record.
- **RC2-03 acts on every archive source**, Bybit's public host included, since the rule is about the host's refusal. Like `VenueCheckStop`,
  `HostRefusalStop` ends the run `failed` and goes on up, so the command exits with a traceback and `last_ingest.json` is not rewritten.
  The run's summary is in the catalog's run row, with `stop_reason`. `stop_reason` also names a venue check's code, because a key reading
  `none` on a run that a venue check stopped would mislead.
- **Where a stopped result is kept.** On its manifest entry, marked `quarantined`, and not on the quarantine log. `_venue_span` already reads
  the manifest at every status, and a later fetch of the month replaces the entry at the same path, which is what "until that month passes"
  needs. Every other reader of raw entries reads `present` only, as the parse-failure path already relies on.
- **`move_tick` is refused, not made required.** It follows two fields with defaults, and a stop update has no tick to give.
- **RB-03 scans the whole package,** with a list of who may touch the checks, as the reader's import rule does, so a new module cannot
  escape it. Its limit: a module that reads `last_ingest.json` or a run's summary whole and passes it on, without naming `venue_checks`,
  would not be seen. None does today. The report reads only the pipeline log's line.

**The coordinator's ruling, as built.** F1, F2, F4 or K1 `false` over the span ends every run `failed`, with `stop_reason` the check's code, until the month is fetched again and passes, so a run inside the retry wait no longer ends `ok`. `null` stops nothing and K3 only reports (`SPAN_STOPS` in `data/ingest.py`; `test_rc2_02_a_kept_failure_stops_every_run_until_its_month_passes`, F2 and K1, each with a refetch that clears it; mutants "F4 only" and "`null` stops" killed on an assertion, and `tests/data` rerun after it).

**Mutation checks.** Each mutant ran in its own copy of `src`, `tests` and `configs` outside the repository, against the tests named. A
plugin recorded each failure's exception type, and a kill counts only on an `AssertionError`. A control with no change passed all 82 tests
it ran. **14 of 14 killed on an assertion.**

| Mutant | Killed by, on an assertion |
|---|---|
| A span flag passes on part of the span | 8 tests, the four new RC2-02 tests among them |
| A stopped file's result not kept | The reproduction test. The first pass failed on a `ValueError` from unpacking an empty list, so the test now asserts the entry's status first, and the second pass kills it on an assertion |
| The end-of-run F4 stop acting on `null` | Before the ruling, the reproduction test. After it, the stage-one test, which now asserts that a run with every flag `null` does not stop |
| K2 counting a month checked without a table | `test_rc2_02_a_month_checked_without_a_tick_table_is_not_checked_for_k2` |
| An outside slot counted as a duplicate (RC2-01) | Both RC2-01 tests |
| A refusal not ending the run (RC2-03) | The 429, 403 and 451 cases |
| `stop_reason` not recorded | The 429, 403 and 451 cases |
| A target move with no tick accepted | `test_a_target_move_without_the_tick_it_was_set_at_is_refused` |
| T5: a stop update's tick read a day after its close | The new dated test, long and short, and the RB-01 cut test on 9 of 10 strategies. S09 makes no stop update on its market |
| T6: a target move's tick read a day after its close | The new dated test, long and short, and the RB-01 cut test on 7 of 10. S04, S05 and S06 make no target update on theirs |
| T9: the view's tick read a day after its close | The new dated test, long and short, and the RB-01 cut test on S08 |
| T2: a setup target's margin at the fill's tick | The new T2 test, long and short. Not the cut test, as expected: the fill's tick is known at the fill |
| VC1: the engine reads the `venue_checks` meta | The RB-03 scan |
| VC2: a strategy imports the checks | The RB-03 scan |

**Commands, on the working tree.**

```text
ruff check src tests                 All checks passed!
ruff format --check src tests        119 files already formatted
mypy src  (PYTHONPATH at the short junction)
                                     Success: no issues found in 72 source files
pytest tests/data tests/engine/test_recheck_fixes.py tests/engine/test_dated_tick.py
       tests/leak/test_venue_checks_reach_no_decision.py
                                     879 passed, 1 skipped in 410.06s. The skip is the Windows symlink privilege
pytest tests/engine                  525 passed in 239.62s
pytest tests/leak/test_whole_run_cuts.py
                                     37 passed in 857.68s, sharing the machine with the runs above
pytest tests/data/test_venue_checks.py tests/leak/test_venue_checks_reach_no_decision.py, after the last test change
                                     26 passed in 48.56s
```

The full suite was not run, and neither were the other five files in `tests/leak`.
