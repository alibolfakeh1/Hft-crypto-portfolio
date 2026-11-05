# Feature triage

Status: revised after [the leak audit of 2026-11-04](../reviews/leak/features_2026-11-04.md), and awaiting re-audit. No verdict is claimed here. Date: 2026-11-05. Owner: `feature-integrator`.

This document decides what happens to each of the 44 features in the external knowledge base
(`HFT_KB_PATH`) when moved from ES futures at high frequency to BTC and ETH at decision times of 5
minutes to 4 hours, under two decisions: `D-15`, **everything runs on GitHub, with no server**, and `D-22`, **the research
path is Kraken spot, BTC/USD and ETH/USD, subject to written permission that has not been requested, with Bitstamp as the
fallback.** All sources stay disabled.

**Nothing here has been tested.** No code exists and no feature has been computed on crypto data. Every
statement about what a feature might do is a hypothesis. An `ADAPT` decision means "worth
testing or needed as infrastructure", never "works". Anything not checked is marked `UNVERIFIED`.

Related documents: [decision point map](DECISION_POINT_MAP.md), [gate specification](GATE_SPEC.md),
[strategy feature matrix](STRATEGY_FEATURE_MATRIX.md), [data sources](../03_DATA_SOURCES.md).

## 1. Summary

| Decision | Count | Meaning | Features |
|---|---|---|---|
| `USE` | 0 | Canonical formula, sign and unit kept | None. F01 held this until `D-22`. It reads a book, and no free book history exists |
| `ADAPT` | 12 | Carries over only with a stated change, under a derived ID | F18, F19, F23, F24, F25, F26, F27, F35, F37, F39, F41, F42 |
| `LATER` | 26 | Blocked by data or by a dependency that has not yet shown value. Ten need `T3`, which cannot be recorded here. Five more were `ADAPT` or `USE` before `D-22` and now wait on paid book history | F01, F02, F03, F05, F07, F08, F09, F10, F11, F12, F13, F14, F15, F16, F17, F20, F21, F22, F28, F29, F30, F32, F33, F40, F43, F44 |
| `DROP` | 6 | No credible path to a decision here, or redundant by construction, for reasons that a server would not change | F04, F06, F31, F34, F36, F38 |

Canonical IDs are unchanged. The decisions changed, the IDs did not. Of the 12 `ADAPT` features, **nine can feed a live paper decision on this setup**: F18,
F19, F23, F24, F25, F26, F27, F39 (`T1` form only) and F41. Three support them without being return
hypotheses: F42 is a control, F37 a frame and F35 a report metric. See section 2.2.

Seven conclusions drive the table:

1. **Nothing that could be a return signal carries over unchanged.**
2. **Net survives, gross does not.** Net flows keep their meaning at minutes. Gross add and cancel flows, order lifetimes, queue position and atomic event
   structure do not.
3. **ES is a large-tick market and BTC is not.** Queue and tick-grid features assume long queues at a one-tick
   spread. See section 2.4.
4. **The source decides what can be studied.** `T0` and `T1` only, on free data, spot only. So the owner's order imbalance question (F16) has no test on this path, and nothing here plans as though it will run. Paid book history is a later owner decision.
5. **`T1` depends on one unproved fact.** Kraken's pages show `b` or `s` without saying this is the taker's side. Every signed feature waits on check D2.
6. **The hourly cycle leaves a filter, not a timing tool.** A veto at a bar close mostly survives. `ENTER` timing,
   `WAIT` and fast flow exits are largely destroyed. See section 5.7. The project's question "whether and when to
   enter, and when to exit" can be tested live only for "whether", and crudely for "when to exit".
7. **Cost and power are the other hard limits.** The base-tier taker fee read for this venue implies a round trip of about 160 bps, which may dominate everything else. See section 5.5. The prediction for each live strategy's entry gate,
   alone, is `INCONCLUSIVE`. See [the matrix](STRATEGY_FEATURE_MATRIX.md#4-can-each-gate-question-be-answered).

First tests, in order: `F24-X1`, then the response family `F18-X1`, `F19-X1` and
`D-RR18-X1`, then the risk checks `F41-X1` and `F39-X2`, then the burst features where check D14 allows them. The reasons are in
section 7.

## 2. Conventions

### 2.1 Decisions

`ADAPT` always carries a derived ID, defined in section 4. Canonical IDs are never renumbered or redefined. A
`LATER` or `DROP` feature keeps its canonical definition, unused. Derived IDs written before `D-22` for book features stay defined in section 4, marked `LATER`, so their IDs are not reused. A derived ID with no source is retired rather than reassigned.

### 2.2 Live-eligible and research-only

Two kinds of variant exist. They are never mixed, and a result from one is never presented as evidence for the
other. The full rules are in [the gate specification](GATE_SPEC.md#2-two-kinds-of-variant).

| Kind | Suffix | Clock | Inputs | Timeframes | Can it become a live paper position? |
|---|---|---|---|---|---|
| Live-eligible | `.L` | `CYCLE` under C17 of the strategy conventions, with delays and dropped runs reproduced | `T1` and candles from the approved source, as a run would hold them | 1h, 4h | Yes |
| Research-only | `.R` | `IDEAL-1M`, with a finer look grid, not achievable on this setup | `T1` from the same source's archive | 5m to 4h | No, not without an always-on machine (decision `D-04`) |

Live-eligibility of each derived ID, and whether it needs the taker's side:

| Derived ID | Live? | Needs the side? | What is left on the hourly cycle | What is lost |
|---|---|---|---|---|
| `F24-X1`, `D-SV18-X1` | Yes | Yes. `VA_W` alone does not | Balance over the last 60 or 240 minutes, at each run | Any reaction inside the hour |
| `F18-X1`, `F19-X1`, `D-RR18-X1` | Yes | Yes | Response over the last 60 or 240 minutes | Seeing absorption as it happens at a level |
| `F27-X1` | Yes | Yes | Recomputed after the fact from the last hour's trades | Acting at the touch |
| `F26-X1`, `F25-X1` | Yes, as window summaries, if check D14 allows | Yes | "A sweep happened in the last hour" | Event response. A sweep can be over 60 minutes old when first seen |
| `F23-X1` | Yes | Yes | Run of same-sign minute bars ending at `t_cut` | Little, since it is slow by design |
| `F41-X1`, `F39-X2`, `F42-X1` | Yes | **No** | Slow state is mostly intact | Cannot stop an entry into a cascade that began minutes earlier |
| `F37-X1` | Yes, with a live-eligible input | As its input | Hourly conflict check | Fast exits |
| `F35-X1` | Metric only | No | Not applicable | Not applicable |
| `F01-X1`, `F02-X1`, `F05-X1`, `F16-X1`, `F28-X1`, `F39-X1`, `D-OF31-X1` | **`LATER`** | Not applicable | Nothing | No history, no live book |
| `F02-X2`, `F16-X2` | **Retired** | Not applicable | Nothing | Their only source was an archive that `D-17` rules out |

### 2.3 Data tiers and history

Tiers are those of the [charter](../00_CHARTER.md#4-data-tiers). A recipe's testable history is limited by its
highest tier. Everything in this table comes from [the data sources document](../03_DATA_SOURCES.md), not from files opened by this author. **No file has been opened, and nothing may be downloaded before a written yes.**

| Code | Source | Span | Status | Notes |
|---|---|---|---|---|
| `H-K-T` | Kraken time and sales bulk files, then REST `Trades` catch-up | From each pair's first trade to 2026-09-30, in ZIP parts of about 2 GB, updated quarterly. Oldest `XBTUSD` trade 2013-10-06 by a status check. ETH/USD start is not stated | `doc`, permission pending | `b` or `s`, and order type. Side meaning `UNVERIFIED`. Whether trade ids exist in these files `UNVERIFIED`. REST gives 1,000 trades per call with `since`, and catch-up time is not measured. Early years may be thin, so usable history is set by the coverage rule in section 5.6 |
| `H-K-C` | Kraken OHLCVT files, 1 to 1,440 minutes. REST gives the latest 720 per interval | As above | `doc`, permission pending | **Not stated to carry taker volume.** Canonical bars are built from trades (`D-12`), so these are a reconciliation check at G1 only, and no candle-level flow screen has a source |
| `H-FB` | Fallback: Bitstamp under a commercial agreement, with trades from Tardis | Spot since 2019-03-30 | `doc`, paid, not bought | Side column not confirmed on pages read. Bitstamp's `type` is not defined on the page read. A vendor archive stays `.R` until the source card shows it matches the poll, under R4 in section 5.6 |
| `H-PILOT` | Tardis free first-day-of-month files | Sampled days | Owner accepted terms for these downloads only (`D-22`) | **Pipeline test only, never in a result.** The 28-day reference and 8-week profile cannot be built, so features are `WARMUP`, and are not computed on a shorter window |
| `H-PAID-L2` | Tardis L2 for Kraken spot | Since 2019-06-04 | `doc`, paid, not bought | **A later owner decision.** Nothing plans on it |
| `H-T3` | Own recording | **None** | **0 days, and it cannot start on this setup** | Needs a continuous connection. See decision `D-04` |

**Length.** How many years of test blocks this leaves is `UNVERIFIED`. The dates come from [the fold plan](GATE_SPEC.md#82-fold-plan-frozen-before-any-outcome): a start set by data coverage alone, an 18-month first training span, and a locked final block. No outcome may shape them.

**Empty minutes may matter here.** Under C2, a minute with no trades is a gap unless the response proves continuity, by a trade id or sequence with no skip, or by overlapping pages. C2 says this costs little on a liquid perpetual. **That is `UNVERIFIED` for Kraken spot,** where quiet minutes may be many, particularly in early years, and if the files carry no id then every empty minute is a gap, under charter G1. This could shrink usable history a lot, and could put `DATA_GAP` on many runs. Check D8 measures it.

**Known structural breaks inside this history:** none is known, because nothing has been opened. Stamp resolution, file format and fields may change across years, and check D5 looks for that. No result or size assumption carries over from another venue.

### 2.4 Why tick-based definitions do not transfer

| Instrument | Tick | Tick in basis points (illustrative prices) |
|---|---|---|
| ES | 0.25 | About 0.4 at an index level of 6,000 |
| BTC-USD spot (Coinbase, an illustration of a fine spot tick) | 0.01 | 0.001 to 0.0017 at 100,000 to 60,000 |
| BTC/USD, ETH/USD spot (Kraken) | `UNVERIFIED` | Goes in the source card, check D14 |

A fine crypto tick is many times finer in relative terms than an ES tick. A fixed ladder of 10 ticks would span almost no economic distance. So a tick-based definition is replaced by bps of price. Measured queue behaviour does not carry over either way, and no such figure is assumed.

### 2.5 Project conventions for every feature

These apply to all `ADAPT` features, and they are not repeated in the table.

| ID | Convention | Why it differs from the knowledge base |
|---|---|---|
| G1 | **Clock.** Everything follows C17. Windows are `(t_cut - W, t_cut]` on the exchange clock, with `t_cut = floor_1m(min(t_poll) - A)`, one per run and symbol, the same live and in backtest. `A` is 10 s, `UNVERIFIED` until measured under check D10. An `Anchored` window ends at its own object's knowable time, which is at or before `t_cut`. A bar built from rows with one stamp over an interval is knowable at close plus the source's span, under C2. On `.R`, a look at `u` uses `(u - W, u]`, and it fills under `IDEAL-1M` | Task 0 of the knowledge base excludes receive time. The [timing contract](../00_CHARTER.md#3-timing-contract), items 6 and 13, overrides it for this project |
| G2 | **No complete-event assumption.** The atomic unit is one venue message | CME's event-based packets have no equivalent in these feeds |
| G3 | **Units.** Prices in bps, quantities in quote notional. Ticks serve validity checks only | Section 2.4. Contract counts do not compare across venues or over time |
| G4 | **Native sign, proved.** `z = +1` when the taker buys. The meaning of each endpoint's side field must pass check D2 before any signed feature runs. The mirror test does not check this: an inverted side passes it exactly. No tick-rule inference. Unknown sign is ineligible. A sign change after results is a new trial on later data | Most venues publish a side, but the field means different things per venue |
| G5 | **Venue scope.** Every value carries its venue and instrument. No pooling across venues | ES has one primary venue |
| G6 | **Calendar.** No sessions. `hour_of_week` and `qh_phase` replace them. No funding phase on spot. See section 5.4 | 24/7 market |
| G7 | **Missing is invalid.** Never zero, never imputed. A window with proved continuity and no trades is valid and has zero flow, but ratios on it fail their support rule | Same principle as the knowledge base, restated because quiet and missing look alike in crypto data |
| G8 | **Flow population.** All trades are included by default, declared now. Whether block or other flagged trades exist on each endpoint, and what the order type field means, goes in the source card before any outcome. A change to this after results is a new trial | No ES equivalent |
| G9 | **Fitted values.** Anything estimated across a sample, such as a threshold, is fitted on past data and frozen, as in [the gate specification](GATE_SPEC.md#8-fitting-and-freezing), and each artifact is keyed by `(kind, source)`. A fixed-window causal statistic, such as a rolling percentile, needs no freezing, under item 10 of the timing contract, provided each reference member uses its own point-in-time normaliser. No epsilon repairs. A ratio that fails its support rule is invalid | Same principle as the knowledge base, with the charter's ruling on rolling statistics |

## 3. The 44 features

"Live" shows whether the feature can drive a live paper decision: **yes**, **no** (research only), **metric** (never an input), or a dash for a feature with no planned use.

"At minutes, 100 ms" states whether the feature keeps its meaning at minutes and what 100 ms conflation of a `T2` archive
does to it, as seen from a 5-minute decision: **harmless**, **biased** or **destroyed**. These readings hold for any conflated archive, and they are `UNVERIFIED` for a paid Kraken archive, whose update interval has not been read. `T1` features have no conflation
issue.

"Paid book" in the Reason column means: **`LATER`, because Kraken has no free book history. Paid history is a later owner decision.**

| ID | Title | Decision | Tier | Live | History | At minutes, 100 ms | Reason | ES to crypto |
|---|---|---|---|---|---|---|---|---|
| F01 | Spread State | `LATER` | `T2` L1 | - | `H-PAID-L2` | Harmless. State read at `t`. Transition timing is lost at minutes | **Paid book.** It was a validity check and cost input. Research costs are now declared values. See sections 5.5 and 5.8 | Formula unchanged on each venue's own tick, with `F01-X1` in bps if revived |
| F02 | Relative Touch Depth | `LATER` | `T2` | - | `H-PAID-L2` | Harmless as a time mean. Instantaneous touch size lasts seconds, so only the mean is meaningful | **Paid book.** Unsigned thin-book state. `F39-X2` covers part of the question from trades | Touch becomes a bps band, session bucket becomes hour of week, contracts become notional |
| F03 | Depth Concentration | `LATER` | `T2` | - | `H-PAID-L2` | Harmless for state, but its mechanism acts at depletion, which is sub-second | **Paid book.** Shape can only matter after depth level does | Tick ladder would need a bps ladder |
| F04 | Depth Entropy | `DROP` | `T2` | - | None | Harmless, yet not useful | Blind to where depth sits, and at risk of duplicating depth level and shape. Not worth a trial at this horizon | Would need bps bins |
| F05 | Liquidity Gap | `LATER` | `T2` | - | `H-PAID-L2` | Harmless. State at `t` | **Paid book.** It was an input for slippage in research, and not a return hypothesis. Slippage is now a declared value | First gap in ticks becomes distance in bps to fill a notional |
| F06 | Bid–Ask Gap Asymmetry | `DROP` | `T2` | - | None | Harmless, yet redundant | A deterministic transform of two gaps, so not independent evidence | None needed |
| F07 | Average Order Size | `LATER` | `T3` | - | `H-T3` | Destroyed. No order identity in L2 | **Needs `T3`, which cannot be recorded without an always-on machine.** Even then, low priority: it feeds queue models and has no mechanism at minutes | Would need a venue with order ids. Size unit differs |
| F08 | Order-Size Concentration | `LATER` | `T3` | - | `H-T3` | Destroyed | **Needs `T3`.** Same as F07 | Same as F07 |
| F09 | Persistence-Weighted Depth | `LATER` | `T3` | - | `H-T3` | Destroyed. No order age in L2 | **Needs `T3`.** Could test whether a large displayed order at a zone is durable | Decay constants move from seconds to minutes. A level-based lower bound on `T2` would be a separate derived field, not F09 |
| F10 | Fleeting Liquidity Ratio | `LATER` | `T3` | - | `H-T3` | Destroyed. Lifetimes under the bucket width are invisible | **Needs `T3`.** Could condition trust in `F16-X1`, but only after it shows value | Window moves to minutes, age thresholds stay short |
| F11 | Cancel-to-Add Ratio | `LATER` | `T3` | - | `H-T3` | Destroyed. Adds and cancels net inside a bucket. Inferred proxies are lower bounds only | **Needs `T3`.** Explicit classification exists only in order-level feeds | Windows to minutes. Measures only the recorded venue |
| F12 | Cancel-to-Trade Ratio | `LATER` | `T3` | - | `H-T3` | Destroyed for the same reason | **Needs `T3`.** Separates withdrawal from consumption, which is a good question | As F11 |
| F13 | Queue Survival Probability | `LATER` | `T3` plus model | - | `H-T3` | Destroyed | **Needs `T3`.** Even then, low priority: a survival model for a resting order, and no resting orders are in scope | Not applicable |
| F14 | Queue Half-Life | `LATER` | `T2` | - | `H-PAID-L2` | Biased. Recovery over seconds is visible, faster recovery is not | **Paid book.** Summarises prior shocks, so it needs the `F28-X1` episode table first | Touch becomes a band, horizons move to minutes |
| F15 | Queue Churn | `LATER` | `T3` | - | `H-T3` | Destroyed. Gross turnover nets away | **Needs `T3`.** Even then, low priority: likely measures quote maintenance rather than anything a 5-minute decision can use, `UNVERIFIED` | Not applicable |
| F16 | Imbalance Persistence | `LATER` | `T2` | - | `H-PAID-L2` | Harmless. A time mean of state. A 1 s grid should do, and this would be testable with paid data | **Paid book.** The main book-imbalance candidate, and the owner's core question. Nothing here plans as though it will run. Reinstatement conditions are in section 4 | Touch becomes a band, windows move from under 5 s to 1 to 240 minutes |
| F17 | Imbalance Flip Rate | `LATER` | `T2` | - | `H-PAID-L2` | Biased. Flip counts depend on the sampling interval, so the grid must be fixed | **Paid book.** Reliability modifier for `F16-X1`. Pointless if `F16-X1` fails | Band imbalance, fixed grid, dead zone around zero |
| F18 | Price Response per Signed Volume | `ADAPT` `F18-X1` | `T1` | yes | `H-K-T` | Survives. No conflation issue | Price progress per unit of flow. The basic measure for telling absorption from breakthrough | Mid endpoints become short VWAPs, ticks per contract become bps per expected minute of volume |
| F19 | Local Kyle Lambda | `ADAPT` `F19-X1` | `T1` | yes | `H-K-T` | Survives with a longer fit | The "normal response" reference for `D-RR18-X1`, and a fragility state | Sub-window 1 minute, fit 24 hours ending at or before the scored window's start |
| F20 | Impact Surprise | `LATER` | `T1`, `T2` | - | `H-K-T`, `H-PAID-L2` with book inputs | Survives in form | Earns credit only for book-state conditioning beyond `D-RR18-X1`. Needs a frozen model, so it comes after that family | Windows to minutes, frozen model refit on crypto |
| F21 | Post-Trade Relaxation | `LATER` | `T1` | - | `H-K-T` | Survives only as a landmark. Unavailable at the anchor event | Could time entry after a spike in research, once `F26-X1` events exist. No live use at an hourly look | Landmarks in minutes |
| F22 | Flow Saturation | `LATER` | `T1`, `T2` | - | `H-PAID-L2` | Biased. Book order flow imbalance is approximate across buckets | Unsigned transform of the same inputs as F18. The knowledge base itself leaves its input and window open | Test `D-OF31-X1` first, if ever revived |
| F23 | Trade Run Length | `ADAPT` `F23-X1` | `T1` | yes | `H-K-T` | Canonical form loses meaning: a trade run at `t` is a seconds-scale accident, and counts depend on how a venue splits fills. A run of minute bars survives | Simple persistence measure, mainly for exit | Trades become 1-minute net flow bars |
| F24 | Trade-Sign Entropy | `ADAPT` `F24-X1` | `T1` | yes | `H-K-T` | Signed balance survives. Entropy adds nothing, since it is determined by the balance when signs are binary | Primary flow feature and the bar every other flow feature must beat | Balance only, in notional, windows in minutes |
| F25 | Large-Trade Surprise | `ADAPT` `F25-X1` | `T1` | yes, as a summary, if D14 allows | `H-K-T` | Survives as a window summary | Whether unusually large taker orders point the same way as the setup | Unit becomes the `F26-X1` burst, size in notional, reference prior 7 days |
| F26 | Sweep Penetration | `ADAPT` `F26-X1` | `T1` | yes, as a summary, if D14 allows | `H-K-T` | Canonical form destroyed: no event boundaries. A trade-only proxy survives, only with fine match stamps | Event veto in research: do not enter against a sweep that just happened. Live, it degrades to an hourly summary | Atomic event becomes same-timestamp, same-sign burst. Levels cleared become walk in bps |
| F27 | Absorption Efficiency | `ADAPT` `F27-X1` | `T1` | yes, after the fact | `H-K-T` | Survives when anchored to a zone | Natural fit for zone setups. Same family as F18, so not an extra vote | Price level becomes the setup's zone, tick floor becomes an ATR floor |
| F28 | Refill Elasticity | `LATER` | `T2` | - | `H-PAID-L2` | Harmless for landmarks of 1 s or more. Pre-event depth can be stale, which biases the ratio | **Paid book.** It was entry timing after a sweep, in research | Band of prices walked, landmarks in minutes |
| F29 | Absorption Duration | `LATER` | `T1` | - | `H-K-T` | Current duration survives. Final duration is never an input | Cheap, but only after `F27-X1` | Time at a setup's zone |
| F30 | Breakout after Absorption Failure | `LATER` | `T1` | - | `H-K-T` | Survives after an observed break only | Relevant to breakout setups, but depends on F27 and F29 | Observed break of a setup's level |
| F31 | Momentum–Reversal Score | `DROP` | `T1`, `T2` | - | None | Partly destroyed. Depletion and replenishment net inside a bucket, leaving only their difference | Fixed-weight composite with few independent inputs. `D-OF31-X1` stays defined, and it is `LATER` | Not applicable |
| F32 | Queue Value | `LATER` | `T3` plus fill model | - | `H-T3` | Destroyed | **Needs `T3` for queue position.** Also assumes a resting quote that is out of scope, so very low priority | Not applicable |
| F33 | Fill-to-Adverse-Move Race | `LATER` | `T3` plus fill model | - | `H-T3` | Biased on L2. Queue position is unknown | **Needs `T3` for a credible queue.** The only queue feature with a directional meaning: will a passive entry fill before price runs away? | Minutes-scale race, conservative fill rule |
| F34 | Cancel Success Probability | `DROP` | Own order path | - | None | Not applicable | Needs own send and acknowledgement times. No real orders exist here | Not applicable |
| F35 | Opportunity Cost of Not Filling | `ADAPT` `F35-X1` | `T1` | metric | `H-K-T` | Not applicable | Report metric for rejected setups, required by the charter. **Never a live input** | Counterfactual result of a rejected setup instead of a modelled fill |
| F36 | Inventory-Adjusted Fair Value | `DROP` | Not applicable | - | None | Not applicable | Market-making reservation price. Size comes from the initial stop and exposure belongs to the portfolio layer | Not applicable |
| F37 | Inventory–Flow Conflict | `ADAPT` `F37-X1` | `T1` | yes, with a `T1` input | Same as input | Survives. It is a sign product | Names the frame "flow against my position". Adds no information of its own | Position replaces inventory, normalised flow replaces calibrated alpha |
| F38 | Quote Edge Buffer | `DROP` | Model output | - | None | Not applicable | Built on inputs not used here. The cost check is plain arithmetic at the order layer | Not applicable |
| F39 | Liquidity Stress Index | `ADAPT` `F39-X2` | `T1` | yes | `H-K-T` | The cancel and book parts are removed, so no conflation issue | Risk check. Can only block entries or reduce risk. Needs no side. The fuller `F39-X1` is `LATER` | Book and cancel parts replaced, windows in minutes, hour of week replaces session phase |
| F40 | Volatility of Volatility | `LATER` | `T0`, `T1` | - | `H-K-T` | Survives with longer windows | Likely overlaps `F41-X1` and `F39-X2`. Add only if those leave stress losses unexplained | Inner and outer windows in hours |
| F41 | Jump Score | `ADAPT` `F41-X1` | `T0`, `T1` | yes | `H-K-T` | Survives at a 1-minute grid | Discontinuity flag for the risk check. Not a direction signal. Needs no side | Grid 1 minute, scale window 24 hours, bps |
| F42 | Volume-Time Position | `ADAPT` `F42-X1` | `T0`, `T1` | yes, as a control | `H-K-T` | Survives without a session | Activity control used across the gate, **never a gate input**. Also a seasonal reference. Needs no side | Rolling volume against hour-of-week profile instead of cumulative session volume |
| F43 | Time Since Last Midpoint Change | `LATER` | `T2` L1 stream | - | `H-PAID-L2` | Hazard meaning is lost at minutes. Timing is truncated to 100 ms | Its only use here would be a feed watchdog, and with no feed there is nothing to watch. Run health is defined in [the gate specification](GATE_SPEC.md#34-run-health) instead. Revive with an always-on machine | Formula unchanged if revived |
| F44 | Regime-Conditional Feature Reliability | `LATER` | Any | - | Needs completed folds | Not applicable | Setup counts are too small to fill regime cells. Only worthwhile once two features survive | Regimes from `hour_of_week` and risk state |

## 4. Derived IDs and their exact changes

Notation: `t` is the decision time, `W` the window in minutes, and a record is in the window under G1. `n_j` is trade notional and
`z_j` the taker sign. `E_W(t)` is the expected traded notional for a window of length `W` at `hour_of_week(t)`, from
`F42-X1`. `e_W = E_W / W` is expected notional per minute. Window lengths per decision timeframe are in [the gate specification](GATE_SPEC.md#32-windows-on-the-cycle). Default
constants were chosen without reference to outcomes and are declared, not fitted. What each feature stores between runs, and over what horizon, is in [section 3.7 of the gate specification](GATE_SPEC.md#37-state-each-feature-needs).

### Flow, `T1`, live-eligible

All of these can be computed at a run from polled trades or trade-built minute bars. The same code runs on the archive for
backtests. All are `UNVERIFIED` on the approved source, and those needing the side wait on check D2.

**`D-SV18-X1` signed notional.** Derived from `D-SV18`. `VS_W = sum(z_j * n_j)` and `VA_W = sum(n_j)`. Change: notional replaces
contract quantity. `NS_W = VS_W / E_W` expresses flow in units of normal window volume. Invalid if the unknown-sign share exceeds 1%, or
if the window holds a gap under C2.

**`F24-X1` volume balance.** Parent F24. `B_W = VS_W / VA_W` in `[-1, 1]`. Changes: only the balance output is used, with no
entropy trial. Windows in minutes. Valid only if `VA_W >= 0.1 * E_W`. The count-based balance is a single registered sensitivity.

**`F18-X1` price response.** Parent F18. `PRE_W = dP_W / NS1_W`, with `NS1_W = VS_W / e_W`, `dP_W = 1e4 * (P(t) - P(t-W)) / P(t-W)` and `P(u)` the
notional-weighted price of trades in the last completed minute ending at `u`. Changes: short VWAP endpoints replace mid, so the
feature needs only `T1`. Unit is bps per expected minute of volume. Valid only if `abs(NS_W) >= v_min`, with `v_min` the training-span
median of `abs(NS_W)`, fitted with no outcome and frozen for the block.

**`F19-X1` local lambda.** Parent F19. Huber fit, tuning 1.345, of `dP_i = a + lambda * NS1_i` on non-overlapping 1-minute sub-windows, with `NS1_i = VS_i / e_i` and `e_i` the expected notional per minute at that minute's `hour_of_week`.

- **Fit window.** `(t0 - 24 h, t0]`, with 6 hours as a single sensitivity, where `t0 = t_cut - W` is the start of the scored window. **So a fit never overlaps what it scores.**
- **On `.L`,** it is fitted at each run on that window. Each reference member is scored against a fit on its own `t0`.
- **On `.R`,** the newest fit on a 15-minute schedule with `fit_end <= t0`.
- **Logged and tested.** `fit_end` goes in the decision record, and `fit_end <= t0` is an invariant.
- **Valid only** with 70% or more valid sub-windows and `lambda > 0`. No fallback prior. The change from the canonical parameters is the time scale.

**`D-RR18-X1` response ratio.** Derived from `D-RR18`. `RR_W = PRE_W / lambda`, from `F18-X1` and `F19-X1`. Both use the same per-minute denominator, so under pure linear impact at a stable seasonal level `RR` is about 1. About 0 means absorbed, and below 0 means moved against the flow. It is not repaired with any full-sample ratio. Tested as one family with its two inputs, never as extra votes. Ranked on the grid of [section 4 of the gate specification](GATE_SPEC.md#4-normalisation), valid members only, excluding the ranked window.

**`F26-X1` taker burst.** Parent F26. Consecutive trades with an identical venue match timestamp and an identical sign form one
burst. Fields: `burst_notional`, `n_prices`, and `walk_bps = 1e4 * z * (p_last - p_first) / p_first`. A sweep is a burst with
`n_prices >= 2` and `walk_bps >= 2`, 5 as a single sensitivity. Window outputs: `SW_W = sum(z * n)` over sweeps, divided by `E_W`, and
the largest `walk_bps`. Changes: no complete event exists, so a burst is a proxy that can merge two takers in the same millisecond or
split one. `levels_cleared` is unavailable. A mixed-sign group is invalid. **Invalid unless check D14 shows millisecond or finer match stamps on both REST and the bulk files.** Coarser or batch-publish stamps would make `n_prices` and `walk_bps` fire on whole batches. Its validity is weakly checked, under check D3.

**`F25-X1` large burst.** Parent F25. Robust score `(log(1 + n) - M) / MAD` on the prior 7 days of bursts on the same instrument, with
the current burst added only after scoring. Output `LS_W = sum(z * n * 1{score >= 3}) / VA_W`. Invalid if `MAD = 0` or fewer than 100
prior bursts. Same condition on check D14. Changes: burst unit, notional size, longer reference.

**`F23-X1` flow bar run.** Parent F23. The number of consecutive complete 1-minute bars ending at `t` whose `VS` has the same nonzero
sign, with its net `NS`. An invalid or zero bar breaks the run. Change: bars replace trades.

**`F27-X1` zone absorption.** Parent F27. Episode from the first trade inside the setup's zone within the window, starting **no earlier than the zone's knowable time**. `AE = NS_abs /
(progress + 0.05)`, where `NS_abs` is taker notional pushing into the zone since the episode began, in units of normal volume, and
`progress` is the farthest move through the zone edge in that direction, in units of the strategy's `ATR`. Changes: zone replaces price
level, an ATR floor replaces the one-tick term, which would be near zero here. Only the current value is an input. **It ranks against earlier setups of the same strategy and symbol, whose `knowable_time` is before this look, with at least 30 of them. Otherwise it is invalid.** No hourly grid exists for it, since no zone exists there.

**`F42-X1` relative volume.** Parent F42. `RV_W = VA_W / E_W`, usually as its log, with `E_W` the median over the prior 8
same-`hour_of_week` buckets, recomputed at each run, valid with 6 or more. Each reference member's `E_W` is the value as of that member's own time. Primary `W` is 60 minutes. Changes: rolling window instead of a
session reset, hour of week instead of the session taxonomy. A sensitivity resets at 00:00 UTC. At one `T_d` bar, this is nearly the same
quantity as `SRV` in C3 of the strategy conventions, in notional and with a stricter support rule. **It is a control throughout, and never a gate input.**

**`F41-X1` jump score.** Parent F41. `JS = abs(r_1m) / BV`, with `r_1m` in bps and `BV` the bipower scale of 1-minute returns over the
trailing 24 hours, ending at or before the start of the current return. 6 hours is a single sensitivity. On the cycle, the input is
`JSmax_60`, the largest `JS` in the last 60 minutes. **Minimum scale:** a `BV` below the lower 1% of positive `BV` in the training span makes the value invalid. That cut is fitted with no outcome and frozen. **Adverse** means `JSmax_60` is beyond its frozen limit, and the signed return of the bar that set it runs against the position. Changes: 1 minute grid and 24 hour scale in place of the canonical 100 ms and 30 s.

**`D-RV40-X1` realized volatility.** Derived from `D-RV40`. `sqrt(sum(r_1m^2))` over 60 minutes.

**`F39-X2` stress, `T1` only.** Parent F39. Probit-rank sum, with the rank map frozen at each block's start, of `D-RV40-X1`, `log RV_60m` and the illiquidity ratio
`sum(abs(r_1m)) / sum(n_1m)` over 60 minutes, each with weight +1. It is compared with a frozen limit, the training span's 95th percentile. It is a level, read only against that limit. Changes: book parts replaced, so it runs live. Not comparable in level with `F39-X1`.

**`F35-X1` rejected setup result.** Parent F35. The counterfactual of a vetoed, expired or skipped setup, in `Result_B`, under C14.

- **If `V0.L` traded the setup,** the counterfactual is that trade, on the same seed. This is `CF_CYCLE`.
- **If `V0.L` also rejected the setup,** `CF_IDEAL` applies, for analysis only. It is excluded from `D` and `D_C15`, and reported apart, and it never enters the ledger or `CYCLE` statistics. On a source with no `IDEAL`, this field is empty.
- **On `.R`,** it is the same trade in `IDEAL-1M`.

**Evaluation only.** It is a later event with `knowable_time` at maturity, so it can never be an input.

**`F37-X1` position flow conflict.** Parent F37. `C = -s * (2 * pct(x) - 1)`, with `s` the position side and `pct(x)` the rolling percentile
from [the gate specification](GATE_SPEC.md#4-normalisation). Positive means flow against the position. Changes: position replaces
inventory, normalised flow replaces calibrated alpha. A deterministic frame, so it never counts as separate evidence.

### Book, `T2`, `LATER`

These are `LATER`. **Nothing plans on them, and none runs on this path.** Definitions stay so their IDs are not reused. None could drive a live paper decision on this setup, since no live book exists.

**Conditions to reinstate any of them,** all required:

1. A written owner decision to buy paid book history, entered in the decision log.
2. Check D13 on that stream. Until it passes, availability is stamp plus sampling interval plus `A`, and resample is backward only.
3. A new leak audit of the document. A change of band source is a new derived ID.
4. Its `b`, its thresholds, and any cut, such as the one for `F28-X1`, declared before any run.

`D_side(u)` is displayed notional within `b` bps of mid on that side, from the
latest state at or before `u`. `b` is declared, or taken from the first training span, under check D1. A band that passes the ladder's edge is invalid, never treated as empty.

**`F01-X1` spread in bps.** Parent F01. `SB = 1e4 * (ask - bid) / mid`, with a time mean on a 1 s grid.

**`F02-X1` relative band depth.** Parent F02. Time mean of `D_bid + D_ask` over `W` on a 1 s grid, divided by the median of that
bucket over the prior 8 same-`hour_of_week` buckets, valid with 6 or more. Side-specific forms are validated separately.

**`F05-X1` fill distance.** Parent F05. `IMP_N = 1e4 * abs(p(N) - mid) / mid`, with `p(N)` the marginal price that fills notional `N` by walking
the visible ladder on that side. `N` is the intended order size. Invalid when the ladder ends first.

**`F16-X1` band imbalance persistence.** Parent F16. `I(u) = (D_bid - D_ask) / (D_bid + D_ask)` on a 1 s grid, with the three canonical
summaries kept separate: signed mean, absolute mean, and share of time on the current sign. Valid with 95% or more of grid points valid.
Changes: band for touch, grid mean for integral, windows in minutes.

**`D-OF31-X1` conflated order flow imbalance.** Derived from `D-OF31`. The canonical best-level terms summed across consecutive conflated
states over `W`, divided by `E_W`. Change: buckets replace complete events, so only net change per bucket is seen.

**`F28-X1` band refill to date.** Parent F28. After an `F26-X1` sweep, the ratio of displayed notional at the prices walked, at landmark `u`, to
that notional in the last state before the burst, where "before" must be proved by check D13. `u` is 30 s, with 2 minutes as a single sensitivity. A landmark creates a new decision, and
its target starts after it. Change: band and time scale. Elasticity itself remains a label.

**`F39-X1` stress, `T2`.** Parent F39. Probit-rank sum, frozen in training, of `F01-X1` mean, minus `log F02-X1`, `D-RV40-X1`, and `log RV_W`, with
weights +1, -1, +1, +1. Change: the canonical cancel part is removed because it is not available below `T3`.

### Retired

**`F16-X2` and `F02-X2`.** Both existed only on an archive that `D-17` rules out, so they have no source. The IDs are not reused. A replacement on another stream would be a new derived ID.

## 5. Answers to the required questions

### 5.1 Which features survive aggregation from milliseconds to minutes?

Survival here means the number keeps its meaning. It says nothing about whether it predicts anything.

| Class | Features | Why |
|---|---|---|
| Slow state and regime | F39, F40, F41, F42 (F44 once folds exist) | Already about state. Only time constants change |
| Net trade flow and response | F18, F19, F20, F22 as a `T1` form, F24 balance, F25 as a window summary | Sums and slopes of signed notional scale with time |
| Time-averaged book state | F01, F02, F05, F16, and F03 in form | A sampled state is still a state, but only the mean or the persistence lasts to a 5-minute decision. **All `LATER` on this path** |
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
read, Coinbase's `full` channel and Kraken's `level3` both require authentication. [The data sources document](../03_DATA_SOURCES.md) lists paid L3 events for Bitstamp through Tardis, which would be a purchase and a later owner decision. These would measure one spot venue, whose share of price formation is `UNVERIFIED`.

### 5.3 Do features 32 to 38 apply to a directional mid-frequency entry?

None applies in canonical form. Those features assume a resting quote, a fill model and inventory management.

| ID | Decision | Honest answer |
|---|---|---|
| F32 | `LATER` | Needs a queue model from `T3`, and calibrated fill and markout models. Assumes a resting quote that is out of scope, so a revival is unlikely even with `T3` |
| F33 | `LATER` | The one with directional meaning: a passive entry fills mostly when price is about to go through it. Needs `T3` for a credible queue. Revisit only if a passive-entry variant is registered under G5. At a taker fee this high, the owners may want that question asked, and it is theirs |
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
| Session start and warmup | None. Warmup exists only where bars or state needed for a window are missing |
| Maintenance halt | Venue maintenance or outage, treated as a gap |
| Contract roll | None on spot. Instrument metadata such as tick and lot is versioned by date |
| Settlement, close | None. Spot has no funding, so no funding phase. Index and strategy text naming funding does not apply here, and [the gate specification](GATE_SPEC.md#15-open-items) flags it |
| Early close and holiday classes | Weekends are covered by `hour_of_week`. An approved point-in-time calendar of scheduled macro events is an optional control only |
| Cumulative session volume | Rolling volume, `F42-X1` |

**Seasonal profile.**

- `hour_of_week(t) = 24 * weekday(t) + hour(t)` in UTC, with Monday as 0, giving buckets 0 to 167.
- For a quantity `x`, the profile value is the median of `x` in the same bucket across the prior 8 weeks. It is valid with at least 6 valid weeks (the
  0.75 share is the F02 default, not tuned). Otherwise the value is invalid and is never filled from another bucket.
- Sensitivities are 4 and 26 weeks. Each is counted as a trial.
- Profiles are recomputed at each run from earlier data, and each value is the one as of its own time. Under item 10 of the timing contract, a fixed-window statistic like this is a causal indicator
  and needs no freezing, while a threshold on it is a fitted object. See [the gate specification](GATE_SPEC.md#4-normalisation).

**One flag beside the profile.**

- `qh_phase`: minutes since the last quarter-hour boundary. One preprint on another venue's perpetuals reports bursts of activity at quarter-hour marks (Kim and
  Hansen, 2026), which an hourly profile cannot see. Whether this exists on Kraken spot is `UNVERIFIED`. The reference grid uses minute 7, but **a run's window does not always end there**: `C-LATE` spreads runs across 43 minutes. So a late window can sit on a different quarter-hour phase from its reference members. It is logged, and it is part of why trigger-bar overlap is reported.

**One known weakness.** A UTC profile blurs anything tied to US market hours when daylight saving changes. A sensitivity using New York local hour tests
this. Alexander, Heck and Kaeck (2021) link bitcoin volatility dynamics to US hours, on another venue, and I have not verified how large this effect is on flow features.

### 5.5 How do taker fees compare with the effect being sought?

**The fee.** Values are configuration, and they depend on tier and venue:

| Venue and product | Maker | Taker | Source status |
|---|---|---|---|
| Kraken Pro spot, tier 1 | 40 bps | 80 bps | Kraken fee page, opened 2026-11-04. Higher tiers and the owner's own tier were not read |
| Bitstamp spot | `UNVERIFIED` | `UNVERIFIED` | Page could not be read |

So a taker round trip on the primary source costs **about 160 bps before slippage.** The strategy documents' examples were written with a much lower illustrative fee in C16. **Reference venue decision `D-01` stays separate, and the `RT` used in research must be declared before any block, under C12.** `RT` in C9 is a declared constant. Measured slippage goes to reports, or is fitted per fold, and never changes a past trade list.

**In `R`.** Round-trip cost divided by initial stop distance, using C16's 10 bps round trip for comparison:

| Stop distance | 10 bps, C16 illustration | 160 bps at 1x | 320 bps at 2x | 480 bps at 3x |
|---|---|---|---|---|
| 50 bps | 0.20 R | 3.20 R | 6.40 R | 9.60 R |
| 100 bps | 0.10 R | 1.60 R | 3.20 R | 4.80 R |
| 200 bps | 0.05 R | 0.80 R | 1.60 R | 2.40 R |
| 400 bps | 0.025 R | 0.40 R | 0.80 R | 1.20 R |
| 650 bps | 0.015 R | 0.25 R | 0.49 R | 0.74 R |

This is arithmetic, not a result. **The strategy conventions floor the initial stop at `4 * RT * C_k`, to limit cost to about 0.25 R.** With 1 bp of slippage on each side, `RT` is 162 bps, so the floor is about 650 bps from the close. The design stops are about 60 to 300 bps. So at this fee the floor would bind on nearly every setup, and every strategy's stop, target and frequency would differ from its document. **This is first-order, and it comes before any flow question. I do not decide it.** It belongs to the owner and `strategy-architect`, along with the `RT` to declare.

**The effect.** No effect size exists for our setups, because nothing has been run. The published indications I read are all on another venue's perpetuals, or are at much shorter horizons, and none carries over:

- Kim and Hansen (2026), a preprint: 1-minute opening imbalance shows little association with later returns. 15-minute opening imbalance is associated with
  returns 4 to 12 hours later, with an interquartile effect of its lagged-flow component of about 5 to 6 bps.
- Bieganowski and Ślepaczuk (2026), a preprint, at a 3-second horizon: the BTC taker test did not beat buy and hold.
- Albers et al. (2021), at 500 ms: taker results are particularly weak on markets with large taker fees.

The honest prior: **a flow state is unlikely to predict a mid-frequency move larger than a 160 bps round trip by itself.** That does not end the question, because a gate
does not pay its own fee. It chooses among trades.

**What the gate must actually clear.** With `g` the mean gross per setup under `V0`, `c` the round-trip cost, `p` the kept share, `g_k` the gross mean of kept setups and
`g_v` that of vetoed ones:

- A veto improves total result if and only if `g_v < c`. A veto saves the whole round trip.
- **A random veto passes that test whenever `g < c`.** If `V0` loses after costs, trading less always helps, and that says nothing about flow. So the only meaningful
  comparison is against a placebo veto at the same rate, which means `g_v < g`.
- For the gated strategy to be worth running at all, `g_k > c` is needed. The lift required on kept setups is `c - g`.
- `WAIT` pays no extra fee. Its value is price improvement less the result of missed setups.
- An early exit that replaces a stop adds no fee. One that replaces a maker target adds the taker-maker difference, about 40 bps at the fee read. So the fee hurdle is lowest at exit, where
  the larger cost is cutting winners short.

**What would settle it.** Gross `Result_B` by aligned-flow quintile at setups, one table per class, with confidence intervals from a UTC-week block bootstrap, compared
with placebo, reported at 1x, 2x and 3x cost. **It reads the first training span only,** and each table is a counted trial. If `V0.L` gross there is far below `c`, stop. A gate cannot be asked to rescue that, and the owner should hear it early.

### 5.6 Whose flow is measured, and does that venue lead or follow?

**The measurement is always one venue's flow, never "the market's".** Here that is Kraken spot's flow. Spot flow is not perpetual flow.

**Evidence read.** Alexander, Heck and Kaeck (2021) and Albers et al. (2021) study leadership among venues, as of 2021. The parts I read name other venues as leaders, and give me nothing usable about Kraken spot at these horizons. **I found nothing recent.** Whether this venue leads or follows, and its share of total pressure, are `UNVERIFIED`. Nothing about the source is assumed from another venue.

**Why millisecond leadership is not the point.** At an hourly look, venues have long since converged in price, and a sub-second lead cannot be traded here. What matters is whether this venue's flow is a good measure of total pressure, which cannot be tested without a second source.

**Requirements.** Each source must meet these **before any outcome is seen**.

| # | Requirement | Measured by |
|---|---|---|
| R1 | Written permission or agreement, and reachable from a GitHub runner | Owner. Then check D9 |
| R2 | Signed trades, with the side's meaning proved per endpoint | Checks D2, D14 |
| R3 | Enough reachable recent history to recover a missed run | Check D9, [modelled fetch](GATE_SPEC.md#36-poll-capacity) |
| R4 | An archive with the same definitions as the poll, for backtest parity. A vendor archive stays `.R` until shown | Checks D10, D14 |
| R5 | Fits the job budget of about 3 minutes in [the data center document](../08_DATA_CENTER.md#staying-within-githubs-terms), in a normal and a stressed hour | Check D9, [modelled fetch](GATE_SPEC.md#36-poll-capacity) |
| R6 | Enough activity. **Numeric:** per calendar quarter on both symbols, unproved empty minutes under 1%, and at least 100 trades in each of 90% of hours. Declared here, without sight of any data | Check D8 |

| Source | R1 | R2 | R3 | R4 | R5 | R6 |
|---|---|---|---|---|---|---|
| **Kraken spot** | Permission not requested. Section 9 of its terms bars scripts on its face, and the request names hourly polling. Runner reach `UNVERIFIED` | `b` or `s`, meaning `UNVERIFIED` | `since` cursor, reach `UNVERIFIED` | Bulk files quarterly, then REST. Match `UNVERIFIED` | 1,000 trades per call, spacing 1 to 2 s suggested. Whether it fits is `UNVERIFIED`. See [the arithmetic](GATE_SPEC.md#36-poll-capacity) | `UNVERIFIED` |
| **Bitstamp**, fallback | Commercial agreement, not signed. Price not stated | `type`, meaning not defined on the page read | `time=hour` covers the hour, longest free window one day | Tardis vendor archive, paid. Match `UNVERIFIED` | `UNVERIFIED` | `UNVERIFIED` |

**Registered plan.** Fixed here, before any flow outcome, for both kinds, because choosing a venue after seeing results is a leak class the auditor checks.

| Item | Rule |
|---|---|
| `flow_venue`, `.L` and `.R` | The same source for both. **Kraken spot, then Bitstamp, in that order.** The first to meet R1 to R6 is used |
| Fallback trigger | The status of the written permission only, under `D-22`. Suggested rule: no written yes in 30 days. **Never a result** |
| Tie rule | The list order decides, so a tie cannot arise |
| After results | Nothing reassigns `flow_venue`. A change, for any reason, restarts on later data as a new counted family. Nothing read on one source is reused on another |
| If neither passes | No flow variant runs. The owner decides what comes next |
| `price_venue` | Under C1, one venue per run, so the flow source is the price source. `D-01` stays open and separate. A result must be retested on the venue it names, as the charter requires |
| Cost of the cycle | Only `.R` run on the `.L` source's archive, so venue is never confused with clock |

**What follows from this.**

- **If no source passes, there is no live gate and no live candle strategy either,** since under `D-12` bars come from the same trades.
- **A run on the hourly clock before the source has passed is `.R`.** It tells us about the idea, and it cannot be quoted beside the live record.
- **Venue tests are `LATER`.** Incremental flow from a second venue, information share and lead-lag all need a second source, and there is no second free one. If one is added, it is a new counted family, and it cannot reassign `flow_venue`.

**Signing.** A wrong sign silently reverses a feature, and the mirror test cannot catch it. [Check D2](#8-checks-needed-before-testing) holds the method.

| Source and field | Meaning read in documentation | `z = +1` when |
|---|---|---|
| Kraken REST `Trades`, `b` or `s` | Not stated | **`UNVERIFIED`.** Expected `b`, to be proved |
| Kraken bulk files, `b` or `s` | Not stated | **`UNVERIFIED`.** Expected `b`, to be proved separately |
| Kraken WebSocket v2 `side` | Taker side. This page covers that channel only, and it is not evidence for the two above. The channel is not used here | Not used |
| Bitstamp `type` | Not defined on the page read | **`UNVERIFIED`** |

Venues do differ on this: [the data sources document](../03_DATA_SOURCES.md) records that Coinbase's `side` is the maker's.

### 5.7 What the hourly cycle costs

This section is deliberately blunt. Each row states what is left.

| Capability | Research clock (`.R`) | Hourly cycle (`.L`) | Verdict |
|---|---|---|---|
| Veto at a bar close, 1h and 4h | At the close | At the first run, about 9 minutes or more after the close, using flow up to `t_cut` | **Mostly survives.** Entry is later for every variant, baseline included |
| Risk gate, new entries | Any grid | Each run. Sees stress already visible at the run | **Partly survives.** It blocks entries after stress is visible, and cannot pre-empt within the hour |
| `ENTER` timing | Choose a moment inside the setup's life | Only at a run | **Destroyed at 1h.** Almost nothing to choose from at 4h |
| `WAIT` | Look again in a minute | The next run, up to `expiry` and `A_max`, as C17 states. It is available by the rule in [section 5.4 of the gate specification](GATE_SPEC.md#54-how-wait-works-when-the-next-look-may-be-an-hour-away), which never reads a realised next run. Under `C-LATE`, the next run passes Age for only about 16% to 49% of 1h setups | **Destroyed at 1h,** where a `WAIT` usually ends as `STALE_SETUP`. **Weak at 4h** |
| Acting at a level or zone as price touches it | Possible | Not possible. Seen after the fact | **Destroyed.** The flow hooks in the strategy documents that ask "while price is at the level" cannot be answered live |
| Flow exit on a fast event, such as a sweep against the position | Within a minute | Up to 60 minutes later or more, by which time the stop may already have fired | **Destroyed** |
| Flow exit on slow conflict | Any grid | Each run | **Survives only for trades held many hours.** A trade that closes between runs never gets a look |
| Flow stop tightening | Any grid | Each run | Same as slow flow exit |
| Book imbalance, depth, order flow imbalance, refill | **Not available on this path** | None | **Gone in both.** The owner's "order imbalance" question has no test here, live or backtest, until a paid-data decision |
| Decision timeframes 5m, 15m, 30m | Available | None | **Destroyed for live.** S01 and S06 are backtest only at every timeframe, because the reaction they trade is shorter than the hour lost to the cycle. S08 at 30m is backtest only. S02, S07, S08 and S09 are live at 1h, and S03, S04, S05 and S10 at 1h or 4h |
| Order-level features | Not available either | Not available | Unavailable on this setup in any form |
| Time stops | Exact | Take effect at the first run after they fall due, under rule 7 of charter section 7 | **A limit of the cycle, logged and reported.** See [the gate specification](GATE_SPEC.md#6-flow-exit-on-the-cycle) |

**A partial offset, unproved here.** A dropped run loses decisions but may not lose data, if the REST source keeps enough recent history. A disconnected stream would lose data for good. How far back Kraken's `since` reaches, and whether a backlog fits the job, are `UNVERIFIED`.

**What would need an always-on machine (`D-04`):**

1. `T3` recording, and so any test of F07 to F13, F15, F32 and F33.
2. Any live use of book features: F02, F05 as a series, F16, F28, `F39-X1`, `D-OF31-X1`.
3. Decisions inside the hour: entry at the touch, `WAIT` as real timing, reaction to a sweep.
4. Fast flow exits and fast stop tightening.
5. Live positions at 5-minute to 30-minute timeframes.
6. Measured receive times and latency, and the feed watchdog (F43).
7. Ground truth for the burst proxy.

**Paid book history is a separate decision.** It would let book features be backtested as `.R`. It would not make them live-eligible.

**How to put a number on it, with no machine.** Run the same recipe as `.L` and as `.R` on identical setups, on the same source. `V0.R` minus `V0.L` is the cost of the cycle to candles alone. The difference in gate value between
`VE.F.R` and `VE.F.L` is the cost to flow. If those differences are small, the hourly cycle costs little and `D-15` is confirmed. If they
are large, the owner has a measured case for `D-04`. These are `SIMULATED` estimates.

### 5.8 Does the book snapshot at poll time have any use?

**As a gate input, no.** A single sample of a book state that turns over within seconds, once an hour, carries no persistence and cannot distinguish a real imbalance from a momentary one. **The decision function never receives it, so no `.L` decision can read a book.** It has no history behind it, so any live use would break backtest parity.

**It has at most two narrow uses, and neither is a decision. Both are optional, and need the source's permission.** A separate writer may add it to the record after the commit, as [section 14 of the gate specification](GATE_SPEC.md#14-decision-record) states.

1. **Cost evidence.** Spread and fill distance feed the paper-versus-simulation mismatch report: is the assumed slippage realistic at this minute of the hour?
2. **A slow depth regime, possibly.** Hourly samples accumulated over days could describe a depth regime, because a regime moves slowly enough to survive the sampling. I would not prioritise this, since the illiquidity ratio in
   `F39-X2` addresses the same question from `T1`.

A crossed, locked or empty book is not a run health input. That earlier idea is withdrawn, since it would let a book read affect decisions.

## 6. What the knowledge base does not cover

These have no ES analogue and no canonical ID. Each would need its own document. None is proposed for testing before wave 1 finishes.

| Candidate | Data | Live-eligible? | Note |
|---|---|---|---|
| Order type share | `market` or `limit` on Kraken's time and sales files and REST (`doc`). Meaning `UNVERIFIED` | Possibly | May give a second view of aggression, and it could help check D2. Nothing about it is known yet |
| Funding, premium, open interest | No source for this research | No | **Spot only, so no perpetual or funding inputs.** Kraken Futures keeps 7 days of public trades and has funding history, and mixing it in is out of scope |
| Spot versus perpetual flow divergence | No source | No | Same |
| Forced flow share (liquidations) | No source | No | Same |

## 7. Test order and trial budget

Every feature tried is a trial, and the deflated Sharpe ratio pays for each one. The order below is deliberately short. Live-eligible work comes first, because it is the only
kind that can reach the paper record.

**Test blocks are not reused.** A later wave may start after an earlier one has a verdict, but scored on blocks read before that verdict's date it is `EXPLORATORY`, and it cannot earn `SUPPORTED`. See [the matrix](STRATEGY_FEATURE_MATRIX.md#31-outcomes). **Nothing reads outcomes before the fold plan and locked block are frozen from data coverage alone, and diagnostics that read outcomes read the first training span only.**

**Not hypotheses (no return claim, not counted as gate trials):** `F42-X1` as a control, `F35-X1` as a metric, `F37-X1` as a frame.

| Wave | Family | Kind | Tier | Why here |
|---|---|---|---|---|
| 1a | `F24-X1`, with `D-SV18-X1` as its raw form | `.L` | `T1`, after check D2 | Simplest measure, no conflation issue, and fully computable at a run. If this has nothing, more complicated flow features have a high bar. Everything else must beat it |
| 1b | `F18-X1`, `F19-X1`, `D-RR18-X1` | `.L` | `T1`, after check D2 | Directly addresses the question level strategies pose: did flow make progress? Also controls for flow that merely re-measures the bar |
| 1c | `F41-X1`, `F39-X2` | `.L` | Needs no side | Can only block or reduce risk, and is cheap. Must still beat a placebo. Tested through class test C-4 |
| 1d | `F25-X1` in S09 row 2. `F26-X1` as an event in S01 row 2, S06 rows 1 and 3, on `.R` | `.L`, `.R` | `T1`, after checks D2, D3, D14 | First-pass rows, if D14 allows. `F26-X1` has no separate `.L` first-pass row, since its summary form is degraded and comes in wave 2L |
| 1R | The same families | `.R` | `T1`, same source | Measures the cost of the cycle, and covers timeframes under 1 hour. Evidence for `D-04`, not for live |
| 2L | `F27-X1`, `F23-X1`, `F25-X1` and `F26-X1` as a summary in later rows | `.L` | `T1` | Only where wave 1 gave something to refine, and under the rule above |
| None | Book and `T3` features | - | Paid or not recordable | Not planned |

**Budget.** A first pass uses one declared threshold per feature, on 1 window and 1 source, so each row is one logged line. Sensitivities run only on survivors, and are also logged. `.R` runs are trials too. **[Section 7 of the matrix](STRATEGY_FEATURE_MATRIX.md#7-trial-count) has the bottom-up list of every run, the one symbol rule, and how `N` is set.** Maximum features per strategy is about five, per the role definition.

## 8. Checks needed before testing

**Only D11 and the listed diagnostics read outcomes, on the first training span, and each is counted.** The rest use no flow outcomes, so they cannot contaminate later tests. All of them are open, and **none can start before a written yes**, except D6 on a schedule test that fetches nothing from a source.

| ID | Check | Why it matters | Owner |
|---|---|---|---|
| D1 | **Ladder reach. Revival only.** On a paid archive, how far it reaches from mid in bps. Declare `b`, or take it from the first training span, with out-of-reach treated as invalid | A wider band would be mostly invalid. Later data must not set a band for earlier tests | `data-steward` |
| D2 | **What the side means. Required for every signed feature, `UNVERIFIED` until run.** Separately for REST and for the bulk files, on sampled prints from each year of history. Method, with no book history: under the taker reading, `b` prints near the ask and `s` near the bid, so across adjacent prints the price change on `s` then `b` should be positive on average, and on `b` then `s` negative. Report this per year. Compare with the order type field, since a market order is a taker. The written request to Kraken can also ask this directly | A flipped sign silently reverses every flow feature, and the mirror test passes regardless. If the result is unclear on any endpoint or year, features needing the side do not use that span. A mapping change after results is a new trial | `developer`, `data-steward` |
| D3 | **Burst validity.** Whether `F26-X1` groups look like single takers, against trade ids if the source has them. True ground truth needs taker order ids, so this stays partly `UNVERIFIED` | Timestamp grouping may merge or split takers | `developer` |
| D4 | **Flow population.** Which flagged or unusual trades exist on each endpoint. Result goes to the source card | G8. A choice made after results would be a leak | `data-steward` |
| D5 | **Breaks in the files.** Stamp resolution, fields and format, by year | Features may jump for reasons unrelated to the market | `data-steward` |
| D6 | **Run delay.** Log delay after the nominal minute, job duration and drops by `hour_of_week` from the hourly job, for at least 30 days before paper starts | This gives `C-MEASURED` under C17, to report beside the assumed `C-LATE`. GitHub states that scheduled runs can be delayed or dropped, especially around the start of the hour | `data-steward` |
| D7 | **Conflation damage. Revival only.** Compare book features at several sampling intervals | Tests the claim in section 3 that bucket width is harmless for state | `developer` |
| D8 | **Empty minutes and gaps.** Per source, per quarter, per symbol: empty minutes with proof (`empty_proof = id_run`) and without (`empty_proof = none`), as charter G1 requires, with `continuity` and `max_quiet_s`. This also gives numeric R6 and `T_start` | Quiet is zero flow. Missing is invalid. **Under C2 this may decide how much history is usable, and whether `CYCLE` can run at all on this source** | `data-steward` |
| D9 | **Source from a runner.** Test R1 to R6 from a GitHub runner, after a written yes. Measure page size, rate limit, reachable history, fetch offset, and trades per hour normal and stressed. These fill the C-10 placeholder and [poll capacity](GATE_SPEC.md#36-poll-capacity) | Without them, every result is `.R`, and no `CYCLE` run may start | `data-steward`, owner for terms |
| D10 | **What a run first sees.** Compare the bar at `t_cut` as first seen at a run with later delivered data: the next run's REST pages, then the bulk files. Set `A` at the 99.9th percentile of how late trades arrive. Also reconcile a week of polled bars against the archive, using the tolerance in the data center document | Parity between backtest and live depends on this. 10 s stays `UNVERIFIED` until then | `data-steward` |
| D11 | **Reachable trades.** From `V0.L` on each strategy, the share of trades still open at the first flow look. **First training span only, one counted line per strategy** | If most trades close between runs, a flow exit has nothing to act on. Below 50%, `VX.L` is recorded as not testable for the whole record | `developer` |
| D12 | **Minute-of-hour effect.** Distribution of `F24-X1` by run minute. **Report only.** Minute 7 is frozen, and this cannot move it | Shows what the frozen minute costs | `developer` |
| D13 | **`T2` stamps. Revival only, and required before any `T2` row.** Per stream, test stamp meaning against an independent stream: a state stamped `u` must not reflect trades after `u`. Record `stamp_meaning`. Until it passes, availability is stamp plus sampling interval plus `A`, and resampling is backward only | A snapshot stamped at the start of its interval reads the book from the future, and truncation tests trust the stamp | `data-steward` |
| D14 | **Source card, frozen before any outcome.** Per endpoint, REST, bulk files and candle files separately: side meaning from D2. Stamp meaning and resolution. Whether match time or publish time. Bar label, with `knowable = label + interval` for bars stamped at the start of a period. Trade id or sequence, where a row number never counts. Flagged trades. Tick and lot. Whether a later file corrects an earlier one. `fill_span_allowance_ms` and `stamp_kind` | M13 of the audit. A burst needs fine match stamps on both endpoints, or `F25-X1` and `F26-X1` are invalid. A start-labelled bar used from its stamp is an hour of look-ahead. This also shows whether the source's prices can carry an after-close print, which decides if it gets any `IDEAL` | `data-steward` |

## 9. Sources opened

Knowledge base (`HFT_KB_PATH`), all read directly: `README.md`, `00_TASK_0_EVENT_TIME_AND_INFORMATION_SEMANTICS.md`, `00_FEATURE_DEFINITION_REGISTRY.md`, `FEATURE_DEPENDENCY_MAP.md`, `RESEARCH_GATES.md`, `FEATURE_REGISTRY.md`, `RISK_REGISTER.md`, all 44
feature files, and these cards: data capability audit, cross-feature event semantics audit, control variables and baselines, feature application catalog, red-team amendment, frozen expected impact model, F42 experiment, common research contract, and the shared
episode detector. Summaries here are my own.

Project documents read: charter, data center, data lifecycle, data sources, decision log, roadmap, portfolio outputs, the strategy index in full, the leak audit of these documents, the recheck of the strategy audit, and sections 5, 6, 11, 13 and 14 of all ten strategy documents, plus the time stop sections.

**All Kraken and Bitstamp facts here come from [the data sources document](../03_DATA_SOURCES.md)** unless marked as my own reading below. No file from either has been opened.

External sources were opened on 2026-11-04 through a page-reading tool that returns extracted answers rather than full text. **Treat any detail as needing a check against the source before relying on it.** PDF-only sources could not be read and are not used.
Search results that were not opened are not cited.

| Source | What was read |
|---|---|
| Alexander, Heck, Kaeck (2021), *The Role of Binance in Bitcoin Volatility Transmission*, <https://arxiv.org/abs/2107.00298> | Abstract page. Another venue, and it does not transfer |
| Albers, Cucuringu, Howison, Shestopaloff (2021), *Fragmentation, Price Formation, and Cross-Impact in Bitcoin Markets*, <https://arxiv.org/abs/2108.09750> and <https://ar5iv.labs.arxiv.org/html/2108.09750> | Abstract, first part of the text |
| Kim, Hansen (2026), *The Quarter-Hour Effect*, <https://arxiv.org/abs/2607.09426>, preprint | First part of the HTML text, including sections 2 to 6. Another venue, and it does not transfer |
| Bieganowski, Ślepaczuk (2026), *Explainable Patterns in Cryptocurrency Microstructure*, <https://arxiv.org/html/2602.00776>, preprint | HTML text. Another venue, and it does not transfer |
| GitHub: [events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows), [terms for additional products](https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features) | Schedule behaviour and the Actions section |
| Coinbase: [product trades](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-trades), product endpoint for `BTC-USD` | Side field, tick. Used as illustrations only |
| Kraken: [v2 trade](https://docs.kraken.com/api/docs/websocket-v2/trade), [v2 level3](https://docs.kraken.com/api/docs/websocket-v2/level3), [recent trades REST](https://docs.kraken.com/api/docs/rest-api/get-recent-trades/), [fee schedule](https://www.kraken.com/features/fee-schedule) | Field descriptions, base-tier fees |
| Small REST requests on 2026-11-04 from my tool, before `D-22`, to several venues | Whether a response came back, and field names. **Not from a GitHub runner, and no value from them is used.** None has been repeated since |

Could not be read, so anything depending on them is `UNVERIFIED`: Bitstamp fee page and WebSocket documentation, Coinbase fee pages, and the Easley et al. (2024) PDF.
