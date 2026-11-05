# Gate specification

Status: revised after [the leak audit of 2026-11-04](../reviews/leak/features_2026-11-04.md), and awaiting re-audit. No verdict is claimed here. Date: 2026-11-05. Owner: `feature-integrator`.

This document specifies the entry gate (`ENTER`, `WAIT`, `VETO`, `EXPIRE`) and the flow exit (`HOLD`, `TIGHTEN`, `SCALE_OUT`, `EXIT`). It covers what flow reads inside a run, how thresholds are set on past data, missing-data behaviour, and what happens when a run is late or dropped.

**Nothing here has been tested.** No code exists. Every default below is a declared value chosen without looking at outcomes, not a fitted or measured one, unless it says otherwise. The gate is a hypothesis under test, not a claim that flow improves anything.

**The run belongs to [C17 of the strategy conventions](../01_strategies/00_INDEX.md#c17-hourly-live-cycle), and this document does not redefine it.** Its run clock, run order, time fields, gap rules and delay scenarios apply as written. This document adds only what the gate and the flow exit do inside a run.

**Source (`D-22`).** Kraken spot, BTC/USD and ETH/USD, subject to written permission that has not been requested. Bitstamp is the fallback. All sources stay disabled. `T0` and `T1` only on free data, spot only, with no perpetual or funding input. Nothing about this source is assumed from another venue. Every value that must come from the source is marked `UNVERIFIED`.

Related: [strategy feature matrix](STRATEGY_FEATURE_MATRIX.md), [triage](FEATURE_TRIAGE.md), [decision point map](DECISION_POINT_MAP.md), [data sources](../03_DATA_SOURCES.md), [timing contract](../00_CHARTER.md#3-timing-contract), [data center](../08_DATA_CENTER.md#5-running-on-github-itself).

## 1. What the hourly cycle costs

The whole system runs as scheduled GitHub jobs (`D-15`). There is no continuous flow clock. A decision can happen only at a run, about once an hour, and a run can be late or dropped. So:

| Function | Status on the cycle |
|---|---|
| `VETO` at the first look after a bar close | Mostly survives. This is the realistic live job of the gate |
| `ENTER` | Not a timing decision. It means "the first run after the setup, if nothing blocks it" |
| `WAIT` | Means "the next run, if it comes within `A_max`". At 1h under `C-LATE`, the next run passes the Age check for only about 16% to 49% of setups. See 5.4. Close to worthless at 1h, weak at 4h |
| Flow exit, `TIGHTEN` | Slow conflict only, on trades held for many hours. Fast reaction is gone |
| Book features, `T2` | No live use, and no free history to study them on |
| Timeframes under 1 hour | Backtest only. S01 and S06 are backtest only at every timeframe |

An always-on machine (`D-04`) would restore the live losses. Paid book history would restore the book research. Both are owner decisions, and nothing here plans on them. [Section 5.7 of the triage](FEATURE_TRIAGE.md#57-what-the-hourly-cycle-costs) has the full list.

## 2. Two kinds of variant

Every flow result belongs to exactly one kind. **They are never mixed, averaged or presented as evidence for each other.**

| | Live-eligible, `.L` | Research-only, `.R` |
|---|---|---|
| Mode, from [the mode table](../01_strategies/00_INDEX.md#5-common-conventions) | `CYCLE` under C17 | `IDEAL-1M`, with the look grid in section 10 |
| Inputs | What a run can see: closed 1m bars and trades up to `t_cut` | Trades and 1m bars from the same source's archive, at finer windows |
| Source | The approved source | **The same approved source.** A different one would confound venue with clock |
| Timeframes | 1h, 4h | 5m to 4h |
| Can reach a live paper position | Yes | **No** |
| Report label | `SIMULATED`, with `mode` | `SIMULATED`, `RESEARCH-ONLY`, with `mode`, and for S01 and S06 also their documents' label |
| Compared against | `V0.L` | `V0.R`, which is `V0` under `IDEAL-1M` |

**No flow variant runs in `IDEAL`.** The mode table lets `IDEAL` read only the `settled_*` volume columns, with no plain volume column and no `fill_count`, and a source whose prices can carry an after-close print gets no `IDEAL` results at all. Flow needs signed trades and windows that reach past the close. So `IDEAL` is left to the strategies' own reports. Whether S07 and S08 have `IDEAL` results is open with `leak-auditor`, and it does not change this rule.

| Name | Entry | Exit |
|---|---|---|
| `V0S.L`, `V0S.R` | Candle only | Fixed, control |
| `V0.L`, `V0.R` | Candle only | Dynamic model |
| `VE.F.L`, `VE.F.R` | Gate, filter only: `ENTER` or `VETO` at the first look | Dynamic model |
| `VE.T.L`, `VE.T.R` | Gate, with `WAIT` | Dynamic model |
| `VX.L`, `VX.R` | Candle only | Dynamic model plus flow |
| `VEX.L`, `VEX.R` | `VE.F` | Dynamic model plus flow |

**The baseline must run on the same clock.** Comparing `VE.F.L` with an ideal `V0` would hide the cost of the cycle and misstate the gate. Cross-kind comparison is allowed for one purpose only, which is to measure that cost: `V0.R` minus `V0.L`, and gate value on `.R` minus gate value on `.L`, on the same source. This is the difference C17 reports with `IDEAL-1M` beside `IDEAL`, and on a source with no `IDEAL` it is the only one. The rejection reason R5 in the matrix is the only other decision that may read across kinds.

**No `.L` result exists until all of these hold.** The written permission, the source card (check D14, including the side check D2), the C-10 trade feed values in C17, and reachability from a GitHub runner (check D9). A run on the hourly clock before that is `.R`, whatever clock it used. Until a source is approved, nothing runs at all: under `D-12` every bar comes from that source's trades, so this holds for every strategy and not only the `T1` ones.

## 3. The cycle

### 3.1 Run timeline

**All of this comes from C17.** It is restated here only so that the flow rules below can name it.

| Field | Meaning |
|---|---|
| `run_start` | When the job starts. In a backtest, nominal minute 7 plus the scenario's delay |
| `t_poll[source]` | The runner's clock at the start of the fetch attempt that delivered that source's data |
| `A` | Declared allowance, 10 s, `UNVERIFIED` until measured from a runner |
| `t_cut` | `floor_1m(min(t_poll[source]) - A)`. One per run and symbol, shared by all strategies and variants |
| `P_dec` | Close of the last 1m bar with close time at or before `t_cut` |
| `t_dec` | Commit time. In a backtest, `run_start + D_run`. Used only for fills and `effective_from` |
| `D_run` | As C17 declares per tier. A flow variant uses the same value as its `V0` on the same clock. Re-basing tier `T0` on the shared fetch is part of condition C-10 |
| `latency` | 500 ms |
| `effective_from` | Open time of the first 1m bar with `open_time >= t_dec + latency` that has a price. The same bar is the fill bar. The bar straddling that instant keeps the old values |
| `knowable_time`, `event_time`, `detection_time`, `lateness` | As in the C17 table. For a gate decision, `knowable_time` is the setup's `t_k`, so `lateness` matches the C17 timeline |

**What flow reads.** Step 3b of `decide` reads only bars and trades at or before `t_cut`. A `Bar` window at a run is `(t_cut - W, t_cut]` on the exchange clock. An `Anchored` window ends at its own object's knowable time, which is at or before `t_cut`, and an `F27-X1` episode starts no earlier than the zone's knowable time. Under C17, `t_cut + A <= t_poll <= t_dec` holds by construction, and invariant I10 tests it.

**One source, one fetch.** Flow reads the symbol's trade feed, the same feed that builds its bars under `D-12`, so it adds no source to `min(t_poll)` and its fetch offset is the 0 s in C17. If a later document adds a flow source, its offset must be declared here. A book snapshot is not a source. See 14.

**Bars, not ticks.** Features are built from trade-built 1m bars, except those that need individual trades (`F25-X1`, `F26-X1`, `F27-X1`). The same `decide` runs on the poll and on the archive, as C17 requires.

### 3.2 Windows on the cycle

| Timeframe | Entry window, primary | Entry window, single sensitivity | Exit window | Reference |
|---|---|---|---|---|
| 1h | 60 min | 15 min | 60 min | Section 4 |
| 4h | 240 min | 60 min | 60 min | Section 4 |
| 5m, 15m, 30m | Not on the cycle | | | `.R` only |

Windows are not searched. One bar is primary because it matches the bar that produced the setup. A recipe may instead use an `Anchored` window, as listed in the [matrix](STRATEGY_FEATURE_MATRIX.md). An anchored value is computed once at its object's knowable time and kept in state. See 3.7.

**Trap.** The entry window overlaps the trigger bar, and by how much depends on the delay: a `Bar` first look holds 51 of 60 trigger-bar minutes under `C-FAST`, and as few as 8 at the latest `C-LATE` run, ranked against one reference. It is not future information, but it is a different mix at each delay. So the decision record logs overlap minutes, and the control in section 11 is reported by overlap band.

### 3.3 Late and dropped runs

| Situation | Decisions | What happens |
|---|---|---|
| Run on time or late | Yes | Same rules, on its own `t_cut`. `lateness` is logged |
| Run dropped | None for that hour | A look is lost, and nothing is decided retroactively. The next run walks all the new 1m bars and processes each newly closed `T_d` bar in order |
| Any 1m bar missing since the last processed minute, or an empty minute with no proof of continuity under C2 | **None for this symbol** | `DATA_GAP`. Resolve nothing past the gap. If the gap is still open at the next run, each open position is closed, logged `GAP_CLOSE`. C17 has the hole deadline and corrections |

**The late-run rule.**

1. **Never back-date.** A late run decides on its own `t_cut`.
2. **Never replay missed looks.** A run gives each live setup one look, however many hours were missed. Missed looks are counted.
3. **Life does not stretch.** A dropped run burns setup life. `expiry` and `A_max` count from `t_k`.
4. **Backtest the same way.** Delays and drops come from the C17 scenarios.

Being late does not make a decision invalid, because it uses only data available at its own `t_cut`. It makes it worse, and that cost shows up honestly in `.L` results.

**Open, not decided here.** How `decide` treats a `gap` flag resting on a later row is with `leak-auditor`. The window rule in 3.4 follows that ruling.

### 3.4 Run health

There is no feed to watch, so health is judged per run. This adds to C17 and replaces none of it.

| Check | Where it is defined | Failure | Effect |
|---|---|---|---|
| Source data complete through `t_cut` | C17 completeness check | `t_cut` moves back one minute and the check repeats once, then `DATA_GAP` | No decisions for this symbol, in any variant |
| 1m bars complete, empty minutes proved | C17, C2, charter G1 | `DATA_GAP` | Same |
| Poll fits its budget | 3.6 | Over budget means the data does not reach `t_cut`, so the completeness check fails | Same. **Flow and bars share a feed, so a failed poll is never a flow-only event** |
| State for a window or reference is held | 3.7 | `WARMUP` | That feature is invalid. Reason `flow_blind`. The base strategy continues |
| Taker side usable | Source card, check D14 | Source-wide, before any run | Features needing the side do not run at all |

**The runner's clock has no separate state.** C17 logs the skew at each run. A runner clock running behind only moves `t_cut` earlier. One running ahead moves `t_cut` past the data, so the completeness check fails and the run logs `DATA_GAP`. Both are safe by construction, and `V0.L` and flow variants are treated alike.

**A feature is valid at a run only if** its window holds no gap and its reference and state exist. Otherwise it is invalid, with a reason code, and it is never imputed.

**Missing and quiet are different.** A support failure, such as too little flow, is `NEUTRAL`: the market said nothing. Missing data is `UNKNOWN`: we do not know. See 5.1.

### 3.5 Where flow attaches to the run

C17's order is normative. Flow attaches here and nowhere else:

| C17 stage and step | What flow does |
|---|---|
| `fetch` 0, `decide` 1 to 3 | **Nothing.** Bars, gap checks, the walk, model updates, setup detection and late-entry checks are candle logic |
| `decide` 3b | **Here, at every run.** Flow exit for each open position, then the entry gate for each live setup, oldest first. It reads only bars and trades at or before `t_cut`, with position state as of `t_cut`. It computes no model update |
| `decide` 4 | All decisions commit together, including those from step 3b |
| `settle` 5 | Entries, flow exits and scale-outs fill as C17 states. Every 1m bar before the fill bar is walked first under the stop in force. A touch there stands, and a pending exit is cancelled and logged as superseded |
| `settle` 6 | Flow `TIGHTEN` enters the stored history with its `effective_from` |

**`settle` cannot change a decision, and nothing in it feeds flow.** Posts go out only after the ledger write, as the charter requires.

**Pending exits and overlap.** Flow is not evaluated for a position with an exit already pending from step 3, so no second order can be sent. Under C11, a pending exit counts as open, so a same-run setup on that strategy and symbol is `SKIPPED_OPEN`, whichever step set the exit.

**Idempotency.** A decision is keyed by `(setup_id, run_id)` or `(position_id, run_id)`. A retried run finds the key in the ledger and books nothing new. C17 covers a run that dies after its commit.

### 3.6 Poll capacity

C17 item 3 requires a run that would exceed its budget to behave in a backtest as it would live, and leaves per-source values to this document. Flow has no source of its own, so **these are the trade feed values held as a placeholder in C17 (condition C-10), and no `CYCLE` run may start until `data-steward` fills them.**

| Value | Kraken spot `Trades` | Status |
|---|---|---|
| Page size | 1,000 trades per call | `doc`, in `03_DATA_SOURCES.md`. Confirm under D9 |
| Call spacing | 1 to 2 s between calls is suggested | `doc`. The real limit from a runner is `UNVERIFIED` |
| Recent history reachable with `since` | `UNVERIFIED` | Needed for how far a backlog can be recovered |
| Job budget | About 3 minutes (`08_DATA_CENTER.md`), matching `D_run` of 180 s | Shared by both symbols. Their order and split are declared under C-10 |
| Trades per hour by symbol, normal and stressed | `UNVERIFIED` | Not measured, and no size carries over from another venue |

**Arithmetic only, and an upper bound.** At 1 to 2 s between calls, 180 s gives 90 to 180 calls, so 90,000 to 180,000 trades for both symbols together, before any time for responses. Whether a stressed hour or a backlog on Kraken exceeds that is `UNVERIFIED`.

**Modelled fetch, for every simulated run.**

1. From the archive, count the trades on each symbol since that symbol's last successful fetch, up to the run's cut.
2. Compute `pages = ceil(trades / page size)`, in the declared symbol order, against the shared budget.
3. If a symbol's pages do not fit, its data stops short of `t_cut`, and the completeness check fails exactly as it would live: `t_cut` moves back once, then `DATA_GAP`.
4. The next run starts with the larger backlog. A backlog past the reachable history stays a permanent gap. A gap still open at the next run brings `GAP_CLOSE`.

Dropped runs therefore enlarge later fetches in the backtest, as they would live. **If any value above is unknown, a result is `.R`.** Reports show the share of runs with `DATA_GAP` from capacity. At G8 they compare the live and backtest shares.

### 3.7 State each feature needs

A `.L` backtest reads only what a run would hold. Each member of a reference needs its own point-in-time normaliser (section 4), so the horizon is longer than the reference itself.

| Feature | What is kept | Horizon |
|---|---|---|
| `F24-X1`, `D-SV18-X1`, `F23-X1`, `F42-X1`, `F41-X1`, `F39-X2` | 1m bars with buy notional, sell notional, trade count and price. These also serve the windows and `JS` | 84 days: 28 for the reference, plus 8 weeks for each member's `E_W`. 70 days at the minimum of 6 valid weeks |
| `F18-X1`, `F19-X1`, `D-RR18-X1` | The same 1m bars | 85 days, adding the 24 hour fit that each member needs |
| `F25-X1`, `F26-X1` | Burst summaries per minute, and burst rows for the `F25-X1` reference, because 1m bars cannot rebuild them. Valid only if check D14 shows millisecond or finer stamps on both endpoints | 35 days of burst rows, plus the 84 days of 1m bars |
| `F27-X1` | Trades inside the longest entry window, and the earlier setups' `AE` values for its rank | 240 minutes of trades. `AE` values for the life of the record |
| `Anchored` values | The value computed at the object's knowable time | The object's life, up to its setup's `A_max`. A departure can be days old |

**Where it lives.** The Actions cache, under `08_DATA_CENTER.md` section 5, with a deterministic rebuild or `DATA_GAP`. Sizes are `UNVERIFIED`, and must fit the cache budget in that document.

**After a lost cache.** Rebuilding 84 days through REST at 1,000 trades per call is not expected to fit one job, and rebuild time is `UNVERIFIED`. So what a run cannot recover is `WARMUP`, and the feature is invalid until the state is back. **The backtest does the same.** It applies a declared cache-loss stress, one loss per 90 days at random seeded times, with state back only after the measured rebuild time. Until that is measured, state is back only after the full horizon. These values are my assumptions and are not GitHub figures. Reports show the share of runs in `WARMUP`.

## 4. Normalisation

A feature value becomes a percentile against its own recent past, with no outcomes involved.

- **`pct(x)`** is the mid-rank of `x` in a reference sample, clipped to `[1/(2n), 1 - 1/(2n)]`.
- **Reference on the cycle.** Values of the same feature and window length, computed from 1m bars at minute 7 of each hour over the trailing 28 days, up to 672 values. Using a fixed minute makes the reference independent of when runs actually happened.
- **No overlap.** Each member's window ends at or before `t_cut - W`, so the ranked window never enters its own reference.
- **Point-in-time members.** Each member's `E_W`, and each member's fit for `D-RR18-X1`, is the value as of that member's own time, never today's profile. Test: recomputing a member a month later gives the identical number.
- **Recomputed at each run,** from earlier data. Under item 10 of the timing contract this is a causal indicator with no fitted state, and it needs no freezing. A threshold on it is a fitted object. Section 8 covers that.
- **Minimum.** At least 100 valid members, or the feature is `WARMUP`. A declared value.
- **Symmetrised for signed features.** The reference holds both `x` and `-x`, so mirroring a market exactly mirrors the percentile, and the mirror test can be exact. A real asymmetry between long and short is reported by side. **An inverted trade side passes this test exactly and looks normal, so the mirror test does not check the side. Only check D2 does.**
- **Aligned value.** `A = s * (2 * pct(x) - 1)` in `(-1, 1)`, with `s = +1` for a long setup and `-1` for a short one.
- **Zero-heavy features** (`F25-X1`, `F26-X1`). A window with no sweep or large burst is a real zero, and a percentile cannot say "worst 20%" of a pile of zeros. So these rank among their nonzero members only. Zero is `NEUTRAL`, unless a row names the absence itself, as S06 row 1 does.
- **`RR`.** Ranked on this same grid, valid members only. See the states in [the matrix](STRATEGY_FEATURE_MATRIX.md#21-notation).
- **`AE` in `F27-X1`.** No zone exists on the hourly grid. So it ranks against earlier setups of the same strategy and symbol, whose `knowable_time` is before this look, with at least 30 of them. Otherwise it is invalid.
- **Unsigned risk features** (`F39-X2`, `JSmax_60`) are compared with a frozen limit in their own units. They use no percentile. See section 8.

## 5. Entry gate on the cycle

### 5.1 Recipe

A strategy's gate is a **recipe**, frozen before a test block and set in the [matrix](STRATEGY_FEATURE_MATRIX.md). It holds up to 3 features from the live-eligible list, each with an expected sign `e` relative to the setup side, its window, and a mode (`.F` or `.T`). Layers and features are not collapsed into one score. In the first pass each row is a recipe of one feature.

**Votes.** For each feature at a look:

| Vote | Signed feature | Response state, `D-RR18-X1` | Unsigned risk feature |
|---|---|---|---|
| `BLOCK` | `e * A <= -tau_b` | The state the recipe names | Value beyond its frozen limit |
| `PASS` | `e * A >= tau_p` | The state the recipe prefers | Inside the limit |
| `NEUTRAL` | Otherwise, or **support failed** | Otherwise, including `NO_FLOW` | Not used |
| `UNKNOWN` | **Data missing, or state not held** | Same | Same |

**First-pass values, declared and not fitted.** `tau_b = 0.6`, the worst 20% among members. `tau_p = 0`, so `PASS` means on the favourable side of the rolling median. Exception: S06 row 1, stated in the matrix.

### 5.2 Setup and state

The setup comes from Layer 1 as in [C5](../01_strategies/00_INDEX.md#c5-setup-object-and-gate-window). The state below is kept between runs.

```text
LIVE(looks_used, looks_lost) --> ENTERED | VETOED | EXPIRED    all three terminal
```

The gate cannot resurrect a closed setup, or change its side, stop or expiry. It cannot raise a target: see the last rule of "Flow under `CYCLE`" in C17 and 5.5.

### 5.3 Evaluation at each look

This is step 3b of `decide`. Strict order. The first rule that applies decides.

| # | Condition | Output | Reason |
|---|---|---|---|
| 1 | `t_cut >= expiry` | `EXPIRE` | `expired`, or `no_run` if the setup never received a look |
| 2 | Any **C17 late-entry check** fails at the current `P_dec`: Age, Path, Chase, Risk, Reward or Thesis, with the values in the strategy's section 14, including any it adds | `EXPIRE`, event `STALE_SETUP` | The check's own reason, such as `RR_LATE` |
| 3 | Risk check breached, if in the recipe: `JSmax_60` or `F39-X2` beyond its frozen limit | `.T`: `WAIT` if a look remains. Otherwise `VETO` | `stress` |
| 4 | Any valid feature votes `BLOCK` | `VETO` | `flow_block:<feature>` |
| 5 | Any required feature is `UNKNOWN` | `.T`: `WAIT` if a look remains. Otherwise `EXPIRE` | `flow_blind` |
| 6 | `.F`: no `BLOCK`, all valid | `ENTER` | `no_block` |
| 7 | `.T`: all features `PASS` | `ENTER` | `confirmed` |
| 8 | `.T`: otherwise, a look remains | `WAIT` | `no_confirmation` |
| 9 | `.T`: otherwise, no look remains | `EXPIRE` | `no_confirmation` |

A `DATA_GAP` means no decision at all for this symbol this run, under C17, so no rule is evaluated and the look counts as lost. "A look remains" is defined in 5.4, and `.F` never has one. `V0.L` applies rules 1 and 2 only, followed by `ENTER`.

**What the gate is charged for.** At the first look, `V0.L` and `VE.L` meet the same checks, so a first-look `STALE_SETUP` is not credited to the gate. On `.T`, a setup that `WAIT` carries into a failed check is charged to the gate: `V0.L` may well have traded it. Section 11 says how each case enters the statistic.

**Why a valid `BLOCK` outranks `UNKNOWN`.** Evidence against the setup stands even if another feature is missing. Absence of evidence never allows an `ENTER`.

**Fail closed, by default.** `VE` with missing flow does not trade. Falling back to candle-only behaviour (`FAIL_OPEN`) is a single registered sensitivity, and its trades carry `degraded = true`. **No recipe silently degrades to fewer features.** A reduced recipe would be a separate registered variant.

### 5.4 How `WAIT` works when the next look may be an hour away

C17 states it: `WAIT` means the next run, up to `expiry` and `A_max`. It holds no order and reserves nothing. In every live strategy, `A_max` binds long before `expiry`.

- **Budget.** `looks_max` is 2 at 1h and 3 at 4h, always bounded by `A_max` and `expiry`.
- **A look remains** when `looks_used < looks_max`, and the next nominal run time plus the active scenario's **declared minimum delay** is within both limits. All current scenarios have a 2 minute minimum.
- **The decision never reads a realised next run.** No run can know one. Test: changing the seeded next run time leaves the current output unchanged.
- **A `WAIT` whose next run fails Age** closes as `STALE_SETUP`, and it is charged to the gate.
- **Last-look rule.** At the last look, `WAIT` is not available. `.T` then gives `ENTER` on a full pass, `VETO` on a block, and `EXPIRE` otherwise.
- **A dropped run burns life, not budget.** It counts as a look lost, not a look used.
- **Every look starts over.** Each look recomputes everything on its own `t_cut`, including the C17 checks.
- **Repeated looks are a trial cost.** Multiple looks at a threshold raise the chance of an `ENTER` by luck, and consecutive 60-minute windows can share up to 43 minutes of flow under `C-LATE`. Wait statistics are reported: looks used, looks lost, price change while waiting.

**Is `WAIT` available?** By the rule above, from minute 7, with a 2 minute minimum, the next nominal age is 69 minutes after the first look and 129 after the second.

| `A_max` | Strategies | Available at first look | Available at second look |
|---|---|---|---|
| 75 min, 1h | S04, S08, S09 | Yes | No, this is the last look |
| 90 min, 1h | S02, S03, S05, S07, S10 | Yes | No, this is the last look |
| 150 min, 4h | S03, S04, S05, S10 | Yes | Yes. The third is the last |

**How often does the next run pass Age?** This is the realised rate, for reporting only, and no decision reads it. With `t_cut = floor_1m(run_start - 10 s)`, and by arithmetic on the C17 scenarios' assumed values:

| `A_max` | Look | `C-FAST` | `C-LATE` | `C-BAD` |
|---|---|---|---|---|
| 75 min, 1h | Second | Always | About 16% | About 11% |
| 90 min, 1h | Second | Always | About 49% | About 33% |
| 150 min, 4h | Second | Always | About 95% | About 85% |
| 150 min, 4h | Third | Always | About 49% | About 33% |

These are arithmetic on assumed delays, not measurements. `C-MEASURED` replaces them once 30 days of run logs exist. Whether load at the top of the hour still reaches minute 7 is `UNVERIFIED`.

**Plain expectation, not a result.** At 1h, `WAIT` usually ends in `STALE_SETUP`, and when a second look does happen, the setup has waited a full bar and its window no longer overlaps the moment that created it. So `VE.T.L` is **not a per-strategy test**. It runs once, pooled across the `A_max = 90` strategies, to check this expectation. At 4h it is a fairer test, but the samples there are too small to read per strategy.

### 5.5 After `ENTER`

From C6, C17 and [charter section 7](../00_CHARTER.md#7-dynamic-stops-and-targets), with nothing added:

- **Fill reference.** The open of the first 1m bar with `open_time >= t_dec + latency` that has a price.
- **Collar.** The entry goes out as a marketable limit around `P_dec`. A reference beyond it gives `ENTRY_COLLAR`.
- **Through the stop.** A reference at or beyond `S0` is **not cancelled**. The trade exists and is stopped on the fill bar, logged `ENTRY_THROUGH_STOP`. `Result_B` always includes these trades.
- **Size** uses `R_dec = abs(P_dec - S0)`. **`R`** is `abs(fill - S0)`, fixed at the fill.
- **Target.** Under `.T`, where `WAIT` can make the fill later than the first look, each fill-based term of a target rule uses the less distant of its actual value and its value computed with the first look's `P_dec`, as C17 requires. Flow may never extend a target. `.F` fills at the same run as `V0.L`, so it is not affected.
- **Order style** is taker. No book input reaches this step.

**Rejected setups.** `VETO`, `EXPIRE`, `STALE_SETUP`, `SKIPPED_OPEN` and `ENTRY_COLLAR` all keep their counterfactual under [C14](../01_strategies/00_INDEX.md#c14-event-log). See `F35-X1` in the triage and section 11.

## 6. Flow exit on the cycle

Applies to `VX.L` and `VEX.L`, in step 3b, for open positions with no exit pending.

**The hard rules, from [charter section 7](../00_CHARTER.md#7-dynamic-stops-and-targets), which no parameter can change:**

1. A stop moves only toward the market. Every flow change passes through the ratchet C8, with the C17 clamp.
2. Flow may never widen a stop, extend a time stop or extend a target.
3. `R` and `R_dec` never change.
4. Flow never adds to a position, and a scale-out is never reversed.
5. Stops and targets are resolved first, in steps 2 and 5. Flow acts only on what is still open.

**A stop can only be as good as the run that sets it.** C17 keeps the old stop in force until `effective_from`, and never applies a stop retroactively. A dropped run means a stop that was due to tighten did not, and this is logged. Stops are modelled as orders resting at the venue between runs, as item 13 of the timing contract states, and reports say so.

**Time stops.** Under rule 7 of charter section 7, a time stop takes effect at the first run after it falls due, and fills after that run. The overrun is logged and reported. It is a limit of the cycle, not a rule that extends the stop, and flow has no part in it.

### 6.1 Ladder

**Conflict.** `C = F37-X1` on the recipe's one exit feature, over the exit window, in `(-1, 1)`, positive when flow is against the position.

**First flow look.** The first run with at least one full exit window of post-fill data, so that a trade is judged on flow since it opened.

| Output | Trigger, from a frozen ladder | Action | Event |
|---|---|---|---|
| `HOLD` | None, or any required input invalid | None | Decision record |
| `TIGHTEN` | `C >= c1`, at most twice per trade, at least 2 runs apart | Stop candidate halfway between the stop and `P_dec` | `STOP_UPDATE` |
| `SCALE_OUT` | `C >= c2`, at most once per trade | Close half of what remains, at the C17 fill, less `slip` | `SCALE_OUT` |
| `EXIT` | `C >= c3`, or an adverse `F41-X1` breach | Close the rest, at the C17 fill, less `slip` | `EXIT` |

At each run, the highest triggered action not yet used is taken, and only one per run. A `HOLD` or `TIGHTEN` may follow a `SCALE_OUT`: what cannot happen is that quantity rises or a stop loosens. A trigger needs a single look, since waiting for two would mean two hours.

**Adverse `F41-X1`.** `JSmax_60` is beyond its frozen limit, and the signed return of the bar that set it runs against the position. Only this one trigger reads `F41-X1`. `F39-X2` is not in the ladder.

**Ladder settings** on `(c1, c2, c3)`: `(0.4, 0.6, 0.8)` is the first-pass default. `(0.6, 0.8, 0.9)` and `(0.2, 0.5, 0.8)` are for the class test and survivors only.

**`TIGHTEN` in detail.** `S` is the stop after step 3, **including any model stop pending from this run**. Long: `S_cand = S + 0.5 * (P_dec - S)`, then `S_new = max(S, min(S_cand, C_b - 0.10 * ATR_b, P_dec - 0.10 * ATR_b))`, with `b` the last processed `T_d` bar. Short is the mirror. If this would break the strategy's floor, or leaves the stop unchanged, the action is logged as `tighten_blocked` and not counted. The stop that takes effect at `effective_from` is the tightest of the pending model stop and the flow stop. It enters the stored history, so a later close passes through C8 from it. The bar straddling `t_dec + latency` is ruled by the old stop. If the first bar under the new stop opens through it, the position exits at that open less stop slippage, logged `STOP_GAP`, as in C7.

**Between `T_d` closes.** Flow may act at any run, including runs between 4h closes, using the last closed `T_d` bar, as C8 and C17 now state. The candle model computes nothing at those runs.

**Missing data.** Invalid flow means `HOLD` with reason `flow_blind`. A flow outage is not information about the market. So it never forces an exit, and the position continues under its dynamic model exactly as `V0.L` would.

**When flow exit is not tested.** `flow_reachable_share` is the share of a strategy's `V0.L` trades still open at their first flow look (check D11). It is read on the first training span only, and each reading is a counted trial. If it is below 50%, `VX.L` is recorded as not testable for that strategy for the whole record, and it is not run.

## 7. Failure and fallback on the cycle

| Situation | New entries, `VE.L` | New entries, `V0.L` | Open positions | Record |
|---|---|---|---|---|
| Run late | Normal, on its own `t_cut` | Same | Same | `lateness` logged and reported |
| Run dropped, next run on time | Look lost. C17 checks at the next run | Same | Old stop governs the gap. Touches resolved at the next run with `event_time` and `detection_time`. Updates delayed | Looks lost |
| Actions outage over many hours | As above, and setups go stale | Same | As above. `OUTAGE` event per the data center document | `OUTAGE` in the ledger |
| Poll failing, or over budget (3.6) | `DATA_GAP`, no decisions for the symbol | Same | Nothing resolved past the gap. `GAP_CLOSE` if still open at the next run | `DATA_GAP`, with reason |
| Empty minute with no proof | Same | Same | Same | `DATA_GAP`. See check D8: **this may be common on Kraken spot, `UNVERIFIED`** |
| Gap never filled | Windows crossing it invalid until clear | Normal once bars return | Hole deadline, `GAP_UNRESOLVED`, reported both ways under C17 | Permanent gap noted |
| Cached state lost (3.7) | That feature `WARMUP`, `flow_blind` | Normal, unless the bars themselves are gone | `HOLD`, `flow_blind` | `cache_lost`, and bars marked `rebuild` per C3 |
| Ledger write fails | Run void, counted as dropped | Same | Unchanged | Next run reports the void |
| Schedule disabled, GitHub restricts jobs | Everything stops | Same | Unmanaged | Watchdog may also be silent, as the data center document notes |

**Never fill or repair silently.** A correction is a new ledger event.

## 8. Fitting and freezing

This applies to both kinds, on their own modes. Under item 10 of the timing contract, a rolling percentile needs no freezing, while a threshold on one is a fitted object, frozen before its block.

### 8.1 What is frozen, and when

| Item | Kind | Set from | Frozen |
|---|---|---|---|
| `tau_b`, `tau_p`, the first-pass ladder, the 0.5 and 0.25 rank cuts on `RR`, 30% and 100-member minimums | Declared constant | This document, before any data | Now. A change is a counted trial |
| Nominal minute, `latency`, `A`, `D_run`, seeds | Declared constant | C17 | C17. The check on minute of hour (D12) is a report only |
| `RT` and stop slippage | Declared constant or estimated, chosen before the first run under C12 | The approved venue's values, `UNVERIFIED`. Measured slippage goes to reports. See [the triage](FEATURE_TRIAGE.md#55-how-do-taker-fees-compare-with-the-effect-being-sought) | Before the first run |
| `v_min` | Fitted, no outcome | Training span's median of `abs(NS_W)` | At each block's start |
| `F39-X2` rank map and limit (95th percentile) | Fitted, no outcome | Training span | At each block's start |
| `JSmax_60` limit (99.5th percentile), `F41-X1` minimum scale (lower 1% of positive `BV`) | Fitted, no outcome | Training span | At each block's start |
| Any grid result | Fitted on outcomes | Training span only, under 8.5 | At each block's start |

**The block for fitted objects is the calendar quarter of the fold plan.** The same calendar as C12. **Each artifact is keyed by `(kind, source)`.** `.L` loads only artifacts fitted under `.L` on its own source.

### 8.2 Fold plan, frozen before any outcome

These dates come from data coverage alone, and they are frozen before any `V0` outcome. `project-manager` records them under condition C-7, along with which dates were looked at during the build.

| Item | Value | Status |
|---|---|---|
| Research data end | 2026-09-30, the end of Kraken's bulk files | `doc`. REST catch-up is not used in research blocks |
| **Locked final block** | **2025-10-01 to 2026-09-30, by date.** It does not move as data arrives | Fixed here. Read by nothing before the final verdict, `V0` included |
| `T_start` | The start of the first calendar quarter from which every later quarter meets the coverage rule, on both symbols | **`UNVERIFIED`.** Computed by `data-steward` from the G1 report, with no outcome read |
| Coverage rule | Unproved empty minutes under 1%, and at least 100 trades in each of 90% of hours | Declared here. Numeric form of R6 in [the triage](FEATURE_TRIAGE.md#56-whose-flow-is-measured-and-does-that-venue-lead-or-follow) |
| First training span | 18 months from `T_start` | Declared here |
| Test blocks | Calendar quarters, from the end of the first training span to 2025-09-30, with expanding training | Follows from the above. Expanding training is the ruling `project-manager` is asked to make under C-7 |

**If the fallback applies,** a new table is frozen before the first outcome on that source, and nothing read on Kraken is reused. The fallback is triggered by the permission's status only, never by a result.

### 8.3 What may read outcomes before the blocks

**Only the first training span, and each reading is a counted trial.** That covers the `V0` comparison with C15 for flow purposes, check D11, the setup-free screen and the quintile tables. **Nothing reads the locked block before the final verdict.** `V0` selection follows C18: chosen per fold from training only, under `C-LATE`, on `Result_B`. Flow rows run on the configuration frozen for that block, including its `T_d`.

### 8.4 First pass: nothing is fitted to outcomes

Sample sizes cannot support it, as [section 3.3 of the matrix](STRATEGY_FEATURE_MATRIX.md#33-fixed-thresholds-in-the-first-pass) shows. Each row uses the declared constants in 8.1.

### 8.5 Grid, for class tests and survivors only

1. **Pre-register** the recipe, sign, windows, grid and mode in the trial registry, before the block.
2. **Compute outcomes.** Simulate every setup in the training span under `V0` on the same clock. For `.L`, use `C-LATE`, averaged over the declared seeds.
3. **Grid.**

   | Mode | Grid | Settings |
   |---|---|---|
   | `.F` | `tau_b` in {0.8, 0.6, 0.4}, the worst 10%, 20% or 30% | 3 |
   | `.T` | The same `tau_b`, and `tau_p` in {0, 0.4} | 6 |
   | Exit | The three ladder settings of 6.1 | 3 |

4. **Objective.** `D`, in `Result_B`, as defined in section 11. Per-setup gain is reported beside it, and is `p * (1 - p) * D` for kept share `p`. For exits, the paired `D_x`.
5. **Select.** Standard error by UTC-week block bootstrap, 500 resamples. Keep settings whose `D` exceeds one standard error above 0. Among those within one standard error of the best, take the least restrictive. Requires at least 30% of setups kept and at least 30 rejected.
6. **No setting qualifies? `PASS_THROUGH`.** The gate does nothing for that fold, and that is recorded. A feature is never forced into use.
7. **Freeze** into one versioned artifact. A new live version starts a new, visibly labelled segment of the paper record, per the charter.

### 8.6 Test blocks are not reused for selection

**Each first-pass verdict is recorded with its date.** A later row, grid or sensitivity scored on blocks read before that date is labelled `EXPLORATORY`, and **it cannot earn `SUPPORTED`**. A refinement earns it only on blocks after that date, or once on the locked block. The same holds across waves. An earlier test block may join the training of later blocks only, since it is past for them. Item 11 of the timing contract does not say this yet, so section 15 asks for it.

**Order between kinds.** The `.L` recipes are frozen in the matrix before any `.R` result exists. `.R` and `.L` share calendar blocks and nearly the same setups, so reading `.R` on a quarter largely reveals `.L` on it. A new `.L` recipe written after reading `.R` on a block counts that block as used.

### 8.7 Purge and embargo

**These follow item 11 of the timing contract and C18.** A training setup is removed from selection when `t_k + H_max` reaches the block, using the maximum possible hold and not the actual exit, so removal does not depend on the outcome. Under `CYCLE`, add `A_max` plus 2 hours, and the active scenario's largest declared overrun beyond that, such as the 90-minute hole in `C-GAP`. Each training simulation's data ends at the block's start, and a trade still open then is removed and counted. That also covers a trade whose stop was touched before the block but detected after it, and a run of drops longer than any declared overrun.

The audit's fix for this item was written on a label's end, using detection times. Item 11 and C18 were ruled after it, and they use the maximum possible hold, so they govern here.

- **Class tests** use the largest `H_max`, `A_max` and overrun in the pool.
- **Both sides.** Nothing at or after a block's start is in its training. A finished block joins later blocks' training under the same purge.
- **Counterfactuals** are later events, with `knowable_time` at maturity, under C14.
- **Bootstrap weeks** are assigned by `created_at`.

### 8.8 Ablation

**Ablation is removing one member of a recipe to see what it adds.** It is pre-registered per recipe and decided on training spans, and each removal is a counted trial. On test blocks, only a frozen recipe is reported. "No gain beyond row 1" is scored on identical setups, under 8.6.

### 8.9 Pooling

Long and short share one threshold. BTC/USD and ETH/USD have their own references, and thresholds are pooled per strategy. Results are reported by side and by symbol. [Section 7 of the matrix](STRATEGY_FEATURE_MATRIX.md#7-trial-count) holds the one symbol rule and every trial.

## 9. Backtest parity for live-eligible variants

A `.L` backtest must measure what the live record measures. **C17 sets this out under "Backtest reproduction", and those rules apply as written.** Flow adds the items below. **If any item cannot be met, the result is `.R`, whatever it is called.**

| # | Requirement |
|---|---|
| P1 | **Same inputs.** Only what `decide` receives, truncated at `t_cut`, from the approved source. The source card (check D14) covers both REST and the bulk files, and check D10 reconciles them |
| P2 | **Same scenarios.** `C-LATE` is the headline and selection scenario. `C-FAST` is the upper bound. `C-BAD` and `C-GAP` are stress reports. At least 5 declared seeds per random scenario, with the spread. `D_run` and fetch offsets are drawn or set as C17 says, so the backtest's `t_cut` equals what the run would hold |
| P3 | **Same state.** Features read only the state in 3.7, under the cache-loss stress there. What a run could not recover is `WARMUP` on both paths |
| P4 | **Same reference.** As in section 4 |
| P5 | **Same poll capacity.** The modelled fetch in 3.6. The backtest goes blind in exactly the hours live would |
| P6 | **One run-time draw.** All variants and placebos of a recipe share it, seed by seed |

**`C-MEASURED`.** Once 30 days of logs exist, it reports alongside. Re-running a selection under it is a new counted trial, and it applies to later blocks only.

**Replay.** C17 requires the live period to be replayed with actual run times, from the as-seen inputs in `decisions/`. Decisions and vetoes are checked in the same way. Every mismatch goes into the paper-versus-simulation report for gate G8, with its cause.

## 10. Research-only variants

**These cannot reach a live position on this setup.** They exist to study what the cycle removes and to cover timeframes under 1 hour. S01 and S06 exist only here, apart from their control run through `C-LATE`. There are **no book rows** on the free path.

**Mode.** `IDEAL-1M`. A look at instant `u` reads records with exchange time at or before `u`, and it fills at the first 1m bar with `open_time >= u + max(latency, A)` that has a price, under the C6 collar. The exit engine walks 1m bars in time order, stop first inside each. New stops and targets act from that same first bar, and the straddling bar keeps the old values. **No fill or update precedes its decision.** C7's text naming `O_(k+1)` belongs to `IDEAL` and does not apply here.

| Timeframe | Entry window, primary | Entry window, sensitivity | Exit window | Look spacing |
|---|---|---|---|---|
| 5m | 5 min | 1 min | 1 min | 60 s |
| 15m | 15 min | 5 min | 5 min | 60 s |
| 30m | 30 min | 10 min | 10 min | 60 s |
| 1h | 60 min | 15 min | 15 min | 60 s |
| 4h | 240 min | 60 min | 60 min | 300 s |

**State machines.** The entry gate of section 5 and the flow exit of section 6 apply as written, with these differences: C5 replaces the C17 checks, the first look is at `t_k`, each later tick is a look, the exit requires two consecutive ticks, `looks_max` is bounded only by `expiry`, and the reference is sampled every minute over 28 days. Instead of run health, an archive gap invalidates any window crossing it.

**Inputs.** All live-eligible features at finer windows, and `F26-X1` as an event if check D14 allows it.

## 11. Evaluation requirements

For all flow variants. **Outcomes and rejection rules are in [section 3 of the matrix](STRATEGY_FEATURE_MATRIX.md#3-rejection-rules).** Gates, placebo comparisons and variant comparisons use **`Result_B`**, under charter section 7 rule 4. `R` may be shown beside it.

**The statistic.**

- `D` is the mean `Result_B` of kept setups minus that of blocked setups.
- **Per setup, on a shadow `V0` trade that ignores C11,** because whether a setup is skipped depends on how an earlier one ended. Path results under C11 are reported separately.
- **`blocked` means rules 3 and 4 of 5.3 only.** Rules 1, 2 and 5 are reported apart.
- **Setups `V0` also rejected** are excluded from `D` and `D_C15`, and reported apart. `CF_IDEAL` is for analysis only, under C14.
- **`CYCLE` figures** are the mean over the declared seeds, with the spread shown. "Positive under `C-BAD`" means that mean.
- **Timing.** `VE.T` is compared with `VE.F` on identical setups, by the mean `Result_B` per setup. A setup that `WAIT` carried into `STALE_SETUP` counts as 0 for `VE.T`, against its `CF_CYCLE` under `VE.F`.

**Placebos.** All are required. A random veto looks good whenever costs exceed gross, as [the triage](FEATURE_TRIAGE.md#55-how-do-taker-fees-compare-with-the-effect-being-sought) shows. Placebos are controls, logged and labelled as controls.

| Placebo | How | What beating it shows |
|---|---|---|
| Random veto | Same rate, stratified by `hour_of_week`, 200 draws. `D` is near 0 in expectation | Selection beats trading less |
| **C15 placebo** | The same recipe on the strategy's [C15](../01_strategies/00_INDEX.md#c15-placebo-control) setups, as C15 defines them per strategy. Distribution from earlier blocks. At least 100 declared draws, no redraws, compared with their mean, and the distribution shown. Under `.L`, through the same run function and run times | Flow says something about this mechanism, and is not just a general market filter |
| Shifted flow | Same feature from the same hour one week earlier | Beats a seasonal pattern |
| Reversed sign | Flip the expected sign | Should do worse. If not, the feature is not doing what the recipe claims |

**Control for re-measuring the bar.** Report each flow feature's effect after controlling for the return over the same window, `F42-X1` and hour of week, by overlap band (3.2). If it vanishes, the gate is re-reading the candle.

**Blind set.** Results are shown for setups where flow was valid, compared with `V0` on those **same** setups, plus separately the blind set. Otherwise a gate can look better by simply avoiding periods when data went missing, a selection effect that has nothing to do with flow.

**Decomposition.** Filter value, from `VE.F`. Timing value, from `VE.T` against `VE.F`. Exit value, from `VX`. Cycle costs from section 2. Reports always include `flow_reachable_share`, looks lost, `lateness`, `STALE_SETUP` by reason, time stop overruns, and the capacity and `WARMUP` shares.

**Costs.** At 1x, 2x and 3x, per charter section 6. Measured slippage is a report and never changes a trade list. See 8.1.

**Statistical power.** To detect a difference `D` in mean `Result_B` between kept and rejected setups, keeping share `p`, at two-sided 5% and 80% power, with outcome standard deviation `sigma`:

```text
n >= (1.96 + 0.84)^2 * sigma^2 * (1/p + 1/(1 - p)) / D^2
```

With `p = 0.7` and an **assumed** `sigma = 1.2`, in units of the risk budget:

| `D` | Setups needed |
|---|---|
| 0.3 | About 600 |
| 0.2 | About 1,350 |
| 0.1 | About 5,400 |

These are before any multiple-testing correction, and overlapping setups count for less. **[Section 4 of the matrix](STRATEGY_FEATURE_MATRIX.md#4-can-each-gate-question-be-answered) applies this to each strategy, and predicts `INCONCLUSIVE` for most.** An inconclusive result must be reported as inconclusive and not as a failure or a pass.

**Setup-free screen.** Each first-pass feature against forward returns at 1 and 4 hours has far more power for the question "is there any information?". It reads the first training span only, and each line is a counted trial.

## 12. Invariants and required tests

The first group must hold for every run, in code. The second group follows the [leak auditor's list](../../.claude/agents/leak-auditor.md) and C17's required tests.

| # | Invariant |
|---|---|
| I1 | A stop never moves away from the market. On the same path, a `VX` stop is never looser than the `V0` stop |
| I2 | Flow never extends a time stop or a target. On `.T`, each fill-based target term is at most as distant as its first-look value |
| I3 | `R` and `R_dec` never change once set |
| I4 | Flow never increases a position, and a scale-out is never reversed |
| I5 | At most one flow action per run. No flow decision on a position with an exit pending |
| I6 | **All-flow-invalid equivalence.** With all flow invalid, `VX.L` must produce exactly the trades of `V0.L`. With `FAIL_OPEN`, `VE.F.L` must also. With fail closed, it must produce no trades |
| I7 | **Pass-through equivalence.** With `PASS_THROUGH`, `VE.F.L` must equal `V0.L` exactly |
| I8 | No `.L` decision input comes from `T2`. `decide` never receives a book snapshot. `.L` loads only `.L` artifacts on its own source. No `.L` result is written without its parity manifest |
| I9 | One decision per `(setup_id, run_id)` or `(position_id, run_id)`, however many times a run is repeated |
| I10 | Every flow input has `exchange_ts <= t_cut`, and `t_cut + A <= t_poll <= t_dec` |
| I11 | `fit_end <= t0` on every `F19-X1` fit, with `t0 = t_cut - W`, and on each reference member's own `t0` |

| Test | What it proves |
|---|---|
| Truncation | Removing data after `t_cut` changes nothing in `decide`, with held state as of `t_cut` |
| Future perturbation | Randomising data after `t_cut` changes no decision at or before that run |
| Poll offset | Varying `run_start` and the poll offset gives the `t_cut` that C17 defines, and the backtest never holds more than the run would |
| Shift | Delaying inputs by one run. A sharp collapse is suspicious |
| Mirror | Swapping side and sign mirrors every decision exactly. This does not test the side's meaning |
| Next run | Changing the seeded next run time leaves the current `WAIT` output unchanged |
| Target on `.T` | A fill made later by `WAIT` gives no fill-based target term further away than its first-look value |
| Stop under `VX` | On the same path, with a model stop pending in the same run, the stop in force is never looser than under `V0` |
| Late run | A late run gives the same decision whether simulated or replayed, and it never fills before `t_dec + latency` |
| Dropped run | Stops are resolved across the gap, looks are lost, `expiry` and `A_max` do not stretch, no retroactive decision appears |
| Capacity | A run over budget gives `DATA_GAP` in the backtest although the archive holds the trades |
| Cache loss | A feature whose state is gone is `WARMUP` on both paths |
| Member | Recomputing a reference member a month later gives the identical number |
| `.R` fill | No fill or update precedes its decision |
| Crash | A crash at each run step leaves a valid ledger, and a retry books nothing twice |
| Coverage | A hole in the poll invalidates exactly the windows that cross it |
| Replay | Section 9 |

Hand fixtures for each state transition are required before a verdict on gate G2.

## 13. Worked example

**Invented numbers, for checking the rules only. This is not a market result.** `VEX.L`, 1h long on BTC/USD, in the style of S02. Recipe: `F24-X1`, `e = +1`, `tau_b = 0.6`, window 60 min. Ladder `(0.4, 0.6, 0.8)`. `latency` 500 ms, `A` 10 s, slippage 1 bp. `D_run` is taken as 180 s for the example, since S02's tier value is being re-based under C-10. Setup: `C_k = 60,000`, `S0 = 59,400`, `T1 = 61,000`, `ATR_k = 300`, `t_k = 10:00`. Checks: `A_max` 90 min, chase `0.75 * ATR_k = 225`, risk up to `2.5 * ATR_k = 750`, `RR_late = 1.0`.

**Run nominally at 10:07, delayed 2 min 20 s.** `run_start = 10:09:20` is `detection_time`, and `lateness` is 9 min 20 s. `t_poll = 10:09:20`. `t_cut = floor_1m(10:09:10) = 10:09:00`. `P_dec = 60,040`, the close of the bar closing 10:09. `t_dec = 10:12:20`.

- C17 checks: age 9 min passes. Path passes. Chase 40 passes. Risk 640 passes. Reward `61,000 - 60,040 = 960` is at least 640, so it passes.
- Window `(09:09, 10:09]`. `B_60 = -0.08`. Percentile 0.46, so `A = -0.08`. `e * A = -0.08`, above `-0.6`.
- `.F` gives `ENTER`, reason `no_block`. `R_dec = 640`, and size is `risk_budget / 640`. The collar is `60,040 + 150 = 60,190`.
- Fill: the first 1m bar with `open_time >= 10:12:20.5` opens at 10:13:00, at 60,060, inside the collar. With slippage, fill is 60,066. `R = 666`.

**The run at about 11:07 is dropped.** No flow look, no stop update, and the 11:00 bar goes unprocessed.

**Run nominally at 12:07, delayed 1 min.** `run_start = 12:08:00`. `t_cut = floor_1m(12:07:50) = 12:07:00`. `t_dec = 12:11:00`.

- Step 2: 1m bars up to 12:07 show no touch.
- Step 3: bars closing 11:00 and 12:00 are processed in order. Suppose the model's ratchet leaves the stop at 59,400.
- Step 3b, first flow look: post-fill data covers more than 60 minutes. Window `(11:07, 12:07]`. Percentile of `B_60` is 0.15, so `C = +0.70`. `C` is above `c2 = 0.6` and below `c3 = 0.8`, so the highest unused action is `SCALE_OUT`.
- `settle`: the first 1m bar with `open_time >= 12:11:00.5` opens at 12:12:00. Bars from 12:07 to 12:12 are walked first under the stop in force. No touch, so half closes at that open, less `slip`.

**Run nominally at 13:07, delayed 1 min 10 s.** `run_start = 13:08:10`. `t_cut = floor_1m(13:08:00) = 13:08:00`.

- Step 2: the 1m bar closing 12:41 touched the stop. The rest closes at the stop, less stop slippage, with `event_time = 12:41`, `detection_time = 13:08:10`, and `lateness` of 27 min 10 s.
- No flow look occurs, since the position is already closed.

The stop fired at 12:41, and it took until 13:08 to know. The flow reading that might have helped could not arrive any sooner than the next run. That is the cost of the cycle in one example.

## 14. Decision record

Every look and every exit evaluation writes one append-only record to `decisions`, before anything is posted. Time fields follow C17.

| Group | Fields |
|---|---|
| Identity | `decision_id`, `setup_id` or `position_id`, `run_id`, strategy, symbol, side, variant name, kind, `mode`, scenario and seed in a backtest |
| Clock | `knowable_time`, `event_time`, `detection_time`, `effective_from`, `lateness`, `t_poll`, skew, `t_cut`, `t_dec`, `P_dec`, run delay after the nominal minute, `looks_used`, `looks_lost`, trigger-bar overlap minutes |
| Output | Decision, reason code, C14 event, and for exits: old and new stop, quantity |
| Inputs | For each feature: value, window, percentile, vote, valid flag, reason, and `fit_end` where it applies |
| Health | Completeness result, and whether it passed on server time alone, state held per feature, capacity use |
| Versions | Recipe, threshold artifact, data, code |

**Book snapshot: optional, and outside `decide`.** If the permission covers it, a separate writer may fetch spread and fill distance **after** the commit, for the mismatch report only. It never reaches `decide`, it is not a source in `min(t_poll)`, and it never takes part in run health. It has no history behind it, so it cannot be backtested. It is off by default.

No market data goes into git beyond what `D-21` and the data documents allow. Whether publishing these values is allowed under the source's terms is part of the written request in [the data sources document](../03_DATA_SOURCES.md).

## 15. Open items

| Item | Owner | Blocks |
|---|---|---|
| **Open, not decided here:** S07 and S08 under `IDEAL` | `leak-auditor`, ruling now | Those strategies' `IDEAL` reports. Flow does not run in `IDEAL` either way |
| **Open, not decided here:** how `decide` treats a `gap` flag resting on a later row | `leak-auditor`, ruling now | The window rule in 3.4 follows it |
| Written permission from Kraken, not yet requested. Fallback by its status only | Owner, `D-22` | Everything on market data |
| Source card, including what `b` and `s` mean (checks D2, D14). The written request could ask Kraken this directly | `data-steward`. Owner for the request | Every feature needing the taker's side |
| C-10 trade feed values in 3.6, `A`, `fill_span_allowance_ms`, reachability from a runner | `data-steward` | All `.L` results |
| `T_start` and the fold table in 8.2 | `data-steward`, `project-manager` under C-7 | First `V0` run |
| Amend item 11 of the timing contract: an earlier test block may join the training of later blocks only | `project-manager` | Section 8.6 reads this way until then |
| **`RT` on the approved venue.** Kraken Pro's base-tier taker fee as read on 2026-11-04 implies a round trip of 160 bps before slippage. See the triage. `D-01` stays separate | Owner, `strategy-architect` | First run |
| C1 still says "one linear perpetual", and several strategy documents assume funding and easy shorting. Research is now spot. How shorts are simulated on spot is `UNVERIFIED` | `strategy-architect`, `project-manager` | First `V0` run on the source |
| Whether empty minutes without proof make `DATA_GAP` common on Kraken spot (check D8) | `data-steward` | Whether `CYCLE` can run on this source at all |
| Whether an hourly paper engine and a public channel sit within GitHub's terms. See decision `D-16` | Owner | Live paper |
| Whether the hourly schedule should ever be shortened. GitHub allows down to 5 minutes, but that would raise the question above, and poll capacity depends on it | Owner, under `D-04` | Nothing now |
