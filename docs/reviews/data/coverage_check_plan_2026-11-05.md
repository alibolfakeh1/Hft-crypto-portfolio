# Coverage check: run plan for review

Date: 2026-11-05. Owner: `data-steward`. For item 8 of the leak recheck's list
(`docs/reviews/leak/data_center_recheck_2026-11-04.md`, section 17.4) and plan section 2
(`docs/decisions/FOLD_PLAN_2026-11-05.md`). Code read at commit `1c2dc23`.

**Status, 2026-11-06: run once by Option B under `D-44`, and complete. Both lists ended with `stopped: none`. The result is
`D-45`: plan section 2 applied once on candles, every quarter passes, and no date moves. The two output documents are
`coverage_check_closed-dates_2026-11-06.json` and `coverage_check_first-span_2026-11-06.json` beside this file. No run follows.**
The earlier status lines follow. Option B was approved under `D-44`, with the script of section 11.3 and the runner's steps of 11.4. **Status: for review by `leak-auditor` and
`project-manager`. Nothing here has run.** No workflow file exists, and this plan
does not create one. The workflow text is in section 5 for review only. No source was contacted to write this.

## 1. What runs, and what it decides

| Item | Value |
|---|---|
| Command | `hft-crypto coverage-check --list <closed-dates or first-span> --check-root <new, empty folder>` |
| Code | `src/hft_crypto/data/coverage.py` and `src/hft_crypto/cli.py` at the base commit. RA-02 is in `1c2dc23` |
| `closed-dates` | 2024-01 to 2026-09, both symbols: 66 monthly candle zips and 66 sidecars, 132 requests, 124.40 MB |
| `first-span` | 2020-01 to 2023-12, both symbols: 96 zips and 96 sidecars, 192 requests, 179.12 MB |
| Together | 324 requests, about 303.5 MB. Sizes are from the listing in the coverage record. Transfer time on a runner is `UNVERIFIED` |
| Pace | One connection, with 2 s after every request, so at least 11 minutes of waiting in all |

**What it decides:** coverage and storage only (FP-08). It stays a count. It opens no date, and `D-38` still holds for any read.

**What counts as the plan's application:** both lists, from the same run commit, each with `stopped: none`. If either stops,
crashes or times out, neither decides anything, and both run again in new roots (section 8). This pairing is my proposal (see
section 10).

After a complete run, `data-steward` writes the result to the decision log with the commit, and applies plan section 2 once.
On candles the rule applies once only (FP-09), so a complete run is never repeated.

## 2. Before either option

| # | Condition | Who |
|---|---|---|
| 1 | `leak-auditor` re-audits RA-02 at the base commit. The commit message of `1c2dc23` says "Not yet reviewed" (17.4 condition 1) | `leak-auditor` |
| 2 | **A 429 stops the run at once.** My record's section 4.2 says stop on a 403 or a 429. The fetcher stops on 403 and 451, but tries a 429 three times, 2 s and then 4 s apart. I ask for 429 to join 403 and 451 before the run (section 8) | `developer`, then review |
| 3 | The run commit is the base plus only the change in section 3, reviewed as a diff | `leak-auditor` |
| 4 | The workflow in section 5 or the script in section 6 is approved as written. Any change comes back for review | `leak-auditor` |
| 5 | `project-manager` records approval of the job under `D-34`, naming the option and the base commit | `project-manager` |

`D-37` is met by design: neither option saves anything to the Actions cache.

## 3. The run commit

A new branch, `check/coverage-check-run-1`, from the approved base commit. The proposed base is `1c2dc23`
(`1c2dc234b1b8d1ab3846a307bf3124414b3b516c`), to be replaced by whatever `leak-auditor` approves. It carries one commit with
exactly these changes:

```diff
--- a/configs/pipeline.toml
+++ b/configs/pipeline.toml
 [sources.binance]
-enabled = false
+enabled = true
```

Option A also adds `.github/workflows/coverage-check.yml`, the text in section 5. Option B adds nothing else, and its commit is
never pushed. Nothing else changes.

- **The branch name is chosen to stay out of the way.** `ci.yml` runs on `main` and `pipeline/**`, so it does not run here. The
  other four workflows have no push trigger, and schedules run only from the default branch.
- **`main` does not change.** `pipeline/first-data-run` does not change either, so no workflow file reaches a branch that others
  push to.
- **The branch is never merged** and gets no pull request.
- **After the result is logged,** a tag replaces the branch, so the recorded commit stays reachable with nothing armed. A tag push does
  not start a workflow whose trigger names only branches.

Enabling the source passes the config check, because `candle_allowance_ms` is declared. With the switch on, the client may contact only
`data.binance.vision` under `/data/futures/um`.

## 4. Steps, in order

| # | Step | Option A, Actions | Option B, local |
|---|---|---|---|
| 1 | Install `uv` 0.11.24 and run `uv sync --frozen --no-dev --python 3.12`. Nothing runs from the project yet | Job step | Script |
| 2 | Check the run commit: parent is the base, only the allowed files changed, and the config changes only `sources.binance.enabled`. Stop if not | Job step | Script, which also checks the tree is clean |
| 3 | `closed-dates` into a new, empty root | Job step | Script |
| 4 | Check that `stopped` is `none` and that `code_version` names this commit with no `-dirty`. Print the output's SHA-256, the file digest and the root's size | Same step | Script |
| 5 | `first-span` into a second new, empty root, only if step 4 passed | Same step | Script |
| 6 | As step 4 | Same step | Script |
| 7 | The roots go | They leave with the runner. Not a deletion under lifecycle section 5 | Removed in the same step, under the rule in section 6 |
| 8 | Write the decision log entry from the printed documents, then apply plan section 2 | `data-steward` | `data-steward` |

## 5. Option A: a GitHub Actions job

**Trigger: one push of the dedicated branch.**

- The file exists only on that branch, and its trigger names only that branch.
- `github.run_attempt == '1'` refuses a re-run from the interface.
- The base check refuses any later commit pushed to the branch.
- `concurrency` refuses overlap.
- `workflow_dispatch` is not used, because, from memory and `UNVERIFIED`, it needs the file on the default branch, and `main` must
  not change.

**What the job does not have:** no cache restore or save, no `upload-artifact`, no Pages step, no publish step, no secrets, and read-only
contents. `setup-uv` has its own cache switched off.

```yaml
# For review only. It belongs on branch check/coverage-check-run-1 and on no other branch.
name: Coverage check, one run

on:
  push:
    branches: ["check/coverage-check-run-1"]

permissions:
  contents: read

concurrency:
  group: coverage-check
  cancel-in-progress: false

jobs:
  count:
    if: github.run_attempt == '1'
    runs-on: ubuntu-24.04
    timeout-minutes: 45
    permissions:
      contents: read
    env:
      BASE_SHA: "1c2dc234b1b8d1ab3846a307bf3124414b3b516c" # replaced by the base leak-auditor approves
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
          fetch-depth: 2

      - uses: astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2 # v10.3.3
        with:
          version: "0.11.24"
          enable-cache: false

      - name: Install
        run: uv sync --frozen --no-dev --python 3.12

      - name: Refuse anything but the reviewed change
        run: |
          set -euo pipefail
          test "$(git rev-parse HEAD^)" = "$BASE_SHA"
          test "$(git diff --name-only HEAD^ HEAD | sort | paste -sd ' ')" = ".github/workflows/coverage-check.yml configs/pipeline.toml"
          git show HEAD^:configs/pipeline.toml > "$RUNNER_TEMP/base_pipeline.toml"
          uv run --frozen --no-dev python - "$RUNNER_TEMP/base_pipeline.toml" configs/pipeline.toml <<'EOF'
          import sys, tomllib
          with open(sys.argv[1], "rb") as a, open(sys.argv[2], "rb") as b:
              base, run = tomllib.load(a), tomllib.load(b)
          assert base["sources"]["binance"]["enabled"] is False
          assert run["sources"]["binance"]["enabled"] is True
          base["sources"]["binance"]["enabled"] = True
          assert base == run, "pipeline.toml differs beyond the one switch"
          EOF
          echo "commit $GITHUB_SHA on base $BASE_SHA: only the reviewed change"

      - name: Count closed-dates, then first-span
        run: |
          set -euo pipefail
          for list in closed-dates first-span; do
            root="$RUNNER_TEMP/check-$list"
            echo "list: $list"
            uv run --frozen --no-dev hft-crypto coverage-check --list "$list" --check-root "$root"
            echo
            uv run --frozen --no-dev python - "$root/coverage/coverage_check.json" "$GITHUB_SHA" <<'EOF'
          import json, sys
          with open(sys.argv[1], encoding="utf-8") as handle:
              document = json.load(handle)
          print("stopped:", document["stopped"])
          if not document["code_version"].endswith("+" + sys.argv[2][:12]):
              sys.exit("code_version does not name this commit")
          sys.exit(0 if document["stopped"] == "none" else 1)
          EOF
            echo "output_sha256: $(sha256sum "$root/coverage/coverage_check.json" | cut -d' ' -f1)"
            echo "files_digest: $(find "$root/raw" -type f -name '*.zip' -exec sha256sum {} + \
              | awk '{n = split($2, p, "/"); print $1 "  " p[n]}' | sort -k2 | sha256sum | cut -d' ' -f1)"
            echo "bytes_in_root: $(du -sb "$root" | cut -f1)"
          done

      - name: Free space left on the runner
        if: always()
        run: |
          echo "runner_free_bytes: $(df -B1 --output=avail "$RUNNER_TEMP" | tail -1)"
```

The heredocs sit at the block's left edge on purpose. YAML strips the block's indentation, so `EOF` ends up at column 0.

## 6. Option B: a local run

One script, run once, from a clean clone at the run commit. The clone is needed because `code_version` marks a changed tree `-dirty`,
and this working tree holds others' uncommitted work. `GITHUB_SHA` is unset, so the commit is read from git.

```bash
#!/usr/bin/env bash
# For review only. Coverage check, local route: both lists, and each root removed before the script ends.
set -euo pipefail
BASE_SHA="1c2dc234b1b8d1ab3846a307bf3124414b3b516c"   # the approved base
RUN_SHA="<the reviewed run commit, 40 hex>"
SOURCE_REPO="<this repository, as a clone URL or path>"

out="$(mktemp -d)"                                    # outside any repository. Holds the clone and the two outputs
git clone --quiet --no-local "$SOURCE_REPO" "$out/repo"
cd "$out/repo"
git checkout --quiet --detach "$RUN_SHA"
unset GITHUB_SHA DATA_ROOT HFT_CONFIG_DIR CHECK_ROOT
uv sync --frozen --no-dev --python 3.12
# The reviewed change and nothing else. Under this option the run commit carries no workflow file.
test "$(git rev-parse HEAD^)" = "$BASE_SHA"
test "$(git diff --name-only HEAD^ HEAD)" = "configs/pipeline.toml"
git show HEAD^:configs/pipeline.toml > "$out/base_pipeline.toml"
uv run --frozen --no-dev python - "$out/base_pipeline.toml" configs/pipeline.toml <<'EOF'
import sys, tomllib
with open(sys.argv[1], "rb") as a, open(sys.argv[2], "rb") as b:
    base, run = tomllib.load(a), tomllib.load(b)
assert base["sources"]["binance"]["enabled"] is False
assert run["sources"]["binance"]["enabled"] is True
base["sources"]["binance"]["enabled"] = True
assert base == run, "pipeline.toml differs beyond the one switch"
EOF
test -z "$(git status --porcelain)"                   # a clean tree, so the output names the commit
echo "commit $RUN_SHA on base $BASE_SHA: only the reviewed change"

remove_root() {   # rule check-root-after-run, below
  local root="$1"
  [ -n "$root" ] && [ -e "$root" ] || return 0
  if [ -L "$root" ] || [ ! -f "$root/ROOT_KIND" ]; then echo "removal refused: not a check root"; return 1; fi
  echo "removal plan: rule=check-root-after-run class=RE-DOWNLOADABLE files=$(find "$root" -type f | wc -l) bytes=$(du -sb "$root" | cut -f1)"
  rm -rf -- "$root"
  echo "removed: rule=check-root-after-run at=$(date -u +%FT%TZ)"
}

for list in closed-dates first-span; do
  root="$(mktemp -d)"
  trap 'remove_root "$root"' EXIT                     # a stop, a crash or Ctrl-C still removes the root
  echo "list: $list"
  uv run --frozen --no-dev hft-crypto coverage-check --list "$list" --check-root "$root"
  echo
  uv run --frozen --no-dev python - "$root/coverage/coverage_check.json" "$RUN_SHA" <<'EOF'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    document = json.load(handle)
print("stopped:", document["stopped"])
if not document["code_version"].endswith("+" + sys.argv[2][:12]):
    sys.exit("code_version does not name this commit, or the tree was not clean")
sys.exit(0 if document["stopped"] == "none" else 1)
EOF
  echo "output_sha256: $(sha256sum "$root/coverage/coverage_check.json" | cut -d' ' -f1)"
  echo "files_digest: $(find "$root/raw" -type f -name '*.zip' -exec sha256sum {} + \
    | awk '{n = split($2, p, "/"); print $1 "  " p[n]}' | sort -k2 | sha256sum | cut -d' ' -f1)"
  echo "bytes_in_root: $(du -sb "$root" | cut -f1)"
  cp "$root/coverage/coverage_check.json" "$out/$list.json"   # counts only
  remove_root "$root"
  trap - EXIT
done
```

**Rule `check-root-after-run`.** This is a deletion rule I propose as rule owner. It is not reviewed, so Option B cannot run until it is.

| Part | Text |
|---|---|
| Selects | Exactly the one root this script made with `mktemp -d`, which holds `ROOT_KIND`. Nothing else |
| Class | `RE-DOWNLOADABLE`, from a public archive that still serves it |
| Derived-data precondition | **Does not apply, by design.** The check keeps nothing derived. Its purpose is that these files are not kept |
| Path check | Not a link. Holds `ROOT_KIND`. `init_check_root` has already refused a root inside a repository. The script unsets `DATA_ROOT`, so the runner confirms before the run that `DATA_ROOT`, if set, is neither the temporary folder nor above it (leak recheck 17.7 condition 1). Corrected on 2026-11-06 under finding CR-04 of the script review. This is a named exception to deletion rule 5, which checks against `DATA_ROOT` |
| Plan before delete | The `removal plan` line, printed in the same step before `rm` |
| Log | The `removal plan` and `removed` lines, and the decision log entry says the roots were removed |
| Published runs | None depend on these files |

**What stays local afterwards:** the clone, its `.venv` and the two output files, with no market data. They can go once the
decision log entry is written.

## 7. Everything the run prints or writes

### 7.1 Written to disk

| Path, inside each root | What | Option A | Option B |
|---|---|---|---|
| `ROOT_KIND` | The text `check-only` | Leaves with the runner | Removed in the step |
| `raw/archive/binance/klines/<SYMBOL>/date=YYYY-MM-01/<SYMBOL>-1m-YYYY-MM.zip` | One monthly candle file, as served | Leaves with the runner | Removed in the step |
| The same with `.CHECKSUM` | Its sidecar | Leaves with the runner | Removed in the step |
| `coverage/coverage_check.json` | The one output, below | Leaves with the runner. Its content is in the log | Copied out, then removed with the root |

No other file is written: no curated data, bars, features, results, catalog, cache or artifact. Option B also writes the clone and
`.venv`, which hold no market data.

### 7.2 The output document, printed to the log and written to the file

The command prints the document as canonical JSON. The file holds the same content, indented. `check_output` enforces exact keys
and exact types, with no float, before anything is written.

| Field | Type | Meaning | Allowed by |
|---|---|---|---|
| `check` | Text | `coverage-check-v1` | Provenance |
| `code_version` | Text | `<package version>+<first 12 hex of the commit>`, with `-dirty` if the tree had changes | Provenance, 17.4 condition 4 |
| `run_at` | Text | UTC time of the run | Provenance |
| `file_list_sha256` | Text | SHA-256 of the frozen list's file names | Provenance |
| `stopped` | Text | Only `none` or `fetch_refused` (RA-02) | Fixed words about the host |
| `quarters` | List | Empty unless `stopped` is `none`. One entry per quarter and symbol: 22 for `closed-dates`, 32 for `first-span` | |
| `quarters[].quarter` | Text | For example `2024-Q1` | Names |
| `quarters[].symbol` | Text | `BTCUSDT` or `ETHUSDT` | Names |
| `quarters[].files` | Integer | Files fetched, out of 3 | Plan section 3, counts of files |
| `quarters[].files_checksum_ok` | Integer | Files that matched their sidecar | Counts of files |
| `quarters[].rows` | Integer | Candle rows read | Counts of rows |
| `quarters[].empty_minutes_unproved` | Integer | Missing rows on the 1-minute grid | Plan sections 2 and 3 |
| `quarters[].empty_minutes_proved` | Integer | Rows with zero trades (ruling 7 condition 4) | Plan sections 2 and 3 |
| `quarters[].row_checks_pass` | True or false | Every file read, and no row failed the checks of condition 5 | A row check that outputs only a flag |
| `quarters[].passes` | True or false | Plan section 2: three files read and matched, unproved empty minutes under 1%, and at least 100 trades in 90% of hours | Pass or fail by quarter |

**Never printed or written:** prices, volumes, taker flow, funding, trade counts, the share of busy hours, first or last stamps,
anything per hour, day or month, and the text of any error from a row.

### 7.3 Lines the job or script adds

| Line | Content |
|---|---|
| `commit <sha> on base <sha>: only the reviewed change` | Full commit hashes |
| `list: <name>` | The list about to run |
| `stopped: <word>` | `none` or `fetch_refused` |
| `output_sha256: <hex>` | SHA-256 of the output file. It differs from the printed JSON's, because the file is indented |
| `files_digest: <hex>` | SHA-256 over the sorted lines `<sha256>  <zip name>` of the zips in the root. It ties the counts to exact bytes, and stage one can compute the same over its own `first-span` files |
| `bytes_in_root: <integer>` | The root's size on disk |
| `runner_free_bytes: <integer>` | Option A only. Free space left on the runner's disk |
| `removal plan: ...` and `removed: ...` | Option B only. Rule, class, file count, bytes and UTC time |

**Also in the log:** checkout, `setup-uv` and `uv sync` lines (tool and package names and versions), and on a failure one of:

- `error: <text>` from a config, root or schema refusal, which names a key and never a value. Exit 2.
- A Python traceback from a refused host, which names the host. Exit 1.

The check's own `except` paths quote no row (17.1).

**Exit codes.** The command exits 0 even when `stopped` is `fetch_refused`. That is why step 4 reads `stopped` and fails the job itself.

## 8. If the runner cannot reach the source

| Event | What the code does | Result |
|---|---|---|
| HTTP 404 on a listed file | Skips that file | Not a stop. `files` is lower, and its quarter has `passes: false`. That is a coverage fact |
| HTTP 403 or 451 | Stops at once | `stopped: fetch_refused`, `quarters: []` |
| A file larger than the fetch limit of 2 GB | Stops at once | The same |
| HTTP 429, another HTTP error, a timeout, a DNS or connection failure, a short read | Three attempts, 2 s and then 4 s apart, then stops | The same. Condition 2 asks that 429 stop at once |
| A host outside the approved route | Refuses before connecting | A traceback, exit 1, no output file |
| Job timeout, cancel or runner loss | Nothing is written | No output file |

**In every case the run decides nothing.**

- The job ends red at step 4, or earlier, and the second list does not start.
- No partial counts exist, because a stopped document holds no quarter.
- `data-steward` logs the stop in the decision log that day.

**It is not worked around.** There is no retry loop beyond the fetcher's own, and no change of region, runner type, self-hosted
runner, proxy, VPN or mirror. Nothing is fetched from another host. The client cannot reach the bucket host the listing used anyway,
because only `data.binance.vision` under `/data/futures/um` is open to it.

**After a stop:** a rerun needs a new written note from `project-manager`, a new root, and the same option. If the run is refused
again, that route is closed and the owner decides. Moving from Option A to Option B after a refusal is not automatic. It needs a
written decision that states the refusal and why the local route is allowed on its own terms, so that it cannot be going around a
block.

**What the word cannot say.** `fetch_refused` covers both a block and an outage, because the code keeps the reason inside, as RA-02
requires. Whether GitHub's runner regions are inside Binance's terms of use is `UNVERIFIED`. I did not check it, and no source may be
contacted for this plan. An HTTP 451 would be the host's own answer, and it is a stop.

## 9. Recommendation: Option A, the Actions job

- **No local copy.** Closed-date files never sit on a machine where agents work, which is 17.4 condition 2's concern.
- **No deletion at all.** The files leave with the runner, which lifecycle section 5 does not count as a deletion. Option B needs a new
  deletion rule and its review.
- **A clean commit record.** `GITHUB_SHA` names the pushed commit, and the job refuses anything but the reviewed diff. Option B needs a
  clean clone to avoid `-dirty`.
- **A public trail.** The log holds the commit, both documents and the digests. The auditor allows the one output file in a public log.

**Its costs:**

- Every line of section 7.3 is public. That is all counts and fixed words.
- The runner's region and its reach to the source are `UNVERIFIED`. A refusal stops it, as section 8 says.
- It needs one push of a throwaway branch. Owner and `project-manager` decide that push. I do not push or commit.

**If Option A ends in `fetch_refused` twice, I do not recommend Option B as the next step by default.** That goes to the owner with the
refusal stated.

## 10. Not decided here

| Item | My proposal | Who decides |
|---|---|---|
| The pairing: both lists complete, or neither counts | Both or neither, from one run commit | `leak-auditor`, `project-manager` |
| 429 stops at once (section 2 condition 2) | Yes, before the run. It is my record's spec, and the code differs | `developer`, `leak-auditor` |
| A rerun after `fetch_refused` | One, on a written note, in a new root, with the same option. A second refusal goes to the owner | `project-manager` |
| Whether `fetch_refused` should carry a fixed reason (`http_403`, `http_451`, `timeout`) to tell a block from an outage | Worth having, as more fixed words under RA-02's test | `leak-auditor`, `developer` |
| Branch after the run | A tag on the run commit, then delete the branch | `project-manager` |
| Rule `check-root-after-run` | Review only if Option B is chosen | `python-reviewer`, `leak-auditor` |
| `code_version` holds 12 hex characters, not the full hash | Enough, with the full hash in the log line. The decision log entry records both | `leak-auditor` |
| Counts describe the files as served on the run day. First-span files have been republished before (2022-05), and the output cannot hold per-file checksums | The `files_digest` line lets stage one confirm the same bytes. If it differs, stage one's files are counted again before use | `data-steward` |
| Whether the runner's region is within Binance's terms of use | Unchecked. A refusal is a stop | Owner |

## 11. Option B on the owner's machine, 2026-11-06

**The owner chose Option B, the local run, on 2026-11-06.** The machine runs Windows, so the section 6 script runs under Git
Bash with the changes below. **Nothing has run.** This text goes to `python-reviewer` for rule `check-root-after-run` and to
`leak-auditor` for the changes and the run commit's diff, under section 2 conditions 3 and 4.

### 11.1 Base and run commit

| Item | Value |
|---|---|
| Base | `0b853bdf87e72591c24ee21d220719b668661f55`. Its diff beyond `be20ee7` touches `data/ingest.py`, `data/venue_checks.py`, `engine/simulator.py`, `configs/engine.toml` and tests, all from `d888254`, which `leak-auditor` re-audited at `8da9ebc`. Commits after `d888254` change documents only |
| Run commit | `99629db21a04e49e848455e4c4e1815c2f785055`, on local branch `check/coverage-check-run-1`. One line: `enabled = false` becomes `enabled = true` under `[sources.binance]`. Made without touching the working tree. Never pushed, never merged |

### 11.2 Changes from the section 6 script

| # | Change | Why |
|---|---|---|
| 1 | `BASE_SHA` and `RUN_SHA` filled in. `SOURCE_REPO` is the script's first argument | No local path is written into a committed text |
| 2 | `run_folder: <path>` is printed | So the two output files can be found. The log stays local, and the path is never copied into the repository |
| 3 | `test "$(git rev-parse HEAD)" = "$RUN_SHA"` added | The checkout is checked too, not only its parent |
| 4 | Paths given to `uv` and Python go through `cygpath -m` | Native Windows programs get a Windows path, with no reliance on Git Bash's automatic conversion |
| 5 | Each root is made inside the run folder as `root.XXXXXX`. `remove_root` refuses any path that is not `"$out"/root.*` | It narrows what the rule can select to a root this script made |
| 6 | `trap 'exit 130' INT TERM HUP` before the loop | A signal becomes an exit, so the `EXIT` trap still removes the root |
| 7 | `stop_reason: <word>` is printed after `stopped:` | A fixed word from the list, held by the schema test of RA-02. It tells a block from an outage |
| 8 | Last line `roots_left_in_run_folder: <count>` | Condition 2 of 17.6, inside the script. The same search runs again after the script ends, in case it was killed |
| 9 | `uv sync --python 3.12` uses the 3.12 interpreter uv already holds on the machine | Nothing extra is downloaded for the interpreter |

**Who runs it.** The main session, whose brief excludes the root: it reads only the script's printed lines and the two output
files, which hold counts. The run folder is new, under the system temporary folder, and no agent session uses it.

**Afterwards.** The clone, its `.venv` and the two output files stay in the run folder until the decision log entry is
written, then go. They hold no market data.

### 11.3 The script, as it will run

```bash
#!/usr/bin/env bash
# Coverage check, local route (Option B), on Windows under Git Bash. Both lists, and each root removed before the
# script ends. Text reviewed in section 11 of docs/reviews/data/coverage_check_plan_2026-11-05.md.
# Usage: bash run_coverage_check.sh <path of this repository>
set -euo pipefail
BASE_SHA="0b853bdf87e72591c24ee21d220719b668661f55"   # the approved base
RUN_SHA="99629db21a04e49e848455e4c4e1815c2f785055"    # the reviewed run commit, local branch check/coverage-check-run-1
SOURCE_REPO="$1"                                      # passed in, so no local path is written into this text

out="$(mktemp -d)"                                    # a new folder under the system temporary folder, in no repository
echo "run_folder: $out"
git clone --quiet --no-local "$SOURCE_REPO" "$out/repo"
cd "$out/repo"
git checkout --quiet --detach "$RUN_SHA"
unset GITHUB_SHA DATA_ROOT HFT_CONFIG_DIR CHECK_ROOT
uv sync --frozen --no-dev --python 3.12
# The reviewed change and nothing else. Under this option the run commit carries no workflow file.
test "$(git rev-parse HEAD)" = "$RUN_SHA"
test "$(git rev-parse HEAD^)" = "$BASE_SHA"
test "$(git diff --name-only HEAD^ HEAD)" = "configs/pipeline.toml"
git show HEAD^:configs/pipeline.toml > "$out/base_pipeline.toml"
uv run --frozen --no-dev python - "$(cygpath -m "$out/base_pipeline.toml")" configs/pipeline.toml <<'EOF'
import sys, tomllib
with open(sys.argv[1], "rb") as a, open(sys.argv[2], "rb") as b:
    base, run = tomllib.load(a), tomllib.load(b)
assert base["sources"]["binance"]["enabled"] is False
assert run["sources"]["binance"]["enabled"] is True
base["sources"]["binance"]["enabled"] = True
assert base == run, "pipeline.toml differs beyond the one switch"
EOF
test -z "$(git status --porcelain)"                   # a clean tree, so the output names the commit
echo "commit $RUN_SHA on base $BASE_SHA: only the reviewed change"

remove_root() {   # rule check-root-after-run
  local root="$1"
  [ -n "$root" ] && [ -e "$root" ] || return 0
  case "$root" in "$out"/root.*) ;; *) echo "removal refused: not a root this script made"; return 1 ;; esac
  if [ -L "$root" ] || [ ! -f "$root/ROOT_KIND" ]; then echo "removal refused: not a check root"; return 1; fi
  echo "removal plan: rule=check-root-after-run class=RE-DOWNLOADABLE files=$(find "$root" -type f | wc -l) bytes=$(du -sb "$root" | cut -f1)"
  rm -rf -- "$root"
  echo "removed: rule=check-root-after-run at=$(date -u +%FT%TZ)"
}

trap 'exit 130' INT TERM HUP                          # a signal becomes an exit, so the EXIT trap below still runs
for list in closed-dates first-span; do
  root="$(mktemp -d -p "$out" root.XXXXXX)"
  trap 'remove_root "$root"' EXIT                     # a stop, a crash or Ctrl-C still removes the root
  echo "list: $list"
  uv run --frozen --no-dev hft-crypto coverage-check --list "$list" --check-root "$(cygpath -m "$root")"
  echo
  uv run --frozen --no-dev python - "$(cygpath -m "$root/coverage/coverage_check.json")" "$RUN_SHA" <<'EOF'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    document = json.load(handle)
print("stopped:", document["stopped"])
print("stop_reason:", document["stop_reason"])
if not document["code_version"].endswith("+" + sys.argv[2][:12]):
    sys.exit("code_version does not name this commit, or the tree was not clean")
sys.exit(0 if document["stopped"] == "none" else 1)
EOF
  echo "output_sha256: $(sha256sum "$root/coverage/coverage_check.json" | cut -d' ' -f1)"
  echo "files_digest: $(find "$root/raw" -type f -name '*.zip' -exec sha256sum {} + \
    | awk '{n = split($2, p, "/"); print $1 "  " p[n]}' | sort -k2 | sha256sum | cut -d' ' -f1)"
  echo "bytes_in_root: $(du -sb "$root" | cut -f1)"
  cp "$root/coverage/coverage_check.json" "$out/$list.json"   # counts only
  remove_root "$root"
  trap - EXIT
done
echo "roots_left_in_run_folder: $(find "$out" -maxdepth 2 -name ROOT_KIND -type f | wc -l)"
```

The file that runs must have SHA-256 `48c6d571f6be748a3befd2ea64a69d68ea99b4c3e86dca1915ccab5019d990c0`, with LF line endings.
The decision log entry records that hash.

### 11.4 Reviews and the runner's steps

`leak-auditor`: `PASS WITH CONDITIONS`, section 17.7 of the leak recheck. `python-reviewer`: `PASS WITH CONDITIONS`,
`docs/reviews/code/coverage_run_script_2026-11-06.md`. The script runs as it is. The conditions are the runner's steps:

1. **Before.** In the shell that runs it: `mktemp` names a folder directly in the system temporary folder and in no agent
   folder, `DATA_ROOT` is unset, and the file has the hash above.
2. **How.** Started in the background with no time limit.
3. **Stopping.** Only `taskkill /F /T` on the run's `uv.exe`. Never a signal to bash, `kill -9`, or `taskkill /F` without `/T`.
4. **The run folder's path** stays in the local log only. Until the after-run counts read 0, nothing under the run folder is
   opened except the two output files.
5. **After, in this order.** No `uv.exe`, `python.exe` or `hft-crypto.exe` of the run is alive. Then two counts, both 0:
   `root.*` folders inside any `tmp.*` folder beside the run folder, and `*.zip` or `*.CHECKSUM` files under the run folder
   outside `repo/`. Both counts go in the decision log entry. Commands: section 6 of the script review.
6. **A leftover without its marker** is removed only by the one-off `check-root-leftover` selection in section 5.1 of the
   script review, after step 5's process count reads 0. If that refuses, nothing works around it, and `data-steward` and
   the owner decide.
7. **The first complete pair is the application:** both documents with `stopped: none` and a `code_version` ending
   `+99629db21a04` with no `-dirty`. No run follows a complete pair.
