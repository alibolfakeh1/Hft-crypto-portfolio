# Data center and pipeline

How market data gets in, where it lives, how results get out, and how the system stays running. Owned by
`data-steward`. Retention rules are in [the data lifecycle document](05_DATA_LIFECYCLE.md).

## 1. Why the data does not live in GitHub

GitHub is the home of the code, the catalog summaries and the results. It cannot be the home of the data:

- GitHub blocks files over 100 MiB. One day of Bybit `ob200` for BTC is about 228 MB.
- Book data alone is on the order of 150 GB per year for two symbols, and GitHub recommends far smaller
  repositories.
- This repository is public, and redistributing an exchange's data is a separate legal question.

So data lives in a data center, under `DATA_ROOT`, on a machine that stays on. Only small results reach GitHub.

## 2. The whole flow

```text
Exchange archives ──┐
                    ├─> ingest ─> raw zone ─> curated zone ─> feature zone ─> compute ─> results
Live feeds ─────────┘                                                                    │
                                                                ┌────────────────────────┤
  data-steward: catalog, integrity, retention, deletion         ▼                        ▼
                                                          GitHub, Pages          desktop app, Telegram
```

- **Historical path:** daily archive files, used for backtests and reports.
- **Live path:** continuous feeds, used for live paper positions and for recording data no archive offers.
- **One codebase.** Bars and features are built by the same code on both paths. Each day, bars built live are
  reconciled against bars built from that day's archive, and any difference is reported.

## 3. Zones

```text
DATA_ROOT/
  raw/archive/<venue>/<dataset>/<symbol>/date=YYYY-MM-DD/    files exactly as delivered, with checksums
  raw/live/<venue>/<channel>/<symbol>/date=YYYY-MM-DD/       messages with receive time, compressed
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
| `raw/live` | `IRREPLACEABLE` | Never edited. Compressed after a day, and deleted only by policy |
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

## 5. Where each job runs

| Job | Where | Why |
|---|---|---|
| Live recorder, live bars, paper engine, Telegram posts | **Always-on server** | These need continuous connections. See below |
| Backfill, daily catch-up, feature builds, backtests | Server. GitHub Actions can cover the light historical part until a server exists | Actions has limited disk and time |
| Tests and code checks | GitHub Actions | Free for public repositories |
| Publishing the report to GitHub Pages | GitHub Actions | This is the publication of the project |
| Watchdog | GitHub Actions | It must run outside the machine it watches |

**Live work cannot run on GitHub Actions.** A job stops at 6 hours. GitHub says scheduled runs can be delayed under
load and can even be dropped. Its terms also say Actions should not be used as part of a serverless application or
a standalone service, and misuse can lead to a disabled repository or a suspended account.

## 6. Staying up

No system can promise 100% uptime. This design promises two things: a failure does not corrupt anything, and a
failure does not go unnoticed.

- **Catch-up instead of schedules.** Each run asks the catalog what is missing and processes all of it, so a missed
  run repairs itself on the next one.
- **Idempotent jobs.** Running a job twice gives the same result.
- **Atomic writes.** Files are written to a temporary name, verified, then renamed. A crash cannot leave a half-
  written partition looking complete.
- **Supervised services.** Live services restart automatically and reconnect with backoff.
- **Outside watchdog.** The server writes a heartbeat. A separate scheduled check alerts the owner on Telegram if the
  heartbeat goes stale, because a dead server cannot report its own death.
- **Visible staleness.** Every output shows the age of its data. Stale data is labelled, never shown as current.

### What happens when something fails

| Failure | Result | Recovery |
|---|---|---|
| Archive file late or missing | That date stays pending | Picked up by a later run. Alert if overdue |
| Download corrupted | Checksum fails, file goes to quarantine | Downloaded again |
| A scheduled GitHub run is delayed or dropped | Nothing is lost | The next run catches up |
| GitHub disables a schedule after 60 days without activity (public repositories) | Scheduled runs stop | Regular result commits keep the repository active. The server also checks when the last report was published and raises an alert. To be confirmed in practice |
| Live feed drops | Gap recorded, automatic reconnect | The gap cannot be recovered. Affected feature windows are marked invalid |
| Server down | Recording and live positions stop | Watchdog alerts. On restart, an `OUTAGE` event goes into the ledger and the channel is told. Open positions are reassessed at the first valid price |
| Disk filling up | Watermark actions from the lifecycle document | Recorder headroom is protected |
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
| Live L3 recording, BTC and ETH | About 30 GB raw JSON, before compression. Not yet measured over a day | Keep 90 days compressed if the disk allows |

Replaying one day of `ob200` took 95 seconds in plain Python on one core. A rough starting point for the server is 4
CPU cores, 8 GB of memory and 500 GB to 1 TB of SSD. The live recording rate is what decides the disk size, so revise
this after a measured day.
