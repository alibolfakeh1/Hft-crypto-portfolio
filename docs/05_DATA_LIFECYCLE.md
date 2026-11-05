# Market data lifecycle

The policy that `data-steward` enforces. Its goals are that the disk never fills up, and that data we
cannot get back is never lost by accident. Retention periods below are starting defaults, to be revised
from real measurements.

**Current mode.** The system runs on GitHub only (decision `D-15`). `DATA_QUOTA_GB` is therefore the
Actions cache budget: 4 GB by default for the data center, and 1 GB for the hourly poll, which has its own
cache. Raw and quarantined files last for one job. They leave with the runner whether or not curated data
passed, and the catalog then marks them `absent`. This is not a deletion under section 5, and it is
acceptable only because these files can be fetched again. A reviewed rule can only remove them sooner,
inside the job. Rows and rules about live recordings (`T3`) and recorder headroom are inactive until an
always-on machine is added.

The reasons, and what the code must still change to match this document, are in
[the data lifecycle rulings](reviews/data/data_center_rulings_2026-11-04.md).

## 1. Classes

| Class | Meaning | Examples |
|---|---|---|
| `IRREPLACEABLE` | Exists only because we recorded it | Live feed recordings, polled trades with their receive times, decision snapshots, the live ledger |
| `RE-DOWNLOADABLE` | Available from a public archive, while the archive lasts | Exchange daily trade and book files |
| `DERIVED` | Can be rebuilt from raw data, while the raw data exists | Candles, flow bars, feature tables |

Losing its raw files does not by itself end a dataset's rebuild, because on GitHub raw files leave after every
job and the archive is the real raw store. For a deletion, a dataset counts as `DERIVED` only if every raw parent
is on disk, or if the rule says `rebuildable_from_archive = true` and every raw parent is an archive file from a
source that is still usable and still serves it. In every other case it is treated as `IRREPLACEABLE`. That
includes polled data, which has no archive parent, and whose receive times exist only because we recorded them.
Archives can disappear, so a rule that relies on one needs its own review.

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
| Curated trades (`T1`) | `DERIVED` while the archive can rebuild them | Keep | Keep | Rule `curated-trades-window` deletes them after 90 days and keeps the bars. Not reviewed, and 90 days is a placeholder until sizes are measured |
| Sample days of `T1` | `IRREPLACEABLE` by policy | Not held | Curated data only | Keep one day per month, chosen by the calendar. Never deleted automatically. A regression test for bar building, not for parsers. Held in the cache, so it does not survive losing both the cache and the archive |
| Sample days of `T2` | None held | Not held | Not held | No sample exists, because book replay keeps statistics only and raw book days do not fit the cache budget. Revisit when a `T2` source is approved |
| Polled trades and bars (`trades_live`, `bars_*_live`) | `IRREPLACEABLE` | Keep | Keep | Never deleted automatically. The poll's cache can lose them, which is accepted while no paper decision rests on them. After that, each decision's as-seen inputs must reach `decisions/` in the same run |
| Our live recordings (`T3`) | `IRREPLACEABLE` | 1 day | 90 days | Delete raw only after derived data passes its checks |
| Feature tables and flow bars | `DERIVED` | Keep | Keep | Review yearly |
| Decision snapshots | `IRREPLACEABLE` | Keep | Keep | Keep forever. These are the inputs behind each paper decision |
| Live ledger | `IRREPLACEABLE` | Keep | Keep | Keep forever, with an off-site copy |
| Published run results | `DERIVED` | Keep | Keep | Keep forever |
| Unpublished run results | `DERIVED` | 30 days | 180 days | Delete. The trial registry entry stays forever |

## 4. Disk watermarks

Measured against `DATA_QUOTA_GB`, on the zones that survive between runs (`persisted_zones`), not on files that
leave with the runner. GitHub's own figure for total cache use is a second check, because that total is what
causes eviction. Live recorders have reserved headroom, so backfills can never starve them.

| Usage | Action | On GitHub (`D-15`) |
|---|---|---|
| Below 70% | Normal. Daily report only | The same |
| 70% | Warn the owner. Report days until full at the current growth rate | The same |
| 80% | Stop new backfills. Run the normal retention jobs immediately | Backfills stop and routine catch-up continues. Retention already runs in every daily job, as a dry run |
| 85% | Delete all raw data that is `RE-DOWNLOADABLE` and past its derived-data check, oldest first | Frees nothing, because raw data is not in the cache. Alert only |
| 90% | Delete unpublished run results past 30 days. Pause feature rebuilds. Alert the owner | Frees nothing, because run results are not in the cache. No feature job exists yet. Alert the owner |
| 95% | Only recorders, ledger and live paper keep running. Urgent alert to the owner | Ingest holds all its work and the poll keeps running. Urgent alert to the owner |
| Recorder headroom under 3 days | Urgent alert, whatever the percentage | Inactive, because there is no recorder |

`IRREPLACEABLE` data inside its retention period is never deleted automatically, at any watermark. If the
disk still fills up, a person decides. On GitHub, what can free cache space is stopping backfills, the rule
`curated-trades-window` once it is reviewed, and the owner.

## 5. Deletion protocol

Each deletion, whether automated or manual, goes through these steps:

1. **Plan.** A dry run lists each file, its class, its size, and the rule that selected it.
2. **Check the preconditions.** Derived data exists and passes its checks. `provisional` and `warn` do not
   pass. The manifest shows nothing dependent, and no published run depends on the file unless it can be
   rebuilt.
3. **Check the path.** Each path must resolve inside `DATA_ROOT`, and symbolic links are not followed.
4. **Delete and log.** Append to `deletions.jsonl`: time, path, size, checksum, rule and the code version.
5. **Update the manifest and report it** in the next daily report.

Automated jobs run with a real delete only for rules marked as reviewed in configuration. No rule is reviewed
yet, and `retention` stays a dry run in the workflow. The rulings list what must be true before either changes.

## 6. Manifest

Each dataset has a manifest entry with: dataset id, class, tier, source URL or feed, venue, symbol, date
range, file path, size, checksum, created time, producing code version, parent datasets, licence or terms
note, and last integrity check result.

## 7. Integrity checks

- **Archive files:** checksum when available, delivered length against the declared length, no empty files,
  record counts where a count can be known (candles per day, consecutive trade ids), gaps in time.
- **Expected size and row bands:** set later, from at least 30 measured partitions per dataset on the approved
  source. A file outside its band raises an alert for `data-steward` and nothing else. It never changes a check
  status, because a large file is often a volatile day, and a day must not leave the results for that reason.
- **Polled trades:** each row keeps `knowable_time`, which is its receive time unless its stamp plus the
  allowance is later. Each run logs a hash of what it emitted.
- **Quarantined files:** each one leaves a record of time, source URL, size, checksum, reason and code version,
  published with the run log. `data-steward` reviews the record. On GitHub the file itself leaves with the
  runner, and it can be fetched again from its URL.
- **Live recordings:** receive time recorded on every message, connection and reconnection events logged,
  sequence checks where the feed provides them, periodic snapshot reconciliation where it does not.
- **Gaps are recorded, never filled silently.** A feature window that crosses a gap is marked invalid.

## 8. Rules that protect the public repository

- No market data in git. The `.gitignore` blocks common data formats, and pull request checks reject large
  files.
- Check each source's terms before keeping or redistributing its data. Publishing derived statistics and
  publishing raw data are different questions.

## 9. If an always-on machine is added

Recording `T3` should then start immediately, because every day not recorded is lost for good, and no free
source offers this history later. The `raw/live` zone comes into use then, and quarantine needs a retention
rule, because nothing would otherwise remove it.
