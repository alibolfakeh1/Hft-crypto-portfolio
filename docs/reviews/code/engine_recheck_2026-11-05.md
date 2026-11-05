# Code recheck: engine, placebos and V0S, before the first candle run

Reviewer: `python-reviewer`. Date: 2026-11-05. Code at commit `1c2dc23` on `pipeline/first-data-run`, read and run from a frozen copy of that commit. This answers
[the engine review](engine_review_2026-11-05.md) and tests the claims in [the progress note](engine_progress_2026-11-05.md). All data is generated, and nothing touched a network.
This report says nothing about whether any strategy works.

## 1. Verdict

**On correctness, the first `V0` run on official candles may start.** Every finding of the engine review that would have changed that run's trade list or net figures is fixed, at the
scenario the review gave. The money arithmetic still recomputes to the cent, two runs give identical files, and seven of the developer's kills, re-run by me, all failed on an assertion.

The conditions below are not correctness defects in this code. They stand outside it:

1. **The full suite passes.** The coordinator is running it. I ran only what my checks needed.
2. **Tick sizes are read from the venue,** as `configs/engine.toml` says, before the run. This is open from the review.
3. **The meaning of Binance's `funding_interval_hours` column is confirmed** (R-01). BTCUSDT and ETHUSDT are expected to stay at 8 hours, so R-01 should not act on this run. The interval values in the files the first span reads will show that.

| Area | Verdict | Section |
|---|---|---|
| The review's E-01 to E-17 | `PASS` | 3 |
| The author's rulings in `3b54087` and `47c0dc8` | `PASS` | 3 |
| The leak audit's EN-01 to EN-07, RA-01, RA-02 | `PASS` | 3 |
| Funding schedule, `engine/funding.py` | `PASS WITH CONDITIONS` | R-01 |
| Booking, equity, totals, determinism | `PASS` | 4 |
| C15 placebos | `PASS WITH CONDITIONS` | 5, R-02, R-03 |
| `V0S` control | `PASS` | 6 |
| The developer's mutation figures | `PASS`, on a sample of 7 | 7 |
| S05's coverage | `PASS WITH CONDITIONS` | 8 |
| Registry count | `PASS` | 9 |

## 2. New findings

All three are Low, and none changes a `V0` trade.

### R-01, Low. An interval that lengthens makes a false gap, and one that shortens can hide a real one

`src/hft_crypto/engine/funding.py:53-56`.

The cadence of a stretch is read from the row before it. Case: rows at 4 h and 8 h with `funding_interval_hours` 4, then 16 h and 24 h with 8. The schedule names a missing settlement at 12 h, which never existed. The reverse
also fails: a shortening from 8 to 4 with one row missing gives `round(8 / 8) = 1` step, and the missing row is not seen. `test_e01_a_late_stamp_and_a_change_of_interval_are_not_holes` covers only a shortening with
no row missing.

Which of the two readings is right depends on whether a row's interval describes the period ending at it or the one starting at it. That is `UNVERIFIED`. On BTCUSDT and ETHUSDT the interval is
expected to stay 8 hours, so no settlement should be affected on the first run. **Fix:** confirm the column's meaning, and read the interval from the row that matches it. Or, simpler, count a stretch as missing
settlements only when both rows agree on the interval, and log the stretch when they do not.

### R-02, Low. When eligible bars are scarce, the entry draw can miss a count it could meet

`src/hft_crypto/engine/placebo.py:381-396`.

The ruling says drawing the scarcer side first "meets both counts whenever the bars allow". It does not always. Case: the long side needs 1 of bars {1, 2}, and the short side needs 2 of {2, 3}. Both sides have two bars, so
the tie order puts long first. When long draws bar 2, short gets one entry and not two. Over 500 seeds the short count was met in 265. Every satisfiable case I built with room to spare met both counts in all 500.

**Fix:** print the shortfall per draw, so a quarter where it happens is visible. If it matters, assign a bar both sides share only after the bars only one side can use.

### R-03, Information. A placebo's first quarter is the first quarter of the run's range

`src/hft_crypto/engine/placebo.py:194-195`, `:227-230`.

For a run over the first span this is 2020-Q1, as C15 says. A later run whose range starts at a test block finds no earlier block in its own range, so that block has no level placebo at all, and says so with
`FIRST_QUARTER_HAS_NO_EARLIER_BLOCK`. C15 says 2024-Q1 "may draw on the whole first span". So a test block's placebo needs a range that holds the span before it. This is loud, not silent. **For
`project-manager`:** state the range that each test-block run must use.

## 3. The fixes, one by one

**Evidence:**

- My own probes from the review, rerun on this commit.
- New hand cases.
- The developer's three fix test files: 91 passed.
- RA-01 and RA-02: 12 passed.
- Seven mutants, in section 7.

| Item | What I ran | Result |
|---|---|---|
| E-01 | A long held over three settlements with the middle rate missing. And `funding_schedule` on rows with a two-day hole | Pays 20.00 for the two rates that exist. One `DATA_GAP` is logged, `funding_rate_missing` is 1, and the trade carries the gap. The schedule names all 8 missing settlements, both inside the range and after its last row. See R-01 for a change of interval |
| E-02 | My review case: rows 198 to 201 missing, with a settlement in them | Now charged. A stop gapped through at an open pays nothing later in that minute |
| E-03 | My review case: headline stopped at a gap, with a later 1% settlement | Funding 0, net -1,000.00 |
| E-04 | A whole 1h bar with no rows, and a swing whose window crosses it | No swing. `V0S`'s hold counts the gap bar in `n` (section 6) |
| E-05 | S03 run as a sequence of closes. It passes at `n = 30` and falls below `fill + 1R` at 35. Below at 30. No trade at 30 | No exit. Exit at 30. Exit at 31, the next close with a price, as ruled |
| E-06 | Developer test, with the S04 birth case from the review | Passed. Not reproduced independently this round |
| E-07 | A bar opens the retest and closes below `mid`, and the next bar closes above `top` | The flip dies, with no trigger |
| E-08, E-09, E-10 | Developer tests | Passed, and E-08's test checks a swing pool against the whole register. Not reproduced independently |
| E-11 | Gross 400.00, costs 11.20, funding 100.00 | Net is zero at the printed multiple |
| E-12, E-13 | My review cases | Part-closed trade: 0.00 unrealised. A refused trade has no exit reason. The old stop is named `STOP_INITIAL` |
| E-14 | Section 9 | 52 lines per symbol |
| E-15, E-16, E-17 | Developer tests | Passed |
| S03 reading | Developer test | Passed |
| S05 travel ruling | The bar that completes travel also dips to `top` | No retest opens |
| S01, S06 linger, S09 `n = 4`, S07, S05 no-trade rulings | Developer tests in `test_audit_more.py` | Passed. Not reproduced independently |
| EN-01 | Mutant: the cap reads the headline legs again | Killed |
| EN-02 | Same as E-02 | Holds |
| EN-03 | Read `engine/portfolio.py:57-94` | A refused entry reserves its scaled room until the minute that refused it |
| EN-04 | Section 8 for S05. The whole-run cut tests were not run here, see section 11 | Not rerun |
| EN-05, EN-07 | Developer tests | Passed |
| EN-06 | First allowed minute missing. First allowed minute proved empty | Refused and counted. Fills at the next print |
| RA-01, RA-02 | Their 12 tests | Passed |

## 4. Booking and the whole command

My hand cases from the review, rerun on this commit:

- **Hand cases:** 39 accounting checks with 0 deviations. The second set now passes on E-03, E-11 and E-13.
- **Full run on 200 generated days:** two runs give byte-identical files. Every one of 305 trades recomputes from its own row.
- **Portfolio:** the capped and uncapped rows equal the sums of their trades, and the equity file ends on them.
- **Equity statistics:** max drawdown, Sharpe on 365 days and CAGR agree with my own arithmetic.
- **`V0S` stays out:** the portfolio rows equal the `V0` trades marked in it, so no `V0S` money is in them.
- **Driftless market:** every strategy's default line, 4 seeds of 300 days: 2,141 trades, mean gross `Result_B` -0.0049, t -0.21, so no edge appears from nowhere after the fixes. Every event knowable by a cut at day 200 is identical with the data after it removed, for all ten.

## 5. C15 against its text

| Point | Text | As built, and how checked | Result |
|---|---|---|---|
| Seed | First 8 bytes of the SHA-256 of `C15\|<strategy>\|<symbol>\|<line>\|<draw>` | My own hash, big-endian, matches `draw_seed`, and draws run from 1 | Holds |
| Count | 200 draws, declared | `configs/engine.toml` declares 200, and the progress note says a market configuration may not state another | Holds |
| Kinds | Kept by kind, never pooled. A set born together draws one earlier set's whole vector | A pool with two daily sets, one weekly set and a later daily set. 200 draws in a later quarter gave only the two earlier daily vectors, whole | Holds |
| Earlier blocks | Only earlier blocks, uniform with replacement | `count_before` is 0 for the birth's own quarter. The mutant that lets a draw read its own quarter is killed | Holds |
| First quarter | 2020-Q1 has no level placebo, and is named | By the run's range, see R-03 | Holds for the first span |
| Rank and ties | Rank among the draws | `1 + count(draw >= real)`: 1 above all, a tie counts against the real line, the lowest real ranks last | Holds, as ruled |
| S03 and S10 | As many long and short entries per block and symbol as the real setups, without replacement | 500 seeds on two quarters with room: exact counts per quarter and side, each bar once, from that side's own bars | Holds. R-02 when bars are scarce |
| What stays real | The new paragraph | Read in `strategies/sources.py`: only the source's object is replaced | Holds |
| A placebo run is a logged read | Controls in the registry | Section 9 | Holds |

The 200-draw run itself was not repeated. The note times it at 1,191 s with 5 workers. Its driftless check put the real ranks between 23 and 185, and none in the top or bottom 10, which is what a working
placebo should show there.

## 6. `V0S` against C13 and section 7.10

| Point | Checked by | Result |
|---|---|---|
| `m` and `H` | Each class's constants against the ruling's table, all ten | Match: S01 2.0/16, S02 2.5/48, S03 3.0/120 and 30, S04 and S05 2.5/48 and 24, S06 2.0/16 and 32, S07 2.0/48, S08 2.0/8 and 16, S09 2.0 and the hard flat, S10 4.0/36 and 72 |
| One target at `fill + m * R`, from the fill, which rules the fill bar | Hand case: fill 1002.1002, `R` 12.1002, `m` 2 | Target 1026.30, rounded down from 1026.3006, set at the fill. A trade-through takes the whole position |
| No update of any kind, no invalidation | An inner strategy that asks for a trail at every close | No stop moved. The inner `manage` is never called |
| `H` counts `n`, and closes at the next open | `H` = 4 on 5m bars | `n = 4` at the close of minute 120, filled at the open of minute 121 |
| A bar with no trade counts | The same, with a whole 5m bar missing | Same exit as recorded. C2 headlines the stop at the hole, as it does for `V0` |
| S09's `H` is the hard flat fixed at entry | Read: `v0s_time_up` reads `memo.flat_us`, set at the setup | Holds |
| Its own stream | Read: its own `Simulator`, and `notify_sent` on its own instance | Holds |
| Never in the portfolio | `in_portfolio=False` in the stream and its registry row. `build_rows` takes `V0` streams only. The end-to-end totals match `V0` alone | Holds |
| Same `H_max` | `h_max_us` is the inner strategy's | Holds |

## 7. The developer's mutation figures

I reverted seven fixes or injected seven leaks, chosen by me, each in its own copy. I ran the named tests and told a failed assertion apart from an error.

| Mutant | Tests | Outcome |
|---|---|---|
| E-01: no settlement is ever marked missing | `test_e01_*` | Killed by a failed assertion |
| E-02: settlements before the previous minute are skipped again | `test_e02_*` | Killed by a failed assertion |
| E-07: the bar opening the retest does not count towards `mid` | `test_e07_*` | Killed by a failed assertion |
| EN-06: an entry waits across a missing minute again | `test_en06_*` | Killed by a failed assertion |
| EN-01: the gross cap reads the C2 headline again | `test_en01_*` | Killed by a failed assertion |
| C15: a draw can read its own quarter | `tests/leak/test_placebo_leak.py` | Killed by a failed assertion |
| E-14: S08 counts one line on trades | Registry tests | Killed by a failed assertion |

None was killed by an error. That is the trap the earlier pass fell into, and the developer reports fixing it. This is a sample of 7 of their 122, so it supports their figures and does not prove all of them.

## 8. S05's coverage

The developer's runs never reach a second S05 setup on a line, so their injected "filter from the third setup" cannot act. I ran S05 on two driftless generated markets of 1,500 days, every grid line.

- **Setups:** 2 to 5 setups per line.
- **Cuts:** at every setup's close and at 3 random closes, every event knowable by the cut is identical with the data after it removed.
- **Result:** 8 runs, 0 differences.

**Is there a real gap?** A narrow one, in the tests and not in the code. S05's registers come from `ZoneBook`, which S04 shares and which has many more setups, plus its flip logic. My runs show that truncation holds over several S05 setups. What is not shown is that the whole-run harness catches a leak that starts late in an S05 run. **Fix:** give S05's cut test one long driftless seed like mine. It runs in seconds, and then the third-setup mutant can act.

## 9. Registry count

On the market configuration, on candles, run through `simulate_streams` and `simulate_v0s` against a fresh registry:

| Step | Distinct trials | C15 readings |
|---|---|---|
| All `V0` lines, both symbols | 104, which is 52 lines × 2 symbols | 0 |
| Then all `V0S` lines | 104 | 0 |
| Then the same `V0` run again | 104 | 0 |

The count is 52 lines per symbol, as asked. A `V0S` row is a control and counts nothing. Only a row with a draw is a C15 reading. The registry tests' mutant, S08 counting one line on trades, is killed. `D-32`'s 2 runs are
printed beside the count, by reading `reports/portfolio.py:875`. I did not see a printed header on market data, since that needs a market root.

## 10. Commands and output

Run from a frozen copy of `1c2dc23` under Git Bash, with `PYTHONPATH` set to the copy.

```text
$ python -m pytest -q tests/engine/test_review_fixes.py tests/engine/test_audit_fixes.py tests/engine/test_audit_more.py
91 passed in 5.80s
$ python -m pytest -q tests/data/test_candle_path.py tests/data/test_date_guard.py -k "ra01 or ra02"
12 passed, 90 deselected in 77.95s
$ mypy src          (PYTHONPATH set to the short junction)
Success: no issues found in 70 source files
$ ruff check src tests ; ruff format --check src tests
All checks passed!
113 files already formatted
```

| Probe | Checks | Deviations |
|---|---|---|
| Accounting by hand, from the review | 39 | 0 |
| Accounting, second set | 7 | 1: my old case passed events straight to the simulator, so it bypasses `funding_schedule` and does not test E-01. Replaced by the E-01 case below |
| Missing bar, capped row, registry count, from the review | 3 | 0 |
| `V0S`, funding schedule, S03 stall, S05 retest, EN-06 | 15 | 1: R-01 |
| Registry, seed, rank, kinds, entry counts | 13 | 1: my own case asked for more bars than existed. Rerun as a satisfiable case: 0 |
| Entry draw, feasible edge | 2 | 1: R-02 |
| Whole command, every figure recomputed | 10 | 0 |
| S05, 1,500 days, cuts at every setup | 8 | 0 |
| Mutation spot-check | 7 | 7 killed by assertion |
| Driftless market, 4 seeds of 300 days, every strategy's default line, and truncation at day 200 | 21 | 0: 2,141 trades, mean gross `Result_B` -0.0049, t -0.21, and every strategy's events identical by the cut |

## 11. What I did not check

- **The full suite,** which the coordinator is running.
- **`tests/leak/test_named_leaks.py` and `test_whole_run_cuts.py` in full.** The note puts S06's cut test alone at about 17 minutes.
- **A 200-draw placebo run.** I tested its parts and one leak mutant.
- **The S01, S06, S07 and S09 rulings for a bar with no trade, independently.** Only their tests ran.
- **Real data or real funding files.** R-01 rests on how they are written.
