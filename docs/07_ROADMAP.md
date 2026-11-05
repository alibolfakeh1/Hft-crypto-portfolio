# Roadmap

Maintained by `project-manager`. A phase starts only when the gate it depends on has a verdict. Phases have no dates
yet, because the reference venue (`D-01`) and the live source (`D-24`) are still open. The research source is chosen (`D-29`).

| Phase | Deliverable | Lead | Reviewers | Gate | Status |
|---|---|---|---|---|---|
| P0 Foundation | Charter, team, strategy and feature documents, leak audit of documents, output, data and app specifications | `project-manager` | `leak-auditor` | G0 | In progress |
| P1 Data center | Zones and catalog on GitHub, historical ingest with catch-up, bars from trades, retention job, hourly live poll, health report, first end-to-end report. See `docs/08_DATA_CENTER.md` | `data-steward`, `developer` | `python-reviewer`, `leak-auditor` | G1 | In progress |
| P2 Engine | Event-driven simulator, timing contract enforced in code, costs, funding, dynamic stops, trial registry, leak test suite | `developer` | `python-reviewer`, `leak-auditor` | G6 (engine) | In progress, on generated data |
| P3 Baselines | All strategies in `V0S` and `V0`, on `T0` and `T1` data | `developer` | `strategy-architect`, `leak-auditor` | G3 | In progress, on generated data. No market data yet |
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
- **One rule for reading dates** (`docs/decisions/FOLD_PLAN_2026-11-05.md`, section 3). The first training span is open. Test
  blocks stay unread until the owner opens them in writing, in calendar order. The locked block is read once, at the final
  verdict, for every candidate frozen that day. This binds every phase here, including P3, P4 and P7: no report, chart or app
  reads a date that is not open.

## Current status

Updated 2026-11-05. The research source is chosen: Binance Vision perpetual data, non-commercial (`D-29`). The fold plan is
frozen (`D-30`), with review by `leak-auditor` pending. `developer` is building the engine and `V0` on generated data, and the
data-layer fixes are in progress. No strategy has seen market data, and every source in the configuration stays disabled until
those fixes pass.

- **Fold plan:** `docs/decisions/FOLD_PLAN_2026-11-05.md`. `T_start` 2020-01-01, `UNVERIFIED` until `data-steward` measures it.
  First training span to 2023-12-31. Seven test quarters from 2024-01-01 to 2025-09-30. Locked block 2025-10-01 to 2026-09-30,
  which is read on 10 listed days (`D-27`). Section 7 of the plan says which conditions are met before the first run.
- **First run:** `V0` on official 1-minute candles and funding, on the first span only. That covers eight strategies. S07 and S08
  need trades, so they wait for bars from trades. No log entry yet records the candle stage as an exception to `D-12`.
- **Data center reviews:** both rechecks returned `FAIL`, on narrower grounds than before. `docs/reviews/code/data_center_recheck_2026-11-04.md`
  rests on F-18, the watchdog. `docs/reviews/leak/data_center_recheck_2026-11-04.md`, still marked work in progress, finds four
  new leaks in the fixes. It says building the engine and `V0` on generated data is not held back, and its section 10 lists what must
  be fixed before any strategy sees market data.
- **Strategy documents:** leak audit `PASS WITH CONDITIONS`, after fixes and three rechecks. Their text conditions are closed.
- **Feature documents:** leak re-audit `PASS WITH CONDITIONS` on the source-independent parts only, in
  `docs/reviews/leak/features_recheck_2026-11-05.md`. The source-tied parts are `PENDING SOURCE`. All four documents still name the
  earlier source, so `feature-integrator` corrects them to `D-29`, and `leak-auditor` rechecks them before any flow code on this source.
- **Sources:** Binance Vision is the research history (`D-29`, replacing `D-17`). Kraken is out (`D-23`), and the project pays for no
  data and asks no venue for a licence (`D-25`), so the routes in `D-20` and `D-22` no longer apply. `configs/pipeline.toml` still marks
  Binance prohibited, which `developer` changes as part of the fixes. **The live source stays open (`D-24`),** so the hourly poll has no
  source and there are no live paper positions.
- **Network contact:** test runs reached a Bybit host by mistake and received no data. See `D-19`.
- **Results:** no S01 to S10 strategy has run on market data, so there are no strategy results of any kind. A private demonstration
  of a different, fixed rule ran on 12 days (`D-27`). It is not a result.

### Conditions from the data center leak audit

From section 5 of `docs/reviews/leak/data_center_2026-11-04.md`, with verdicts from its recheck, which is still marked work in
progress. Items named "stage 1" and "stage 2" are in section 10 of that recheck.

| Falls due | Condition | Owner | State |
|---|---|---|---|
| Before market data, by the recheck. Building on generated data is not held back | DC-01, DC-02, DC-04, DC-05, DC-07, DC-11 and DC-12 in code | `developer` | DC-05 and DC-12 `PASS`. DC-01, DC-02, DC-04 and DC-07 `PASS WITH CONDITIONS`. DC-11 is still being run in the recheck. Fixes in progress |
| Same | DC-03: the charter and C2 text, with its configuration keys and columns | `project-manager`, `strategy-architect`, `developer` | `FAIL` on the `IDEAL` columns. Text and keys are met, and every value is a placeholder. The new charter and C2 sentences for official candles are stage 1 and not done |
| Before a source is enabled | DC-06 and DC-08 | `developer` | DC-06 `PASS`. DC-08 `PASS WITH CONDITIONS` |
| Before bars from trades, stage 2 | The row-shape check of ruling 2 on the source, and `continuity` declared | `data-steward` | Pending. The source is known (`D-29`), and neither applies to the first run on candles |
| Before bars from trades, stage 2 | The window `boundary_window_ms` frozen under C12 | `project-manager` | **Pending, and no value is chosen.** The value in `configs/pipeline.toml` is a placeholder and does not meet this condition. It must come from the first span, which is outside any test block, and a later change is a counted trial. The recheck withdraws the earlier remark that only a recheck would remain: it stays a declared constant |
| Before the first `V0` run | C-5 extended to the declared values | `project-manager` | Pending. No frozen commit is recorded. At the candle stage it covers `candle_allowance`, the research span and the fold plan. The tolerances and `max_quiet_s` join at stage 2 |
| Before gate G1 on the chosen source | DC-09 and DC-13 | `developer`, `data-steward` | Both `PASS WITH CONDITIONS`. The DC-13 allowances are placeholders, `UNVERIFIED` until measured |
| Before gate G1 on the chosen source | Empty minutes with and without proof reported per source | `developer`, `data-steward` | Required by the charter, section 5. The report is not built |
| Before the first `CYCLE` run | DC-10, and minute 7 or 23 settled | `developer`, `strategy-architect` | DC-10 `PASS WITH CONDITIONS`. Minute 7 is settled in C17, and the recheck finds it in the code |
| With the next pass over these files | DC-14 and DC-15 | `developer` | DC-14 `PASS`. DC-15 `PASS WITH CONDITIONS` |

The recheck requires a re-audit of items 1 to 4 before the candle run, and of items 8 to 12 before bars from trades, with its probes rerun.
