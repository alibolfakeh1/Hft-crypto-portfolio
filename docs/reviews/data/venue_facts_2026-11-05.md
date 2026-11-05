# Venue facts for the first candle run: funding interval and tick size

Date: 2026-11-05. Owner: `data-steward`. For conditions 2 and 3 of the code recheck
(`docs/reviews/code/engine_recheck_2026-11-05.md`, section 1 and R-01), before the first candle run on BTCUSDT and ETHUSDT,
2020-01-01 to 2023-12-31.

**Method.** Public pages only: Binance's developer documentation, the `binance/binance-public-data` README, and Binance FAQ and
announcement pages. No market data file was fetched, no Binance API host was called, and nothing was signed in to or accepted. Pages
were read through a fetch tool that returns extracts, so quotes are short excerpts as that tool returned them. Search-result snippets
were not used as evidence. Every page used is listed in section 4.

## Answers

| Question | Answer | Confidence |
|---|---|---|
| What a settlement's rate covers | **The funding period ending at that settlement.** The FAQ says rates "calculated from 00:00 - 08:00 are exchanged at 08:00", and the formula's `N` is the funding interval (S7) | High, for the rate |
| What the archive's `funding_interval_hours` column describes | **`UNVERIFIED`.** No page read documents the archive's `fundingRate` files. The README does not list that dataset at all (S1) | None |
| BTCUSDT or ETHUSDT interval other than 8 h, 2020 to 2023 | **None found.** The one multi-contract move to 4 h (2023-10-12) names 15 other contracts (S8). Absence from what I read is not proof | Medium. The data check in 3.1 settles it |
| BTCUSDT or ETHUSDT interval other than 8 h, later | **Possible, and unannounced.** From 2025-05-02 any USDⓈ-M perpetual moves to 1 h after a settlement at the cap or floor, from 2026-01-02 it moves from 1 h to 4 h after 16 quiet cycles, and "No announcement will be made" (S7). Whether either symbol ever moved is `UNVERIFIED` | High for the rule, none for its use |
| BTCUSDT tick | **0.01 until 2022-02-15 03:30 UTC, then 0.1** (S9). The config's single 0.1 is wrong for 2020-01-01 to 2022-02-15 | High for the change. Medium that 0.01 held from 2020-01-01 |
| ETHUSDT tick | **No change found.** No page read states its value. The config's 0.01 stays `UNVERIFIED` | Low. The data check in 3.2 settles it |
| Any tick change on either symbol after 2023 | None in the 2024 notices read (S15, S16). Not exhaustive | Low |

## 1. The funding interval

### 1.1 What the pages say

- **Default schedule.** "The default funding interval is every 8 hours at 00:00 (UTC), 08:00 (UTC), and 16:00 (UTC)", and "There is a
  15-second deviation in the actual funding fee transaction time" (S7).
- **A settlement pays for the period before it.** "the funding rates calculated from 00:00 - 08:00 are exchanged at 08:00", and "For
  symbols of which the funding interval is greater than 1 hour, we use the premium index series in this funding period" (S7).
- **The interval scales the rate.** "Funding Rate (F) = [Average Premium Index (P) + clamp (interest rate - Premium Index (P), 0.05%,
  -0.05%)] / (8 / N)", with "N is Funding Interval" (S7). So `N` belongs to the rate it scales, which is the period ending at the
  settlement.
- **The API does not define it either.** `fundingInfo` lists `fundingIntervalHours` with no description, only for "symbols that had
  FundingRateCap/FundingRateFloor / fundingIntervalHours adjustment" (S3). `fundingRate` history labels its time "Funding Time" and gives
  no interval (S2). The change log adds `fundingInfo` on 2023-09-25 (S5).

### 1.2 What that means for R-01

- **Documented:** the rate at a settlement covers the interval ending there.
- **Not documented:** whether the archive's column, on the row where a change takes effect, carries that interval or the next one. That is
  `UNVERIFIED`. Reading it as the period ending at `calc_time` fits the formula, but it is an inference, and the code should not rest on it.
- **The first span cannot answer it.** If every row there is 8, both readings give the same schedule. Telling them apart needs a file that
  holds a change, which means another symbol or a later date. Neither is in this brief.
- **So R-01's simpler fix is the safe one:** count missing settlements in a stretch only when the rows at both ends agree on the interval,
  and log the stretch when they do not. It does not depend on the column's direction.

### 1.3 History of changes

| When | What | Source |
|---|---|---|
| 2023-10-12 08:00 UTC | 15 contracts from 8 h to 4 h: IMX, LPT, API3, HIFI, NMR, TRB, BLZ, DODO, STMX, CYBER, YGG, UNFI, FLM, PERP, AMB. Not BTCUSDT or ETHUSDT. 4 h settlements fall at 00:00, 04:00, 08:00, 12:00, 16:00 and 20:00 UTC | S8 |
| 2025-05-02 08:00 UTC | Any USDⓈ-M perpetual goes from "every eight hours or every four hours to every one hour" when the previous settlement reaches the cap or floor. The FAQ's worked example uses BTCUSDT, framed "as an example" | S7 |
| 2026-01-02 12:00 UTC | From 1 h back "to every four hours on the 17th cycle" after 16 cycles at or under 0.025% in absolute value | S7 |
| Any time | "Binance reserves the right to update the funding interval of a perpetual contract" | S7 |

**For later blocks.** From 2025-05-02, 8 h cannot be assumed on either symbol, and an unannounced change will not show in any announcement.
Only the files will show it. The check in 3.1 must run on every block's funding files before that block is used, and R-01's fix must be in
first.

## 2. The tick size

### 2.1 What the pages say

- **The rule.** `PRICE_FILTER`: "tickSize defines the intervals that a price/stopPrice can be increased/decreased by", and a price passes
  when "(price-minPrice) % tickSize == 0" (S6). The grid starts at `minPrice`, not at zero.
- **BTCUSDT.** "Updates on the Tick Size for BTC USDⓈ-M Perpetual Futures Contracts", published 2021-12-31: BTCUSDT from 0.01 to 0.1 "at
  2022-02-15 03:30 AM (UTC)". Also: "orders placed before the update will be matched with the original tick size" (S9).
- **No other change to either symbol** in the tick notices read, which take effect on 2021-05-11, 2021-06-01, 2021-11-15, 2021-12-13,
  2022-05-19, 2023-02-10, 2024-07-25 and 2024-11-28 (S10 to S16). That is a sample of notices found by search, not the whole archive.

### 2.2 What that means for the run

| Symbol | 2020-01-01 to 2022-02-15 03:30 UTC | 2022-02-15 03:30 UTC to 2023-12-31 | Config now |
|---|---|---|---|
| BTCUSDT | 0.01. Stated as "Before" in S9. That it held from 2020-01-01 is `UNVERIFIED` | 0.1 (S9) | 0.1, `UNVERIFIED` |
| ETHUSDT | `UNVERIFIED`. No change found | `UNVERIFIED`. No change found | 0.01, `UNVERIFIED` |

- **The engine holds one tick per symbol.** A single value cannot match BTCUSDT across the span.
- **0.1 for the whole span** gives only prices that were legal throughout, since every multiple of 0.1 is a multiple of 0.01. It is coarser
  than the venue before 2022-02-15.
- **0.01 for the whole span** gives prices that were not legal after 2022-02-15.
- **A dated tick needs a code change.** Which way to go is for `project-manager`, `developer` and `leak-auditor`. I have not edited the config.
- **Old orders.** Because orders placed before the change still matched at 0.01, BTCUSDT candles after 03:30 on 2022-02-15 may show prices
  off the 0.1 grid for a while. How long is `UNVERIFIED`. The check below expects this and does not fail on it.

## 3. A check on the files after the fetch

For `developer` to build and `python-reviewer` to review. Described here, not written. It runs in the stage one job after the checksum
check, on the first-span files only (the first span is open). Its output is counts, flags and minute times, never a price or a rate.

### 3.1 Funding files, 96 monthly files

| # | Check | Fails when |
|---|---|---|
| F1 | Every file has the header `calc_time,funding_interval_hours,last_funding_rate`. The parser already refuses anything else. Whether 2020 files carry this header is `UNVERIFIED` | Any file. Stage one stops on it, which is the right result |
| F2 | Every `funding_interval_hours` is 8, on both symbols | Any row. The run stops until R-01's fix is in. Print `calc_time` and the interval of each such row |
| F3 | Every `calc_time` is within 15 s of 00:00, 08:00 or 16:00 UTC, the FAQ's stated deviation (S7). Record the largest offset in ms | Any row past 15 s. Whether `calc_time` is the fee transaction time is `UNVERIFIED`, so a failure is reviewed, not corrected |
| F4 | One row per settlement: 1,461 days × 3 = **4,383 rows per symbol**, from 2020-01-01 00:00 to 2023-12-31 16:00 UTC. Count missing and duplicate settlements, across month boundaries too | Any duplicate. A missing settlement is reported and stays a `DATA_GAP` under C17, never filled |
| F5 | Consecutive rows are 8 h apart, after rounding each to its settlement | Any other gap not already counted in F4 |

If F2 to F5 all pass, R-01 cannot act on this run, whatever the column means.

### 3.2 Candle files, 96 monthly files

Prices are compared exactly. Parse the price text as a decimal, not as a binary float. If only floats are at hand, test
`abs(p - round(p / t) * t) < t * 1e-6`. Open, high, low and close are all tested. The grid is taken from zero. Since the venue's rule
starts at `minPrice`, which I could not read for these dates, a failure means "investigate", not "bad data".

| # | Check | Expected | Fails when |
|---|---|---|---|
| K1 | Every price on both symbols is a multiple of 0.01, every minute of the span | All pass | Any price. That would mean a finer tick or an offset grid. Stop and review |
| K2 | BTCUSDT before 2022-02-15 03:30: count months with at least one price off the 0.1 grid | All 26 months from 2020-01 to 2022-02. With K1, this shows the tick was 0.01 in each month, not coarser | A month with none. The 0.01 claim is then unproved for it |
| K3 | BTCUSDT from 2022-02-15 03:30: count minutes with any price off the 0.1 grid, and report the first and last such minute | Some, soon after the change, from orders placed before it. Then none | Not a failure. If they last for months, `data-steward` reviews it before choosing the tick |
| K4 | ETHUSDT: count months with at least one price off the 0.1 grid | All 48 months. With K1, this shows a 0.01 tick in each month | A month with none |
| K5 | Rows per symbol: 1,461 × 1,440 = **2,103,840**. Count missing and duplicate minutes | All present | Reported by the coverage check. It decides coverage, not ticks |

**Output.** Per symbol: pass or fail for F1 to F5 and K1, the counts in F4, K2, K3 and K4, the largest offset in F3, and the minute times in
F2 and K3. Recorded in the manifest's integrity result. No price, volume, rate or per-day series.

**What it settles.** F2 answers whether either symbol left 8 h in 2020 to 2023. K1 to K4 answer the ticks and date the BTCUSDT change in
the data. Neither settles the meaning of the interval column (1.2).

## 4. Pages read

| # | URL | What it says |
|---|---|---|
| S1 | https://github.com/binance/binance-public-data and https://raw.githubusercontent.com/binance/binance-public-data/master/README.md | USD-M futures data types listed as AggTrades, Klines and Trades. Klines columns given. No `fundingRate` dataset, no definition of its columns, nothing on tick size |
| S2 | https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History | `GET /fapi/v1/fundingRate`. `fundingTime` labelled "Funding Time", with no definition and no interval field |
| S3 | https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-Info | `GET /fapi/v1/fundingInfo`: "Query funding rate info for symbols that had FundingRateCap/FundingRateFloor / fundingIntervalHours adjustment". `fundingIntervalHours` has no description |
| S4 | https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price | `lastFundingRate`: "This is the Latest funding rate". `nextFundingTime`: "Next Funding Time". No note on intervals |
| S5 | https://developers.binance.com/docs/derivatives/change-log | 2019-10-14: "Added `GET /fapi/v1/fundingRate`". 2023-09-25: "`GET /fapi/v1/fundingInfo`: query adjusted funding info". No entry on `tickSize`, `PRICE_FILTER` or `fundingIntervalHours` |
| S6 | https://developers.binance.com/docs/derivatives/usds-margined-futures/common-definition | `PRICE_FILTER` rules, including "(price-minPrice) % tickSize == 0" |
| S7 | https://www.binance.com/en/support/faq/detail/360033525031 | "Introduction to Binance Futures Funding Rates", published 2019-09-09, updated 2026-03-06. Default 8 h schedule, 15 s deviation, the period a rate covers, the formula and `N`, the right to change intervals, and the 2025-05-02 and 2026-01-02 rules (section 1) |
| S8 | https://www.binance.com/en/support/announcement/important-updates-on-funding-rates-of-usd%E2%93%A2-m-perpetual-contracts-98d6b24d3e5c4f84a8ed04087997d8d0 | Published 2023-09-28. 15 contracts to 4 h at 2023-10-12 08:00 UTC, BTCUSDT and ETHUSDT not among them. 4 h settlement times. `fundingInfo` added |
| S9 | https://www.binance.com/en/support/announcement/updates-on-the-tick-size-for-btc-usd%E2%93%A2-m-perpetual-futures-contracts-81e6795b0bae49828cbd52479094a987 | Published 2021-12-31. BTCUSDT 0.01 to 0.1 at 2022-02-15 03:30 UTC. Old orders match at the original tick |
| S10 | https://www.binance.com/en/support/announcement/updates-on-tick-size-for-usdt-margined-perpetual-futures-contracts-2021-05-07-790cd97ae5d54cd6897ad4fc81ab477b | Effective 2021-05-11. 17 contracts, not BTCUSDT or ETHUSDT |
| S11 | https://www.binance.com/en/support/announcement/updates-on-tick-size-for-usdt-margined-perpetual-futures-contracts-2021-05-27-10e4069265794d1db0edf4a88a6be849 | Effective 2021-06-01. MATIC, HNT, EGLD, YFI. Not BTCUSDT or ETHUSDT |
| S12 | https://www.binance.com/en/support/announcement/updates-on-the-tick-size-for-usd%E2%93%A2-m-perpetual-futures-contracts-dbb7562c81ca4faea2ea84fe9669dec4 | Published 2021-11-03, effective 2021-11-15. OMG, REN. Not BTCUSDT or ETHUSDT |
| S13 | https://www.binance.com/en/support/announcement/updates-on-the-tick-size-for-usd%E2%93%A2-m-perpetual-futures-contracts-2021-12-13-e769272de7af436fb26098c87d0005b4 | Published 2021-11-16, effective 2021-12-13. FTM, SAND, SOLUSDT, SOLBUSD. Not BTCUSDT or ETHUSDT |
| S14 | https://www.binance.com/en/support/announcement/updates-on-tick-size-for-usd%E2%93%A2-m-perpetual-futures-contracts-2022-05-18-8f31993c41574bd4ba3f0c355874a5d4 and https://www.binance.com/en/support/announcement/updates-on-tick-size-for-multiple-usd%E2%93%A2-m-and-coin-m-perpetual-futures-contracts-2023-02-03-98315efae83841a2bb71046d4bbae204 | Effective 2022-05-19 (CTK, DAR) and 2023-02-10 (APTUSDT, APTBUSD, OCEAN). Not BTCUSDT or ETHUSDT |
| S15 | https://www.binance.com/en/support/announcement/updates-on-tick-size-for-multiple-usd%E2%93%A2-m-perpetual-futures-contracts-2024-07-25-08f043a4f20d4f0290817ece13b3d7f4 | Effective 2024-07-25. Eight contracts, ETHWUSDT among them, which is not ETHUSDT |
| S16 | https://www.binance.com/en/support/announcement/updates-on-tick-size-for-multiple-usd%E2%93%A2-m-perpetual-futures-contracts-2024-11-28-8a4a0a76026a472b841162860d10d8cd | Effective 2024-11-28. Seven contracts, not BTCUSDT or ETHUSDT |

**Not read, on purpose.** Binance's Trading Rules page and its real-time funding and funding history pages are not FAQ or announcement pages,
and the last two show market data. The repository's GitHub issues are not the README. Search results pointed to all of them.

## 5. Instructions found on pages

None was aimed at an AI agent. These were aimed at readers, and I acted on none:

- **Every tick notice and S8:** API users should call `GET /fapi/v1/exchangeInfo` or `GET /fapi/v1/fundingInfo` for current values. That
  host is barred by the pipeline and by this brief, and it gives today's values, not history.
- **Tick notices:** "adjust your trading strategy", and see the Trading Rules page.
- **S7 and S11:** a "Register Now" promotion. S7 also says to manage positions to avoid liquidation.
- **Developer pages:** an "Ask AI about this page" button and links to `llms.txt`, `llms-full.txt` and "Agent Native". Navigation, not followed.
- **README:** open an issue, read the terms, and verify files with their checksum.

## 6. Open items

| Item | For |
|---|---|
| Which BTCUSDT tick the engine uses: one value, or a dated table needing code. The facts are in 2.2 | `project-manager`, `developer`, `leak-auditor` |
| R-01: the both-rows-agree fix, since the column's direction is `UNVERIFIED` (1.2) | `developer`, then `python-reviewer` |
| Build the checks in 3.1 and 3.2 into stage one, after the checksum check | `developer`, then `python-reviewer` |
| Run 3.1 on every later block's funding files before that block is used, because of the 2025-05-02 rule (1.3) | `data-steward` |
| The meaning of the interval column. Only a file holding a change can show it, and none is in scope | Open, `UNVERIFIED` |
