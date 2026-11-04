# Leak audit: data center code

Date: 2026-11-04. Auditor: `leak-auditor`. Artifact: `src/hft_crypto/`, `tests/leak/` and `configs/` at commit `b874055`. Read: `CLAUDE.md`, charter section 3,
`08_DATA_CENTER.md`, conventions C2, C3, C4, C12 and C17 in `01_strategies/00_INDEX.md`, and the earlier leak audits.

All data in this audit is generated, and all prices are invented. No source was contacted. Adapters ran only on generated files, with sources switched on in an in-memory copy of the
configuration, so every source in `configs/` stays disabled. Probes and mutated copies of the code were kept outside the repository. Nothing here says anything about a market or a strategy's merit.

## 1. Verdict

**`FAIL`.**

The bar arithmetic is causal. Built on an explicit grid, as production calls it, truncation invariance and future perturbation hold on every configured timeframe, no higher-timeframe bar is visible
before it closes, and the report's calculations cannot read a later bar.

The data layer fails on what it can hand a later strategy:

1. **A hole looks like a quiet market.** `gap=False` with zero volume means both "proved empty" and "nothing known". A stop touched inside a hole is touched in no bar. C17 requires a test that this cannot happen, and it would fail (DC-01, DC-02).
2. **A bar's volume can hold fills from after its close,** on any source whose row carries one stamp over an interval. `knowable_time = close_time` does not stand for those rows (DC-03).
3. **Receive time is recorded and not enforced.** The default is the optimistic path, and nothing makes a consumer filter (DC-04, DC-05, DC-06, DC-07).
4. **A day's existence depends on what happened later that day,** through reconciliation (DC-08).
5. **`tests/leak` would not catch several real leaks,** including a one-bar look-ahead on the path production uses (DC-11).

Nothing has leaked into a result, because no strategy exists and no source is enabled. This verdict is about what the layer would do once a source is enabled. No strategy, feature or `decide` code
should be built on it until the two `HIGH` code findings and DC-03's ruling are dealt with and re-audited. Section 5 gives the order.

**Severity** is used as in the earlier audits. `HIGH`: a faithful reading makes a decision or fill depend on data not available at that time. `MEDIUM`: one plausible reading leaks, or a selection, fill or
accounting rule favours the strategy. `LOW`: no future data enters on any reading I found, or the effect is small, but the rule is ambiguous, not reproducible, or leaves a wrong audit trail.

## 2. Findings

| ID | Location | Leak class | Scenario with times | Severity | Fix |
|---|---|---|---|---|---|
| DC-01 | `data/poll.py` `poll_symbol`, `_emit_bars`. `bars/core.py` | Hole passes as zero-volume minutes, live path | Four reproduced cases. **(a) Failed pass.** At the 13:23 run, page 1 shows ids jump from 101 (12:00:20) to 150 (12:30:30), and page 2 fails. `gap_closes` is a local variable and dies with the run. The 14:23 run emits 12:01 to 12:30 with `gap=False` and logs no gap. The 1h bar closing 13:00 says `complete=True`, `gap=False`. The catalog holds the gap, and no bar reads it. **(b) Tail.** Last trade 13:03:10. The 13:23:05 run emits 13:04 to 13:22 as empty, on wall-clock time and a short page, with no proof. If the next id then jumps (stamped 13:40:30), those 18 minutes can never be flagged, because emitted rows never change. If ids run on and a print at 95 stamped 13:10:30 arrives late, the bar closing 13:11 stays empty and the 1h bar closing 14:00 shows a low of 100. A long stop at 98 is touched in no bar, and the only trace is `late_trades = 1`. **(c) Before the first trade.** After a lost cache the cursor starts 03-01, and the source's reachable history starts 03-20. All 19 days of minutes come out with zero volume, `gap=False` and no `DATA_GAP`. **(d) Time budget.** A jump's last minute, 12:31, lies past `safe_end`, so that partial bar comes out `gap=False` | `HIGH` | Emit only through the earlier of `t_cut` and the minute before the newest trade held. Minutes after the newest trade wait for a later row. `_emit_bars` reads gap ranges from the catalog, not a local variable. With no previous id, minutes before the first row are `gap=True` and logged `DATA_GAP`. A late row appends a correction record with its receive time, which C17's "bars that arrive later" reads, and never rewrites a bar. Add a 1m column `empty_proof` with values `traded`, `id_run` and `none`, with `gap` true on `none`. A higher bar with any gap minute has `complete=False`. Add C17's required test |
| DC-02 | `data/derive.py` `derive_day`. `data/parsers.py` `parse_agg_trades`, `parse_bybit_trades` | Hole passes as zero-volume minutes, archive path | **(a)** A generated trade file lacks 13:10 to 14:40 and everything after 18:00, on a venue with no official candles, which today is every venue but the one `D-17` bans. Task `done`, check `pass`, 450 minutes with `gap=False`, 1d bar `complete=True`, `gap=False`. A backtest long with its stop inside 13:10 to 14:40 never reaches `GAP_UNRESOLVED`, and `ATR` never re-seeds under C3. **(b)** Aggregate ids skip across the same hole, and the source's candles share it. The parser counts `id_breaks = 1` and warns, reconciliation passes, and the bars carry no flag. **(c)** `parse_bybit_trades` sets `trade_id` to the row number, so ids run unbroken across any hole and would pass a continuity test | `HIGH` | Add a required per-source key `continuity`, either `trade_id` or `none`, with no default. With `trade_id`, keep the real id and flag every minute from the last row before a skip through the first row after it, using the neighbouring files at the day's edges. With `none`, every empty minute is `gap=True`, as C2 says. Rename the row number `file_row`. Same column and test as DC-01. At G1, report empty minutes with and without proof per source |
| DC-03 | `data/parsers.py` `parse_agg_trades`. `bars/core.py` `build_bars_1m`. `configs/pipeline.toml` `[latency]` | Window extends past `t`. A decision depends on a print after its own fill | Invented numbers. Bar `(11:59, 12:00]`, rule `buy_volume >= 12`. Order 2 fills 1.5 at 11:59:59.950 and 1.5 at 12:00:00.046, delivered as one row of 3.0 stamped 11:59:59.950. `visible_bars` at 12:00:00.000 shows `buy_volume` 13.0, knowable 12:00:00.000. What had printed by then is 11.5. The rule says enter on the feed and not on the truth. Under `IDEAL` the fill is the next open, stamped 12:00:00.010, before the print that decided it. Changing only the fill at 12:00:00.046 changes a value visible at 12:00:00.000, which is a direct future-perturbation failure. Charter item 5 ("trades already completed") and item 6 (declared allowance) are both broken | `HIGH`. Dormant, as no enabled source makes such rows, and bounded by the span | See ruling 2 in section 3 |
| DC-04 | `bars/core.py` `visible_bars`, `assert_knowable`. `data/atomic.py` `read_parquet` | Timing depends on the consumer remembering | A feature reads the 03-01 polled part for a decision at 12:00 on 03-01 and gets 758 of 1,440 rows not knowable until later, with no error. `visible_bars` is called only by the report. `assert_knowable` and `TimingContractError` are called by nothing in `src/`. Trades have a `knowable_time` and no filter at all. Also, a `book_depth` row stamped 14:20:30 is knowable at 14:20:31, so a `.L` gate at a 14:21 run passes the timestamp audit, though C17 says a run sees no book | `MEDIUM` | One read API for later code: `bars_for_run` and `trades_for_run` (DC-07). `decide` gets frames and holds no root, as the third recheck asked. A test fails if strategy or feature code imports `read_parquet`. `DatasetSpec` gains `live_eligible`, and `.L` reads refuse a dataset without it. `assert_knowable` runs on every join |
| DC-05 | `bars/core.py` `build_bars_1m(knowable_at_us=None)`. `data/poll.py` `rebuild_day_bars`. `data/derive.py` | Optimistic default | Polled trades carry their receive time, and `build_bars_1m` ignores that column. With default arguments on those trades, knowable is the close on every row, and the public `rebuild_day_bars` returns exactly that. `derive_day` on a day of polled trades moved the 1h bar closing 13:00 from knowable 13:23 to 13:00, with state `done`. The global `--now` flag also reaches `poll` and `ingest`, so a run with a fixed clock stamps receipts at that time | `MEDIUM` | Make the argument required. A bar's knowable time is the latest of its close plus the allowance, the run's receive time, and the newest `knowable_time` among its trades. `rebuild_day_bars` returns a comparison frame with no `knowable_time` column. `derive_day` refuses trades whose `knowable_time` is later than `ts` plus the allowance. `poll` and `ingest` refuse `--now` |
| DC-06 | `data/poll.py`. `data/ingest.py` `run_archive_task`. `data/zones.py` | Later archive replaces live values | Only an environment variable in each workflow keeps the poll and the archive apart, and `03_DATA_SOURCES.md` recommends one venue for both. Under one root, the poll runs at 03-02 00:23 and ingest then runs. The trade part is overwritten and all 1,410 receive times are gone. The bar closing 12:00 on 03-01 moves from knowable 03-02 00:23 to 03-01 12:00. Status is `ok`, with no error, warning or reconciliation row. The bars were rebuilt from the polled trades while the next day was processed, and `needs_derive` then called the day done. So 09:00 to 09:30 shows no trades in its bars, over 31 stored trades, one of them at 90 | `MEDIUM` | The poll writes its own datasets: `trades_live`, `bars_1m_live` and `_live` higher timeframes. Archive code has no name that reaches them, so a shared root is harmless. A trade part replaced under existing bars reopens the derive task |
| DC-07 | `data/poll.py`. `bars/core.py` `visible_bars`. `.github/workflows/live-poll.yml`. `configs/pipeline.toml` `bar_grace_s` | Run clock not implemented. One filter for two clocks | Run starts 14:21:05 and the fetch ends 14:21:09, so `t_cut` is 14:20 and `t_dec` is 14:22:05. `visible_bars` at `t_cut`: polled 0 rows, archive through 14:20. At `t_poll`: polled 0 rows, archive through 14:21. At `t_dec`: polled through 14:20, archive through 14:22, two bars C17 forbids. No single value gives both paths the same bars, and the one that makes live work leaks in the backtest. `safe_end` is not `t_cut`: with a 5 s fetch it is a minute earlier for 75 percent of start seconds, so step 1 finds a missing bar, and with a 120 s fetch it is later for all of them. `lateness`, if read from a polled bar's `knowable_time`, is -4 s where the archive gives +65 s, which hides the hour the cycle costs. No per-source `t_poll`, skew or evidence is recorded, and `caught_up` means only a short page. The cron is minute 23 where C17 freezes minute 7, and `bar_grace_s` is 60 s where C17 freezes `A` at 10 s | `MEDIUM` | Build C17 step 0 here: `t_poll` per source at the start of the attempt, `t_cut`, the evidence check with one step back, `DATA_GAP`, skew, all logged. Remove `bar_grace_s`. Add `bars_for_run(bars, t_cut, t_dec)`: close at or before `t_cut`, knowable at or before `t_dec`, raising otherwise. In a backtest the modelled fetch stamps bars knowable at the modelled `t_poll`. Events use a named bar close time for `lateness`. Settle minute 7 or 23 by a documented edit before the first run |
| DC-08 | `data/derive.py` `_remove_day_outputs`. `bars/reconcile.py`. `configs/pipeline.toml` `boundary_window_ms` | Future perturbation through a dataset. Selection on outcome-linked state | One aggregate of 5 units late on 03-01, with 2 units in the official candle after midnight. Stamped 200 ms before midnight, 480 bars are visible at 03-01 08:00. Stamped 300 ms before, both days fail and all their bars go to quarantine, so none is visible at 08:00, because of an event 16 hours later. A long aggregate is likeliest in a burst, so this could remove the days on which stops fill worst. That link is a hypothesis, not a measurement. A 500 ms window brings the same days back, so `boundary_window_ms` picks the sample. A failed day also stays failed with a good file published: candles run first, re-derive on the old trades, and reset the trade file's retry. It was still failed in three later passes | `MEDIUM` | Keep a failed day's bars readable. Flag from the first boundary the check cannot explain, which `running` already gives, so earlier minutes do not depend on later data. Quarantine a whole day only for a structural failure such as a checksum or parse. Append each exclusion, with date, reason and tolerance, to a log. Count exclusions in every result, and treat a position open across one as `GAP_UNRESOLVED`. Declare the window under C12: see ruling 7 |
| DC-09 | `data/live_checks.py`. `bars/reconcile.py` `cross_venue_check` | Backtest sees what live did not, unreported | `08_DATA_CENTER.md` says each day's live bars are reconciled against that day's archive. No code does this. `poll_rebuild` compares the poll with its own trades, so a trade the poll never received cannot show. `cross_venue_check` passes with volume doubled, 5 extra trades a bar, lows 10 percent lower and closes 10 bps away. A backtest can hold a stop touch or a setup the live run never saw, and any bar difference carries on through recursive `ATR`, where C3 says live and backtest match exactly | `MEDIUM` | Add `compare_live_with_archive`, same venue only, on trade count, volume, high, low and close per bar, with a daily status. `cross_venue_check` refuses a same-venue pair. Its output feeds the G8 mismatch report |
| DC-10 | `data/poll.py`. `data/zones.py`. `08_DATA_CENTER.md` section 3 | Repaint through a rebuild | Bar closing 13:11 is emitted with volume 0, knowable 03-01 13:23. A late print at 95 arrives. The cache is lost and rebuilt at 03-03 06:23, and the same bar now has volume 9, low 95, knowable 03-03 06:23. Knowable time stays honest: an as-of read at 03-01 14:30 returns no rows. So a G8 replay has to read by close time, and then sees a print the live run never had. The daily check now says `pass`. `curated` is class `DERIVED`, "rebuilt rather than patched", yet polled receive times and first-emitted values exist nowhere else: no code writes `raw/live` | `MEDIUM` | Log a hash of each run's emitted rows in the run log, which is on the results branch. Mark rebuilt rows `emission = "rebuild"`, and have `poll_rebuild` return `not_applicable` for them. G8 replays use as-seen inputs from `decisions/`, never rebuilt bars. C3's "match exactly" should say it holds only with no late or missing trades |
| DC-11 | `tests/leak/test_bars_leak.py` | Tests cannot see the leak | See section 4 | `MEDIUM` | Run on the paths production uses: an explicit grid, `derive_day` and `run_poll`. Use every minute as a cutoff, not seven. Cover every configured timeframe. Use sparse data with long silences. Add a fill-level generator for DC-03, and C17's hole test |
| DC-12 | `bars/core.py` default grid, `aggregate_bars` | Higher bar computed before it closes. A row that exists because a later trade exists | With no grid, the way `tests/leak` calls it, trades up to 12:04:30 give a 5m bar closing 12:05 with `complete=True`, `gap=False`, knowable 12:05, volume 5. The finished bar has a high of 500 and volume 45. A row held from 12:04:30 shows neither at 12:05, while the docstring says an unfinished bar can never be seen. At 12:05, a bar in a silence exists only if a later trade is in the data, so truncation differs on 359 of 2,144 comparisons. The project's own test fails 19 of 35 cases when given 40 trades in place of 3,000. No production caller uses this path | `MEDIUM` | Make `first_close_us` and `last_close_us` required. `aggregate_bars` takes `through_close_us`, the last minute known to be closed, and emits nothing past it |
| DC-13 | `data/parsers.py`. `configs/pipeline.toml` `[latency]` | No declared allowance | Item 6 asks for a declared allowance where receive time is unknown. Archive trades have `knowable_time = ts`, and none is declared. A flow window at 12:00:00 reads a row stamped 12:00:00 as known at that instant. `book_depth_allowance_s` covers only the truncated stamp and no publication delay. Modes that wait `A` are safe at 10 s | `LOW` | Use the per-source allowance from ruling 2 for trades and funding. Say in configuration what each allowance covers |
| DC-14 | `data/catalog.py` `put_reconciliation`, `register_file`. `reports/report.py` run record | Evidence overwritten. Revised data dated at the original close | A day fails on 03-03, candles are corrected, and it passes on 03-05: the fail row no longer exists. A good day delivered again moves a close from 100.0 to 100.4, knowable time stays at the original close, the old hash is overwritten, and no event is written. A run's manifest lists paths and no hashes, so two backtests can differ with no trace | `LOW` | Keep reconciliation and file hashes in append-only history. A changed hash on a known partition is an event and an alert. Manifests carry hashes |
| DC-15 | `reports/report.py` `build_status`, `summarise_poll`, `build_benchmark` | Status fields not as of the stated time | A report stated at 03-06 12:30, with a fixed clock, on a root holding later work: the benchmark is clean, but reconciliation counts 12 days and `live_poll` shows a run on 03-15 with an age of -213.88 hours. Separately, a day with one flagged minute has `complete=True` and counts as whole, and only the newest day's gap is reported | `LOW` | Filter by `checked_at` and `job_started_at` at or before the stated time. DC-01's meaning of `complete` settles the second point |

## 3. Rulings on the seven questions

### 1. Bars and knowable time

**Correct on the production path, for every field but the one in DC-03.** A 1m bar is knowable at its close, or at receipt on the poll path. A higher bar is knowable at the later of its close and its newest input, so a 1h bar closing 13:00 is knowable at the 13:23 run.

My own tests, written without reading from `tests/leak`, at four trade rates from 0.05 to 20 a minute, on 1m and all seven configured higher timeframes, with cutoffs on, one microsecond either side of, and inside minutes:

| Path | Truncation: differences of comparisons | Perturbation: differences of comparisons | Bars visible before close |
|---|---|---|---|
| Explicit grid | 0 of 2,144 | 0 of 2,144 | 0 |
| Default grid | 359 of 2,144 | 0 of 2,144 | 0 |
| `derive_day`, 30 cuts, 8 datasets | 0 of 240 | 0 of 240 | 0 |
| Real poll runs, hourly over 2 days, 4 cuts, 5 datasets | 0 of 20 | 0 of 60, on 3 seeds | 0 |

The default-grid failures are DC-12. A higher bar seen before it closes is safe only with a grid. On rows alone these tests cannot see DC-03, because the row is the whole truth they are given.

### 2. Aggregate trades

**Ruling: `knowable_time = close_time` does not stand for any source whose row carries one stamp over an interval.** It is not specific to one venue. It depends on the shape of the row.

**Does the volume include a moment after the close?** Yes. The whole row's quantity sits in the bar of its first stamp, so `volume`, `buy_volume`, `sell_volume`, `quote_volume` and `fill_count` can hold fills from after the close. It moves one way only, late and never early.

**The consequence for a decision at that close** is the DC-03 scenario. Under `IDEAL`, which C6 and the mode table define as a decision at the close with zero allowance and a fill at the next open, a rule reading any volume field can flip on a fill that came after the close, and after the fill reference. That reaches `SRV_k`, VWAP, volume profile, buy and sell flow, and S09's volume check. Under `IDEAL-1M` and `CYCLE`, the value is known before the fill, provided `A` exceeds the span, which at 10 s it should by a wide margin.

**Which fields are affected depends on the row:**

| Row shape | Volume fields | `H`, `L` | `O`, `C` | Where it could occur |
|---|---|---|---|---|
| One price, one stamp, summed quantity | After-close fills | Clean | A real print at or before the close, possibly not the last one | The `parse_agg_trades` adapter, `n_fills > 1` |
| Several prices, one stamp per taker | After-close fills | After-close prices, if the walk takes time | After-close prices, same condition | The poll adapter's own comment says a taker's fills share one stamp. Whether that hides elapsed time is `UNVERIFIED` |
| Stamp floored to a coarse resolution | After-close fills | After-close prices | After-close prices | Any file with coarse stamps. Which candidates have them is `UNVERIFIED`. `bookDepth` already has this, and it is the reason for its allowance |
| Batched publication under one stamp | As above, by batch | As above | As above | The charter records batching at one venue. `UNVERIFIED` for trade stamps |

On generated fills, a one-second floor changed volume on 351 of 1,440 bars, the high on 85 and the close on 189, and flipped a threshold on 39. These rates mean nothing for any venue. They show which fields the class reaches.

**Is an allowance enough?** For knowability in `IDEAL-1M` and `CYCLE`, yes, on four conditions. For `IDEAL`, no. An allowance also does not make the volume a true `(open, close]` sum, so a live feed and an archive with different row shapes will differ at boundaries, which only DC-09 would show.

**What must change:**

1. **Charter item 1 and C2 gain a sentence:** a bar built from rows with one stamp over an interval is knowable at its close plus the source's declared span. Owners: `project-manager`, `strategy-architect`.
2. **Required per-source configuration, with no default:** `stamp_kind` and `fill_span_allowance_ms`, covering the span and the stamp's resolution. The value is `UNVERIFIED` until measured on the approved source, including stressed days. One day on any source is not a bound, and zero is a valid value only once measured. Owner: `data-steward`.
3. **In the data, not in the consumer's memory:** a trade's `knowable_time` is `ts` plus the allowance, and a bar's is its close plus the allowance, or receipt if later.
4. **For `IDEAL`:** add `settled_volume`, `settled_buy_volume`, `settled_sell_volume` and `settled_quote_volume`, leaving out rows with `n_fills > 1`, or in a same-stamp group, stamped within the allowance before the close. Those rows count in the next bar's settled columns. `IDEAL` reads only these columns, through the read API of DC-04, and the C17 mode table says so. A source where prices can carry an after-close print, the second and third rows above, gets no `IDEAL` results, only `IDEAL-1M` and `CYCLE`.
5. **For `IDEAL-1M` and `CYCLE`:** assert `A >= fill_span_allowance_ms` at the start of a run.
6. **A detector that fails closed:** `reconcile_official` already reports `largest_window_needed_ms`, and nothing compares it. If it exceeds the allowance, the allowance is false: alert, and stop using it. That does not remove the day (DC-08). No official candles means no detector, which today covers Bybit and Kraken in the configuration, so `IDEAL` on volume stays blocked there until some other evidence bounds the span.

I keep this at `HIGH` because the scale does not depend on size, and because no test on rows can see it. It is due before the first result from any source with such rows, and every candidate source needs the row-shape check before `IDEAL` is trusted on it.

### 3. Polled bars

**Recorded: yes. Enforced: no. It depends on the consumer remembering.** `knowable_time` holds receipt time on every polled trade and bar at every timeframe, first receipt stands, and an emitted bar is never rewritten by a later poll. As-of reads through real runs are stable: 0 of 20 differ with later data removed, and 0 of 60 with it scrambled. But nothing makes anyone use them (DC-04), the default is the optimistic path (DC-05), and a same-named archive can overwrite them (DC-06).

**Not consistent with C17** (DC-07). There is no `t_poll` per source, no `t_cut`, no evidence check, and no marking of empty minutes in a fetch stage, and `bar_grace_s` stands where C17 has `A`. Receive time is taken after the last page and after the trades are written, which is later than C17's `t_poll`. That direction is safe, but it means no polled bar from a run is visible at that run's own `t_cut`.

**The two rules are not in conflict, once named.** Contract item 1 says when a value could exist. Receipt says when this system had it. C17 cuts by close time and acts at `t_dec`. So later code needs both conditions, `close_time <= t_cut` and `knowable_time <= t_dec`, in one function, which is `bars_for_run`.

### 4. Gaps

**No.** The bar code can tell an empty minute from a missing one in one case only: an id jump found in a pass that also reaches its emission. Otherwise `trade_count = 0`, `gap = False` means both things. No column records proof. DC-01 and DC-02 hold the reproduced cases. The logic also runs the wrong way round for C2: the code assumes empty unless disproved, and C2 says a gap unless proved.

The third recheck asked that code take the fail-closed reading of "overlapping pages", and that empty-minute marks hold with data after `t_poll - A` removed. Neither can be tested until marks exist.

### 5. Reconciliation and repairs

**Reconciliation never changes a bar:** with candles at a wrong price of 50, bars are byte-identical to a build with no candles. Late polled trades do not repaint an emitted bar. **Nothing backfills or forward-fills.** `src/` has no `forward_fill`, `backward_fill`, `interpolate` or `shift`. `fill_null` and `fill_nan` only convert between null and NaN, or sit inside a comparison. An empty minute keeps null prices, and open and close of a higher bar come only from inside that bar.

**A later archive can still change what a backtest sees, silently,** in four ways: a shared root (DC-06), no same-venue comparison (DC-09), a poll rebuild (DC-10), and a re-delivered file (DC-14). On the workflows as they stand, with two roots, the first does not happen. The others do. A failed reconciliation also deletes a day (DC-08), which is the opposite of a repair and more of a concern.

### 6. Report and status output

**The report's calculations cannot read a bar after their stated time.** A benchmark stated at 03-06 12:30 was identical on three roots: later days present, wild prices after that moment, and nothing delivered after it. Its newest mark is at or before the stated time. `site.py` reads no files. **Status fields other than bars are not as of that time** (DC-15), which matters only with a fixed clock.

### 7. Selection hygiene

**No date, venue or threshold in the code or configuration is chosen from returns.** Start dates are stated as limited by the cache. The venue recommendation in `03_DATA_SOURCES.md` rests on terms and cost. Retention's sample day is a calendar rule, and catch-up order depends on age and budget. `cross_venue_check` thresholds set a status and remove nothing.

**The Binance-informed design: a recheck, and in one respect more than a recheck.**

- **The reconciliation rule's design** needs only a recheck on the approved source, as `D-18` says. It reads no return and feeds no strategy, and what was seen carries no direction. The claim "it only moves that way, never the other" is a property of that source, and must be tested again, not assumed.
- **The 250 ms placeholder is more than that, because today it decides which days exist** (DC-08). That makes it a sample filter, and so an object under C12. Raising it until every day passes, across a whole history, fits it on the full sample and lets later data decide which early days exist. Lowering it can remove bursts. So it is a declared constant, frozen before the first `V0` run from data outside any test block, and a change is a counted trial. Once DC-08 is fixed and a failure no longer removes a day, only the recheck remains.
- **The span allowance** of DC-03 and this window should be one source-level constant, since both bound the same mechanism.
- **`bar_grace_s`, the row shapes and the `A` value** must also come from the approved source. The generated end-to-end run limits its spills to 80 ms, below the window, so it never exercises the failing path, whatever that value was based on.
- **Days already seen:** nobody saw a strategy result on them, so they need no exclusion. The fold plan under C-7 should still record which dates were looked at during the build.

**Not yet frozen:** configured start dates, `poll.start_date` and the tolerances should be covered by C-5's commit before the first run.

## 4. Do the leak tests catch a leak?

**Partly.** `tests/leak` catches a blunt leak that lands on one of its seven cutoffs, and its vacuity guard and walk through higher bars do what they say. But it reaches only `build_bars_1m` with no grid, and `aggregate_bars`. It never passes a grid or calls `derive_day`, `run_poll` or the report, and its data has 2 empty minutes in 480. It passes on that data only because the data is dense (DC-12).

I injected 30 leaks, one at a time, each into its own copy of the code, then ran `tests/leak` and the rest of the suite. Fifteen workflow and git tests also fail on an unmodified copy, because a copy has no `.github` or git, and they are left out of these results.

| Result | Count | Injected leaks |
|---|---|---|
| Caught by `tests/leak` | 10 | 1m bar knowable at its open. Receive time ignored on 1m bars. `visible_bars` filtering on close time. `visible_bars` looking one minute ahead. Trades placed one bar early. 1m close peeking at the next minute. Volume scaled by the whole sample. Unfinished higher bar emitted. Higher bar knowable at its first minute. Higher close peeking past its bar on every timeframe |
| Missed by `tests/leak`, caught by a focused test elsewhere | 14 | Empty minute backfilled from the next trade. Empty minute forward filled. Higher bar dropping receive time. Poll bars knowable at close. Poll receive time an hour early. Poll emitting the minute in progress. A late trade repainting an emitted bar. Polled trades knowable at their stamp. Poll gap flags dropped. Official volume replacing trade volume. Last bar of a day not flagged. Aggregate rows stamped 500 ms early. Archive trades knowable an hour early. Report daily bars read with no as-of filter |
| Missed by `tests/leak` and every focused subset, caught only by accident | 2 | A 1m close peeking one minute ahead on every bar, when a grid is passed, which is how production calls it. The same peek placed only in `derive_day`. One end-to-end test fails, because it compares polled bars with a rebuild and with a second generated market. It checks agreement and not timing, and the one-in-seven peek below passes it |
| **Missed by the whole suite** | 3 | **A 1m high peeking one minute ahead on one bar in seven,** which no cutoff lands on. **A higher close peeking one minute past its bar on 240m only:** no cutoff sits on a 240m close, and the repaint test skips 240m. **The same on 30m, 120m and 1440m,** which the configuration uses and the leak tests do not cover |
| Missed by `tests/leak` and the focused subsets, not run on the whole suite | 1 | Report equity marks read with no as-of filter. On archive bars a second filter on close time makes this harmless. On polled bars it would matter |

None of these tests can see DC-01, DC-02 or DC-03. The hole tests C17 requires do not exist, and a row-level generator gives no way to express a fill after a row's stamp.

## 5. What must change, and when

| When | What | Owner |
|---|---|---|
| Before any strategy, feature or `decide` code | DC-01, DC-02, DC-04, DC-05, DC-07, DC-11, DC-12 in code. DC-03's charter and C2 text, with its configuration keys and columns | `developer`, `strategy-architect`, `project-manager` |
| Before a source is enabled | DC-06, DC-08. The row-shape check of ruling 2 on that source, and `continuity` declared | `developer`, `data-steward` |
| Before the first `V0` run | The window frozen under C12. C-5 extended to the tolerances | `project-manager` |
| Before gate G1 on the chosen source | DC-09. Empty minutes with and without proof reported per source. DC-13 | `developer`, `data-steward` |
| Before the first `CYCLE` run | DC-10. Minute 7 or 23 settled | `developer`, `strategy-architect` |
| With the next pass over these files | DC-14, DC-15 | `developer` |

**Re-audit needed:** the changes for DC-01 to DC-08, DC-11 and DC-12, with my probes rerun against them. The rest can wait for their due dates.

## 6. Probes

Throwaway scripts, not in the repository.

| Probe | Result |
|---|---|
| Truncation and perturbation | See ruling 1 |
| Fill-level truth against rows | Worked example in DC-03. Future perturbation changes a value visible at the close. Row shapes in ruling 2 |
| Poll runs under C17's clock | `visible_bars` table and `safe_end` against `t_cut` in DC-07. With 1, 5, 20, 45, 55, 70 and 120 s fetches, `safe_end` is later than `t_cut` in 0, 0, 0, 0, 8.3, 33.3 and 100 percent of start seconds, and earlier in 81.7, 75, 50, 8.3, 0, 0 and 0 percent |
| Holes | Each case in DC-01 and DC-02. The one handled case flags 29 of 29 minutes. The others flag 0 |
| Reconciliation | DC-06, DC-08, DC-09, DC-10, DC-14 |
| Report | Ruling 6 |
| Mutation | Section 4 |

## 7. Checked and found clean

- **Boundaries.** `(open, close]` holds to the microsecond, on stamps exactly on and one microsecond either side of a minute. Timeframes align to the UTC day, so a 4h bar closes at 00, 04 and on to 20.
- **Higher bars.** Not emitted until their closing minute is in the input, on the grid path. Knowable never before close, on all timeframes and both paths. Missing input minutes give `complete=False`.
- **Polled receipt.** First receipt stands on repeated fetches, and it survives into every higher timeframe.
- **Official candles.** Knowable at open plus 60 s, not at their open label. Used only for checks.
- **Funding.** Knowable at its stamp, which is its settlement. No forward rate is read.
- **Fill or stale prices.** No price is carried into a bar that has none, and a higher bar with no trades has a null close.
- **Timestamps.** Parsed on digits, not through floats. They floor, which moves a stamp earlier by under a microsecond. That is the leak direction, and small enough to ignore.
- **No full-sample fit.** Nothing in `src/` estimates a value across a sample for use in a bar or a filter. The medians and percentiles there describe run timing and one day's check.
- **Synthetic isolation.** Real jobs refuse a marked root, and its calendar is before either asset existed.
- **Publishing.** `publish_results.sh` keeps every existing line of a log, and refuses to change a file already in `ledger/` or `decisions/`. No such files exist yet.

## 8. What I could not check

- **Any behaviour of a real feed.** Row shapes, spans, stamp resolution, publication lag, late trades and history limits for every candidate are unknown to me. I opened no source. Statements about them are `UNVERIFIED`.
- **The size of DC-03 on any market,** or how often a threshold would flip. Whether long aggregates cluster in bursts, which DC-08's bias depends on.
- **The shift test,** the label timeline and funding timing in accounting, because no strategy, label or accounting code exists.
- **`decide`, `settle`, registers, `ATR`, the ledger and its hash chain, Telegram output and the paper record,** because none exists yet. C4 and C17's required tests stay due on that code.
- **GitHub behaviour:** real cache restores, including an older cache coming back, and real run timing.
- **The real API behind the poll.** The hole probes use a fake source that follows the assumptions written in `poll.py`, and nobody has checked those on an approved source.

## 9. Notes for other reviewers

These are outside the leak question, or only touch it:

- **Stuck failed day** (DC-08): when candles and trades both exist and the trades were bad, the candle task runs first and re-derives on the old trades, which resets the trade file's retry. A good file is never picked up. Probe: three later passes.
- **Raw reuse:** on a machine that keeps `raw/`, `_fetch_raw` reuses the old file, so "fetched again later" does not fetch. A runner discards `raw/`, so GitHub is not affected.
- **`needs_derive`** returns false for a done day whose trade part has been replaced (DC-06).
- **`aggregate_bars` does not check venue or symbol.** It would merge two venues under the first one's label, against C1.
