# First-span fetch: run plan for review

Date: 2026-11-06. Owner: `data-steward`. For section 7 item 17 of `docs/decisions/FOLD_PLAN_2026-11-05.md`, and for part 4 of its
section 11. Code read at `d5c4147`. Its `src/`, `configs/`, `tests/`, `pyproject.toml` and `uv.lock` are those of `0b853bd`, the
coverage check's base.

**Status: for review by `leak-auditor` and `python-reviewer`, and for decisions by `project-manager` and the owner. Nothing here has
run.** No host was contacted to write this, no file was fetched, and no configuration file was changed. The script in section 5 is
text for review. It names no commit yet.

Sizes and counts quoted here come from `docs/reviews/data/binance_vision_coverage_2026-11-05.md` (called "the coverage record") and
from `D-45`. They are derived from Binance Vision data, CC BY-NC-SA 4.0. Not associated with or endorsed by Binance.

## Answers

| Question | Answer |
|---|---|
| The commands | `init`, then one `ingest`. That one command fetches, checks each checksum, runs F1 to F5 and K1 to K5 on each file, curates, computes the span flags, and builds the bars. No separate command exists for the venue checks or for bars (section 4) |
| The switch | **A configuration folder made for each run and passed by the explicit `--config-dir` flag.** Not a run commit, and not `HFT_CONFIG_DIR`. The engine run needs the switch too. `--declare-costs` does not (section 3). `project-manager` decides |
| The market root | `hft-crypto-data`, directly in the owner's Documents folder, new and empty. It fits the zone layout in section 3 of `docs/08_DATA_CENTER.md`. It is a local exception to that document's section 5, which `D-37` foresees, and `project-manager` should record it (section 8) |
| Its class | By zone: raw files are `RE-DOWNLOADABLE`, and curated data and bars are `DERIVED`. The whole root is kept through stage one, and no deletion rule applies to it. From `--declare-costs` on, the root's trial registry is our own record and is treated as `IRREPLACEABLE` (section 8) |
| `files_digest` | The coverage script's own line, run inside the market root's candle folder, plus a Python cross-check. It must equal `2706d31edc73002aaa70845fe6e4e7fc421d581a3be3f0f54fa3e9ac3483c0ca` (section 6) |
| Stops | The code ends the run on a 403, 429 or 451, and on a `false` from F1, F2, F4 or K1. It does not end the run on a 404, a missing sidecar or a checksum mismatch, so the script reads those from the catalog and this plan treats them as stops (section 7) |
| Size and time | 179.2 MB of raw zips, measured for candles. About 0.8 GB with curated data, bars and catalog, `UNVERIFIED`. The fetch takes about 5 minutes without pauses, or about 18 with the record's 2 s pause. Bars are not measured (section 9) |
| What the runner reads | The script's printed lines and one flag file, `venue_checks.json`. These hold counts, hashes, fixed words, times and flags, and no price, volume or rate (section 10) |
| Reviewers | `leak-auditor` for the read boundary, the switch and the root. `python-reviewer` for the script, its commands and flags, and the stop table. `developer` for P-1 (section 12) |
| **Blocking** | **P-1: `ingest` does not pause between requests.** The coverage record's section 4.2 sets a 2 s pause (section 2) |

## 1. What runs, and what it decides

| Item | Value |
|---|---|
| Files | 96 monthly 1-minute candle zips and 96 monthly funding zips, 2020-01 to 2023-12, BTCUSDT and ETHUSDT, each with its sidecar. 192 zips and 384 requests. This is the frozen list in section 4.1 of the coverage record |
| Route | `https://data.binance.vision/data/futures/um/monthly/klines/...` and `.../monthly/fundingRate/...`. The client can open no other host or path: `APPROVED_ROUTES` in `config.py` and `check_url` in `data/fetch.py` |
| Where | The market root (section 8) |
| Code | `hft-crypto ingest`, from a clean clone at the approved commit |
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
| P-1 | **It does not pause between requests.** `_fetch_raw` calls `download` and then fetches the sidecar with `get_bytes`, file after file. `HttpFetcher` sleeps only between attempts at a single request. The coverage check waits 2 s after each request (`MIN_REQUEST_GAP_S`), as section 4.2 of the coverage record says | `data/ingest.py` `_fetch_raw`. `data/fetch.py` `_attempt`. `data/coverage.py` | The 384 requests go back to back | **Blocking. Either:** `developer` gives every request `ingest` makes the same 2 s minimum gap, with a test on a fake clock, reviewed by `python-reviewer` and `leak-auditor`, because plan section 7 sends data code back to `leak-auditor`. **Or:** `project-manager` records in writing that stage one runs without the pause, and why. The coverage record found no rate limit posted in the terms, so the 2 s is our own pace and not a term. I recommend the gap. Splitting the run into many small `ingest` calls does not replace it, because a zip and its sidecar would still go back to back |
| P-2 | A 404 on a sidecar lets its zip through unchecked. `checksum_source` reads `none`, the task is `done`, and catch-up never fetches that file again | `_fetch_raw` | An unverified file could enter the root without anyone noticing | The script counts raw files by `checksum_source`, and all 192 must read `sidecar`. Any other value is a stop (section 7). A code change that fails the task instead is worth making before stage two. It is not needed now |
| P-3 | A 404 on a listed zip marks the task `overdue`, and the run goes on. `_finish_status` ignores `overdue`, so the run ends `ok`. The month's span flag is `null`, which stops nothing | `run_archive_task`, `_finish_status`, `span_flag` | The status hides a missing month | The script prints `overdue` and every open task. `overdue` above 0 is a stop (section 7). Counting it as `partial` is a later fix |
| P-4 | A checksum mismatch quarantines the download, marks the task `failed` with a retry 30 minutes later, and the run goes on. The status is `partial` | `_fetch_raw`, `run_archive_task` | The coverage check stopped at once here. `ingest` does not | Accepted, because no file is used until the checks after the run pass. `failed` above 0 means this is not the fetch of record (section 7) |
| P-5 | A host refusal ends `ingest` with a traceback and exit 1, because `main` does not catch `HostRefusalStop`. No summary is printed. A refusal on a sidecar also leaves one temporary file, which the next `ingest` sweeps away | `cli.py` `main` and `_cmd_ingest`. `_fetch_raw` | The summary must be read from the catalog | On every exit, the script reads the run row's `stop_reason` from the catalog. It is a fixed word |
| P-6 | The summary's `errors` and the catalog's `last_error` hold raw exception text. Parser messages can quote a row: `unexpected header`, `unreadable CSV`, `bad value in file` | `run_archive_task`, `_contain_task_failure`. `data/parsers.py` | A price could reach a printed line | Neither is printed. The script prints each error's task key, and the rest only after `publishable_reason`, which removes every number and every path |
| P-7 | The manifest holds each file's URL, size, SHA-256, time, code version and licence note. It does not hold `Last-Modified` or the listing's size, which section 4.2 of the coverage record asks for | `JobContext.register_output` | Weaker evidence of when a file was republished | Not blocking. The SHA-256 pins the bytes, and `file_history` records any later change. For `developer` before stage two |

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
| **A.** A local run commit, never merged, as for the coverage check | A branch from the approved commit with one line changed, run from a clean clone at that branch | Already used once (`D-44`, `D-45`). The switch stays in git history, with its diff | `code_version` names the run commit, not the reviewed one. For the fetch, every manifest row would name a commit only this machine holds, so it would have to be tagged and kept. For the engine run after C-5 it is worse: the outputs and every trial row would name a commit that is not the C-5 commit, while item 18 asks for the suite at "the commit that runs". Each later run would need another such commit |
| **B.** A configuration folder for each run, passed by `--config-dir` to `hft-crypto`, or by `--pipeline-config-dir` to the engine | The script copies the clone's three configuration files into a new folder inside its run folder, changes one line, checks the result, and passes the folder by flag. The folder is deleted with the run folder | No commit and no branch. No anchored file changes, before C-5 or after it. The tree stays clean, so `code_version` names the reviewed commit, and later the C-5 commit itself. Each command line shows which configuration it used. The engine run can use the same method | The switch is outside git, so the script's checks and printed hashes are its only proof. There are three ways to get it wrong, and each is closed. Without `engine.toml` in the folder, `_market_ticks` returns `None` without an error, and K2 to K4 go untested, so the script copies the file and compares bytes. Without `pipeline.toml`, `find_config_dir` falls back to the repository's own file, where the source is disabled, so the run refuses (fails closed). Without `retention.toml`, loading fails (fails closed) |
| **B'.** The same folder, named by `HFT_CONFIG_DIR` | `find_config_dir` supports it | Nothing over B | The variable outlives the command. It reaches every process the shell starts, the test suite included, and it does not appear on the command line. Not proposed. The script unsets it |
| **C.** `enabled = true` committed in git, before C-5 or as part of it | Nothing here | Nothing here | On `main`, the daily schedule would run `ingest --light` and then `report --published`. That would publish first-span figures that must stay private (plan section 5), and save market data to the cache while `D-37` is open. A change before C-5 also adds a row to the published diff audit. Not proposed |

**B is the safer option.** The script runs five checks on it:

1. In `pipeline.toml`, exactly one line differs: `enabled = false` becomes `enabled = true` under `[sources.binance]`.
2. Parsed with `tomllib`, the two files are equal once that key is set, as in the coverage script.
3. `engine.toml` and `retention.toml` are byte copies.
4. Through the project's own loader, the repository's copy reports `no approved source configured`. The run's copy reports `binance`. `data.binance.vision` is the only host it can open, and the last opened date is 2023-12-31.
5. It prints the three SHA-256 values and both `config_hash` values.

**What the folder cannot do.** It cannot open a host or path outside `APPROVED_ROUTES`, and it cannot move the ceiling, because both are
in code. The worst a wrong folder can do is fetch first-span files over the approved route, or be refused.

**Where it is recorded.** The catalog's `runs` table holds the `config_hash` of the changed file. The decision log entry records both
hashes and the one line that differs.

**For the engine run.** The same method applies, starting from the C-5 commit's own `pipeline.toml` and passed by
`--pipeline-config-dir`. The engine takes the candle allowance, the allowance `A` and the equity timeframe from that file. Check 2
makes those values equal to the anchored file's. That run needs its own approval, and this plan does not give it.

**`project-manager` decides.** If A is chosen, the script changes and goes back to review. The coverage script's check on the run
commit's diff replaces the folder steps and the loader check, and `--config-dir` is dropped.

## 4. The commands, in order, and what each prints

All of them run from a clean clone at the approved commit, through `uv run --frozen --no-dev`. In the table, `<root>` is the market
root and `<cfg>` is the run's configuration folder, both in the Windows form `cygpath -m` gives.

| # | Command | Prints | Exit |
|---|---|---|---|
| 1 | `git clone --no-local`, `git checkout --detach <commit>`, then `uv sync --frozen --no-dev --python 3.12` | `uv`'s own lines: package names and versions | 0 |
| 2 | Build the folder of section 3, then load it | `override:`, `override_sha256:`, `code_version:`, `source_state:`, `enabled_hosts:`, `last_opened_date:`, `config_hash:` | 0, or the script stops |
| 3 | `hft-crypto --data-root <root> --config-dir <cfg> init` | `DATA_ROOT zones and catalog are ready.` | 0. If the root is inside a git work tree: exit 2 and `error: DATA_ROOT must be outside the repository, ...` |
| 4 | `hft-crypto --data-root <root> --config-dir <cfg> ingest --datasets binance.klines,binance.fundingRate --symbols BTCUSDT,ETHUSDT --start 2020-01-01 --end 2023-12-31 --event manual` | On exit 0: one line of canonical JSON, the `IngestSummary`, written to a file that is never printed. On a venue check stop: `error: <codes>: <task key or symbols>` on stderr. On a host refusal: a traceback ending `HostRefusalStop: <http_403, http_429 or http_451>: <task key>` | 0, 2 or 1 |
| 5 | The report after the run: a read-only query of the catalog | Section 10 | 0 |
| 6 | `files_digest` and `funding_digest` (section 6) | Section 10 | 0 |
| 7 | Sizes and free space | Section 10 | 0 |

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
2. It plans 192 tasks, newest month first, with candles before funding in each month.
3. For each task, it downloads the zip under a temporary name and reads the sidecar into memory. It compares the SHA-256 values, then renames the zip into `raw/archive/binance/<kind>/<symbol>/date=YYYY-MM-01/`. The sidecar is not kept on disk.
4. Before parsing a file, it runs the per-file checks. Funding files get F1, F2 and F4's duplicate count. Candle files get the K1 to K4 counts, using the tick table from `<cfg>/engine.toml`. A stop quarantines the file, fails the task and ends the run.
5. It parses each file into one monthly part under `curated/candles_official/` or `curated/funding/`, registered with its raw parent.
6. After each candle month, it reopens that month's days for bar building.
7. After the loop, it computes the span flags over all 48 months for each symbol (`_venue_span`), and saves them in the catalog's `meta` table under `venue_checks`. A `false` from F1, F2, F4 or K1 ends the run here, before any bars are built.
8. It builds bars for every stored day: `bars_1m_official` and seven higher timeframes, for 2,922 symbol-days.
9. It writes `catalog/last_ingest.json` and a heartbeat, then prints the summary.

**Not run under this plan:** `report`, `reconcile-live`, `poll`, `health`, `retention`, `candle-check`, `coverage-check` and the engine.

## 5. The script

For review only. It runs under Git Bash, with the conventions of section 11 of the coverage check plan. Its hash is pinned once
`RUN_SHA` is filled in at approval. It deletes nothing.

```bash
#!/usr/bin/env bash
# First-span fetch, stage one (fold plan section 7 item 17), under Git Bash. Text reviewed in section 5 of
# docs/reviews/data/first_span_fetch_plan_2026-11-06.md. Prints counts, hashes, fixed words, times and flags only.
# Usage: bash run_first_span_fetch.sh <path of this repository> <the market root> <first|resume>
set -euo pipefail
RUN_SHA="<the approved commit, 40 hex>"               # filled in at approval, then the file's hash is pinned
SOURCE_REPO="$1"                                      # passed in, so no local path is written into this text
ROOT="$2"                                             # the market root, passed in for the same reason
MODE="$3"
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
unset GITHUB_SHA DATA_ROOT HFT_CONFIG_DIR CHECK_ROOT DATA_QUOTA_GB
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
echo "override_sha256: pipeline=$(sha256sum < "$cfg/pipeline.toml" | cut -d' ' -f1)" \
  "engine=$(sha256sum < "$cfg/engine.toml" | cut -d' ' -f1) retention=$(sha256sum < "$cfg/retention.toml" | cut -d' ' -f1)"
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
echo "ingest_started: $(date -u +%FT%TZ)"
set +e
uv run --frozen --no-dev hft-crypto --data-root "$ROOT_M" --config-dir "$CFG_M" ingest \
  --datasets binance.klines,binance.fundingRate --symbols BTCUSDT,ETHUSDT \
  --start 2020-01-01 --end 2023-12-31 --event manual \
  > "$out/ingest.json" 2> "$out/ingest.err"          # neither file is printed or opened (section 10)
rc=$?
set -e
echo "ingest_finished: $(date -u +%FT%TZ)"
echo "ingest_exit: $rc"

# The report after the run. The catalog is opened read-only, and only the fields below are printed.
uv run --frozen --no-dev python - "$ROOT_M" "$(cygpath -m "$out")" <<'EOF'
import collections, hashlib, json, pathlib, sqlite3, sys
from hft_crypto.data.ingest import publishable_reason
root, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
db = sqlite3.connect(f"{(root / 'catalog' / 'catalog.sqlite').as_uri()}?mode=ro", uri=True)
row = db.execute(
    "SELECT status, code_version, config_hash, summary FROM runs WHERE kind = 'ingest' "
    "ORDER BY started_at DESC LIMIT 1"
).fetchone()
if row is None:
    print("run_row: none")
else:
    summary = json.loads(row[3] or "{}")
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
print("raw_hash_differs_from_catalog:", sum(hashlib.sha256((root / r[0]).read_bytes()).hexdigest() != r[4] for r in present))
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
value = db.execute("SELECT value FROM meta WHERE key = 'venue_checks'").fetchone()
if value is None:
    print("venue_checks: none")
else:
    document = json.loads(value[0])
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    (out / "venue_checks.json").write_text(text, encoding="utf-8", newline="\n")
    print("venue_checks_sha256:", hashlib.sha256(text.encode("utf-8")).hexdigest())
    for symbol, result in sorted(document.items()):
        for check, body in sorted(result.items()):
            print("venue_check:", symbol, check, json.dumps(body, sort_keys=True))
EOF

# Section 6. The coverage script's digest line, run inside each raw folder of the market root.
for kind in klines fundingRate; do
  dir="$ROOT/raw/archive/binance/$kind"
  name="$([ "$kind" = klines ] && echo files_digest || echo funding_digest)"
  if [ -d "$dir" ]; then
    echo "zips: $kind $(cd "$dir" && find . -type f -name '*.zip' | wc -l)"
    echo "$name: $(cd "$dir" && find . -type f -name '*.zip' -exec sha256sum {} + \
      | awk '{n = split($2, p, "/"); print $1 "  " p[n]}' | sort -k2 | sha256sum | cut -d' ' -f1)"
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
echo "done: $(date -u +%FT%TZ)"
exit "$rc"
```

**Notes for `python-reviewer`.**

- The market root's path is never printed. Only the run folder's path is printed, and it stays in the local log, as in condition 3 of 17.7.
- `set +e` around `ingest` lets the report run after a stop. The script exits with `ingest`'s exit code.
- In `first` mode the root must not exist yet. `init` creates it, and `DataRoot` refuses a root inside a work tree or a check root. In `resume` mode the root must already hold a catalog.
- The catalog is opened through a `file:` URI with `mode=ro`, so the report cannot write to it.
- Zips are hashed as bytes, and nothing unzips them.

**Tried offline,** on copies in a scratch folder outside the repository, with no project code run and no host contacted:

- **The override generator.** On a CRLF copy of `configs/pipeline.toml` it found exactly one hit, at line 55. It kept all 291 CRLF endings and changed only that line. The `diff` count read 2.
- **A second switch.** The `tomllib` comparison catches a second change, `bybit` enabled as well.
- **The digest line.** The digest line run inside the folder, with two dummy zips under a root whose path contains a space, gave the same digest as the Python cross-check. The coverage script's original form, `find "$root/raw"`, gave a different and wrong digest there.

These checks used the system Python, not the clone's 3.12, so `python-reviewer`'s own checks still stand.

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
- A space in the root's path would split awk's `$2` and break the base name.

Neither reason changes a line of what is hashed, because awk keeps only the hash and the base name. Git Bash's `sha256sum` prints `*`
before the path, and awk drops it, as `python-reviewer` found in section 1 of the script review.

**The cross-check.** The script also computes the digest in Python, from the files' own bytes, sorted by name. With these names, that
order is the same as `sort -k2` in any locale: every name has the same pattern and length, and they differ only in letters and digits.
The script also requires:

- 96 names, each once, matching `(BTC|ETH)USDT-1m-YYYY-MM.zip` for 2020-01 to 2023-12.
- `raw_hash_differs_from_catalog` at 0.

**Reading the result.**

| Result | Meaning | Next |
|---|---|---|
| Both digests equal `2706d31e...c0ca` | The same bytes the coverage check counted. `D-45`'s counts describe this root's candles | K5 must also read 2,103,840 rows, 0 missing and 0 duplicates on each symbol. That is the sum of the 16 quarters in the first-span document |
| The two digests differ from each other | A tool fault, not a data fact | Stop. `python-reviewer` finds out why. Nothing is used |
| Both agree, and differ from `D-45` | The archive served different bytes from those of 2026-11-06 | Stop before any use. As `D-45` requires, the 96 files are counted again with the same checker, `_count_candles` and `_Quarter` in `data/coverage.py`. A short script runs them on the market root's files, fetches nothing, and prints only the first-span document's quarter fields. That script needs `python-reviewer` and `leak-auditor` first. Plan section 2 applies only once on candles, so whether a different count changes anything is for `project-manager` and `leak-auditor` |

**Funding has no earlier reference.** The script prints `funding_digest` in the same form, and it becomes the reference for later
checks. From this run on, the catalog holds each of the 192 files' SHA-256 values, so any later difference can be traced to a single
file. The coverage check's output could not do that.

**Again later.** The same command runs again before the first `V0` run, to show the bytes have not changed.

## 7. Stops and reruns

| Event | What the code does | Exit and status | What this plan does |
|---|---|---|---|
| HTTP 403 or 429, on a zip or a sidecar | `fetch.py` does not retry it. `ingest` fails the task, with a retry 30 minutes later, and raises `HostRefusalStop`. The run row records `failed` and `stop_reason` `http_403` or `http_429`. No later file is requested, and neither the span check nor bar building runs | Exit 1, traceback | **Stop.** One `resume` run, on a written note from `project-manager`, after the task's `next_retry_at`. A second refusal goes to the owner |
| HTTP 451 | The same, with `http_451` | Exit 1 | **Stop. To the owner first.** A 451 gives a legal reason, so a note alone is not enough to rerun |
| HTTP 404 on a listed zip | The task is marked `overdue` with an alert, and the run goes on. The month's flags read `null` (P-3) | Exit 0, status `ok` | **A stop when `overdue` is above 0.** Every file was in the listing, and the coverage check found all 96 candle files on 2026-11-06, so a 404 now looks like an outage. One `resume` run on a note. A second 404 on the same file goes to `project-manager` as a coverage fact |
| HTTP 404 on a sidecar | The zip is accepted unchecked, with `checksum_source` `none`, and the task is `done` (P-2) | Exit 0 | **A stop when any raw file does not read `sidecar`.** A `resume` run cannot fix this, because the task is done. `data-steward` and `project-manager` decide. The likely remedy is a new root on a later day |
| SHA-256 does not match the sidecar, or the sidecar cannot be read | The download is quarantined and recorded with a reason from `publishable_reason`. The task fails, with a retry 30 minutes later, and the run goes on (P-4) | Exit 0, status `partial` | **A stop when `failed` is above 0.** One `resume` run on a note, after `next_retry_at`. A second mismatch on the same file goes to `project-manager` |
| F1, F2, F4's duplicates or K1 fail on one file | The file is quarantined with its check results kept, the task fails, and `VenueCheckStop` is raised | Exit 2, `error: <code>: <task key>` | **Stop, with no rerun.** The archive would serve the same bytes and fail the same way. `data-steward`, `project-manager` and `developer` review it. Under `D-43` and RB-02, a check never moves a tick row. A row changes only on a venue document and a new decision. Section 3.1 of the venue facts leaves open whether the 2020 funding files have F1's header |
| F1, F2, F4 or K1 read `false` over the span | `_venue_span` raises before any bars are built. Every later `ingest` fails the same way until that month is fetched again and passes | Exit 2, `error: <codes>: <symbols>` | The same |
| F3, F5, K2 or K4 read `false`, or any flag reads `null` | No stop in code | Exit 0 | **Not the run's stop, but item 17's.** The first `V0` run waits until each one is reviewed. A `null` must be explained month by month |
| A crash, a hard kill or a lost machine | Writes are atomic: a temporary name, then a rename. The next `ingest` sweeps temporary files and redoes what is not `done` | Varies | First, no process of the run may be alive (section 11). Then one `resume` run on a note |
| `files_digest` differs from `D-45` | Nothing in code | Exit 0 | **Stop before any use.** Section 6 |

**What a stop means here.** The run is not the fetch of record. Nothing in the root is used, and `--declare-costs` waits. `data-steward`
writes the stop to the decision log that same day, with the fixed word and the task key.

**What a rerun is.**

- The same script, in mode `resume`, at the same commit, into the same root, from a new run folder, on a written note from `project-manager`.
- Catch-up fetches only tasks that are not `done`: a failed task is fetched again from scratch, and an overdue one is tried again.
- Files already `done` are untouched, and their per-file check results stay.
- A rerun before a failed task's `next_retry_at` skips that task (`skipped_retry_wait`), so the note names a later time.
- There is no retry loop beyond the fetcher's own. No other host, mirror, region, proxy or VPN is used.

## 8. The market root: place, layout and class

**Place.** `hft-crypto-data`, directly in the owner's Documents folder.

| Requirement | Met by |
|---|---|
| Outside every git work tree | `DataRoot` refuses a root that has a `.git` folder in it or above it, both as written and after following links. The runner also confirms this before the run |
| Outside every agent's scratch folder | The owner's Documents folder is not under any agent's data folder |
| Survives the session | It is the owner's own folder, and no session removes it |
| New and empty, and no earlier root (`D-29`) | The script refuses a root that already exists in `first` mode |
| Separate from the sealed demonstration (`D-41`) | It sits beside the folder the owner approved for the sealed files, never inside it. Nothing in this plan lists or opens that folder. Opening it would be a read |
| No copy to a cloud service | **To confirm.** If the Documents folder is synced by OneDrive or another client, licensed data would be copied off the machine, and the catalog database and the atomic renames could clash with the sync. If it is synced, the owner names another folder outside every work tree and agent folder, and this plan says "the market root" either way |
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
| Raw in all | 192 zips | **179,206,025** | `downloaded_bytes` should read this if no file has changed |
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
| **Fetch in all** | **384** | **About 5 minutes without pauses (at most 292 s). About 18 minutes with them (at most 1,060 s)** | The two rows above. P-1 decides which applies |
| Per-file checks and curation | none | Not measured | K1 to K4 look up a tick in Python for each of about 2.1 million minutes per symbol. Each part is written as Parquet and registered |
| Bars for 2,922 symbol-days | none | Not measured | Each day reads a month's candles once and writes eight Parquet files, each with its catalog row |
| **The whole run** | | **Allow 60 minutes, `UNVERIFIED`** | `ingest_started` and `ingest_finished` measure it. The decision log entry records the measured figure, which replaces this estimate |

The run takes longer than an agent's foreground call allows, so it starts in the background with no time limit (RE-02).

## 10. What the runner reads

**Who runs it:** the main session, as for the coverage check. It reads the script's printed lines and nothing else under the run
folder, except `venue_checks.json`.

**The printed lines.**

| Line | Content |
|---|---|
| `run_folder: <path>` | The run folder. **Local log only.** No document, decision log entry, commit or other agent receives it |
| `commit <sha>: clean clone` | The full commit hash |
| `uv`'s own lines | Tool and package names and versions |
| `override: ...` and `override_sha256: pipeline=... engine=... retention=...` | Fixed text and three hashes |
| `code_version:`, `source_state:`, `enabled_hosts:`, `last_opened_date:`, `config_hash:` | Version and 12 hex characters, fixed words, one host, one date, two hashes |
| `DATA_ROOT zones and catalog are ready.` | Fixed text from `init` |
| `ingest_started:`, `ingest_finished:`, `ingest_exit:` | Two UTC times and an integer |
| `run_status:`, `stop_reason:`, `run_code_version:`, `run_config_hash:` | Fixed words, a version and a hash |
| `planned:` to `downloaded_bytes:` | Sixteen integers |
| `error: <task key> <reason>` | The reason only after `publishable_reason`, which removes every number and path (P-6) |
| `alert: <text>` | `ingest`'s own sentences. They hold task keys, root-relative paths and counts only |
| `raw_files:`, `raw_checksum_source:`, `raw_with_venue_checks:`, `raw_bytes:`, `raw_hash_differs_from_catalog:` | Counts by kind, status and fixed word, and bytes |
| `funding_file: <symbol> date=<month> missing [...] outside_month [...] off_grid [...]` | Settlement times, printed only for a file that has any. This gives item 17's list for F4 |
| `tasks:`, `open_task: <key> <state> <time>` | Counts by state, and the keys of tasks that are not done. No error text |
| `curated_files:`, `gaps:`, `exclusions_open:`, `quarantined:` | Counts by kind and status |
| `quarantine: <dataset> <symbol> <partition> <reason> <sha256> <size>` | The fields of the published quarantine record. Its reason has already passed through `publishable_reason` |
| `venue_checks_sha256:` and `venue_check: <symbol> <check> <json>` | Each check's result: pass, counts and `months_checked`. Also F2's rows as a time and an interval in hours, F3's largest offset in ms, F4's expected, missing and duplicate counts with its settlements outside the span, F5's times, K3's first and last minute, and K5's rows, missing and duplicates |
| `zips:`, `files_digest:`, `funding_digest:`, `candle_zip_names_ok:`, `files_digest_python:`, `files_digest_expected:` | Counts, hashes and a yes or no |
| `zone_bytes:`, `files_in_root:`, `free_bytes:`, `done:` | Sizes, a count and a time |

**The flag file.** `venue_checks.json`, in the run folder. It holds the `venue_checks` value from the catalog's `meta` table, indented
and with LF line endings, and its hash is printed. The runner may open it.

- I propose to commit it byte for byte as `docs/reviews/data/venue_checks_first-span_<date>.json`, with a `-text` line in `.gitattributes` as for `D-45`'s documents, and with the attribution in its decision log entry. `project-manager` and `leak-auditor` decide.
- The same values stay in the catalog: in `meta`, and file by file in each raw file's `check_detail`. Those are the manifest's integrity results.

**Never printed or opened:**

- prices, volumes, taker flow, funding rates, trade counts, or any row;
- `ingest.json` and `ingest.err` in the run folder;
- `catalog/last_ingest.json`;
- the catalog's `last_error` column, and any `check_detail` content apart from `checksum_source` and `venue_checks`;
- any file under `curated/`, and the contents of any zip;
- the market root's path;
- the sealed demonstration's folder.

The first span is open, so this is not a closed-date boundary. It keeps the record at counts, as section 3 of the venue facts requires
("never a price or a rate"), so that no reading has to be logged for it.

**No date after 2023-12-31 enters the root.**

- No partition after 2023-12 is planned or fetched, and no bar is built after 2023-12-31.
- The 2023-12 funding file may hold the 2024-01-01 00:00 settlement, stamped a little early. F4 lists its time under `outside_span` and decides nothing on it (RC2-01).
- Its rate stays in that month's curated part. Nothing in this plan reads a rate, and FP-07 leaves out any setup that reaches that instant.

## 11. Before and after the run

### 11.1 Before

| # | Condition | Who |
|---|---|---|
| 1 | P-1 settled: the pause is in and reviewed, or the decision to run without it is written down | `developer`, `python-reviewer`, `leak-auditor`, or `project-manager` |
| 2 | The run commit chosen. Its data code is reviewed, and the full suite passes at that commit with its output recorded, as item 18 asks for the run commit | `project-manager`, the coordinator |
| 3 | This plan and its script reviewed: `PASS` or `PASS WITH CONDITIONS` | `leak-auditor`, `python-reviewer` |
| 4 | The root confirmed: `hft-crypto-data` directly in the owner's Documents folder, not synced to a cloud service, not there yet, and at least 5 GB free | Owner |
| 5 | Approval recorded in the decision log. It names the option for the switch, the run commit, the script's SHA-256 with LF endings, and the root by description only | `project-manager` |
| 6 | The registry's second copy decided, before part 4 (section 8) | `project-manager`, owner |

### 11.2 The runner's steps

These follow section 11.4 of the coverage check plan.

1. **Before.** In the shell that will run it, the runner confirms these and prints only yes or no for each, never a value:
   - The file hashes to the pinned value and has LF line endings.
   - `mktemp -u -d` names a folder directly in the system temporary folder, inside no agent's folder.
   - `DATA_ROOT` and `HFT_CONFIG_DIR` are unset in the shell. If either is set in the user or machine environment, it does not name the market root or an earlier root.
   - The Documents folder holds no `hft-crypto-data` and is inside no git work tree.
2. **How.** `bash run_first_span_fetch.sh <this repository> <the market root> first`, started in the background with no time limit.
3. **Stopping.** Only with `taskkill /F /T` on the run's `uv.exe`, found by name and by the run folder's last part, as in section 6 of the script review. Never with a signal to bash, `kill -9`, or `taskkill /F` without `/T`.
4. **After a stop or a kill,** and before anything is read, the count of the run's `uv.exe`, `python.exe` and `hft-crypto.exe` processes must read 0. An orphaned process writes only first-span files over the approved route, but counts read while it is still writing are wrong.
5. **Paths.** The run folder's path and the root's path stay in the local log.

### 11.3 After

**The fetch of record.** Every item below must hold:

- `ingest_exit` is 0, `run_status` is `ok` and `stop_reason` is `none`.
- `planned` and `done` are 192, and `overdue`, `failed`, `pending`, `bars_failed`, `bars_left_by_budget` and every `held_*` count are 0.
- `raw_files` shows `klines present 96` and `fundingRate present 96`, and nothing is quarantined.
- `raw_checksum_source` is `sidecar` for all 192 files, `raw_with_venue_checks` is 192 of 192, and `raw_hash_differs_from_catalog` is 0.
- `files_digest`, `files_digest_python` and `files_digest_expected` are equal, and `candle_zip_names_ok` is `True`.
- `curated_files` shows 96 parts each for `candles_official` and `funding`, and 2,922 parts for each of the eight bar datasets. `derived.bars.binance` shows 2,922 tasks `done`.
- `gaps` and `exclusions_open` are 0. On candles this follows from `D-45`'s zero unproved empty minutes. Anything else gets reported.

**Item 17, per symbol.**

- F1 to F5, K1, and K2 on BTCUSDT or K4 on ETHUSDT each read `true` with `months_checked` 48, and none reads `false`.
- F4's `expected` is 4,383 with `duplicates` 0. Its `missing` count is 0, or the `funding_file` lines list every missing settlement.
- K5 reads 2,103,840 rows, with 0 missing and 0 duplicates.
- K3's first and last minute go to review. No tick row is dated from them.

**The decision log entry.** `data-steward` writes it from the printed lines, with no path. It records:

- the commit and the script's hash;
- the three override hashes and both `config_hash` values;
- the start and end times and the exit code;
- the counts above, the three digests and every flag with its `months_checked`;
- F4's list, and K3's first and last minute;
- the zone sizes and the free space;
- "the market root", a new folder in the owner's Documents folder.

**The run folder.** It goes once the entry is written, and only after a count of `*.zip`, `*.parquet` and `*.sqlite` files under it,
outside `repo/`, reads 0. At that point it holds no dataset, so removing it is not a deletion under section 5 of the lifecycle document.
It takes the only copy of the switch with it.

**Then C-5 part 4.** `developer` runs it, from a clean clone at the commit `project-manager` names, whose `[costs]` in `engine.toml` equal
the C-5 commit's:

```bash
uv run --frozen --no-dev python -m hft_crypto.engine --data-root "<the market root>" --config configs/engine.toml \
  --start 2020-01-01 --end 2023-12-31 --declare-costs
```

- It needs no switch.
- The parser requires `--start` and `--end`, and `declare_costs` does not use them.
- It prints `The configuration's costs are in the trial registry. Nothing ran.`
- From then on, the root holds the registry (section 8).

## 12. Reviews, and what is not decided here

| Reviewer | What they review |
|---|---|
| `leak-auditor` | **The read boundary.** What leaves the root, and which lines and which file the main session may read (section 10). That the override cannot open a host, a path or a date beyond what the code allows (section 3). The root's place, beside the sealed demonstration and outside every agent's folder (section 8). The rerun rules (section 7). Whether `venue_checks.json` may be committed. The P-1 change, if it is made |
| `python-reviewer` | **The script, its commands and flags.** The order and exit-code handling. The override generator and its five checks. The digest line run inside the candle folder, and its Python cross-check. The read-only catalog queries. Git Bash details: `cygpath`, `sha256sum`'s `*`, `du -sb`, `df` on that drive. The stop table checked against the code (section 7). The P-1 change, if it is made |
| `developer` | P-1. P-2, P-3 and P-7 later, before stage two |
| `project-manager` | The switch (section 3), P-1's route, the approval entry, the root together with the owner, and any rerun note |
| Owner | The folder, whether it is synced, and the registry's second copy |

| Not decided here | My proposal | Who decides |
|---|---|---|
| The switch | Option B, by flag | `project-manager` |
| P-1 | Add the 2 s pause before the run | `project-manager`, `developer`, reviewers |
| The root | `hft-crypto-data` in the owner's Documents folder, if that folder is not synced | Owner, `project-manager` |
| Committing `venue_checks.json` | Yes, byte for byte, as for `D-45`'s documents | `project-manager`, `leak-auditor` |
| The registry's second copy | A copy of `catalog/` outside the root, plus a hash and row count in the log after each append | `project-manager`, owner |
| A recount if `files_digest` differs | The same checker, on the root's files, through a reviewed script | `project-manager`, `leak-auditor` |
| Rule `raw-archive-after-curated` for this root | It stays unreviewed. Nothing is deleted during stage one | `data-steward`, as rule owner |

## 13. Not checked

- **Any host.** Whether every file is still served, and whether any changed after `D-45`'s run, is unknown until the run.
- **Whether the owner's Documents folder is synced** by OneDrive or another client. I did not inspect the machine.
- **Times** for funding requests, the per-file checks and the bars (section 9).
- **The header of the 2020 funding files.** Section 3.1 of the venue facts leaves it `UNVERIFIED`. F1 stops the run if it differs.
- **Interference during a rename.** Whether antivirus or the search indexer holds a new file during a rename. The code would contain that as a failed task, and the run would end `partial`.
- **Git Bash on that drive.** Whether `df -B1 --output=avail` works on the Documents drive, and whether `du -sb` there counts as `python-reviewer` saw in the temporary folder.
- **The script itself.** It has not run, in any form.
