# Code review: data center and pipeline

Reviewer: `python-reviewer`. Date: 2026-11-04. Branch `pipeline/first-data-run`, commit `b874055`.

Specifications: `docs/08_DATA_CENTER.md`, `docs/05_DATA_LIFECYCLE.md`, `docs/00_CHARTER.md` section 3, decisions
`D-10` to `D-18`. Everything ran on generated data and local fakes, on Windows. No market data source was contacted and
no dataset was downloaded. All probes lived outside the repository.

## 1. Verdict: `FAIL`

**Not safe to enable a source, and not ready for gate G1.** With the shipped configuration nothing can download, so none
of this can hurt anything today. The failures below are what would happen on the day a source is approved.

The core is sound. Bars, higher timeframes, catch-up, determinism and the benchmark arithmetic all matched
hand-computed values. The failures are around that core: what counts as a passing day, what a crash leaves behind, what
a bad catalog row can delete, and bars that look clean when nothing vouches for them.

Eight findings must be fixed first (`F-01` to `F-08`). Each one was reproduced with a probe.

| ID | Severity | Finding |
|---|---|---|
| F-01 | High | A catalog row with `..` in its path deletes the ledger, classed as `RE-DOWNLOADABLE` |
| F-02 | High | `execute_plan` and `delete_file` do not re-check the protocol, so a stale or forged plan deletes |
| F-03 | High | A 6-hour hole in an archive file gets `check_status=pass`, no gap record, and complete bars |
| F-04 | High | Reconciliation passes invented volume, lost volume and flipped sides. Other errors only warn, and the day is final |
| F-05 | High | One corrupt file kills the whole run, and blocks catch-up on every later run |
| F-06 | High | A crash during a rebuild leaves `bars_1d` wrong forever while `bars_1m` is right |
| F-07 | High | The poll emits permanent empty bars for minutes it never saw |
| F-08 | High | A gap found in one poll pass is not flagged on bars emitted by a later pass |
| F-09 | Medium | `NaN` and `inf` pass every parser |
| F-10 | Medium | With the shipped config nothing can be contacted. But the Binance ban holds against one edit only, and several configuration routes reach the host |
| F-11 | Medium | Retention fails open: no `requires` means no check, and `reviewed = "false"` means reviewed |
| F-12 | Medium | A report can publish a prohibited, disabled venue, labelled `MARKET` |
| F-13 | Medium | The `SYNTHETIC` label can be lost in three ways |
| F-14 | Medium | `publish_results.sh` trusts every path in the bundle, including `.git/config` |
| F-15 | Medium | The log merge removes existing duplicate lines, and accepts edited ledger lines |
| F-16 | Medium | Approving Bybit gives a green daily job that fetches nothing and alerts nobody |
| F-17 | Medium | Cache pruning crosses branches, and two copies of the cache can exceed GitHub's limit |
| F-18 | Medium | Alerts never reach the owner. The watchdog reads only `generated_at` |
| F-19 | Medium | The book validator fails a normal restart, and passes negative and `NaN` sizes |
| F-20 | Medium | Missing hourly marks shrink max drawdown silently |
| F-21 | Medium | The time budget does not bound the bar sweep or bar emission |
| F-22 | Medium | Specification clauses with no line of code |
| F-23 | Low | Smaller items, listed together |

## 2. High severity findings

### F-01: a catalog row with `..` deletes the ledger

`src/hft_crypto/data/zones.py:45-50`, `src/hft_crypto/data/retention.py:169` and `:235`,
`src/hft_crypto/data/guard.py:43`.

`classify()` reads the class from the text of the path. `guard.check()` normalises the path, confirms it is inside the
root, and its result is thrown away. So the class and the file come from two different paths.

**Probe.** Shipped policy, shipped reviewed rule. One catalog row, `raw/archive/../../ledger/events.jsonl`, kind `klines`,
correct checksum, with one passing child. `build_plan` selects it as `RE-DOWNLOADABLE`, and `execute_plan`, which is what
`retention --execute` runs, deletes `ledger/events.jsonl`. The same worked for `decisions/`, `raw/live/` and `curated/`.

The path the daily workflow really uses is also open. The row
`raw/archive/binance/klines/BTCUSDT/date=2026-11-02/../../../../../../ledger/events.jsonl` matches the prefix in
`ingest.py:492-495`, so `--delete-raw-after-curated` deleted the ledger file too. The deletion log recorded it as
`class=RE-DOWNLOADABLE`.

This breaks the header of `retention.py` ("the ledger, decisions and catalog zones are never selected") and the docstring
of `classify` ("a bad catalog row cannot make irreplaceable data look deletable"). The catalog is restored from the
Actions cache, so it is an input, and a bad row is exactly the case that sentence is about.

Normal code writes normalised paths, so this needs a bad or poisoned row. On a runner today `ledger/` and `decisions/` are empty,
because those records live on the `results` branch, so what is in reach there is `curated/` and `catalog/`. It stays High because
this is the only barrier, deletion cannot be undone, and an always-on machine would hold the real ledger under `DATA_ROOT`.

`test_catalog_paths_outside_the_root_are_refused` only tries to leave the root. `test_ledger_files_survive_even_if_catalogued`
passes because the rule's zone does not match the row, so it never reaches the class logic.

**Fix.** Refuse any catalog path that is not already canonical: `posixpath.normpath(p) == p`, no `..`, no backslash,
not absolute. Enforce it in `Catalog.register_file` and again in `_evaluate`, and make `classify` raise on a
non-canonical path. Add this row to the retention tests.

### F-02: the last gate before a delete does not check the protocol

`src/hft_crypto/data/retention.py:333-375`, `:405-415`.

`delete_file` checks that the rule is reviewed, the row is present, the path is allowed and the checksum matches. It does
not check that the rule covers the file, what class the file is, or the preconditions. `execute_plan` trusts
`item.data_class`, and its docstring says "every item goes back through the protocol at the moment of deletion", which
it does not.

**Probes.**

- A plan item for `ledger/events.jsonl` under `raw-archive-after-curated`: `deleted=1, refused=[]`.
- `delete_file(ctx, "ledger/e2.jsonl", raw_rule, data_class="RE-DOWNLOADABLE")`: deleted.
- A stale plan: build it, move the bars to quarantine, execute it. The raw file was deleted although its derived data is
  gone.

The command line builds and executes in one process, so the stale window is small today. Any later code that stores a plan
for approval inherits the hole, and deletion cannot be undone.

**Fix.** In `execute_plan`, run `_rule_applies` and `_evaluate` for each item and use the class they return. In
`delete_file`, refuse a file outside `rule.zone` and refuse `IRREPLACEABLE` unless the rule is a `raw/live` rule past its
retention.

### F-03: a hole in an archive file is invisible

`src/hft_crypto/data/parsers.py:157-175`, `src/hft_crypto/data/ingest.py:420`, `src/hft_crypto/data/derive.py:116-123`.
`add_gap` has one caller, in `poll.py:429`.

`_time_checks` measures `largest_time_gap_s`, `out_of_order` and `rows_outside_partition`, and nothing ever reads them.
`check_status="pass"` is a literal.

**Probe.** An `aggTrades` day with one trade a minute, and minutes 360 to 719 removed.

| Check | Spec requires | Result |
|---|---|---|
| Trades `check_status` | Not a clean pass | `pass`, warnings `[]`, `largest_time_gap_s=21660.0` |
| Catalog gaps | Recorded | 0 |
| 1-minute bars with `gap` | The 360 in the hole | 0 of 1440 |
| Hourly bars `complete` | False for the 6 hours | 24 of 24 true |

With official candles the volume check would catch this. Bybit, the only non-prohibited archive configured, has none
(`derive.py:130`), so there nothing can. A truncated or holed file looks like a quiet market, and a higher bar cannot be
`complete=False` on this path at all because the grid is always full. `aggTrades` id breaks are also only a note: a
break of 500 ids still gave `check_status=pass`.

This is lifecycle section 7 ("gaps in time", "gaps are recorded, never filled silently") and the G1 evidence "gap reports".

**Fix.** Give each dataset a declared `max_quiet_s`. Above it, call `add_gap`, set `gap=True` on the affected bars, and
store `check_status=warn`. Do the same for id breaks. Let `complete` mean "no gap in this bucket".

### F-04: reconciliation passes real data errors

`src/hft_crypto/bars/reconcile.py:100-112`, `:174-213`, `src/hft_crypto/data/derive.py:152-157`,
`configs/retention.toml:44-45`, `src/hft_crypto/reports/report.py:91`.

Yes, the rule can pass a real error. Day D-1 and D+1 were clean. Day D's official candles were the truth, and D's trade
file was corrupted. All of it went through `run_ingest` with raw deletion on.

| Error in the trade file | Status | Day state | Raw kept | Why |
|---|---|---|---|---|
| B. Invented 4 coins at 23:59:59.900 | `pass` | `done` | No | The window that excuses the trade contains the trade |
| A2. Real 3 coin sell lost at 00:00:10 | `pass` | `done` | No | "Explained" by the previous tail, though the previous day's difference was 0 |
| D. Taker side flipped for two hours | `pass` | `done` | No | Only daily taker totals are compared, and these net to zero |
| C2. Invented 4 coin sell at noon | `warn` | `done` | No | 719 unexplained boundaries are only a warning |
| E2. Three hours stamped 40 s early | `warn` | `done` | No | Same |
| F. Last price of the day 10x | `warn` | `done` | No | A price outside tolerance is only a warning |
| K. First day of a dataset, 3 coins lost | `pass`, open | `provisional` for good | No | No previous file will ever arrive |

The rule did catch a lost hour, the last two hours, a duplicated hour, and three hours stamped late (all `fail`, raw kept).
A2 and C2 also depend on the mix inside the window. The same errors on the buy side, with only sells in the window, were caught by
the taker-buy comparison.

The root problem in A2 and B is that each day is judged alone. The stated mechanism is that "the two days' differences
cancel", but nothing checks that they do. D's `+4` is never matched against D+1's carry, which is 0.

The consequence of `warn` reaches the page. Feeding a slipped digit (99.0 read as 990.0) through the benchmark gives
Sharpe 9.42, max drawdown -90%, volatility 9308%, with no flag beside the numbers. `report.py:91` filters on
`complete` and a non-null close, and ignores the check status.

**Fix.**

1. Check conservation across days: D's implied carry must equal D-1's positive difference, within `eps`. Keep a day
   provisional until both neighbours are known, and fail it when they disagree.
2. Compare the running taker-buy difference per minute. The official file already has the column.
3. Compare `trades_fills` with `official_count`. It is computed at line 225 and never used.
4. Decide what `warn` means. As it stands, unexplained boundaries and a bad price are accepted as final, by `done` and by
   retention. Either fail them, or flag the bars and exclude them from published statistics.
5. Also note that `bar_price_abs` is an absolute figure, so its meaning changes with the price level. Use a relative one.

`D-18` already requires this rule to be rechecked on the approved source. These points should go into that recheck.

### F-05: one corrupt file stops all catch-up

`src/hft_crypto/data/parsers.py:99`, `:107`, `src/hft_crypto/data/book_replay.py:184`,
`src/hft_crypto/data/ingest.py:400-407`, `src/hft_crypto/data/fetch.py:114`, `:128`, `src/hft_crypto/cli.py:382`.

`zlib.error` is not an `OSError` or a `BadZipFile`, so bad compressed data escapes every handler.

**Probes.**

- 2,400 mutated files through the six parsers: 218 raised `zlib.error`. Bybit alone: 155 of 400.
- A real ingest with a corrupt newest Bybit file (Bybit has no checksum sidecar) and a good older day:
  `zlib.error: Error -3 while decompressing data`. The good day was not processed, nothing went to quarantine, and the run row
  stays `running`. Work is newest first, so the next run hits the same file first. Three runs in a row all died the same way,
  with the task table still empty. This lasts as long as the source serves that file. In the daily workflow the job also stops at
  that step, so no report is published.
- `http.client.IncompleteRead`, `BadStatusLine` and a non-numeric `Content-Length` also escape `HttpFetcher._attempt` and
  kill the run. So does an absurd poll timestamp (`OverflowError`, see F-07).

The document says: "Download corrupted: Checksum fails, file goes to quarantine. Downloaded again".

**Fix.** Catch `zlib.error` in the three readers. Catch `http.client.HTTPException` and `ValueError` in `_attempt`. Around
each task in `run_ingest`, catch `Exception`, record it with `_set_failed`, quarantine the file and move on, so that one
partition can never stop the others.

### F-06: a crash during a rebuild leaves wrong bars forever

`src/hft_crypto/data/derive.py:167-208`, `:223-233`.

`derive_day` writes `bars_1m`, then each higher timeframe, then the caller sets the task. `needs_derive` decides from the
detail stored on `bars_1m`. So a crash after `bars_1m` during the provisional-to-final rebuild says "final" on a day whose
higher bars are still the old ones.

**Probe, by hand.** D1 trades are 1@100 and 2@101. The D2 file holds 7@150 stamped exactly at midnight, which belongs to
D1, so D1 must be V10 C150. Crash at the first higher timeframe of the rebuild, then run again.

| Moment | `bars_1m` | `bars_1d` | Task |
|---|---|---|---|
| Recovery run | V10 C150 | V3 C101, gap on | `provisional` |
| A day later | V10 C150 | V3 C101, gap on | `provisional` |
| A week later | V10 C150 | V3 C101, gap on | `provisional` |

It never heals. The report reads `bars_1d` and `bars_1h`, so the published close is wrong.

I tried a crash before and after each of the 56 persistence calls in two runs, 112 crash points. Then one recovery run,
compared with a run that never crashed:

- 48: identical.
- 54: identical except that a raw file stays until the runner is disposed. Harmless on GitHub.
- 10: this bug, all in the rebuild of the older day. Curated bytes differ at 6 of them, task state at all 10.

The specification says "a failure does not corrupt anything".

**Fix.** Set the task to `pending` before the first write of a rebuild, since `needs_derive` already rebuilds a pending
task. Or write the higher timeframes first and `bars_1m` last, so that `bars_1m` is the commit mark.

### F-07: the poll emits permanent empty bars for minutes it never saw

`src/hft_crypto/data/poll.py:100`, `:451-453`, `:463`, `:466-468`.

A short page is taken to mean "caught up", and everything up to `now - grace` is then emitted. A bar is never rewritten, so a
wrong empty bar stays. Four probes with hand-known trades:

| Input | Result | Expected |
|---|---|---|
| Empty answer with no error, while the market traded, 2 h behind | `status=ok, caught_up=True`, 119 empty bars, `gap` on 0, catalog gaps 0 | No bars, or bars flagged |
| Host returning 2 rows when 1000 are asked for, 60 trades waiting | `caught_up=True` after 2 trades. 119 bars holding 2 trades. Next pass: `late_trades=1`, bar volume still 2.0 | Not caught up |
| Writes taking 150 s after a fetch that ended 01:00:30 | Last bar closes 01:02, after the fetch ended, because `received_us` is read after the write | Last bar closes 00:59 |
| One row stamped 3 days ahead, pass stopped by its budget | 4,319 bars emitted up to `2026-03-03T23:59`, with the clock at Mar 1 01:00. Later real trades count as late | Row refused |

Whether Kraken ever returns a short page mid-history is `UNVERIFIED`. A service problem that returns an empty result needs no
such assumption. Section 08 says "Polling source unavailable: gap recorded".

**Fix.** Never emit past the newest trade held. A minute is proven closed only by a later trade, so
`safe_end = min(grace_end, floor(last_trade))`, and flag anything beyond it as `gap` if it must be emitted. Measure the
grace from the last page's fetch time. Refuse a trade stamped later than receipt plus a small skew, and bound the range
so `OverflowError` cannot happen.

### F-08: the gap flag does not survive to the next pass

`src/hft_crypto/data/poll.py:404`, `:440`, `:474-475`.

`gap_closes` is a local variable. Bars are emitted only in a pass that succeeds, and only up to `safe_end`.

**Probes.**

- Ids 100, 101, 150. The trade after the jump is at 00:03:00.000001. The next page fails. The gap goes to the catalog. The
  recovery pass emits the bars with **no flags at all**. Expected closes 00:01 to 00:04.
- The same gap in a pass stopped by its budget: closes 00:01 to 00:03 flagged, 00:04 not, although that bar holds the first
  trade after the gap.

The catalog and the bars then disagree, and a feature window reads the bars. The lifecycle says "a feature window that
crosses a gap is marked invalid". The existing test only covers a gap and its emission in one successful pass.

**Fix.** Compute the flags at emission from `catalog.gaps()`, which is persistent.

## 3. Medium severity findings

### F-09: `NaN` and `inf` pass every parser

`src/hft_crypto/data/parsers.py:204`, `:249`, `:405`, `src/hft_crypto/data/poll.py:96`, `src/hft_crypto/data/book_replay.py:87`.

`price <= 0` is false for `NaN`. Probed through `aggTrades`, Bybit, funding and Kraken, all accepted. A `NaN` price gives a bar
with `open=100, high=None, low=None, close=100, quote=nan`. `inf` gives `high=inf`. Empty fill ids give
`fill_count=-9223372036854775808` and a `RuntimeWarning` from `core.py:132`.

**Fix.** Check `is_finite` on every numeric column and on each Kraken row. Add `first_trade_id` and `last_trade_id` to
`_require_no_nulls`.

### F-10: how many ways around the allowlist

`src/hft_crypto/config.py:255-259`, `:210-223`, `src/hft_crypto/data/fetch.py:21-28`.

With the shipped configuration the claim holds, and I confirmed it by probe. With sockets, DNS and URL opening replaced by
recorders, 12 commands made **zero** attempts: `init`, six forms of `ingest` (daily, with book, plain, naming Bybit, naming Binance,
an unknown dataset), `poll`, `reconcile-live`, `retention`, `health` and `report`. The client refuses all four hosts. Naming a
disabled dataset exits 2. Flipping `enabled` on Binance alone is a config error.

But the ban is on a name and the allowlist is on a host, and `data.binance.vision` is hard-coded in `ALLOWED_HOSTS`. These are
the ways around it. Every one needs a change to configuration, an environment variable or code:

| # | Route | Result |
|---|---|---|
| 1 | Delete `prohibited`, set `enabled = true` | Binance host reachable. This is the documented path, and CI would catch it in the shipped file |
| 2 | `prohibited = ""` with `enabled = true` | Binance host reachable. `bool("")` is false |
| 3 | Another source's URL set to the Binance host | Binance host reachable, with `binance` not in `enabled_sources()` |
| 4 | A new `[sources.mirror]` with the Binance URL, dataset venue changed | Binance host reachable |
| 5 | `HFT_CONFIG_DIR`, or a `configs/` folder in the working directory | Another file is read, so any of the above applies without touching the shipped one. Workflows do not set this |
| 6 | Code calling `HttpFetcher(allowed_hosts=ALLOWED_HOSTS)` | Reaches the network layer |
| 7 | `enabled = "false"` on any other source (a string) | That source reads as **enabled**. `bool("false")` is true |

`test_every_source_ships_disabled` catches routes 1 to 4 and 7 in the shipped file, but only until the first source is approved. After
that, routes 3 and 4 pass every test. `test_binance_is_prohibited_and_cannot_be_enabled` only flips the one flag.

Parser tricks did not work. Only one URL is read differently: `https://evil.example\@public.bybit.com/x` passes `check_url`, and
urllib then looks up the literal name `evil.example\@public.bybit.com`. That cannot resolve, so it is harmless, but any port on
an allowed host is also accepted. Redirects to another host, to HTTP and to `file:` are all refused.

**Fix.** Refuse at load any enabled source whose host belongs to a prohibited source, and keep a `PROHIBITED_HOSTS` set in code.
Require real booleans in TOML for `enabled`, `prohibited` and `reviewed`. Reject `\` and `@` in the netloc, and any port. Add a
test for redirects (see section 5).

### F-11: retention fails open

`src/hft_crypto/data/retention.py:196-197`, `src/hft_crypto/config.py:357`.

| Input | Result |
|---|---|
| Reviewed raw rule, a kind listed in `kinds` but not in `requires` | Deletable, with no derived data at all |
| Reviewed `raw/live` rule with no `requires`, file past retention | `IRREPLACEABLE` file deletable |
| `reviewed = "false"` | Parsed as reviewed |
| `raw/archive` row with `source_url` null | Deletable as `RE-DOWNLOADABLE`, though nothing can fetch it again |

The shipped rules cover their kinds, so none of this fires today. Adding one dataset kind would trigger the first row. The
header says "raw data goes only when its derived data exists and passes its checks".

Also, `configs/retention.toml:36` marks a rule reviewed, with the note "Awaiting data-steward confirmation". That is disclosed,
but a writer should not approve its own rule. `data-steward` should not confirm it until F-01, F-02 and this finding are fixed.

**Fix.** At load, refuse a rule on a `raw/` zone that has no `requires` entry for each kind. In `check_preconditions`, treat
missing requirements on raw data as a refusal. Require `source_url` on `raw/archive`.

### F-12: a report can publish a prohibited venue

`src/hft_crypto/reports/report.py:83-85`, `:267`, `src/hft_crypto/config.py:317`.

With `benchmark_venue = "binance"` and the source prohibited and disabled, `report --published` on a root holding Binance parts
exits 0 with `data_kind=MARKET`, `venue=binance`, `source_state="no approved source configured"`. Nothing connects the report
to the source switches. `D-18` says that data is not used in any result, and about 953 MB of it was downloaded earlier.

**Fix.** At load, `benchmark_venue` must name an enabled, non-prohibited source. Set `data_kind=MARKET` only then.

### F-13: the `SYNTHETIC` label can be lost

`src/hft_crypto/data/zones.py:75-77`, `src/hft_crypto/reports/report.py:263-267`, `:388-397`, `src/hft_crypto/cli.py:254-255`, `:268`.

The label depends on one small file, `catalog/SYNTHETIC`.

- **Marker gone.** Delete the marker and point `benchmark_venue` at `synthetic`. `report --published` exits 0, with
  `data_kind=MARKET`, label `BENCHMARK, not a strategy result`, benchmarks `SYNTHBTC` and `SYNTHETH`. Refusal to publish goes
  with the marker.
- **Unlabelled logs.** `results/run_log/pipeline_runs.jsonl`, `poll_runs.jsonl` and `deletions.jsonl` carry no label.
- **Mixed roots.** A real root with `--live-root` at a synthetic root: `report --published` exits 0, shows 43 generated poll
  runs, and is not labelled. `_refuse_synthetic` guards only `ingest` and `poll`, although its docstring says "the two can never mix".

The page and `status.json` do label correctly on every route where the marker exists, and the existing test for that is good.

**Fix.** F-12 closes the first route. Also store the flag in the catalog, refuse when a root's datasets name a synthetic venue
but the marker is missing, refuse a marked live root from a real job, and add `data_kind` to each log line.

### F-14: `publish_results.sh` trusts every path in the bundle

`.github/scripts/publish_results.sh:23-44`.

The job with the write token does run no Python and no `uv`, as claimed. But the bundle comes from the job that ran project code, and
the script copies any path it finds. Run against a local bare repository:

- A bundle holding `.git/config` with `core.fsmonitor` set: **the command ran during `git add`**, in the job holding the write
  token. The token file is on that runner.
- A bundle holding `.gitignore` with `ledger/`: later ledger files were silently left out, with `Published to results` and exit 0.
- Any other path is replaced or added: `status.json`, `README.md`, `index.html`.

What limits this today: the pinned `upload-artifact` has `include-hidden-files` defaulting to `false`, which I read in its
`action.yml`. So `.git` and `.gitignore` should not reach the bundle through that step. An attacker needs a compromised pipeline job
and another way to write the artifact. Non-hidden paths need only the compromised job.

**Fix.** Copy by an explicit list: `status.json`, `live_state.json`, `run_log/*.jsonl`, `ledger/*`, `decisions/*`. Refuse anything
else, any path segment starting with a dot, and anything that is not a regular file.

### F-15: the log merge is not strictly append-only

`.github/scripts/publish_results.sh:29-33`.

`awk '!seen[$0]++' existing new` also removes duplicates inside the existing file. Existing log of 3 lines, two identical, plus one
new line: 4 expected, **3** found. The comment says "existing lines keep their place". Also, the `*.jsonl` case comes before
`ledger/*`, so a changed line in `ledger/e.jsonl` is appended, not refused: `{"id":1,"pnl":-5}` then `{"id":1,"pnl":+5}`, exit 0.

What held: a changed `ledger/*.json` is refused, a bundle cannot delete anything, no push uses force, and a failed branch lookup
builds an orphan commit that the remote rejects as non-fast-forward. I checked that the old tip stays an ancestor.

**Fix.** Filter only the new file: `awk 'NR==FNR{seen[$0]=1;print;next} !seen[$0]++' existing new`. For ledger files, require the
existing content to be a byte prefix of the new one.

### F-16: approving Bybit gives a green job with no data

`configs/pipeline.toml:147`, `src/hft_crypto/cli.py:108-116`, `.github/workflows/daily-pipeline.yml:90`,
`src/hft_crypto/data/health.py:200-202`.

`bybit.trades` has `light = false`, and the workflow passes `--light`. With Bybit enabled, the selection is `()`.
Result: `status=ok, planned=0, downloaded_bytes=0`, health `alerts=[]`, `partial_coverage=False`. The health check also skips a
non-light dataset with zero done, so the absence is invisible.

**Fix.** Select by enabled source, not `light`, or raise an alert when an enabled source has no dataset selected.

### F-17: cache pruning and the cache limit

`.github/workflows/daily-pipeline.yml:179-181`, `.github/workflows/live-poll.yml:129-131`, `configs/pipeline.toml:19`. Read, not run.

`gh cache list --key data-center-v1-` has no `--ref`, so it lists every branch (the manual shows `--ref` as an optional filter).
A `workflow_dispatch` from another branch saves the newest copy under that branch's scope, and its prune then deletes `main`'s copy
as "superseded". The next scheduled run on `main` starts from nothing. It rebuilds, so nothing is lost for good, but it costs the whole
backfill.

Separately, each save creates a new copy before the old one is pruned. At the 8 GB budget that is about 16 GB plus the poll cache
against a 10 GB limit, so what gets evicted is GitHub's choice, and it may be the poll cache. `DATA_QUOTA_GB` does not allow for this.

**Fix.** Add `--ref refs/heads/main` and limit the jobs to the default branch. Set the budget to under half the limit until
measured sizes say otherwise.

### F-18: alerts never reach the owner

`.github/workflows/watchdog.yml:33-43`, `src/hft_crypto/data/health.py:207-215`.

Section 6 says "alert if overdue" and "alert" on a format change. The lifecycle says "warn the owner" at 70% and "urgent alert" at
95%. These become strings in `status.json` and on the page. The watchdog reads only `.generated_at`, so a job that keeps reporting
5-day-old data, with `stale: true`, an overdue file and a storage alert, sends nothing. An overdue partition also leaves the run status
`ok` (probed).

**Fix.** Have the watchdog read `stale` and `health.alerts` too, and alert on a change.

### F-19: book validator verdict

`src/hft_crypto/data/book_replay.py:43-51`, `:87`, `:124-137`.

| Input | `ok` | Should be |
|---|---|---|
| A service restart (`u=1` snapshot) with a new book | False, `snapshot_mismatches=1` | True. The code treats it as normal two lines later |
| Negative size in a delta | True | False |
| `NaN` size in a delta | True | False |
| A whole file with an empty ask side | True, `crossed_checks=0` | False |

So a restart day would be quarantined and fetched again with a 24 h backoff, forever, at about 228 MB each time.
`test_a_service_restart_snapshot_is_a_reset_and_not_a_break` hides this: it restates the same book and does not assert `ok`.
Unknown: how often a real file holds a restart. This needs a real file from the approved source.

**Fix.** Skip the comparison when the snapshot is a reset. Mark sizes that are negative or not finite as malformed. Require
`crossed_checks > 0`.

### F-20: missing hourly marks shrink drawdown

`src/hft_crypto/reports/report.py:101-106`, `src/hft_crypto/reports/benchmark.py:87-92`.

The docstring says both series "must start and end on the same price", and nothing checks that. Remove one day's `bars_1h` part with
`bars_1d` still there: max drawdown goes from -50% to -10%, marks from 8 to 5, with no error and no flag.

**Fix.** Check that each day in the tail has its marks, and that both series end on one price. Otherwise publish `None` with a reason.

### F-21: the time budget does not bound everything

`src/hft_crypto/data/ingest.py:623`, `src/hft_crypto/data/poll.py:474-476`.

Budget 1 s, clock jumping 100 s a read, 6 days to rebuild: all 6 rebuilt after the budget ended, `status=ok`. `_emit_bars` is unbounded
too. The job's hard timeout can then kill a rebuild in the middle, which is F-06. Also, one Kraken page can take 186 s (3 attempts of 60 s
plus backoff), so the 120 s budget and the "under 3 minutes" target are not a limit.

**Fix.** Check the deadline in `_sweep_open_bars`, and count what is left. Lower `timeout_s` for the poll.

### F-22: specification clauses with no line of code

| Clause | State |
|---|---|
| 08 section 2: "bars built live are reconciled against bars built from that day's archive" | Replaced by `poll_rebuild`, which compares the poll with itself and finds only late trades, plus `cross_venue`, a sanity check across markets. The docstring is honest, but the clause is unmet |
| 08 section 3: `raw/live/` zone with receive time | Never written. The poll writes straight to `curated` |
| 05 section 7: "expected size and record count" | No code. 1440 candles is only a warning |
| 05 section 4: at 80% "run the normal retention jobs immediately", at 85% and 90% delete | `retention` is dry-run only in the workflow, and nothing triggers it. Ingest removes raw. Nothing else ever deletes |
| 05 section 4: at 95% "live paper keeps running" | The poll stops at its own 95%, and the poll root has no retention, so it eventually stops for good |
| 05 section 3: sample days of `T1` and `T2` | Curated only (`protect_raw=false`, disclosed). `book_replay` holds statistics only, so no `T2` book sample exists on the approved venue |
| 08 section 3: quarantine "reviewed by data-steward" | Not in `persisted_zones`, so the evidence goes with the runner |
| 08 section 5: "each run logs how late it was" | The poll does. The daily job does not. `DataRoot.pipeline_log` is unused |
| G1: reconciliation against the source | `has_official_candles` is true only for Binance, which is prohibited. On Bybit no reconciliation exists at all |

Each needs either code or an entry saying it does not apply yet, from `data-steward` or `project-manager`.

## 4. Low severity findings (F-23)

| Location | Item |
|---|---|
| `configs/retention.toml:44-45` | `provisional` is accepted, though the lifecycle says "passes its checks". The test name says it waits "only for their neighbour", but provisional also covers "not reconciled yet" and "carry unresolved". On GitHub raw goes with the runner anyway. This matters on an always-on machine |
| `src/hft_crypto/data/zones.py:132` | `DATA_ROOT` through a junction into a git work tree is accepted, because `.absolute()` does not resolve links. Zones were created inside the tree |
| `src/hft_crypto/data/atomic.py:149-155`, `health.py:38-39` | On Windows, `os.walk` enters a junction. The sweep then raises `PathGuardError` and stops ingest, and disk use counts the target's files. It fails closed and deletes nothing. Symlinks on Linux are handled |
| `src/hft_crypto/data/ingest.py:559` | The temp sweep covers `ledger/` and `decisions/` and deletes with no log line, outside the protocol |
| `src/hft_crypto/data/retention.py:119`, `:313` | A file in two reviewed rules counts twice in `bytes_freed_if_run`: 140 against 70 real |
| `src/hft_crypto/cli.py:62` | A dry run on a mistyped `DATA_ROOT` creates it, with zones and a catalog |
| `src/hft_crypto/data/poll.py:410-417` | A row repeated in one page raises a false `DATA_GAP`, and overcounts `new_trades`. Stored data stays right |
| `src/hft_crypto/data/poll.py:610` | `no_approved_source` is stored as `failed` in `runs.status` |
| `src/hft_crypto/data/fetch.py:137` | `get_bytes` has no `Content-Length` check, unlike `download`. A short body returns as if whole. JSON parsing would then catch it |
| `src/hft_crypto/reports/site.py:503` | The page says "the daily totals must match", which is no longer the rule |
| `.github/workflows/daily-pipeline.yml:89`, `ci.yml:34` | `${{ inputs.include_book }}` and `${{ matrix.python }}` are in `run` blocks. The first is the only input-derived one. Only people with write access can dispatch. Pass it through `env` anyway |
| `.github/workflows/watchdog.yml:40` | `date -d` on a malformed `generated_at` fails the step under `bash -e`, against "it never fails" |
| Workflows, `setup-uv` | No `version`, so each run takes the newest uv (read in its `action.yml`). The action is pinned and the tool is not. Set `required-version` |
| `src/hft_crypto/reports/report.py:106` | Drawdown uses hourly closes. A wick to 40 between closes reads -25%, not -66.7%. This is declared on the page and fine for a benchmark. A strategy report needs its stop model considered |

**Possible leak, for `leak-auditor`.** Archive trades have `knowable_time = ts` (`parsers.py:224`, `:278`), with no latency allowance.
`bookDepth` declares one. Timing contract item 6 asks for a declared allowance when receive time is unknown. Bars are not affected,
because they are knowable at close. A flow feature built on trades would be.

## 5. Judging the tests

I reran the suite: 501 passed, 1 skipped. The skip is a real limit: creating a file symlink needs a privilege on this machine, so that
guard path runs only on Linux CI.

**Good.** `tests/bars/test_core.py`, `tests/reports/test_benchmark.py` and `tests/leak/test_bars_leak.py` use hand-computed values and
real perturbation, with a guard against vacuous passes. Most retention tests attack something real. The publish tests run the real script.

**Mutation check.** 24 deliberate bugs in a temporary copy of the source, against focused test files.

| Result | Mutants |
|---|---|
| 21 killed | Bar boundary flipped, buy and sell swapped, poll bars knowable at close, late knowable ignored, unfinished higher bar emitted, 252 days, population deviation, drawdown from the first mark, unreviewed rule deletes, changed file deleted, failing derived data accepted, zone guard removed, link check removed, failed pass emits bars, open minute emitted, daily excess unchecked, boundaries unwarned, midnight bar unflagged, both side inversions, allowlist widened |
| Survived | **Redirect check removed.** There is no redirect test, although a redirect is a named safety claim of `fetch.py` |
| Survived | `keep="first"` to `keep="last"` when merging poll trades. The dedupe filter hides it unless a crash replays a page. No test does that |
| Survived | The `IRREPLACEABLE` term in the watermark bypass (`retention.py:254`). This one is an equivalent mutant: the branch above already blocks that case, so the term is dead code |

**Code compared with itself, or passing by construction.**

| Test | Problem |
|---|---|
| `tests/reports/test_benchmark.py:68-74` | `volatility` and `wrong` are the same call, compared to each other. Lines 75-76 are the real check. Delete the first part |
| `tests/test_synthetic_end_to_end.py:150-163` | The generator implements the rule's own hypothesis, with spills of 1 to 80 ms against a 250 ms window. So reconciliation passing there says nothing about the rule |
| `tests/test_synthetic_end_to_end.py:198-206`, `tests/bars/test_reconcile.py:200-204` | Poll bars against a rebuild by the same builder, and a frame against itself. Useful only as a late-trade check |
| `tests/reports/test_report.py:269-276` | Named for escaping in the page, but it tests `_e` directly and never looks at the page |

**Weakened or empty assertions.**

| Test | Problem |
|---|---|
| `tests/data/test_book_replay.py:109-117` | Omits `assert result.ok`, and restates the same book. See F-19 |
| `tests/data/test_retention.py:343-349` | Passes because the rule's zone does not match. See F-01 |
| `tests/data/test_retention.py:291-301` | `execute_plan` on an empty plan cannot delete. The real check is the line above |
| `tests/data/test_retention.py:608-618` | The parameter says 2 GB and the body swaps it for 3 GB. The comment still says 3.6 days at 2 GB, which would not alert. It reads as if it was edited until it passed |
| `tests/test_synthetic_end_to_end.py:238` | A `.get` default passes if the rule vanishes |
| `tests/data/test_safety.py:72-82` | Flips one flag and calls the ban tested. See F-10 |
| `tests/data/test_retention.py:679-680` | `isinstance` on the return type. Tests nothing |

**Missing.** Redirects. `HttpFetcher` past its refusal path: no test runs a success, a 404, a retry or a size cap. I ran these through a
fake opener and they are right, apart from F-05. Corrupt compressed data. `NaN` and `inf`. Crash during a rebuild. Gap across passes. Short
and empty pages. Archive holes. Conservation across days. Traversal inside the root. Hidden paths in the bundle.

## 6. Workflows

Read as an attacker and as an operator. None of it has run on GitHub.

| Question | Answer | Evidence |
|---|---|---|
| Token permissions | Sound. Default read-only. `contents: write` in one job, `actions: write` in one job, `pages` and `id-token` only in deploy | Read, and `tests/test_workflows.py` |
| Can a fork PR reach write access or secrets? | No. Only `ci.yml` takes `pull_request`. There is no `pull_request_target` or `workflow_run`. It has a read token, `persist-credentials: false`, and no secrets | Read |
| Can a fork PR read data? | `UNVERIFIED`. A PR run may be able to restore the base branch's cache, which holds curated market data. Check against each source's terms | Not run |
| Script injection | Two `${{ }}` in `run` blocks: one boolean input, one fixed matrix. All others go through `env`. See F-23 | `git grep` |
| Cache poisoning | The main-branch cache is written only by the daily and poll jobs. CI saves nothing. Branch runs should write only to their own scope (`UNVERIFIED` here). But the restored catalog is trusted input to deletion. See F-01 | Read |
| Does the write job run no project code? | True for Python and `uv`. It does act on bundle contents. See F-14 | Probe |
| What can the `results` push overwrite? | Any path on `results` except a changed ledger or decisions file. Not other branches, by the script. The token itself could | Probe |
| Force push? | None | Read, and the orphan probe |
| Can anything post or commit in a loop? | No recursion. CI ignores `results`, and the poll commits at most once an hour. A cache that is lost every hour gives one `cache_lost` commit an hour. The watchdog sends at most 2 messages a day while stale | Read, and a probe of `state_changes` |
| Are actions pinned to what the comment says? | Yes. All 7 SHAs match their tags upstream | `git ls-remote` |
| Secrets in code or logs | None found. The Telegram token goes through `env` | `git grep` |

**Only a real run can settle:**

- That the daily job's restore of `live-poll-v1-` hits, since the cache version depends on the path string.
- Eviction near the 10 GB limit, and whether a failed cache save still reports `success`, which would trigger pruning.
- `gh cache list` scope and `gh api` behaviour on a 404. `gh` is not installed here.
- That hidden files really stay out of the artifact.
- Whether a shallow fetch plus push works against GitHub.
- Whether pushes to a non-default branch keep schedules alive past 60 days.
- Pages deployment, Python 3.14 wheels, and all Linux-only paths, including file symlinks.
- Every assumption about Kraken and Bybit: `since`, `count`, `last`, order, side meaning, id continuity, formats. All are `UNVERIFIED` until a
  source is approved.

## 7. What held up

- **Bars.** A trade at exactly a boundary closes the bar ending there, by hand to the microsecond. Empty minutes are real rows with null prices
  and zero volume. Buy plus sell equals volume within 1e-12. Higher timeframes matched by hand. A trade at exactly midnight moves to the prior
  day, whichever day arrives first.
- **Knowable time on the poll.** 1-minute and 1-hour bars are knowable at receipt, not close. They keep their first receipt across passes, and
  become the rebuild time after a lost cache.
- **Poll resume.** A pass stopped by its budget then resumed: no duplicates, no false gap, and bars equal to one uninterrupted pass except for
  knowable time.
- **Catch-up.** Daily runs, one run at the end, missed runs, repeated runs, a lost cache, a stale cache restored, curated lost with the catalog
  kept, one bars file lost, and a backfill crossing four runs on a time budget all gave byte-identical curated files, task states and
  reconciliation results. The state turns from pending to overdue exactly one microsecond after the deadline. A repeated run downloads nothing.
- **Determinism.** The claim is true. 222 files, including the catalog, were byte-identical in separate processes across thread counts (1 and 16),
  hash seeds, a time zone and a different path. It holds for a fresh root. A second run on the same root appends to its logs by design, and 13
  files change. No absolute path appears in any file written.
- **Retention on normal rows.** Young `raw/live`, ledger and decisions survived every watermark from 0% to 1000% with hostile rules. Junctions,
  paths outside the root and files not in the catalog were refused. Dry run changed no byte or mtime. Execute deleted exactly the reviewed items.
  The log has every protocol field.
- **Benchmark arithmetic.** 365 days, daily Sharpe with sample deviation, CAGR, and drawdown on hourly marks all matched by hand: Sharpe 5.515131
  against 5.515131, volatility 2.206052 (252 days would give 1.833030), drawdown -25%.
- **Static page.** A `<script>` tag planted in the status and the symbol name of the poll log, which comes from the results branch,
  came out escaped.

## 8. Commands and output

```text
.venv/Scripts/python.exe -m pytest -q
501 passed, 1 skipped in 320.30s (0:05:20)
SKIPPED [1] tests\data\test_foundation.py:156: creating file symlinks needs a privilege on this machine

.venv/Scripts/python.exe -m ruff check .              All checks passed!
.venv/Scripts/python.exe -m ruff format --check .     85 files already formatted

mypy src                                              Success: no issues found in 30 source files
mypy   (project config, src and tests)                Success: no issues found in 46 source files

git ls-remote https://github.com/<action> refs/tags/<tag>
actions/checkout v7.0.1                3d3c42e5aac5ba805825da76410c181273ba90b1  matches
astral-sh/setup-uv v10.3.3             68559e99cc807c1eb7e9238fd43a15bba460eec2  matches
actions/cache v6.1.0                   55cc8345863c7cc4c66a329aec7e433d2d1c52a9  matches
actions/upload-pages-artifact v5.0.0   fc324d3547104276b827a68afc52ff2a11cc49c9  matches
actions/upload-artifact v7.0.2         cf430e030ddbb5b0abf93d22962f4752f3646cd9  matches
actions/deploy-pages v5.0.1            368f82528645a54fb793d4d04e342629a3f51346  matches
actions/download-artifact v8.0.2       9000827ccba6bdab643e8b6fd33ac0654aef8333  matches

git status --short, after all probes: only the untracked AGENTS.md, .codex/, this report and the leak report.
```

Probes, each with hand-computed expectations. Checks counted include both passes and deviations:

| Probe | Checks | Deviations |
|---|---|---|
| Bars: boundaries, empty minutes, split, higher timeframes, midnight, file hole | 28 | 4 (F-03) |
| Retention attacks | 40 | 19 real, plus 1 error in my own probe's expected count, not a finding |
| Crash at each persistence call | 112 crash points | 10 (F-06), 54 harmless |
| Reconciliation, two rounds | 15 | 8 (F-04). One of them, prices 14% high inside `bar_price_abs` on a 100 USD test asset, shows only that the tolerance is absolute |
| Poll | 24 | 11 (F-07, F-08, F-09, F-23) |
| Source switches, sockets replaced | 14 | 4 (F-10, F-16) |
| Publish script on a local bare repository | 8 scenarios, plus 2 for branch lookup failure | F-14, F-15 |
| Numbers, labels, NaN, book replay | 33 | 20 (F-09, F-13, F-19, F-20) |
| Follow-ups: stale bars, time budget, prohibited venue | 7 | 6 |
| Determinism across processes | 8 | 0 |
| Catch-up routes | 28, plus 3 on a rerun | 0 real. The first attempt at the budget route gave 3 deviations because my budget was too small to get past the pending newest date, so it made no progress. With a workable budget, on 3 generated days, it matched |
| Fuzz: 2,400 mutated files, plus corrupt file, future stamp | 5 | 5 (F-05, F-07) |
| HTTP client through a fake opener | 15 | 4 (F-05, F-23) |
| Claims left resting on reading: repeated crash, id break, page escaping, temp sweep | 4 | 3 (F-05, F-03, F-23) |
| Mutation of a temporary source copy | 24 | 3 survived |

## 9. What I did not check

- Real market data of any kind, or any real API response. Sources are held off by owner decision, so every format and API assumption is untested
  against a real source.
- Any workflow on GitHub. See section 6.
- Linux. All probes ran on Windows, where symlinks and `fsync` of a directory differ.
- Python 3.14, which CI also targets.
- Scale: sizes, run times and memory on a real day of data, and the 8 GB budget.
- Races between processes on one root, and the time gap between a path check and its use. Each job has its own runner.
- Telegram sending, and the page's appearance.
- A full future-leak audit. That belongs to `leak-auditor`. I reported only what I noticed.
- `uv` itself, and whether the lockfile matches: the commands ran from the existing environment.
