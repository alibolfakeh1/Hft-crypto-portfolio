# HFT Crypto Portfolio: project rules

Research project for mid-frequency strategies on BTC and ETH. Candle strategies propose trades.
Order-flow and order-imbalance features decide whether and when to enter and when to exit.
Results are shown as a portfolio, and live paper positions are published to a Telegram channel.
Read [docs/00_CHARTER.md](docs/00_CHARTER.md) before any work.

**This repository is public.** Everything committed can be read by anyone, forever.

## Non-negotiable rules

1. **Documents first.** No strategy or feature is coded until its document exists and has a
   leak-audit verdict of `PASS` or `PASS WITH CONDITIONS`.
2. **The timing contract is law.** Every value has a time at which it became knowable. See
   [the timing contract](docs/00_CHARTER.md#3-timing-contract).
3. **No real orders.** Nothing in this repository sends real orders. "Live position" means a paper
   position run on live market data. Real orders need a written decision by the owner in the
   decision log.
4. **No profitability claims.** Backtest results are labelled `SIMULATED` and forward results are
   labelled `PAPER`, in every report, chart and Telegram post. Passing a gate is evidence for
   continuing research, nothing more. Nothing published here is investment advice.
5. **Baseline always runs.** A flow-gated result is reported only next to its candle-only baseline.
6. **Every trial is counted.** Parameter runs are logged in the trial registry, because the
   deflated Sharpe ratio depends on the number of trials.
7. **Keep the public repository clean.** No secrets, market data, licensed data, local paths,
   personal details or location details in git. Tokens live in environment variables. Data lives
   outside the repository under `DATA_ROOT`.
8. **Never invent evidence.** Cite only sources you actually read. Unverified statements are
   marked `UNVERIFIED`.
9. **Stops and targets are dynamic and belong to the strategy expert.** After entry, a stop may only
   move in the direction that reduces risk. See
   [the charter](docs/00_CHARTER.md#7-dynamic-stops-and-targets).
10. **The live record is append-only.** Paper positions and published posts are never edited, hidden
    or removed, including the losing ones. Corrections are new records.

## The team

Agent definitions are in `.claude/agents/`.

| Agent | Owns |
|---|---|
| `project-manager` | Roadmap, gates, decision log, status reports |
| `strategy-architect` | Candle strategy documents in `docs/01_strategies/`, including each dynamic stop and target model |
| `feature-integrator` | Feature usage documents in `docs/02_features/` |
| `leak-auditor` | Future-leak verdicts on documents, code and results |
| `python-reviewer` | Correctness verdicts on Python code |
| `developer` | All production code and tests |
| `data-steward` | Market data storage, integrity, retention and deletion |
| `app-builder` | Telegram bot and channel, desktop app |
| `ui-designer` | Design system, screens and report layout |

## Workflow

```text
strategy-architect / feature-integrator  write the document
leak-auditor                             audits the document
developer                                implements it on a branch
python-reviewer + leak-auditor           review the code
project-manager                          records the gate verdict and merges
```

Writers do not approve their own work.

## Conventions

- Documents and code comments are in English. Reports to the owner are in Persian.
- Gate verdicts are exactly `PASS`, `PASS WITH CONDITIONS`, `FAIL` or `BLOCKED`.
- All timestamps are UTC. Annualisation uses 365 days, because crypto trades every day.
- The feature knowledge base is external and read-only, at the path in the `HFT_KB_PATH`
  environment variable. It is not copied into this repository. Its numeric feature IDs are
  canonical: never renumber or redefine them. A crypto adaptation gets a derived ID such as `F16-X1`.
- Work happens on branches and reaches `main` through a pull request.
