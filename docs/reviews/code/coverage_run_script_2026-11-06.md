**On correctness, the coverage check script may run as hashed, once the runner's steps in section 1 are in place. The rule removes what it should and refuses everything else I tried.**

# Code review: the coverage check script for Option B, and rule `check-root-after-run`

Reviewer: `python-reviewer`. Date: 2026-11-06. Run in Git Bash on the machine that will run the check.

**What was reviewed:**

- The script in section 11.3 of `docs/reviews/data/coverage_check_plan_2026-11-05.md` at `c40c91b`. The file that will run hashes to `48c6d571f6be748a3befd2ea64a69d68ea99b4c3e86dca1915ccab5019d990c0`. It has LF endings and is byte-identical to the 11.3 block. I extracted that block myself and got the same hash.
- The rule's table in section 6.
- Sections 17.6 and 17.7 of `docs/reviews/leak/data_center_recheck_2026-11-04.md`. Section 17.7 is not committed yet.
- `init_check_root`, `run_coverage_check` and `check_output` in `data/coverage.py`. `refuse_inside_repository` and `ROOT_KIND` in `data/zones.py`. `code_version` in `versioning.py`. `_cmd_coverage_check` in `cli.py`. `HttpFetcher.download` in `data/fetch.py`, to learn which file names the check writes.
- The run commit `99629db21a04e49e848455e4c4e1815c2f785055`. `git diff 0b853bd 99629db` is one line in `configs/pipeline.toml`. `git diff 0b853bd c40c91b -- src tests configs pyproject.toml uv.lock` is empty, so the code at `c40c91b` is the code that will run.

**Limits I kept:**

- `coverage-check` ran only with `--help`, and no market data host was contacted.
- Every probe ran in a new folder of my own under the system temp folder. The probes used dummy files of zero bytes or short text, and no market data.
- Production code and the script were not edited.

## 1. Verdict

**`PASS WITH CONDITIONS`.**

**What holds, run on this machine:**

- **The rule.** `remove_root`, copied verbatim from the script, removes a real `"$out"/root.*` root and prints both lines with the right counts. It refuses a folder with no `ROOT_KIND`. It refuses an NTFS junction or a Cygwin symlink named `"$out"/root.*` whose target holds `ROOT_KIND`, and the target survives. It refuses any path outside `"$out"/root.*`. It returns 0 on an empty or missing path.
- **Junctions inside a root.** `rm -rf` does not follow a junction inside a root, and the outside files survived with the same hashes. `find -type f` and `du -sb` do not follow it either.
- **The traps.** The root is removed when a command fails under `set -e`, and on `SIGINT`, `SIGTERM` and `SIGHUP` sent with `kill`, with a native Python child running. This holds both with and without `uv run`.
- **The steps before the fetch.** All pass in a fresh clone at the run commit:
  - The tree stays clean under `core.autocrlf=true`.
  - The three `test` lines and the HEAD check pass.
  - The `tomllib` heredoc passes, and it fails when it should.
  - `code_version()` prints `0.1.0+99629db21a04`, with no `-dirty`.
  - `init_check_root` takes a `cygpath -m` path and writes `ROOT_KIND`, and it refuses a path inside the clone.
- **The digest lines.** `output_sha256`, `files_digest` and `bytes_in_root` match values I computed separately in Python on dummy files. Git Bash's `sha256sum` prints a `*` before the path, and the `awk` step drops it.

**What the script cannot do:** recover from a hard kill, or from a removal cut short. I confirmed both of the auditor's `UNVERIFIED` points (section 5).

**Conditions.** None of them changes the script or its hash.

1. **Stop a run only by ending the run's `uv` process tree** (finding CR-03). Use `taskkill /F /T` on the `uv.exe` whose command line names the run folder. The script's own `EXIT` trap then removes the root within about a second and prints both lines. Do not use these, because they leave the fetch running:
   - `kill` or Ctrl-Break sent to the script's bash
   - `kill -9` on the bash
   - `taskkill /F` without `/T`
2. **RE-01's steps, with the process check filtered by name** (finding CR-05). Section 6 gives the exact commands. I tested each of them.
3. **A `root.*` folder left without its marker is not removed under rule `check-root-after-run` as written.** Use the one-off removal in section 5, or add it to the rule as a second case before the run (finding CR-06).
4. **Correct the rule table's path-check row** (finding CR-04). It claims a check against `DATA_ROOT` that cannot run, because the script unsets `DATA_ROOT`. For this run, 17.7 condition 1 covers the gap.

Findings CR-01 and CR-02 are hardening for any later version of the script. They are not conditions for this run, because the steps in condition 2 catch what they leave.

## 2. Each clause of the rule, and the line that implements it

Line numbers are those of the 11.3 script.

| Clause (section 6 table, section 11.2) | Line | Result |
|---|---|---|
| Selects exactly the one root this script made with `mktemp -d` | 46 makes it, and 37 checks the path | Holds, but only because line 46 is the only place `$root` is set. The pattern on line 37 also accepts `"$out"/root.X/../elsewhere` (CR-01) |
| ...which holds `ROOT_KIND` | 38 | Holds |
| Class `RE-DOWNLOADABLE` | 39, printed | Holds |
| Derived-data precondition does not apply | No line, by design | Correct: the check writes nothing derived |
| Path check: not a link | 38, `[ -L ]` | True for an NTFS junction and for a Cygwin symlink. A native symlink could not be made here without a privilege, so it is untested |
| Path check: `init_check_root` refused a root inside a repository | `coverage.py:183` | Holds. It refused a path inside the clone, both an existing folder and one not yet made |
| Path check: `init_check_root` refused a root holding or held by `DATA_ROOT` | `coverage.py:186-190` | **Never runs.** Line 15 unsets `DATA_ROOT`, and no `--data-root` is passed (CR-04) |
| Plan before delete | 39 before 40 | Holds |
| Log: `removal plan` and `removed` lines | 39 and 41 | Holds. When `rm` fails, `set -e` ends the function before line 41, both in a plain call and inside the `EXIT` trap. **No false `removed` line was printed** |
| 11.2 change 5: refuse anything not `"$out"/root.*` | 37 | Holds, apart from the `..` case in CR-01 |
| 11.2 change 6: a signal becomes an exit | 44 | Holds. Bash runs the trap only once the command in progress has returned (CR-03) |
| 11.2 change 8: `roots_left_in_run_folder` | 69 | Printed only when the script reaches its end, and it counts markers only. RE-01 covers the rest |

**Lines with no clause.**

- Line 36 returns 0 for an empty or missing path. This is harmless, because there is nothing to remove.
- A dangling junction named `root.*` also returns 0 there, and nothing is removed. Section 6's count 1 would still report it.

## 3. Check 1: `remove_root`

**Setup.** The function was copied verbatim with `sed -n '34,42p'` from the hashed file. It ran with `out` set to a folder of my own, through `bash -c 'set -euo pipefail; ...; remove_root "$1"'`. That is the script's own context: a plain call with `errexit` on. Junctions were made with `MSYS_NO_PATHCONV=1 cmd /c mklink /J`. Plain `cmd //c mklink /J` fails under Git Bash, because the `/J` switch is converted as a path.

| Case | Expected | Seen |
|---|---|---|
| Real root: `ROOT_KIND` (11 B), plus 100, 2000 and 300 B in nested folders | `files=4 bytes=2411`, removed | `removal plan: ... files=4 bytes=2411`, then `removed: ...`. rc 0, root gone |
| 5 files of 1 to 5 KiB in 3 nested folders, plus `ROOT_KIND` | `files=6 bytes=15371` | `files=6 bytes=15371`, removed. Folders count 0 bytes in `du -sb` on NTFS |
| `root.*` folder with no `ROOT_KIND` | Refused, rc 1 | `removal refused: not a check root`, rc 1, contents survive |
| Junction named `root.*`, target holds `ROOT_KIND` | Refused, target survives | `[ -L ]` true. `removal refused: not a check root`, rc 1, target intact |
| Cygwin symlink (`MSYS=winsymlinks:sys`) named `root.*`, target holds `ROOT_KIND` | Refused | `[ -L ]` true, refused, target intact |
| Native symlink (`mklink /D`, `winsymlinks:nativestrict`) | Refused | **Not tested.** Creating one needs an administrator account or Developer Mode on this machine, so `mktemp` cannot produce one either |
| Root holding `ROOT_KIND`, outside `"$out"` | Refused | `removal refused: not a root this script made`, rc 1, survives |
| `"$out"/notroot.*` holding `ROOT_KIND`, and `"$out"` itself holding `ROOT_KIND` | Refused | Both refused, rc 1, both survive |
| `"$out"/root.exists/../victim`, where `victim` holds `ROOT_KIND` | Refused | **Removed** (CR-01) |
| Empty path, and a missing `"$out"/root.missing` | rc 0, no output | rc 0, no output, for both |
| Dangling junction named `root.*` | rc 0 | rc 0, no output, junction left |
| Real root holding a junction to an outside folder of 3 files | Root removed, outside intact | `files=2 bytes=147`: the junction adds its own 36-byte size, and its target is not counted. Root gone. The outside files' SHA-256 values are unchanged |

**Git Bash behaviour.**

- `find -type f | wc -l` and `du -sb | cut -f1` give exact counts and apparent sizes.
- Neither follows a junction, because both default to `-P`.
- `du -sb` counts folders as 0 bytes. On Linux it counts 4096 per folder, so `bytes_in_root` from this run is not comparable byte for byte with a Linux `du`.

## 4. Check 2: the traps

**Setup.** The probe used the script's lines 5, 44 to 47 and 66 to 69 verbatim, with the fetch replaced by a stand-in command. It ran in the background under `set -m`. Without job control, a background job starts with `SIGINT` ignored, and that would have made the test meaningless. Each stand-in child ran for 60 s.

| Event | Child at the time | Bash ended | Root | Lines printed |
|---|---|---|---|---|
| `false` under `set -e` | None | At once, exit 1 | Removed | Plan and removed |
| `python -c "import sys; sys.exit(1)"`, as the stopped-document check does | Native | At once, exit 1 | Removed | Both |
| `kill -INT` | `python -c "...time.sleep(60)"` | **58 s later**, exit 130 | Removed | Both |
| `kill -TERM` | The same | **58 s later**, exit 130 | Removed | Both |
| `kill -INT` | `uv run --no-project --python 3.12 python -c "...sleep(60)"` | **57 s later**, exit 130 | Removed | Both |
| `kill -INT`, `-TERM` and `-HUP` | Cygwin `sleep 60` | 57 to 58 s later, exit 130 | Removed | Both |
| `false`, while another native process holds a zip deep in the root open | Holder not waited on | At once, exit 1 | **Partly removed:** `ROOT_KIND` and the sidecar went, the held zip and its folders stayed | Plan, then `rm: cannot remove '...zip': Device or resource busy`. **No `removed` line** |
| The same, with the failure in the plain call on line 66 | The same | At once, exit 1 | Partly removed, as above. The `EXIT` trap's second call then printed `removal refused: not a check root` | Plan, the `rm` error, then the refusal. No `removed` line and no `roots_left` line |
| A second `TERM` while the `EXIT` trap is removing (a test copy with `sleep 4` added before `rm`) | None | Exit 130 | **Left, with `ROOT_KIND`** | Plan only (CR-02) |
| `taskkill /F /T` on the run's `uv.exe` tree, leaving the bash alone | `uv run ... python` | **1 s later**, exit 1 | Removed | Both. The probe's second list did not start |

**A hard kill bypasses the trap.**

| Hard kill | Child | Bash | Child afterwards | Root |
|---|---|---|---|---|
| `kill -9` on bash | Direct `python`, a launcher and the interpreter under it | Gone | **Still running** | Left, with `ROOT_KIND` |
| `taskkill /F /PID` on bash's Windows process, without `/T` | Direct `python` | Gone | **Still running** | Left |
| `kill -9` on bash | `uv run ... python` | Gone | **`uv.exe` and `python.exe` still running** | Left |
| `taskkill /F /T /PID` on bash's Windows process | `uv run ... python` | Gone | Whole tree ended: bash, its stub, `uv` and `python` | Left, with `ROOT_KIND`. Nothing wrote to it afterwards |

**The orphan rebuilt the root.** In the three cases where the child survived, the child stood in for `_fetch_one`. Every 3 s it ran `mkdir(parents=True, exist_ok=True)` under the root and wrote a file there.

1. After the hard kill, I removed the root with `rm -rf`, as a runner would after a `ROOT_KIND` search. `rm` returned 0, and the root was gone.
2. Seven seconds later the root was back, holding 2 zips and **no `ROOT_KIND`**.
3. A search for `ROOT_KIND` under the run folder found **0**. A search for `root.*` entries found **1**.

This is RE-01 case (a), shown on this machine.

## 5. Answers to the questions in 17.7

### 5.1 May rule `check-root-after-run` remove a leftover with no marker?

**No, not as written.**

- **The rule's text.** The "Selects" row says the root "holds `ROOT_KIND`", and the path check says "Holds `ROOT_KIND`".
- **The function.** `remove_root` refuses such a folder: section 4 shows `removal refused: not a check root`.
- **The marker's role.** The marker is what shows a folder is a check root rather than some other `root.*` folder. Without it, something else has to stand in for it.

**The one-off removal.** This is a selection of its own, under its own name in the log. It can be written as a second case of the rule if the rule owner prefers. Use it only after every precondition below holds.

**Preconditions:**

1. **No process of the run is alive.** Count 0 from section 6, step 1.
2. **`out` is set to the run folder exactly as the `run_folder:` line in the local log printed it.** The pattern below compares text, so a different form of the same folder is refused, which fails safe.

**Selection and checks.** All of these were tested on this machine, on dummy files.

```bash
remove_leftover() {   # one-off, for a root.* that lost its marker. Run only once no process of the run is alive
  local root="$1" odd extra
  case "$root" in
    "$out"/root.*/*) echo "removal refused: not a root this script made"; return 1 ;;
    "$out"/root.[A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9][A-Za-z0-9]) ;;
    *) echo "removal refused: not a root this script made"; return 1 ;;
  esac
  if [ -L "$root" ] || [ ! -d "$root" ]; then echo "removal refused: a link, or not a folder"; return 1; fi
  odd="$(cd "$root" && find . -mindepth 1 ! -type d ! -type f | wc -l)"   # links, junctions, anything else
  extra="$(cd "$root" && find . -mindepth 1 | { grep -Ev '^\./(ROOT_KIND|coverage(/coverage_check\.json)?|raw(/archive(/binance(/klines(/(BTC|ETH)USDT(/date=[0-9]{4}-[0-9]{2}-01(/(BTC|ETH)USDT-1m-[0-9]{4}-[0-9]{2}\.zip(\.CHECKSUM)?)?)?)?)?)?)?)$' || true; } | wc -l)"
  if [ "$odd" -ne 0 ] || [ "$extra" -ne 0 ]; then echo "removal refused: holds entries the check does not write (links=$odd other=$extra)"; return 1; fi
  echo "removal plan: rule=check-root-leftover class=RE-DOWNLOADABLE files=$(find "$root" -type f | wc -l) bytes=$(du -sb "$root" | cut -f1)"
  rm -rf -- "$root"
  if [ -e "$root" ]; then echo "removal incomplete"; return 1; fi
  echo "removed: rule=check-root-leftover at=$(date -u +%FT%TZ)"
}
```

Run it with `set -euo pipefail`, once per entry that section 6's count 1 found in the run folder.

**What each part does:**

- **The path.** It must be a direct child of the printed run folder, named `root.` plus the six characters `mktemp` makes. No `/` may follow, so no `..` gets in.
- **Not a link or junction, and a real folder.**
- **No link, junction or other special entry inside.** This is not needed for safety, because `rm -rf` does not follow a junction (section 3). It keeps the selection to what the check could have made.
- **Every entry is one the check writes.** The check writes `ROOT_KIND`, `coverage/coverage_check.json`, and each `raw/archive/binance/klines/<BTCUSDT|ETHUSDT>/date=YYYY-MM-01/<SYMBOL>-1m-YYYY-MM.zip` with its `.CHECKSUM`, plus the folders above them. `HttpFetcher.download` writes straight to that name, with no temporary name. The zip is read in memory, so nothing is unzipped. I confirmed the names offline with `frozen_file_list`: for example `BTCUSDT-1m-2024-01.zip` under `date=2024-01-01`. **Only names are read, never content.**
- **The result is checked.** `removed` is printed only once the folder is confirmed gone.

**Tested cases:**

| Case | Result |
|---|---|
| A leftover holding only the check's paths | Removed, both lines |
| The same with `ROOT_KIND` and the output file | Removed |
| An empty `root.*` folder | Removed, `files=0 bytes=0` |
| One stray `raw/notes.txt` | Refused, `other=1` |
| A junction inside to an outside folder | Refused, `links=1`. The outside folder is intact |
| A junction named `root.XXXXXX` | Refused |
| `"$out"/root.X/../victim` | Refused |
| `root.toolongname`, and a name with spaces | Refused |
| A root outside the run folder | Refused |
| A file held open | `rm` error, then `removal incomplete`, rc 1, and no `removed` line. Once the holder ended, a second call removed it |

**If it refuses, do not work around it.** The folder is not opened. Its name counts are stated in the decision log, and `data-steward` and the owner decide.

**On the auditor's view that the path check alone is enough.** From correctness, the path check alone cannot reach outside the folder: `rm -rf` did not follow a junction inside one. The content check costs nothing in a fresh run folder, and it should always pass there. If it ever fails, something other than the check wrote into the run folder, and a person should know that before anything is deleted.

### 5.2 Does a native child outlive a hard kill? Does `rm -rf` fail on a file held open?

**A native child outlives a hard kill of its Git Bash parent: yes, verified.**

- After `kill -9` and after `taskkill /F` without `/T`, the native Python child kept running, and so did `uv.exe` under `uv run`.
- In each case it went on writing into the root and rebuilt `root.X/raw/...` with no `ROOT_KIND`, after the root had been removed.
- `taskkill /F /T` on bash's Windows process ended the whole tree.

**`rm -rf` on a file held open: it partly succeeds, verified.**

- A file held open by another Windows process fails with `Device or resource busy`.
- `rm -rf` carries on past it. `ROOT_KIND`, the sidecar and the other files went, and the held zip and its parent folders stayed.
- In the script this ends with no `removed` line and no `roots_left` line. The `EXIT` trap's second call refuses the now unmarked folder.
- Once the holder ended, `rm -rf` removed the rest.

**One more observation, on RE-02.** In my own session, a foreground tool call that ran past its limit was moved to the background at 180 s and ran to the end, instead of being ended. That is one session of this harness, and it is not evidence about the main session or about stopping a task by hand. Starting the script in the background, as 17.7 condition 2 says, is still right.

## 6. The runner's steps after the script, as tested

Set `out` to the `run_folder:` line from the local log, and `leaf` to its last part, `tmp.XXXXXXXXXX`.

**Step 1. No process of the run is alive.** Run this in PowerShell. It must print 0.

```powershell
@(Get-CimInstance Win32_Process | Where-Object { $_.Name -in 'uv.exe','python.exe','hft-crypto.exe' -and ($_.CommandLine -like "*$leaf*" -or $_.ExecutablePath -like "*$leaf*") }).Count
```

**Keep the name filter (CR-05).** Without it, the query matches its own shell, whose command line holds the folder name, and it never reads 0. I saw this happen.

What I saw with a `uv run --frozen --no-dev python ... --check-root <cygpath -m path>` stand-in:

- `uv.exe` matched on its command line.
- The venv's `python.exe` matched on both its path and its command line.
- The base interpreter's `python.exe` matched on its command line.

The `hft-crypto.exe` launcher could not be watched, because only `--help` may run. It sits under `repo/.venv/Scripts`, so `ExecutablePath` names the run folder. Whether the Python it starts carries the arguments is `UNVERIFIED`.

**To stop a live run (condition 1)**, end the `uv.exe` tree:

```powershell
Get-CimInstance Win32_Process -Filter "Name='uv.exe'" | Where-Object { $_.CommandLine -like "*$leaf*" } | ForEach-Object { taskkill /F /T /PID $_.ProcessId }
```

**Step 2. The two counts.** Run these in Git Bash. Both must print 0.

```bash
T="$(dirname "$out")"
find "$T" -mindepth 2 -maxdepth 2 -path "$T/tmp.*/root.*" | wc -l
find "$out" -path "$out/repo" -prune -o -type f \( -name '*.zip' -o -name '*.CHECKSUM' \) -print | wc -l
```

- `T` comes from the printed run folder, not from `$TEMP`, so it is the folder `mktemp` really used, whatever `TMPDIR` was.
- On a dummy layout, each command found exactly the entries it should. Entries under `repo/` and outside a `tmp.*` folder were not counted.
- Run them only after step 1 reads 0. Otherwise an orphan can rebuild a root after the count (section 4).

**Baseline.** When I finished, there was no `tmp.*` folder directly in the system temp folder, and no `ROOT_KIND` within four levels of it. A count above 0 after the run therefore comes from the run.

## 7. Findings

| ID | Location | Failure scenario | Severity | Fix |
|---|---|---|---|---|
| CR-01 | Script line 37 | The pattern `"$out"/root.*` accepts any text after `root.`, `/` and `..` included. Example: with `"$out"/root.exists` present and `"$out"/victim` holding `ROOT_KIND`, `remove_root "$out/root.exists/../victim"` prints both lines and removes `victim`. **Not reachable in this script,** because `$root` is set only on line 46 by `mktemp` | LOW. Not a condition | For any later version, replace line 37 with `case "$root" in "$out"/root.*/*) echo "removal refused: not a root this script made"; return 1 ;; "$out"/root.*) ;; *) echo "removal refused: not a root this script made"; return 1 ;; esac`. Tested: the `..` path is refused and a real root still goes |
| CR-02 | Script line 47 | A second signal while the `EXIT` trap is removing runs `exit 130` inside the trap. Bash then stops without finishing the removal. Shown with a test copy: the root was left with `ROOT_KIND`, after the `plan` line only. The real window is the length of `find`, `du` and `rm` on one root, well under a second here. Condition 2's search catches it | LOW. Not a condition | For any later version: `trap 'trap "" INT TERM HUP; remove_root "$root"' EXIT`. Tested: a second `TERM` during removal no longer stops it, and both lines print |
| CR-03 | Script line 44, and how a run is stopped | `kill -INT`, `-TERM` or `-HUP` sent to the script's bash waits for the command in progress, 57 to 58 s with a 60 s child. In the real run, the list in progress fetches to its end before the root goes. `kill -9`, or `taskkill /F` without `/T`, leaves `uv` and Python running and writing into a root nobody will remove. They rebuild it without a marker after a cleanup | MEDIUM, on the procedure. Not the script text | Condition 1: stop only by `taskkill /F /T` on the run's `uv.exe`. Tested: the script's own trap removed the root 1 s later, printed both lines, and did not start the next list. If bash itself must go, use `taskkill /F /T` on its Windows process. That ended the whole tree, and the root is then removed under the rule after step 1 reads 0 |
| CR-04 | Section 6 rule table, "Path check" row. Script line 15 | The row says `init_check_root` "has already refused ... one holding or held by `DATA_ROOT`". Line 15 unsets `DATA_ROOT` and no `--data-root` is passed, so `coverage.py:186-190` never runs. Example: `DATA_ROOT` set to a folder above the system temp folder would not be refused. Here `DATA_ROOT` was unset in my shell | LOW. Text, and closed for this run by 17.7 condition 1 | Change the row to: "Not a link. Holds `ROOT_KIND`. `init_check_root` has already refused a root inside a repository. The script unsets `DATA_ROOT`, so the runner confirms before the run that `DATA_ROOT`, if set, is neither the temporary folder nor above it (17.7 condition 1)." Or, in a later script version, keep `DATA_ROOT` and pass it as `--data-root`. I did not test that route |
| CR-05 | 17.7 RE-01 step (1) | A process search by command line alone, with the run folder's name in it, matches the searching shell itself. It never reads 0, or a runner learns to ignore it | LOW | Filter by `Name` as in section 6. Tested: 0 after the stand-in ended |
| CR-06 | Rule `check-root-after-run` | Both RE-01 cases leave a `root.*` folder with closed-date zips and no `ROOT_KIND`. The rule cannot select it, and `remove_root` refuses it | MEDIUM, on the procedure | Condition 3: section 5.1's one-off removal, or the same text added to the rule as a reviewed second case |

**Seen, and not a finding for this script:**

- `mypy` reports 4 errors at the run commit, all in `tests/`: `test_dated_tick.py:458` and `:519`, `test_date_guard.py:760` and `test_recheck_fixes.py:178`. There are none in `src/`. They are the same code as the base, they are not on this path, and they are for `developer`.
- `mypy` from the main working tree did not start, because of a Windows path-length error loading its compiled module. It ran from the clone.

## 8. Commands run, and what they printed

Folder names are replaced by placeholders. Every probe folder came from `mktemp -d`, directly in the system temp folder.

**The script and the run commit.**

```text
$ sha256sum <script>
48c6d571f6be748a3befd2ea64a69d68ea99b4c3e86dca1915ccab5019d990c0
$ git show c40c91b:docs/reviews/data/coverage_check_plan_2026-11-05.md | <extract the 11.3 block> | sha256sum
48c6d571f6be748a3befd2ea64a69d68ea99b4c3e86dca1915ccab5019d990c0
$ grep -c $'\r' <script>
0
$ git diff 0b853bd 99629db          -> one line: enabled = false -> enabled = true under [sources.binance]
$ git diff --stat 0b853bd c40c91b -- src tests configs pyproject.toml uv.lock     -> (empty)
```

**Check 3, in a fresh clone.** The commands are the script's lines 12 to 31 with `out` set to my folder:

```text
$ git clone --quiet --no-local <the repository path> "$out/repo"; cd "$out/repo"; git checkout --quiet --detach 99629db21a04e49e848455e4c4e1815c2f785055
$ git config --show-origin core.autocrlf      -> the system gitconfig: true
$ uv sync --frozen --no-dev --python 3.12
Using CPython 3.12.13
Creating virtual environment at: .venv
Installed 5 packages: hft-crypto==0.1.0, numpy==2.5.4, polars==1.44.2, polars-runtime-32==1.44.2, tzdata==2026.6
test 1 (HEAD) passes / test 2 (HEAD^) passes / test 3 (one file) passes
tomllib heredoc rc=0
porcelain: []            -> clean-tree test passes
$ uv run --frozen --no-dev python -c "from hft_crypto.versioning import code_version; print(code_version())"
0.1.0+99629db21a04
package file: src\hft_crypto\__init__.py   (an editable install, so code_version runs git in the clone)
config dir: configs                         (find_config_dir finds the clone's own configs/)
porcelain after imports: []                 (__pycache__ and .venv are ignored)
```

**The `tomllib` heredoc's negative cases**, on copies in my folder and not in the clone:

```text
base vs base                          rc=1 AssertionError
base vs run with prohibited flipped   rc=1 AssertionError: pipeline.toml differs beyond the one switch
base vs a copy of the run file        rc=0
```

**`init_check_root`, called from the clone's Python:**

```text
A) a fresh empty root.XXXXXX, cygpath -m form   made; ROOT_KIND: check-only | entries: ['ROOT_KIND']   rc=0
   the shell sees ROOT_KIND: yes (its content is "check-only\r\n" on Windows)
B) the same root again                          refused: CHECK_ROOT must be new and empty on each run
C) a new path inside the clone                  refused: DATA_ROOT must be outside the repository ...   (not created)
D) an existing empty folder inside the clone    refused: the same
E) a fresh root, cygpath -w form                made
porcelain after the probes: []
```

**The command's help:**

```text
$ uv run --frozen --no-dev hft-crypto coverage-check --help
usage: hft-crypto coverage-check [-h] [--check-root CHECK_ROOT] --list {closed-dates,first-span} [--venue VENUE]
```

**The digest lines.** The script's lines 61 to 64 ran verbatim on 6 dummy zips, 6 sidecars and an output file:

```text
output_sha256: e8c628edc9968ef0c668f54e0ba2636b35503357eb1aca0ddc828aeace432f67   expected (Python): the same
files_digest:  30a9ce6e9d4d7501a791fe3eda0bc354adf854101096f31d6aabc3084f874663   expected (Python): the same
bytes_in_root: 158                                                                expected: 158
```

**Checks 1 and 2.** Their outputs are in the tables of sections 3 and 4. Sample lines:

```text
T1  output: removal plan: rule=check-root-after-run class=RE-DOWNLOADABLE files=4 bytes=2411 | removed: rule=check-root-after-run at=2026-11-06T09:55:39Z   rc=0
T3a [ -L ] true on the junction; output: removal refused: not a check root   rc=1; target survives
mode=python signal=TERM: bash ended after 58 s, exit code 130; root removed
mode=uvwriter kill=kill9: native python child STILL RUNNING; its parent (uv) STILL RUNNING
  root after kill: present, ROOT_KIND present; runner rm -rf rc=0; 7 s later: root present, ROOT_KIND absent, zip files 2
  search for ROOT_KIND finds: 0; search for root.* entries finds: 1
mode=held: rm: cannot remove '.../BTCUSDT-1m-2024-01.zip': Device or resource busy; root LEFT (1 file); ROOT_KIND gone
tree kill of uv: bash ended 1 s later, exit code 1; removal plan ... / removed ...; 7 s later root absent
```

**The code under it, at `c40c91b`, whose code is the base's:**

```text
$ uv run --frozen pytest -q -m "not network" -p no:cacheprovider tests/data/test_date_guard.py tests/test_workflows.py
189 passed, 1 skipped (file symlinks need a privilege on this machine)
$ uv run --frozen ruff check src tests
All checks passed!
$ uv run --frozen mypy          (from the clone, after a full sync)
Found 4 errors in 3 files (checked 119 source files)   -> all four in tests/, listed in section 7
```

The full suite was not run at the run commit. With the source enabled, I chose not to run tests there, although `tests/conftest.py` installs a network guard.

## 9. Not checked

- **The fetch itself.** It was not run, as required. The following are therefore untested:
  - how long a list takes
  - whether Windows Defender or an indexer holds a new zip open long enough to make `rm` fail in a normal run
  - the real `uv` to `hft-crypto.exe` to `python` tree under a signal
- **A real Ctrl-C typed in a console window.** Git Bash here runs with `MSYS=disable_pcon`. Whether a console Ctrl-C reaches the native children directly, and so stops the fetch at once, was not tested. Section 6's tree kill does not depend on it.
- **A native NTFS symlink named `root.*`.** It needs a privilege this account does not have. `mktemp` cannot make one either.
- **How the main session's tool ends a task it stops by hand,** and that session's environment: `TMPDIR`, `DATA_ROOT`, `MSYS`. 17.7 condition 1 has the runner confirm these.
- **Whether the Python started by the `hft-crypto.exe` launcher carries the run folder in its command line.** It is `UNVERIFIED`. Section 6 step 1 also matches the launcher by its path, and the stop command works on the tree.
- **The full test suite at the run commit.**

## 10. Left running, and left on disk

- **Processes.** None left running. Every child my probes started ended, either by itself or by `taskkill`. A final search for any `uv.exe`, `python.exe`, `hft-crypto.exe`, `bash.exe`, `sleep.exe` or `cmd.exe` naming my folders found none.
- **Folders.** All my probe folders under the system temp folder were removed. Afterwards there was no `tmp.*` folder directly in it, no `root.*` inside one, and no `ROOT_KIND` within four levels.
- **Files.**
  - The script file was not changed, and its hash still reads `48c6d571...990c0`.
  - This review file is the only file I wrote in the repository, and it is not committed.
  - Running the tests in the main working tree used its existing `.venv`, and `-p no:cacheprovider` kept a cache from being written there. `git status` shows only what was there before, plus this file.
