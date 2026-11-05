# Roadmap

Maintained by `project-manager`. A phase starts only when the gate it depends on has a verdict. There are no
dates yet, because the reference venue (`D-01`) and the research and live sources (`D-24`) are still open.

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

Updated 2026-11-04. The first data center build is finished and has not passed review. Its code review and its leak
audit both returned `FAIL`. The fixes are in commit `dafe3f2`, and `python-reviewer` and `leak-auditor` are rechecking
them now. No verdict has changed, so both stand at `FAIL` until the recheck reports. All data sources are disabled until
one is approved.

- **Data center reviews:** `docs/reviews/code/data_center_2026-11-04.md` and `docs/reviews/leak/data_center_2026-11-04.md`.
  The developer's answer to each finding is in `docs/reviews/code/data_center_fixes_2026-11-04.md`. That file is the
  writer's account, and no reviewer has confirmed it yet.
- **Strategy documents:** leak audit `PASS WITH CONDITIONS`, after fixes and three rechecks. Their text conditions are
  closed. Coding the run logic now waits for the first two rows of the table below, because the data center audit holds
  back strategy, feature and `decide` code until they are met. Conditions C-3, C-4, C-5, C-7 and C-10 in
  `docs/reviews/leak/strategies_recheck_2026-11-04.md` fall due before the first run on market data.
- **Feature documents:** leak audit `FAIL`. They must be corrected to match the final hourly cycle and the approved source,
  and audited again, before any gate or flow exit is coded. With the data path chosen (`D-22`), `feature-integrator` is correcting them now.
- **Research data path:** the owner has ruled Kraken out (`D-23`), so the source is open again (`D-24`). No source is
  approved and all sources stay disabled. The hourly poll has no source. A pipeline test on Tardis free first-day-of-month
  files can run once the data center recheck passes (`D-22`). The feature documents assumed Kraken, so their
  source-specific parts wait for `D-24`.
- **Network contact:** test runs reached a Bybit host by mistake and received no data. See `D-19`.
- **Results:** no strategy has been coded or tested, so there are no strategy results of any kind.

### Conditions from the data center leak audit

From section 5 of `docs/reviews/leak/data_center_2026-11-04.md`. "Answered" means the developer reports a change in
`dafe3f2`. It does not mean the condition is met, which only the recheck can say.

| Falls due | Condition | Owner | State |
|---|---|---|---|
| Before any strategy, feature or `decide` code | DC-01, DC-02, DC-04, DC-05, DC-07, DC-11 and DC-12 in code | `developer` | Answered, recheck running. Parts of DC-01, DC-04 and DC-07 wait for `decide` and `settle`, which do not exist yet |
| Before any strategy, feature or `decide` code | DC-03: the charter and C2 text, with its configuration keys and columns | `project-manager`, `strategy-architect`, `developer` | Charter sentence added in section 3 item 1. C2 sentence with `strategy-architect`. Keys and columns answered, recheck running |
| Before a source is enabled | DC-06 and DC-08 | `developer` | Answered, recheck running |
| Before a source is enabled | The row-shape check of ruling 2 on that source, and `continuity` declared | `data-steward` | Pending, because no source is approved yet (`D-22`). The configuration holds first values for `stamp_kind`, `fill_span_allowance_ms` and `continuity`. All are `UNVERIFIED` on a real feed |
| Before the first `V0` run | The window `boundary_window_ms` frozen under C12 | `project-manager` | **Pending. It cannot be frozen until a source is approved (`D-20`), and no value is chosen.** The value now in `configs/pipeline.toml` is a placeholder and does not meet this condition. Under ruling 7 the window comes from data outside any test block, so the fold plan (C-7) comes first, and a later change is a counted trial. Ruling 7 also asks that it share one source-level constant with the DC-03 span allowance, and says only a recheck remains once the DC-08 fix stands. `leak-auditor` rules on that |
| Before the first `V0` run | C-5 extended to the tolerances | `project-manager` | Pending. No frozen commit is recorded. It comes after the window is frozen, and it also covers the configured start dates and `poll.start_date`, under ruling 7. `max_quiet_s`, which the fixes added after the audit, is treated as one of the tolerances. C-7's fold plan also records which dates were looked at during the build |
| Before gate G1 on the chosen source | DC-09 and DC-13 | `developer`, `data-steward` | Answered, recheck running. The DC-13 allowances are placeholders, `UNVERIFIED` until measured on the approved source |
| Before gate G1 on the chosen source | Empty minutes with and without proof reported per source | `developer`, `data-steward` | Required by the charter, section 5. The report is not built. Its column, `empty_proof`, is answered, recheck running |
| Before the first `CYCLE` run | DC-10, and minute 7 or 23 settled | `developer`, `strategy-architect` | DC-10 answered, recheck running, with its G8 replay part still to come. The hourly workflow now runs at minute 7, the value C17 freezes |
| With the next pass over these files | DC-14 and DC-15 | `developer` | Answered, recheck running |

The audit requires a re-audit of the changes for DC-01 to DC-08, DC-11 and DC-12, with its probes rerun.
