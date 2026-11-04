# Data center and pipeline

How market data gets in, where it lives, how results get out, and how the system stays running. Owned by
`data-steward`. Retention rules are in [the data lifecycle document](05_DATA_LIFECYCLE.md).

## 1. Why market data does not live in git

The system runs on GitHub itself, but git history is the home of the code and the small results, not the data:

- GitHub blocks files over 100 MiB. One day of Bybit `ob200` for BTC is about 228 MB.
- Book data alone is on the order of 150 GB per year for two symbols, and GitHub recommends far smaller
  repositories.
- This repository is public, and redistributing an exchange's data is a separate legal question.

So the data center runs on GitHub's runners and cache, under `DATA_ROOT`. See [section 5](#5-running-on-github-itself).

## 2. The whole flow

```text
Exchange archives ──┐
                    ├─> ingest ─> raw zone ─> curated zone ─> feature zone ─> compute ─> results
Hourly live poll ───┘                                                                    │
                                                                ┌────────────────────────┤
  data-steward: catalog, integrity, retention, deletion         ▼                        ▼
                                                          GitHub, Pages          desktop app, Telegram
```

- **Historical path:** daily archive files, used for backtests and reports.
- **Live path:** recent trades polled once an hour from public REST sources, used for live paper positions.
- **One codebase.** Bars and features are built by the same code on both paths. Each day, bars built live are
  reconciled against bars built from that day's archive, and any difference is reported.

## 3. Zones

```text
DATA_ROOT/
  raw/archive/<venue>/<dataset>/<symbol>/date=YYYY-MM-DD/    files exactly as delivered, with checksums
  raw/live/<venue>/<channel>/<symbol>/date=YYYY-MM-DD/       polled live data with receive time
  curated/<dataset>/venue=<v>/symbol=<s>/month=YYYY-MM/      clean Parquet with one schema per dataset
  features/<feature_id>/<version>/symbol=<s>/month=YYYY-MM/  computed features, versioned
  results/runs/<run_id>/                                     backtest and report outputs
  ledger/                                                    append-only paper position events
  decisions/                                                 inputs behind every paper decision
  quarantine/                                                files that failed a check
  catalog/catalog.sqlite                                     every dataset, file, run and deletion
  catalog/deletions.jsonl                                    append-only deletion log
```

| Zone | Class | Rule |
|---|---|---|
| `raw/archive` | `RE-DOWNLOADABLE` | Never edited. Deleted by policy once curated data passes its checks |
| `raw/live` | `RE-DOWNLOADABLE` for a limited time | Never edited. Deleted once curated, since the source keeps recent history. A gap longer than that history is permanent |
| `curated` | `DERIVED` | Rebuilt rather than patched |
| `features` | `DERIVED` | A changed definition means a new version, never an overwrite |
| `ledger`, `decisions` | `IRREPLACEABLE` | Kept forever, with an off-site copy |
| `quarantine` | Depends on its source | Reviewed by `data-steward`. Never used for research |

## 4. Rules learned from the first real data

Measured on 2026-11-04 using files dated 2026-11-03. One day is a first look, not a full audit.

- **Canonical bars are built from trades.** Rebuilding Binance 1-minute bars from `aggTrades` gave identical
  daily volume and taker-buy volume, but 127 of 1,440 bars differed by more than 0.001 BTC, by up to 1.627 BTC,
  and prices differed by up to 0.2 USD. The cause seen in the samples is the minute boundary: a trade stamped a
  few milliseconds before a boundary can sit in the official bar after it. Official bars remain a
  reconciliation check, with these differences as the expected tolerance.
- **Bar boundary.** Our bars cover `(open_time, close_time]`, as the timing contract says.
- **Official candles carry signed volume.** `taker_buy_volume` gives signed flow per bar with a long history at
  very small size.
- **Bybit `ob200` is a 100 ms conflated feed.** The median gap between messages was 100 ms, 99th percentile 102 ms.
  A full replay of 863,782 messages had zero update-id breaks, zero crossed books in 1,727 checks, and the mid-
  file snapshot matched the rebuilt book exactly.
- **Bybit changed its book depth.** `ob500` files exist at least from 2023-06-01 to 2025-06-01 and `ob200` files
  by 2025-12-01. Neither exists on 2022-06-01. The curated schema must use a common depth and flag the change.
- **Binance `bookDepth` is a compact imbalance source.** It gives cumulative depth at ±0.2% and ±1% to ±5%,
  about every 30 seconds. It exists on 2023-06-01 and not on 2022-06-01.

## 5. Running on GitHub itself

By the owner's decision (`D-15`), the whole system runs on GitHub, with no server.

| Part | Where it lives |
|---|---|
| Daily historical pipeline | Scheduled Actions job, with a time budget of about 60 minutes. Backfill continues across runs |
| Hourly live cycle | Scheduled Actions job, short, with no overlapping runs |
| `raw` zone | The runner's disk, for one job only. The exchange archives are the real raw store |
| `curated`, `features`, `catalog` | Actions cache, with a budget of 8 GB against the default 10 GB limit. If lost, catch-up rebuilds it from the archives |
| `ledger`, `decisions`, status, run log | The `results` branch in git. Small, append-only and public |
| Report | GitHub Pages |
| Tests and code checks | Actions |
| Alerts | A separate watchdog workflow, through Telegram |

### What running only on GitHub gives up

| Capability | On GitHub | Consequence |
|---|---|---|
| Continuous feeds | Not possible. A job stops at 6 hours, and Actions is not meant to host a service | Live paper positions run on an hourly cycle, not tick by tick |
| Order-level recording (`T3`) | Not possible | Features that need `T3` wait, unless an always-on machine is added later |
| Live order book | Only a snapshot at poll time | Live gates use trades and candles only. `T2` comes from next-day archives, for research only |
| Exact timing | GitHub says scheduled runs can be delayed under load and can be dropped | Each run logs how late it was, and the report shows it. The next run catches up |
| Live strategies under 1 hour | Not practical | 5-minute and 15-minute timeframes are backtest only |

A position on this cycle can detect a stop or an entry up to an hour late, or longer if a run is late. The ledger
records both the event time and the detection time, so the delay stays visible.

### Staying within GitHub's terms

GitHub's terms limit Actions to activity related to producing, testing, deploying or publishing the project, and they
forbid a burden disproportionate to the benefit, naming serverless applications as an example. Misuse can lead to
terminated jobs, a disabled repository or a suspended account. To stay well inside this:

- Jobs are short: under about 3 minutes for the hourly run, and about 60 minutes for the daily run.
- No continuous loops, and no serving of traffic.
- The code stays portable, so the system can move if GitHub ever objects. The ledger is safe in git.

This reduces the risk but does not remove it, because GitHub decides how its terms apply. The risk falls on the
owner's account.

## 6. Staying up

No system can promise 100% uptime. This design promises two things: a failure does not corrupt anything, and a
failure does not go unnoticed.

- **Catch-up instead of schedules.** Each run asks the catalog what is missing and processes all of it, so a missed
  run repairs itself on the next one.
- **Idempotent jobs.** Running a job twice gives the same result.
- **Atomic writes.** Files are written to a temporary name, verified, then renamed. A crash cannot leave a half-
  written partition looking complete.
- **Watchdog.** A separate workflow checks the age of the last result and alerts the owner on Telegram. It runs on the
  same platform, so a GitHub outage can silence it too.
- **Visible staleness.** Every output shows the age of its data. Stale data is labelled, never shown as current.

### What happens when something fails

| Failure | Result | Recovery |
|---|---|---|
| Archive file late or missing | That date stays pending | Picked up by a later run. Alert if overdue |
| Download corrupted | Checksum fails, file goes to quarantine | Downloaded again |
| A scheduled GitHub run is delayed or dropped | Nothing is lost | The next run catches up |
| GitHub disables a schedule after 60 days without activity (public repositories) | Scheduled runs stop | Regular result commits should keep the repository active. To be confirmed in practice |
| Polling source unavailable | Gap recorded | The next run catches up from the source's recent history. A longer gap is permanent, and affected windows are marked invalid |
| Actions cache lost or evicted | Curated data is missing | Catch-up rebuilds it from the archives. The report shows partial coverage until then |
| GitHub Actions outage | Everything waits | Catch-up on return. An `OUTAGE` event goes into the ledger and the channel is told. Open positions are reassessed at the first valid price |
| Cache over budget | Oldest entries are pruned | The newest copy always stays |
| GitHub restricts the jobs | Everything stops | The code is portable and the ledger is in git, so the system can move |
| Exchange changes a format | Validation fails, data is quarantined | Alert. Fix the adapter, then rebuild |

## 7. Who deletes data

`data-steward` owns the policy, the deletion code and the daily review. Routine deletion itself is done by a reviewed
scheduled job, because it has to run reliably with nobody present. The job runs every deletion through the protocol
in the lifecycle document. Anything outside its rules, such as irreplaceable data at a high watermark, goes to the
agent and then to the owner.

## 8. Sizing

Estimates from single-day measurements. Volatile periods will be larger.

| Dataset | Per day | Long-term plan |
|---|---|---|
| Binance candles, BTC | 0.06 MB | Keep. Tiny |
| Binance `bookDepth`, BTC | 0.56 MB | Keep curated |
| Binance `aggTrades`, BTC | 12 MB | Keep flow bars, delete raw |
| Bybit trades, BTC | 50 MB | Keep flow bars, delete raw |
| Bybit `ob200`, BTC and ETH | 430 MB | Keep features, delete raw |

Replaying one day of `ob200` took 95 seconds in plain Python on one core. A runner's disk is limited, so large files
are processed one day at a time and removed before the next one. Only curated data and features are kept between
runs, so the cache budget decides how much history fits, and this must be revised from measured sizes.
