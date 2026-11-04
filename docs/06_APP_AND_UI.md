# App and UI specification

Two front ends show the same results: a desktop app and a Telegram bot that posts to a channel. Neither
computes performance, and neither can send a real order. `app-builder` owns the build and `ui-designer` owns
the design. Metric definitions are in [the portfolio outputs document](04_PORTFOLIO_OUTPUTS.md).

## 1. Architecture

```text
live data -> paper engine -> append-only ledger ─┐
backtests -> report engine -> results store ─────┴-> read-only local API -> desktop app
                                                                         -> Telegram bot -> channel
```

Proposed stack, pending decision `D-05`: a Python read-only API, and a desktop app that wraps a local web UI
in a native window, packaged as one Windows application. The same chart components can then serve the
desktop app, the HTML tear sheet and the Telegram images, so there is one visual language to maintain.

## 2. Desktop views

| View | Answers |
|---|---|
| **Portfolio** | How is everything doing? League table, combined equity and drawdown, exposure |
| **Live positions** | What is open right now, and where are its stop and target? |
| **Strategy** | Full tear sheet for one strategy, with long and short split |
| **Variants** | Did flow help? `V0S`, `V0`, `VE`, `VX` and `VEX` side by side |
| **Trade explorer** | Why did this trade happen? Chart with entry, exit, stop and target path, and the gate state |
| **Portfolio construction** | Correlation, risk contribution, allocation methods |
| **Robustness** | Walk-forward, deflated Sharpe, overfitting probability, Monte Carlo cone, trial count |
| **Data health** | Feed status, gaps, disk usage, days until full, recent deletions |

Each view has designed empty, loading, stale and error states. A blank chart must never look like a flat
result.

## 3. Telegram

### Channel posts

| Event | Content |
|---|---|
| Position opened | Strategy, symbol, side, entry, initial stop, target, `R` size, gate state, time |
| Stop or target moved | Old and new values and the reason. Throttled, so that small trailing moves are grouped |
| Scale-out | Portion closed, result so far |
| Position closed | Exit reason, result in `R` and percent, holding time |
| Daily summary | Portfolio equity, drawdown, open positions, best and worst strategy today |
| Weekly and monthly | Tear-sheet images |

Example format. All values are placeholders, not results:

```text
PAPER | S04 Supply and demand | v1 | gate G6
OPENED LONG BTCUSDT
Entry 00000.0 | Stop 00000.0 | Target 00000.0
Risk 1R = 0.00% of paper equity
2026-01-01 00:00:00 UTC
Paper trading on live data. No real orders. Not investment advice.
```

### Channel rules

1. Post only from the ledger, after the event has been written there.
2. Post every event, losing trades included. Posts are not edited or deleted to improve the record.
3. Every performance post carries `PAPER` or `SIMULATED` and a not-investment-advice notice.
4. The first post to any channel needs the owner's approval. Test on a private channel first.
5. Backtest results and paper results are never presented as one track record.
6. If the system loses data or stops, the channel is told, because silence would misrepresent the record.

The owner should check whether publishing positions has legal requirements where they and the audience are.
See decision `D-03`.

### Private bot commands

Restricted to an allow-list of owner user ids: `/status`, `/positions`, `/portfolio`, `/strategy <id>`,
`/health` and `/pause_posts`. There is no command that places an order.

## 4. Security

- Tokens come only from environment variables or the operating system's secure store. See `.env.example`.
- The local API binds to localhost and is read-only.
- Logs and screenshots must never include tokens.
- The repository is public, so assume everything committed will be read.

## 5. Design requirements

Details are in the `ui-designer` agent definition. In short: dark and light themes, Persian and English
support including right-to-left layout, tabular figures, no reliance on red and green alone, and the
`SIMULATED` or `PAPER` label visible in every view of performance, including screenshots and images.
