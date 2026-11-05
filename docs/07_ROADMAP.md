# Roadmap

Maintained by `project-manager`. A phase starts only when the gate it depends on has a verdict. Phases have no dates
yet, because the reference venue (`D-01`) and the live source (`D-24`) are still open. The research source is chosen (`D-29`).

| Phase | Deliverable | Lead | Reviewers | Gate | Status |
|---|---|---|---|---|---|
| P0 Foundation | Charter, team, strategy and feature documents, leak audit of documents, output, data and app specifications | `project-manager` | `leak-auditor` | G0 | In progress |
| P1 Data center | Zones and catalog on GitHub, historical ingest with catch-up, bars from trades, retention job, hourly live poll, health report, first end-to-end report. See `docs/08_DATA_CENTER.md` | `data-steward`, `developer` | `python-reviewer`, `leak-auditor` | G1 | In progress |
| P2 Engine | Event-driven simulator, timing contract enforced in code, costs, funding, dynamic stops, trial registry, leak test suite | `developer` | `python-reviewer`, `leak-auditor` | G6 (engine) | In progress, on generated data. Not reviewed |
| P3 Baselines | All strategies in `V0S` and `V0`, on `T0` and `T1` data | `developer` | `strategy-architect`, `leak-auditor` | G3 | In progress, on generated data. No market data yet |
| P4 Portfolio report | Full tear sheets and portfolio report from real baseline results | `developer`, `ui-designer` | `python-reviewer` | G6 | Started, on generated data. Not reviewed |
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
  reads a date that is not open. The last opened date is 2023-12-31 (`D-34`).
- **Two stages (`D-31`).** Stage 1 is official 1-minute candles and funding, first span only, and shows eight strategies. Stage 2 is bars from
  trades, and all ten. A quarter read on candles is `EXPLORATORY` for all ten strategies and every flow line, so test quarters stay
  closed through stage 1.

## Current status

Updated 2026-11-05, after `aac99e2`. The research source is chosen (`D-29`) and research goes in two stages (`D-31`). The fold plan is
frozen and reviewed, and **it is not clean on one point: about 137 MB of `D-18` cannot be dated (`D-38`).** `developer` is building the engine and `V0` on generated data,
and the data-layer fixes are in progress. No S01 to S10 strategy has seen market data, and the source stays off until item 0 below is in.

| Reviewed | Verdict | What it rests on |
|---|---|---|
| Data center code at `dafe3f2`, leak recheck | `FAIL`, narrower than the first | Four new leaks from the fixes. Archive bars on a source with official candles fail on DR-04, and the `IDEAL` read path on DR-01 to DR-03. Other paths `PASS WITH CONDITIONS` |
| Data center code at `dafe3f2`, code recheck | `FAIL` | F-18, the watchdog. All eight High findings closed. Fixes are in the working tree and not yet rechecked |
| Fold plan at `1e634fc` | `PASS WITH CONDITIONS` | The dates and rules hold. Amended by `D-34` to meet the conditions, and `leak-auditor` has not read the amendment |
| Two-stage plan, `D-31` | `PASS WITH CONDITIONS` | Reading only the first span is required, not merely convenient |
| `D-27` as "not a trial" | Does not stand | Replaced by `D-32`, a counted run that came before C-3 and C-5 |
| Feature documents | `PASS WITH CONDITIONS`, source-independent parts only | Source-tied parts stay `PENDING SOURCE`, and most of that falls due before stage 2 and does not hold back stage 1 |
| Strategy documents | `PASS WITH CONDITIONS` | Text conditions closed. Changes since the demonstration are listed for audit in section 10 of the fold plan |

Reports: `docs/reviews/leak/data_center_recheck_2026-11-04.md`, `docs/reviews/code/data_center_recheck_2026-11-04.md`,
`docs/reviews/leak/features_recheck_2026-11-05.md`, `docs/reviews/leak/strategies_recheck_2026-11-04.md`.

- **Fold plan:** `docs/decisions/FOLD_PLAN_2026-11-05.md`. `T_start` 2020-01-01, which holds on file coverage, with the quarter check not yet run.
  First training span to 2023-12-31. Seven test quarters from 2024-01-01 to 2025-09-30. Locked block 2025-10-01 to 2026-09-30, read on 10 listed days (`D-27`).
  It stays the locked block, and a locked read now rests on what can be shown to predate the demonstration.
- **First run:** `V0` on official 1-minute candles and funding, on the first span only. S07 and S08 need trades, so **the owner's first view shows eight strategies, not ten.**
- **Sources:** Binance Vision is the research history (`D-29`, replacing `D-17`). Kraken is out (`D-23`), and the project pays for no
  data and asks no venue for a licence (`D-25`), so the routes in `D-20` and `D-22` no longer apply. `configs/pipeline.toml` still marks
  Binance prohibited in the committed code. **The live source stays open (`D-24`),** so the hourly poll has no source and there are no live paper positions.
- **Read record:** section 4 of the fold plan. The demonstration's 12 days are logged, 10 of them in the locked block. The 30 `D-18` dates `data-steward` could name all fall after it. A
  `bookDepth` file name in 2024-06, inside test block 2024-Q2, counts as read until shown otherwise. **About 137 MB of `D-18` cannot be dated. The developer who ran it does not recall the dates or
  whether a report was produced, and size does not rule out closed dates.** So stage 1 goes on, and opening any date after 2023-12-31 is `BLOCKED` until the owner decides with this stated (`D-38`).
- **Network contact:** test runs reached a Bybit host by mistake and received no data. See `D-19`.
- **Results:** no S01 to S10 strategy has run on market data, so there are no strategy results of any kind. The demonstration (`D-32`) is a counted run and not a result.

### What happens next

| # | What | Who |
|---|---|---|
| 1 | Item 0 of recheck section 10: nothing can read an unopened date. The scheduled report stays off until then. **Merging this branch to `main` arms the schedule, so no merge until this is in** | `developer`, `data-steward` |
| 2 | The quarter check on candle files for closed dates, once `leak-auditor` approves the job. The condition 2 test on the declared sample days, once its inequality is ruled on | `data-steward`, `leak-auditor` |
| 3 | Stage 1 code: candle converter, reader, date guard, read-path holes, benchmark span, the false "frozen" wording. The declared values in section 8 of the plan go in its configuration | `developer` |
| 4 | Text: `GATE_SPEC.md` 8.2, 8.3 and 8.6, matrix 3.1 and pooled `N`, on this source | `feature-integrator` |
| 5 | Re-audit of items 0 to 4, the plan's amendment, the ruling in `D-38`, and the diff in section 10 of the plan | `leak-auditor` |
| 6 | The C-5 commit, with host push times | `project-manager` |
| 7 | The first run, on the first span. Then the owner's private view | `developer`, `project-manager` |
| 8 | Stage 2: bars from trades, all ten strategies. Needs a reviewed rule for curated trades against the 4 GB cache | `developer`, `data-steward` |

**Waiting for the owner:** `D-36`, the statement that completes `D-32`. `D-37`, market data in the Actions cache, which does not block a local first run. `D-28`, the portfolio's limits, best answered before
the first view, so they are not set after sight of it too.

### Conditions from the data center leak audit

From section 5 of `docs/reviews/leak/data_center_2026-11-04.md`, with verdicts from its recheck. Items named "stage 1" and "stage 2" are in section 10 of that recheck. The conditions before
the first run are in section 7 of the fold plan.

| Falls due | Condition | Owner | State |
|---|---|---|---|
| Before market data, by the recheck. Building on generated data is not held back | DC-01, DC-02, DC-04, DC-05, DC-07, DC-11 and DC-12 in code | `developer` | DC-05 and DC-12 `PASS`. DC-01, DC-02, DC-04, DC-07 and DC-11 `PASS WITH CONDITIONS`. Fixes in progress |
| Same | DC-03: the charter and C2 text, with its configuration keys and columns | `project-manager`, `strategy-architect`, `developer` | `FAIL` on the `IDEAL` columns, which is stage 2. Text and keys are met, and every value is a placeholder. The sentences for official candles are in, the charter's here and C2's at `389fcee` |
| Before a source is enabled | DC-06 and DC-08 | `developer` | DC-06 `PASS`. DC-08 `PASS WITH CONDITIONS` |
| Before bars from trades, stage 2 | The row-shape check of ruling 2 on the source, and `continuity` declared | `data-steward` | Pending. Neither applies to stage 1. Its estimator is declared in section 8 of the fold plan |
| Before bars from trades, stage 2 | The window `boundary_window_ms` frozen under C12 | `project-manager` | **Pending, and no value is chosen.** Its estimator is declared in section 8 of the fold plan, as one constant with the allowance. The value is computed on the first span. The value in `configs/pipeline.toml` is a placeholder and does not meet this condition |
| Before the first `V0` run | C-5 extended to the declared values | `project-manager` | Pending. The per-file anchor is set in section 10 of the fold plan. The diff audit, host push times and the commit remain |
| Before gate G1 on the chosen source | DC-09 and DC-13 | `developer`, `data-steward` | Both `PASS WITH CONDITIONS`. The DC-13 allowances are placeholders, `UNVERIFIED` until measured |
| Before gate G1 on the chosen source | Empty minutes with and without proof reported per source | `developer`, `data-steward` | Required by the charter, section 5. The report is not built |
| Before the first `CYCLE` run | DC-10, and minute 7 or 23 settled | `developer`, `strategy-architect` | DC-10 `PASS WITH CONDITIONS`. Minute 7 is settled in C17, and the recheck finds it in the code |
| With the next pass over these files | DC-14 and DC-15 | `developer` | DC-14 `PASS`. DC-15 `PASS WITH CONDITIONS` |

The recheck requires a re-audit of items 0 to 4 before the candle run, and of items 8 to 12 before bars from trades, with its probes rerun.
