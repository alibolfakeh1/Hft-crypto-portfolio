# Code recheck: data center and pipeline

Reviewer: `python-reviewer`. Work done 2026-11-04 to 2026-11-05. Code at commit `dafe3f2`, documents at `38d5907`, branch
`pipeline/first-data-run`. `git diff dafe3f2 HEAD` over `src`, `tests`, `configs`, `.github` and `pyproject.toml` is
empty, so the code reviewed is the code at the branch tip.

This answers [the code review](data_center_2026-11-04.md) and tests the claims in
[the developer's answer](data_center_fixes_2026-11-04.md). Each claim there was treated as a claim. All data used is
generated, nothing touched the network, and every probe ran in a temporary directory outside the repository. This report
says nothing about any strategy or result.

**Addition of 2026-11-05: section 14 rechecks N-01 to N-18 at `cf1880f`, and its verdict is `PASS WITH CONDITIONS`. The sections below stand as written at `dafe3f2`.**

## 1. Verdict: `FAIL`

The verdict rests on one finding. **F-18 is reopened: the fix to the watchdog made the owner's only alarm fail silently,
in two ways.** A refused alert is recorded as sent, and a watchdog that cannot read the result reports nothing to
check. If a third risk holds on GitHub (N-03, which I could not test), publishing skips on every scheduled run and the
watchdog then stays quiet about that too.

Everything else is much better than the first review. All eight High findings are closed: five `PASS`, and three
`PASS WITH CONDITIONS` for residuals that are narrower than what they replaced.

| Verdict | Count | Findings |
|---|---|---|
| `PASS` | 13 | F-01, F-02, F-06, F-07, F-08, F-10, F-11, F-14, F-15, F-16, F-19, F-20, F-21 |
| `PASS WITH CONDITIONS` | 9 | F-03, F-04, F-05, F-09, F-12, F-13, F-17, F-22, F-23 |
| `FAIL` | 1 | F-18 |

**To change the overall verdict:** fix N-01 and N-02, replace the expression in N-03 or show it working on GitHub, and
fix N-04. A recheck of those lines is enough. The rest of section 3, N-18 above all, and the steward's R6 changes should be done before any
source is enabled.

## 2. Verdict per finding

| ID | Verdict | Evidence from running it |
|---|---|---|
| F-01 | `PASS` | 45 true traversal rows refused, and all 50 target files survive. `register_file` refuses bad paths and parents. A traversal child blocks raw. Five `%2e%2e` rows are literal names: selected, and they delete nothing |
| F-02 | `PASS` | Forged plan, out-of-zone delete, stale plan and unknown rule all refused at the moment of deletion. `bytes_freed` counts a shared file once |
| F-03 | `PASS WITH CONDITIONS` | 6 h hole: trades `warn`, gap recorded, 361 bars flagged from 06:01 to 12:01, 17 of 24 hours complete. **Condition:** N-17, a short hole on a source with no sequence and no candles still reads `pass` at day level. The bars themselves are flagged. This waits on the G1 ruling |
| F-04 | `PASS WITH CONDITIONS` | Every row of the review now fails through `run_ingest`, with flags from the first bad minute, an exclusion, raw kept, and the day out of the benchmark. A real straddle over midnight passes on both days, and a carry plus a straddle at the first boundary passes by both arrival orders. Departure accepted (section 4). **Conditions:** N-05, the 2% price tolerance. Tests for the daily excess check and the carry override, which have none (section 6) |
| F-05 | `PASS WITH CONDITIONS` | Three runs in a row over a corrupt file: older day done, file quarantined, run row finishes, status `partial`. 2,000 fuzzed files across the five parsers raised only `ValidationError`. The ten HTTP failure shapes all retried and ended right. **Conditions:** N-04, N-09, N-10, N-18. The fixes file's "the run row always finishes" is refuted by N-04 |
| F-06 | `PASS` | The hand case of the review now ends with `bars_1m` and `bars_1d` both V10 C150. A crash before and after every persistence call across three runs: 198 crash points, 0 differ from a run that never crashed, in curated bytes, tasks and verdicts |
| F-07 | `PASS` | Empty answer: no bars, `DATA_GAP`. Host cap of 2 rows: not caught up, 1 bar. Slow write: last close stays at `t_cut`. Five C17 cases by hand all right. Future stamps and year 9999 fail the pass |
| F-08 | `PASS` | Flags [1,2,3,4] after a failed pass and after a budget stop. Resume equals an uninterrupted run, 19 of 19 bars. 18 crash points across the poll's writes, 0 differ from a clean run, gap flags included |
| F-09 | `PASS WITH CONDITIONS` | All hand cases refused, and empty fill ids refused. **Condition:** N-11, the claim "every numeric column" is false for two unused columns |
| F-10 | `PASS` | 12 commands, zero network attempts. Every configuration route refused at load: flip enabled, delete `prohibited`, `prohibited=false` and `""`, a Kraken URL at the Binance host (also with other case and a trailing dot), a new source holding a Binance URL, `enabled="false"`, a misspelt key, a Binance benchmark. A new source on an unlisted host loads but the fixed list refuses it. Redirects right. `check_url` refuses a user part, backslash, port, leading space and trailing dot |
| F-11 | `PASS` | Missing requirements refused at load. String and misspelt booleans refused. A raw file with no source URL is not deletable. Young `raw/live`, the ledger and decisions survive every watermark from 0 to 1000% |
| F-12 | `PASS WITH CONDITIONS` | The load check works. The second check works when reached: `build_benchmark` refuses a prohibited venue with passing catalog rows and the load check bypassed. **Condition:** the named test never reaches it, because it copies files with no catalog rows, so `statuses` stops it first (`tests/reports/test_report.py:362`). That mutant survives. See also N-08 |
| F-13 | `PASS WITH CONDITIONS` | Marker gone: refused under both configs. A real report over a marked live root: refused. `reconcile-live`: refused. Every log line has `data_kind`. **Condition:** N-07 |
| F-14 | `PASS` | `.git/config`, `.gitignore`, `.gitattributes`, `ledger/.gitignore`, hidden names, workflow files, `README.md`, `index.html`, wrong case and wrong suffix all refused, and nothing changed. A junction refused. The real results and poll bundles pass the list. N-16 is a small remainder. The link test skips on this machine, and I reached the same check with a junction |
| F-15 | `PASS` | 10 checks, 0 deviations. Existing duplicates stay, an edited or shorter ledger log is refused, a true append is accepted, a bundle cannot delete, a refusal pushes nothing, the next good bundle starts clean, and an orphan from a failed lookup never replaces history |
| F-16 | `PASS` | Status `nothing_selected`, alerts raised, health shows partial coverage |
| F-17 | `PASS WITH CONDITIONS` | The 8 GB text is gone from both documents at `38d5907`. **Conditions:** cannot be run here. Cache save has no branch limit, and the 10 GB limit has no margin (section 7, section 8) |
| F-18 | **`FAIL`** | N-01 and N-02. What works: a stale report alerts, the same message is suppressed, a change resends, all clear resets, a bad date counts as stale, no secrets stays quiet and sends later, a connection failure retries |
| F-19 | `PASS` | A restart with a new book passes, a break after it fails. Negative, `NaN` and `inf` sizes refused. One-sided file refused. How often real files restart is still unknown |
| F-20 | `PASS` | By hand on a 3-day series: total 8.9%, annualised over 365 days, volatility 2.206052, Sharpe 5.515131, drawdown -10%, 73 marks. All match. With one hourly file missing: `None` and the note "48 of 72 marks are available" |
| F-21 | `PASS` | Budget of 1 s with a clock jumping 100 s per read: sweep rebuilds 0, reports 6 left, status `partial`. Departure accepted. The 75% share has no test that pins it (section 6) |
| F-22 | `PASS WITH CONDITIONS` | The count slip is real (section 9). Rulings exist for five of the six clauses. **Conditions:** G1 is still with `project-manager`, and the code the rulings ask for is not written |
| F-23 | `PASS WITH CONDITIONS` | Junction, walk, sweep, double count, mistyped root, `get_bytes`, env inputs, date guard, `no_approved_source`, fixed clock and page text verified. **Condition:** `provisional` is overruled and the change is not made (section 8). N-14 is a remainder |

## 3. New and remaining defects

### N-01, High. A refused alert counts as sent

`.github/workflows/watchdog.yml:91-94`, with the digest stored at `:100`.

`curl` has no `--fail`, so it exits 0 on any HTTP answer. I ran the shell block with a real `curl` against a loopback server:
exit 0 on 200, 400, 401, 403, 429 and 500. Each gives `sent=1`, stores the digest, and prints "An alert was sent."

- **A passing refusal.** Telegram answers 429 or 500 once to a health alert whose text does not change. The next run says
  "Nothing has changed since the last alert", makes 0 attempts, and the alert is gone. The version before this fix had no
  memory, so this is a new way to lose an alert.
- **A lasting refusal.** With a revoked token or a wrong chat id, the watchdog reports "An alert was sent" on every change,
  and the job is green.
- **Two owners.** `sent=1` is set if any one send succeeds, so an owner whose send failed never gets that alert. I read this
  one and did not run it.

**Fix:** use `--fail-with-body` or check `http_code`, store the digest only when every owner's send got a 200, and let the
run report failure. "This step never fails" is right for the watchdog's own bad data, and wrong for an alert that did not
go out. A test needs a fake `curl` that exits 0 with a 403 body, or a loopback server.

### N-02, High. A watchdog that cannot read the result says there is nothing to check

`.github/workflows/watchdog.yml:43-48`.

I ran three inputs: `gh api` failing, a corrupt `status.json`, and a `status.json` with no `generated_at`. All three print
"No result on the results branch yet, so there is nothing to check.", exit 0, and send nothing. A wrong token scope, a
deleted branch, a truncated file or a missing `jq` all look like this forever, and those are the cases a watchdog exists for.

**Fix:** tell a true 404 from every other failure. Anything else alerts. Also alert on "no result" itself once the job has
existed for longer than the age limit, or after a date set by a repository variable.

### N-03, High if it holds. `default_branch` on a scheduled run. `UNVERIFIED`

`.github/workflows/daily-pipeline.yml:141,158,180,189`, `.github/workflows/live-poll.yml:99,121,130`.

Publish, deploy and prune all need `github.ref == format('refs/heads/{0}', github.event.repository.default_branch)`. I could
not check here whether the payload of a `schedule` event carries `repository`. The expression is the only thing deciding
those jobs, and the tests read its text. If it is empty on a schedule, every scheduled run skips publish, deploy and prune and
stays green, and N-02 then reads "No result ... yet". That chain has no alarm at all.

**Fix:** remove the doubt rather than test it. Schedules run on the default branch by definition, so use
`github.event_name == 'schedule' || github.ref == ...`, and take the prune's branch from `github.ref_name`. Then check the first
scheduled run by hand.

### N-04, Medium. A stray file name kills the run and leaves its row `running`

`src/hft_crypto/data/ingest.py:582`, called at `:752`. `finish_run` at `:764` is not in a `finally`.

Put `part-notadate.parquet` in `curated/trades/...`. `dt.date.fromisoformat` raises `ValueError` in the sweep, outside the
containment around tasks. The run dies with a traceback, its row stays `running`, and every later run does the same. The same
path holds for any other exception in the housekeeping after the task loop.

**Fix:** skip and alert on a name that is not a date, and wrap the body so `finish_run` always runs with a failed status.

### N-05, Medium. The price tolerance passes a wrong price of 1.9%

`configs/pipeline.toml:104,110`, `bar_price_rel = 0.02`.

I raised the last price of a day by 1.9% in the trade file and left the official candles alone. Result: `pass`, 0 bars flagged,
raw deleted, and the day is in the benchmark, with a daily return off by 1.9%. The earlier absolute 15 USD was about 1.5 basis
points at a 100,000 price, so this is about 130 times wider. It is also near a typical day's move, which makes it a wide gate
for an equity curve. Rows F (10x) and N2 (VWAP off by 9%) do fail, so the check works and only the width is at issue.

**Fix:** trades and candles from one venue should agree to about a tick, so start near that, and measure on the approved source.
The comment at `:98-100` calls a change before that recheck a counted trial, so `project-manager` should say whether changing a
placeholder with no real data seen counts.

### N-06, Medium. The network guard: see section 5

`tests/conftest.py:15-22`. The suite reached nothing, measured. The guard would not have stopped several routes, and its alarm
can be swallowed. A stronger version was tried, and it works.

### N-07, Medium. A live root that lost its marker reports generated runs with no label

`src/hft_crypto/cli.py:89`. `_refuse_mixed_roots` looks only for the marker file on the live root. `src/hft_crypto/reports/report.py:316-322`
checks the catalog's stored flag and venue names, but only on the report's own root.

`report --published --live-root <generated root with its marker removed>`, on a real root: exit 0, and `status.json` shows 43 generated poll runs with
`data_kind` `NONE`, while every one of those log lines says `SYNTHETIC`. No `SYNTHETIC` label reaches the output (rule 4).

**Fix:** apply the check in `_is_synthetic` to the live root's catalog as well, and refuse a poll log with a line that says `SYNTHETIC` when the report's own root
is not marked.

### N-08, Medium. The read API serves a prohibited venue

`src/hft_crypto/data/reader.py:67-74`.

`reader.bars(1, "binance", ...)` with files on disk returned the row. An unknown venue returns 0 rows with no error. Nothing in `src` calls
`MarketReader` yet, but it is the API strategies are told to use, and every other route to that venue is closed.

**Fix:** call `source_usable` in `_load`, and raise on an unknown venue.

### N-09, Medium. The broad catch in the fetcher (departure on F-05)

`src/hft_crypto/data/fetch.py:130`.

A programming error inside the opener comes out as `FetchError: public.bybit.com: a bug in our own code`, after three attempts with
backoff, as though the host had failed. The network guard's `AssertionError` is turned into a `FetchError` the same way. See section 4.

**Fix:** catch `(OSError, EOFError, ValueError, http.client.HTTPException)`, and narrow the rule in `test_safety.py` to refuse the use of
connections, not the import of an exception class.

### N-18, Medium. Failing newest files use up the budget, and older days are never reached

`src/hft_crypto/data/ingest.py:237` sorts newest first, and `:702-709` retries any failed task whose wait is over. `_retry_at` at `:241-243` caps the wait at 24 hours, so on a daily job a
failed file is due again on every run.

I ran seven days of files with a budget counted in delivered files, one run per day:

| Files | Budget per run | Result |
|---|---|---|
| Errors in two days, retries due every run | 3 | Finished in 11 runs, verdicts right |
| Newest three days always fail, 6 files | 3 | **After 20 runs, verdicts for days 5, 6 and 7 only. Days 1 to 4 have none** |
| The same | 2 | **After 12 runs, a verdict for day 7 only** |

This is F-05's "blocks catch-up on every later run" in a milder form. It needs failing files that cost more than a run's budget, which is 50 minutes in the daily job. A bad month at the newest end could do it, and so could a few of Kraken's
large quarterly files. I did not measure real download times, so how close that is remains unknown. The run says `partial` with a `not_started` count, but by reading `ingest.py:638` and `:696`, no alert names it, so the watchdog would not report it.

**Fix:** give tasks never tried first call on the budget, or cap the share of a run that retries may use, as `max_book_days_per_run` does for books. Add an alert when older days are left unstarted for several runs. A test needs this same shape with a budget.

### Low

| ID | Where | Scenario and wrong output | Fix |
|---|---|---|---|
| N-10 | `src/hft_crypto/data/book_replay.py:192` | `replay_zip` omits `zlib.error`. A corrupt book zip gives `validate-book` a `zlib.error` traceback rather than a malformed result, in 16 of 400 fuzzed files. The fixes file says three readers were fixed, and this is the fourth | Add `zlib.error` |
| N-11 | `src/hft_crypto/data/parsers.py:352` | Klines `quote_volume` and `taker_buy_quote_volume` accept `NaN` and `inf` (4 fuzz cases each). No code reads either column today | Add both to the list, or drop them |
| N-12 | `src/hft_crypto/data/reader.py:74,100,110,116,129` | An empty read returns `pl.DataFrame()` with no columns, so a mistyped symbol or a first day raises `ColumnNotFoundError` in the consumer. Loud, but far from the cause | Return the schema, or raise |
| N-13 | `src/hft_crypto/data/reader.py:62-63` | The part stem is compared to `since` as text. A monthly part `2026-03` with `since=2026-03-15` is dropped, giving 0 rows and not 2, silently. No caller yet | Compare by period |
| N-14 | `src/hft_crypto/cli.py:67-73` | A dry run on an existing empty folder writes `catalog/catalog.sqlite`, exit 0. Only a missing root is refused | Refuse a root with no catalog in the commands that only look |
| N-15 | `src/hft_crypto/data/poll.py:598` | Ids [100,102,101,103] in one page: 101 is dropped and counted as repeated. Its volume is lost, and gap (100,102) flags the minutes, so it is not silent. Whether Kraken can do this is `UNVERIFIED` | Sort a page by id, or fail it |
| N-16 | `.github/scripts/publish_results.sh:43` | The `case` glob crosses `/`, so `run_log/sub/x.jsonl`, `ledger/sub/x.json` and `decisions/sub/x.json` are accepted. Harmless so far, and wider than the header of the script says | Refuse a further `/` |
| N-17 | `continuity = "none"` path, `configs/pipeline.toml:58` | A 10-minute hole with no candle file: flagged 10, `check_status=pass`, catalog gaps 0, raw deleted. And three quiet minutes a day: every day `complete=False`, so the benchmark is `None`. Loud, but it means no benchmark from any such source. See section 10 | A G1 ruling. Worth deciding before Kraken's file format is known |

## 4. The departures

| Finding | Accepted? | Why |
|---|---|---|
| F-04: an unconfirmed carry warns on a dataset's first day, and beside a broken neighbour | **Yes** | A first day has no earlier file, so it cannot be proved. It stays out of the benchmark, its raw is kept and its first bar is flagged. An hour lost on a first day still fails (K2). I also ran the neighbour: day 2 fails and day 3 warns, and after a good file is published both become `pass`, the flag clears and no exclusion stays open |
| F-05: `_attempt` catches `Exception` | **Yes, with conditions** | Containment is the right result. The stated reason is weak, because a test rule the developer controls is not a reason to hide programming errors as host failures. N-09 |
| F-17: documents said 8 GB | **Closed** | `38d5907` changed `05_DATA_LIFECYCLE.md` and `08_DATA_CENTER.md` to 4 GB. "Not run on GitHub" remains, see section 7 |
| F-21: one day's emission can pass the budget | **Yes** | The cost is small. The stated reason is overstated, because a stop inside a poll day would heal rather than repeat F-06, but it does not need changing |
| F-23: `provisional` accepted for raw deletion | **No, overruled** | The steward's reasoning holds when run (section 8). Open as work for `developer` |
| F-10: `HFT_CONFIG_DIR` still selects a file | **Yes** | That file gets every check, and I ran the routes through it |
| F-14: the link test skips here | **Yes** | My junction probe reached the check and was refused. I did not confirm the skip is gone on Linux, only that CI passed as reported |

## 5. Does anything get past `tests/conftest.py`?

**Yes, several routes do. The suite as it stands used none of them, by measurement.**

### What the suite really did

I ran the whole suite with a Python audit hook loaded before any test, which fires inside the C functions, so no patch or fixture
scope hides anything from it.

| Event | Count | Where |
|---|---|---|
| `socket.connect`, `socket.getaddrinfo`, `socket.gethostbyname`, `socket.sendto`, `socket.bind` | 0 each | Nowhere |
| `http.client.connect` | 3 | All in `test_the_guard_below_every_http_library_is_on`, stopped before a socket |
| `urllib.Request` | 55 | All in `tests/data/test_source_switches.py`, none reached a socket |
| `subprocess.Popen` | 185 | git 135, bash 44, `cmd` for `mklink` 5, python 1. None names a remote |

The one python child is `test_a_hard_process_kill_leaves_no_partition_that_looks_complete`. Events outside any test: none, which covers
collection and session setup.

The hook cannot see inside a child. So I ran the four test files that start children (`tests/test_workflows.py`, and `test_health.py`, `test_safety.py` and
`test_foundation.py` under `tests/data/`) with `curl`, `wget`, `gh`, `ssh`, `nc` and `scp` shadowed by loggers placed behind any stub a test sets up, with
`GIT_ALLOW_PROTOCOL=file` and a dead proxy. **151 passed, 2 skipped, and 0 calls reached a real network tool.** A git remote over a network would have been refused and
failed its test, and none did. This shows nothing about a raw socket opened by a child, but the only python child is the one named above.

### What the guard would miss

I copied `conftest.py` byte for byte and tried each route against a loopback server.

| Route | Result |
|---|---|
| `socket.socket.connect`, `urlopen`, `socket.getaddrinfo` in a test | Refused |
| Module-level code at collection | **Got through** |
| Session, module and class-scoped fixtures | **Got through** |
| `_socket.socket.connect`, the base class | **Got through** |
| `socket.sendto`, UDP | **Got through** |
| `socket.gethostbyname`, `gethostbyname_ex` | **Got through** |
| A child python process, by socket and by `urllib` | **Got through** |
| `pl.read_parquet("http://...")`, in Rust | **Got through**, 3 hits on the server |

Three more points:

- `tests/test_synthetic_end_to_end.py` has a module-scoped `run` fixture that runs before the autouse guard. It sets its own refusal of
  `OpenerDirector.open` and `socket.socket.connect`, and not of `getaddrinfo` or `create_connection`.
- **The alarm can be swallowed.** The guard raises `AssertionError`, which `src/hft_crypto/data/fetch.py:130` turns into
  `FetchError: public.bybit.com: a test tried to use the network`. A test expecting a `FetchError` goes green. The guard's own test,
  `tests/data/test_source_switches.py:360`, expects exactly that. The catches at `ingest.py:519,718` would swallow it too.
- Neither `src` nor `tests` passes a URL to a polars reader, by `git grep`: `atomic.py:120` and `parsers.py:129` read from `BytesIO`.

### A stronger guard, tried

I wrote this as a probe in a temporary directory and ran it against the same routes: `sys.addaudithook` at conftest import, refusing
`socket.connect`, `sendto`, `sendmsg`, `getaddrinfo`, `gethostbyname` and `gethostbyaddr`, raising a class derived from `BaseException`. Plus an
environment with a dead proxy and `GIT_ALLOW_PROTOCOL=file`.

| Route | Result with the stronger guard |
|---|---|
| Module level, session fixture, plain connect, `_socket` base class, `sendto`, `gethostbyname`, `getaddrinfo` | All refused |
| Production code's `except Exception` | Does not swallow it: `HttpFetcher` lets the alarm through |
| Child through `urllib` | Stopped by the dead proxy |
| `git ls-remote https://...` | `fatal: transport 'https' not allowed` |
| A raw socket in a child | **Still connects** |
| Rust inside polars | Below the hook, so still open. Not retried |

**Recommendation for `developer`:** adopt that, since the suite makes no socket call at all and needs no allow-list. For the two gaps left:

1. Add an audit check on `subprocess.Popen` that allows only git, bash, `cmd /c mklink` and `sys.executable`.
2. Set `PYTHONPATH` for children to a `sitecustomize.py` that installs the same hook.
3. Add a source scan refusing a URL passed to any polars `read_` or `scan_` call.

## 6. How much the developer's mutation check proves

I re-ran both mutants that survived the first review. **Both are now killed**: the redirect bug by
`test_a_redirect_off_the_list_is_refused_before_anything_is_asked_of_it`, and `keep="first"` by
`test_a_replayed_page_after_a_crash_keeps_the_first_receipt`. The IRREPLACEABLE term, which the first review called equivalent, was removed from the
code.

I then put 94 bugs of my own choosing in the fixed areas, each in its own copy, running whole test files first and a wider second stage for those
that lived. The clean copy passes, and I confirmed the package under test was the copy. **82 killed, 12 survived.**

| Survivor | Why it lives | Does the code work anyway? |
|---|---|---|
| `zlib.error` removed from the gzip reader | The corrupt-gzip test does not produce a `zlib.error` | Yes, by reading. The task catch would contain it |
| No reopen when a day's flow changes | No test of an override reaching a neighbour | Yes, order of arrival gave equal verdicts |
| Carry override removed | No test | Yes, a carry plus a straddle passed by hand |
| Daily excess check removed | No test, and it is the only catch for a truncated official file | Yes, row N4 fails on it alone |
| Live reader filters by `t_dec` | No test tells `t_cut` from `t_dec` there, and all `live_eligible` are false | Not run another way. For `leak-auditor` |
| Fetch takes the whole share and not 75% | The test does not pin the number | Not separately run |
| Bars knowable before the last page | The row's knowable time covers it, and tests use a fixed clock | Probably equivalent |
| A day is final at once | The `passing` filter makes it redundant on tested paths | For `leak-auditor` (DC-15) |
| Report reads any venue | The named test stops at catalog status | Yes, the second check ran by hand (F-12) |
| Publish force push | No test | Yes, the script has none, by reading |
| Publish allows links | The test skips on this machine | Yes, a junction is refused |
| Watchdog ignores a send failure | Text-only tests | **No: this is where N-01 is** |

One more was killed only at the second stage: "open neighbours do not hold a day", by `test_report::test_a_lost_cache_shows_partial_coverage`, which is about something
else.

**Judgement.** The developer's check shows that a named test is sensitive to a bug the writer chose. It is useful for what it says, and the file says so itself: "a
sample of what I chose to break". It says nothing about bugs the writer did not think of. The two rates are close: 5 of 41 (12%) in the developer's first round, and 12 of 94 (13%)
from me, so about one plausible bug in eight in this code has no test that notices. My list was also my own choice, so 13% is a sample too and not a coverage figure. Eleven of the
twelve do not point at wrong behaviour I could find. One does, and it is the worst defect in this report, which is the case for keeping the check while not relying on it.

**Tests to add first:** daily excess, carry override, the live reader's two clocks, and the watchdog's send failure.

## 7. "Not run on GitHub" and "checked on its text": what is really at risk

**What I ran:** `publish_results.sh` on real local git, including a lost race, refusals and a failed lookup. The watchdog's shell block with stubs and a real `curl` on loopback. The coordinator reports
the CI Linux run for `dafe3f2` passed, which covers `ci.yml` and the shell tests inside `test_workflows.py` on GNU tools. It does not run any other workflow.

**What nobody can run here:** expression evaluation, the cache service, `gh cache` on real data, Pages, and Telegram's answers. In order of risk:

| # | Risk | What happens if it is wrong | Noisy? |
|---|---|---|---|
| 1 | `default_branch` on a schedule, N-03 | Nothing is ever published, in a green run | **Silent**, with N-02 |
| 2 | Telegram's real answers, N-01 | Alerts lost or never sent | **Silent** |
| 3 | `gh cache list ... \| while` at `daily-pipeline.yml:191`, with no `shell:` set | The default shell, as I recall it, is `bash -e` with no `pipefail` (`UNVERIFIED`). A failed list means no prune and a green step. The next save overflows a limit with no margin, then GitHub evicts | **Silent** until a lost cache shows as `rebuild` on bars, which is permanent for those first emissions |
| 4 | `live-poll-v1-` restore, cache version match, and "save succeeded" output | Each run starts from an empty cache and reports `cache_lost` | Loud, as a state change |
| 5 | The 60-day rule that disables schedules | The watchdog stops with the job, and nothing watches it. Whether pushes to `results` count as activity is `UNVERIFIED` | Only GitHub's own email |
| 6 | `jq` or `gh` missing on the runner | Goes down the N-02 path | **Silent** until N-02 is fixed |
| 7 | Pages setup, push permissions, shallow fetch | The job fails | Loud |

Pinning, `bash -n`, the `${{ matrix.python }}` route through `env` at `ci.yml:36`, and `uv` version `0.11.24` matching the local tool are all fine as far as a reading goes. They are low risk, since a wrong one fails loudly.

## 8. The steward's rulings against the code

### Code claims

| Claim | Result | What I saw |
|---|---|---|
| Watermarks count raw and quarantine: `ingest.py:710`, `cli.py:200`, `health.py:153`, `retention.py:445` | **Confirmed, run** | Raw and quarantine files at 82% of the quota, with 0.003% in persisted zones, give level `stop_backfill` at 82.003%, and `held_by_watermark` is 1. Health shows 82.003% used. Also at `poll.py:778` and `synthetic.py:580`. At `health.py:153` the sum is computed at `:142` and passed on at `:153` |
| A checksum failure leaves no catalog row: `ingest.py:317` | **Confirmed, run** | No file row, the file is in quarantine, the task holds `last_error`, and that is `None` after a later success |
| `emitted_hash` covers `knowable_time` and `emission`, so a rebuild can never match: `poll.py:468` | **Confirmed, run, with one precision** | Equal only for the same rows, same clock and first emission. A rebuild differs, and so does a later clock, while all price and volume columns are equal. So it also differs between two first emissions at different clocks |
| `needs_derive` is false for a missing bar part whose trades were deleted: `derive.py:404` | **Confirmed, run** | `False`. The next run plans 0, downloads 0, reopens 1, the bar stays missing, the derive task stays pending, the archive task says done |
| Cache saves are not limited to the default branch: `daily-pipeline.yml:120`, `live-poll.yml:83` | **Confirmed on text** | `if: always() && steps.restore.outcome == 'success'`. `test_only_the_default_branch_prunes_and_publishes` does not cover save |

I spot-checked the ruling's other citations and they land right: `retention.py:75,190,210,228`, `poll.py:297`, `fetch.py:147`, `ingest.py:304,436,627`, `parsers.py:394`, `derive.py:156,265,319,327-334`, `pipeline.toml:75`, `watchdog.yml:43`.
Line 394 of `parsers.py` is the `if`, and the warning text is at `:395`.

### Ruling 6: `provisional` overruled

The reasoning holds when run.

1. **Fill count `warn` while the next file is missing.** The day reads `provisional` and raw is deleted, then it settles on `warn` with 0 downloads. Raw that the rule would keep is already gone.
2. **No candle file, or no tolerance.** It stays `provisional` with no check at all, and raw goes.
3. **`retention.py:210`** checks only that a URL is present. A reading.

My row A2 is a concrete case the ruling does not name: a day that later **fails** had already lost its raw, because it was `provisional` when the sweep ran. It still fails correctly, and it recovers by download.

**One addition for R6.1.** With `pass` only, `descendants_of` runs through trades to the neighbours' bars, because the bars of D-1 and D+1 name D's trades as parents. So raw for D waits on three days. Run with one `warn` day, the result was
day 1 `pass` raw gone, day 2 `warn` kept, day 3 `pass` kept, day 4 `pass` kept, day 5 `provisional` kept. Day 1's raw went only because it was deleted before day 2's rebuild added the parent, so the result depends on order. The ruling's "a few
files for about two more days" holds beside clean days, not beside a `warn` or `fail` day, where raw stays until that day resolves. That is safe, but **the test for R6.2 should state what is wanted**, rather than pick up today's behaviour.

## 9. Smaller points

- **Search caveat.** In the first review, one search of `src` returned partial results. I noticed and repeated it with `git grep`. No conclusion of the first review depended on the partial result. This recheck used `git grep` and direct reads for `src/hft_crypto/data/`.
- **F-22 count.** The row says "Four clauses need a ruling", and its table has six: five for `data-steward` and G1 for `project-manager`. A slip with no effect on code. The rulings answer the five.
- **"Frozen under decision D-18", `configs/pipeline.toml:98`.** No code reads the comment, so it has no correctness effect. It matters only for N-05, as the comment's trial rule decides how that value may change.
- **F-15, first publish.** On a new log, the awk's `NR==FNR` holds for the incoming file, so a line repeated within it is kept. Nothing is lost. Not a finding.
- **Fault route.** In the catch-up probe with a very small budget and real errors, my loop stopped at its limit of 60 runs and not at completion, with verdicts matching after settling. I traced it. My clock charged a second per read, and a failed task waiting for its retry only reads the clock, so that stall came from my probe. With a clock charging only delivered files, the route finished in 5 runs at one fixed time. The same trace found N-18, which is real.

## 10. What `D-22` means for this code

From reading the code and `docs/03`, not from running anything. No source is enabled, and nothing was requested.

| Point | In the code now | Consequence |
|---|---|---|
| No Kraken dataset | `configs/pipeline.toml` has only the poll for Kraken | The steward's R9.1 stands. The daily job selects nothing from Kraken |
| Bulk files are quarterly | `granularity` is `day` or `month` only, at `config.py:336` | Needs a new value and a new planner path |
| File size | `max_download_bytes` is 2e9 at `pipeline.toml:75`, and `docs/03` puts parts near 2 GB | Borderline. Measure |
| Archive shape | `read_zip_member` reads one member | A quarterly archive with many members needs a new reader |
| Hosts | `ALLOWED_HOSTS` at `fetch.py:22` holds `api.kraken.com` and nothing for bulk files or for Bitstamp | Each needs a reviewed addition |
| **REST catch-up for research** | `docs/03` fills the gap after the last quarter with REST. The poll writes `trades_live`, and `_refuse_rows_from_another_path` at `derive.py:130` refuses rows received after their stamp plus the allowance as archive bars | **There is no path today from REST rows to research bars, by design.** This is a planning point, and `leak-auditor` should rule on any new one |
| Trade ids in the files | `docs/03` does not say whether time and sales files carry one. `UNVERIFIED` | With no id, `continuity = "none"` applies, so N-17: every quiet minute is a gap, and a day with one is `complete=False`. The benchmark is `None` under the present rule, unless the 1,440-minute completeness rule changes |
| Taker side | `b` and `s` are not stated to be the taker's side. `UNVERIFIED` | `docs/03` already requires the test. All flow features rest on it |
| Official candles | OHLCVT files exist. The rule was shaped on Binance's aggregates, and the comment at `pipeline.toml:98` says so | Recheck under `D-18`. N-05's tolerance and `boundary_window_ms` have to be measured there |
| Bitstamp | No adapter, no host, and history would come from a vendor | A new dataset and a new reconciliation question, if the fallback is used |

## 11. For `leak-auditor`

I noticed no new leak. Three things for that audit:

- The mutant "live reader filters by `t_dec`" survives. No test tells the two clocks apart in `live_dataset`.
- The mutant "a day is final at once" survives. DC-15's rule rests on `passing` on tested paths.
- A `gap` flag on an empty minute in IDEAL can rest on a later row. The developer disclosed this, and it is still open.

## 12. Commands and their output

Run on Windows under Git Bash, Python 3.12, from the repository root. Probes are in a temporary directory outside the repository, and none is committed.

```text
$ .venv/Scripts/python.exe -m pytest -q -p <audit plugin>
832 passed, 2 skipped in 885.53s
SKIPPED tests/data/test_foundation.py:164   file symlink privilege
SKIPPED tests/test_workflows.py:337         file symlink privilege

$ .venv/Scripts/python.exe -m ruff check --no-cache src tests
All checks passed!
$ .venv/Scripts/python.exe -m ruff format --no-cache --check src tests
50 files already formatted
$ python -m mypy src                        (mypy 2.4.1, from a virtual environment on a short path)
Success: no issues found in 31 source files
```

`mypy` from `.venv` does not start on this machine, with `DLL load failed ... The filename or extension is too long`. That is the machine's path length, and not a fault in the code.

| Probe | Checks | Deviations | Which were real |
|---|---|---|---|
| Retention | 43 | 2 | N-14 |
| Reconciliation through `run_ingest` | 34 | 3 | N-05 (two checks on row N1), A2 as the F-23 case |
| Poll | 31 | 3 | N-15. The other two were my own wrong expectations, explained in the probe notes |
| REST, sources, fuzz, reader | 69 | 9 | N-04, N-07, N-08, N-10 to N-13, N-17. The rest were probe artefacts |
| Steward's claims | 13 | 1 | Ruling 6, not a defect |
| Watchdog | 16 | 5 | N-01, N-02 |
| Publish, bundle (F-14 section finished, and a time limit cut what came after, which the next row reran) | Not counted | 0 | N-16 noted |
| Publish, append-only and failed lookup | 10 | 0 | None |
| F-06, F-12, F-21, HTTP, carry, no sequence, F-23 | 21 | 2 | N-10, N-17 |
| Neighbour recovery, poll crash | 3 | 0 | None |
| Budget traced run by run, on a clock charging only delivered files | 4 cases | 2 not finished | N-18 |
| Stronger guard | 5 tests pass | n/a | Section 5 |
| Mutation | 94 bugs | 12 alive | Section 6 |

**Catch-up routes and crash injection:** seven routes (one run at the end, runs missed, cache lost, stale cache restored, budget across runs, curated lost, one bars file lost) compared
with the daily route, on a clean market where every day reaches `pass` and on a market with errors in two days.

```text
--- crash: persistence calls per run: [25, 37, 37]
   crash points tried: 198. Recovery differs from a run that never crashed: 0
--- 29 checks, 0 deviations
```

Before this I ran the same probe with candle counts that made every day `warn`: also 0 deviations, with 186 crash points. I reran it because that version never reached `pass`.

**Child processes under shadowed tools:**

```text
$ PATH=<loggers>:$PATH GIT_ALLOW_PROTOCOL=file HTTPS_PROXY=<dead> python -m pytest -q tests/test_workflows.py \
      tests/data/test_health.py tests/data/test_safety.py tests/data/test_foundation.py
151 passed, 2 skipped in 201.17s (0:03:21)
calls that reached a real network tool: 0
```

## 13. What I did not check

- **Anything on GitHub.** See section 7. No workflow ran here. I did not re-read every line of each workflow after the fix.
- **Real data from any source.** Every format and API assumption is still untested. `docs/03`'s statements on Kraken are read and not verified.
- **Real Telegram.** A loopback server gave the status codes, and the answer bodies are assumed.
- **Linux for the two skipped tests.** The file symlink tests skip here. The coordinator reports CI passed.
- **Three-way line coverage of F-22.** I relied on the named tests for `compare_live_with_archive`, the lateness log and the 95% watermark. I did not attack them.
- **Whether the code the rulings ask for is right,** since it is not written.
- **A review of `AGENTS.md`, `.codex/` or `docs/02_features/GATE_SPEC.md`,** which are outside this work.

## 14. Addition, 2026-11-05: N-01 to N-18 at `cf1880f`

Against the round of 2026-11-05 in [the developer's answer](data_center_fixes_2026-11-04.md), treated as claims. Run from a frozen copy of `cf1880f`, because the working tree was changing. The reported `1657 passed, 2 skipped` is the developer's, and I did not repeat the full suite.

### Verdict: `PASS WITH CONDITIONS`

F-18 is closed, and with it the reason for the `FAIL` in section 1. Every N finding but N-17 is fixed in what I could run. The conditions are few:

1. **N-03 can only be proved on GitHub.** Look at the first scheduled run by hand.
2. **N-17 still needs its G1 ruling.** It does not touch the candle stage, where a missing row is a gap.
3. **N-05's value is for `project-manager` to record,** as a trial or not, and 5 bp is still a placeholder until measured.

### Per finding

| ID | Verdict | What I ran |
|---|---|---|
| N-01 | `PASS` | The real `watchdog.py` and its real `http_call`, against a loopback server. 403, 429, 500, 200 with `ok` false, and 200 not JSON: exit 1, no digest kept, the next run sends again, then stays quiet. One owner's failure is theirs alone, and only they are sent again. The token is in no note |
| N-02 | `PASS` | 401, 500, corrupt JSON, a list, no `generated_at`, no alerts list: an alert each time. A true 404 is a note, then an alert past the age limit, or at once past `WATCHDOG_EXPECT_RESULT_AFTER`, which someone must set. While a result is stale, the age in the text means a new alert on each of the two daily runs, which is bounded and acceptable |
| N-03 | `PASS WITH CONDITIONS` | On text only: publish, deploy, prune and save all read `github.event_name == 'schedule' \|\| ...`, and the prune takes the branch from `REF_NAME`. Not provable here. `gh cache list ... \| while` still has no `pipefail`, so a failed list is still a quiet no-op, and that default is `UNVERIFIED` |
| N-04 | `PASS` | A stray part name: run `ok`, row `ok`. Named tests ran |
| N-05 | `PASS WITH CONDITIONS` | Value 0.0005. My reconcile probe now gives 34 checks and 0 deviations: a last price +1.9% fails, is excluded, and keeps its raw |
| N-06 | `PASS WITH CONDITIONS` | My routes against the new guard, on loopback. Refused: module level, session and module fixtures, `connect`, `connect_ex`, the `_socket` base class, `sendto`, both `gethostbyname` forms, `getaddrinfo`, `urlopen`, a thread, a Python child, and `curl`, `powershell` and `ssh` as children. `git` to a remote: `transport 'https' not allowed`. **Two left, both Low:** a Python child started with `-I` ignores `PYTHONPATH` and connected, and polars stays below the hook, with only the source scan covering it. Nothing in the suite does either, by the scan and by my earlier tally |
| N-07 | `PASS` | The same case now exits 2: "the live root's catalog holds generated data" |
| N-08 | `PASS` | `candles` from `kraken`, `bybit`, a disabled `binance` and an unknown name: all `SourceNotApproved`, with nothing read |
| N-09 | `PASS` | Named tests ran, and the fix is narrow |
| N-10 | `PASS` | 400 fuzzed book files: only `ValidationError` or accepted, and no `zlib.error` |
| N-11 | `PASS` | 2,000 fuzzed files: no accepted frame holds a non-finite number |
| N-12 | `PASS` | Named test read and run. `live_dataset` on an empty read still has no columns, a stated departure I accept since each dataset differs |
| N-13 | `PASS` | Named test read and run: a mid-month `since` gives 2 rows, a later month none |
| N-14 | `PASS` | A dry run on an existing empty folder: exit 2, nothing written |
| N-15 | `PASS` | Ids [100,102,101,103]: stored [100,101,102,103], 0 repeated |
| N-16 | `PASS` | `run_log/sub/x.jsonl`, `ledger/sub/x.json`, `decisions/sub/x.json`: exit 1, nothing on the branch |
| N-17 | Open | Not done, as stated. Better than before: a 10-minute hole with no sequence and no candles now reads `unreconciled`, with its raw kept, and it is no longer `pass`. Catalog gaps still 0 |
| N-18 | `PASS` | My case again, 7 days, budget 3 files. Retries due every run: finished in 6 runs, from 11. Newest three days always failing: 10 tasks done by run 5, where before no older day was ever reached. The alert after three runs is in a named test I ran |

### Changes the fixes file lists as outside its scope

| File | What I checked | Result |
|---|---|---|
| `config.py` | `LAST_OPENED_DATE` is a constant, `APPROVED_ROUTES` opens one host for one source, and `ARCHIVE_ONLY_SOURCES` holds `binance`. Named route tests ran | Holds. The route accepts any USD-M perpetual symbol, as disclosed, and `[universe]` is what limits it |
| `synthetic.py` | The `official_1m` path, and `candle_allowance_ms = 250` for generated data only. I ran the engine's edge separately: with `knowable = close + 10 s` and a delay of 10 s, a candle is known at its decision | Holds. The 250 ms never reaches real data. A real value of 10 s sits exactly on the `<=` edge, and it passes |
| `reports/benchmark.py` | `compute_span_stats` by hand: total 8.9%, Sharpe 5.515131 on 365 days, drawdown -10%. Read for holes: a return across a hole is not a one-day return | Holds |
| `reports/site.py` | The added lines are escaped text on the page | Holds |
| Tests a ruling replaced | Read: `test_bad_klines_are_refused` loses `high is below`, as ruling 7 asks. The R6.1 retention test is stricter. The `test_safety.py` rule allows exactly `HTTPException` from `http.client`, in `fetch.py` only. `test_retention` gains checks | None was weakened beyond what its ruling states, on those I read. I did not read all of `test_report.py` and `test_ingest.py`'s rewritten tests |

### Commands

```text
$ python -m pytest -q -x tests/test_workflows.py tests/data/test_source_switches.py tests/data/test_safety.py ...
no failure in the first two files. It stopped in test_safety.py at test_generated_output_is_ignored_by_git, which needs a git checkout, and my frozen copy is not one
$ python -m pytest -q tests/data/test_safety.py tests/data/test_reader.py tests/data/test_parsers.py tests/data/test_book_replay.py tests/data/test_ingest.py -k "<those files, and the N-04 and N-18 tests>"
156 passed, 3 skipped, 76 deselected in 51.18s
$ ruff check src tests
Found 4 errors. All E501, line too long, in tests/child_guard/sitecustomize.py lines 3, 5, 6 and 10
$ ruff format --check src tests
99 files already formatted
$ mypy src     (from a short-path environment, because mypy in .venv does not start on this machine's long path)
Success: no issues found in 63 source files
```

The four E501 lines are not a correctness matter in themselves, but `.github/workflows/ci.yml:40` runs `ruff check .`, so CI fails on them at this commit. Run from the frozen copy with its own `pyproject.toml`.

**Not checked:** the full suite, anything on GitHub, real data, and the steward's later items, which the fixes file leaves open.
