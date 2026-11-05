# Data sources

Status: first full pass, date 2026-11-04. Owned by `data-steward`. The choice of source is for the owner to decide.

**This is a factual summary of documents, not legal advice.** Eligibility under each venue's terms is for the owner to
confirm. Anything not opened is marked `UNVERIFIED`. A document that says nothing on a point is marked `SILENT`, and
silence is not read as permission.

Decision `D-17` makes possible commercial use the deciding scenario.

> **Update, 2026-11-05.** The owner has ruled Kraken out (`D-23`), so the recommendation below is kept only as the record
> of 2026-11-04. The next source is open (`D-24`). The facts about other sources stand. One addition: Tardis's terms say
> that agreeing to them also means agreeing to the Buyer Terms of Paddle, its reseller for paid subscriptions. Those
> Buyer Terms were not read: `UNVERIFIED`.

## Recommendation

**No free source clearly allows possible commercial use today.** Each free venue read either bars it, requires a
permission or signed agreement first, is `SILENT`, or has terms that could not be opened. The only licence that allows
it on terms readable today is the paid Tardis licence, and that covers history only: an hourly poll taken directly
from a venue stays under the venue's own terms (Tardis clause 9.7).

| Need | Recommendation |
|---|---|
| Primary research source | Kraken spot, BTC/USD and ETH/USD: Kraken's own free trade and candle files, then REST catch-up |
| Hourly live source | Kraken spot, public `Trades` REST endpoint with `since`. Same venue as research |
| Condition | Eligibility under Kraken's terms is for the owner to confirm first. Then written permission from Kraken (marketdata@kraken.com) **before** any download or poll. It should name: private research, a public report of derived statistics, a public channel of paper positions, those for money, real trading using derived results, hourly automated polling from a hosted runner, keeping polled trades in a GitHub Actions cache, and publishing the as-seen bar values behind each paper decision in this public repository |
| Fallback | Bitstamp for both, under its commercial Data License Agreement (partners@bitstamp.net), with history bought from Tardis. Send Bitstamp the same request at the same time. Suggested rule: no written yes from Kraken in 30 days means moving to the fallback |
| Until a reply arrives | Pipeline work only, on Tardis free first-day-of-month CSV files, which are licensed by clause 9.4. This needs the owner's agreement, because `D-17` holds data downloads. Not enough days for a backtest |

Why Kraken: among venues with a stated route to commercial use, it is the only one with free signed trade history over
many years and a same-venue hourly poll, so it is the only such route that might cost nothing. Bitstamp's own wording on
commercial use is more favourable, but the longest free trade window it states is one day, so its route needs paid
history. Bybit and Coinbase also have free signed history, but their terms could not be opened and the indirect evidence
points against them. Bybit's latest-trades cap of 1,000 per symbol would also leave gaps in a busy hour for an hourly poll.

Not settled by this document: whether Kraken will grant permission, on what terms, and at what price. Kraken's Global
Terms apply on their face until then, including the bar on scripts in section 9.

### Options side by side

| Option | Research data | Hourly live | Position on commercial use | Data cost | Main risk |
|---|---|---|---|---|---|
| **1. Kraken with written permission (recommended)** | Free, signed trades and candles from each pair's first trade | Kraken REST | Needs prior permission, route is stated | Free files. Any permission fee not stated | Refused, conditional or unanswered. No free book history |
| 2. Bitstamp with signed agreement, plus Tardis history | Tardis, spot since 2019-03-30. Bitstamp free candles | Bitstamp REST, `time=hour` | Bitstamp says allowed under a signed agreement. Tardis allows it by its terms | Agreement price not stated. Tardis Solo: see [price](#tardis-price) | Bitstamp Terms of Use unread. Spot plan page does not name Bitstamp, so All Exchanges may be needed |
| 3. Tardis history, with live from another venue | Tardis, any covered venue | Venue REST, under that venue's terms | Allowed for history. Live not covered (clause 9.7) | Tardis Solo: see [price](#tardis-price) | Still needs a venue's permission for commercial live use. Clause 11 gives no warranty of rights in exchange data |
| 4. Rely on a source with silent terms (dYdX, or Hyperliquid once its terms are read) | Free indexer or requester-paid archive | Same venue | `SILENT` or `UNVERIFIED` | Free, or transfer costs on Hyperliquid archives | See below |
| 5. Binance enterprise licence | Binance Vision | `UNVERIFIED` | Clause 3.4 offers a separate written licence | Not stated | Needs the owner to revisit `D-17` |

**Risk of relying on silence.** Silent terms give no right that can be shown later. A venue could object or add terms
after results are public, and work built on its data might then have to be redone before any paid use. Project rule 10
makes this harder: the live record is append-only, so published posts cannot be withdrawn to cure a licence problem.
dYdX is also perpetuals only, and traded about 100 BTC by 20:00 UTC on the day checked.

### What is lost compared with Binance

- **Book history.** No free book history at Kraken, so `T2` imbalance and depth features cannot be backtested free.
  Paid route: Tardis L2 for Kraken spot, since 2019-06-04.
- **Perpetuals.** Research would be on spot. Kraken Futures gives 7 days of public trades, candles from about 2023
  (`PF_XBTUSD`) and funding, so a deep free perpetual study is not possible.
- **Daily archive.** Kraken's bulk files are quarterly, not daily. The gap is filled by REST at 1,000 trades per call
  with a suggested 1 to 2 seconds between calls. Catch-up time is not yet measured.
- **Market depth and price discovery.** Not measured here. No result or size assumption carries over from Binance.
  Measurements in `docs/08_DATA_CENTER.md` must be repeated on the chosen venue.
- **Trade side certainty.** Kraken's pages show `b` or `s` but do not say this is the taker's side. This must be tested
  before any `T1` feature depends on it.

Gained: signed history reaching back to 2013-10-06 for `XBTUSD` (status check).

### Scenario A: if the project stayed non-commercial forever

This needs the owner to reverse `D-17`. Binance Vision would then be the simplest research source: CC BY-NC-SA 4.0, with
attribution and share-alike, no signals for compensation and no live proprietary trading (clauses 3.1, 4.2). Those
terms cover the archive, not an hourly poll, and Binance's API terms were not read, so the live source would stay
`UNVERIFIED`. Kraken's permission notice is aimed at commercial use, but section 9 of its Global Terms still limits
third-party availability and scripts. OKX stays unsuitable for a public channel (section 9.4). Going commercial later
would mean redoing research on another source or obtaining a licence (clause 3.4).

## Governing documents

Dates are those shown on each document. "Opened" means opened on 2026-11-04.

| Source | Governing document | Key clause, in our words | Opened |
|---|---|---|---|
| Binance Vision | [Dataset Terms, v1.0, 2026-08-26](https://github.com/binance/binance-public-data/blob/master/TERMS_AND_CONDITIONS.md) | Non-commercial only (CC BY-NC-SA 4.0, clause 3.1). Commercial use needs a separate written licence (clause 3.4). Out under `D-17` | Yes |
| OKX | [API Agreement, 2026-07-28, section 9.4](https://www.okx.com/en-us/help/okx-api-agreement) | Market data use limited to personal, non-commercial trading and account management. No publishing or display to third parties without written consent, even free. Applies to public endpoints too | Yes |
| Kraken spot | [Global Terms, 2026-10-30, sections 8, 9](https://www.kraken.com/legal/global-terms). [API notice, undated, legacy documentation](https://docs-legacy.kraken.com/api/docs/guides/global-intro/) | Use is for your own benefit. Commercial exploitation, third-party availability of site content, scraping and scripts are barred. The notice requires prior permission for "any non-personal commercial use of data from publicly accessible endpoints". The [legal index](https://www.kraken.com/legal) lists no market data licence or API terms. The [current developer page](https://docs.kraken.com/api/docs/guides/global-intro/) does not repeat the notice, and the legacy page does not say it is superseded. Regional versions of the terms exist | Yes |
| Kraken Futures | Same documents. No Futures document on the legal index. [Derivatives API introduction](https://support.kraken.com/articles/360022635512-introduction-derivatives) has no data licence | The notice covers "the Kraken APIs" without separating spot and futures | Yes |
| Gate | [User Agreement, 2026-07-22, clauses 10.1, 16.2](https://www.gate.com/legal/user-agreement) | Licence limited to non-commercial or personal use. Resale or commercial purposes need written agreement. Recorded from an earlier reading | No, so `UNVERIFIED` today |
| Tardis | [Terms, modified 2026-10-28, clauses 1.1, 9, 10.4, 11, 23](https://docs.tardis.dev/legal/terms-of-service) | Licence for internal business, research, educational or personal purposes, including trading. Derived Data may be shared, including for a fee, in charts, statistics and reports, or in any form if "aggregated over periods of at least 10 minutes". Raw data may not be passed on. Coinbase data is not excluded, but it carries extra limits and has no publishing right. Downloaded data keeps a perpetual licence (clause 9.4) unless ended for breach. Free access: first day of each month, [per the CSV page](https://docs.tardis.dev/downloadable-csv-files/overview) | Yes |
| Bybit | Terms and API Terms did not open: `UNVERIFIED`. Read only: [archive index](https://public.bybit.com/), [recent trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade), [candles](https://bybit-exchange.github.io/docs/v5/market/kline), [funding](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate), [rate limits](https://bybit-exchange.github.io/docs/v5/rate-limit) | Pages read carry no licence or usage terms. A search excerpt of the API Terms, not opened, suggests a bar on commercial exploitation: `UNVERIFIED` | Legal no, technical yes |
| Coinbase (Exchange and Advanced) | Market Data Terms, Developer Platform Terms and User Agreement did not open: `UNVERIFIED`. Read: [Exchange welcome page, undated](https://docs.cdp.coinbase.com/exchange/introduction/welcome), [Advanced REST overview](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api) | Using the Exchange market data API means you "agree to be bound by the Market Data Terms of Use". Indirect evidence only: Tardis clause 23 passes on Coinbase limits, including no display to non-customers of data or derived works, no financial products, and no AI or machine learning use | Legal no, technical yes |
| Bitstamp | [API documentation, undated, "Commercial Use of Bitstamp's Exchange Data"](https://www.bitstamp.net/api/). Terms of Use showed no readable text: `UNVERIFIED` | Bitstamp "allows the incorporation and redistribution of our exchange data for commercial purposes", including statistics and new works. Companies are directed to sign a commercial Data License Agreement. No price stated | API page yes, Terms no |
| Hyperliquid | Terms did not open or showed no text: `UNVERIFIED`. Read: [historical data](https://hyperliquid.gitbook.io/hyperliquid-docs/historical-data), [info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint), [rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) | Documentation pages state no licence. Trade archives are requester-pays | Legal no, technical yes |
| dYdX | [Software Terms of Use, 2026-03-12](https://dydx.exchange/terms). [Integration compliance](https://docs.dydx.xyz/interaction/integration/integration-compliance) | Licenses the software, AGPL by default (section 2). The Indexer and any market data licence are not mentioned. Integrators are expected to follow the same terms | Yes |

## What each document says

Points that could not be checked are `UNVERIFIED`.

| Source | Private research, backtesting | Free public report of derived statistics | Free public channel of paper positions | Those for money | Real trading using derived results | Redistribution and attribution | Automated polling |
|---|---|---|---|---|---|---|---|
| Binance Vision | Non-commercial only | Non-commercial, under CC BY-NC-SA terms | Free case `SILENT`. Compensated signals barred (clause 4.2) | Barred without a written licence (clauses 3.4, 4.2 to 4.4) | Live proprietary execution barred (clause 4.2) | No commercial hosting or sale (clause 4.3). CC attribution and share-alike | Not re-read: `UNVERIFIED` |
| OKX | Limited to personal, non-commercial trading and account management. Research not named | Publishing market data barred without consent. Derived statistics `SILENT` | Publishing market data barred without consent. Positions `SILENT` | Barred without a separate licence | Personal trading only | Barred without written consent. Attribution `SILENT` | Barred beyond what personal trading reasonably needs |
| Kraken spot | Own benefit only (section 8). Research not named | Third-party availability of content barred (section 9). Derived statistics `SILENT` | Same. Positions `SILENT` | Barred by section 9, which also bars competing products. API notice: prior permission | API orders on Kraken are provided for (section 4). Derived results `SILENT` | Barred without permission. Attribution `SILENT` | Conflict: section 9 bars scripts and data extraction, while API pages describe polling with `since`. Needs a written answer |
| Kraken Futures | As Kraken spot | As Kraken spot | As Kraken spot | As Kraken spot | As Kraken spot | As Kraken spot | As Kraken spot |
| Gate | Non-commercial or personal use, as recorded earlier | `UNVERIFIED` | `UNVERIFIED` | Written agreement needed, as recorded earlier | `UNVERIFIED` | Resale needs written agreement, as recorded earlier. Attribution `UNVERIFIED` | `UNVERIFIED` |
| Tardis | Allowed (clause 1.1) | Allowed as Derived Data, not as a dataset, feed or API (clause 9.3). Not for Coinbase | Not named. Nearest wording is "similar work" and 10-minute aggregates (clause 9.3), so `SILENT` on positions as such. Derived Data must not expose raw records (clause 1.1) | Allowed, including for a fee (clause 9.3) | Trading and investment are in Permitted Use (clause 1.1) | Raw data barred (clause 9.2). No attribution duty. The Tardis mark may be used only to credit the source (clause 10.1) | `SILENT`. Live data taken from a venue stays under its terms (clause 9.7) |
| Bybit | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | Terms `UNVERIFIED`. Technical limit only: 600 requests per 5 seconds per IP |
| Coinbase | `UNVERIFIED` | `UNVERIFIED`. Indirectly restrictive (Tardis clause 23) | `UNVERIFIED`. Indirectly restrictive (Tardis clause 23) | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | Terms `UNVERIFIED`. Candle page says historical rates should not be polled often. Public limit 10 requests per second |
| Bitstamp | API page `SILENT`. Terms `UNVERIFIED` | Statistics covered by the commercial wording. Free case `SILENT` | `SILENT` | Allowed under a signed Data License Agreement | `SILENT` | Commercial redistribution allowed under that agreement. Attribution `SILENT` | No ban on API page. Limit 10,000 requests per 10 minutes. Terms `UNVERIFIED` |
| Hyperliquid | Docs `SILENT`. Terms `UNVERIFIED` | Docs `SILENT`. Terms `UNVERIFIED` | Docs `SILENT`. Terms `UNVERIFIED` | Docs `SILENT`. Terms `UNVERIFIED` | Docs `SILENT`. Terms `UNVERIFIED` | Docs `SILENT`. Terms `UNVERIFIED` | Technical limit only: weight 1,200 per minute per IP. Terms `UNVERIFIED` |
| dYdX | `SILENT` | `SILENT` | `SILENT` | `SILENT` on data. Annex C covers affiliate marketing only | `SILENT` on derived results | Software licence only. Data and attribution `SILENT` | `SILENT` |

## Data

Each fact is tagged `doc` (from a page read) or `status` (from a very small request on 2026-11-04). No dataset file was
downloaded. Reachability from GitHub-hosted runners is `UNVERIFIED` for every source and must be tested from a runner.

| Source | Candles | Signed trades | Book history | Funding | Market | Free history and delivery |
|---|---|---|---|---|---|---|
| Binance Vision | Daily files, per `docs/08_DATA_CENTER.md` | `aggTrades`, same | `bookDepth`, same | Not re-read | Not re-read | Daily archive. Out under `D-17` |
| OKX, Gate | Not checked | Not checked | Not checked | Not checked | Not checked | Excluded by their terms |
| Kraken spot | [OHLCVT files](https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data), 1 to 1,440 minutes (`doc`). REST: 720 latest per interval (`doc`) | [Time and sales files](https://support.kraken.com/articles/360047543791-downloadable-historical-market-data-time-and-sales-) with `b` or `s` and order type (`doc`). Taker meaning not stated (`doc`). [REST](https://docs.kraken.com/api/docs/rest-api/get-recent-trades): 1,000 per call with `since` (`doc`) | None. [Depth is not historical](https://docs.kraken.com/exchange/guides/general/historical-data) (`doc`) | Not applicable | Spot | From each pair's first trade to 2026-09-30 in ZIP parts of about 2 GB, updated quarterly (`doc`). Oldest `XBTUSD` trade 2013-10-06 (`status`). The developer guide says no bulk dump exists, which the support pages contradict |
| Kraken Futures | REST charts (`doc`). `PF_XBTUSD` daily present at 2023-01-01, absent at 2022-01-01 (`status`) | [Taker `side`](https://docs.kraken.com/api-reference/market-data/get-trade-history), 100 per call, up to 7 days or last engine restart (`doc`) | `UNVERIFIED` | [Public history](https://docs.kraken.com/api/docs/futures-api/trading/historical-funding-rates), depth not stated (`doc`) | Perpetual | REST JSON. No bulk files found |
| Tardis | Not sold as candles on pages read. Build from trades | Trades (`doc`). Side column not confirmed on pages read | Incremental L2, snapshots, quotes (`doc`). [Bitstamp](https://docs.tardis.dev/historical-data-details/bitstamp) also L3 events (`doc`) | In derivative ticker (`doc`) | Spot and perpetuals. [Bitstamp](https://docs.tardis.dev/historical-data-details/bitstamp) spot since 2019-03-30, perpetuals since 2026-10-07. [Kraken](https://docs.tardis.dev/historical-data-details/kraken) spot since 2019-06-04 (`doc`) | First day of each month, CSV, no key. Next-day files at about 05:00 UTC (`doc`) |
| Bybit | REST, 1,000 per call, spot and linear, depth not stated (`doc`) | REST `side` is the taker's, spot 60 latest, others 1,000 latest (`doc`). Archive files (`status`), columns not opened | `UNVERIFIED` | REST, 200 per page, depth not stated (`doc`) | Spot and perpetual | Perpetual daily `.csv.gz` from 2020-03-25, spot from 2022-11-10 to 2026-11-03 (`status`, directory index). Latest perpetual file not confirmed |
| Coinbase | [Exchange](https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproductcandles): 1 minute to 1 day, 300 per call, may be incomplete (`doc`). Daily candle at 2016-01-01 present (`status`) | [Exchange](https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproducttrades): `side` is the **maker's**, cursor pages (`doc`). Oldest `BTC-USD` trade 2014-12-01 (`status`) | History `SILENT` | Not on Exchange spot. INTX perpetuals ended 2026-10-01 (`doc`) | Spot. Derivatives gateway not read | REST JSON only, at [10 requests per second](https://docs.cdp.coinbase.com/exchange/rest-api/rate-limits) (`doc`) |
| Bitstamp | [OHLC](https://www.bitstamp.net/api/), 60 seconds to 3 days, 1,000 per call, depth not stated (`doc`) | `type` field, meaning not defined on the page read. Windows: minute, hour, day (`doc`) | No free archive found. Paid L2 and L3 via Tardis (`doc`) | History up to 30 days old (`doc`) | Spot and perpetual (`doc`) | REST JSON. Free trade window of one day. No free bulk files found |
| Hyperliquid | REST, 5,000 latest per interval. Not in archive (`doc`). 2023-01-01 daily exists with zero volume (`status`) | `recentTrades` with side (`status`). `node_fills` archive, requester-pays (`doc`) | L2 snapshots in archive, roughly monthly, may have gaps (`doc`) | Non-trade events archive (`doc`) | Perpetual. Spot on REST only (`doc`) | S3 via AWS CLI, requester pays transfer. Depth not stated (`doc`) |
| dYdX | [Indexer](https://docs.dydx.xyz/indexer-client/http) REST (`doc`). Query for 2023 returned none (`status`) | `side` present (`status`). Paged by block height (`doc`) | Current book only (`doc`) | Historical endpoint (`doc`) | Perpetual (`doc`) | REST JSON, depth not stated (`doc`). `BTC-USD` traded about 100 BTC by 20:00 UTC on 2026-11-04 (`status`) |

## Tardis price

From the [Tardis home page](https://tardis.dev), read 2026-11-04. These are listed amounts in USD per month, per plan.
Tier order was inferred from page layout, so **confirm in the order form**. Billing: yearly, quarterly or monthly.

| Plan | Academic | Solo | Professional | Business |
|---|---|---|---|---|
| Perpetuals | 350 | 700 | 1,000 | 3,000 |
| Spot | 450 | 900 | 1,350 | 3,500 |
| Derivatives | 450 | 900 | 1,350 | 3,500 |
| All Exchanges | 650 | 1,200 | 2,200 | 6,000 |

- **Smallest plan for BTC and ETH trades with commercial use:** Solo, at 700 (perpetuals) or 900 (spot). The Terms do
  not vary rights by tier. Academic is [for people with a university email](https://docs.tardis.dev/faq/billing-and-subscriptions), so it is not a fit. If the
  listed rate applies to yearly billing, that is 8,400 or 10,800 per year (arithmetic, not a quoted price).
- **Limits:** Solo is CSV files only. History is 4 years with yearly billing. Lookback under monthly or quarterly
  billing is not stated. No refunds.
- **Plan coverage:** the Spot plan names Kraken. It does not name Bitstamp, which is named only in the page footer. All
  Exchanges is the safe reading for Bitstamp until confirmed.
- **Possible one-off:** clause 9.4 keeps the licence for data downloaded during paid access, so a single paid period is
  possible. Whether that period reaches enough history is `UNVERIFIED`. Storage for those downloads is not yet measured.

Other paid sources: [CoinAPI](https://www.coinapi.io/products/market-data-api/pricing) lists 79, 249 and 599 per month,
with no statement on commercial use and its terms not read (`UNVERIFIED`). [Crypto Lake](https://crypto-lake.com/) shows
no prices on the page read.

## Limits of this reading

- **Did not open or showed no text, one attempt each:** Bybit Terms and API Terms. Coinbase Market Data Terms, Developer
  Platform Terms, User Agreement and institutional market data page. Bitstamp legal index, Terms of Use and WebSocket
  documentation. Hyperliquid Terms. Gate User Agreement. Kraken API terms at the guessed address, and two Kraken Futures
  reference pages at guessed addresses.
- **Partly read:** Kraken's Global Terms were read up to Annex F, so later annexes are unread. The last 6% of Bitstamp's
  API page is unread.
- **Search excerpts** were used only to find pages. Nothing here relies on one except where marked `UNVERIFIED`.
- Pages were read through an automated reader. Have a person read the clauses before relying on them, especially Kraken
  sections 8 and 9 and Tardis clause 9.
