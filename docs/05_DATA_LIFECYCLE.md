# Market data lifecycle

The policy that `data-steward` enforces. Its goals are that the disk never fills up, and that data we
cannot get back is never lost by accident. Retention periods below are starting defaults, to be revised
once real measurements and the server's disk size are known (decision `D-04`).

## 1. Classes

| Class | Meaning | Examples |
|---|---|---|
| `IRREPLACEABLE` | Exists only because we recorded it | Live feed recordings, decision snapshots, the live ledger |
| `RE-DOWNLOADABLE` | Available from a public archive, while the archive lasts | Exchange daily trade and book files |
| `DERIVED` | Can be rebuilt from raw data, while the raw data exists | Candles, flow bars, feature tables |

Once its raw data has been deleted, a `DERIVED` dataset can no longer be rebuilt, so it is treated as
`IRREPLACEABLE` from then on.

## 2. Measured sizes

| Dataset | Size | Status |
|---|---|---|
| Bybit linear `BTCUSDT` `ob200`, one day | About 228 MB zipped, 1.33 GB uncompressed | Measured from one file, 2026-11-03 |
| Bybit linear `ETHUSDT` `ob200`, one day | About 200 MB zipped | Measured from one file, 2026-11-03 |
| Bybit linear `BTCUSDT` trades, one day | About 50 MB gzipped | Measured from one file, 2026-11-03 |
| Binance futures `BTCUSDT` `aggTrades`, one day | About 12 MB zipped, 65 MB uncompressed | Measured from one file, 2026-11-03 |
| Binance futures `BTCUSDT` `bookDepth`, one day | About 0.56 MB zipped | Measured from one file, 2026-11-03 |
| Binance futures `BTCUSDT` 1-minute candles, one day | About 0.06 MB zipped | Measured from one file, 2026-11-03 |
| Bitstamp `live_orders`, BTC and ETH | About 30 GB per day as raw JSON | **Estimate** from a one-minute rate of about 800 messages per second. Not yet measured over a day |

Rates change with volatility. Budgets must be replaced by measured growth as soon as recording starts. See
[the data center document](08_DATA_CENTER.md) for where each dataset lives.

## 3. Retention defaults

| Dataset | Class | Uncompressed | Compressed | After that |
|---|---|---|---|---|
| Candles at every timeframe | `DERIVED` | Keep | Keep | Keep, because they are small |
| Archive trades (`T1`) | `RE-DOWNLOADABLE` | Until derived data is built | 30 days | Delete raw, keep flow bars |
| Archive L2 book (`T2`) | `RE-DOWNLOADABLE` | Until derived data is built | 7 days | Delete raw, keep feature tables |
| Sample days of `T1` and `T2` | `IRREPLACEABLE` by policy | 1 day | Keep | Keep one day per month, as regression tests in case an archive disappears |
| Our live recordings (`T3`) | `IRREPLACEABLE` | 1 day | 90 days | Delete raw only after derived data passes its checks |
| Feature tables and flow bars | `DERIVED` | Keep | Keep | Review yearly |
| Decision snapshots | `IRREPLACEABLE` | Keep | Keep | Keep forever. These are the inputs behind each paper decision |
| Live ledger | `IRREPLACEABLE` | Keep | Keep | Keep forever, with an off-site copy |
| Published run results | `DERIVED` | Keep | Keep | Keep forever |
| Unpublished run results | `DERIVED` | 30 days | 180 days | Delete. The trial registry entry stays forever |

## 4. Disk watermarks

Measured against `DATA_QUOTA_GB`. Live recorders have reserved headroom, so backfills can never starve them.

| Usage | Action |
|---|---|
| Below 70% | Normal. Daily report only |
| 70% | Warn the owner. Report days until full at the current growth rate |
| 80% | Stop new backfills. Run the normal retention jobs immediately |
| 85% | Delete all raw data that is `RE-DOWNLOADABLE` and past its derived-data check, oldest first |
| 90% | Delete unpublished run results past 30 days. Pause feature rebuilds. Alert the owner |
| 95% | Only recorders, ledger and live paper keep running. Urgent alert to the owner |
| Recorder headroom under 3 days | Urgent alert, whatever the percentage |

`IRREPLACEABLE` data inside its retention period is never deleted automatically, at any watermark. If the
disk still fills up, a person decides.

## 5. Deletion protocol

Each deletion, whether automated or manual, goes through these steps:

1. **Plan.** A dry run lists each file, its class, its size, and the rule that selected it.
2. **Check the preconditions.** Derived data exists and passes its checks. The manifest shows nothing
   dependent, and no published run depends on the file unless it can be rebuilt.
3. **Check the path.** Each path must resolve inside `DATA_ROOT`, and symbolic links are not followed.
4. **Delete and log.** Append to `deletions.jsonl`: time, path, size, checksum, rule and the code version.
5. **Update the manifest and report it** in the next daily report.

Automated jobs run with a real delete only for rules marked as reviewed in configuration.

## 6. Manifest

Each dataset has a manifest entry with: dataset id, class, tier, source URL or feed, venue, symbol, date
range, file path, size, checksum, created time, producing code version, parent datasets, licence or terms
note, and last integrity check result.

## 7. Integrity checks

- **Archive files:** checksum when available, expected size and record count, gaps in time.
- **Live recordings:** receive time recorded on every message, connection and reconnection events logged,
  sequence checks where the feed provides them, periodic snapshot reconciliation where it does not.
- **Gaps are recorded, never filled silently.** A feature window that crosses a gap is marked invalid.

## 8. Rules that protect the public repository

- No market data in git. The `.gitignore` blocks common data formats, and pull request checks reject large
  files.
- Check each source's terms before keeping or redistributing its data. Publishing derived statistics and
  publishing raw data are different questions.

## 9. Start recording early

Recording `T3` belongs early in the roadmap, because every day not recorded is lost for good, and no free
source offers this history later. Building the recorder comes before the research that needs its data.
