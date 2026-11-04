# Roadmap

Maintained by `project-manager`. A phase starts only when the gate it depends on has a verdict. There are no
dates yet, because the server and the reference venue are still open decisions.

| Phase | Deliverable | Lead | Reviewers | Gate | Status |
|---|---|---|---|---|---|
| P0 Foundation | Charter, team, strategy and feature documents, leak audit of documents, output, data and app specifications | `project-manager` | `leak-auditor` | G0 | In progress |
| P1 Data center | Zones and catalog on GitHub, historical ingest with catch-up, bars from trades, retention job, hourly live poll, health report, first end-to-end report. See `docs/08_DATA_CENTER.md` | `data-steward`, `developer` | `python-reviewer`, `leak-auditor` | G1 | In progress |
| P2 Engine | Event-driven simulator, timing contract enforced in code, costs, funding, dynamic stops, trial registry, leak test suite | `developer` | `python-reviewer`, `leak-auditor` | G6 (engine) | Not started |
| P3 Baselines | All strategies in `V0S` and `V0`, on `T0` and `T1` data | `developer` | `strategy-architect`, `leak-auditor` | G3 | Not started |
| P4 Portfolio report | Full tear sheets and portfolio report from real baseline results | `developer`, `ui-designer` | `python-reviewer` | G6 | Not started |
| P5 Flow features | Features from the triage, `T1` first and then `T2` | `feature-integrator`, `developer` | `leak-auditor`, `python-reviewer` | G2 | Not started |
| P6 Gates | `VE`, `VX` and `VEX` with walk-forward evaluation | `feature-integrator`, `developer` | `leak-auditor` | G4, G7 | Not started |
| P7 Apps | Desktop app and Telegram bot, on a private test channel | `app-builder`, `ui-designer` | `python-reviewer` | None | Not started |
| P8 Live paper | Paper engine on the hourly cycle, append-only ledger, live positions, **public channel after owner approval** | `developer`, `app-builder` | `leak-auditor`, `python-reviewer` | G8 | Not started |

## Sequencing notes

- **Everything runs on GitHub** (decision `D-15`). There is no order-level recording, so `T3` features wait.
- **Baselines before flow.** If `V0` cannot survive costs, flow must improve it a lot, and that is worth
  knowing before building gates.
- **Apps can begin with P4 results.** They show real `SIMULATED` output, and screens built earlier use
  labelled synthetic data.
- **Live paper need not wait for every strategy.** A strategy can go live on paper once it has passed G6. Its
  posts show its current gate, so an unvalidated strategy is visibly unvalidated.

## Current status

Updated 2026-11-04. The data center is being built, and all data sources are disabled until one is approved.

- **Strategy documents:** leak audit `PASS WITH CONDITIONS`, after fixes and three rechecks. Their text conditions are
  closed, so the run logic may be coded. Conditions C-3, C-4, C-5, C-7 and C-10 in
  `docs/reviews/leak/strategies_recheck_2026-11-04.md` fall due before the first run on market data.
- **Feature documents:** leak audit `FAIL`. They must be corrected to match the final hourly cycle and the approved source,
  and audited again, before any gate or flow exit is coded.
- **Results:** no strategy has been coded or tested, so there are no strategy results of any kind.
