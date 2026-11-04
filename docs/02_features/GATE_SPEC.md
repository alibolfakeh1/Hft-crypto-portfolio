# Gate specification

Status: draft for leak audit. Date: 2026-11-04. Owner: `feature-integrator`.

This document specifies the entry gate (`ENTER`, `WAIT`, `VETO`, `EXPIRE`) and the flow exit (`HOLD`, `TIGHTEN`, `SCALE_OUT`, `EXIT`). It covers the clock, the windows, how thresholds are set on past data, missing-data behaviour and what happens when a run is late or dropped.

**Nothing here has been tested.** No code exists. Every default below is a declared value chosen without looking at outcomes, not a fitted or measured one, unless it says otherwise. The gate is a hypothesis under test, not a claim that flow improves anything.

**The run itself is defined in [C17 of the strategy conventions](../01_strategies/00_INDEX.md#c17-hourly-live-cycle), and this document does not redefine it.** Its run order, time fields and delay scenarios apply as written. This document adds only what the gate and the flow exit do inside a run.

Related: [strategy feature matrix](STRATEGY_FEATURE_MATRIX.md), [triage](FEATURE_TRIAGE.md), [decision point map](DECISION_POINT_MAP.md), [timing contract](../00_CHARTER.md#3-timing-contract), [data center](../08_DATA_CENTER.md#5-running-on-github-itself).

## 1. What the hourly cycle costs

The whole system runs as scheduled GitHub jobs (`D-15`). There is no continuous flow clock. A decision can happen only at a run, about once an hour, and a run can be late or dropped. So:

| Function | Status on the cycle |
|---|---|
| `VETO` at the first look after a bar close | Mostly survives. This is the realistic live job of the gate |
| `ENTER` | Not a timing decision. It means "the first run after the setup, if nothing blocks it" |
| `WAIT` | Means "the next run, if it comes within `A_max`". At 1h under `C-LATE` a second look exists for only about 13% to 46% of setups. See 5.4. Close to worthless at 1h, weak at 4h |
| Flow exit, `TIGHTEN` | Slow conflict only, on trades held for many hours. Fast reaction is gone |
| Book features, `T2` | No live use at all |
| Timeframes under 1 hour | Backtest only. S01 and S06 are backtest only at every timeframe |

An always-on machine (`D-04`) is what would restore the losses. [Section 5.7 of the triage](FEATURE_TRIAGE.md#57-what-the-hourly-cycle-costs) has the full list and shows how to measure the cost without building one.

## 2. Two kinds of variant

Every flow result belongs to exactly one kind. **They are never mixed, averaged or presented as evidence for each other.** The charter has adopted these names.

| | Live-eligible, `.L` | Research-only, `.R` |
|---|---|---|
| Clock | `CYCLE` under C17, with delays and drops reproduced | `IDEAL` under C5 to C7, section 10 |
| Inputs | What a run can see: closed 1m bars, and trades since the last run from the poll source or its archive | Any `T1`, `T2` archives |
| Timeframes | 1h, 4h | 5m to 4h |
| Can reach a live paper position | Yes | **No** |
| Report label | `SIMULATED` | `SIMULATED`, `RESEARCH-ONLY`, and for S01 and S06 also `IDEAL, NOT LIVE-COMPARABLE` |
| Compared against | `V0.L` | `V0.R` |

| Name | Entry | Exit |
|---|---|---|
| `V0S.L`, `V0S.R` | Candle only | Fixed, control |
| `V0.L`, `V0.R` | Candle only | Dynamic model |
| `VE.F.L`, `VE.F.R` | Gate, filter only: `ENTER` or `VETO` at the first look | Dynamic model |
| `VE.T.L`, `VE.T.R` | Gate, with `WAIT` | Dynamic model |
| `VX.L`, `VX.R` | Candle only | Dynamic model plus flow |
| `VEX.L`, `VEX.R` | `VE.F` | Dynamic model plus flow |

**The baseline must run on the same clock.** Comparing `VE.F.L` with `V0` under `IDEAL` would hide the cost of the cycle and misstate the gate. Cross-kind comparison is allowed for exactly one purpose, which is to measure that cost. `V0.R` minus `V0.L` on the same data is the `IDEAL` minus `CYCLE` difference that C17 already requires. Gate value on `.R` minus gate value on `.L` is the same measure for flow. `T2` results always carry the caveat that a next-day archive is not a live feed.

**No `.L` result exists until check D9 names a poll source.** A run on the hourly clock using an archive whose REST source has not passed is `.R`, whatever clock it used. If no source passes, `VE.L`, `VX.L` and `VEX.L` cannot run, and live paper is `V0.L` only. S07 and S08 are `T1` strategies, so they would not run live at all.

## 3. The cycle

### 3.1 Run timeline

Everything here comes from C17, except the one helper marked below.

| Field | Meaning | Source |
|---|---|---|
| Nominal minute | Fixed minute after the hour when a run should start. Default 7 | C17 |
| `t_dec` | Decision time of the run | C17 step 4 |
| `P_dec` | Close of the last completed 1m bar | C17 step 4 |
| `latency` | Declared. Entries, close-based exits and flow exits fill at the open of the first 1m bar with `open_time >= t_dec + latency`. New stops and targets act from `t_dec + latency` | C17 steps 5 and 6 |
| `knowable_time` | When an input became knowable | C17 |
| `event_time` | Close of the 1m bar in which a touch or fill happened, or `t_dec` for a decision | C17 |
| `detection_time` | Start of the run that found it | C17 |
| `effective_from` | When a new stop or target starts to act | C17 |
| `lateness` | `detection_time - knowable_time`. For a gate decision, `knowable_time` is the setup's `t_k`, so `lateness` matches the C17 timeline | C17 |
| `t_last` | **Helper, this document only.** Close time of the bar that gives `P_dec`. Every flow window ends here | This document |

**What a record's availability means.** Polled data arrives in one batch, so every trade polled at a run has about the same receive time, up to about an hour after it happened. Windows are therefore defined on the exchange clock, and availability is checked against the run: a record may be used if its exchange time is at or before `t_last` and it was received by `t_dec`. A window at a run is `(t_last - W, t_last]`. This satisfies item 6 of the timing contract. In backtests, C17 requires data shown only up to `t_dec` less a declared allowance, and that allowance is 10 s by default.

**Bars, not ticks.** Features are built from trade-built minute bars, as `D-12` requires, except those that need individual trades (`F25-X1`, `F26-X1`, `F27-X1`). The same run function is used on the poll and on the archive, as C17 requires.

### 3.2 Windows on the cycle

| Timeframe | Entry window, primary | Entry window, single sensitivity | Exit window | Looks possible | Reference |
|---|---|---|---|---|---|
| 1h | 60 min | 15 min | 60 min | 1, sometimes 2. See 5.4 | Hourly grid, section 4 |
| 4h | 240 min | 60 min | 60 min | 2, sometimes 3. See 5.4 | Hourly grid, section 4 |
| 5m, 15m, 30m | Not on the cycle | | | | `.R` only |

Windows are not searched. One bar is primary because it is the natural unit and it matches the bar that produced the setup. A recipe may instead use an `Anchored` window tied to a strategy object, such as a departure or a box, as listed in the [matrix](STRATEGY_FEATURE_MATRIX.md). An anchored value is computed from cached bars and has its own `knowable_time`.

**Trap.** The entry window overlaps the trigger bar, so aligned flow may only re-measure the same move. Section 11 requires a control for this.

### 3.3 Late and dropped runs

| Situation | Decisions | What happens |
|---|---|---|
| Run on time or late | Yes | Same rules, at its actual `t_dec`. `lateness` is logged |
| Run dropped | None for that hour | A look is lost. Nothing is decided retroactively. C17 has the next run walk all the new 1m bars and process each newly closed `T_d` bar in order |
| Any 1m bar missing since the last processed minute | **None for this symbol** | C17 logs `DATA_GAP`, resolves nothing past the gap, and takes no new decisions for this symbol. Never fill or assume |

**The late-run rule.**

1. **Never back-date.** A late run decides at its actual `t_dec` on data up to its actual `t_last`.
2. **Never replay missed looks.** A run gives each live setup one look, however many hours were missed. Missed looks are counted.
3. **Life does not stretch.** A dropped run burns setup life. `expiry` and `A_max` count from `t_k`.
4. **Backtest the same way.** Delays and drops come from the C17 scenarios. See section 9.

Being late does not make a decision invalid, because it uses only data available at its own `t_dec`. It makes it worse, and that cost shows up honestly in `.L` results.

### 3.4 Run health

There is no feed to watch, so health is judged per run and recorded on the run's log entry. This adds to C17's `DATA_GAP` and does not replace it.

| Check | Failure state | Effect |
|---|---|---|
| 1m bars complete since the last processed minute | `DATA_GAP` | C17 rule, for the symbol. For `T1` strategies, also when trades are missing |
| Flow source poll complete, within the job budget of about 3 minutes, with continuity verified by trade id where the source has it | `flow_blind` | Flow features are invalid. A `T0` strategy's base logic continues |
| Runner clock within 5 s of venue server time, where available | `CLOCK_SUSPECT` | No new decisions this run |
| Bars needed for a window and its reference are in the cache or recoverable by poll | `WARMUP` | That feature is invalid |

**A feature is valid at a run only if** its stream is continuous across the window and its reference exists. Otherwise it is invalid, with a reason code, and it is never imputed.

**Missing and quiet are different.** A support failure, such as too little flow, is `NEUTRAL`: the market said nothing. Missing data is `UNKNOWN`: we do not know. See 5.1.

**Reference venue.** The poll source and the price venue may differ (`D-01` is open). Health is tracked for each one. A `.L` price path for `F18-X1` comes from the flow source itself, since a response on one venue must be measured with its own prices. A zone from the price venue may differ slightly from the flow venue's prices, and that basis is reported.

### 3.5 Where flow attaches to the run

C17's order is normative. Flow attaches at these points only:

| C17 step | What flow does |
|---|---|
| 1. Load state, check gap | Also checks flow health |
| 2. Resolve pending fills, walk positions through 1m bars | **Nothing.** Stops and targets resolve first, on the stops active before this run |
| 3. Process each newly closed `T_d` bar in order | **Nothing.** Invalidation, time stops, model updates and setup detection are candle logic |
| 4. Set `t_dec`, `P_dec`, commit decisions | **Here.** Flow exit (section 6) for each position still open, then the entry gate (section 5) for each live setup, oldest first. All decisions commit together |
| 5. Fills | Entries and flow exits fill as C17 states |
| 6. New stops and targets act | Flow `TIGHTEN` acts as C17 states |

Posts go out only after the ledger write, as the charter requires.

**Idempotency.** A decision is keyed by `(setup_id, run_id)` or `(position_id, run_id)`. A retried run finds the key in the ledger and books nothing new.

**A decision exists only once committed.** If the ledger write fails, the run counts as dropped and nothing is booked. The fill rule is deterministic, so a crash after the commit costs nothing: the next run computes the same fill.

## 4. Normalisation

A feature value becomes a percentile against its own recent past, with no outcomes involved.

- **`pct(x)`** is the mid-rank of `x` in a reference sample, clipped to `[1/(2n), 1 - 1/(2n)]`.
- **Reference sample on the cycle.** Values of the same feature and window length, computed from 1m bars at the nominal minute of each hour over the trailing 28 days, which is 672 values. Using the nominal minute makes the reference independent of when runs actually happened, and keeps each window spanning the same number of quarter-hour marks.
- **Recomputed at each run,** from data before that run. Under item 10 of the timing contract, this is a causal indicator with no fitted state, and it needs no freezing. The same applies to `E_W`, which has the same construction as `SRV` in C3. A threshold on either one is a fitted object. Section 8 covers that. This replaces an earlier weekly refresh, so the question of whether a week is a valid block does not arise here.
- **Symmetrised for signed features.** The reference holds both `x` and `-x`. Mirroring a market then exactly mirrors the percentile, and the mirror test in section 12 can be exact. Any genuine asymmetry between long and short is reported by side rather than built in.
- **Aligned value.** `A = s * (2 * pct(x) - 1)` in `(-1, 1)`, with `s = +1` for a long setup and `-1` for a short one.
- **Unsigned features** such as stress and jump scores use their own one-sided percentile.

**State.** `F42-X1`, percentiles and windows need up to 28 days of signed 1m bars. C17 and open question 9 of the strategy index leave it to `data-steward` where such derived state may live. If it is lost, a run rebuilds from the source, and otherwise the feature is in `WARMUP`.

## 5. Entry gate on the cycle

### 5.1 Recipe

A strategy's gate is a **recipe**, frozen before a test block and set in the [matrix](STRATEGY_FEATURE_MATRIX.md). It holds up to 3 features from the live-eligible list, each with an expected sign `e` relative to the setup side, its window, and a mode (`.F` or `.T`). Layers and features are not collapsed into one score.

**Votes.** For each feature at a look:

| Vote | Signed feature | Response state, `D-RR18-X1` | Unsigned feature |
|---|---|---|---|
| `BLOCK` | `e * A <= -tau_b` | The state the recipe names | `pct(x)` beyond its frozen limit, on the side the recipe declares harmful |
| `PASS` | `e * A >= tau_p` | The state the recipe prefers | Inside the limit |
| `NEUTRAL` | Otherwise, or **support failed** | Otherwise, including `NO_FLOW` | Not used |
| `UNKNOWN` | **Data missing or not continuous** | Same | Same |

Response states are defined in [section 2.1 of the matrix](STRATEGY_FEATURE_MATRIX.md#21-notation).

### 5.2 Setup and state

The setup comes from Layer 1 as in [C5](../01_strategies/00_INDEX.md#c5-setup-object-and-gate-window). It has `side`, `level_or_zone`, `invalidation` (`S0`), `targets`, `created_at = t_k` and `expiry`. The state below is kept between runs.

```text
LIVE(looks_used, looks_lost) --> ENTERED | VETOED | EXPIRED    all three terminal
```

The gate cannot resurrect a closed setup, change its side, or change its stop, targets or expiry. A new trade needs a new setup from the strategy.

### 5.3 Evaluation at each look

Strict order. The first rule that applies decides.

| # | Condition | Output | Reason |
|---|---|---|---|
| 1 | `t_dec >= expiry` | `EXPIRE` | `expired`, or `no_run` if the setup never received a look |
| 2 | Any **C17 late-entry check** fails: Age, Path, Chase, Risk, Reward or Thesis, with the values in the strategy's section 14, including any it adds (`S03` Extension, `S08` Roll, `S09` Clock) | `EXPIRE`, event `STALE_SETUP` | The check's own reason, such as `RR_LATE` |
| 3 | Run health shows `CLOCK_SUSPECT` | `.T`: `WAIT` if a look remains. Otherwise `EXPIRE` | `clock_suspect` |
| 4 | Risk check breached, if in the recipe: `JSmax_60` or `F39-X2` beyond its limit | `.T`: `WAIT` if a look remains. Otherwise `VETO` | `stress` |
| 5 | Any valid feature votes `BLOCK` | `VETO` | `flow_block:<feature>` |
| 6 | Any required feature is `UNKNOWN` | `.T`: `WAIT` if a look remains. Otherwise `EXPIRE` | `flow_blind` |
| 7 | `.F`: no `BLOCK`, all valid | `ENTER` | `no_block` |
| 8 | `.T`: all features `PASS` | `ENTER` | `confirmed` |
| 9 | `.T`: otherwise, a look remains | `WAIT` | `no_confirmation` |
| 10 | `.T`: otherwise, no look remains | `EXPIRE` | `no_confirmation` |

A `DATA_GAP` means no decision at all for this symbol this run, under C17, so no rule is evaluated and the look counts as lost.

"A look remains" is defined in 5.4, and `.F` never has one. `V0.L` applies rules 1 and 2 only, followed by `ENTER`, so `V0.L` and `VE.L` lose the same setups to `STALE_SETUP`, and the gate is not credited for them.

**Why a valid `BLOCK` outranks `UNKNOWN`.** Evidence against the setup stands even if another feature is missing. Absence of evidence never allows an `ENTER`.

**Fail closed, by default.** `VE` with missing flow does not trade. Outages may cluster in stress, so entering blind at those moments is the wrong default. Falling back to candle-only behaviour (`FAIL_OPEN`) is a single registered sensitivity, and its trades carry `degraded = true`. **No recipe silently degrades to fewer features.** A reduced recipe would be a separate registered variant.

### 5.4 How `WAIT` works when the next look may be an hour away

C17 states it: `WAIT` means the next run, up to `expiry` and `A_max`. It holds no order and reserves nothing. In every live strategy, `A_max` binds long before `expiry`.

**How many looks actually exist.** A look at run `j` has age about `7 + 60 * j + d` minutes, with `d` the delay after the nominal minute. From the C17 scenarios, by arithmetic on their declared values:

| `A_max` | Strategies | Second look under `C-FAST` | Under `C-LATE` | Under `C-BAD` | Third look under `C-LATE` |
|---|---|---|---|---|---|
| 75 min, 1h | S04, S08, S09 | Always | **About 13%** | About 9% | None |
| 90 min, 1h | S02, S03, S05, S07, S10 | Always | **About 46%** | About 31% | None |
| 150 min, 4h | S03, S04, S05, S10 | Always | About 95% | About 85% | About 46% |

These figures are arithmetic on assumed delays, not measurements. `C-MEASURED` replaces them once 30 days of run logs exist.

- **Budget.** `looks_max` is 2 at 1h and 3 at 4h, always bounded by `A_max` and `expiry`.
- **A look remains** when `looks_used < looks_max` and the next nominal run time, plus the median delay of the active scenario, is within both limits.
- **Last-look rule.** At the last look, `WAIT` is not an available output. `.T` then gives `ENTER` on a full pass, `VETO` on a block, and `EXPIRE` otherwise.
- **A dropped run burns life, not budget.** It counts as a look lost, not a look used.
- **Every look starts over.** Each look recomputes everything, including the C17 checks at the current `P_dec`. A failed check closes the setup, as it would under `V0.L`.
- **Repeated looks are a trial cost.** Multiple looks at a threshold raise the chance of an `ENTER` by luck, and wait statistics are reported: looks used, looks lost, price change while waiting.

**Plain expectation, not a result.** At 1h, a second look often does not exist. When it does, the setup has waited a full bar and the flow window no longer overlaps the moment that created it. So `VE.T.L` is **not a per-strategy test**. It runs once pooled across the `A_max = 90` strategies, to check this expectation, and it is dropped if confirmed. At 4h it is a fairer test, but the samples there are too small to read per strategy.

### 5.5 After `ENTER`

- **Fill** at the open of the first 1m bar with `open_time >= t_dec + latency`. If the fill reference is at or beyond `S0`, the entry is cancelled, as in C17.
- **Size** uses `abs(P_dec - S0)`, as in C17 and rule 4 of [charter section 7](../00_CHARTER.md#7-dynamic-stops-and-targets).
- **`R`** is `abs(fill - S0)`, fixed at the fill. A later entry means a different `R` from `V0.L`. Comparison is made in risk units, so each trade risks the same money.
- **Order style** is taker. The Layer 3 cost check is arithmetic on declared fees and slippage. The book snapshot is logged only.

**Rejected setups.** `VETO`, `EXPIRE`, `STALE_SETUP` and `SKIPPED_OPEN` setups all stay in the record with their counterfactual (`F35-X1`), as the charter requires.

## 6. Flow exit on the cycle

Applies to `VX.L` and `VEX.L`, for positions still open after C17 steps 2 and 3.

**The hard rules, from [charter section 7](../00_CHARTER.md#7-dynamic-stops-and-targets), which no parameter can change:**

1. A stop moves only toward the market. Every flow change passes through the ratchet C8, with the C17 clamp.
2. Flow may never widen a stop, extend a time stop or extend a target.
3. `R` never changes.
4. Flow never adds to a position, and a scale-out is never reversed.
5. Stops and targets are resolved first at each run. Flow acts only on what is still open.

**A stop can only be as good as the run that sets it.** C17 keeps the old stop in force until `t_dec + latency`, and never applies a stop retroactively. A dropped run means a stop that was due to tighten did not. Risk does not rise from the original plan, but the plan was not followed, and this is logged. Stops are modelled as orders resting at the venue between runs, as item 13 of the timing contract states, and reports say so.

**Time stops.** Under rule 7 of charter section 7, a time stop takes effect at the first run after it falls due, and fills at the first price after that run. The overrun is logged and reported. It is a limit of the cycle, not a rule that extends the stop, and flow has no part in it.

### 6.1 Ladder

Severity only rises within a position: `HOLD` < `TIGHTEN` < `SCALE_OUT` < `EXIT`.

**Conflict.** `C = F37-X1` on the recipe's exit feature, over the exit window, in `(-1, 1)`, positive when flow is against the position.

**First flow look.** The first run with at least one full exit window of post-fill data, so that a trade is judged on flow since it opened. On the cycle this is usually the second run after the fill.

| Output | Trigger, from a frozen ladder | Action | Event |
|---|---|---|---|
| `HOLD` | None, or any required input invalid | None | Logged in the decision record |
| `TIGHTEN` | `C >= c1`, at most twice per trade, at least 2 runs apart | Stop candidate halfway between current stop and `P_dec`, through C8 with the C17 clamp | `STOP_UPDATE` |
| `SCALE_OUT` | `C >= c2`, at most once per trade | Close half of what remains, at the C17 fill | `SCALE_OUT` |
| `EXIT` | `C >= c3`, or an adverse `F41-X1` breach | Close the rest, at the C17 fill | `EXIT` |

At each run, the highest triggered action not yet used is taken. Only one action per run.

**Ladder settings** on `(c1, c2, c3)`: `(0.4, 0.6, 0.8)` is the first-pass default. `(0.6, 0.8, 0.9)` and `(0.2, 0.5, 0.8)` are for survivors only. A trigger needs a single look, since waiting for two would mean two hours.

**`TIGHTEN` in detail.** Long: `S_cand = S + 0.5 * (P_dec - S)`, then `S_new = max(S, min(S_cand, C_b - 0.10 * ATR_b, P_dec - 0.10 * ATR_b))`, with `b` the last processed `T_d` bar. Short is the mirror. If this would break the strategy's floor, or if it leaves the stop unchanged, the action is logged as `tighten_blocked` and not counted. `effective_from` is `t_dec + latency`.

**Between 4h closes.** C17 says those runs compute no model updates, and also says a gate is evaluated at runs. I read flow as acting at any run, including between 4h closes, using the last processed `T_d` bar. Section 15 asks for this reading to be confirmed.

**Missing data.** Invalid flow means `HOLD` with reason `flow_blind`. A flow outage is not information about the market. So it never forces an exit, and the position continues under its dynamic model exactly as `V0.L` would.

**When flow exit is not tested.** `flow_reachable_share` is the share of a strategy's `V0.L` trades still open at their first flow look (check D11). If it is below 50%, `VX.L` is recorded as not testable for that strategy. It is not run, and it costs no trial.

## 7. Failure and fallback on the cycle

| Situation | New entries, `VE.L` | New entries, `V0.L` | Open positions | Record |
|---|---|---|---|---|
| Run late | Normal, at actual time | Normal, at actual time | Normal, at actual time | `lateness` logged and reported |
| Run dropped, next run on time | Look lost. C17 checks at the next run | Same | Old stop governs the gap. Touches resolved at the next run with `event_time` and `detection_time`. Updates delayed | Looks lost |
| Actions outage over many hours | As above, and setups go stale | As above | As above. `OUTAGE` event per the data center document | `OUTAGE` in the ledger |
| Flow source failing, 1m bars fine | `flow_blind`, per 5.3 | Normal | `HOLD`, `flow_blind`. Stops resolved from 1m bars | Health state logged |
| Partial flow poll within budget | Invalid features, as above | Normal | `HOLD`, `flow_blind` | Health state logged |
| 1m bars missing | `DATA_GAP`, no decisions for the symbol | Same | Nothing resolved past the gap, per C17 | `DATA_GAP` |
| Gap longer than the source's history | Windows crossing it invalid until clear | Normal once bars return | Per C2 and the data center document, the next available bar is processed. A gap through the stop exits at that open as `STOP_GAP`, flagged with `DATA_GAP` | Permanent gap noted |
| Clock suspect | No decisions | No decisions | `HOLD` | `CLOCK_SUSPECT` |
| Actions cache lost | `WARMUP` until rebuilt, `flow_blind` | Depends on candle availability | `HOLD`, `flow_blind` | Rebuilt by catch-up per the data center document |
| Ledger write fails | Run void, counted as dropped | Run void | Unchanged | Next run reports the void |
| Schedule disabled, GitHub restricts jobs | Everything stops | Everything stops | Unmanaged | Watchdog may also be silent, as the data center document notes |

**Never fill or repair silently.** A correction is a new ledger event. A flagged fill stays flagged.

## 8. Fitting and freezing

This applies to both kinds, on their own clocks. Under item 10 of the timing contract, a rolling percentile needs no freezing, while a threshold on one is a fitted object, frozen before its block.

**First pass: nothing is fitted to outcomes.** Sample sizes cannot support it, as [section 3.3 of the matrix](STRATEGY_FEATURE_MATRIX.md#33-fixed-thresholds-in-the-first-pass) shows. Each feature uses one declared constant:

| Item | First-pass value | Kind |
|---|---|---|
| `tau_b` | 0.6, the worst 20%. Exception: S06 row 1, stated in the matrix | Declared constant |
| Response cuts | Rolling median and 25th percentile of `RR` | Causal indicators |
| Exit ladder | `(0.4, 0.6, 0.8)` | Declared constant |
| `v_min`, `F39-X2` scaling, risk limits (`F39-X2` at its 95th percentile, `JSmax_60` at its 99.5th) | Set from the feature's own training distribution, with no outcomes | Fitted, frozen before the block |

**Grid, for class-level tests and survivors only.**

1. **Pre-register** the recipe, sign, windows, grid, venue and mode in the trial registry, before the test block.
2. **Compute outcomes.** Simulate every setup in the training fold under `V0` on the same clock. For `.L`, use `C-LATE`, averaged over at least 5 seeds, since C17 names it for selection.
3. **Grid.**

   | Mode | Grid | Settings |
   |---|---|---|
   | `.F` | `tau_b` in {0.8, 0.6, 0.4}, which is the worst 10%, 20% or 30% | 3 |
   | `.T` | The same `tau_b`, and `tau_p` in {0, 0.4} | 6 |
   | Exit | The three ladder settings of 6.1 | 3 |

4. **Objective.** `D`, the mean net `R` of kept setups minus blocked setups. A random veto has `D` near 0 in expectation. Per-setup gain is reported beside it, and is `p * (1 - p) * D` for kept share `p`. For exits, the paired `D_x`.
5. **Select.** Standard error by UTC-week block bootstrap, 500 resamples. Keep settings whose `D` exceeds one standard error above 0. Among those within one standard error of the best, take the least restrictive. Requires at least 30% of setups kept and at least 30 rejected.
6. **No setting qualifies? `PASS_THROUGH`.** The gate does nothing for that fold, and that is recorded. A feature is never forced into use.
7. **Freeze.** Parameters, code version and training cutoff go into one versioned artifact. It does not change during the block. A new live version starts a new, visibly labelled segment of the paper record, per the charter.

**Fold plan (a proposal, to be confirmed once `V0` results exist).**

| Tier | First training span | Test blocks | Locked final block |
|---|---|---|---|
| `T1` | First 18 months of the chosen source | Calendar quarters, expanding training | The last 12 months |
| `T2`, `.R` | First 12 months | Calendar quarters | The last 12 months |

The locked block is untouched until a final verdict. On Binance data it lies entirely after the RPI change, so a feature that depended on the earlier regime will show it there.

**Purge and embargo.** A training setup is removed if its label interval reaches the test block. Embargo is the longest hold or expiry in the strategy.

**Long and short share one threshold.** Aligned values make this natural, and it improves support. BTC and ETH have their own references, and thresholds are pooled per strategy. Results are reported by side and by symbol.

**Trial budget.** [Section 7 of the matrix](STRATEGY_FEATURE_MATRIX.md#7-trial-count) has the count. Delay scenarios, seeds and cost multiples are reports, not trials, as the strategy index states. Selecting a seed is forbidden.

## 9. Backtest parity for live-eligible variants

A `.L` backtest must measure what the live record measures. C17 sets out most of this under "Backtest reproduction": the same run function on a dataset truncated at `t_dec`, a declared allowance, `T_d` bars built from 1m bars, run times from a seeded scenario, a replay of actual run times at gate G8, and `IDEAL` minus `CYCLE` as the cost of the cycle. **Those rules apply as written.** Flow adds the items below. **If any item cannot be met, the result is `.R`, whatever it is called.**

| # | Requirement |
|---|---|
| P1 | **Same inputs.** Only what a run can see, from the poll source or its archive, reconciled per check D10. No `T2` |
| P2 | **Same scenarios.** `C-LATE` is the headline and selection scenario. `C-FAST` is the upper bound. `C-BAD` is the stress report. `C-MEASURED` replaces `C-LATE` as a new, visibly labelled configuration once 30 days of run logs exist. At least 5 seeds per random scenario, with the spread |
| P3 | **Same reference.** Percentiles and `E_W` at each run are built as in section 4 |
| P4 | **Same attachment.** Flow attaches to the run as in 3.5 |

**Replay.** C17 requires the live period to be replayed with actual run times, and the trade list must match the ledger. Decisions and vetoes are checked in the same way. Every mismatch goes into the paper-versus-simulation report for gate G8, with its cause: data difference, timing or bug.

## 10. Research-only variants

**These cannot reach a live position on this setup.** They exist to study what the cycle removes, to cover timeframes under 1 hour, and to study the book. S01 and S06 exist only here, apart from their control run through `C-LATE`.

**Clock.** `IDEAL`, under C5 to C7. The first look is at `t_k`. Later looks on `.T` are every `dg` until `expiry`, each checked against the C5 guard. Fills follow C6. Archives have no receive time, so a record's availability is `exchange_ts + A`, with `A` declared per stream: 300 ms by default, stressed at 1 s and 5 s. It cannot be measured on this setup.

| Timeframe | Entry window, primary | Entry window, sensitivity | Exit window | `dg` |
|---|---|---|---|---|
| 5m | 5 min | 1 min | 1 min | 60 s |
| 15m | 15 min | 5 min | 5 min | 60 s |
| 30m | 30 min | 10 min | 10 min | 60 s |
| 1h | 60 min | 15 min | 15 min | 60 s |
| 4h | 240 min | 60 min | 60 min | 300 s |

**State machines.** The entry gate of section 5 and the flow exit of section 6 apply as written, with these differences: C5 replaces the C17 checks, each tick is a look, the exit requires two consecutive ticks, `looks_max` is bounded only by `expiry`, and the reference is sampled every minute over 28 days. Instead of run health, an archive gap invalidates any window crossing it.

**Inputs.** All live-eligible features at finer windows, `F26-X1` as an event, and `T2` features.

**Band depth inputs**, for `F02-X1` and `F16-X1`, use a 1 s grid. `F16-X2` and `F02-X2` use the 30 s `bookDepth` grid. Book state at a tick uses the latest state available by the tick. **A conflated bucket is never treated as individual events.**

## 11. Evaluation requirements

For all flow variants. **Outcomes and rejection rules are in [section 3 of the matrix](STRATEGY_FEATURE_MATRIX.md#3-rejection-rules).**

**Pairing.** Every gate is compared on identical setups, on the same clock, with its own baseline. A veto is judged by what it rejected.

**Placebos.** All are required. Random veto is needed because it looks good whenever costs exceed gross, as [the triage](FEATURE_TRIAGE.md#55-how-do-taker-fees-compare-with-the-effect-being-sought) shows.

| Placebo | How | What beating it shows |
|---|---|---|
| Random veto | Same rate, stratified by `hour_of_week`. `D` is near 0 in expectation | Selection beats trading less |
| **C15 placebo** | The same recipe on the strategy's [C15](../01_strategies/00_INDEX.md#c15-placebo-control) setups: random levels at the same distance distribution, or for S03 and S10, random entry times | Flow says something about this mechanism, and is not just a general market filter |
| Shifted flow | Same feature taken from the same hour one week earlier | Beats a seasonal pattern |
| Reversed sign | Flip the expected sign | Should do worse. If not, the feature is not doing what the recipe claims |

**Control for re-measuring the bar.** Report each flow feature's effect after controlling for the return over the same window, `F42-X1` and hour of week. If it vanishes, the gate is re-reading the candle.

**Blind set.** Results are shown for setups where flow was valid, compared with `V0` on those **same** setups, plus separately the blind set. Otherwise a gate can look better by simply avoiding periods when data went missing, a selection effect that has nothing to do with flow.

**Decomposition.** Filter value, from `VE.F`. Timing value, from `VE.T` minus `VE.F`. Exit value, from `VX`. Cycle costs from section 2. Reports always include `flow_reachable_share`, looks lost, `lateness`, `STALE_SETUP` by reason and time stop overruns.

**Costs.** At 1x, 2x and 3x, per charter section 6. Slippage measured at the run minute, in line with the note in C6 on measuring it where fills happen.

**Statistical power.** To detect a difference `D` in mean net `R` between kept and rejected setups, keeping share `p`, at two-sided 5% and 80% power, with outcome standard deviation `sigma`:

```text
n >= (1.96 + 0.84)^2 * sigma^2 * (1/p + 1/(1 - p)) / D^2
```

With `p = 0.7` and an **assumed** `sigma = 1.2 R`:

| `D` | Setups needed |
|---|---|
| 0.3 R | About 600 |
| 0.2 R | About 1,350 |
| 0.1 R | About 5,400 |

These are before any multiple-testing correction, and overlapping setups count for less. **[Section 4 of the matrix](STRATEGY_FEATURE_MATRIX.md#4-can-each-gate-question-be-answered) applies this to each strategy, and predicts `INCONCLUSIVE` for most.** Pooling across strategies can answer a class-level question, "does aligned flow help setups of this kind?", but not whether it helps this one. An inconclusive result must be reported as inconclusive and not as a failure or a pass.

A dense, setup-free first screen of each feature against forward returns at the same horizons has far more power for the question "is there any information?". Those runs are logged as trials too.

## 12. Invariants and required tests

The first group must hold for every run, in code. The second group follows the [leak auditor's list](../../.claude/agents/leak-auditor.md).

**Invariants.**

| # | Invariant |
|---|---|
| I1 | A stop never moves away from the market |
| I2 | Flow never extends a time stop and never extends a target |
| I3 | `R` never changes after the fill |
| I4 | Flow never increases a position |
| I5 | Severity within a position never falls, and a scale-out is never reversed |
| I6 | **All-flow-invalid equivalence.** With all flow invalid, `VX.L` must produce exactly the trades of `V0.L`. With `FAIL_OPEN`, `VE.F.L` must also. With fail closed, it must produce no trades |
| I7 | **Pass-through equivalence.** With `PASS_THROUGH`, `VE.F.L` must equal `V0.L` exactly |
| I8 | No `.L` code path can read `T2`, and no `.L` result can be written without its parity manifest |
| I9 | One decision per `(setup_id, run_id)` or `(position_id, run_id)`, however many times a run is repeated |
| I10 | Every flow input has an exchange time at or before `t_last`, and was received by `t_dec` |

**Tests.**

| Test | What it proves |
|---|---|
| Truncation | Removing data after `t_last` changes nothing at or before that run |
| Future perturbation | Randomising data after `t_last` changes no decision at or before that run |
| Shift | Delaying inputs by one run. A sharp collapse is suspicious |
| Mirror | Swapping side and sign mirrors every decision exactly |
| Late run | A late run gives the same decision whether simulated or replayed, and it never fills before `t_dec + latency` |
| Dropped run | Stops are resolved across the gap, looks are lost, `expiry` and `A_max` do not stretch, no retroactive decision appears |
| Crash | A crash at each run step leaves a valid ledger, and a retry books nothing twice |
| Sign per venue | Check D2 |
| Coverage | A hole in the poll invalidates exactly the windows that cross it |
| Replay | Section 9 |

Hand fixtures for each state transition are required before a verdict on gate G2.

## 13. Worked example

**Invented numbers, for checking the rules only. This is not a market result.** `VEX.L`, 1h long on BTC, in the style of S02. Recipe: `F24-X1`, `e = +1`, `tau_b = 0.6`, window 60 min. Ladder `(0.4, 0.6, 0.8)`. `latency = 500 ms`, slippage 1 bp. Setup: `C_k = 60,000`, `S0 = 59,400`, `T1 = 61,000`, `ATR_k = 300`, `t_k = 10:00`. Checks: `A_max` 90 min, chase `0.75 * ATR_k = 225`, risk up to `2.5 * ATR_k = 750`, `RR_late = 1.0`.

**Run at about 10:07.** Started at 10:09:20, so `detection_time = 10:09:20` and `lateness = 9 min 20 s`. `t_dec = 10:09:50`. Allowing 10 s, the last completed 1m bar closes at `t_last = 10:09:00`, with `P_dec = 60,040`.

- C17 checks: age under 10 min passes. Path passes. Chase 40 passes. Risk 640 passes. Reward `61,000 - 60,040 = 960` is at least 640, so it passes.
- Window `(09:09, 10:09]`. `B_60 = -0.08`. Percentile 0.46, so `A = -0.08`. `e * A = -0.08`, above `-0.6`.
- `.F` gives `ENTER`, reason `no_block`. Size uses `abs(P_dec - S0) = 640`.
- Fill: first 1m bar with `open_time >= 10:09:50.5` opens at 10:10:00, at 60,060. With slippage, fill is 60,066. `R = 666`.

**The run at about 11:07 is dropped.** No flow look, no stop update, and the 11:00 bar goes unprocessed.

**Run at about 12:07.** `detection_time = 12:08:00`. `t_dec = 12:08:30`, `t_last = 12:08:00`.

- C17 step 2: 1m bars from 10:10 to 12:08 show no touch.
- C17 step 3: bars closing 11:00 and 12:00 are processed in order. Suppose the model's ratchet leaves the stop at 59,400.
- First flow look: post-fill data covers more than 60 minutes. Window `(11:08, 12:08]`. Percentile of `B_60` is 0.15, so `A = -0.70`, and `C = +0.70`.
- `C` is above `c2 = 0.6` and below `c3 = 0.8`, so the highest unused action is `SCALE_OUT`. Half closes at the open of the 12:09 bar.

**Run at about 13:07.** `detection_time = 13:08:10`.

- C17 step 2: the 1m bar closing 12:41 touched the stop. The rest of the position closes at the stop, with `event_time = 12:41`, `detection_time = 13:08:10`, and `lateness` of 27 min 10 s.
- No flow look occurs, since the position is already closed.

The stop fired at 12:41, and it took until 13:08 to know. The flow reading that might have helped could not arrive any sooner than the next run. That is the cost of the cycle in one example.

## 14. Decision record

Every look and every exit evaluation writes one append-only record to `decisions`, before anything is posted. Time fields follow C17.

| Group | Fields |
|---|---|
| Identity | `decision_id`, `setup_id` or `position_id`, `run_id`, strategy, symbol, side, variant name, kind |
| Clock | `knowable_time`, `event_time`, `detection_time`, `effective_from`, `lateness`, `t_dec`, `P_dec`, `t_last`, run delay after the nominal minute, `looks_used`, `looks_lost` |
| Output | Decision, reason code, C14 event, and for exits: old and new stop, quantity |
| Inputs | For each feature: value, window, percentile, vote, valid flag, reason |
| Health | Poll source, price venue, health state per source |
| Snapshot | Bid, ask and fill distance at the run, for the record only |
| Versions | Recipe, threshold artifact, data, code |

No market data goes into git. The values above are small derived statistics. Whether publishing them is allowed under each source's terms is a separate question, already raised in [the data lifecycle document](../05_DATA_LIFECYCLE.md).

## 15. Open items

| Item | Owner | Blocks |
|---|---|---|
| Poll source: passes R1 to R6 from a GitHub runner, including terms. **HTTP 451 from Binance USD-M REST on my tool suggests the research favourite may be unusable live. It must not be routed around.** See [section 5.6 of the triage](FEATURE_TRIAGE.md#56-whose-flow-is-measured-and-does-that-venue-lead-or-follow) | `data-steward`, owner under `D-01` | All `.L` results, and S07 and S08 live |
| Delay and drop distribution, `C-MEASURED` | `data-steward` | Replaces `C-LATE` |
| `pct` and `E_W` recomputed at each run are treated as causal indicators under item 10, with thresholds as the fitted objects. Please confirm | `leak-auditor` | Section 4 |
| The availability rule in 3.1, with a 10 s allowance | `leak-auditor` | Section 3 |
| Flow acting at runs between 4h closes. C17 says those runs compute no model updates, and also that a gate is evaluated at runs | `strategy-architect`, `leak-auditor` | Section 6 |
| Whether an hourly paper engine and a public channel sit within GitHub's terms, which say Actions may be used to "develop and test" and are limited to activity related to the project. See decision `D-16` | Owner | Live paper |
| Whether the hourly schedule should ever be shortened. GitHub allows down to 5 minutes, but that would raise the burden question above, and the data center document sets hourly. A `.L` run on a shorter cycle would cost one extra trial family and would show what it might buy | Owner, under `D-04` | Nothing now |
