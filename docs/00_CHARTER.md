# Project charter

Status: draft for owner review. Date: 2026-11-04.

## 1. Purpose

Find out, with honest evidence, whether order-flow and order-imbalance information improves
advanced candle strategies on BTC and ETH, both in deciding whether and when to enter and in
deciding when to exit. Show all results as a professional portfolio report, and run the strategies
forward on live data with their positions visible and published.

**In scope:** BTC and ETH, long and short, decision timeframes from 5 minutes to 4 hours, holding
periods from minutes to days, research simulation, paper trading on live data, and publishing live
paper positions to a Telegram channel.

**Out of scope for now:** real orders, market making, latency competition, other assets.

**Public project.** The repository is public. Nothing published here is investment advice.

**Runs on GitHub itself.** There is no server (decision `D-15`). Backtests can use any timeframe in scope. Live
paper positions run on an hourly cycle at 1-hour or 4-hour timeframes. See
[what this gives up](08_DATA_CENTER.md#5-running-on-github-itself).

## 2. Decision stack

Each layer has one job. Layers are not collapsed into one score.

| Layer | Owner | Input | Output |
|---|---|---|---|
| 1. Setup | Candle strategy | Closed bars | `Setup`: side, level or zone, invalidation price, target, expiry |
| 2. Entry gate | Flow features | Flow data while the setup is live | `ENTER`, `WAIT`, `VETO` or `EXPIRE` |
| 3. Order | Execution model | Entry decision, book state, costs | Simulated order and fills |
| 4. Exit | Dynamic stop and target model, plus flow features | Position, bars, flow | `HOLD`, `TIGHTEN`, `SCALE_OUT` or `EXIT` |
| 5. Portfolio | Portfolio engine | All strategy streams | Sizing, risk limits, combined equity |

Hard rules for layer 4 are in [section 7](#7-dynamic-stops-and-targets).

### Variants

Every strategy runs in the variants below, so the value of each decision can be measured separately.

| Variant | Entry | Exit |
|---|---|---|
| `V0S` | Candle only | Fixed stop, target and maximum hold, set at entry and never moved. Control only |
| `V0` | Candle only | Dynamic stop and target model |
| `VE` | Flow gate | Dynamic stop and target model |
| `VX` | Candle only | Dynamic model plus flow |
| `VEX` | Flow gate | Dynamic model plus flow |

`V0` is the baseline. `V0S` exists only to show whether dynamic management adds anything.

Two refinements come from [the gate specification](02_features/GATE_SPEC.md):

- **`VE` has two forms.** `VE.F` only filters, with `ENTER` or `VETO` at the first look. `VE.T` also allows `WAIT`.
  They are separate because filtering survives the hourly cycle and timing mostly does not.
- **Each variant has two kinds.** `.L` is live-eligible: it uses only inputs available on the hourly cycle, and runs
  on the same cycle in backtests. `.R` is research-only and may use data a live run would not have. The difference
  between them is a simulated estimate of what running only on GitHub costs.

Vetoed, expired and skipped setups stay in the record with their counterfactual result, so the gate
can be judged on what it rejected as well as on what it accepted.

## 3. Timing contract

Every value has a **knowable time**, the earliest moment a live system could have had it.

1. A bar covers `(open_time, close_time]` and is knowable at `close_time`. A higher-timeframe bar
   is knowable only when that higher-timeframe bar closes.
2. A swing pivot with `R` right-side bars is knowable at the close of the `R`-th right bar. Its
   knowable time is the confirmation time, never the time of the extreme.
3. A daily or weekly pivot is computed only from completed UTC periods.
4. A zone is knowable when its departure is complete. Its strength score uses only data up to that
   time. Its touch count updates only as touches occur.
5. Volume profile and VWAP values use only trades already completed at the decision time.
6. A flow feature uses the causal window `(t - W, t]` on a declared clock, with data availability
   based on receive time when it is known and a declared latency allowance when it is not.
7. A decision at time `t` fills no earlier than `t + latency`, at a price available then. A decision
   made on a bar close cannot fill at that bar's close without a declared latency and slippage.
8. Stops and targets inside a bar are resolved conservatively: if both could have been hit in the
   same bar, assume the stop was hit first, unless finer data settles the order.
9. Funding is charged at its actual settlement times.
10. Anything estimated across a sample and then applied forward (scalers, thresholds, seasonal profiles) is
    fitted only on past data and frozen before the block it is applied to. A fixed-window statistic recomputed at
    each step from data at or before that step (`ATR`, a rolling percentile rank) is a causal indicator with no
    fitted state, and needs no freezing. A threshold on such an indicator is still a fitted object.
11. Parameters are selected on training folds only. Test blocks are never reused for selection.
12. A stop or target update computed at time `t` applies from `t + latency`. An update computed on a
    bar close applies from the next bar, never to the bar that produced it.
13. On the hourly live cycle, a decision is made at the time of the run, however much earlier its setup
    became knowable. A paper entry fills at the first price available after that run. A stop or target touched
    between runs is resolved from 1-minute bars at the next run and recorded with both its event time and its
    detection time. Paper stops and targets are modelled as orders resting on the exchange between runs, with
    stop slippage charged. This is fair only if a real system would hold such orders, and reports say so. Backtests
    of live-eligible variants reproduce this cycle.

## 4. Data tiers

Mid-frequency decisions do not need every feature to be event-level, so features are tiered by the
data they require. A strategy's testable history is limited by the highest tier it uses.

| Tier | Data | Use | History |
|---|---|---|---|
| `T0` | Candles | Setups | Years |
| `T1` | Signed trades | Trade-flow features, volume profile, VWAP | Years, to be confirmed per venue |
| `T2` | Conflated L2 book | Imbalance, depth and spread features | Daily archive, depth of history to be confirmed |
| `T3` | Order-level L3 events | Order lifecycle and queue features | Forward only, from our own recording. Not available while running on GitHub only |

### Checks made on 2026-11-04

| Source | Result |
|---|---|
| Bybit archive, `quote-saver.bycsi.com/orderbook/linear/BTCUSDT/<date>_BTCUSDT_ob200.data.zip` | Opened and replayed for one day. See [the data center document](08_DATA_CENTER.md#4-rules-learned-from-the-first-real-data) |
| Binance archive, `data.binance.vision` | Candles, `aggTrades`, `bookDepth` and funding opened for one day or month. Checksum verified on one file |
| Bitstamp `live_orders` plus REST snapshot | Book rebuilt from events for 60 s with zero differences within 2% of mid. No sequence numbers. Trades carry both order ids |
| Coinbase Advanced `level2`, `market_trades` | Public. Batches of about 50 ms. No sequence breaks in 1,164 messages |
| Kraken v2 `book`, `trade` | Public, close to one change per message, level-based |
| Tardis | Without a key, only the first day of each month is free |

A one-minute test is not a reliability result. These entries record what was seen, not a guarantee.

### Open issue: reference venue

The venue whose prices define the live paper positions has not been chosen. It must be one the owner
may lawfully use under that venue's terms. See decision `D-01` in the
[decision log](decisions/DECISION_LOG.md). Research uses public archives in the meantime, and any
result from one venue must be retested on the chosen venue's data.

## 5. Gates

Gates follow the knowledge base (`RESEARCH_GATES.md`). Verdicts are `PASS`, `PASS WITH CONDITIONS`,
`FAIL` or `BLOCKED`. Passing a gate is evidence for continuing research, not proof of profitability
and not permission to trade.

| Gate | This project's evidence |
|---|---|
| G0 Charter | This document approved by the owner |
| G1 Data | Deterministic candles and replay, gap reports, reconciliation against the source |
| G2 Features | Unit tests, mirror tests, causality tests, missing-data report |
| G3 Setups and labels | Exact timeline, repaint test, overlap policy, frozen definitions |
| G4 Gate models | Walk-forward results, comparison with `V0`, trial registry |
| G5 Fills | Separate fill and slippage assumptions, tested for passive orders only if they are used |
| G6 Simulation | Partial fills, fees, funding, latency, position and risk limits |
| G7 Robustness | Cost, delay, parameter, regime and data-gap stress, deflated Sharpe, overfitting probability |
| G8 Paper | Reproducible versions, monitoring, append-only ledger, paper versus simulation mismatch report |

## 6. Costs

Fees, slippage, funding and latency are explicit configuration values with no hidden defaults. Each
strategy is reported at 1x, 2x and 3x cost, with its break-even cost. Mid-frequency edges are often
small relative to taker fees, so cost is a first-class result.

## 7. Dynamic stops and targets

Stops and targets are dynamic. Their design belongs to the strategy expert (`strategy-architect`), and
each strategy document defines its own model. A flat rule used for every strategy is not acceptable,
because a pivot rejection and a breakout fail in different ways.

Each model states:

| Element | What must be defined |
|---|---|
| Initial stop | Placed from market structure and scaled by current volatility, for example beyond the zone by a multiple of ATR |
| Stop updates | Method and schedule: structure-based, ATR or chandelier trail, move to break-even, time decay |
| Target | From the next structural level or a volatility multiple, and when it may be recomputed |
| Scale-out | Whether part of the position exits at intermediate levels |
| Regime scaling | How distances change with volatility or liquidity state |
| Floors | The minimum stop distance that clears noise and costs |
| Time stop | When a trade that has gone nowhere is closed |

Hard rules, for every strategy:

1. **Stops only tighten.** After entry, a stop may move only in the direction that reduces risk. It is
   never moved away from the market, by any rule or feature.
2. **Targets may move either way,** but only by the documented rule. Moving a target never moves the
   stop backward.
3. **Flow can only reduce risk.** Flow features may exit early, scale out or tighten a stop. They may
   never widen a stop, extend a time stop or extend a target.
4. **Position size comes from the initial stop.** The fill is not yet known when size is sent, so size uses the
   distance from the decision price to the initial stop. `R` is the distance from the actual fill to the initial
   stop, and it never changes afterwards, so trade results stay comparable in `R` multiples.
5. **Every update is a logged event,** with old and new values, the reason and the knowable time.
6. **Inside a bar, the stop is applied first.** See items 8 and 12 of the
   [timing contract](#3-timing-contract).
7. **Time stops on the hourly cycle.** A time stop takes effect at the first run after it falls due, and fills at
   the first price after that run. The overrun is logged and reported. This is a limit of the cycle, not a rule
   that extends the stop.

## 8. Live positions and publication

Strategies that reach gate G6 run forward on live market data as paper positions, on an hourly cycle of
scheduled GitHub jobs. "Live" here means current to within the last run, not tick by tick, and every view shows
the age of its data. No real orders are sent. See rule 3 in [CLAUDE.md](../CLAUDE.md).

- **Live view.** For each open position: strategy, symbol, side, entry time and price, size, `R`, current
  stop and target, distance to each, unrealised P&L in money and in `R`, age, and the stop and target
  history. The portfolio view adds net and gross exposure and open risk.
- **Channel posts.** Position opened, stop or target changed, scale-out and position closed, plus a daily
  portfolio summary. Each post carries the `PAPER` label, the strategy's current gate, the time of the event and
  the time the run detected it.
- **Append-only ledger.** Every position event goes to a hash-chained ledger before it is posted. A
  losing trade is never hidden. A correction is a new event. Changing a strategy's version starts a new,
  visibly labelled segment of its record, so a backtest can never be mixed into the forward record.
- **Backtest and forward results stay apart.** Equity curves mark the point where simulation ends and the
  live paper record begins.
- **Owner approval.** The first post to any channel needs the owner's approval. Testing uses a private
  test channel first. See decision `D-03` in the [decision log](decisions/DECISION_LOG.md).
