# First-span fetch: run plan for review

Date: 2026-11-06. Owner: `data-steward`. For section 7 item 17 of `docs/decisions/FOLD_PLAN_2026-11-05.md`, and for part 4 of its
section 11. Code read at `d5c4147`. Its `src/`, `configs/`, `tests/`, `pyproject.toml` and `uv.lock` are those of `0b853bd`, the
coverage check's base.

**Status: revised after both reviews, which are committed at `6b15ea7`.**

- `leak-auditor`: `PASS WITH CONDITIONS`, section 17.8 of `docs/reviews/leak/data_center_recheck_2026-11-04.md`.
- `python-reviewer`: `PASS WITH CONDITIONS`, `docs/reviews/code/first_span_fetch_script_2026-11-06.md`.

The revised script goes back to both for a recheck. **Nothing here has run.** No host was contacted to write this, no file was fetched,
and no configuration file was changed.

**`RUN_SHA` stays a placeholder.** The fetch runs at the C-5 commit, which is not made yet. Once that commit exists, `RUN_SHA` is filled
in and the script's hash is pinned.

**P-1 is committed at `7bd375f`.** `leak-auditor` has added an addendum to section 17.8, which is in the working tree and not yet
committed. It rules P-1 `PASS` and restates condition 1: the run commit is `7bd375f`, or a later commit whose `src/` and `configs/` equal
`7bd375f`'s. `python-reviewer`'s review of P-1 is still to come.

Sizes and counts quoted here come from `docs/reviews/data/binance_vision_coverage_2026-11-05.md` (called "the coverage record") and
from `D-45`. They are derived from Binance Vision data, CC BY-NC-SA 4.0. Not associated with or endorsed by Binance.

## What changed after the reviews

| Condition | Where it is met |
|---|---|
| FS-01: report this invocation's row, and take its flags from that row (python-reviewer 1, leak note 1) | Script: `started` without `Z`, the report's row selected by `started_at`, `run_rows_this_invocation`, and `venue_checks` taken from that row's summary instead of `meta`. These are python-reviewer's tested lines from its section 5 |
| FS-02: `versions_match: yes\|no` (python-reviewer 2) | Script: python-reviewer's tested lines. I also print each distinct pair, with a count, as `ingest_rows_version:` (leak condition 2) |
| FS-03: refuse a root that is relative or holds a space (python-reviewer 3) | Script: python-reviewer's two tested `case` lines, after `MODE="$3"` |
| FS-09: hardening | Script: `PYTHONOPTIMIZE PYTHONPATH PYTHONHOME PYTHONSTARTUP` added to the `unset` line |
| FS-11: a listed file missing from disk | Script: `raw_missing_on_disk:` counts such files, and the hash comparison reads only files that exist. Accepting it as written was also allowed. I took the fix because it keeps the root's path out of a traceback |
| Leak condition 2, RF-01 | Script: after `ingest`, `cmp` runs again and the three hashes are printed again, followed by `override_unchanged: yes\|no`. For `pipeline.toml` the new hash is compared with step 2's. Text: sections 1 and 3 say which layer holds what |
| Leak condition 3, `D-43`'s counts | Section 11.3, check by check. Script: `item_17_counts: yes\|no` |
| Leak condition 4, paths and error text | Section 10 |
| Leak condition 5, `venue_checks.json` | Script: `venue_checks_json_clean: yes\|no`. Section 10 has the rule for committing it |
| Leak condition 6, reruns | Section 7 |
| Leak condition 7, RF-02 | Sections 8 and 11.3, including a yes/no check before every later command on the root |
| Leak conditions 1 and 8 | Section 11.1 row 2 for condition 1. Section 3 for the engine run, condition 8 |
| python-reviewer 4: FS-04, FS-06, FS-07 | Section 11.3 judges a resume by the catalog. Section 4 step 7 and section 7 are corrected for FS-06. Section 7 gains the rows FS-07 found missing |
| FS-08: `uv`'s lines | Section 10: they stay in the local log only |
| R-1 | Script: a computed `fetch_of_record: yes\|no <failing items>` line. The script exits 3 when `ingest` exits 0 but the run is not the fetch of record |
| FS-05, FS-10, FS-02's code part | Section 2: items for `developer` before stage two, not conditions for this run. FS-05 does not block the fetch of record, for the reasons in section 2 |

**The script's hash**, with the `RUN_SHA` placeholder, LF endings and a final newline:
`2028e146bd388391c1bbacf699fb1195b6a3e88df019019144b0503ebb66eb0e`, over 366 lines. It was `d58f3dcd...49ac2` at `d6da50c`. It changes
again when `RUN_SHA` is filled in.

## Answers

| Question | Answer |
|---|---|
| The commands | `init`, then one `ingest`. That one command fetches, checks each checksum, runs F1 to F5 and K1 to K5 on each file, curates, computes the span flags, and builds the bars. No separate command exists for the venue checks or for bars (section 4) |
| The switch | **A configuration folder made for each run and passed by the explicit `--config-dir` flag.** Not a run commit, and not `HFT_CONFIG_DIR`. `leak-auditor` accepts this on RF-01. The engine run needs the switch too. `--declare-costs` does not (section 3). `project-manager` decides |
| The run commit | **The C-5 commit, not made yet.** Its `src/` and `configs/` equal those of `7bd375f`, P-1's commit (section 11.1) |
| The market root | `hft-crypto-data`, directly in the owner's Documents folder, new and empty. It fits the zone layout in section 3 of `docs/08_DATA_CENTER.md`. It is a local exception to that document's section 5, which `D-37` foresees, and `project-manager` should record it (section 8) |
| Its class | By zone: raw files are `RE-DOWNLOADABLE`, and curated data and bars are `DERIVED`. The whole root is kept through stage one, and no deletion rule applies to it. From `--declare-costs` on, the root's trial registry is our own record and is treated as `IRREPLACEABLE` (section 8) |
| `files_digest` | The coverage script's own line, run inside the market root's candle folder, plus a Python cross-check. It must equal `2706d31edc73002aaa70845fe6e4e7fc421d581a3be3f0f54fa3e9ac3483c0ca` (section 6) |
| Stops | The code ends the run on a 403, 429 or 451, and on a `false` from F1, F2, F4 or K1. Other failures leave `ingest`'s exit code at 0, so the script reads them from the catalog and prints `fetch_of_record: no` with their names (section 7) |
| Size and time | 179.2 MB of raw zips, measured for candles. About 0.8 GB with curated data, bars and catalog, `UNVERIFIED`. The fetch takes about 5 minutes without pauses, or about 18 with the 2 s pause. Bars take perhaps 21 minutes, from a rough probe (section 9) |
| What the runner reads | The script's printed lines and one flag file, `venue_checks.json`. These hold counts, hashes, fixed words, times and flags, and no price, volume or rate (section 10) |
| Reviewers | Both verdicts are `PASS WITH CONDITIONS`. The revised script goes back to `python-reviewer` and `leak-auditor`. P-1 has `leak-auditor`'s `PASS` and waits for `python-reviewer` (section 12) |
| **Waiting on** | **`python-reviewer` on P-1,** at `7bd375f`. **The rechecks of this revision.** **The C-5 commit,** which the fetch runs at |

## 1. What runs, and what it decides

| Item | Value |
|---|---|
| Files | 96 monthly 1-minute candle zips and 96 monthly funding zips, 2020-01 to 2023-12, BTCUSDT and ETHUSDT, each with its sidecar. 192 zips and 384 requests. This is the frozen list in section 4.1 of the coverage record |
| Route | `https://data.binance.vision/data/futures/um/monthly/klines/...` and `.../monthly/fundingRate/...`. **Code holds Binance's route:** `route_problem` checks it at load, and `check_url` checks it on every request and every redirect. **Checks 2 and 4 of section 3 hold which hosts are open.** `fetch.ALLOWED_HOSTS` also lists two Bybit hosts that have no route and are not prohibited (RF-01) |
| Where | The market root (section 8) |
| Code | `hft-crypto ingest`, from a clean clone at the C-5 commit |
| Ceiling | `LAST_OPENED_DATE`, 2023-12-31, in `config.py`. `expected_partitions`, `_fetch_raw`, `derive_day` and `MarketReader` all use it. No configuration file, flag or environment variable can move it, so the switch cannot move it either. `--end 2023-12-31` is passed as well (`D-38`) |

**What it decides.** It builds the market root and its manifest, and it produces item 17's flags. It reads no outcome and runs no
strategy. **It does not apply the coverage rule again.** Plan section 2 was applied once on candles (`D-45`). The flags confirm or refute
the venue facts. They date no tick row (`D-43`, RB-02).

**What it is for.** Item 17 must be met before the first `V0` run. Part 4 of C-5 runs `--declare-costs` on this root.

**The engine does not read the flags.** RB-03's static test keeps engine and strategy modules away from the venue checks. So a `false`
flag stops later `ingest` runs, but nothing in code stops a `V0` run. Item 17 holds because `project-manager` records the flags before
approving the run (section 11).

## 2. What the code does that the plan must handle

| ID | What the code does | Where | Effect here | Proposal |
|---|---|---|---|---|
| P-1 | **It does not pause between requests.** `_fetch_raw` calls `download` and then fetches the sidecar with `get_bytes`, file after file. `HttpFetcher` sleeps only between attempts at a single request. The coverage check waits 2 s after each request (`MIN_REQUEST_GAP_S`), as section 4.2 of the coverage record says | `data/ingest.py` `_fetch_raw`. `data/fetch.py` `_attempt`. `data/coverage.py` | The 384 requests go back to back | **Committed at `7bd375f`,** in `data/fetch.py`, `cli.py` and `tests/data/test_request_pace.py`. `PacedFetcher` leaves at least `MIN_REQUEST_GAP_S`, 2 s, from the end of one request to the start of the next. A zip and its sidecar count as two requests. `leak-auditor` rules it `PASS` in the addendum to 17.8: it changes only when requests go. `python-reviewer`'s review is still to come |
| P-2 | A 404 on a sidecar lets its zip through unchecked. `checksum_source` reads `none`, the task is `done`, and catch-up never fetches that file again | `_fetch_raw` | An unverified file could enter the root without anyone noticing | `fetch_of_record` requires `sidecar` on all 192 files. A code change that fails the task instead is for `developer` after the fetch |
| P-3 | A 404 on a listed zip marks the task `overdue`, and the run goes on. `_finish_status` ignores `overdue`, so the run ends `ok`. The month's span flag is `null`, which stops nothing | `run_archive_task`, `_finish_status`, `span_flag` | The status hides a missing month | `fetch_of_record` requires `overdue` at 0 and all tasks `done`. Counting `overdue` as `partial` is for `developer` after the fetch |
| P-4 | A checksum mismatch quarantines the download, marks the task `failed` with a retry 30 minutes later, and the run goes on. The status is `partial` | `_fetch_raw`, `run_archive_task` | The coverage check stopped at once here. `ingest` does not | Accepted, because no file is used until the run is the fetch of record |
| P-5 | A host refusal ends `ingest` with a traceback and exit 1, because `main` does not catch `HostRefusalStop`. No summary is printed. A refusal on a sidecar also leaves one temporary file, which the next `ingest` sweeps away | `cli.py` `main` and `_cmd_ingest`. `_fetch_raw` | The summary must be read from the catalog | On every exit, the script reads this invocation's run row from the catalog. Its `stop_reason` is a fixed word |
| P-6 | The summary's `errors` and the catalog's `last_error` hold raw exception text. Parser messages can quote a row: `unexpected header`, `unreadable CSV`, `bad value in file` | `run_archive_task`, `_contain_task_failure`. `data/parsers.py` | A price could reach a printed line | Neither is printed. The script prints each error's task key, and the rest only after `publishable_reason`, which removes every number and every path |
| P-7 | The manifest holds each file's URL, size, SHA-256, time, code version and licence note. It does not hold `Last-Modified` or the listing's size, which section 4.2 of the coverage record asks for | `JobContext.register_output` | Weaker evidence of when a file was republished | Not blocking. The SHA-256 pins the bytes, and `file_history` records any later change. For `developer` before stage two |

**Found in review. These are items for `developer` before stage two, not conditions for this run.** Leak condition 1 holds the
C-5 commit's `src/` and `configs/` to P-1's change alone, so none of these lands before the fetch.

| ID | Item | Why it does not hold the fetch |
|---|---|---|
| FS-05 | `_fail_derive` writes task rows keyed by day, `archive:binance.klines:<symbol>:<YYYY-MM-DD>` and `archive:binance.aggTrades:...`, for monthly datasets. Those rows stay `failed` for good. Fix: use the spec's own partition key, and touch only datasets that have a task row for it | **I judge that it does not block the fetch of record.** (1) It happens only after a bar day fails, and `bars_failed` above 0 is already a stop on that attempt. (2) A `resume` after `next_retry_at` rebuilds that day from the same curated month, so the data ends up whole. The stray rows are bookkeeping that the planner, which looks up month keys, never reads. (3) `fetch_of_record` recognises the rows by their exact shape. It accepts them only when that day's `derive:binance:<symbol>:<day>` task now reads `done`, and it prints their count as `fs05_rows:`. Any other open task fails it. If a bar day fails again on the rebuild, `bars_failed` stops the run again |
| FS-10 | `publishable_reason` cuts a path at its first space, so the rest of the path can survive on an `error:` line. Fix: match a quoted path up to its closing quote | FS-03 now refuses a root path that holds a space, and the temporary folder holds none on this machine. So it cannot be reached here |
| FS-02, code part | `code_version()` turns any `git` failure into `0.1.0+unknown`. It should fail instead | `versions_match` catches the case in this run (section 5) |

## 3. The source switch

### 3.1 What needs it

| Command | Needs `sources.binance.enabled = true` | Why, in code |
|---|---|---|
| `hft-crypto init` | No | It only makes the zones and a catalog |
| `hft-crypto ingest` | **Yes** | `check_requested_sources` refuses a named dataset whose source is disabled (exit 2). Without named datasets, `ingest` reports `no approved source configured` and fetches nothing. `HttpFetcher` gets `allowed_hosts=config.enabled_hosts()`, which is empty while the source is disabled |
| `python -m hft_crypto.engine --declare-costs` | No | `declare_costs` reads `engine.toml` and the root, and loads no `pipeline.toml` |
| `python -m hft_crypto.engine`, a run | **Yes** | `resolve_source` refuses a market root when no source is enabled. `MarketReader._check_route` refuses any read from a disabled source |

**So the engine run needs the switch as well as the fetch.** Only `--declare-costs` does not.

### 3.2 The options

| Option | How | For | Against |
|---|---|---|---|
| **A.** A local run commit, never merged, as for the coverage check | A branch from the approved commit with one line changed, run from a clean clone at that branch | Already used once (`D-44`, `D-45`). The switch stays in git history, with its diff | `code_version` names the run commit, not the C-5 commit. Every manifest row of the fetch, and later every output and trial row of the engine run, would name a commit only this machine holds, which would have to be tagged and kept. Item 18 asks for the suite at "the commit that runs". Each later run would need another such commit |
| **B.** A configuration folder for each run, passed by `--config-dir` to `hft-crypto`, or by `--pipeline-config-dir` to the engine | The script copies the clone's three configuration files into a new folder inside its run folder, changes one line, checks the result, and passes the folder by flag. The folder is deleted with the run folder | No commit and no branch. No anchored file changes. The tree stays clean, so `code_version` names the C-5 commit. Each command line shows which configuration it used. The engine run can use the same method | The switch is outside git, so the script's checks and printed hashes are its only proof. There are three ways to get it wrong, and each is closed. Without `engine.toml` in the folder, `_market_ticks` returns `None` without an error, and K2 to K4 go untested, so the script copies the file and compares bytes, and 11.3's K2 and K4 counts catch it after the run. Without `pipeline.toml`, `find_config_dir` falls back to the repository's own file, where the source is disabled, so the run refuses (fails closed). Without `retention.toml`, loading fails (fails closed) |
| **B'.** The same folder, named by `HFT_CONFIG_DIR` | `find_config_dir` supports it | Nothing over B | The variable outlives the command. It reaches every process the shell starts, the test suite included, and it does not appear on the command line. Not proposed. The script unsets it |
| **C.** `enabled = true` committed in git, before C-5 or as part of it | Nothing here | Nothing here | On `main`, the daily schedule would run `ingest --light` and then `report --published`. That would publish first-span figures that must stay private (plan section 5), and save market data to the cache while `D-37` is open. Not proposed |

**B is the safer option, and `leak-auditor` accepts it on RF-01.** The script runs five checks on it:

1. In `pipeline.toml`, exactly one line differs: `enabled = false` becomes `enabled = true` under `[sources.binance]`.
2. Parsed with `tomllib`, the two files are equal once that key is set, as in the coverage script.
3. `engine.toml` and `retention.toml` are byte copies.
4. Through the project's own loader, the repository's copy reports `no approved source configured`. The run's copy reports `binance`. `data.binance.vision` is the only host it can open, and the last opened date is 2023-12-31.
5. It prints the three SHA-256 values and both `config_hash` values. After `ingest` it compares the files and prints the hashes again (leak condition 2).

**Which layer holds what (RF-01).**

| What | Held by | How |
|---|---|---|
| The ceiling, 2023-12-31 | **Code** | `LAST_OPENED_DATE` is a constant that no key sets. `expected_partitions`, `_fetch_raw`, `derive_day` and `MarketReader` all stop at it |
| Binance's route | **Code** | `route_problem` at load, and `check_url` on every request and every redirect |
| Which hosts are open | **Checks 2 and 4** | `fetch.ALLOWED_HOSTS` holds three hosts, and only `data.binance.vision` has a route. A folder that also enabled Bybit would open the other two to requests and redirects. Check 2 refuses any second change. Check 4 requires `data.binance.vision` alone |
| Timing stored in the root | **Check 2** | `candle_allowance_ms` and `fill_span_allowance_ms` come from the folder. They set the knowable time stamped on every stored candle, bar and settlement, and those rows stay for every later run |
| Everything else in `pipeline.toml` | **Check 2** | Starts, symbols, timeframes, fetch limits, retries and the quota |

**So checks 1 to 5 run in every invocation that uses a folder:** `first`, every `resume`, and the engine run. The script builds the
folder again on each invocation. None of the checks is dropped as covered by code.

**Where it is recorded.** The catalog's `runs` table holds the `config_hash` of the changed file. The script prints each distinct
`(code_version, config_hash)` pair among the root's `ingest` rows. The decision log entry records them and the one line that differs.

**For the engine run (leak condition 8).** The same method applies, starting from the C-5 commit's own `pipeline.toml` and passed by
`--pipeline-config-dir`. The engine takes A, the candle allowance and the equity timeframe from that file. `run_engine` records only
the engine file's `config_hash`, so that run's printed lines must include the folder's `config_hash`, and its folder runs checks 1 to 5.
That run comes back for its own review, and this plan does not approve it.

**`project-manager` decides.** If A is chosen, the script changes and goes back to review. The coverage script's check on the run
commit's diff replaces the folder steps and the loader check, and `--config-dir` is dropped.

## 4. The commands, in order, and what each prints

All of them run from a clean clone at the C-5 commit, through `uv run --frozen --no-dev`. In the table, `<root>` is the market root
and `<cfg>` is the run's configuration folder, both in the Windows form `cygpath -m` gives.

| # | Command | Prints | Exit |
|---|---|---|---|
| 1 | `git clone --no-local`, `git checkout --detach <commit>`, then `uv sync --frozen --no-dev --python 3.12` | `uv`'s own lines, which stay in the local log (section 10) | 0 |
| 2 | Build the folder of section 3, then load it | `override:`, `override_sha256:`, `code_version:`, `source_state:`, `enabled_hosts:`, `last_opened_date:`, `config_hash:` | 0, or the script stops |
| 3 | `hft-crypto --data-root <root> --config-dir <cfg> init` | `DATA_ROOT zones and catalog are ready.` | 0. If the root is inside a git work tree: exit 2 and `error: DATA_ROOT must be outside the repository, ...` |
| 4 | `hft-crypto --data-root <root> --config-dir <cfg> ingest --datasets binance.klines,binance.fundingRate --symbols BTCUSDT,ETHUSDT --start 2020-01-01 --end 2023-12-31 --event manual` | On exit 0: one line of canonical JSON, the `IngestSummary`, written to a file that is never printed. On a venue check stop: `error: <codes>: <task key or symbols>` on stderr. On a host refusal: a traceback ending `HostRefusalStop: <http_403, http_429 or http_451>: <task key>` | 0, 2 or 1 |
| 5 | The folder checked again | `override_sha256_after:`, `override_unchanged:` | 0 |
| 6 | The report after the run: a read-only query of the catalog | Section 10 | 0 |
| 7 | `files_digest` and `funding_digest` (section 6), then sizes and free space | Section 10 | 0 |
| 8 | The judgement: `fetch_of_record` and `item_17_counts` | Section 10 | 0 when the run is the fetch of record, 3 when it is not |

**The script's exit code:** `ingest`'s own exit code when that is not 0. Otherwise 0 for the fetch of record, 3 when it is not, and 1
if the judgement step itself failed.

**The flags of step 4.**

- `--data-root` and `--config-dir` are flags of `hft-crypto` itself, so they go before the command name.
- `--datasets binance.klines,binance.fundingRate` names exactly stage one's two datasets. A named dataset whose source is disabled is refused, not skipped. `bookDepth` and `aggTrades` are opt-in, so they stay out either way.
- `--symbols` names the universe's two symbols.
- `--start 2020-01-01 --end 2023-12-31` gives 48 monthly partitions for each dataset and symbol, so 192 tasks. The ceiling in code ends there anyway.
- **No `--time-budget`,** so there is no deadline and the bars are built in the same run. With a budget, unbuilt days would leave the run `partial`.
- **No `--delete-raw-after-curated`,** so raw files stay (section 8). The deletion rule is not reviewed in any case.
- No `--include-book`, `--light`, `--scheduled-cron` or `--job-started-at`. `ingest` refuses `--now`.

**What step 4 does, in order** (`run_ingest`, `_run_tasks`):

1. It sweeps temporary files and matches the catalog to the disk. A new root has nothing to sweep.
2. It plans every task that is not `done`, newest month first, with candles before funding in each month. A first run plans 192.
3. For each task, it downloads the zip under a temporary name and reads the sidecar into memory. It compares the SHA-256 values, then renames the zip into `raw/archive/binance/<kind>/<symbol>/date=YYYY-MM-01/`. The sidecar is not kept on disk.
4. Before parsing a file, it runs the per-file checks. Funding files get F1, F2 and F4's duplicate count. Candle files get the K1 to K4 counts, using the tick table from `<cfg>/engine.toml`. A stop quarantines the file, fails the task and ends the run.
5. It parses each file into one monthly part under `curated/candles_official/` or `curated/funding/`, registered with its raw parent.
6. After each candle month, it reopens that month's days for bar building, and **builds the bars for that month's first day at once** (`_run_tasks`).
7. After the loop, it computes the span flags over all 48 months for each symbol (`_venue_span`), and saves them in the run's summary and in the catalog's `meta` table under `venue_checks`. A `false` from F1, F2, F4 or K1 ends the run here, **before the final bar sweep. The first day of each candle month already fetched has bars** (FS-06).
8. The final sweep builds bars for every other stored day: `bars_1m_official` and seven higher timeframes, for 2,922 symbol-days in all.
9. It writes `catalog/last_ingest.json` and a heartbeat, then prints the summary.

**Not run under this plan:** `report`, `reconcile-live`, `poll`, `health`, `retention`, `candle-check`, `coverage-check` and the engine.

## 5. The script

For review only. It runs under Git Bash, with the conventions of section 11 of the coverage check plan. It deletes nothing.
`RUN_SHA` stays a placeholder until the C-5 commit exists. With the placeholder, the block's 366 lines hash to
`2028e146bd388391c1bbacf699fb1195b6a3e88df019019144b0503ebb66eb0e` (LF endings, final newline).

```bash
#!/usr/bin/env bash
# First-span fetch, stage one (fold plan section 7 item 17), under Git Bash. Text reviewed in section 5 of
# docs/reviews/data/first_span_fetch_plan_2026-11-06.md. Prints counts, hashes, fixed words, times and flags only.
# Usage: bash run_first_span_fetch.sh <path of this repository> <the market root> <first|resume>
set -euo pipefail
RUN_SHA="<the C-5 commit, 40 hex>"                    # filled in once the C-5 commit exists, then the hash is pinned
SOURCE_REPO="$1"                                      # passed in, so no local path is written into this text
ROOT="$2"                                             # the market root, passed in for the same reason
MODE="$3"
case "$ROOT" in /*|[A-Za-z]:/*|[A-Za-z]:"\\"*) ;; *) echo "refused: the market root must be an absolute path"; exit 1 ;; esac
case "$ROOT" in *" "*) echo "refused: the market root path holds a space"; exit 1 ;; esac
case "$MODE" in first|resume) ;; *) echo "refused: the mode is first or resume"; exit 1 ;; esac
test "$(basename "$ROOT")" = "hft-crypto-data"
test -d "$(dirname "$ROOT")"                          # init would otherwise create a mistyped parent
if [ "$MODE" = first ] && [ -e "$ROOT" ]; then echo "refused: the market root already exists"; exit 1; fi
if [ "$MODE" = resume ] && [ ! -f "$ROOT/catalog/catalog.sqlite" ]; then echo "refused: no catalog to resume"; exit 1; fi

out="$(mktemp -d)"                                    # a new folder under the system temporary folder
echo "run_folder: $out"                               # local log only
git clone --quiet --no-local "$SOURCE_REPO" "$out/repo"
cd "$out/repo"
git checkout --quiet --detach "$RUN_SHA"
unset GITHUB_SHA DATA_ROOT HFT_CONFIG_DIR CHECK_ROOT DATA_QUOTA_GB PYTHONOPTIMIZE PYTHONPATH PYTHONHOME PYTHONSTARTUP
uv sync --frozen --no-dev --python 3.12
test "$(git rev-parse HEAD)" = "$RUN_SHA"
test -z "$(git status --porcelain)"                   # a clean tree, so code_version names the commit
echo "commit $RUN_SHA: clean clone"

# The switch, for this run only, in a folder outside every work tree (section 3).
cfg="$out/run-config"
mkdir "$cfg"
cp configs/engine.toml configs/retention.toml "$cfg/"
uv run --frozen --no-dev python - "$(cygpath -m configs/pipeline.toml)" "$(cygpath -m "$cfg/pipeline.toml")" <<'EOF'
import sys, tomllib
source, target = sys.argv[1], sys.argv[2]
lines = open(source, "rb").read().decode("utf-8").splitlines(keepends=True)
table, hits = None, []
for number, line in enumerate(lines):
    text = line.strip()
    if text.startswith("["):
        table = text
    elif table == "[sources.binance]" and text == "enabled = false":
        hits.append(number)
assert len(hits) == 1, "not exactly one enabled = false under [sources.binance]"
lines[hits[0]] = lines[hits[0]].replace("enabled = false", "enabled = true", 1)
with open(target, "wb") as handle:
    handle.write("".join(lines).encode("utf-8"))
with open(source, "rb") as a, open(target, "rb") as b:
    base, run = tomllib.load(a), tomllib.load(b)
assert base["sources"]["binance"]["enabled"] is False
assert run["sources"]["binance"]["enabled"] is True
base["sources"]["binance"]["enabled"] = True
assert base == run, "pipeline.toml differs beyond the one switch"
EOF
cmp configs/engine.toml "$cfg/engine.toml"
cmp configs/retention.toml "$cfg/retention.toml"
test "$({ diff configs/pipeline.toml "$cfg/pipeline.toml" || true; } | grep -c '^[<>]')" = "2"
echo "override: one line differs, enabled = true under [sources.binance]. engine.toml and retention.toml are copies"
hashes() { echo "pipeline=$(sha256sum < "$cfg/pipeline.toml" | cut -d' ' -f1)" \
  "engine=$(sha256sum < "$cfg/engine.toml" | cut -d' ' -f1) retention=$(sha256sum < "$cfg/retention.toml" | cut -d' ' -f1)"; }
before="$(hashes)"
echo "override_sha256: $before"
CFG_M="$(cygpath -m "$cfg")"
ROOT_M="$(cygpath -m "$ROOT")"
uv run --frozen --no-dev python - "$CFG_M" <<'EOF'
import sys
from hft_crypto.config import load_pipeline_config, load_retention_policy
from hft_crypto.versioning import code_version
base, run = load_pipeline_config("configs"), load_pipeline_config(sys.argv[1])
load_retention_policy(sys.argv[1])
print("code_version:", code_version())
print("source_state: repository", repr(base.source_state()), "run", repr(run.source_state()))
print("enabled_hosts:", ",".join(sorted(run.enabled_hosts())))
print("last_opened_date:", run.last_opened_date.isoformat())
print("config_hash: repository", base.config_hash, "run", run.config_hash)
assert not base.enabled_sources() and run.enabled_sources() == ("binance",)
assert run.enabled_hosts() == frozenset({"data.binance.vision"})
assert run.last_opened_date.isoformat() == "2023-12-31"
assert not code_version().endswith("-dirty")
EOF

uv run --frozen --no-dev hft-crypto --data-root "$ROOT_M" --config-dir "$CFG_M" init
started="$(date -u +%FT%T)"
echo "ingest_started: ${started}Z"
set +e
uv run --frozen --no-dev hft-crypto --data-root "$ROOT_M" --config-dir "$CFG_M" ingest \
  --datasets binance.klines,binance.fundingRate --symbols BTCUSDT,ETHUSDT \
  --start 2020-01-01 --end 2023-12-31 --event manual \
  > "$out/ingest.json" 2> "$out/ingest.err"          # neither file is printed or opened (section 10)
rc=$?
set -e
echo "ingest_finished: $(date -u +%FT%TZ)"
echo "ingest_exit: $rc"

# Leak condition 2: the folder is checked again. pipeline.toml differs from the clone's by design, so its hash is compared.
after="$(hashes)"
echo "override_sha256_after: $after"
if cmp -s configs/engine.toml "$cfg/engine.toml" && cmp -s configs/retention.toml "$cfg/retention.toml" \
  && [ "$after" = "$before" ]; then unchanged=yes; else unchanged=no; fi
echo "override_unchanged: $unchanged"

# The report after the run. The catalog is opened read-only, and only the fields below are printed.
uv run --frozen --no-dev python - "$ROOT_M" "$(cygpath -m "$out")" "$started" "$CFG_M" <<'EOF'
import collections, hashlib, json, pathlib, sqlite3, sys
from hft_crypto.data.ingest import publishable_reason
root, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
db = sqlite3.connect(f"{(root / 'catalog' / 'catalog.sqlite').as_uri()}?mode=ro", uri=True)
rows = db.execute(
    "SELECT status, code_version, config_hash, summary FROM runs WHERE kind = 'ingest' AND started_at >= ? "
    "ORDER BY started_at", (sys.argv[3],)
).fetchall()
print("run_rows_this_invocation:", len(rows))
row = rows[0] if len(rows) == 1 else None
summary = json.loads(row[3] or "{}") if row is not None else {}
if row is None:
    print("run_row: none")
else:
    print("run_status:", row[0], "stop_reason:", summary.get("stop_reason"))
    print("run_code_version:", row[1], "run_config_hash:", row[2])
    for key in ("planned", "done", "pending", "overdue", "failed", "skipped_retry_wait", "held_by_watermark",
                "held_by_disk", "not_started_time_budget", "bars_built", "bars_provisional", "bars_failed",
                "bars_left_by_budget", "raw_deleted_files", "temp_files_swept", "downloaded_bytes"):
        print(f"{key}:", summary.get(key))
    for item in summary.get("errors", []):
        key, _, rest = item.partition(": ")
        if key.startswith(("archive:", "derive:")):
            print("error:", key, publishable_reason(rest))
        else:
            print("error:", publishable_reason(item))
    for item in summary.get("alerts", []):
        print("alert:", item)
from hft_crypto.config import load_pipeline_config
from hft_crypto.versioning import code_version
expected = (code_version(), load_pipeline_config(sys.argv[4]).config_hash)
pairs = db.execute("SELECT DISTINCT code_version, config_hash FROM runs WHERE kind = 'ingest'").fetchall()
versions = sorted(v for (v,) in db.execute("SELECT DISTINCT code_version FROM files"))
print("versions_match:", "yes" if pairs == [expected] and versions == [expected[0]]
      and "+unknown" not in expected[0] and not expected[0].endswith("-dirty") else "no")
for version, config, n in db.execute(
    "SELECT code_version, config_hash, COUNT(*) FROM runs WHERE kind = 'ingest' GROUP BY 1, 2 ORDER BY 1, 2"
):
    print("ingest_rows_version:", version, config, n)
raw = db.execute(
    "SELECT rel_path, kind, status, size_bytes, sha256, check_detail FROM files "
    "WHERE rel_path LIKE 'raw/archive/binance/%' ORDER BY rel_path"
).fetchall()
for (kind, status), n in sorted(collections.Counter((r[1], r[2]) for r in raw).items()):
    print("raw_files:", kind, status, n)
present = [r for r in raw if r[2] == "present"]
details = {r[0]: json.loads(r[5] or "{}") for r in present}
print("raw_checksum_source:", dict(sorted(collections.Counter(str(d.get("checksum_source")) for d in details.values()).items())))
print("raw_with_venue_checks:", sum("venue_checks" in d for d in details.values()), "of", len(present))
print("raw_bytes:", {kind: sum(r[3] for r in present if r[1] == kind) for kind in ("klines", "fundingRate")})
on_disk = [r for r in present if (root / r[0]).is_file()]
print("raw_missing_on_disk:", len(present) - len(on_disk))
print("raw_hash_differs_from_catalog:", sum(hashlib.sha256((root / r[0]).read_bytes()).hexdigest() != r[4] for r in on_disk))
for rel, detail in details.items():
    parts, facts = rel.split("/"), detail.get("venue_checks") or {}
    if parts[3] == "fundingRate" and any(facts.get(k) for k in ("missing", "outside_month", "off_grid")):
        print("funding_file:", parts[4], parts[5], "missing", facts.get("missing"),
              "outside_month", facts.get("outside_month"), "off_grid", facts.get("off_grid"))
for dataset, state, n in db.execute("SELECT dataset_id, state, COUNT(*) FROM tasks GROUP BY 1, 2 ORDER BY 1, 2"):
    print("tasks:", dataset, state, n)
for key, state, retry in db.execute("SELECT task_key, state, next_retry_at FROM tasks WHERE state != 'done' ORDER BY 1"):
    print("open_task:", key, state, retry)
for kind, status, n in db.execute(
    "SELECT kind, check_status, COUNT(*) FROM files WHERE rel_path LIKE 'curated/%' AND status = 'present' "
    "GROUP BY 1, 2 ORDER BY 1, 2"
):
    print("curated_files:", kind, status, n)
print("gaps:", db.execute("SELECT COUNT(*) FROM gaps").fetchone()[0])
print("exclusions_open:", db.execute("SELECT COUNT(*) FROM exclusions WHERE resolved_at IS NULL").fetchone()[0])
log = root / "catalog" / "quarantine.jsonl"
records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
print("quarantined:", len(records))
for item in records:   # the published record's fields. Its reason has already passed publishable_reason
    print("quarantine:", item["dataset"], item["symbol"], item["partition"], item["reason"], item["sha256"], item["size"])
value = summary.get("venue_checks") or None
if value is None:
    print("venue_checks: none")
else:
    document = value
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    (out / "venue_checks.json").write_text(text, encoding="utf-8", newline="\n")
    print("venue_checks_sha256:", hashlib.sha256(text.encode("utf-8")).hexdigest())
    for symbol, result in sorted(document.items()):
        for check, body in sorted(result.items()):
            print("venue_check:", symbol, check, json.dumps(body, sort_keys=True))
EOF

# Section 6. The coverage script's digest line, run inside each raw folder of the market root.
files_digest=none
for kind in klines fundingRate; do
  dir="$ROOT/raw/archive/binance/$kind"
  name="$([ "$kind" = klines ] && echo files_digest || echo funding_digest)"
  if [ -d "$dir" ]; then
    echo "zips: $kind $(cd "$dir" && find . -type f -name '*.zip' | wc -l)"
    value="$(cd "$dir" && find . -type f -name '*.zip' -exec sha256sum {} + \
      | awk '{n = split($2, p, "/"); print $1 "  " p[n]}' | sort -k2 | sha256sum | cut -d' ' -f1)" || value=failed
    echo "$name: $value"
    if [ "$kind" = klines ]; then files_digest="$value"; fi
  else
    echo "zips: $kind 0"
  fi
done
uv run --frozen --no-dev python - "$ROOT_M" <<'EOF'
import hashlib, pathlib, re, sys
base = pathlib.Path(sys.argv[1]) / "raw" / "archive" / "binance" / "klines"
files = sorted(base.rglob("*.zip"), key=lambda path: path.name) if base.is_dir() else []
names = [path.name for path in files]
pattern = re.compile(r"(BTC|ETH)USDT-1m-20(20|21|22|23)-(0[1-9]|1[0-2])\.zip")
print("candle_zip_names_ok:", len(names) == 96 and len(set(names)) == 96 and all(pattern.fullmatch(n) for n in names))
lines = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files)
print("files_digest_python:", hashlib.sha256(lines.encode("ascii")).hexdigest())
EOF
echo "files_digest_expected: 2706d31edc73002aaa70845fe6e4e7fc421d581a3be3f0f54fa3e9ac3483c0ca"

for zone in raw/archive curated catalog quarantine features results; do
  echo "zone_bytes: $zone $(du -sb "$ROOT/$zone" | cut -f1)"
done
echo "files_in_root: $(find "$ROOT" -type f | wc -l)"
echo "free_bytes: $(df -B1 --output=avail "$ROOT" | tail -1)"

# R-1: the judgement, computed from the catalog and the files, so that nobody reads twenty items by eye (section 11.3).
set +e
uv run --frozen --no-dev python - "$ROOT_M" "$(cygpath -m "$out")" "$started" "$CFG_M" "$rc" "$unchanged" "$files_digest" <<'EOF'
import collections, hashlib, json, pathlib, re, sqlite3, sys
from hft_crypto.config import load_pipeline_config
from hft_crypto.versioning import code_version
root, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
started, cfg, rc, unchanged, shell_digest = sys.argv[3:8]
D45_DIGEST = "2706d31edc73002aaa70845fe6e4e7fc421d581a3be3f0f54fa3e9ac3483c0ca"
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?Z")
NOTE = "no tick table was given, so the ticks were not tested"
CHECKS = {"F1", "F2", "F3", "F4", "F5", "K1", "K2", "K3", "K4", "K5", "K2_K4"}
FIELDS = {"pass", "files_with_another_header", "months_checked", "rows", "max_offset_ms", "expected", "missing",
          "duplicates", "files", "outside_span", "other_gaps", "at", "minutes", "months_at_0_01",
          "months_showing_0_01", "reported_not_failed", "first", "last", "note"}


def clean(value):
    """Leak condition 5. bool is an int in Python, so a float is refused by name before ints are allowed."""
    if isinstance(value, float):
        return False
    if value is None or isinstance(value, int):
        return True
    if isinstance(value, str):
        return TIME.fullmatch(value) is not None or value == NOTE
    if isinstance(value, list):
        return all(clean(item) for item in value)
    if isinstance(value, dict):
        return all(key in FIELDS and clean(item) for key, item in value.items())
    return False


failing = []


def need(name, ok):
    if not ok:
        failing.append(name)


db = sqlite3.connect(f"{(root / 'catalog' / 'catalog.sqlite').as_uri()}?mode=ro", uri=True)
rows = db.execute("SELECT status, summary FROM runs WHERE kind = 'ingest' AND started_at >= ?", (started,)).fetchall()
summary = json.loads(rows[0][1] or "{}") if len(rows) == 1 else {}
need("ingest_exit", rc == "0")
need("override_unchanged", unchanged == "yes")
need("run_rows_this_invocation", len(rows) == 1)
need("run_status", len(rows) == 1 and rows[0][0] == "ok" and summary.get("stop_reason") == "none")
for key in ("pending", "overdue", "failed", "skipped_retry_wait", "held_by_watermark", "held_by_disk",
            "not_started_time_budget", "bars_failed", "bars_left_by_budget"):
    need(key, summary.get(key) == 0)
expected = (code_version(), load_pipeline_config(cfg).config_hash)
pairs = db.execute("SELECT DISTINCT code_version, config_hash FROM runs WHERE kind = 'ingest'").fetchall()
versions = sorted(v for (v,) in db.execute("SELECT DISTINCT code_version FROM files"))
need("versions_match", pairs == [expected] and versions == [expected[0]]
     and "+unknown" not in expected[0] and not expected[0].endswith("-dirty"))
# Tasks are read from the root, so a resume is judged on the whole root and not on its own run (FS-04).
stray_key = re.compile(r"archive:binance\.(klines|aggTrades):(BTCUSDT|ETHUSDT):(\d{4}-\d{2}-\d{2})")
done, other, stray = collections.Counter(), 0, []
for key, dataset, state in db.execute("SELECT task_key, dataset_id, state FROM tasks"):
    match = stray_key.fullmatch(key)
    if match:
        stray.append(f"derive:binance:{match.group(2)}:{match.group(3)}")
    elif state == "done":
        done[dataset] += 1
    else:
        other += 1
need("tasks", dict(done) == {"binance.klines": 96, "binance.fundingRate": 96, "derived.bars.binance": 2922}
     and other == 0)
bar_days = {k for (k,) in db.execute("SELECT task_key FROM tasks WHERE dataset_id = 'derived.bars.binance' AND state = 'done'")}
need("fs05_rows", all(day in bar_days for day in stray))
print("fs05_rows:", len(stray))
raw = db.execute(
    "SELECT rel_path, kind, status, sha256, check_detail FROM files WHERE rel_path LIKE 'raw/archive/binance/%'"
).fetchall()
present = [r for r in raw if r[2] == "present"]
details = [json.loads(r[4] or "{}") for r in present]
need("raw_files", len(present) == len(raw)
     and sorted(collections.Counter(r[1] for r in present).items()) == [("fundingRate", 96), ("klines", 96)])
need("raw_checksum_source", all(d.get("checksum_source") == "sidecar" for d in details))
need("raw_with_venue_checks", all("venue_checks" in d for d in details))
need("raw_hash", all((root / r[0]).is_file() and hashlib.sha256((root / r[0]).read_bytes()).hexdigest() == r[3]
                     for r in present))
log = root / "catalog" / "quarantine.jsonl"
records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []
done_keys = {k for (k,) in db.execute("SELECT task_key FROM tasks WHERE state = 'done'")}
need("quarantine", all(item.get("run_id") != summary.get("run_id")
                       and f"archive:{item['dataset']}:{item['symbol']}:{item['partition']}" in done_keys
                       for item in records))
curated = dict(db.execute(
    "SELECT kind, COUNT(*) FROM files WHERE rel_path LIKE 'curated/%' AND status = 'present' GROUP BY 1"
).fetchall())
bars = [kind for kind in curated if kind.startswith("bars_")]
need("curated_files", len(curated) == 10 and curated.get("candles_official") == 96 and curated.get("funding") == 96
     and len(bars) == 8 and all(curated[kind] == 2922 for kind in bars))
need("gaps", db.execute("SELECT COUNT(*) FROM gaps").fetchone()[0] == 0)
need("exclusions_open", db.execute("SELECT COUNT(*) FROM exclusions WHERE resolved_at IS NULL").fetchone()[0] == 0)
klines = root / "raw" / "archive" / "binance" / "klines"
files = sorted(klines.rglob("*.zip"), key=lambda path: path.name) if klines.is_dir() else []
names = [path.name for path in files]
pattern = re.compile(r"(BTC|ETH)USDT-1m-20(20|21|22|23)-(0[1-9]|1[0-2])\.zip")
need("candle_zip_names", len(names) == 96 and len(set(names)) == 96 and all(pattern.fullmatch(n) for n in names))
lines = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files)
need("files_digest", shell_digest == hashlib.sha256(lines.encode("ascii")).hexdigest() == D45_DIGEST)
funding = root / "raw" / "archive" / "binance" / "fundingRate"
need("funding_zips", funding.is_dir() and len(list(funding.rglob("*.zip"))) == 96)
flags = out / "venue_checks.json"
document = json.loads(flags.read_text(encoding="utf-8")) if flags.is_file() else None
tidy = (isinstance(document, dict) and set(document) == {"BTCUSDT", "ETHUSDT"}
        and all(isinstance(result, dict) and set(result) <= CHECKS
                and all(isinstance(body, dict) and clean(body) for body in result.values())
                for result in document.values()))
print("venue_checks_json_clean:", "yes" if tidy else "no")
need("venue_checks_json", tidy and document == summary.get("venue_checks"))
short = []


def flag(symbol, check, **want):
    body = ((document or {}).get(symbol) or {}).get(check) or {}
    if not (body.get("pass") is True and body.get("months_checked") == 48
            and all(body.get(key) == value for key, value in want.items())):
        short.append(f"{symbol}.{check}")


for symbol in ("BTCUSDT", "ETHUSDT"):
    for check in ("F1", "F2", "F3", "F5"):
        flag(symbol, check)
    flag(symbol, "F4", expected=4383, duplicates=0, missing=0)
    flag(symbol, "K1", minutes=0)
    k5 = ((document or {}).get(symbol) or {}).get("K5") or {}
    if (k5.get("rows"), k5.get("missing"), k5.get("duplicates")) != (2103840, 0, 0):
        short.append(f"{symbol}.K5")
flag("BTCUSDT", "K2", months_at_0_01=26)
flag("ETHUSDT", "K4", months_at_0_01=48)
print("item_17_counts:", "yes" if not short else "no " + " ".join(short))
print("fetch_of_record_run_id:", summary.get("run_id", "none"))
print("fetch_of_record:", "yes" if not failing else "no " + " ".join(failing))
sys.exit(0 if not failing else 3)
EOF
record=$?
set -e
echo "done: $(date -u +%FT%TZ)"
if [ "$rc" -ne 0 ]; then exit "$rc"; fi
exit "$record"
```

**Notes for `python-reviewer`.**

- **Your tested lines are used verbatim** for FS-01, FS-02 and FS-03. Lines 253 to 265 of the old report sit unchanged under the `else:`.
- **What is new beyond your text, for your recheck:**
  - FS-09's `unset` names.
  - The `hashes` function and the check after `ingest` (leak condition 2).
  - `ingest_rows_version:` lines (leak condition 2).
  - `raw_missing_on_disk:`, from FS-11's fix.
  - The digest loop keeps the klines value in `files_digest`, and `|| value=failed` stops a failing `find` from ending the script.
  - The judgement step, R-1, with `fs05_rows`, `venue_checks_json_clean`, `item_17_counts`, `fetch_of_record_run_id` and `fetch_of_record`.
  - The exit codes.
- **The judgement repeats the report's queries instead of parsing its output,** so each can be read and tested alone.
- **`venue_checks_json_clean` checks the file as read back from disk,** so a float written by `json.dumps` would show up.
- **The note `no tick table was given, ...` is allowed by the shape check,** as leak condition 5 words it. It can never pass item 17, because K2 and K4 must then be present with their counts.
- **The market root's path is not printed by design.** Under leak condition 4 it can still reach the local log through an error from `du`, `find` or a traceback.
- **`set +e` around `ingest` and around the judgement** lets every line print after a stop.
- **The catalog is opened through a `file:` URI with `mode=ro`.** Zips are hashed as bytes, and nothing unzips them.

**Tried offline after the revision, not end to end.** I used a clone of `6b15ea7` in a scratch folder, synced with `UV_OFFLINE=1`, and
it stayed clean throughout. I extracted the block above byte for byte (`bash -n` passes) and ran its five heredocs one by one with the
clone's Python. I did not run the script itself, `uv run`, or its `cygpath` steps.

- **The folder.** The generator and loader printed what `python-reviewer` saw for the CRLF files: `override_sha256` `221678dc...`, `acf5b4dd...` and `e1458642...`, `config_hash` `8fd2f5cd...` for the repository and `4e3e6a65...` for the run.
- **A root filled by real code.**
  - `run_ingest` ran in-process, with an audit hook that refused every socket, and a fake fetcher serving invented zips and sidecars for 2023-10 to 2023-12, both symbols and both datasets.
  - The tick table came from the folder's `engine.toml`.
  - It ended `ok`, with 12 tasks done, 184 bar days and 24 requests.
- **The report, with a start time before the run:**
  - `run_rows_this_invocation: 1`, `versions_match: yes`, and one `ingest_rows_version:` pair.
  - `raw_checksum_source: {'sidecar': 12}`, with `raw_missing_on_disk` and `raw_hash_differs_from_catalog` both 0.
  - 17 `venue_check:` lines.
  - The bash and Python digests were equal.
- **The judgement on that root.**
  - `venue_checks_json_clean: yes` and `fs05_rows: 0`.
  - `item_17_counts: no`, naming all 16 checks, which is right, because nothing passes on 3 of 48 months.
  - `fetch_of_record: no tasks raw_files curated_files candle_zip_names files_digest funding_zips`, and exit 3.
- **With a start time after the run,** as when a resume exits before its row:
  - The report printed `run_rows_this_invocation: 0`, `run_row: none` and `venue_checks: none`, and wrote no flag file.
  - With `ingest_exit` 2, the judgement named `ingest_exit`, `run_rows_this_invocation`, `run_status` and the rest, and exited 3.
- **The shape check** read `no` for each of these: a float in F3, a price text in K3's `first`, and an unknown key in K5.
- **The two `case` lines,** copied from the block, accepted `C:\...`, `C:/...` and `/c/...`. They refused `../hft-crypto-data`, `hft-crypto-data`, `C:x`, and a path with a space.
- **The check after `ingest`** read `yes` on an untouched folder. It read `no` after one byte was added to `pipeline.toml`, `yes` once the file was restored, and `no` without `engine.toml`.
- **Not tested:** the script as a whole, its exit codes through `uv run`, and anything that needs the real 96 months.

## 6. The `files_digest` comparison

**What `D-45` holds.** `files_digest` `2706d31edc73002aaa70845fe6e4e7fc421d581a3be3f0f54fa3e9ac3483c0ca`, over the 96 first-span candle zips that
the coverage check fetched on 2026-11-06. Section 7.3 of the coverage check plan defines it: the SHA-256 of the sorted lines
`<sha256>  <zip base name>`.

**The command, over the market root's 96 candle zips only, with no funding file:**

```bash
( cd "$ROOT/raw/archive/binance/klines" && find . -type f -name '*.zip' -exec sha256sum {} + \
  | awk '{n = split($2, p, "/"); print $1 "  " p[n]}' | sort -k2 | sha256sum | cut -d' ' -f1 )
```

`$ROOT` is set only in the runner's shell. This is the script's line from section 11.3 of the coverage check plan, with one change:
it runs `find .` inside the candle folder instead of `find "$root/raw"`. That change has two reasons:

- The market root's raw zone also holds the funding zips, and `D-45` leaves them out.
- A space in the root's path would split awk's `$2` and break the base name. FS-03 now refuses such a path anyway.

Neither reason changes a line of what is hashed, because awk keeps only the hash and the base name. Git Bash's `sha256sum` prints `*`
before the path, and awk drops it. `python-reviewer` confirmed all of this in section 3.3 of its review: the line, the Python
cross-check and the served bytes gave one digest in a path with a space.

**The cross-check.** The script also computes the digest in Python, from the files' own bytes, sorted by name. That order equals
`sort -k2` under `C`, `C.UTF-8` and `en_US.UTF-8` for the real names. The judgement step requires all of these:

- the bash value equals the Python value;
- both equal `D-45`'s;
- there are 96 names, each once, matching `(BTC|ETH)USDT-1m-YYYY-MM.zip` for 2020-01 to 2023-12;
- every present raw file hashes to its catalog value.

**Reading the result.**

| Result | Meaning | Next |
|---|---|---|
| Both digests equal `2706d31e...c0ca` | The same bytes the coverage check counted. `D-45`'s counts describe this root's candles | K5 must also read 2,103,840 rows, 0 missing and 0 duplicates on each symbol. That is the sum of the 16 quarters in the first-span document |
| The two digests differ from each other | A tool fault, not a data fact | Stop. `python-reviewer` finds out why. Nothing is used |
| Both agree, and differ from `D-45` | The archive served different bytes from those of 2026-11-06 | Stop before any use. As `D-45` requires, the 96 files are counted again with the same checker, `_count_candles` and `_Quarter` in `data/coverage.py`. A short script runs them on the market root's files, fetches nothing, and prints only the first-span document's quarter fields. That script needs `python-reviewer` and `leak-auditor` first. Plan section 2 applies only once on candles, so whether a different count changes anything is for `project-manager` and `leak-auditor` |

**Funding has no earlier reference.** The script prints `funding_digest` in the same form, and it becomes the reference for later
checks. From this run on, the catalog holds each of the 192 files' SHA-256 values, so any later difference can be traced to a single
file. The coverage check's output could not do that.

**Every attempt prints its digests, stopped or not** (leak condition 6a). If the root is ever lost, a new fetch is a new decision, and
its digests are compared with those of the fetch of record.

**Again later.** The same command runs again before the first `V0` run, to show the bytes have not changed.

## 7. Stops and reruns

| Event | What the code does | Exit and status | What this plan does |
|---|---|---|---|
| HTTP 403 or 429, on a zip or a sidecar | `fetch.py` does not retry it. `ingest` fails the task, with a retry 30 minutes later, and raises `HostRefusalStop`. The run row records `failed` and `stop_reason` `http_403` or `http_429`. No later file is requested. The span check and the final bar sweep do not run, **but the loop has already built bars for the first day of each candle month done so far** (FS-06), up to 96 symbol-days | Exit 1, traceback | **Stop.** One `resume` run, on a written note from `project-manager`, after the task's `next_retry_at`. A second refusal goes to the owner |
| HTTP 451 | The same, with `http_451` | Exit 1 | **Stop. To the owner first.** A 451 gives a legal reason, so a note alone is not enough to rerun |
| HTTP 404 on a listed zip | The task is marked `overdue` with an alert, and the run goes on. The month's flags read `null` (P-3) | Exit 0, status `ok` | **Not of record** (`overdue`, `tasks`). Every file was in the listing, and the coverage check found all 96 candle files on 2026-11-06, so a 404 now looks like an outage. One `resume` run on a note. A second 404 on the same file goes to `project-manager` as a coverage fact |
| HTTP 404 on a sidecar | The zip is accepted unchecked, with `checksum_source` `none`, and the task is `done` (P-2) | Exit 0 | **Not of record** (`raw_checksum_source`). A `resume` run cannot fix this, because the task is done. The case for a new root under rule 6c |
| SHA-256 does not match the sidecar, or the sidecar cannot be read | The download is quarantined and recorded with a reason from `publishable_reason`. The task fails, with a retry 30 minutes later, and the run goes on (P-4) | Exit 0, status `partial` | **Not of record** (`failed`, `tasks`). One `resume` run on a note, after `next_retry_at`. A second mismatch on the same file goes to `project-manager` |
| A timeout, a refused or reset connection, the size limit, or another HTTP error after the fetcher's three attempts (FS-07) | `fetch.py` `_attempt` raises `FetchError`. The task fails, with a retry 30 minutes later, and the run goes on | Exit 0, status `partial` | **Not of record** (`failed`, `tasks`). One `resume` run on a note, after `next_retry_at` |
| A redirect off the approved route (FS-07) | `check_url` raises `ForbiddenHostError` before any byte is read from the other host. `_contain_task_failure` fails the task, and the run goes on | Exit 0, status `partial` | **Not of record.** No rerun until `data-steward` and `leak-auditor` have read the `error:` line. The client refused the redirect, so nothing came from elsewhere |
| A file passes its checksum and checks, then fails to parse (FS-07) | The file is quarantined and the task fails. The run goes on | Exit 0, status `partial` | **Not of record.** No rerun on a note alone, because the same bytes would fail again. Reviewed like a venue stop |
| A day's bars fail to build (FS-07) | `_fail_derive` records `bars_failed` and retries the day after `next_retry_at`. The run goes on. It also writes FS-05's day-keyed task rows, which no rerun clears | Exit 0, status `partial` | **Not of record** (`bars_failed`). One `resume` run on a note, after `next_retry_at`, rebuilds the day from the same curated month. `fetch_of_record` then accepts FS-05's rows only when that day's bar task reads `done`, and prints their count |
| A `resume` started before a failed task's `next_retry_at` (FS-07) | The task is skipped and still reads `failed`. The run ends `ok` | Exit 0, status `ok` | **Not of record** (`skipped_retry_wait`, `tasks`). Resume again after that time |
| F1, F2, F4's duplicates or K1 fail on one file | The file is quarantined with its check results kept, the task fails, and `VenueCheckStop` is raised | Exit 2, `error: <code>: <task key>` | **Stop, with no rerun.** The archive would serve the same bytes and fail the same way. `data-steward`, `project-manager` and `developer` review it. Under `D-43` and RB-02, a check never moves a tick row. A row changes only on a venue document and a new decision. Section 3.1 of the venue facts leaves open whether the 2020 funding files have F1's header |
| F1, F2, F4 or K1 read `false` over the span | `_venue_span` raises **before the final bar sweep. The first day of each candle month already fetched has bars** (FS-06). Every later `ingest` fails the same way until that month is fetched again and passes | Exit 2, `error: <codes>: <symbols>` | The same |
| F3, F5, K2 or K4 read `false`, or any flag reads `null` | No stop in code | Exit 0 | **Not the run's stop, but item 17's.** `item_17_counts` reads `no`. The first `V0` run waits until each one is reviewed. A `null` must be explained month by month |
| `versions_match: no` or `override_unchanged: no` | Nothing in code | Exit 0 | **Not of record.** `data-steward` and `python-reviewer` find out why before any rerun. `versions_match` covers every `ingest` row of the root, so a root that once recorded `+unknown` can never read `yes` again. That is a new root under rule 6c |
| A crash, a hard kill or a lost machine | Writes are atomic: a temporary name, then a rename. The next `ingest` sweeps temporary files and redoes what is not `done` | Varies | First, no process of the run may be alive (section 11). Then one `resume` run on a note |
| `files_digest` differs from `D-45` | Nothing in code | Exit 0 | **Not of record** (`files_digest`). Stop before any use. Section 6 |

**What a stop means here.** The run is not the fetch of record. Nothing in the root is used, and `--declare-costs` waits. `data-steward`
writes the stop to the decision log that same day, with the fixed word and the task key.

**The rerun rules (leak condition 6).**

- **(a) Every attempt is logged.** The script prints every attempt's digest, flag and count lines, stopped or not. The stop's decision log entry carries them, so bytes that change between attempts show up.
- **(b) The fetch of record is the first root, together with its resumes, whose invocation prints `fetch_of_record: yes`.** No second complete fetch is made while that root stands. If it is lost, a new fetch is a new decision, and its digests are compared with the first's.
- **(c) A new root needs a written note from `project-manager`.** That covers the P-2 case and a root whose versions can no longer match. The stopped root is then opened by no command, and goes only by a reviewed rule.
- **(d) After a resume, 11.3 is read from the catalog, not from the resume's own counts.** That means: 96 tasks `done` for each dataset, 2,922 bar days `done`, and no `open_task:` line apart from FS-05's rows whose day reads `done`. It also means `skipped_retry_wait` at 0, and every quarantine record already reported with its task now `done`. A resume's `planned`, `done` and `downloaded_bytes` count only its own run, so "192" cannot hold there. The judgement step checks all of this.

**What a rerun is.**

- The same script, in mode `resume`, at the same commit, into the same root, from a new run folder, on a written note from `project-manager`.
- The script builds and checks the folder again, so checks 1 to 5 run on every resume.
- Catch-up fetches only tasks that are not `done`: a failed task is fetched again from scratch, and an overdue one is tried again.
- Files already `done` are untouched, and their per-file check results stay.
- A rerun before a failed task's `next_retry_at` skips that task, so the note names a later time.
- There is no retry loop beyond the fetcher's own. No other host, mirror, region, proxy or VPN is used.

## 8. The market root: place, layout and class

**Place.** `hft-crypto-data`, directly in the owner's Documents folder.

| Requirement | Met by |
|---|---|
| Outside every git work tree | `DataRoot` refuses a root that has a `.git` folder in it or above it, both as written and after following links. The runner also confirms this before the run |
| Outside every agent's scratch folder | The owner's Documents folder is not under any agent's data folder |
| Survives the session | It is the owner's own folder, and no session removes it |
| New and empty, and no earlier root (`D-29`) | The script refuses a root that already exists in `first` mode |
| An absolute path with no space | The script refuses anything else (FS-03) |
| Separate from the sealed demonstration (`D-41`) | It sits beside the folder the owner approved for the sealed files, never inside it. Nothing in this plan lists or opens that folder. Opening it would be a read |
| **Reached without a search (RF-02)** | The root's full path goes to each runner directly, in the local channel. No command lists, globs or searches the owner's Documents folder, or names it as a root. Every later command on the root first prints `market_root_is_fetch_of_record: yes\|no` (11.3) |
| No copy to a cloud service | The coordinator reports that the folder is local and not synced by OneDrive (17.8). Other sync or backup clients are the owner's word (11.1 row 4) |
| Free space | At least 5 GB free on that drive (section 9) |
| Not written into the repository | Documents say "the market root". The path stays in the local log |

**Against `docs/08_DATA_CENTER.md`.**

- **Section 3, the zones: it fits.** `DataRoot` creates the same zones in any folder. Stage one fills `raw/archive`, `curated` and `catalog`, and possibly `quarantine`. Later, the engine writes `results/runs`. `raw/live`, `ledger`, `decisions` and `features` stay empty.
- **Section 5, running on GitHub: it does not fit, and it is not meant to.** That section puts curated data and the catalog in the Actions cache, with raw files lasting one job. This root is the local first run that `D-37` foresees ("It does not block a local first run").
- `project-manager` should record three things in the approval: no workflow reads or writes this root, nothing from it goes to the Actions cache while `D-37` is open, and nothing from it is published.
- After approval, I will add a short paragraph on the local market root to section 5 of `08_DATA_CENTER.md` and to "Current mode" in `05_DATA_LIFECYCLE.md`. In this root, raw files persist and no schedule touches it.

**Class and retention.**

| In the root | Class by zone (`classify` in `data/zones.py`) | Held | Deleted |
|---|---|---|---|
| `raw/archive/binance/klines/`, `.../fundingRate/` | `RE-DOWNLOADABLE` | **Kept for all of stage one** | **Never automatically.** Rule `raw-archive-after-curated` is not reviewed, and I do not mark it reviewed for this root. The archive republishes files (section 1 of the coverage record), so a second fetch may not return the same bytes. From the first `V0` run on, a run rests on these exact bytes, and deletion rule 4 then applies. Keeping them costs 179 MB |
| `curated/candles_official/`, `curated/funding/`, `curated/bars_*_official/` | `DERIVED` | Kept. Section 3 of the lifecycle document keeps candles at every timeframe | Never automatically. They can be rebuilt from raw files while the raw files are here |
| `quarantine/` | The source's class, here `RE-DOWNLOADABLE` | Kept until `data-steward` reviews each record | Only by a reviewed decision |
| `catalog/`: the manifest, run rows and logs | No class by zone. No rule can ever select this zone (`FORBIDDEN_RETENTION_ZONES`) | Kept | Never |
| `catalog/trial_registry.jsonl`, from C-5 part 4 on | **`IRREPLACEABLE` in substance.** It is our own record of every trial, and nothing can fetch or rebuild it | Kept forever, with a copy outside the root | Never |
| `results/runs/`, later | `DERIVED` | As section 3 of the lifecycle document says | Only by a reviewed rule, and none is reviewed |

**A root that stopped and was replaced** under rule 6c is opened by no command, and goes only by a reviewed rule.

**Open item: the registry's second copy.** `--declare-costs` and every `V0` run append to `catalog/trial_registry.jsonl` inside this root.
The deflated Sharpe ratio rests on its count, and it is the only copy. I propose two things. After each append, its SHA-256 and row
count go into the decision log. A copy of the `catalog/` folder is kept outside the root, wherever the owner chooses. That is the same
care the lifecycle document gives the ledger and decisions. `project-manager` and the owner decide, before part 4.

**Watermarks.** These are measured against the default `DATA_QUOTA_GB` of 4 GB, on `curated`, `features` and `catalog`. That comes to about
0.64 GB, or 16%, which is under the 70% warning (`UNVERIFIED`, section 9). The script unsets `DATA_QUOTA_GB`. No scheduled job reaches
this root, so nothing in it is deleted, and the daily report for it is the size lines of each run.

**Terms.** `D-29` allows personal, non-commercial research, so keeping a local copy for it is within those terms. The manifest records
the licence note for each dataset. Nothing from this root goes into git, a cache, a synced folder or a publication. Anything derived from
it that is shared carries the attribution.

## 9. Size and time

**Size on disk.**

| Zone | Contents | Bytes | Basis |
|---|---|---|---|
| `raw/archive/binance/klines` | 96 zips. Sidecars are not kept | 179,120,784 | **Measured.** `D-45`'s `bytes_in_root` of 179,138,240, less 96 sidecars of 89 bytes, the 12-byte marker and the 8,900-byte output document |
| `raw/archive/binance/fundingRate` | 96 zips | 85,241 | The listing's total of 179,223,977 bytes, less every sidecar (96 × 89 and 96 × 98) and the candle zips. Not measured |
| Raw in all | 192 zips | **179,206,025** | A first run's `downloaded_bytes` should read this if no file has changed |
| `curated/candles_official` | 96 monthly parts | about 185 MB | `UNVERIFIED`. Section 2.1 of the coverage record, from daily parts built by older code |
| `curated/funding` | 96 monthly parts | under 1 MB | `UNVERIFIED` |
| `curated/bars_*_official` | 8 datasets × 2,922 symbol-days = 23,376 files | about 399 MB | `UNVERIFIED`. Section 2.1 of the coverage record |
| `catalog` | SQLite and logs | about 59 MB | `UNVERIFIED`. Section 2.1 of the coverage record |
| **In all** | about 23,770 files | **about 0.82 GB** | Only the raw zone is measured. The run's `zone_bytes` lines replace the rest |

**Free space.** `ingest` holds every download while less than 2,000,000,000 bytes are free (`max_download_bytes`). With about 0.8 GB of
data on top of that, the runner confirms at least 5 GB free before the run.

**Time on this machine.**

| Part | Requests | Time | Basis |
|---|---|---|---|
| Candle zips and sidecars | 192 | 530 s with a 2 s pause after each request. 146 s without the pauses | **Measured,** `D-45`: 530 s, of which 384 s were pauses. The 146 s includes parsing each file in memory |
| Funding zips and sidecars | 192 | At most about 146 s without pauses, and 384 s more with them | **Estimate, `UNVERIFIED`.** The same number of requests, carrying 0.05% of the bytes. A candle request's average time, 0.76 s, is taken as the upper bound |
| **Fetch in all** | **384** | **About 5 minutes without pauses (at most 292 s). About 18 minutes with them (at most 1,060 s)** | The two rows above. With P-1 in, the second figure applies |
| Per-file checks and curation | none | Not measured | K1 to K4 look up a tick in Python for each of about 2.1 million minutes per symbol. Each part is written as Parquet and registered |
| Bars for 2,922 symbol-days | none | **About 21 minutes, as a rough guide only** | `python-reviewer`'s stand-in built 184 symbol-days in about 80 s while other jobs ran (section 7 of its review). Scaled to 2,922 days that is about 1,270 s, `UNVERIFIED` |
| **The whole run** | | **Allow 60 minutes, `UNVERIFIED`** | `ingest_started` and `ingest_finished` measure it. The decision log entry records the measured figure, which replaces this estimate |

The run takes longer than an agent's foreground call allows, so it starts in the background with no time limit (RE-02).

## 10. What the runner reads

**Who runs it:** the main session, as for the coverage check. It reads the script's printed lines and nothing else under the run
folder, except `venue_checks.json`.

**The printed lines.**

| Line | Content |
|---|---|
| `run_folder: <path>` | The run folder. **Local log only.** No document, decision log entry, commit or other agent receives it |
| `uv`'s own lines | Tool and package names and versions. `uv sync` also prints `Building hft-crypto @ file:///<run folder>/repo`, which holds the user name. **So they stay in the local log only, as `run_folder:` does** (FS-08) |
| `commit <sha>: clean clone` | The full commit hash |
| `override: ...`, `override_sha256: pipeline=... engine=... retention=...` | Fixed text and three hashes |
| `code_version:`, `source_state:`, `enabled_hosts:`, `last_opened_date:`, `config_hash:` | Version and 12 hex characters, fixed words, one host, one date, two hashes |
| `DATA_ROOT zones and catalog are ready.` | Fixed text from `init` |
| `ingest_started:`, `ingest_finished:`, `ingest_exit:` | Two UTC times and an integer |
| `override_sha256_after:`, `override_unchanged:` | Three hashes and a yes or no |
| `run_rows_this_invocation:`, and `run_row: none` when it is not 1 | An integer, and fixed text |
| `run_status:`, `stop_reason:`, `run_code_version:`, `run_config_hash:` | Fixed words, a version and a hash |
| `planned:` to `downloaded_bytes:` | Sixteen integers, for this invocation's run only |
| `error: <task key> <reason>` | The reason only after `publishable_reason`, which removes every number and path (P-6) |
| `alert: <text>` | `ingest`'s own sentences. They hold task keys, root-relative paths and counts only |
| `versions_match:`, `ingest_rows_version: <code_version> <config_hash> <count>` | A yes or no, then each distinct pair among the root's `ingest` rows |
| `raw_files:`, `raw_checksum_source:`, `raw_with_venue_checks:`, `raw_bytes:`, `raw_missing_on_disk:`, `raw_hash_differs_from_catalog:` | Counts by kind, status and fixed word, and bytes |
| `funding_file: <symbol> date=<month> missing [...] outside_month [...] off_grid [...]` | Settlement times, printed only for a file that has any. This gives item 17's list for F4 |
| `tasks:`, `open_task: <key> <state> <time>` | Counts by state, and the keys of tasks that are not done. No error text |
| `curated_files:`, `gaps:`, `exclusions_open:`, `quarantined:` | Counts by kind and status |
| `quarantine: <dataset> <symbol> <partition> <reason> <sha256> <size>` | The fields of the published quarantine record. Its reason has already passed through `publishable_reason` |
| `venue_checks: none`, or `venue_checks_sha256:` and `venue_check: <symbol> <check> <json>` | From this invocation's run row only (FS-01). Each check's result: pass, counts and `months_checked`. Also F2's rows as a time and an interval in hours, F3's largest offset in ms, F4's expected, missing and duplicate counts with its settlements outside the span, F5's times, K3's first and last minute, and K5's rows, missing and duplicates |
| `zips:`, `files_digest:`, `funding_digest:`, `candle_zip_names_ok:`, `files_digest_python:`, `files_digest_expected:` | Counts, hashes and a yes or no |
| `zone_bytes:`, `files_in_root:`, `free_bytes:` | Sizes and a count |
| `fs05_rows:`, `venue_checks_json_clean:`, `item_17_counts:`, `fetch_of_record_run_id:`, `fetch_of_record:` | A count, yes or no, the names of checks or items that fall short, and a run id |
| `done:` | A time |

**The flag file.** `venue_checks.json`, in the run folder. The script writes it from this invocation's run row, indented and with LF
line endings, and prints its hash. It is written only when the span check ran. The runner may open it.

**Committing it (leak condition 5).**

- Only the fetch of record's file is committed. It must be byte for byte the file with the printed hash, and `venue_checks_json_clean` must read `yes`.
- It goes in as `docs/reviews/data/venue_checks_first-span_<date>.json`, with a `-text` line in `.gitattributes`, as for `D-45`'s documents, and with the attribution in its decision log entry. It is copied into the repository before the run folder goes.
- The shape check requires:
  - top-level keys `BTCUSDT` and `ETHUSDT`, exactly;
  - check names from `F1` to `F5`, `K1` to `K5` and `K2_K4`;
  - fields from the code's own list only;
  - no float anywhere, tested by name, because `bool` is an `int`;
  - every string an ISO UTC time, with fractional seconds allowed, or the code's one fixed note.
- A stopped run's flags go into its entry as lines. If its file is committed as well, its name says `stopped`.
- The same values stay in the catalog: in the run row, in `meta`, and file by file in each raw file's `check_detail`. Those are the manifest's integrity results.

**Paths and error text (leak condition 4).**

- The root's path is held as condition 3 of 17.7 holds the run folder's: local log only.
- It can still reach that log through an error from `du`, `find` or a traceback in the report step.
- It reaches no document, entry, commit or post, and no agent but a runner who needs it.
- The decision log entry takes task keys and fixed words from `error:` and `quarantine:` lines, never the text after them.

**Never printed or opened:**

- prices, volumes, taker flow, funding rates, trade counts, or any row;
- `ingest.json` and `ingest.err` in the run folder;
- `catalog/last_ingest.json`;
- the catalog's `last_error` column, and any `check_detail` content apart from `checksum_source` and `venue_checks`;
- any file under `curated/`, and the contents of any zip;
- the sealed demonstration's folder.

The first span is open, so this is not a closed-date boundary. It keeps the record at counts, as section 3 of the venue facts requires
("never a price or a rate"), so that no reading has to be logged for it.

**No date after 2023-12-31 enters the root.**

- No partition after 2023-12 is planned or fetched, no 2024 candle is stored, and no bar is built after 2023-12-31.
- The 2023-12 funding part can hold the 2024-01-01 00:00 settlement, stamped a little early or a little late. Stamped at or before 00:00, it is the boundary value already ruled (RC2-01, FP-07). Stamped after, the reader never returns it.
- F4's `outside_span` shows its hour either way. Nothing in this plan reads a rate.

## 11. Before and after the run

### 11.1 Before

| # | Condition | Who |
|---|---|---|
| 1 | P-1 reviewed. It is committed at `7bd375f`, and `leak-auditor` rules it `PASS`. `python-reviewer`'s review is still to come | `python-reviewer` |
| 2 | **The run commit is the C-5 commit.** Its `src/` and `configs/` equal `7bd375f`'s, as the addendum restates leak condition 1. The full suite passes at it, with its output recorded, as item 18 asks. `RUN_SHA` is filled in, the file is hashed with LF endings, and the hash is pinned | `project-manager`, the coordinator |
| 3 | The revised script rechecked: `python-reviewer` on FS-01 to FS-03 and the other changes listed in section 5, and `leak-auditor` on conditions 2, 5, 6 and 7 as met here | `python-reviewer`, `leak-auditor` |
| 4 | The root confirmed: `hft-crypto-data` directly in the owner's Documents folder, not there yet, and at least 5 GB free. The coordinator reports no OneDrive sync. The owner's word covers any other sync or backup client | Owner |
| 5 | Approval recorded in the decision log. It names the option for the switch, the C-5 commit, the script's SHA-256 with LF endings, and the root by description only | `project-manager` |
| 6 | The registry's second copy decided, before part 4 (section 8) | `project-manager`, owner |

### 11.2 The runner's steps

These follow section 11.4 of the coverage check plan.

1. **Before.** In the shell that will run it, the runner confirms these and prints only yes or no for each, never a value:
   - The file hashes to the pinned value and has LF line endings.
   - `mktemp -u -d` names a folder directly in the system temporary folder, inside no agent's folder.
   - `DATA_ROOT` and `HFT_CONFIG_DIR` are unset in the shell. If either is set in the user or machine environment, it does not name the market root or an earlier root.
   - The Documents folder holds no `hft-crypto-data` and is inside no git work tree. This is checked by testing that one name, not by listing the folder (RF-02).
2. **How.** `bash run_first_span_fetch.sh <this repository> <the market root> first`, started in the background with no time limit. The owner gives the root's full path to the runner directly.
3. **Stopping.** Only with `taskkill /F /T` on the run's `uv.exe`, found by name and by the run folder's last part, as in section 6 of the coverage script review. Never with a signal to bash, `kill -9`, or `taskkill /F` without `/T`.
4. **After a stop or a kill,** and before anything is read, the count of the run's `uv.exe`, `python.exe` and `hft-crypto.exe` processes must read 0. An orphaned process writes only first-span files over the approved route, but counts read while it is still writing are wrong.
5. **Paths.** The run folder's path and the root's path stay in the local log.

### 11.3 After

**The fetch of record: the invocation prints `fetch_of_record: yes`, and the script exits 0.** The judgement step computes it, for a
`first` run and for a `resume` alike, from the catalog and the files rather than from one run's counts (FS-04, leak condition 6d). Every
item below must hold, and a `no` names each item that fails:

- `ingest_exit` is 0, `run_rows_this_invocation` is 1, and that row reads `ok` with `stop_reason` `none`.
- That row's `pending`, `overdue`, `failed`, `skipped_retry_wait`, `held_by_watermark`, `held_by_disk`, `not_started_time_budget`, `bars_failed` and `bars_left_by_budget` are all 0.
- `versions_match` reads yes: exactly one `(code_version, config_hash)` pair across the root's `ingest` rows, one `code_version` across every manifest row, both equal to step 2's, with no `+unknown` and no `-dirty`. `override_unchanged` reads yes.
- `tasks`: `binance.klines` 96 `done`, `binance.fundingRate` 96 `done`, `derived.bars.binance` 2,922 `done`, and no other task open. The only exception is FS-05's day-keyed rows, and only when that day's bar task reads `done`. `fs05_rows` gives their count.
- `raw_files`: 96 `klines` and 96 `fundingRate`, all present and none in another state. All 192 read `checksum_source` `sidecar`, all carry `venue_checks`, and every one hashes to its catalog value.
- `quarantine`: no record from this invocation, and every earlier record's task now reads `done`. That those records were reported in an earlier attempt's log, the runner confirms against that log.
- `curated_files`: 96 `candles_official` parts, 96 `funding` parts, and 2,922 parts in each of the eight bar datasets. `gaps` and `exclusions_open` are both 0. On candles that follows from `D-45`'s zero unproved empty minutes.
- `files_digest`: the bash value, the Python value and `D-45`'s are equal. There are 96 candle zip names, each once, and 96 funding zips.
- `venue_checks.json` exists for this invocation, passes the shape check, and equals the run row's flags.

**Item 17, per symbol (leak condition 3).** `item_17_counts: yes` means all of these:

- F1, F2, F3 and F5 each read `true` with `months_checked` 48.
- F4 reads `true` with `months_checked` 48, `expected` 4,383, `duplicates` 0 and `missing` 0.
- K1 reads `true` with `months_checked` 48 and **`K1.minutes` 0**.
- K5 reads 2,103,840 rows, with 0 missing and 0 duplicates.
- **BTCUSDT: K2 reads `true` with `months_checked` 48 and `K2.months_at_0_01` 26.**
- **ETHUSDT: K4 reads `true` with `months_checked` 48 and `K4.months_at_0_01` 48.**

A pass with other counts means the run's tick table is not `D-43`'s, and item 17 is not met. If `item_17_counts` names only F4, and
the `funding_file:` lines list every missing settlement, item 17 can still be met by review. K3's first and last minute go to review in
every case, and no tick row is dated from them.

**The decision log entry.** `data-steward` writes it from the printed lines, with no path. It records:

- the C-5 commit and the script's hash;
- both `override_sha256` lines and both `config_hash` values;
- every `ingest_rows_version:` pair;
- `run_rows_this_invocation`, `versions_match`, `override_unchanged` and `fs05_rows`;
- the start and end times and the exit code;
- the counts above, the three digests and every flag with its `months_checked`;
- F4's list, and K3's first and last minute;
- `venue_checks_sha256` and `venue_checks_json_clean`;
- the zone sizes and the free space;
- `fetch_of_record_run_id`, which later commands check against (below);
- "the market root", a new folder in the owner's Documents folder.

From `error:` and `quarantine:` lines it takes only task keys and fixed words (leak condition 4). A stopped attempt gets an entry the
same day, with the same lines (rule 6a).

**The run folder.** It goes once the entry is written and the flag file is copied out, and only after a count of `*.zip`, `*.parquet`
and `*.sqlite` files under it, outside `repo/`, reads 0. At that point it holds no dataset, so removing it is not a deletion under
section 5 of the lifecycle document. It takes the only copy of the switch with it.

**Before every later command on the root (RF-02).** That covers `--declare-costs`, section 6's recount script if it is ever needed, and
any `V0` run. The runner gets the root's full path directly and the run id from the entry, then runs this. The command goes ahead only
on `yes`. This text is for those commands' own reviews:

```bash
test "$(basename "$ROOT")" = "hft-crypto-data"
uv run --frozen --no-dev python - "$(cygpath -m "$ROOT")" "$RUN_ID" <<'EOF'
import pathlib, sqlite3, sys
root, run_id = pathlib.Path(sys.argv[1]), sys.argv[2]
catalog = root / "catalog" / "catalog.sqlite"
found = 0
if root.name == "hft-crypto-data" and catalog.is_file():
    db = sqlite3.connect(f"{catalog.as_uri()}?mode=ro", uri=True)
    found = db.execute(
        "SELECT COUNT(*) FROM runs WHERE run_id = ? AND kind = 'ingest' AND status = 'ok'", (run_id,)
    ).fetchone()[0]
print("market_root_is_fetch_of_record:", "yes" if found == 1 else "no")
sys.exit(0 if found == 1 else 1)
EOF
```

**Then C-5 part 4.** `developer` runs it from a clean clone at the C-5 commit, after the check above reads `yes`:

```bash
uv run --frozen --no-dev python -m hft_crypto.engine --data-root "<the market root>" --config configs/engine.toml \
  --start 2020-01-01 --end 2023-12-31 --declare-costs
```

- It needs no switch.
- The parser requires `--start` and `--end`, and `declare_costs` does not use them.
- It prints `The configuration's costs are in the trial registry. Nothing ran.`
- From then on, the root holds the registry (section 8).

## 12. Reviews, and what is not decided here

| Reviewer | Verdict so far | What comes back to them |
|---|---|---|
| `leak-auditor` | `PASS WITH CONDITIONS`, 17.8. P-1 `PASS` in its addendum, not yet committed | Conditions 2, 5, 6 and 7 as met here. The engine run's own plan later, under condition 8 |
| `python-reviewer` | `PASS WITH CONDITIONS` | The revised script: FS-01 to FS-03 in its tested text, and the additions listed in section 5. P-1 at `7bd375f`, which needs a fake-clock test covering every request, the sidecar included |
| `developer` | Not a reviewer | After the fetch: FS-02's code part, FS-05, FS-10, P-2, P-3 and P-7, before stage two |
| `project-manager` | Not a reviewer | The switch (section 3), the approval entry, the root together with the owner, and any rerun note |
| Owner | Not a reviewer | Other sync or backup clients, and the registry's second copy |

| Not decided here | My proposal | Who decides |
|---|---|---|
| The switch | Option B, by flag. `leak-auditor` accepts it on RF-01 | `project-manager` |
| The root | `hft-crypto-data` in the owner's Documents folder | Owner, `project-manager` |
| Committing `venue_checks.json` | Yes, byte for byte, for the fetch of record only, once `venue_checks_json_clean` reads `yes`. `leak-auditor` allows it on condition 5 | `project-manager` |
| The registry's second copy | A copy of `catalog/` outside the root, plus a hash and row count in the log after each append | `project-manager`, owner |
| A recount if `files_digest` differs | The same checker, on the root's files, through a reviewed script | `project-manager`, `leak-auditor` |
| Rule `raw-archive-after-curated` for this root | It stays unreviewed. Nothing is deleted during stage one | `data-steward`, as rule owner |

## 13. Not checked

- **Any host.** Whether every file is still served, and whether any changed after `D-45`'s run, is unknown until the run.
- **The whole script.** It has not run in any form here. `python-reviewer` ran the earlier text with `ingest` stood in. The new heredocs were run on their own, on invented data (section 5).
- **The 96-month case.** No span flag reading `true` over 48 months, no `candle_zip_names_ok: True` and no `fetch_of_record: yes` has been seen. Those need the real files.
- **Times** for funding requests, the per-file checks and the bars (section 9).
- **The header of the 2020 funding files.** Section 3.1 of the venue facts leaves it `UNVERIFIED`. F1 stops the run if it differs.
- **Interference during a rename.** Whether antivirus or the search indexer holds a new file during a rename. The code would contain that as a failed task, and the judgement would read `no`.
- **Other sync or backup clients** on the machine, which are the owner's word.
- **P-1's code.** I read only its diff stat: `cli.py`, `data/fetch.py` and the new test, with no other change against `0b853bd` in `src/` and `configs/`. My offline tests above ran at `6b15ea7`, before it.
