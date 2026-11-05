# Binance Vision: coverage, sizes and the `D-18` read record

Date: 2026-11-05. Owner: `data-steward`. For `docs/decisions/FOLD_PLAN_2026-11-05.md` sections 1, 4 and 7, and items 0, 2
and 5a of the leak recheck (`docs/reviews/leak/data_center_recheck_2026-11-04.md`, section 10).

The brief named commit `1e634fc`. The branch reached `389fcee` while I worked, with the plan unchanged, and `src/` and
`configs/` hold uncommitted work by others. So statements about code describe that working copy on this date.

Derived from Binance Vision data, CC BY-NC-SA 4.0. Not associated with or endorsed by Binance.

**No dataset file was fetched, and no price, return, flow or outcome was opened.** Everything here is a listing, a size, a
count, a name, a date or a pass or fail flag, which section 3 of the plan says is not a read. Sizes are decimal
(1 GB = 10^9 bytes). Anything not measured is marked `UNVERIFIED`.

## Answers

| Question | Answer |
|---|---|
| Does `T_start` of 2020-01-01 hold? | **Yes, on file coverage.** All three series have a 2020-01 file on both symbols. The quarter check in plan section 2 needs file contents and has not run |
| Any month missing in the first span? | **None.** 48 of 48 for each series on each symbol, each with a checksum sidecar |
| Stage one size | **179.22 MB, 384 files** |
| Stage two on the first span | **46.37 GB zipped.** Bars only fits the 4 GB cache. The code as it stands does not, because it keeps curated trades |
| `D-18` dates | **30 dates, 2026-10-05 to 2026-11-03, plus the funding month 2026-10.** None is in a test or locked block |
| Was a report over a stretch produced? | **None found.** No `results` branch, no workflow artifact, no Pages site and no pipeline run on GitHub. The `BLOCKED` condition in plan section 4 is not met on this evidence |
| What stays open | **About 137 MB of the 953 MB cannot be dated** (section 3.2) |
| What must change first | Today's ingest flags do not make a first-span download safe (section 4.3) |
| Where do unopened dates sit? (item 0) | **In their own check-only root** that no reader or report can open, with no bars built there. Only the plan's list leaves it. Declared in section 5, not built |
| Sample days for ruling 7 condition 2 (item 2) | **The 15th of every month of the first span, 48 days,** from the calendar alone. Declared in section 6. The test has not run |

## 1. Coverage

**Method.** The page at `data.binance.vision` is a static shell. Its own script, `list.js`, reads the bucket listing named in
the page's `BUCKET_URL` (`s3-ap-northeast-1.amazonaws.com/data.binance.vision`). I made the same request, with a generic
client name and no personal details. In all: 6 requests for the page, `list.js` and `robots.txt`, 26 listing requests and 4
header requests, the listing and header ones about 4 seconds apart. No rate limit is posted in the terms or on the page,
and `robots.txt` does not exist. Whether a limit is published elsewhere is `UNVERIFIED`.

| Symbol | First 1-minute candle file | First funding rate file | First `aggTrades` file |
|---|---|---|---|
| BTCUSDT | Monthly `BTCUSDT-1m-2020-01`. Daily `BTCUSDT-1m-2019-12-31` | Monthly `BTCUSDT-fundingRate-2020-01` | Monthly `BTCUSDT-aggTrades-2020-01`. Daily `BTCUSDT-aggTrades-2019-12-31` |
| ETHUSDT | Monthly `ETHUSDT-1m-2020-01`. Daily `ETHUSDT-1m-2019-12-31` | Monthly `ETHUSDT-fundingRate-2020-01` | Monthly `ETHUSDT-aggTrades-2020-01`. Daily `ETHUSDT-aggTrades-2019-12-31` |

- **`T_start` of 2020-01-01 holds on file coverage.** The first-span rule that a bar closes after 00:00 needs nothing before
  the 2020-01 file. The contract start dates in the plan stay `UNVERIFIED`, but they no longer matter, because the archive's
  own first file is later than both.
- **First span, monthly:** 48 of 48 for candles, funding and `aggTrades`, on both symbols, none empty, every sidecar present.
- **First span, daily `aggTrades` and daily candles:** 1,461 of 1,461 days on both symbols, none empty, every sidecar present.
- **2020-01 to 2026-09, monthly:** 81 of 81 for each series on each symbol.
- **Not measured:** whether a daily funding series exists, and whether monthly and daily candle files hold the same rows.
- **A file existing does not make a quarter pass.** Plan section 2 needs row counts from inside the files. See section 5.

**Files change after publication.** The listing shows first-span files republished after 2024-03-01, a cutoff I chose. What
changed is `UNVERIFIED`, because the listing does not say.

| Series | Republished on or after 2024-03-01 |
|---|---|
| Monthly candles | 2022-05 on both symbols, on 2024-08-20 |
| Monthly funding | None |
| Monthly `aggTrades`, BTCUSDT | 2020-03, 2021-11, 2023-05, 2023-10. The last two on 2026-10-07 |
| Monthly `aggTrades`, ETHUSDT | 2023-05, on 2026-10-07 |
| Daily `aggTrades` | 48 days on BTCUSDT and 52 on ETHUSDT, mostly 2023-05-01 to 2023-06-19 on 2026-04-16 |

So a second download may not match the first. `RE-DOWNLOADABLE` here does not mean byte-identical. The manifest must pin each
file's checksum and `Last-Modified`, and any later difference goes to quarantine and review.

## 2. Sizes

From the listing. Four files were checked against their `Content-Length` headers, and all four matched exactly. Only totals
are given after 2023-12, and no month-by-month size for closed dates was printed. Sizes are not a read, but monthly trade
file sizes would be a rough proxy for activity, so I kept them out.

| Dataset | First span, BTCUSDT | First span, ETHUSDT | First span, both | 2020-01 to 2026-09, both |
|---|---|---|---|---|
| Monthly 1-minute candles | 90.55 MB | 88.57 MB | **179.12 MB** | 303.52 MB |
| Daily 1-minute candles | 91.69 MB | 89.73 MB | **181.43 MB** | Not listed. Later dates were not requested |
| Monthly funding | 0.043 MB | 0.043 MB | **0.085 MB** | 0.144 MB |
| Monthly `aggTrades` | 25.69 GB | 20.16 GB | **45.85 GB** | **86.73 GB** |
| Daily `aggTrades` | 26.04 GB | 20.33 GB | **46.37 GB** | Not listed. Later dates were not requested |

The whole-range monthly totals by symbol are: candles 151.82 and 151.69 MB, funding 0.072 and 0.072 MB, `aggTrades` 44.48
and 42.25 GB.

### 2.1 Stage two against the 4 GB cache

Raw does not fit: 46.37 GB is about 11.6 times the budget, and about 251 GB unzipped. That uses a ratio of 5.42 from one zip
header (BTCUSDT `aggTrades`, 2026-11-03), so the unzipped figure is `UNVERIFIED` for older dates.

Keeping bars only, these are extrapolations, so all are `UNVERIFIED`. The per-day figures are measured sizes from the
2026-10 and 2026-11 catalog rows in section 3, built by code that has changed since. Bars have a fixed row count per day, so
they should carry over better than the trade figures.

| Kept between runs | First span | 2020-01 to 2026-09 | Basis |
|---|---|---|---|
| Bars, all 8 timeframes | 399 MB | 673 MB | 136,571 bytes per symbol-day |
| Curated official candles | 185 MB | 312 MB | 63,301 bytes per symbol-day |
| Trade sample days, one a month (lifecycle section 3) | 1,075 MB | 2,011 MB | Mean zipped day, times 0.705 curated to zip, times months |
| Catalog | 59 MB | 100 MB | 20,275 bytes per symbol-day |
| **Total** | **1.72 GB, 43% of budget** | **3.10 GB, 77% of budget** | |
| Total without sample days | 0.64 GB, 16% | 1.09 GB, 27% | |

- **Bars only fits the first span.** The whole range passes the 70% warning and sits close to the 80% backfill stop, so normal
  error could stop it. Sample days are 65% of that total. A sample day per quarter would save about 1.3 GB, which I would
  propose only if stage two goes past the first span.
- **The code as it stands does not fit.** Curated trades stay in the cache, since `curated-trades-window` is not reviewed and
  `retention` is a dry run. That is about 22.8 MB per day, so the 80% stop arrives after about 140 days of backfill. Keeping
  them all would take 32.7 GB on the first span. Stage two needs a reviewed rule that removes curated trades once a day's
  bars pass, exempting sample days.

### 2.2 Stage two against a runner's disk

GitHub lists 14 GB of SSD for a standard public Linux runner. Free space after the system and a restored cache is
`UNVERIFIED`.

- **Daily files fit.** The largest first-span day is 2021-05-19: 108.69 MB on BTCUSDT and 104.21 MB on ETHUSDT. Together that is
  about 1.15 GB unzipped, and a peak of about 1.67 GB if unzipped to disk and held with two days of curated trades, since the
  midnight check needs a neighbour. All `UNVERIFIED` beyond the zip sizes.
- **Monthly trade files do not.** The largest is 1.39 GB zipped and about 7.5 GB unzipped (`UNVERIFIED`), over half the disk and
  close to the fetch limit of 8 GB in `configs/pipeline.toml`. **Stage two uses daily files, one day at a time.**

### 2.3 Expected time, all `UNVERIFIED`

The only rate measured is one local run: 803.30 MB in 460 seconds, 1.74 MB/s, including building curated files and bars. A
runner may differ a lot.

| Job | Requests | At that rate, plus a 2-second gap per request | In 60-minute daily runs |
|---|---|---|---|
| Stage one | 384 | About 15 minutes | 1 |
| Stage two, first span, daily files | 5,844 | About 10.6 hours | About 11 |
| Stage two, 2020-01 to 2026-09 | 9,860 | About 19.3 hours | About 20 |

## 3. The `D-18` read record

Names and dates only, from zip member names, on-disk file names and catalog columns. I did not select the catalog's free-text
columns (`check_detail`, `detail`, `summary`, `data_manifest`, `last_error`). The test blocks end on 2025-09-30 and the locked
block on 2026-09-30.

| Source | Dataset | Dates | Size | Falls in |
|---|---|---|---|---|
| First look, `dl_sample` | `BTCUSDT-1m`, `ETHUSDT-1m`, `BTCUSDT-aggTrades`, `BTCUSDT-bookDepth` | 2026-11-03 | 12.66 MB with the row below | After the locked block |
| First look, `dl_sample` | `BTCUSDT-fundingRate` | **Month 2026-10.** This closes the plan's `UNVERIFIED` | Included above | After the locked block |
| Run `72616ea30cda4c82`, 2026-11-04 17:59Z to 18:07Z | `klines`, `aggTrades`, both symbols | 2026-10-05 to 2026-11-03, without 2026-10-28 | 803.30 MB with the row below | After the locked block |
| Same run | `bookDepth`, both symbols | 2026-10-05 to 2026-11-03, without 2026-10-08 | Included above | After the locked block |
| Same run, still on disk | `candles_official`, `trades`, `book_depth`, `bars_1m` to `bars_1d`, both symbols | Same range | 578.73 MB, the whole folder | After the locked block |

The two Bybit files in `dl_sample` are another venue, dated 2026-11-03 where named, and are outside the Binance count. The run's
`downloaded_bytes`, the catalog's raw rows and the 174 deletion lines agree exactly. Each raw file covers one day.

### 3.1 Result

**No day in a test block or the locked block appears in any surviving record.** All 30 dates fall in 2026-Q4, a later quarter
under plan section 3.

**No report over a stretch was found, and no benchmark from these runs exists on GitHub** (leak recheck item 5a and section
13.4). From `git` and the repository's public Actions API, names and dates only:

| Place | What is there |
|---|---|
| `results` branch | **Does not exist,** locally or on the remote. The remote has only `main` and `pipeline/first-data-run` |
| Any commit, any branch | No path under `results/` or `run_log/`, no `status.json`, no benchmark output, and no zip, Parquet, CSV, gzip, SQLite, JSONL or HTML file |
| Workflow artifacts | **None.** The API lists 0 |
| Pages | None. The API returns 404 |
| Workflow runs | 16, from 2026-11-04 17:06Z to 2026-11-05 13:42Z: 15 `CI` and 1 `Source check`, all on push. **The daily pipeline never ran.** `main` holds no workflow file, so no schedule could fire. All `D-18` fetching was local |
| Actions cache | Listing it needs a token, so `UNVERIFIED`. With no pipeline run, nothing would have saved market data there |
| The run's local folder | No results. The catalog's only run is `kind = ingest`, `published = 0`, last written when the run ended. A report records its own run in the catalog, so none ran over this root |
| Report outputs elsewhere | A root with no source (`data_kind = NONE`), synthetic roots (`SYNTHETIC`, dates in 2000), tests, and the `D-27` demonstration the plan already lists |

**Limit.** A report made over a root that was later replaced cannot be ruled out, which is the same gap as section 3.2. A deleted
branch or artifact would not show either, and the event list that could show one returned only 5 pushes.

**The closest thing is a check table, not a report.** The catalog holds 58 per-day reconciliation rows over these dates: 56 pass
and 2 fail, both on 2026-10-27. I did not open its `detail` column. `08_DATA_CENTER.md` section 4 records a conclusion drawn from
those runs, so check output reached someone and shaped a rule. Under plan section 3 that is a read of those days, whatever else
it was. It touches no block. `project-manager` decides, but I do not read it as the plan's `BLOCKED` case.

### 3.2 The part I could not date

803.30 MB and 12.66 MB make **815.96 MB, about 137 MB short of the 953 MB in `D-18`.** I searched the 420 catalogs in the session
scratch folder, the file names there, six other session folders beside it (empty) and git on all branches. No record accounts for
the difference.

- **It may be an earlier run whose root was replaced.** The run above started in a folder created seconds before it, and `D-18`
  entered the log at 2026-11-04 20:13Z. That is inference, `UNVERIFIED`.
- **If it ran newest first from the same date,** about 137 MB covers about 5 days, and reaching the locked block would take about
  942 MB. But the code and config of that hour are not in git, and `ingest` takes `--start` and `--end`, so this does not rule out a
  run aimed at older days.
- **Or the figure may simply be counted differently.** That is `UNVERIFIED` too.

Session logs might settle this. I did not search them, because they are outside this brief and can hold market values.

### 3.3 Existence checks and look-alike dates

- **Existence checks (plan section 4).** No file, catalog row or surviving script holds 2022-06-01, 2023-06-01 or 2025-06-01.
  2025-12-01 appears only in the `D-27` demonstration's files. So no copy was kept, but I cannot show that nothing was opened and
  discarded, and this stays `UNVERIFIED`. The Binance days are in the first span, which is open. Bybit's 2025-06-01 is a test-block
  date and its 2025-12-01 is already a `D-27` read day, both on another venue, so `leak-auditor` should note them.
- **Fixture dates.** Test folders hold rows with a `data.binance.vision` URL dated 2026-03-01 to 2026-03-19, inside the locked
  block. They are generated by the test suite. The largest is 13,102 bytes against 25.7 MB for the largest real file in the run
  above. They are not a read, and I name them so nobody counts them as one.

### 3.4 Rows proposed for plan section 4

For `project-manager`. I have not edited the plan.

| Event | Days | What was seen | Where they fall | Treatment |
|---|---|---|---|---|
| First look (`D-18`) | Files dated 2026-11-03, funding month 2026-10 | Data checks | After the locked block | No block touched |
| Pipeline run (`D-18`), measured | 2026-10-05 to 2026-11-03, 30 dates | Data checks, including per-day reconciliation | After the locked block | No block touched. Treated as read, and excluded if those quarters ever join |
| Pipeline runs (`D-18`), about 137 MB | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | No date can be excluded until one is named |

**Local copies are untouched.** Nothing was deleted. `D-29` says they stay unused, so stage one must not read them.

## 4. Stage one download plan

### 4.1 Files

| Item | Pattern |
|---|---|
| Candles | `https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/1m/{SYMBOL}-1m-{YYYY}-{MM}.zip` |
| Candle checksum | The same URL with `.CHECKSUM` added, 89 bytes |
| Funding | `https://data.binance.vision/data/futures/um/monthly/fundingRate/{SYMBOL}/{SYMBOL}-fundingRate-{YYYY}-{MM}.zip` |
| Funding checksum | The same URL with `.CHECKSUM` added, 98 bytes |
| `{SYMBOL}` | `BTCUSDT`, `ETHUSDT` |
| `{YYYY}-{MM}` | 2020-01 to 2023-12 |

**Total: 192 zips and 192 sidecars, 384 requests, 179,223,977 bytes (179.22 MB).** Files are named by open time, so the 2023-12 file
should hold the bar that closes at 24:00 on the last date (rows not opened), and no 2024-01 candle file is needed. No 2024-01
funding file is needed either: FP-07 leaves out any setup that reaches 2024-01-01 00:00, so no trade pays a settlement at that
instant.

### 4.2 Where it goes, and the fetch itself

- **Root:** a new, empty directory named by `DATA_ROOT`, outside the repository. Not an earlier local root (`D-29`). On GitHub that is
  the runner's disk, for one job.
- **Raw:** `raw/archive/binance/klines/{SYMBOL}/date={YYYY}-{MM}-01/{file}` and the same under `fundingRate`, keeping the
  `date=` layout the code already uses for funding's monthly partitions. Class `RE-DOWNLOADABLE`.
- **Curated:** `curated/candles_official/` and `curated/funding/`, in the cache, class `DERIVED`. About 185 MB for candles
  (`UNVERIFIED`, from section 2.1), or 5% of the budget.
- **Order per file:** sidecar, then zip. Check the length against the frozen list and the SHA-256 against the sidecar. A failure goes to
  quarantine, with one retry.
- **Pace:** one connection, at least 2 seconds between requests. Stop on any 403 or 429 rather than retrying around it (terms 7.1 to
  7.3).
- **Manifest per file:** URL, size, checksum, `Last-Modified`, fetch time, code version, and the licence note.
- **Checks leaving the job:** counts and flags only. Expected candles are 2,103,840 per symbol. Expected funding rows are `UNVERIFIED`.

### 4.3 How later dates stay out, and what must change first

**Three guards, all required:**

1. **A frozen list.** The 192 names come from the calendar and are checked against this listing, then saved. The job fetches from that
   list, never from a live listing or a date range ending at today.
2. **A hard ceiling.** The fetcher refuses any partition after 2023-12, using the same constant as the reader's last opened date in
   plan section 3. `developer` builds it, with a test that asks for 2024-01 and is refused.
3. **The source stays off until then.** `sources.binance.enabled` remains `false` until guards 1 and 2 pass review.

**Blocking: today's ingest flags are not a ceiling.** Work is planned newest first. `ingest` takes `--start` and `--end`, but `--end` is
optional and the daily workflow passes neither. `--start` also cannot go below a dataset's `start`, and `binance.klines` and
`binance.fundingRate` start at 2024-01-01. So:

- With today's config, `ingest --end 2023-12-31` plans nothing.
- With `start` moved to 2020-01-01 and no `--end`, it fetches from yesterday backward through the locked and test blocks, and the daily
  workflow then runs `report --published` and publishes. That is FP-01.

One missed flag spends the locked block, which is why guards 1 to 3 are required.

**To settle: monthly or daily candles.** `sources.py` fetches daily candles. Monthly needs a small adapter change and costs 384 requests.
Daily costs 6,036 requests and 181.79 MB with funding and all sidecars, and all 1,461 days are listed. I recommend monthly, given terms
7.2. The test in section 6 must use whichever files the first run reads.

## 5. Where unopened dates sit, and how the coverage check runs (leak recheck item 0)

Declared here, for `developer` to build. Not built and not run. It also answers plan section 2, which needs every quarter counted before
the first outcome, because moving first-span quarters into test is "possible only before the first outcome". A first-span download cannot
do that alone.

**Closed dates never enter `DATA_ROOT`.**

| Root | May hold | Who may open it |
|---|---|---|
| `DATA_ROOT` | Dates to 2023-12-31 only, under the ceiling in 4.3 | `MarketReader`, `report`, bar building |
| `CHECK_ROOT` | Only the files on the check's frozen list | Only the check that owns the list |

```text
CHECK_ROOT/                          new and empty each run, own environment variable
  ROOT_KIND                          says check-only. Reader, report and bar building refuse this root
  raw/archive/binance/klines/<SYMBOL>/date=YYYY-MM-01/<SYMBOL>-1m-YYYY-MM.zip
  raw/archive/binance/klines/<SYMBOL>/date=YYYY-MM-01/<SYMBOL>-1m-YYYY-MM.zip.CHECKSUM
  coverage/coverage_check.json       the only file that leaves
```

- **Placement.** Outside the repository and outside `DATA_ROOT`, and `DATA_ROOT` not inside it. No `curated`, `features`, `results`,
  `ledger` or `decisions` zone, and no bars.
- **Two locks.** The marker makes the reader, `report` and bar building refuse the root. The date guard of item 3a refuses later dates
  anywhere, since a root can lose its marker.
- **On GitHub.** Its own manually started job on the runner's temporary disk, with no cache restore, cache save, artifact upload or publish
  step, so nothing reaches the daily job. The files leave with the runner.
- **Locally.** Deletion rule 5 checks paths against `DATA_ROOT`, so a local run needs this root named as the checked root for its one
  deletion, reviewed first. I prefer the runner.

**How the check runs.**

1. Fetch the frozen list: 2024-01 to 2026-09 candles, 66 zips and 66 sidecars, **124.40 MB**, 132 requests. No funding, since FP-08 treats a
   table of rates as a read and the rule does not need it. No trades at this stage.
2. Check length and SHA-256. Read rows from the zip in memory, with nothing unzipped to disk.
3. Inside the check only, per quarter and symbol, compare rows with the 1-minute grid. A missing row is an unproved empty minute. A zero-trade
   row is a proved one (ruling 7 condition 4). Count trades per hour from the candle's trade count, and run the row checks of condition 5.
4. Apply plan section 2: unproved empty minutes under 1%, and at least 100 trades in each of 90% of hours.
5. Write the output below, and end.

**What may leave**, which is exactly the plan's list and nothing else:

| Field | Type | Allowed by |
|---|---|---|
| `quarter`, `symbol` | Fixed values | Names |
| `files`, `files_checksum_ok`, `rows` | Integer | Plan section 3: counts of files and rows |
| `empty_minutes_unproved`, `empty_minutes_proved` | Integer | Plan sections 2 and 3 |
| `row_checks_pass` | True or false | Plan section 3: row checks that output only a flag |
| `passes` | True or false | Plan sections 2 and 3: pass or fail by quarter |
| `check`, `code_version`, `run_at`, `file_list_sha256` | Fixed format, once per file | Provenance, no market content |

**Never written, logs included:** prices, volumes, taker flow, funding, trade counts, the share of hours that passed, first or last stamps,
anything per hour, day or month, and free text. Plan section 3 counts a log as a read, and Actions logs are public, so errors use fixed codes and
never carry exception text from a row.

**Schema test, for `developer`.** Exact keys and types, and no float anywhere in the output. The tree after a run holds only the paths above. A
planted row error does not reach the log. `MarketReader` and `report` refuse the root, with closed-date files on disk (FP-01).

**Use and order.**

- The output decides coverage and storage only (FP-08). Its result goes in the decision log under plan section 2.
- First-span quarters use the same checker and schema, on the stage one files.
- The rule applies once per bar source (FP-09). Stage two repeats it on trades before that stage's first outcome: 40.88 GB of closed-date monthly
  zips by size, in daily files one at a time, under the same root rules.
- Until this is in, the source and the scheduled report stay off. Merging this branch arms the schedule, because `main` holds no workflow today.

## 6. Sample days for ruling 7 condition 2 (leak recheck item 2)

**Declared now. The test runs later and has not run. No sample-day file was fetched.**

**The days: the 15th of every month from 2020-01 to 2023-12, UTC, on both symbols.** That is 48 days, 2020-01-15, 2020-02-15 and so on to
2023-12-15, with no exception. The day before each (the 14th) is needed for its file's tail only, because the walk's first boundary depends on what
crossed midnight. The 14ths are not tested.

**How they were chosen, from the calendar alone.**

- A fixed day of the month. Every month has a 15th, so there is no exception, no seed and no list to choose from.
- Not day 1. The first of the month is what `[sample_days]`, `D-27` and the existence checks of 2022-06-01 and 2023-06-01 all use.
- Every month, so all 16 quarters are covered and all seven weekdays appear (6 to 9 days each).
- The count comes from the rule. The size below was computed after the days were fixed and changed nothing.

**Checked by script.** All 96 dates are in the first span, so outside every test block. None is a `D-18` date named in section 3, or an existence
check date. The unnamed 137 MB of section 3.2 cannot be checked.

**What I had seen first, disclosed.** Before choosing I had printed first-span file totals, the median and 99th percentile day, the largest day
(2021-05-19) and which first-span files were republished. Those are sizes and dates on the open span. I had seen no price, volume, flow or outcome.
I used none of it. 2023-05-14, 2023-05-15, 2023-06-14 and 2023-06-15 fall in a republish window and stay in. A day picked for being busy would be the
selection FP-08 warns about, so **the sample does not aim at stressed days, and passing says less about them.** Adding any would be a separately
declared and logged choice.

**No replacements.** A day later shown to be touched, or a file that fails its checksum, is dropped and named, and nothing takes its place.

**What the test will need.**

- **Trades:** 192 `aggTrades` zips for the 96 dates and two symbols, 384 requests with sidecars, **3,109 MB zipped,** one day at a time. Leak recheck
  section 14 condition 7 allows this on sample days, first span only.
- **Candles:** the same files the first run reads, so the test covers what the run trusts.
- **Where:** a check-only root as in section 5, so no reader can use these trades. No bars from trades and no curated trades are kept (`D-31`).
- **Output:** a pass or fail flag per symbol and day, and overall. One excess fails it, and then `IDEAL` is not reported and nothing else stops.

**A trap for whoever builds it.** `_walk` in `bars/reconcile.py` absorbs a negative first reading as a carry (`carry = max(0, -running[0])`) and allows
`eps`, from `daily_total_abs`. Used as written, an excess at a day's first boundary, or any excess under `eps`, would pass, yet condition 2 says one
excess falsifies. The carry must be bounded by the previous file's tail. It cannot simply add the whole previous day to the trades side, or the test
can never fail. `leak-auditor` should rule on the exact form before it is built.

**Anchor.** The declaration counts from the commit that adds this file, and this brief does not commit. That commit must come before any sample-day file
is fetched.

## 7. Open items

| Item | For |
|---|---|
| The check-only root and job in section 5, including the narrow route past the ceiling | `project-manager`, `leak-auditor`, then `developer` |
| The exact form of the condition 2 inequality, given the walk's carry and `eps` (section 6) | `leak-auditor`, `developer` |
| The commit that anchors the sample-day declaration, before any such file is fetched | `project-manager` |
| The about 137 MB of `D-18`: ask who ran it, or search session logs, or log it as `UNVERIFIED` | `project-manager` |
| Whether the reconciliation table counts as a read of those days (3.1). The three rows in 3.4 | `project-manager`, `leak-auditor` |
| A fetch ceiling, a frozen list and a first-span order in ingest. Monthly candles, if accepted | `developer`, then `python-reviewer` and `leak-auditor` |
| A reviewed rule for curated trades before stage two (2.1). I own this rule's text | `data-steward`, then review |
| Whether candles in a public repository's Actions cache count as hosting under terms 4.3. Pull request workflows may be able to read a cache (from memory, `UNVERIFIED`). Check before the first save | `project-manager`, owner |
| Measured sizes for `05_DATA_LIFECYCLE.md` section 2 and `08_DATA_CENTER.md` section 8, and `08_DATA_CENTER.md` section 4, which still cites `D-17`. Not edited, since this brief delivers one file | `data-steward` |
