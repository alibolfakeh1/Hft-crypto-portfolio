**On correctness, the first `V0` candle run may start once the three conditions in section 1 hold. Nothing found here changes a `V0` trade.**

# Code recheck: the fixes after the rechecks, `1c2dc23..be20ee7`

Reviewer: `python-reviewer`. Date: 2026-11-05. Code at `be20ee7` on `pipeline/first-data-run`, read and run from a frozen copy of that commit. `1c2dc23` was run from a second frozen copy, for comparisons.

Documents read:

- C7, C8, C15 and C16 of `docs/01_strategies/00_INDEX.md`, with C7 and C16 at `ecc5e49`.
- Section 3 of `docs/reviews/data/venue_facts_2026-11-05.md`.
- The developer's account, the last section of `docs/reviews/code/engine_progress_2026-11-05.md`.

All data is generated or written by hand, and nothing touched a network. This report says nothing about whether any strategy works.

## 1. Verdict

**`PASS WITH CONDITIONS`.**

The engine side does what the documents ask: the dated tick, R-01, R-02 and the cut harness.

- **Hand cases.** They hold long and short, either side of 2022-02-15 03:30 UTC.
- **Generated configuration.** Every trade, event, equity point, `V0S` trade and placebo draw is identical at `1c2dc23` and `be20ee7`.

The defects are in the checks after the fetch. Those checks are the evidence that C16's tick table and the 8-hour funding schedule rest on. One defect can make a run's summary read `pass` after a file has failed. Another can stop every run on a false duplicate. Separately, a 429 no longer stops stage one in the way the coverage plan asks. None of these changes a trade.

**Conditions for the first `V0` candle run:**

1. **The full suite passes at `be20ee7`.** The coordinator is running it.
2. **Stage one's venue checks are read past their pass flags,** until RC2-02 is fixed. For each symbol:
   - `F4.files` is 48, and `F4.missing` is 0 or each missing settlement is listed.
   - `K5.rows` is 2,103,840, with 0 missing.
   - `K2.months_at_0_01` is 26 for BTCUSDT, and `K4.months_at_0_01` is 48 for ETHUSDT.
   - Every check passes.
   - No first-span task in the catalog holds a `venue check:` error.
3. **RC2-01 is fixed before stage one runs.** Otherwise, someone confirms that no 2023-12 funding file holds a row stamped in January.

| Area | Verdict | Section |
|---|---|---|
| Dated tick, C16 and C7 at `ecc5e49` | `PASS` | 3 |
| R-02 as built | `PASS`, with RC2-04 as information | 4 |
| R-01 | `PASS` | 5 |
| Checks after the fetch, F1 to F5 and K1 to K5 | `PASS WITH CONDITIONS` | 2, 6 |
| Coverage stops and `stop_reason` | `PASS` | 7 |
| The 429 change in `HttpFetcher` | `PASS WITH CONDITIONS` | RC2-03, 7 |
| Cut harness, registers at compared closes only | `PASS` | 8 |
| Funding to net and the two C15 tests | `PASS` | 9 |
| The developer's open readings | Ruled one by one | 10 |
| The developer's mutation figures | `PASS`, on a sample of 7 | 11 |

## 2. Findings

### RC2-01, Low. F4 counts a settlement after the span as a duplicate, and so stops every run

**Where.** `src/hft_crypto/data/venue_checks.py:146-154`, acted on at `src/hft_crypto/data/ingest.py:963-965`.

**The rule.** A settlement whose row sits in a neighbouring month's file is matched against the missing list. Anything not on that list counts as a duplicate. A slot after 2023-12-31 is never on the list, because the list covers the span only.

**Failure, run.**

- Input: 48 clean monthly files. The 2023-12 file also holds the 2024-01-01 00:00 settlement, stamped 10 ms early (`calc_time` 2023-12-31 23:59:59.990). F3 allows 15 s either way.
- Output: `F4 = {pass: false, missing: 0, duplicates: 1}`.
- Effect: `_venue_span` raises `VenueCheckStop(F4_DUPLICATE_SETTLEMENT)` at the end of that run, and of every later run, since the manifest keeps the file.
- Contrast: the same early stamp at every month boundary inside the span gives 0 missing and 0 duplicates, which is correct.

Whether Binance ever stamps a settlement early is `UNVERIFIED`.

**Fix.** Count an outside slot as a duplicate only when it is a slot of the span that another file also holds. List a slot outside the span separately, for example as `outside_span`, and decide nothing on it. Add this case as a test.

### RC2-02, Medium. The span's pass flags cover only files that were checked, so a run after a stop reports `pass`

**Where.** `src/hft_crypto/data/venue_checks.py:135-171` and `:236-277`; `src/hft_crypto/data/ingest.py:470-482` and `:939-965`.

**Why it happens.**

- `funding_span` and `candle_span` judge each check over the files whose results are in the manifest.
- A file that stops the run is quarantined before `register_output`, so its result never reaches the manifest.
- Its task then waits `retry_base_minutes` before a retry, doubling with each attempt. A run inside that wait skips the task.

**Failure, run through `run_ingest` with a fake fetcher.** BTCUSDT, 2023-11 and 2023-12. December's funding file has one row at interval 4.

- First run: `VenueCheckStop(F2_INTERVAL_NOT_8)`, status failed. Correct.
- Second run, one minute later:
  - status `ok`, `skipped_retry_wait` 1;
  - `F1 {pass: true}`, `F2 {pass: true, rows: []}`;
  - `F4 {pass: true, missing: 4293, files: 1}`.

So the catalog's `venue_checks` and `last_ingest.json` say F2 passes, while the file that failed it sits in quarantine. Only F4's missing count shows the gap. As the retry wait doubles with each attempt, more and more runs fall inside it.

**Other ways a month goes unchecked.**

- A raw file fetched before `be20ee7` is reused, and a reused file skips the check.
- A check that raises a `ValidationError` fails the task without recording a result.
- With 10 of 48 candle months checked, K1 says `pass: true`, and K2 says `pass: true` with `months_at_0_01` 10. K1 has no count of the months it covers.

The venue facts ask for each check over the whole span. C16 makes the tick table verified only when K1 to K4 pass. A pass that rests on part of the span, or that leaves out the failed file, is not that.

**Fix.**

- A check passes only when all 48 months have a checked file. Otherwise its `pass` is `null`, and it prints `months_checked`.
- Keep a stopped file's result, for example on its quarantine record, so the span fails until a later fetch of that month passes.
- Optionally, `_run_tasks` also raises `VenueCheckStop` at its end while any first-span task holds a `venue check:` error.

### RC2-03, Low. A 429 now skips the backoff, but stage one does not stop

**Where.** `src/hft_crypto/data/fetch.py:47` and `:154-157`; `src/hft_crypto/data/ingest.py:520-523` and `:893-904`.

**The rule.** Section 4.2 of the coverage record says to stop on a 403 or a 429 rather than retry around it. The coverage check does stop. In stage one, a 429 is now a `FetchError` on the first attempt, `run_archive_task` marks the task failed, and the loop goes straight to the next task.

**Failure, run.** A real `HttpFetcher`, whose opener answers every request with 429, over 24 monthly tasks:

- Now: 24 requests back to back, with no sleep. All 24 tasks failed, and the run status is `partial`.
- Before: 3 attempts per task, with waits of 2 s and 4 s.

**Effect.** Nothing is hidden: every task records `HTTP 429 from data.binance.vision`. But on the first span, one 429 sends a request for each of the other 191 files with no pause, which is what section 4.2 rules out. The developer's reading that the ingest "stops at a 429" does not match the code.

**Fix.** In `_run_tasks`, end the run on a `FetchError` whose `reason` is `http_403`, `http_429` or `http_451`, as `VenueCheckStop` does, with the task recorded as failed.

### RC2-04, Information. Where R-02's limit binds, the draw is not uniform over the feasible draws

**Where.** `src/hft_crypto/engine/placebo.py:399-436`.

Both counts are met whenever the bars allow, and where nothing binds every draw is the old one (section 4). Where the limit binds, the draw is close to uniform over the assignments that meet both counts, but not exactly.

- **Case.** Long bars {0, 1, 10, 11}, and long needs 2. Short bars {10, 11, 20, 21, 22}, and short needs 4. The feasible long picks are the five pairs holding at most one of 10 and 11.
- **Measured.** Over 120,000 seeds, {0, 1} came 0.167, and each other pair between 0.205 and 0.210. Uniform would give 0.200 each. By hand, the rule gives 1/6 and 5/24.
- **Also.** Of the 1,704 binding draws that `1c2dc23` had met, 26 were changed anyway.

The limit binds only when a quarter's real counts come close to its number of eligible bars. For S03 and S10, a quarter has thousands of eligible bars against a few setups, so I expect it never to act on market data.

**Fix, only if exact uniformity is wanted.** Draw the first side as at `1c2dc23`. Redraw from the same stream while the second side cannot meet its count, up to a cap, and then fall back to the present rule. That gives the old draw whenever the old draw met both counts, and is uniform over the feasible picks. Otherwise, accept, with the shortfall as printed.

### Information

- **`src/hft_crypto/engine/simulator.py:160`.** `_Scheduled.move_tick` defaults to 0.0. Every construction today passes it. A target move built without it would divide by zero in `traded_through`. Make it required.
- **`src/hft_crypto/strategies/s01_floor_pivot_rejection.py:324-338`, with `src/hft_crypto/engine/simulator.py:592-598`.**
  - At a weekend boundary, S01 re-sends the planned `T1` price with a new fraction, and `_schedule_target` rounds it again with the tick at that close.
  - After a change of tick, that moves the price and its `tick_i`. C16 says a price set before a change "is not rounded again".
  - It cannot happen on the first span. BTCUSDT's change is on a Tuesday at 03:30, and S01 holds at most 24 hours, so no position open across it reaches a Saturday 00:00.
  - Fix before any table with a change near a weekend: when a move's price equals the planned price, keep the leg's price and `tick_i`, and change only the fraction.
- **`src/hft_crypto/engine/run.py:226-236` and `:622-623`.**
  - The manifest's new key `funding_interval_changes` changes `data_manifest_hash` for identical data, and the registry's trial identity holds that hash. The new dated table changes `config_hash` the same way.
  - So a rerun after this commit, of a line run before it, would count as a new trial. No market run exists yet, so nothing is counted twice. Counting too many errs on the safe side for the deflated Sharpe ratio.
  - For `project-manager`: decide whether a change to the code alone should re-key trials.
- **`src/hft_crypto/cli.py:204-209`.** `hft-crypto ingest` refuses to start if `configs/engine.toml` exists and does not parse. With no file, it passes `None`, and K2 to K4 say they were not tested. This is loud, and accepted.

## 3. The dated tick against C16 and C7 as amended

**Setup.** BTCUSDT's table: 0.01, and 0.1 from 2022-02-15 03:30 UTC. A 5m decision timeframe. Each figure was worked by hand first.

- **Long case.** The flat price is 40000.37.
- **Short case.** Every price is mirrored about 80000. That is a multiple of both ticks, so rounding down mirrors to rounding up. Fills are not mirrored, because slippage is multiplicative.

| Clause | Code | Case | Result |
|---|---|---|---|
| `tick(t)` is the latest row at or before `t` | `ticks.py:45-49` | The view's tick at close 03:25 and at 03:30 | 0.01, then 0.1. Holds |
| `S0` and setup targets are set at the decision | `simulator.py:475-486` | Decision at close 03:15. `S0` 39990.037, `T1` 40100.077, `T2` 40200.077 | 39990.03, 40100.07, 40200.07. Short: 40009.97, 39899.93, 39799.93. Holds |
| `BE+` is set at each decision | `simulator.py:545-546`, `:700-717` | Fill 40004.370037, so `BE+` before rounding is 40052.375281 | 40052.37 at the fill's view and at 03:25. 40052.3 at 03:30. Short: 39947.64, then 39947.7. Holds |
| An update is rounded before C8 compares it | `exits.py:42-48`, called at `simulator.py:565-572` | Stop 39990.05 set at 03:25. Candidate 39990.09 at 03:40 rounds to 39990.0. Candidate 39990.15 at 03:50 | The stop stays at 39990.05, with no `STOP_UPDATE` at 03:40. Then it moves to 39990.1. Rule 9 holds across the change, long and short |
| A resting price keeps its value | `simulator.py:714`, `:820-825` | `T1` 40100.07, set at 0.01. After the change: a high of 40100.075, then 40100.08 | No fill on half a tick. A fill at 40100.07 on one tick of 0.01. Holds |
| Each target's own `tick_i`, `H >= Ti + tick_i` | `fills.py:37-44`, `simulator.py:804` | `T2` moved after the change, from 40150.077 to 40150.0, so `tick_i` is 0.1. Highs of 40150.09, then 40150.1 | No fill at 0.9 of a tick. A fill at 40150.0. Holds |
| A target from the fill is set at the fill | `simulator.py:699`, `:737-752` | The real `V0S` wrapper. Decision at 03:25. Four minutes proved empty, so the fill is at 03:30 | Target 40033.050111 rounds to 40033.0. It fills on 40033.1 and not on 40033.09. Short: 39967.0. Holds |
| The same, with no straddle | as above | Fill at 03:26 | 40033.05, with `tick_i` 0.01, filled on 40033.06 and not on 40033.055. Short: 39966.96. Holds |
| Tolerance against binary error | `fills.py:17`, `:37-44` | 0.3 against 0.2 at 0.1, which is 0.09999999999999998 in binary. 0.9999 of a tick. 200000.01 against 200000 | Through, not through, through. Holds |
| `H > Ti` on prices already on the grid | as above | 200,000 random pairs on the 0.01 grid, tick 0.01 | 0 differ from the old rule |
| S08's tick | `s08_volume_profile_value_area.py:175-178` | Read | The tick at the profile's end. It is only a floor on the bin width, `max(tick, share * price)`. S08 does not run on candles |
| The parser's refusals | `config.py:91-114`, `ticks.py:28-35`, `config.py:268-272` | The developer's 11 cases and the range check, run | All pass. By reading, a bare TOML datetime is refused as not text, and a NaN tick is refused by `TickTable` |
| The generated configuration gives the same results | the whole command | Both commits, the same generated root of 200 days, every line, `V0S`, 12 draws a default line | See below |

**The whole command on both commits.** Every output file differs only in the following:

- the header's `data_manifest_hash`, which moved because the manifest gained a key;
- new keys, each empty or zero: `funding_interval_changes: []`, `entry_shortfall: {}`, and `draws_with_an_entry_shortfall: 0`.

Every trade, event, equity point, `V0S` trade, portfolio row and placebo draw is identical: 1,521 `V0` trades, 1,503 `V0S` rows and 240 draws.

## 4. R-02 as built

| Check | Result |
|---|---|
| The reviewer's case: long needs 1 of {1, 2}, short needs 2 of {2, 3} | Met on 500 of 500 seeds |
| Brute force: 3,000 random quarters of up to 9 bars, 20 seeds each | 49,440 feasible draws, all met. 10,560 infeasible draws, each placing the most any assignment could. The recorded shortfall equals the entries not placed, on every draw |
| `1c2dc23` against `be20ee7`: 400 random instances, 25 seeds each, run on both commits | 6,125 draws had no binding quarter, and all are identical, number for number. Of 3,875 with a binding quarter, the old code met 1,704 and the new 2,050. Every new draw left unmet is in an instance with an infeasible quarter. The old code left 346 feasible draws unmet |
| `drawn_entries`, which feeds `placebo.json`, gives the draw that was simulated | Holds, by reading. It replays the same seed, and `draw_entries` is the first consumer of that stream in `draw_strategy` |
| Uniform where the limit binds | Not exactly: RC2-04 |

So both counts are met whenever the bars allow, and the draw is the old draw wherever nothing binds. The literal fix would also have changed draws where nothing binds, whenever the first side held bars of its own beside shared ones.

## 5. R-01

| Case | Result |
|---|---|
| The interval lengthens from 4 to 8 with no row missing. Rows at 4 h, 8 h, 16 h and 24 h | Nothing is named at 12 h. The stretch from 8 h to 16 h is logged with 4 and 8 |
| The interval shortens from 8 to 4. Rows 0, 8, 16 and 24 h, with 20 h missing | 20 h is named, inside a stretch whose rows agree. The stretch from 8 h to 16 h is logged |
| A row missing inside a stretch whose rows disagree | Nothing is named there, and the stretch is logged |
| Rows that agree, with 16 h and 24 h missing | Both are named |
| Before the first row | The first row's interval is assumed back to the range's start, as the developer states. 0 h itself is never named, because no position exists at the first instant |
| The header note | It names the count of stretches and `FUNDING_INTERVAL_CHANGED`, with or without missing rates. With none, it is unchanged |

F2 stops stage one on any interval other than 8 in 2020 to 2023, so on the first span neither the logged stretch nor the edges can act. The note reads "At 1 stretches". That is wording only.

## 6. The checks after the fetch

Generated monthly zip files of invented text, through `funding_file_facts`, `candle_file_facts` and the two span functions.

| Point | Result |
|---|---|
| F4's expected count | 4,383 per symbol, for 1,461 days times 3. K5's is 2,103,840 |
| 48 clean months, every stamp 3 ms late | F1 to F5 pass, 0 missing, 0 duplicates, largest offset 3 ms |
| An early stamp at every month boundary inside the span | 0 missing, 0 duplicates |
| An early stamp of 2024-01-01 00:00 in the 2023-12 file | A false duplicate and a stop: RC2-01 |
| A settlement twice in one file, and one held by two months | Each is one duplicate. The first stops on its file, the second at the end of the run |
| F2, F3, F5 | An interval of 4 is listed with its time, and stops. 15.000 s is within F3 and 15.001 s is over. A row at 04:00 is off the grid |
| Exact decimals from text | "40000.000" and "40000.1000" are on the 0.1 grid. "1.005" is off 0.01 and stops under K1. "1E2" is not a plain decimal, so it is off every grid and stops, meaning "investigate" |
| K2 around 2022-02-15 03:30 | Minutes before 03:30 are at 0.01, and from 03:30 at 0.1. A February whose only price off the 0.1 grid comes after 03:30 does not show 0.01, so K2 fails for it. Those minutes go to K3, with the first and last minute. Over 48 months, K2 is 26 of 26 |
| K4 | Named for a symbol with one tick |
| What stops and quarantines | F1, F2, F4 within a file, and K1 quarantine the file and stop the run. F4 across files stops the run at its end. F3 and F5 fail and are reported. K3 is reported. K5 is counted |
| What leaves | Counts, flags, a largest offset in ms, and settlement or minute times. No float appears in any file's result or in the span's. No price, volume, rate or series by day |
| After a stop, and with months unchecked | RC2-02 |
| `hft-crypto ingest` with no `engine.toml` | `None`, and ingest runs as before. With the market file, both dated tables load |

## 7. Coverage stops and the 429

- **The developer's coverage-stop tests.** 31 passed in `tests/data/test_date_guard.py`.
- **The schema.** `stop_reason` is `none` exactly when the run did not stop, and one of the eight words when it did. A stopped document holds no quarter. The schema refuses anything else before writing.
- **Every caller of `HttpFetcher` after the 429 change:**

| Caller | On a 429 | Silent? |
|---|---|---|
| Coverage check | Stops, with `stop_reason` `http_429` | No |
| Candle check | Stops on the `FetchError` (`coverage.py:554-557`) | No |
| Stage one ingest | Each task fails and the run goes on: RC2-03 | No. Every task records its error |
| Kraken poll | Records a failed poll and ends its page loop (`poll.py:697-699`) | No. The source is out under `D-23` |

## 8. The cut harness

**The change.** Registers are written only at the closes a cut compares. A first run finds the cuts, with every close still keyed, so `_cuts` reads the same events and closes as before. `_compare` reads `_last_decided(full, cut)`, which is in the kept set by construction.

**The risk.** The first run now never calls `snapshot()`. If `snapshot()` had a side effect, that first run, and so its cuts, could differ.

**What I ran.** For every strategy, on its first market (S05's long market among them), on both lines of the test:

- three runs, with registers at every close, at none, and at the kept closes only;
- each compared on events, on the cut lists, and on the registers at the kept closes.

**Result.** 20 of 20 identical. Nothing that was compared before is skipped now. The every-bar comparison of each timeframe is unchanged by the diff.

## 9. Funding to net and the two C15 tests

- **Funding to net.** The tests compare against hand values in cents, for all four signs:
  - 10 units with a 0.1% settlement at a mark of 100 make 1.00;
  - a long pays a positive rate and a short receives it;
  - every row that prints net shows gross less funding, and the 2x and 3x cost lines leave funding unchanged.
- **The C15 eligible-bars test.** It derives its expected set from the bars that reach the end or the read day. It then also holds every kept bar to `left_out_reason`.
- **The C15 quarter test.** It works its quarters by hand.

All passed in the 239 below.

## 10. The developer's open readings

| Reading | Ruling | Why |
|---|---|---|
| `connection` is every failed transfer that is not a timeout, including a 500 or 503 after its attempts | `accept` | `_reason_of` gives `timeout` for a timed-out connect or read, and `connection` otherwise. The word holds no host text |
| The 429 change makes the archive ingest and the Kraken poll stop at a 429 rather than retry | `fix`, for the ingest | The poll does stop. The ingest goes on to every later task: RC2-03 |
| `stop_reason` is a new key that plan section 7.2 does not list, and `candle_check.json` is unchanged | `accept` | `data-steward` adds the key to section 7.2 |
| R-01: a trade across a logged stretch carries no flag of its own. Before the first row and after the last, the nearest row's interval is assumed | `accept`, for the first span | F2 stops stage one on any interval other than 8, so neither can act on this run. Before a block whose F2 is not clean is used, flag such a trade and give the edges the same care |
| C16 at `ecc5e49` has no leak verdict, and no leak is expected | `accept`, on correctness. The verdict is `leak-auditor`'s | Every price is rounded with the tick at the instant it is set (section 3). `MarketView.tick_at` refuses an instant after its close. A leg's `tick_i` is fixed when its price is set |
| S07's band target holds a `fill + r` term inside a `max` computed at a close, rounded with that close's tick | `accept` | It is a target update, which C16 sets at its decision. C16's "`fill + x * R` term" is a target computed at the fill. S07 does not run on candles. `strategy-architect` may confirm |
| F5 is the whole hour nearest `calc_time`, off 00:00, 08:00 and 16:00. F4 counts only settlements on that grid. K2 to K4 need ticks that are powers of ten | `accept`, with RC2-01 fixed | With F4 beside it, this is the venue facts' F5. A tick that is not a power of ten fails each candle task with a `ValidationError`, loudly |
| S05's long market was picked for its setups and for the back door showing on it | `accept` | Stated openly, and picked for coverage, not for any result. `leak-auditor` owns the call |
| R-02 was built differently from the literal fix | `accept` | Section 4. RC2-04 is information |
| Item 9 lives in `run_ingest`, not in `candle-check` | `accept` | Stage one is where every first-span file passes, and the raw text can be deleted once a file is curated |

## 11. Mutation sample

I reverted seven fixes, chosen by me, each in its own copy of `be20ee7`, and ran the tests named for each. A kill counts only on a failed assertion.

| Mutant | Tests | Outcome |
|---|---|---|
| C7: the old `H > Ti`, with no tick margin | `tests/engine/test_dated_tick.py` | Killed, on an assertion |
| C16: `BE+` left at the fill's rounding | `tests/engine/test_dated_tick.py` | Killed, on an assertion |
| C7: a moved target keeps its old `tick_i` | `tests/engine/test_dated_tick.py` | Killed, on an assertion |
| R-01: a disagreeing stretch names settlements again | `test_recheck_fixes.py -k r01` | Killed, on an assertion |
| R-02: the first side draws freely again | `test_recheck_fixes.py -k r02` | Killed, on an assertion |
| K1: a third decimal passes | `tests/data/test_venue_checks.py` | Killed, on an assertion |
| Coverage: a checksum mismatch fails its quarter again | `test_date_guard.py -k checksum` | Killed, on an assertion |

## 12. Commands and output

Run from the frozen copy of `be20ee7`, with `PYTHONPATH` set to the copy, or for mypy to the short junction.

```text
$ ruff check src tests
All checks passed!
$ ruff format --check src tests
118 files already formatted
$ mypy src
Success: no issues found in 72 source files
$ python -m pytest -q tests/engine/test_dated_tick.py tests/engine/test_recheck_fixes.py tests/data/test_venue_checks.py tests/data/test_source_switches.py tests/engine/test_tape.py
239 passed in 250.15s (0:04:10)
$ python -m pytest -q tests/data/test_date_guard.py -k "stop or 404 or published or checksum or 12_hex or 17_6 or refusal or ra02 or reason"
31 passed, 61 deselected in 89.45s (0:01:29)
```

| Probe | Checks | Deviations |
|---|---|---|
| Dated tick in the simulator, long and short | 32 | 0 |
| A target from the fill across the change, with the real `V0S` wrapper, long and short | 8 | 0. A first pass showed 1, and it was my own hand value: the short fill is 39995.630037, not a mirror of the long |
| R-01 | 11 | 0 |
| R-02 against brute force, and uniformity | 5 | 0. RC2-04 is measured there |
| R-02, `1c2dc23` against `be20ee7`, 10,000 draws | 3 counts | Section 4 |
| Checks after the fetch, on generated files | 27 | 1: RC2-01 |
| A stop, then a run inside the retry wait | 2 | 1: RC2-02 |
| A 429 through stage one | 3 | 0 failed checks. The behaviour is RC2-03 |
| `hft-crypto ingest` loading the tick tables | 3 | 0 |
| Cut harness, registers at every close, none or kept | 20 | 0 |
| The whole command on both commits | 11 files | Only the manifest hash and the new keys, which are empty |
| Mutation sample | 7 | 7 killed, on an assertion |

## 13. What I did not check

- **The full suite,** which the coordinator is running.
- **`tests/leak` in full.** In its place, I ran the purity probe of section 8 on all ten strategies.
- **Real Binance files.** Whether a stamp ever falls before its hour (RC2-01), whether the 2020 funding files carry F1's header, and how long prices off the 0.1 grid last after the change (K3).
- **A 200-draw placebo run.** The whole-command comparison used 12 draws per default line.
- **What the funding interval column means.** It stays `UNVERIFIED`, and no file in scope can show it.
- **`CYCLE` mode's `t_cut` as the instant a price is set.** `CYCLE` is not built.
- **The leak verdict on C16 at `ecc5e49`.** That belongs to `leak-auditor`.
