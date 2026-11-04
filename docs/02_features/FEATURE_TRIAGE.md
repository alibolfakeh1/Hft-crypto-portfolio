# Feature triage

Status: draft for leak audit. Date: 2026-11-04. Owner: `feature-integrator`.

This document decides what happens to each of the 44 features in the external knowledge base
(`HFT_KB_PATH`) when moved from ES futures at high frequency to BTC and ETH at decision times of 5
minutes to 4 hours, under the operating decision `D-15`: **everything runs on GitHub, with no server.**

**Nothing here has been tested.** No code exists and no feature has been computed on crypto data. Every
statement about what a feature might do is a hypothesis. A `USE` or `ADAPT` decision means "worth
testing or needed as infrastructure", never "works". Anything not checked is marked `UNVERIFIED`.

Related documents: [decision point map](DECISION_POINT_MAP.md), [gate specification](GATE_SPEC.md),
[strategy feature matrix](STRATEGY_FEATURE_MATRIX.md).

## 1. Summary

| Decision | Count | Meaning | Features |
|---|---|---|---|
| `USE` | 1 | Canonical formula, sign and unit kept. Only the project conventions in section 2.5 apply | F01 |
| `ADAPT` | 16 | Carries over only with a stated change, under a derived ID | F02, F05, F16, F18, F19, F23, F24, F25, F26, F27, F28, F35, F37, F39, F41, F42 |
| `LATER` | 21 | Blocked by data or by a dependency that has not yet shown value. Ten of these need `T3`, which cannot be recorded here | F03, F07, F08, F09, F10, F11, F12, F13, F14, F15, F17, F20, F21, F22, F29, F30, F32, F33, F40, F43, F44 |
| `DROP` | 6 | No credible path to a decision here, or redundant by construction, for reasons that a server would not change | F04, F06, F31, F34, F36, F38 |

Of the 17 `USE` and `ADAPT` features, **only nine can ever feed a live paper decision on this setup**: F18,
F19, F23, F24, F25, F26, F27, F39 (`T1` form only) and F41. A further three support them without being return
hypotheses: F42 is a control, F37 a frame and F35 a report metric. F01, F02, F05, F16 and F28 are research only
on this setup. See section 2.2.

Six conclusions drive the table:

1. **Nothing that could be a return signal carries over unchanged.** The one `USE` feature is a validity check.
2. **Net survives, gross does not.** Net flows and time-averaged book state keep their meaning at minutes and
   under 100 ms conflation. Gross add and cancel flows, order lifetimes, queue position and atomic event
   structure do not.
3. **ES is a large-tick market and BTC is not.** Queue and tick-grid features assume long queues at a one-tick
   spread. See section 2.4.
4. **The gate does not have to clear the fee on its own**, but it must beat a random veto, which also looks good
   when costs are high. See section 5.5.
5. **The hourly cycle leaves a filter, not a timing tool.** A veto at a bar close mostly survives. `ENTER` timing,
   `WAIT` and fast flow exits are largely destroyed. See section 5.7. The project's question "whether and when to
   enter, and when to exit" can be tested live only for "whether", and crudely for "when to exit". The "when" can
   still be studied in research-only backtests.
6. **Statistical power is the other hard limit.** Fast strategies have samples but pay the most cost in `R`, and they
   cannot run live here. Slow ones tolerate cost but have few setups. The prediction for each live strategy's entry gate,
   alone, is `INCONCLUSIVE`. See [the matrix](STRATEGY_FEATURE_MATRIX.md#4-can-each-gate-question-be-answered).

First tests, in order, all live-eligible on `T1`: `F24-X1`, then the response family `F18-X1`, `F19-X1` and
`D-RR18-X1`, then the risk checks `F41-X1` and `F39-X2`, then `F26-X1` as an hourly summary. The reasons are in
section 7.

## 2. Conventions

### 2.1 Decisions

`ADAPT` always carries a derived ID, defined in section 4. Canonical IDs are never renumbered or redefined. A
`LATER` or `DROP` feature keeps its canonical definition, unused. A `LATER` feature that is revived gets its
derived ID and document then.

### 2.2 Live-eligible and research-only

Two kinds of variant exist. They are never mixed, and a result from one is never presented as evidence for the
other. The full rules are in [the gate specification](GATE_SPEC.md#2-two-kinds-of-variant).

| Kind | Suffix | Clock | Inputs | Timeframes | Can it become a live paper position? |
|---|---|---|---|---|---|
| Live-eligible | `.L` | `CYCLE` under C17 of the strategy conventions, with delays and dropped runs reproduced | `T1` from the poll source, and candles | 1h, 4h | Yes |
| Research-only | `.R` | `IDEAL` under C5 to C7, with a finer look grid, not achievable on this setup | Any `T1`, `T2` archives | 5m to 4h | No, not without an always-on machine (decision `D-04`) |

Live-eligibility of each derived ID:

| Derived ID | Live? | What is left on the hourly cycle | What is lost |
|---|---|---|---|
| `F24-X1`, `D-SV18-X1` | Yes | Balance over the last 60 or 240 minutes, at each run | Any reaction inside the hour |
| `F18-X1`, `F19-X1`, `D-RR18-X1` | Yes | Response over the last 60 or 240 minutes | Seeing absorption as it happens at a level |
| `F27-X1` | Yes | Recomputed after the fact from the last hour's trades | Acting at the touch |
| `F26-X1`, `F25-X1` | Yes, as window summaries only | "A sweep happened in the last hour" | Event response. A sweep can be over 60 minutes old when first seen |
| `F23-X1` | Yes | Run of same-sign minute bars ending at the run | Little, since it is slow by design |
| `F41-X1`, `F39-X2`, `F42-X1` | Yes | Slow state is mostly intact | Cannot stop an entry into a cascade that began minutes earlier |
| `F37-X1` | Yes, with a live-eligible input | Hourly conflict check | Fast exits |
| `F35-X1` | Metric only | Not applicable | Not applicable |
| F01, `F01-X1`, `F05-X1` | Snapshot for the record only | Spread and fill distance at the decision. See section 5.8 | The time series |
| `F02-X1`, `F02-X2`, `F16-X1`, `F16-X2`, `F39-X1`, `D-OF31-X1`, `F28-X1` | **No, research only** | Nothing live | Everything live |

### 2.3 Data tiers and history

Tiers are those of the [charter](../00_CHARTER.md#4-data-tiers). A recipe's testable history is limited by its
highest tier. Start dates were read from the archive listings on 2026-11-04. File contents were not opened by this
author, except where [the data center document](../08_DATA_CENTER.md) records a measurement.

| Code | Source | Span | Length at 2026-11-04 | Notes |
|---|---|---|---|---|
| `H-T0` | Official 1-minute candles with `taker_buy_volume` | Start not checked | `UNVERIFIED`, expected at least `H-T1a` | Signed flow at bar level. Trade-built bars remain canonical (`D-12`), so official bars are a screen and a reconciliation check |
| `H-T1a` | Binance USD-M `aggTrades`, BTCUSDT and ETHUSDT | From 2020-01 | 6.8 years | Best research candidate. Its REST source may not be usable live. See section 5.6 |
| `H-T1b` | Bybit linear trades | BTC from 2020-03-25, ETH from 2020-10-21 | 6.6 and 6.0 years | Native taker side |
| `H-T1c` | Binance spot `aggTrades`, BTCUSDT | From 2017-08 | 9.2 years | Spot flow, for research and venue tests. Not a live-eligible source unless the owner confirms under `D-01`. See section 5.6 |
| `H-T2a` | Bybit linear L2 ladder | `ob500` 2023-01-18 to 2025-08-20, then `ob200` from 2025-08-21, same dates for BTC and ETH | 3.8 years with a format break | 100 ms conflated, measured on one `ob200` day. Cadence of `ob500` is `UNVERIFIED`. Next-day archive, so research only |
| `H-T2b` | Binance USD-M `bookDepth` | From 2023-01-01 | 3.8 years | Cumulative depth at ±0.2% and ±1% to ±5%, about every 30 s. State only, no flows. Next-day archive, so research only |
| `H-T2c` | Binance USD-M `bookTicker` | 2023-05-16 to about 2024-03 | Under 1 year, apparently discontinued | No file listed at or after 2024-04-01. Reconciliation use only |
| `H-T3` | Own recording | **None** | **0 days, and it cannot start on this setup** | Needs a continuous connection. See decision `D-04` |

After an initial training span, this leaves roughly 5.3 years of out-of-sample blocks for a `T1` recipe (18 months'
training) and 2.8 years for a `T2` recipe (12 months' training). That is a planning proposal, not a measurement.

**Known structural breaks inside this history:**

- **Bybit book depth format**, 2025-08-21 (`ob500` to `ob200`). Features must use a depth reachable in both formats.
- **Retail price improvement (RPI) orders.** Binance introduced them on USD-M futures in November 2025. They are
  excluded from depth data, match only non-algorithmic orders, and are aggregated in `aggTrades` with no tag according
  to its FAQ, while `isRPITrade` appears on the trade lists. Bybit's documentation also excludes RPI orders from its
  order book stream and flags RPI trades. Trades can therefore print against liquidity the book does not show. Whether
  this changes flow features is `UNVERIFIED`.

### 2.4 Why tick-based definitions do not transfer

| Instrument | Tick | Tick in basis points (illustrative prices) |
|---|---|---|
| ES | 0.25 | About 0.4 at an index level of 6,000 |
| BTCUSDT perpetual (Binance rules page) | 0.10 | 0.01 to 0.017 at 100,000 to 60,000 |
| ETHUSDT perpetual (Binance rules page) | 0.01 | About 0.03 at 3,000 |
| BTC-USD spot (Coinbase) | 0.01 | 0.001 to 0.0017 at 100,000 to 60,000 |

An ES tick is about 25 to 40 times coarser in relative terms than a BTC perpetual tick. A fixed ladder of 10 ticks
spans about 0.1 to 0.17 bps on BTC, which is no economic distance at all. One preprint on Binance perpetuals reports,
as a cross-asset association and not a formal test, that imbalance matters more for instruments with larger relative
ticks (Bieganowski and Ślepaczuk, 2026). That fits the concern but does not settle it for our data.

### 2.5 Project conventions for every feature

These apply to `USE` and `ADAPT` alike, and they are not repeated in the table.

| ID | Convention | Why it differs from the knowledge base |
|---|---|---|
| G1 | **Clock.** Windows are `(t - W, t]` on the exchange clock, and a record may be used only if it was available by `t`. On the live path, availability is the poll's receive time, and all features use completed minute bars up to the last one before `t_dec`, as in [the gate specification](GATE_SPEC.md#31-run-timeline). Archives have no receive time, so backtests apply the same rule with the allowance in C17 (`.L`) or a declared allowance `A` per stream (`.R`) | Task 0 of the knowledge base excludes receive time. The [timing contract](../00_CHARTER.md#3-timing-contract), items 6 and 13, overrides it for this project |
| G2 | **No complete-event assumption.** The atomic unit is one venue message or one conflation bucket | CME's event-based packets have no equivalent in these feeds |
| G3 | **Units.** Prices in bps of mid, quantities in quote notional. Ticks serve validity checks only | Section 2.4. Contract counts do not compare across venues or over time |
| G4 | **Native sign.** `z = +1` when the taker buys. Per-venue mapping is in section 5.6 and needs a mirror test. No tick-rule inference. Unknown sign is ineligible | Most venues publish a side, but the field means different things per venue |
| G5 | **Venue scope.** Every value carries its venue and instrument. Pooling across venues is a separate derived field with a `-P` suffix | ES has one primary venue |
| G6 | **Calendar.** No sessions. `hour_of_week`, `qh_phase` and `funding_phase` replace them. See section 5.4 | 24/7 market |
| G7 | **Missing is invalid.** Never zero, never imputed. A window with verified continuity and no trades is valid and has zero flow, but ratios on it fail their support rule | Same principle as the knowledge base, restated because quiet and missing look alike in crypto data |
| G8 | **Flow population.** Block trades are excluded where flagged. RPI trades stay in the primary definition because `aggTrades` cannot separate them. A sensitivity on tagged trade lists covers the period since the break | No ES equivalent |
| G9 | **Fitted values.** Anything estimated across a sample, such as a threshold, is fitted on past data and frozen, as in [the gate specification](GATE_SPEC.md#8-fitting-and-freezing). A fixed-window causal statistic, such as a rolling percentile, needs no freezing, under item 10 of the timing contract. No epsilon repairs. A ratio that fails its support rule is invalid | Same principle as the knowledge base, with the charter's ruling on rolling statistics |

## 3. The 44 features

"Live" shows whether the feature can drive a live paper decision: **yes**, **no** (research only), **record** (snapshot
logged, no decision), **metric** (never an input), or a dash for a feature with no planned use.

"At minutes, 100 ms" states whether the feature keeps its meaning at minutes and what 100 ms conflation of a `T2` archive
does to it, as seen from a 5-minute decision: **harmless**, **biased** or **destroyed**. `T1` features have no conflation
issue. A 5-minute window holds 3,000 conflation buckets, so state features are not hurt by bucket width. Features built from
events inside a bucket are.

| ID | Title | Decision | Tier | Live | History | At minutes, 100 ms | Reason | ES to crypto |
|---|---|---|---|---|---|---|---|---|
| F01 | Spread State | `USE` (cost via `F01-X1`) | `T2` L1 | record | `H-T2a` | Harmless. State read at `t`. Transition timing is lost at minutes | Validity check for locked, crossed or missing quotes, and the base of the cost input in research. Live, one snapshot per run goes in the record. No direction assumed | Formula unchanged on each venue's own tick. Costs are read in bps through `F01-X1` |
| F02 | Relative Touch Depth | `ADAPT` `F02-X1`, `F02-X2` | `T2` | no | `H-T2a`, `H-T2b` | Harmless as a time mean. Instantaneous touch size lasts seconds, so only the mean is meaningful | Unsigned thin-book state. Candidate for stress and slippage conditioning, in research | Touch becomes a bps band, session bucket becomes hour of week, contracts become notional |
| F03 | Depth Concentration | `LATER` | `T2` | - | `H-T2a` | Harmless for state, but its mechanism acts at depletion, which is sub-second | Shape can only matter after depth level does. Test `F02-X1` first | Tick ladder would need a bps ladder |
| F04 | Depth Entropy | `DROP` | `T2` | - | `H-T2a` | Harmless, yet not useful | Blind to where depth sits, and at risk of duplicating depth level and shape. Not worth a trial at this horizon | Would need bps bins |
| F05 | Liquidity Gap | `ADAPT` `F05-X1` | `T2` | record | `H-T2a` | Harmless. State at `t` | Input for slippage and order style in research, not a return hypothesis. First-level gaps on a very fine tick are likely grid noise, `UNVERIFIED` | First gap in ticks becomes distance in bps to fill a notional |
| F06 | Bid–Ask Gap Asymmetry | `DROP` | `T2` | - | `H-T2a` | Harmless, yet redundant | A deterministic transform of two gaps, so not independent evidence. A model can use both sides of `F05-X1` | None needed |
| F07 | Average Order Size | `LATER` | `T3` | - | `H-T3` | Destroyed. No order identity in L2 | **Needs `T3`, which cannot be recorded without an always-on machine.** Even then, low priority: it feeds queue models and has no mechanism at minutes | Would need a venue with order ids. Size unit differs |
| F08 | Order-Size Concentration | `LATER` | `T3` | - | `H-T3` | Destroyed | **Needs `T3`.** Same as F07 | Same as F07 |
| F09 | Persistence-Weighted Depth | `LATER` | `T3` | - | `H-T3` | Destroyed. No order age in L2 | **Needs `T3`.** Could test whether a large displayed order at a zone is durable | Decay constants move from seconds to minutes. A level-based lower bound on `T2` would be a separate derived field, not F09 |
| F10 | Fleeting Liquidity Ratio | `LATER` | `T3` | - | `H-T3` | Destroyed. Lifetimes under the bucket width are invisible | **Needs `T3`.** Could condition trust in `F16-X1`, but only after `F16-X1` shows value | Window moves to minutes, age thresholds stay short |
| F11 | Cancel-to-Add Ratio | `LATER` | `T3` | - | `H-T3` | Destroyed. Adds and cancels net inside a bucket. Inferred proxies are lower bounds only | **Needs `T3`.** Explicit classification exists only in order-level feeds | Windows to minutes. Measures only the recorded venue |
| F12 | Cancel-to-Trade Ratio | `LATER` | `T3` | - | `H-T3` | Destroyed for the same reason | **Needs `T3`.** Separates withdrawal from consumption, which is a good question | As F11 |
| F13 | Queue Survival Probability | `LATER` | `T3` plus model | - | `H-T3` | Destroyed | **Needs `T3`.** Even then, low priority: a survival model for a resting order, and no resting orders are in scope | Not applicable |
| F14 | Queue Half-Life | `LATER` | `T2` | - | `H-T2a` | Biased. Recovery over seconds is visible, faster recovery is not | Summarises prior shocks, so it needs the `F28-X1` episode table first | Touch becomes a band, horizons move to minutes |
| F15 | Queue Churn | `LATER` | `T3` | - | `H-T3` | Destroyed. Gross turnover nets away | **Needs `T3`.** Even then, low priority: likely measures quote maintenance rather than anything a 5-minute decision can use, `UNVERIFIED` | Not applicable |
| F16 | Imbalance Persistence | `ADAPT` `F16-X1`, `F16-X2` | `T2` | no | `H-T2a`, `H-T2b` | Harmless. A time mean of state. A 1 s grid should do, and this is testable | The main book-imbalance candidate, and the owner's core question. Instantaneous imbalance is unlikely to last to a 5-minute decision, so persistence is the form with a chance. **Research only here** | Touch becomes a band, windows move from under 5 s to 1 to 240 minutes |
| F17 | Imbalance Flip Rate | `LATER` | `T2` | - | `H-T2a` | Biased. Flip counts depend on the sampling interval, so the grid must be fixed | Reliability modifier for `F16-X1`. Pointless if `F16-X1` fails | Band imbalance, fixed grid, dead zone around zero |
| F18 | Price Response per Signed Volume | `ADAPT` `F18-X1` | `T1` | yes | `H-T1a`, `H-T1c` | Survives. No conflation issue | Price progress per unit of flow. The basic measure for telling absorption from breakthrough | Mid endpoints become short VWAPs, ticks per contract become bps per normal volume |
| F19 | Local Kyle Lambda | `ADAPT` `F19-X1` | `T1` | yes | `H-T1a`, `H-T1c` | Survives with a longer fit | The "normal response" reference for `D-RR18-X1`, and a fragility state | Sub-window 1 minute, fit 24 hours, refit every 15 minutes on `.R` and at each run on `.L` |
| F20 | Impact Surprise | `LATER` | `T1`, `T2` | - | `H-T1a`, `H-T2a` with book inputs | Survives in form | Earns credit only for book-state conditioning beyond `D-RR18-X1`. Needs a frozen model, so it comes after that family | Windows to minutes, frozen model refit on crypto |
| F21 | Post-Trade Relaxation | `LATER` | `T1` | - | `H-T1a` | Survives only as a landmark. Unavailable at the anchor event | Could time entry after a spike in research, once `F26-X1` events exist. No live use at an hourly look | Landmarks in minutes |
| F22 | Flow Saturation | `LATER` | `T1`, `T2` | - | `H-T2a` | Biased. Book order flow imbalance is approximate across buckets | Unsigned transform of the same inputs as F18. The knowledge base itself leaves its input and window open | Test `D-OF31-X1` first |
| F23 | Trade Run Length | `ADAPT` `F23-X1` | `T1` | yes | `H-T1a`, `H-T1c` | Canonical form loses meaning: a trade run at `t` is a seconds-scale accident, and counts depend on how a venue splits fills. A run of minute bars survives | Simple persistence measure, mainly for exit | Trades become 1-minute net flow bars |
| F24 | Trade-Sign Entropy | `ADAPT` `F24-X1` | `T1`, `T0` screen | yes | `H-T1a`, `H-T1c`, `H-T0` | Signed balance survives. Entropy adds nothing, since it is determined by the balance when signs are binary | Primary flow feature and the bar every other flow feature must beat | Balance only, in notional, windows in minutes |
| F25 | Large-Trade Surprise | `ADAPT` `F25-X1` | `T1` | yes, as a summary | `H-T1a`, `H-T1c` | Survives as a window summary | Whether unusually large taker orders point the same way as the setup. Second wave | Unit becomes the `F26-X1` burst, size in notional, reference prior 7 days |
| F26 | Sweep Penetration | `ADAPT` `F26-X1` | `T1` | yes, as a summary | `H-T1a`, `H-T1c` | Canonical form destroyed: no event boundaries, and the ladder is up to 100 ms old. A trade-only proxy survives | Event veto in research: do not enter against a sweep that just happened. Live, it degrades to an hourly summary. Liquidation cascades may show up here, `UNVERIFIED` | Atomic event becomes same-timestamp, same-sign burst. Levels cleared become walk in bps |
| F27 | Absorption Efficiency | `ADAPT` `F27-X1` | `T1` | yes, after the fact | `H-T1a`, `H-T1c` | Survives when anchored to a zone | Natural fit for zone setups. Same family as F18, so not an extra vote | Price level becomes the setup's zone, tick floor becomes an ATR floor |
| F28 | Refill Elasticity | `ADAPT` `F28-X1` | `T2` | no | `H-T2a` | Harmless for landmarks of 1 s or more. Pre-event depth can be up to 100 ms stale, which biases the ratio | Entry timing after a sweep, in research. Only the to-date stock measure can be an input. Second wave | Band of prices walked, landmarks in minutes |
| F29 | Absorption Duration | `LATER` | `T1` | - | `H-T1a` | Current duration survives. Final duration is never an input | Cheap, but only after `F27-X1` | Time at a setup's zone |
| F30 | Breakout after Absorption Failure | `LATER` | `T1` | - | `H-T1a` | Survives after an observed break only | Relevant to breakout setups, but depends on F27 and F29 | Observed break of a setup's level |
| F31 | Momentum–Reversal Score | `DROP` | `T1`, `T2` | - | `H-T2a` | Partly destroyed. Depletion and replenishment net inside a bucket, leaving only their difference | Fixed-weight composite with few independent inputs. `D-OF31-X1` stays as a research control | Not applicable |
| F32 | Queue Value | `LATER` | `T3` plus fill model | - | `H-T3` | Destroyed | **Needs `T3` for queue position.** Also assumes a resting quote that is out of scope, so very low priority | Not applicable |
| F33 | Fill-to-Adverse-Move Race | `LATER` | `T3` plus fill model | - | `H-T3` | Biased on L2. Queue position is unknown | **Needs `T3` for a credible queue.** The only queue feature with a directional meaning: will a passive entry fill before price runs away? | Minutes-scale race, conservative fill rule |
| F34 | Cancel Success Probability | `DROP` | Own order path | - | None | Not applicable | Needs own send and acknowledgement times. No real orders exist here | Not applicable |
| F35 | Opportunity Cost of Not Filling | `ADAPT` `F35-X1` | `T1` | metric | `H-T1a` | Not applicable | Report metric for rejected setups, required by the charter. **Never a live input** | Counterfactual result of a rejected setup instead of a modelled fill |
| F36 | Inventory-Adjusted Fair Value | `DROP` | Not applicable | - | None | Not applicable | Market-making reservation price. Size comes from the initial stop and exposure belongs to the portfolio layer | Not applicable |
| F37 | Inventory–Flow Conflict | `ADAPT` `F37-X1` | `T1`, or `T2` for `.R` | yes, with a `T1` input | Same as input | Survives. It is a sign product | Names the frame "flow against my position". Adds no information of its own | Position replaces inventory, normalised flow replaces calibrated alpha |
| F38 | Quote Edge Buffer | `DROP` | Model output | - | None | Not applicable | Built on inputs not used here. The cost check is plain arithmetic at the order layer | Not applicable |
| F39 | Liquidity Stress Index | `ADAPT` `F39-X1`, `F39-X2` | `T2`, `T1` | `F39-X2` only | `H-T2a`, `H-T1a` | Harmless for the kept parts. The cancel part is destroyed and removed | Risk check. Can only block entries or reduce risk | Cancel part removed, windows in minutes, hour of week replaces session phase. The `T1` variant is live-eligible and extends history |
| F40 | Volatility of Volatility | `LATER` | `T0`, `T1` | - | `H-T1a` | Survives with longer windows | Likely overlaps `F41-X1` and `F39-X2`. Add only if those leave stress losses unexplained | Inner and outer windows in hours |
| F41 | Jump Score | `ADAPT` `F41-X1` | `T0`, `T1` | yes | `H-T1a`, `H-T1c` | Survives at a 1-minute grid | Discontinuity flag for the risk check. Not a direction signal | Grid 1 minute, scale window 24 hours, bps |
| F42 | Volume-Time Position | `ADAPT` `F42-X1` | `T0`, `T1` | yes, as a control | `H-T1a`, `H-T1c` | Survives without a session | Activity control used across the gate. Also a seasonal reference | Rolling volume against hour-of-week profile instead of cumulative session volume |
| F43 | Time Since Last Midpoint Change | `LATER` | `T2` L1 stream | - | `H-T2a` | Hazard meaning is lost at minutes. Timing is truncated to 100 ms | Its only use here would be a feed watchdog, and with no feed there is nothing to watch. Run health is defined in [the gate specification](GATE_SPEC.md#34-run-health) instead. Revive with an always-on machine | Formula unchanged if revived |
| F44 | Regime-Conditional Feature Reliability | `LATER` | Any | - | Needs completed folds | Not applicable | Setup counts are too small to fill regime cells. Only worthwhile once two features survive | Regimes from `hour_of_week` and risk state |

## 4. Derived IDs and their exact changes

Notation: `t` is the decision time, `W` the window, and a record is in the window under G1. `n_j` is trade notional and
`z_j` the taker sign. `E_W(t)` is the expected traded notional for a window of length `W` at `hour_of_week(t)`, from
`F42-X1`. Window lengths per decision timeframe are in [the gate specification](GATE_SPEC.md#32-windows-on-the-cycle). Default
constants were chosen without reference to outcomes and are declared, not fitted.

### Flow, `T1`, live-eligible

All of these can be computed at a run from polled trades or trade-built minute bars. The same code runs on the archive for
backtests.

**`D-SV18-X1` signed notional.** Derived from `D-SV18`. `VS_W = sum(z_j * n_j)` and `VA_W = sum(n_j)`. Change: notional replaces
contract quantity. `NS_W = VS_W / E_W` expresses flow in units of normal volume. Invalid if the unknown-sign share exceeds 1%, or
if continuity is not verified across the window.

**`F24-X1` volume balance.** Parent F24. `B_W = VS_W / VA_W` in `[-1, 1]`. Changes: only the balance output is used, with no
entropy trial. Windows in minutes. Valid only if `VA_W >= 0.1 * E_W`. The count-based balance is a single registered sensitivity.

**`F18-X1` price response.** Parent F18. `PRE_W = dP_W / NS_W`, with `dP_W = 1e4 * (P(t) - P(t-W)) / P(t-W)` and `P(u)` the
notional-weighted price of trades in the last completed minute ending at `u`. Changes: short VWAP endpoints replace mid, so the
feature needs only `T1`. Unit is bps per unit of normal volume. Valid only if `abs(NS_W) >= v_min`, with `v_min` the training-fold
median of `abs(NS_W)`, fitted with no outcome.

**`F19-X1` local lambda.** Parent F19. Huber fit, tuning 1.345, of `dP_i = a + lambda * NS_i` on non-overlapping 1-minute sub-windows
over the trailing 24 hours, 6 hours as a single sensitivity. Refit every 15 minutes on `.R` and at each run on `.L`. A scored window
starting at `t0` uses only a fit ending at or before `t0`. Valid only with 70% or more valid sub-windows and `lambda > 0`. No fallback prior. The change from the canonical parameters is
the time scale.

**`D-RR18-X1` response ratio.** Derived from `D-RR18`. `RR_W = PRE_W / lambda`, from `F18-X1` and `F19-X1`. About 1 means normal
response, about 0 absorbed, below 0 moved against the flow. Tested as one family with its two inputs, never as extra votes.

**`F26-X1` taker burst.** Parent F26. Consecutive trades with an identical venue match timestamp and an identical sign form one
burst. Fields: `burst_notional`, `n_prices`, and `walk_bps = 1e4 * z * (p_last - p_first) / p_first`. A sweep is a burst with
`n_prices >= 2` and `walk_bps >= 2`, 5 as a single sensitivity. Window outputs: `SW_W = sum(z * n)` over sweeps, divided by `E_W`, and
the largest `walk_bps`. Changes: no complete event exists, so a burst is a proxy that can merge two takers in the same millisecond or
split one. `levels_cleared` is unavailable. A mixed-sign group is invalid. Its validity is weakly checked. See section 8, check D3.

**`F25-X1` large burst.** Parent F25. Robust score `(log(1 + n) - M) / MAD` on the prior 7 days of bursts on the same instrument, with
the current burst added only after scoring. Output `LS_W = sum(z * n * 1{score >= 3}) / VA_W`. Invalid if `MAD = 0` or fewer than 100
prior bursts. Changes: burst unit, notional size, longer reference.

**`F23-X1` flow bar run.** Parent F23. The number of consecutive complete 1-minute bars ending at `t` whose `VS` has the same nonzero
sign, with its net `NS`. An invalid or zero bar breaks the run. Change: bars replace trades.

**`F27-X1` zone absorption.** Parent F27. Episode from the first trade inside the setup's zone within the window. `AE = NS_abs /
(progress + 0.05)`, where `NS_abs` is taker notional pushing into the zone since the episode began, in units of normal volume, and
`progress` is the farthest move through the zone edge in that direction, in units of the strategy's `ATR`. Changes: zone replaces price
level, an ATR floor replaces the one-tick term, which would be near zero here. Only the current value is an input.

**`F42-X1` relative volume.** Parent F42. `RV_W = VA_W / E_W`, usually as its log, with `E_W` the median over the prior 8
same-`hour_of_week` buckets, recomputed at each run, valid with 6 or more. Primary `W` is 60 minutes. Changes: rolling window instead of a
session reset, hour of week instead of the session taxonomy. A sensitivity resets at 00:00 UTC. At one `T_d` bar, this is nearly the same
quantity as `SRV` in C3 of the strategy conventions, in notional and with a stricter support rule, so where a strategy already uses `SRV`,
`F42-X1` serves as a control and not a gate input.

**`F41-X1` jump score.** Parent F41. `JS = abs(r_1m) / BV`, with `r_1m` in bps and `BV` the bipower scale of 1-minute returns over the
trailing 24 hours, ending at or before the start of the current return. 6 hours is a single sensitivity. On the cycle, the input is
`JSmax_60`, the largest `JS` in the last 60 minutes. Changes: 1 minute grid and 24 hour scale in place of the canonical 100 ms and 30 s.
The minimum-scale rule stays.

**`D-RV40-X1` realized volatility.** Derived from `D-RV40`. `sqrt(sum(r_1m^2))` over 60 minutes.

**`F39-X2` stress, `T1` only.** Parent F39. Probit-rank sum, frozen in training, of `D-RV40-X1`, `log RV_60m` and the illiquidity ratio
`sum(abs(r_1m)) / sum(n_1m)` over 60 minutes, each with weight +1. Changes: book parts replaced, so it runs live and has history back to
2020. Not comparable in level with `F39-X1`.

**`F35-X1` rejected setup result.** Parent F35. The simulated net `R` that a vetoed, expired or skipped setup would have made under its
`V0` rule on the same clock. A `STALE_SETUP` is also rejected by `V0` on the cycle, so its counterfactual is its `IDEAL` result, as C17 states.
**Evaluation only.** Available only after the setup's label matures, so it can never be an input.

**`F37-X1` position flow conflict.** Parent F37. `C = -s * (2 * pct(x) - 1)`, with `s` the position side and `pct(x)` the rolling percentile
from [the gate specification](GATE_SPEC.md#4-normalisation). Positive means flow against the position. Changes: position replaces
inventory, normalised flow replaces calibrated alpha. A deterministic frame, so it never counts as separate evidence.

### Book, `T2`, research only

These exist only in next-day archives. **None can drive a live paper decision on this setup.** The band half-width `b` is set by the reach
rule in section 8, check D1, before any outcome is seen. `D_side(u)` is displayed notional within `b` bps of mid on that side, from the
latest state at or before `u`. A band that passes the ladder's edge is invalid, never treated as empty.

**`F01-X1` spread in bps.** Parent F01. `SB = 1e4 * (ask - bid) / mid`, with a time mean on a 1 s grid.

**`F02-X1` relative band depth.** Parent F02. Time mean of `D_bid + D_ask` over `W` on a 1 s grid, divided by the median of that
bucket over the prior 8 same-`hour_of_week` buckets, valid with 6 or more. Side-specific forms are validated separately. **`F02-X2`** is the
same quantity from `bookDepth` at ±0.2%, on its 30 s grid.

**`F05-X1` fill distance.** Parent F05. `IMP_N = 1e4 * abs(p(N) - mid) / mid`, with `p(N)` the marginal price that fills notional `N` by walking
the visible ladder on that side. `N` is the intended order size. Invalid when the ladder ends first. RPI liquidity is not visible, so this
estimates visible depth only.

**`F16-X1` band imbalance persistence.** Parent F16. `I(u) = (D_bid - D_ask) / (D_bid + D_ask)` on a 1 s grid, with the three canonical
summaries kept separate: signed mean, absolute mean, and share of time on the current sign. Valid with 95% or more of grid points valid.
Changes: band for touch, grid mean for integral, windows in minutes. **`F16-X2`** is the same from `bookDepth` at ±0.2% on its 30 s grid, for
`W` of 5 minutes or more.

**`D-OF31-X1` conflated order flow imbalance.** Derived from `D-OF31`. The canonical best-level terms summed across consecutive conflated
states over `W`, divided by `E_W`. Change: buckets replace complete events, so only net change per bucket is seen. Check D7 measures part of
the damage.

**`F28-X1` band refill to date.** Parent F28. After an `F26-X1` sweep, the ratio of displayed notional at the prices walked, at landmark `u`, to
that notional in the last state before the burst. `u` is 30 s, with 2 minutes as a single sensitivity. A landmark creates a new decision, and
its target starts after it. Pre-burst depth may be up to 100 ms stale and is flagged. Change: band and time scale. Elasticity itself remains
a label.

**`F39-X1` stress, `T2`.** Parent F39. Probit-rank sum, frozen in training, of `F01-X1` mean, minus `log F02-X1`, `D-RV40-X1`, and `log RV_W`, with
weights +1, -1, +1, +1. Change: the canonical cancel part is removed because it is not available below `T3`.

## 5. Answers to the required questions

### 5.1 Which features survive aggregation from milliseconds to minutes?

Survival here means the number keeps its meaning. It says nothing about whether it predicts anything.

| Class | Features | Why |
|---|---|---|
| Slow state and regime | F39, F40, F41, F42 (F44 once folds exist) | Already about state. Only time constants change |
| Net trade flow and response | F18, F19, F20, F22 as a `T1` form, F24 balance, F25 as a window summary | Sums and slopes of signed notional scale with time |
| Time-averaged book state | F01, F02, F05, F16, and F03 in form | A sampled state is still a state, but only the mean or the persistence lasts to a 5-minute decision |
| Event features, once re-anchored | F14, F21, F26, F27, F28, F29, F30 | Survive only as an event or landmark measured in seconds or minutes, or anchored to a setup's zone |
| Lose their meaning | F43 hazard, F23 as a trade run, F17 in its millisecond form | Their information exists at a timescale that a 5-minute decision cannot use |
| Order lifecycle | F07, F08, F09, F10, F11, F12, F13, F15 | Not computable from L2 at all. See 5.2 |
| Execution and policy | F32 to F38 | See 5.3 |

An untested but important caveat: survival does not imply independent value. At a bar close, price has already moved with the same flow, so
aligned flow may just re-measure the bar. `D-RR18-X1` and the control on window return in
[the gate specification](GATE_SPEC.md#11-evaluation-requirements) exist for this reason.

**Surviving aggregation to 5 minutes is not the same as being live-eligible.** Live, the shortest usable look is an hourly one. See 5.7.

### 5.2 Which features need order-level data that exists only going forward?

**Need `T3` in canonical form:** F07, F08, F09, F10, F13 (order identity and age), F11, F12, F15 (explicit add and cancel classification), and F32,
F33 (credible queue position). All ten are `LATER`, for one reason: **`T3` needs a continuous connection, and on this setup it cannot be recorded.**
Nothing in this project plans around them. Every day without recording is lost for good, and that is accepted under `D-15`. If an always-on
machine is added (`D-04`), recording should start at once.

F34 also needs own order timestamps, but it is `DROP` because no real orders exist, which a server would not change.

**What `T3` would actually give, if recorded.** The charter records a 60-second book rebuild from Bitstamp `live_orders`. In the documentation I could
read, Coinbase's `full` channel and Kraken's `level3` both require authentication. I found no public order-level feed for the Binance or Bybit
perpetuals in the pages I opened, `UNVERIFIED`. So `T3` features would measure a venue that is neither the likely price leader nor a cheap place to
trade. The loss is real but smaller than it looks.

### 5.3 Do features 32 to 38 apply to a directional mid-frequency entry?

None applies in canonical form. Those features assume a resting quote, a fill model and inventory management.

| ID | Decision | Honest answer |
|---|---|---|
| F32 | `LATER` | Needs a queue model from `T3`, and calibrated fill and markout models. Assumes a resting quote that is out of scope, so a revival is unlikely even with `T3` |
| F33 | `LATER` | The one with directional meaning: a passive entry fills mostly when price is about to go through it. Needs `T3` for a credible queue. Revisit only if a passive-entry variant is registered under G5 |
| F34 | `DROP` | Needs own send and acknowledgement times. No real orders exist, and an entry at market has nothing to cancel |
| F35 | `ADAPT` `F35-X1` | The idea survives as an evaluation metric, the counterfactual result of rejected setups. It may never be an input |
| F36 | `DROP` | Market-making reservation price. Not applicable |
| F37 | `ADAPT` `F37-X1` | Reduces to "flow against my position", a useful frame for exit. No alpha model needed, and no independent information |
| F38 | `DROP` | Built on inputs not used here. The order layer applies a plain cost check instead |

Default order style is taker. That is conservative on cost, matches the strategy conventions, and removes the need for any queue model.

### 5.4 What replaces ES session logic?

| ES concept | Replacement |
|---|---|
| RTH and ETH phases | `hour_of_week` |
| `session_id` as the statistical cluster | UTC week, with UTC day as a sensitivity. Days run into one another, so a day is not independent |
| Session start and warmup | None. Warmup exists only where bars needed for a window are missing |
| Maintenance halt | Venue maintenance or outage, treated as a gap |
| Contract roll | None for perpetuals. Instrument metadata such as tick, lot and funding interval is versioned by date |
| Settlement, close | `funding_phase`. Funding is charged at actual settlement times, as in item 9 of the timing contract |
| Early close and holiday classes | Weekends are covered by `hour_of_week`. An approved point-in-time calendar of scheduled macro events is an optional control only |
| Cumulative session volume | Rolling volume, `F42-X1` |

**Seasonal profile.**

- `hour_of_week(t) = 24 * weekday(t) + hour(t)` in UTC, with Monday as 0, giving buckets 0 to 167.
- For a quantity `x`, the profile value is the median of `x` in the same bucket across the prior 8 weeks. It is valid with at least 6 valid weeks (the
  0.75 share is the F02 default, not tuned). Otherwise the value is invalid and is never filled from another bucket.
- Sensitivities are 4 and 26 weeks. Each is counted as a trial.
- Profiles are recomputed at each run from earlier data. Under item 10 of the timing contract, a fixed-window statistic like this is a causal indicator
  and needs no freezing, while a threshold on it is a fitted object. See [the gate specification](GATE_SPEC.md#4-normalisation).

**Two flags beside the profile.**

- `qh_phase`: minutes since the last quarter-hour boundary. One preprint on Binance perpetuals reports bursts of activity at quarter-hour marks (Kim and
  Hansen, 2026). An hourly profile cannot see that. On the cycle, every window ends at about the same minute of the hour, so the reference samples for
  percentiles use the same minute. See [the gate specification](GATE_SPEC.md#4-normalisation).
- `funding_phase`: minutes to the next funding settlement, from versioned instrument metadata. Whether flow behaves differently around settlement is
  `UNVERIFIED`.

**One known weakness.** A UTC profile blurs anything tied to US market hours when daylight saving changes. A sensitivity using New York local hour tests
this. Alexander, Heck and Kaeck (2021) link bitcoin volatility dynamics to US hours, but I have not verified how large this effect is on flow features.

### 5.5 How do taker fees compare with the effect being sought?

**The fee.** Values are configuration, and they depend on tier and venue:

| Venue and product | Maker | Taker | Source status |
|---|---|---|---|
| Binance USD-M, standard tier | 2 bps | 5 bps | From Kim and Hansen (2026), a secondary source. The official page did not show its table to my tool |
| Kraken Futures, tier 1 | 2 bps | 5 bps | Kraken fee page, opened |
| Kraken Pro spot, tier 1 | 40 bps | 80 bps | Kraken fee page, opened |
| Bybit perpetuals, base tier | `UNVERIFIED` | `UNVERIFIED` | Official pages did not load. Third-party sites report 2 and 5.5 bps |
| Coinbase and Bitstamp spot | `UNVERIFIED` | `UNVERIFIED` | Pages could not be read |

So a taker round trip on a perpetual costs about 10 bps before slippage. On some spot venues it can cost 160 bps, which would rule out every timeframe. **The
reference venue decision `D-01` is therefore a first-order input to this research.**

**In `R`.** Round-trip cost divided by initial stop distance:

| Stop distance | 10 bps at 1x | 20 bps at 2x | 30 bps at 3x | 160 bps spot |
|---|---|---|---|---|
| 25 bps | 0.40 R | 0.80 R | 1.20 R | 6.40 R |
| 50 bps | 0.20 R | 0.40 R | 0.60 R | 3.20 R |
| 100 bps | 0.10 R | 0.20 R | 0.30 R | 1.60 R |
| 200 bps | 0.05 R | 0.10 R | 0.15 R | 0.80 R |
| 400 bps | 0.025 R | 0.05 R | 0.075 R | 0.40 R |

This is arithmetic, not a result. The strategy conventions set a floor limiting base-case cost to about `0.25R` per trade. Their design estimates put typical stops at
about 50 to 70 bps for the backtest-only 15-minute strategies, about 60 to 150 bps for most 1h strategies, and about 150 to 300 bps for S03 at 1h and S10 at 4h. So the
live-eligible timeframes are the ones where cost in `R` is smallest. That is one small compensation of the hourly cycle, and it is unmeasured.

**The effect.** No effect size exists for our setups, because nothing has been run. Published indications, none on our setups, and all preprints:

- Kim and Hansen (2026), Binance perpetuals: 1-minute opening imbalance shows little association with later returns. 15-minute opening imbalance is associated with
  returns 4 to 12 hours later, with an interquartile effect of its lagged-flow component of about 5 to 6 bps. Their separate quarter-hour return forecast is about 0.5
  bps per boundary, which they note is small against fees.
- Bieganowski and Ślepaczuk (2026), Binance perpetuals at a 3-second horizon: the BTC taker test did not beat buy and hold, and taker results were significant only for
  smaller assets.
- Albers et al. (2021), at 500 ms: taker results are particularly weak on markets with large taker fees. A much shorter horizon than ours.

The honest prior: **a flow state is unlikely to predict a mid-frequency move larger than a 10 bps round trip by itself.** That does not end the question, because a gate
does not pay its own fee. It chooses among trades.

**What the gate must actually clear.** With `g` the mean gross per setup under `V0`, `c` the round-trip cost, `p` the kept share, `g_k` the gross mean of kept setups and
`g_v` that of vetoed ones:

- A veto improves total result if and only if `g_v < c`. A veto saves the whole round trip.
- **A random veto passes that test whenever `g < c`.** If `V0` loses after costs, trading less always helps, and that says nothing about flow. So the only meaningful
  comparison is against a placebo veto at the same rate, which means `g_v < g`.
- For the gated strategy to be worth running at all, `g_k > c` is needed. The lift required on kept setups is `c - g`.
- `WAIT` pays no extra fee. Its value is price improvement less the result of missed setups.
- An early exit that replaces a stop adds no fee. One that replaces a maker target adds the taker-maker difference, about 3 bps. So the fee hurdle is lowest at exit, where
  the larger cost is cutting winners short.

**What would settle it.** After `V0.L` exists (roadmap P3): gross `R` by aligned-flow quintile at setups, with confidence intervals from a UTC-week block bootstrap, compared
with placebo, reported at 1x, 2x and 3x cost. If `V0.L` gross is far below `c`, stop there. A gate cannot be asked to rescue that, and the owner should hear it early.

### 5.6 Whose flow is measured, and does that venue lead or follow?

**The measurement is always one venue's flow, never "the market's".**

**Evidence read.** Alexander, Heck and Kaeck (2021) find the Binance tether-margined perpetual to be the main source of bitcoin volatility transmission. Albers et al. (2021), on
14 markets in February 2021, name Binance and Huobi as leaders in trade flow predictive power at 500 ms, and find that fee regime helps explain who leads. **Both are from 2021.** One
market in that sample no longer exists, and I found nothing recent that compares these venues at this frequency. Current leadership is `UNVERIFIED`.

**Why millisecond leadership is not the point.** At an hourly look, venues have long since converged in price, and a sub-second lead cannot be traded here. What matters is whether one
venue's flow is a good measure of total pressure, and whether another venue's flow adds to it. These are different questions from who moves first.

**The live constraint changes the answer.** The research favourite may be unreachable from where the job runs. Each candidate must meet these requirements **before any outcome is seen**:
R1 reachable from a GitHub runner and lawful under the source's terms, R2 signed trades, R3 enough recent history to recover a missed run, R4 an archive with the same definitions for
backtest parity, R5 fits the job budget of about 3 minutes in [the data center document](../08_DATA_CENTER.md#staying-within-githubs-terms), R6 enough activity to be informative.

| Source | Reached by my tool on 2026-11-04 | Sign | Paging | Multi-year archive | Status |
|---|---|---|---|---|---|
| Binance USD-M REST | **No, HTTP 451** | Buyer-maker flag | `UNVERIFIED` | Yes, `H-T1a` | Best research data. **A 451 is a legal restriction. If a runner gets it too, this source is out, and it must not be routed around** |
| Binance spot, public market data host | Yes: candles with 12 fields, `aggTrades` with the `m` flag | Buyer-maker flag | `UNVERIFIED` | Yes, `H-T1c`. Candles carry taker-buy volume | **Not a candidate unless the owner confirms under `D-01` that Binance's terms allow this use.** Binance's main API refused on legal grounds, so using another of its hosts could amount to routing around that refusal. It is also spot, not the perpetual the strategies trade |
| Bybit REST | No, HTTP 403 on the endpoint I tried | Taker side | `UNVERIFIED` | Yes, `H-T1b` | A candidate only if it answers from a runner and its terms allow this use. If it refuses on the same kind of grounds, it is out |
| OKX `history-trades`, perpetual | Yes, fields include `side` and `ts` | `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` | Unknown. Worth checking because it is a perpetual |
| Kraken spot `Trades` | Yes, with a `since` cursor and up to 1,000 per call | `b` or `s`. Taker on its WebSocket documentation, not stated on the REST page | Forward cursor | `UNVERIFIED` | Spot, activity `UNVERIFIED` |
| Coinbase `trades` | Yes | **Maker side**, so inverted | `before` and `after` cursors | `UNVERIFIED` | Spot, and a useful cross-check |
| Bitstamp `transactions` with `time=hour` | Yes, `type` is 0 or 1 | `UNVERIFIED` | One call covers the hour | None seen | Fails R4 |

My tool is not a GitHub runner, so this table shows only what one outside client saw. **Check D9 repeats it from a runner.** If the poll source differs from the research source, research
results do not transfer, and the gate must be re-run on the poll source's archive. That is a requirement, not a sensitivity.

**Plan.** Each item is pre-registered, because choosing a venue after seeing results is a leak class the auditor checks.

| Role | Choice | Reason |
|---|---|---|
| `flow_venue` for `.L` | **Undecided. No source is confirmed.** Check D9 tries Bybit linear, OKX perpetual, Kraken, then Coinbase, in that order: perpetuals first, then the longest archive. Binance is excluded unless the owner confirms it under `D-01` | Must be pollable and lawful. Chosen before any test |
| `flow_venue` for `.R` | Binance USD-M perpetual, Bybit linear as a cross-check | Longest `T1` and depth history, likely leader by dated evidence |
| `price_venue` | Decision `D-01`, open | Must be lawful for the owner. Any result must be retested on it, as the charter requires |

**What follows from this.**

- **If no source passes, there is no live gate.** `VE.L`, `VX.L` and `VEX.L` cannot run, and live paper is `V0.L` only. **S07 and S08 are `T1` strategies, so they would not run live at all.**
- **A source without a multi-year archive fails R4.** Paging its REST history across daily runs might build one, but rate limits and terms are `UNVERIFIED`. Otherwise its only sample is forward, and at the setup rates in [the matrix](STRATEGY_FEATURE_MATRIX.md#4-can-each-gate-question-be-answered) that would take years.
- **A run on the hourly clock on an archive whose REST source has not passed is `.R`.** It tells us about the idea, and it cannot be quoted beside the live record.
- **The strategies use one venue per run** (C1). For S07 and S08, the flow source must therefore be the price venue. For `T0` strategies it may differ, if `D-01` and check D9 allow it.

**Tests that would settle it, all from archives:**

1. **Incremental flow.** Regress returns at 1 and 4 hours, and at 1, 5 and 15 minutes for `.R`, on flow from venue A and venue B together, with UTC-week block errors. This is the question that
   matters at this horizon.
2. **Setup level.** The same gate on flow from each venue, on identical setups, counted as a trial family.
3. **Information share** on 1-second mids by quarter, on exchange timestamps, to see whether leadership is stable.
4. **Lead-lag on exchange clocks.** A weak test, since venue clocks are not synchronised and no receive time exists. A proper measurement needs recording, so it needs an always-on machine.

**Per-venue signing.** A wrong sign here silently reverses a feature, so each one requires a mirror test.

| Venue and field | Meaning read in documentation | `z = +1` when |
|---|---|---|
| Binance `isBuyerMaker`, `m` | Buyer was the maker | False |
| Bybit `S` | Taker side | `Buy` |
| Kraken WebSocket `side` | Taker side | `buy` |
| Coinbase `side`, on `matches` and on REST trades | **Maker side**, the opposite of the others | `sell` |
| Bitstamp trade `type` | `UNVERIFIED`. The pages I could read do not define it | To be confirmed before use |

**Forced flow is uneven.** Bybit's all-liquidation stream reports all liquidations at 500 ms, while Binance's liquidation stream reports only the largest order in each 1,000 ms, so Binance's stream
cannot be summed into a complete measure. Both are streams, so neither can be collected on this setup in any case.

### 5.7 What the hourly cycle costs

This section is deliberately blunt. Each row states what is left.

| Capability | Research clock (`.R`) | Hourly cycle (`.L`) | Verdict |
|---|---|---|---|
| Veto at a bar close, 1h and 4h | At the close | At the first run, about 9 minutes or more after the close, using flow up to the run | **Mostly survives.** Entry is later for every variant, baseline included |
| Regime filter | Any grid | Each run | **Survives.** It is slow by nature |
| Risk gate, new entries | Any grid | Each run. Sees stress already visible at the run | **Partly survives.** It blocks entries after stress is visible, and cannot pre-empt within the hour |
| `ENTER` timing | Choose a moment inside the setup's life | Only at a run | **Destroyed at 1h.** Almost nothing to choose from at 4h |
| `WAIT` | Look again in a minute | The next run, up to `expiry` and `A_max`, as C17 states. Under `C-LATE`, a second look exists for only about 13% to 46% of 1h setups | **Destroyed at 1h,** where a second look often does not exist and the late-entry checks may close it if it does. **Weak at 4h** |
| Acting at a level or zone as price touches it | Possible | Not possible. Seen after the fact | **Destroyed.** The flow hooks in the strategy documents that ask "while price is at the level" cannot be answered live |
| Flow exit on a fast event, such as a sweep against the position | Within a minute | Up to 60 minutes later or more, by which time the stop may already have fired | **Destroyed** |
| Flow exit on slow conflict | Any grid | Each run | **Survives only for trades held many hours.** A trade that closes between runs never gets a look |
| Flow stop tightening | Any grid | Each run | Same as slow flow exit |
| Book imbalance, depth, order flow imbalance, refill | Available | None | **Destroyed for live.** The owner's "order imbalance" question is research only |
| Decision timeframes 5m, 15m, 30m | Available | None | **Destroyed for live.** S01 and S06 are backtest only at every timeframe, because the reaction they trade is shorter than the hour lost to the cycle. S08 at 30m is backtest only. S02, S07, S08 and S09 are live at 1h, and S03, S04, S05 and S10 at 1h or 4h |
| Order-level features | Not available either | Not available | Unavailable on this setup in any form |
| Time stops | Exact | Take effect at the first run after they fall due, under rule 7 of charter section 7 | **A limit of the cycle, logged and reported.** See [the gate specification](GATE_SPEC.md#6-flow-exit-on-the-cycle) |

**A partial offset.** A dropped run loses decisions but rarely data, because REST sources keep recent history. A disconnected stream would lose data for good. That is the one thing this setup does well.

**What would need an always-on machine (`D-04`):**

1. `T3` recording, and so any test of F07 to F13, F15, F32 and F33.
2. Any live use of book features: F02, F05 as a series, F16, F28, `F39-X1`, `D-OF31-X1`.
3. Decisions inside the hour: entry at the touch, `WAIT` as real timing, reaction to a sweep.
4. Fast flow exits and fast stop tightening.
5. Live positions at 5-minute to 30-minute timeframes.
6. Measured receive times and latency, and the feed watchdog (F43).
7. Ground truth for the burst proxy, and tests of conflation below 100 ms.
8. Complete forced-flow data.

**How to put a number on it, with no machine.** Run the same recipe as `.L` and as `.R` on identical setups. `V0.R` minus `V0.L` is the cost of the cycle to candles alone, the same `IDEAL` minus `CYCLE` figure C17 requires. The difference in gate value between
`VE.F.R` and `VE.F.L` is the cost to flow. A similarly sized difference for `T2` recipes shows what live book data might add. If those differences are small, the hourly cycle costs little and `D-15` is confirmed. If they
are large, the owner has a measured case for `D-04`. These are `SIMULATED` estimates, and on `T2` they carry the caveat that a next-day archive is not a live feed.

### 5.8 Does the book snapshot at poll time have any use?

**As a gate input, no.** A single sample of a book state that turns over within seconds, once an hour, carries no persistence and cannot distinguish a real imbalance from a momentary one. It also cannot be a time series in
the sense `F16-X1` needs.

**It has three narrow uses, none of them a decision:**

1. **Cost evidence.** Spread (F01, `F01-X1`) and fill distance (`F05-X1`) at the decision go into the decision record. They feed the paper-versus-simulation mismatch report: is the assumed slippage realistic at this minute of
   the hour?
2. **Sanity.** A crossed, locked or empty book at the run is a reason to distrust the venue at that moment.
3. **A slow depth regime, possibly.** Hourly samples accumulated over days could describe a depth regime, because a regime moves slowly enough to survive the sampling. I would not prioritise this, since the illiquidity ratio in
   `F39-X2` addresses the same question from `T1`.

**If anyone wants to test it anyway.** Parity demands sampling exactly one state per run from the `T2` archive of the same source as the poll, so it needs a source with both a depth archive and a reachable REST endpoint, and none is
confirmed. My prior is low, and it is not in the test plan.

## 6. What the knowledge base does not cover

These have no ES analogue and no canonical ID. Each would need its own document. None is proposed for testing before wave 1 finishes.

| Candidate | Data | Live-eligible? | Note |
|---|---|---|---|
| Funding and premium state | Binance `premiumIndexKlines`, `markPriceKlines`. Contents not opened | Possibly, by REST | May overlap with the strategy's regime logic |
| Open interest change | Binance `metrics`. Contents not opened | Possibly, by REST | Coarse, but may be informative about leverage build-up. Fits an hourly look unusually well |
| Spot versus perpetual flow divergence | `T1`, from `H-T1c` and `H-T1a` | Only if both are pollable | Needs the venue tests first |
| Forced flow share (liquidations) | Streams only, and no liquidation folder appears in the Binance archive listing | No | Needs an always-on machine |
| RPI-tagged flow | Forward from 2025-11 at best | `UNVERIFIED` | Tagged trades split retail from other flow |

Because these move slowly and need no book, the funding and open interest candidates may suit the hourly cycle better than the microstructure features the knowledge base was written for. That is a judgement, not a finding.

## 7. Test order and trial budget

Every feature tried is a trial, and the deflated Sharpe ratio pays for each one. The order below is deliberately short. A later wave starts only after the earlier one has a verdict. Live-eligible work comes first, because it is the only
kind that can reach the paper record.

**Not hypotheses (no return claim, not counted as gate trials):** F01, `F01-X1`, `F05-X1` as cost inputs and records, `F42-X1` as a control, `F35-X1` as a metric, `F37-X1` as a frame.

| Wave | Family | Kind | Tier and history | Why here |
|---|---|---|---|---|
| 1a | `F24-X1`, with `D-SV18-X1` as its raw form | `.L` | `T1`, length depends on check D9. A `T0` screen is possible at almost no cost | Simplest measure, no conflation issue, and fully computable at a run. If this has nothing, more complicated flow features have a high bar. Everything else must beat it |
| 1b | `F18-X1`, `F19-X1`, `D-RR18-X1` | `.L` | `T1` | Directly addresses the question level strategies pose: did flow make progress? Also controls for flow that merely re-measures the bar |
| 1c | `F41-X1`, `F39-X2` | `.L` | `T0` or `T1` | Can only block or reduce risk, and is cheap. Must still beat a placebo |
| 1d | `F26-X1` as an hourly summary | `.L` | `T1`, after check D3 | Degraded from its event form, so I expect less. Input for `F25-X1` |
| 1R | The same families | `.R` | `T1` | Measures the cost of the cycle, and covers timeframes under 1 hour. Evidence for `D-04`, not for live |
| 2L | `F27-X1`, `F23-X1`, `F25-X1` | `.L` | `T1` | Only where wave 1 gave something to refine |
| 2R | `F16-X2`, then `F16-X1`, `F02-X1`, `F39-X1`, `D-OF31-X1`, `F28-X1` | `.R` | `T2`, 3.8 years | The owner's order imbalance question. **Cannot reach live.** The compact archive comes first because it is cheap and on the candidate lead venue |
| None | `T3` features | - | Not recordable | Not planned |

**Budget.** A first pass uses one declared threshold per feature, on 1 window and 1 venue, so each row is one logged trial. Sensitivities run only on survivors, and are also logged. `.R` runs are trials too. The per-strategy rows and the count are in
[the matrix](STRATEGY_FEATURE_MATRIX.md#7-trial-count). Maximum features per strategy is about five, per the role definition. Each symbol and each flow variant multiplies the strategy grids, as the strategy index notes.

## 8. Checks needed before testing

These use no flow outcomes, so they cannot contaminate later tests. All of them are open.

| ID | Check | Why it matters | Owner |
|---|---|---|---|
| D1 | **Ladder reach.** How far `ob200` and `ob500` reach from mid, in bps, by `hour_of_week`. Set `b` to the largest of {5, 10, 20} bps that is inside the reach at 99% of grid points in both formats | 200 occupied levels on a very fine tick may span only a few bps. A wider band would be mostly invalid | `data-steward` |
| D2 | **Signs.** Per-venue mapping against a known aggressive print or the book move | A flipped sign silently reverses every flow feature | `developer` |
| D3 | **Burst validity.** Compare `F26-X1` groups with `aggTrades` first and last trade ids, and with `trades`. True ground truth needs taker order ids, which come only from a feed we cannot record, so this stays partly `UNVERIFIED` unless a short recording is ever made on another machine | Timestamp grouping may merge or split takers | `developer` |
| D4 | **RPI break.** Compare trade prints with the visible book before and after November 2025. Compare `F24-X1` on tagged and untagged trade data | Prints may no longer relate to visible depth as they did | `developer` |
| D5 | **Format break.** Compare distributions of band depth around 2025-08-21 | Depth features may jump for reasons unrelated to the market | `data-steward` |
| D6 | **Run delay.** Log delay after the nominal minute, job duration and drops by `hour_of_week` from the hourly job, for at least 30 days before paper starts | This gives `C-MEASURED` under C17, to replace the assumed `C-LATE`. GitHub states that scheduled runs can be delayed or dropped, especially around the start of the hour | `data-steward` |
| D7 | **Conflation damage.** Compute `F16-X1` and `D-OF31-X1` at 100 ms, 1 s and 30 s on the same archive days. Below 100 ms cannot be tested without recording | Tests the claim in section 3 that bucket width is harmless for state and net flow | `developer` |
| D8 | **Trade gaps.** Whether trade ids allow gaps to be told apart from quiet periods, per source | Quiet is zero flow. Missing is invalid | `data-steward` |
| D9 | **Poll source.** Test R1 to R6 in section 5.6 from a GitHub runner, including the source's terms | Decides whether the research favourite can be live-eligible at all | `data-steward`, owner for terms under `D-01` |
| D10 | **REST against archive.** Compare a week of polled bars with next-day archive bars, using the expected tolerance in the data center document | Parity between backtest and live depends on this | `data-steward` |
| D11 | **Reachable trades.** From `V0.L` on each strategy, the share of trades still open at the first flow look | If most trades close between runs, a flow exit has nothing to act on. This uses only baseline results | `developer` |
| D12 | **Minute-of-hour effect.** Distribution of `F24-X1` by run minute | Tells whether the choice of run minute matters | `developer` |

## 9. Sources opened

Knowledge base (`HFT_KB_PATH`), all read directly: `README.md`, `00_TASK_0_EVENT_TIME_AND_INFORMATION_SEMANTICS.md`, `00_FEATURE_DEFINITION_REGISTRY.md`, `FEATURE_DEPENDENCY_MAP.md`, `RESEARCH_GATES.md`, `FEATURE_REGISTRY.md`, `RISK_REGISTER.md`, all 44
feature files, and these cards: data capability audit, cross-feature event semantics audit, control variables and baselines, feature application catalog, red-team amendment, frozen expected impact model, F42 experiment, common research contract, and the shared
episode detector. Summaries here are my own.

Project documents read: charter, data center, data lifecycle, roadmap, decision log, portfolio outputs, the strategy index in full, and sections 5, 6, 11, 13 and 14 of all ten strategy documents, plus the time stop sections.

External sources were opened on 2026-11-04 through a page-reading tool that returns extracted answers rather than full text. **Treat any detail as needing a check against the source before relying on it.** PDF-only sources could not be read and are not used.
Search results that were not opened are not cited.

| Source | What was read |
|---|---|
| Alexander, Heck, Kaeck (2021), *The Role of Binance in Bitcoin Volatility Transmission*, <https://arxiv.org/abs/2107.00298> | Abstract page |
| Albers, Cucuringu, Howison, Shestopaloff (2021), *Fragmentation, Price Formation, and Cross-Impact in Bitcoin Markets*, <https://arxiv.org/abs/2108.09750> and <https://ar5iv.labs.arxiv.org/html/2108.09750> | Abstract, first part of the text |
| Kim, Hansen (2026), *The Quarter-Hour Effect*, <https://arxiv.org/abs/2607.09426>, preprint | First part of the HTML text, including sections 2 to 6 |
| Bieganowski, Ślepaczuk (2026), *Explainable Patterns in Cryptocurrency Microstructure*, <https://arxiv.org/html/2602.00776>, preprint | HTML text |
| GitHub: [events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [terms for additional products](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features) | Schedule behaviour and the Actions section |
| Bybit documentation: [order book](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook), [trades](https://bybit-exchange.github.io/docs/v5/websocket/public/trade), [all liquidation](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation) | Field and cadence descriptions |
| Binance: [public data repository](https://github.com/binance/binance-public-data), [derivatives change log](https://developers.binance.com/docs/derivatives/change-log), [RPI order book endpoint](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Order-Book-RPI), [RPI FAQ](https://www.binance.com/en/support/faq/detail/92c83c53173947c4a44f9a7277c3b9ce), [futures trading rules](https://www.binance.com/en/futures/trading-rules/), archive listings at `data.binance.vision` | Field names, dates, tick sizes, file names |
| Bybit archive listings at `public.bybit.com` and `quote-saver.bycsi.com` | File names only |
| Coinbase: [Exchange WebSocket channels](https://docs.cdp.coinbase.com/exchange/websocket-feed/channels), [Advanced Trade channels](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-channels), [product trades](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-trades), product endpoint for `BTC-USD` | Channel and field descriptions, tick |
| Kraken: [v2 trade](https://docs.kraken.com/api/docs/websocket-v2/trade), [v2 level3](https://docs.kraken.com/api/docs/websocket-v2/level3), [recent trades REST](https://docs.kraken.com/api/docs/rest-api/get-recent-trades/), [fee schedule](https://www.kraken.com/features/fee-schedule) | Field descriptions, base-tier fees |
| REST probes on 2026-11-04 from my tool: Binance USD-M candles (HTTP 451), Binance spot candles and `aggTrades`, Kraken, Coinbase, Bitstamp and OKX trades (data returned), Bybit instruments (HTTP 403) | Whether a response came back, and its field names. **Not from a GitHub runner** |

Could not be read, so anything depending on them is `UNVERIFIED`: Binance fee page table, Bybit fee pages, Coinbase fee pages, Bitstamp fee page and WebSocket documentation, Bybit instrument API, Binance stream pages for aggregate trades and diff depth, and the
Easley et al. (2024) PDF.
