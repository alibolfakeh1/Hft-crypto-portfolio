**The script fetches and reports a clean first run correctly. A resume run can print an earlier run's row, so it needs changes. The ingest process can also record a version that is not the commit, and the script does not notice. Three of the script's lines change, and §11.3 changes, before approval. P-1 is still pending.**

# Code review: the first-span fetch script, its commands and its stop table

Reviewer: `python-reviewer`. Date: 2026-11-06. I ran everything in Git Bash on the machine that will run the fetch.

**What was reviewed:**

- **The script.** This is section 5 of `docs/reviews/data/first_span_fetch_plan_2026-11-06.md` at `d6da50c`. I extracted the block myself. It has LF endings and 194 lines. With the `RUN_SHA` placeholder still in it, it hashes to `d58f3dcd3d15727c51aed3d3314888b308ef980f9a30d85a84a1f591cc249ac2`. That hash changes when `RUN_SHA` is filled in.
- **The plan's other sections that the script and the stop table rest on:** 2, 3, 4, 6, 7, 10 and 11.3.
- **The code under the plan.** `git diff 0b853bd d6da50c -- src configs pyproject.toml uv.lock` is empty. `tests/` equals `8ba8c83`. I read these:
  - `cli.py`: `main`, `_cmd_init`, `_cmd_ingest` and `_market_ticks`.
  - `data/ingest.py`, all of it.
  - `data/fetch.py`.
  - `data/venue_checks.py`.
  - `config.py`: `find_config_dir`, the loaders and `PipelineConfig`.
  - `data/catalog.py`: the schema, `register_file`, `start_run` and `finish_run`.
  - `data/zones.py`, `data/sources.py`, `versioning.py` and `data/atomic.py`.
  - `data/derive.py`: `derive_day`, `_derive_from_candles`, `needs_derive` and `reopen_day`.
- **The leak auditor's two notes and five conditions** from section 17.8 of `docs/reviews/leak/data_center_recheck_2026-11-04.md`, as the coordinator relayed them to me. That section is uncommitted, and I did not read it myself.

**Limits I kept:**

- **No `hft-crypto ingest` ran.** No market data host and no package index was contacted, because every `uv` call ran with `UV_OFFLINE=1`. The real market root was not created. I ran `df` on the drive that holds the Documents folder, and that was the only time I touched that folder.
- **Where I needed a catalog that real code had filled,** I called `run_ingest` in-process with a fake fetcher, the way `tests/data/test_venue_checks.py` does. An audit hook in that process refused every socket connect and name lookup. The fake fetcher served zips I generated: months 2023-10 to 2023-12, both symbols, both datasets. Every price and rate in them is invented.
- **How `main` maps exit codes** was checked separately. I called `cli.main([... "ingest" ...])` with `run_ingest` replaced by a stand-in that only raises, so nothing ran and nothing was fetched.
- **Probe roots, run folders and clones** were all in one fresh folder of my own under the system temp folder. Production code, the plan and the script were not edited, and nothing was committed.

## 1. Verdict

**`PASS WITH CONDITIONS`.**

**What holds, run on this machine.** The first five items come from a run of the script itself. I changed only two things: `RUN_SHA` became `d6da50c`, and step 4 became the offline stand-in. Every other line ran as written, against a dummy root named `hft-crypto-data` in a folder whose path has a space.

- **The steps before the fetch.** The clone is clean under the system's `core.autocrlf=true`. `code_version` printed `0.1.0+d6da50c87628`. The repository's configuration read `'no approved source configured'` and the run's read `'binance'`. `enabled_hosts` was `data.binance.vision` and `last_opened_date` was `2023-12-31`.
- **The override generator.** On the CRLF checkout it changed exactly one line and kept all 291 CRLF endings. `diff` counted 2 lines. It refuses a trailing comment on that line, and it refuses a second `enabled = false` under `[sources.binance]`.
- **The order and the exit codes.** `set +e`/`rc=$?`/`set -e` captures the exit code of `ingest`. The report then runs, and the script exits with that code. `uv run` passes exit codes 0, 1, 2 and 3 through unchanged. `main` turns `HostRefusalStop` into a traceback and exit 1, and `VenueCheckStop` into `error: <code>: <key>` and exit 2.
- **The read-only catalog.** A `file:` URI with `mode=ro`, on a path with a space, reads the catalog. It refused a write ("attempt to write a readonly database"), and the bytes and the folder were unchanged afterwards.
- **The clean report checks against hand counts,** which come from the bytes served and not from the catalog. Details are in section 3.4:
  - 12 tasks, of which 12 are done.
  - 184 bar days, which is (31 + 30 + 31) × 2.
  - `raw_bytes` and `downloaded_bytes` equal the bytes served.
  - `files_digest` from bash, from the Python cross-check and from the served bodies are all equal, inside a path with a space.
  - F4 shows 4,383 expected and 4,107 missing. K5 shows 2,103,840 expected, 132,480 rows and 1,971,360 missing. K3 shows 18,928 minutes.
- **`ingest` computes F1 to F5, K1 to K5 and the span flags in the same command** (section 3.7).
- **I checked the stop table against the code,** case by case, in a probe run for each case. P-2, P-3, P-4 and P-5 behave as the plan says. Section 3.6 lists two mistakes in the text and the rows the table is missing.
- **The static checks and tests at `d6da50c`:**
  - `ruff check` and `ruff format --check` are clean.
  - `mypy` (strict) reports no issues in 119 files.
  - `pytest -m "not network"`: **2032 passed, 2 skipped**. Both skips are file symlinks, which need a privilege on this machine.

**Conditions.** Conditions 1 to 3 change the script, so its hash changes. The new text comes back to me for a recheck before `project-manager` records the approval.

1. **Report this run's row, and this run's flags (FS-01, the leak auditor's note 1).** The report must select only the `ingest` row this invocation started. It must take `venue_checks` from that row's summary and not from `meta`. If there is no such row, it must print `run_row: none` and `venue_checks: none`.
2. **Compare the recorded version with the commit (FS-02).** The run's `ingest` process recorded `0.1.0+unknown` while step 2 printed the commit. The report must print `versions_match: yes|no`. "Yes" means four things:
   - exactly one `(code_version, config_hash)` pair across all `ingest` rows;
   - one `code_version` across every manifest row;
   - both equal to step 2's values;
   - not `+unknown` and not `-dirty`.

   This is the leak auditor's condition b, extended to the manifest rows.
3. **Refuse a market root path that is relative or holds a space (FS-03).** A relative path passes the guards on lines 159 to 162. After `cd`, though, it puts the root inside the run folder.
4. **§11.3 and the stop table, corrected for a resume and for the missing cases (FS-04, FS-06, FS-07).** This is a text change and does not change the script.
5. **P-1.** Its diff has not reached me, and it is a separate review (section 8).

I tested the exact text for conditions 1 to 3 on this machine, and it is in section 5. FS-05, about `_fail_derive`, is for `developer`. FS-08 to FS-11 and R-1 are not conditions.

## 2. Each item the plan asks of me, and the line that does it

Line numbers are those of the plan file at `d6da50c`. The script runs from line 149 to line 342.

| Plan item (line 639) | Line | Result |
|---|---|---|
| `init`, then one `ingest` with the stated flags | 226, 229-232 | Holds. The flags go in the right place: `--data-root` and `--config-dir` come before the command name. `ingest --help` lists `--datasets`, `--symbols`, `--start`, `--end` and `--event`. `init` run twice on one root leaves the catalog byte-identical, so `resume` mode is safe |
| Exit-code handling | 228-236, 342 | Holds for capturing the code (section 3.1). A failure in the report ends the script with the report's code instead (FS-11) |
| Override, check 1: exactly one line differs | 179-200, 203 | Holds (section 3.2) |
| Override, check 2: `tomllib` equality | 194-199 | Holds. Every check is an `assert`, which `PYTHONOPTIMIZE` removes (FS-09) |
| Override, check 3: byte copies | 201-202 | Holds. Without `engine.toml`, `cmp` fails. That closes the silent `None` in `_market_ticks` (`cli.py:208-209`) |
| Override, check 4: the loader | 209-224 | Holds. `run.enabled_sources() == ("binance",)` proves the folder's `pipeline.toml` was read, because the repository's copy has no source enabled |
| Override, check 5: the hashes printed | 205-206, 219 | Holds. `config_hash` hashes the parsed TOML (`stable_hash(raw)`), so CRLF does not change it. The three `override_sha256` values hash bytes. On this machine they are the CRLF files' hashes, not the git blobs' |
| Digest line inside the candle folder | 313-323 | Holds (section 3.3) |
| Python cross-check | 324-333 | Holds. Its sort order equals `sort -k2` under `C`, `C.UTF-8` and `en_US.UTF-8` for the 96 real file names |
| Read-only catalog queries | 239-310 | Every column and table exists in the schema. The row selection is wrong after an early exit (FS-01) |
| The fixed stop word after a host refusal | 252 | Holds. `stop_reason` read `http_403`. The `error:` lines mangle the word to `http_#`, because `publishable_reason` replaces digits, and that is harmless |
| `cygpath`, `sha256sum`'s `*`, `du -sb`, `df` | 207-208, 318, 337, 340 | Hold (section 3.5). `cygpath -m` turns a relative path into an absolute one, measured from wherever the shell is at that moment (FS-03) |
| Stop table against the code | Section 7 | Section 3.6 |
| F1 to F5, K1 to K5 and the span in one command | Section 4, step 4 | Section 3.7 |

**Lines with no clause:**

- Line 165 prints the run folder. That is intended, and it goes to the local log.
- The `uv sync` lines on line 170 also print that path, with the user name in it. The table in §10 does not say so (FS-08).

## 3. The checks

### 3.1 Order and exit codes

| Case | What ran | Seen |
|---|---|---|
| A refusal (`HostRefusalStop`) | `cli.main` with `run_ingest` raising, through `uv run` | Traceback ending `hft_crypto.data.ingest.HostRefusalStop: http_403: archive:binance.klines:BTCUSDT:2023-12`, uv exit **1** |
| A venue stop (`VenueCheckStop`) | The same | `error: F1_HEADER: archive:binance.fundingRate:BTCUSDT:2020-01`, uv exit **2** |
| `uv run python -c "sys.exit(n)"` | n = 0, 1, 2, 3 | 0, 1, 2, 3 |
| `init` with a root inside the clone | `hft-crypto --data-root <clone>/inside init` | `error: DATA_ROOT must be outside the repository, ...`, exit 2, nothing created |
| `ingest` fails before its run row | Probe script, step 4 stood in by a process that exits 2, `first` mode | `ingest_exit: 2`, `run_row: none`, script exit 2 |
| The same in `resume` mode, on a root whose last run ended `ok` | The same | `ingest_exit: 2`, but **`run_status: ok stop_reason: none`, `planned: 12`, `done: 12`**, all from the earlier run (FS-01) |

Exit code 2 is ambiguous on its own. Each of these also exits 2:

- an argparse error;
- `ConfigError`, `DataRootError`, `PathGuardError`, `SourceDisabledError` or `ValidationError`;
- `uv` itself failing.

Only a run row from this invocation tells a venue stop apart from the rest. That is the reason for condition 1.

### 3.2 The override generator

I ran lines 180 to 199 verbatim with the clone's Python 3.12:

| Input | Result |
|---|---|
| The shipped `pipeline.toml`, CRLF checkout | rc 0. One hit. 291 of 291 CR kept. The `diff` count is 2 |
| An LF copy | rc 0 |
| `enabled = false  # shipped off` | rc 1, `not exactly one enabled = false under [sources.binance]` |
| A second `enabled = false` under `[sources.binance]` | rc 1, the same |
| `assert False` with `PYTHONOPTIMIZE=1` | **The assert is skipped.** With `python -I`, it raises again, and `hft_crypto` still imports from the clone (FS-09) |

Checked against the code, the plan's three ways the folder can go wrong all fail closed or are caught:

- Without `pipeline.toml`, `find_config_dir` falls back to the clone's own `configs/` (`config.py:367-380`), where the source is disabled. `ingest` then refuses with exit 2.
- Without `retention.toml`, loading fails.
- Without `engine.toml`, `cmp` stops the script.

### 3.3 The digest line and its cross-check

I ran the probe root's 6 candle zips through the script's lines, verbatim, in a path with a space:

| Form | Digest |
|---|---|
| Line 318, inside the candle folder | `e7d06cb88337d97b2d405c2db0c941810b4cc2ef62a0bac0f82232b5929c3c0a` |
| Line 332, the Python cross-check | `e7d06cb88337d97b2d405c2db0c941810b4cc2ef62a0bac0f82232b5929c3c0a` |
| From the served bodies, in the stand-in, before any file was written | `e7d06cb88337d97b2d405c2db0c941810b4cc2ef62a0bac0f82232b5929c3c0a` |
| The coverage script's form, `find "<root>/raw/archive/binance/klines"` | `7ca64032...` (wrong: awk keeps `space` as the name) |
| The coverage script's form as written, `find "<root>/raw"` | `a380b843...` (wrong: it includes the funding zips too) |

**Other facts about the line:**

- Git Bash's `sha256sum` prints `*./BTCUSDT/date=.../...`, and awk keeps only the base name.
- Temporary files end in `.tmp-<pid>-<hex>`, so `*.zip` never matches one. In the sidecar-refusal case, a 260,875-byte temporary zip sat in the raw zone, and `zips: klines` still read 2.

The D-45 value cannot be checked offline. The coverage output holds no hash for each file. The line is the coverage script's line with only the folder changed, and awk keeps only the hash and the base name, so the text that gets hashed is the same.

### 3.4 The read-only queries, on catalogs that real code filled

I ran each scenario below through the probe script, with step 4 stood in.

| Scenario | `ingest_exit` and status | Lines that decide it |
|---|---|---|
| Clean | 0, `ok` | `planned: 12`, `done: 12`, `bars_built: 184`, `raw_checksum_source: {'sidecar': 12}`, `raw_with_venue_checks: 12 of 12`, `raw_hash_differs_from_catalog: 0`, `curated_files` 6 + 6 + 184 × 8, `files_in_root: 1500` (12 + 12 + 1,472 + 4 catalog files) |
| 404 on a listed zip | 0, **`ok`** | `overdue: 1`, `open_task: archive:binance.klines:ETHUSDT:2023-11 overdue None`, ETHUSDT K1 `months_checked: 2` |
| 404 on a sidecar | 0, **`ok`** | `raw_checksum_source: {'none': 1, 'sidecar': 11}`, task done |
| Checksum mismatch | 0, `partial` | `failed: 1`, `quarantine: ... checksum: SHA-# does not match the checksum sidecar <sha256> 269130`, run went on |
| Timeout after the fetcher's attempts | 0, `partial` | `failed: 1`, run went on. **Not in the stop table** (FS-07) |
| 403 on a zip | 1, `failed` | `stop_reason: http_403`. 13 requests, the last one refused, and none after it. `venue_checks: none`. **`bars_built: 4`** (FS-06) |
| 403 on a sidecar | 1, `failed` | The same, plus one temporary zip left in the raw zone (P-5). **`bars_built: 2`** |
| A file stop (K1) | 2, `failed` | `stop_reason: K1_PRICE_OFF_0_01`, `raw_files: klines quarantined 1` |
| A span stop (F4 across two months) | 2, `failed` | `stop_reason: F4_DUPLICATE_SETTLEMENT`, `funding_file: BTCUSDT date=2023-11-01 ... outside_month ['2023-12-01T00:00:00Z']`, **`bars_built: 6`** before the stop (FS-06) |
| Resume before `next_retry_at` | 0, **`ok`** | `planned: 1`, `done: 0`, `skipped_retry_wait: 1`, and the task is still `failed` (FS-04) |

**How the hand counts were made, for the clean run:**

- **F4 missing:** 4,383 − 3 × 92 = 4,107.
- **K5 missing:** 2,103,840 − 132,480 = 1,971,360.
- **K3 minutes:** every seventh minute is off the 0.1 grid, so ⌈44,640/7⌉ + ⌈43,200/7⌉ + ⌈44,640/7⌉ = 6,378 + 6,172 + 6,378 = 18,928.
- **Mismatch:** `raw_bytes` for klines is 1,598,510 − 269,130 = 1,329,380, where 269,130 is the size of the quarantined file.

### 3.5 Git Bash on this machine

| Item | Seen |
|---|---|
| `basename` and `dirname` | Correct for the `C:\...`, `C:/...` and `/c/...` forms, and with a trailing backslash |
| `cygpath -m` | Gives `C:/...` for all three forms. For `../hft-crypto-data` it gives an absolute path measured from the shell's working folder at that moment (FS-03) |
| `sha256sum` | Prints `*` before the path. Section 3.3 covers it |
| `du -sb` | Exact on a path with a space: the raw zone read 1,601,848, equal to `raw_bytes`. On a missing folder it prints an error with the path and reads empty |
| `df -B1 --output=avail` | Works on the drive that holds the Documents folder, and prints a bare integer under `tail -1`. That folder and the system temp folder are on the same drive |
| `mktemp -d` | Honours `TMPDIR`. The runner's step 1 already checks this |

### 3.6 The stop table against the code

| Row | Code | Plan text |
|---|---|---|
| 403, 429 and 451 | `fetch.py:154-157` stops at once. `ingest.py:587-591` fails the task and raises. `run_ingest` records `failed` and `stop_reason` | Correct, apart from **"neither the span check nor bar building runs"**. The span and the final sweep do not run. But `_run_tasks` (`ingest.py:973-976`) has already built bars for the first day of every candle month done so far. In the real run that is up to 96 symbol-days in eight datasets. The probe showed 4 (FS-06) |
| 404 on a listed zip | `ingest.py:570-582` sets `overdue`, and `_finish_status` (`ingest.py:846-858`) ignores it | Correct |
| 404 on a sidecar | `ingest.py:401-406`: the checksum source is `none` | Correct |
| Checksum mismatch | `ingest.py:407-422` quarantines the file. `583-586` fails the task | Correct |
| F1, F2, F4 or K1 on one file | `ingest.py:540-548` | Correct |
| A span stop | `ingest.py:987`, `993-1029` | **"before any bars are built" is wrong.** It comes after the loop, which has already built bars (FS-06). Step 7 of section 4 says the same and needs the same fix |
| Missing rows | Several. A timeout, a refused connection, a size limit, or a 5xx after 3 attempts (`fetch.py:163`). A redirect off the route, through `ForbiddenHostError` and `_contain_task_failure`. A parse failure (`ingest.py:603-611`). A failed bar day (`_fail_derive`). Each of these ends `partial` with exit 0. A resume before `next_retry_at` ends **`ok`** (FS-07) | Not in the table |

### 3.7 Does `ingest` compute F1 to F5, K1 to K5 and the span? Yes. Where does it land?

**Each file.** `_check_after_fetch` (`ingest.py:521-549`) runs `file_facts` after the checksum and before the parse. It runs only on binance month files of the first span that were not reused. Its result is saved in that raw file's `check_detail.venue_checks`. That covers:

- F1, F2 and F4's duplicate count, which stop the run;
- F3 and F5's inputs;
- K1's count, which stops the run;
- K2 to K4's counts, with the tick table from `<cfg>/engine.toml`;
- K5's rows, missing and duplicates.

**The span.** `_venue_span` (`ingest.py:993-1029`) runs once the task loop has finished. It computes `funding_span` (F1 to F5) and `candle_span` (K1, K5, then K2 or K4, then K3) over every raw record, including quarantined ones. It saves the result in two places:

- `meta.venue_checks`, overwritten on every run that reaches it;
- `summary.venue_checks`, kept with that run's row.

**What appears for each symbol.** BTCUSDT gets K2 and K3, because its table has a coarser tick. ETHUSDT gets K4, and no K3.

**Where `venue_checks.json` comes from.** `ingest` does not write it. The script writes it from `meta` (lines 299-306). After a run that stops before the span, `meta` still holds the previous run's flags. So in `resume` mode, the flag file can describe an earlier run (FS-01).

## 4. The leak auditor's notes and conditions, against the code

**Note 1: a resume run that exits early shows the previous row. Confirmed.** I reproduced it (section 3.1). The same happens to `venue_checks.json`, which comes from `meta`. FS-01 fixes both.

**Note 2: `_fail_derive` writes task rows keyed by day for monthly datasets. Confirmed** (FS-05).

The probe made one candle day fail with an `OSError` inside `derive_day`.

| | Status | planned | done | bars_built | bars_failed | Requests | Tasks not done |
|---|---|---|---|---|---|---|---|
| Run 1 | `partial` | 1 | 1 | 30 | 1 | 2 | `archive:binance.klines:BTCUSDT:2023-12-05`, `archive:binance.aggTrades:BTCUSDT:2023-12-05` and `derive:binance:BTCUSDT:2023-12-05`, all `failed` |
| Run 2, two hours later | `ok` | 0 | 0 | 1 | 0 | **0** | **The same two `archive:` rows, still `failed`** |

**What this means:**

- The month is never fetched again. The bar day is rebuilt from the same curated month.
- The stray rows include `binance.aggTrades`, a dataset this run never selected.
- They stay `failed` for good, so the `tasks:` and `open_task:` lines can never come back clean.

**Condition a: re-run `cmp` and print the hashes again after `ingest`. Correct, and it can be done as worded.**

- Nothing in `ingest` writes to `<cfg>`: `_market_ticks`, `load_pipeline_config` and `load_retention_policy` only read.
- `cmp` covers `engine.toml` and `retention.toml`. For `pipeline.toml`, the script should also compare its new hash with the one printed on line 205, because `cmp` against the clone's copy differs by design.

**Condition b: exactly one `(config_hash, code_version)` pair across the root's `ingest` rows, equal to step 2's. Correct and needed.**

- In 2 of my 8 probe runs, which ran at the same time, the `ingest` process recorded `0.1.0+unknown` in its run row and in all 1,254 and 1,494 manifest rows. Step 2 had printed `0.1.0+d6da50c87628`.
- After a resume, the root held two different pairs.
- Extend the condition to the manifest (`files.code_version`) and refuse `+unknown`, as in FS-02.

**Condition c: D-43's counts. Consistent with the code.**

- The BTCUSDT field is `K2.months_at_0_01`. Its table is 0.01 from 2020-01-01 and 0.1 from 2022-02-15 03:30, so the months with any minute at 0.01 run from 2020-01 to 2022-02. That is 26.
- The ETHUSDT field is `K4.months_at_0_01`: 48, from its single 0.01 tick.
- `K1.minutes` is 0 on each.
- `test_rc2_02_k1_and_k2_pass_only_when_every_month_was_checked` asserts the 26.
- Word it per check: "BTCUSDT `K2.months_at_0_01` 26, ETHUSDT `K4.months_at_0_01` 48".

**Condition d: a yes/no check on `venue_checks.json`. It can be done, and I tested it.** Two details matter:

- **ISO times can carry fractions.** F2's `rows` hold the raw `calc_time`, which can be `2020-01-01T00:00:00.003000Z`. The pattern must be `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?Z`.
- **Allowed values are bools, `null`, ints, lists and dicts.** Python's `bool` is a subclass of `int`, so test `float` explicitly.

The code produces no float: `max_offset_ms` is an `int`. The allowed keys are:

- the symbols `BTCUSDT` and `ETHUSDT`;
- the checks `F1` to `F5`, `K1` to `K5` and `K2_K4`;
- the fields `pass`, `files_with_another_header`, `months_checked`, `rows`, `max_offset_ms`, `expected`, `missing`, `duplicates`, `files`, `outside_span`, `other_gaps`, `at`, `minutes`, `months_at_0_01`, `months_showing_0_01`, `reported_not_failed`, `first`, `last` and `note`.

The note `no tick table was given, so the ticks were not tested` appears only when no tick table was given. With this script's folder, it should never appear, so a stricter check can refuse it.

The tested check read `yes` on the clean flag file. It read `no` for each of these:

- a float;
- a price text in K3's `first`;
- an unknown key.

**Condition e: after a resume, read §11.3 from the catalog lines. Right, but not enough as worded:**

- **Quarantine.** `quarantined:` counts `catalog/quarantine.jsonl`, which only grows. After the resume the plan allows for a checksum mismatch, "nothing is quarantined" can never hold. The rule should be: every quarantine record is one already reported, and its task now reads `done`.
- **Stray rows.** After any failed bar day, FS-05's rows keep `tasks: binance.klines failed` and `binance.aggTrades failed` showing.
- **The last run's own lines.** `skipped_retry_wait` must be 0, and `run_status ok` says nothing about tasks the run skipped (section 3.4). `planned`, `done` and `downloaded_bytes` describe the last run only.

## 5. Findings

| ID | Location | Failure scenario | Severity | Fix |
|---|---|---|---|---|
| FS-01 | Script lines 227, 239, 244-252, 299-303 | In `resume` mode, an `ingest` that exits before `start_run` still gets a report. Causes include a `uv` error, an argparse error and a `ConfigError`. The report then prints the previous run's row. I saw `ingest_exit: 2` next to `run_status: ok stop_reason: none`, `planned: 12` and `done: 12`. A resume that stops before the span leaves `meta.venue_checks` from the earlier run, and line 305 writes that into `venue_checks.json` | MEDIUM. Condition 1 | Select by this invocation's start time, and take the flags from that row. The exact text is below. **Tested:** on the clean root, a start time before the run found 1 row and one after it found 0. `started_at` is ISO with microseconds. The comparison holds within the same second too, because `"…:46"` sorts before `"…:46.123456Z"` |
| FS-02 | Report. `versioning.py:41-43` | `code_version()` turns any `git` failure, a timeout included, into `0.1.0+unknown`. That value has no `-dirty`, so line 223's check passes it. Two probe runs recorded it in the run row and in every manifest row, while step 2 printed the commit. The script printed both lines, exited 0 and flagged nothing | MEDIUM. Condition 2 | A `versions_match:` line. The exact text is below. **Tested:** `yes` on the clean root, and `no` on the root resumed after an `unknown` run. For `developer` before stage two: `code_version` should fail rather than return `unknown` |
| FS-03 | Script lines 156-162, 207-208 | With `ROOT=../hft-crypto-data`, the guards on lines 159 to 162 test a path relative to where the script started. After `cd "$out/repo"`, `cygpath -m` and the later lines resolve it to `<run folder>/hft-crypto-data`. That folder is in no work tree, so `init` accepts it. **Shown:** the root was made inside the run folder, and nothing beside the start folder | LOW-MEDIUM. Condition 3 | Two `case` lines after line 158. The exact text is below. **Tested** in a script file: `C:\...`, `C:/...` and `/c/...` are accepted. `../x`, `x`, `C:x` and any path with a space are refused. An unquoted `\\` in that pattern did not match under this Git Bash |
| FS-04 | Plan §11.3, §7 "What a rerun is" | After a resume, `planned` and `done` count only that run's tasks, so "192" can never hold. A resume before `next_retry_at` ends `ok` with the task still failed. `quarantined:` counts a log that only grows. `downloaded_bytes` covers one run | MEDIUM, text. Condition 4 | §11.3: for a resume, judge by these. `tasks: binance.klines done 96` and `tasks: binance.fundingRate done 96`. `tasks: derived.bars.binance done 2922`. No `open_task:` line, apart from FS-05's rows if they were reported before. `skipped_retry_wait: 0`. Each quarantine record already reported, with its task now `done`. `run_rows_this_invocation: 1` and `versions_match: yes` (FS-01, FS-02) |
| FS-05 | `ingest.py:680-692` (`_fail_derive`) | A failed candle day sets `archive:binance.klines:<sym>:<YYYY-MM-DD>` and `archive:binance.aggTrades:...` to `failed`. Both rows are keyed by day. `plan_tasks` looks up `<YYYY-MM>`, so the month is never fetched again and the rows never clear (section 4, note 2) | LOW for this run, because `bars_failed > 0` is already a stop. For `developer` | Use the partition key of the spec's own task, `month_key(day)` for monthly specs. Touch only datasets that have a task row for that partition. Until then, the stop table states that a failed bar day cannot be cleared by a resume |
| FS-06 | Plan §4 step 7, §7 rows "403" and "span" | Bars are built inside the task loop: the first day of each candle month, `ingest.py:973-976`. That happens before a host refusal and before a span stop. Probes: 4, 2 and 6 symbol-days. The real run: up to 96 symbol-days in 8 datasets | LOW, text. Part of condition 4 | Replace "before any bars are built" with "before the final bar sweep. The first day of each candle month already fetched has bars". Change "neither the span check nor bar building runs" to match |
| FS-07 | Plan §7 | Rows are missing for: a timeout, connection, size limit or 5xx after 3 attempts; a redirect off the route; a parse failure; a failed bar day; and a resume before `next_retry_at`. All but the last end `partial` with exit 0. The last ends `ok` | LOW, text. Part of condition 4 | Add them. Each is a stop under `failed > 0`, `bars_failed > 0` or `skipped_retry_wait > 0` |
| FS-08 | Plan §10, row "`uv`'s own lines" | `uv sync` prints `Building hft-crypto @ file:///<run folder>/repo`. That path holds the user name | LOW | Make the row "local log only, as `run_folder:`", or pass `--quiet` to `uv sync` |
| FS-09 | Script line 169 | Every check in the heredocs is an `assert`. `PYTHONOPTIMIZE`, if set, removes all of them. `PYTHONPATH` could shadow a module | LOW, hardening | Line 169: add `PYTHONOPTIMIZE PYTHONPATH PYTHONHOME PYTHONSTARTUP` to the `unset` list |
| FS-10 | `ingest.py:105`, `327-330` | `publishable_reason` cuts a path at its first space. `'C:/Users/Jane Doe/...'` became `'<path> Doe/Documents/hft-crypto-data/raw/x.zip'`. An `OSError` during a rename would then put the rest of the path on an `error:` line | LOW. Not reachable once FS-03's guard is in, because the root and the temp folder have no space here | For `developer`: match a quoted path up to its closing quote |
| FS-11 | Script lines 238-310 under `set -e` | If a file the catalog lists as present vanishes before the report reads it (an antivirus quarantine, for example), `read_bytes` raises. The script then ends with the report's exit 1 before the digests, and the traceback prints the root's path to the local log | LOW | Count the missing files instead of reading them: `raw_missing_on_disk: <n>`. Or accept this as written |

**The exact text for conditions 1 to 3.** I tested each fragment on this machine (sections 3 and 6).

Condition 3, after line 158:

```bash
case "$ROOT" in /*|[A-Za-z]:/*|[A-Za-z]:"\\"*) ;; *) echo "refused: the market root must be an absolute path"; exit 1 ;; esac
case "$ROOT" in *" "*) echo "refused: the market root path holds a space"; exit 1 ;; esac
```

Condition 1, line 227, becomes:

```bash
started="$(date -u +%FT%T)"
echo "ingest_started: ${started}Z"
```

Line 239 becomes:

```bash
uv run --frozen --no-dev python - "$ROOT_M" "$(cygpath -m "$out")" "$started" "$CFG_M" <<'EOF'
```

Lines 244 to 252 of the report become:

```python
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
```

Lines 253 to 265 stay as they are, under that `else:`. Condition 2 comes next, at the outer level:

```python
from hft_crypto.config import load_pipeline_config
from hft_crypto.versioning import code_version
expected = (code_version(), load_pipeline_config(sys.argv[4]).config_hash)
pairs = db.execute("SELECT DISTINCT code_version, config_hash FROM runs WHERE kind = 'ingest'").fetchall()
versions = sorted(v for (v,) in db.execute("SELECT DISTINCT code_version FROM files"))
print("versions_match:", "yes" if pairs == [expected] and versions == [expected[0]]
      and "+unknown" not in expected[0] and not expected[0].endswith("-dirty") else "no")
```

**The rest of condition 1, for the flag file:**

- Line 299 becomes `value = summary.get("venue_checks") or None`.
- Line 300, `if value is None:`, stays as it is.
- Line 303 becomes `document = value`.

**Two consequences:**

- After a run that stopped before the span, the flag file is no longer written. That is intended.
- When the span ran, `meta` and the run's summary hold the same document. `test_stage_one_records_each_file_s_result_in_the_manifest_and_adds_up_the_span` asserts that they are equal.

**R-1, a recommendation.** Five of the plan's stops leave `ingest_exit: 0`:

- an overdue month;
- a missing sidecar;
- a checksum mismatch;
- a failed fetch;
- a resume skipped by its retry time.

§11.3 now has more than twenty items to read by eye. A last report line, `fetch_of_record: yes|no <names of the items that fail>`, computed from the same queries, would remove reading errors. So would ending with exit 3 on `no`.

## 6. Commands run, and what they printed

Paths are replaced by placeholders.

**Setup and static checks**, in a clone at `d6da50c`, synced with `--offline`:

```text
$ git diff --stat 0b853bd d6da50c -- src configs pyproject.toml uv.lock     -> (empty)
$ git diff --stat 8ba8c83 d6da50c -- src configs tests pyproject.toml uv.lock -> (empty)
$ <extract the section 5 block> | sha256sum      -> d58f3dcd3d15727c51aed3d3314888b308ef980f9a30d85a84a1f591cc249ac2   (0 CR, 194 lines)
$ bash -n <script>                                -> syntax ok
$ ruff check --no-cache .                         -> All checks passed!
$ ruff format --no-cache --check .                -> 177 files already formatted
$ mypy                                            -> Success: no issues found in 119 source files
$ pytest -q -p no:cacheprovider -m "not network"  -> 2032 passed, 2 skipped in 2669.94s
     SKIPPED tests\data\test_foundation.py:164 and tests\test_workflows.py:591: creating file symlinks needs a privilege on this machine
```

The suite ran alongside my probe runs, which is why it took 44 minutes.

**Help:**

```text
$ hft-crypto --help          -> usage: hft-crypto [-h] [--data-root DATA_ROOT] [--config-dir CONFIG_DIR] [--now NOW] {init,ingest,...}
$ hft-crypto init --help     -> usage: hft-crypto init [-h]
$ hft-crypto ingest --help   -> usage: hft-crypto ingest [-h] [--datasets DATASETS] [--light] [--symbols SYMBOLS] [--start START] [--end END] [--time-budget TIME_BUDGET] [--delete-raw-after-curated] [--include-book] [--scheduled-cron SCHEDULED_CRON] [--job-started-at JOB_STARTED_AT] [--event EVENT]
```

The `--config-dir` help says "pipeline.toml and retention.toml", but `_market_ticks` also reads `engine.toml` from there. It is text only.

**The probe script, clean scenario.** These are the lines printed before step 4:

```text
commit d6da50c8762872a7b4fe80320cf54d903c0145cf: clean clone
override: one line differs, enabled = true under [sources.binance]. engine.toml and retention.toml are copies
override_sha256: pipeline=221678dc9711ebffe671e7b2362978d841218c293e406433182622a427e87988 engine=acf5b4dd51500429e6de33236824a9c39d5f46f955d4079c7c385ed2af7e38e4 retention=e1458642f3907a6e8166f33abbac62df10481db93dd0105bfd15bbd672e897c7
code_version: 0.1.0+d6da50c87628
source_state: repository 'no approved source configured' run 'binance'
enabled_hosts: data.binance.vision
last_opened_date: 2023-12-31
config_hash: repository 8fd2f5cd8166bc53eeb65afe45188fb3fbf1873cd750a84045137d08e4afe627 run 4e3e6a65484efb759868a2a0e4a78c3f6283f54a2015a7e2f81a1008bf97a6e9
DATA_ROOT zones and catalog are ready.
```

The override hashes are those of CRLF files under this machine's `core.autocrlf=true`. The real run will print the same values if it runs from the same commit's configuration.

The report lines are summarised in section 3.4. Some samples:

```text
ingest_exit: 0 / run_status: ok stop_reason: none / planned: 12 / done: 12 / bars_built: 184 / downloaded_bytes: 1601848
raw_checksum_source: {'sidecar': 12} / raw_with_venue_checks: 12 of 12 / raw_bytes: {'klines': 1598510, 'fundingRate': 3338}
venue_check: BTCUSDT F4 {"duplicates": 0, "expected": 4383, "files": 3, "missing": 4107, "months_checked": 3, "outside_span": [], "pass": null}
venue_check: BTCUSDT K3 {"first": "2023-10-01T00:00:00Z", "last": "2023-12-31T23:59:00Z", "minutes": 18928, "reported_not_failed": true}
venue_check: ETHUSDT K4 {"months_at_0_01": 3, "months_checked": 3, "months_showing_0_01": 3, "pass": null}
venue_check: ETHUSDT K5 {"duplicates": 0, "expected": 2103840, "missing": 1971360, "rows": 132480}
files_digest: e7d06cb8...3c0a / files_digest_python: e7d06cb8...3c0a / stand-in's served digest: e7d06cb8...3c0a
zone_bytes: raw/archive 1601848 / files_in_root: 1500 / free_bytes: <an integer>
```

**Exit codes, the stale row and the versions:**

```text
mode=refusal uv_rc=1   ... HostRefusalStop: http_403: archive:binance.klines:BTCUSDT:2023-12
mode=venue   uv_rc=2   error: F1_HEADER: archive:binance.fundingRate:BTCUSDT:2020-01
resume, step 4 exits 2 before its row:  ingest_exit: 2 / run_status: ok stop_reason: none / planned: 12 / done: 12
zip404 root: files code_version [('0.1.0+unknown', 1254)], runs [('0.1.0+unknown', '4e3e6a65...')]; step 2 printed 0.1.0+d6da50c87628
proposed lines: clean root -> run_rows_this_invocation: 1, versions_match: yes, venue_checks_json_clean: yes
                stale case -> run_rows_this_invocation: 0
                timeout root after resume -> versions_match: no (2 pairs, manifest '0.1.0+unknown')
```

## 7. Not checked

- **The fetch itself, and any host.** I did not test any of these:
  - real file sizes and times;
  - a real 403, 429 or 451;
  - whether the archive still serves the bytes `D-45` counted.
- **The 96-month run.** The probes cover 3 months. That means none of these was checked:
  - a span flag reading `true` with `months_checked` 48;
  - `candle_zip_names_ok: True`;
  - D-43's 26 and 48, beyond the arithmetic in section 4 and the test that asserts 26;
  - the time to build 2,922 days of bars.

  As a rough guide only, while other jobs ran on this machine, 184 symbol-days took about 80 s in the stand-in.
- **What triggered the `+unknown`.** It happened under load, with 8 probe runs at once. It is consistent with `code_version`'s 10 s and 30 s subprocess timeouts, but I did not isolate it.
- **Whether the Documents folder is synced.** That is the owner's item in §8.
- **`taskkill /F /T` during this script.** Section 6 of the coverage script review tested that procedure on the same machine, and I did not repeat it.
- **P-1** (section 8).

## 8. P-1

**Pending.** `developer` is writing the 2 s pause between requests. I have not been sent a diff. When it arrives, I will review it here, in a section of its own. It needs a test on a fake clock covering every request `ingest` makes, the sidecar included.

When I finished, the main working tree held uncommitted changes to `src/hft_crypto/cli.py` and `src/hft_crypto/data/fetch.py`, and a new `tests/data/test_request_pace.py`. They are not mine, and I did not review them. Every probe and test above ran in clones at `d6da50c`, so those changes did not affect any result here.

## 9. Left running, and left on disk

- **Processes.** None. A final search for `uv.exe`, `python.exe`, `hft-crypto.exe`, `pytest.exe`, `bash.exe` or `git.exe` naming my folder found 0.
- **Folders.** I removed my one temp folder, with its clones, probe roots, run folders and probe scripts. No `tmp.*` folder is left directly in the system temp folder.
- **The repository.** This file is my only change, and it is not committed.
