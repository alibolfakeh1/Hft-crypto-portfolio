# Roadmap

Maintained by `project-manager`. A phase starts only when the gate it depends on has a verdict. Phases have no dates
yet, because the reference venue (`D-01`) and the live source (`D-24`) are still open. The research source is chosen (`D-29`).

| Phase | Deliverable | Lead | Reviewers | Gate | Status |
|---|---|---|---|---|---|
| P0 Foundation | Charter, team, strategy and feature documents, leak audit of documents, output, data and app specifications | `project-manager` | `leak-auditor` | G0 | In progress |
| P1 Data center | Zones and catalog on GitHub, historical ingest with catch-up, bars from trades, retention job, hourly live poll, health report, first end-to-end report. See `docs/08_DATA_CENTER.md` | `data-steward`, `developer` | `python-reviewer`, `leak-auditor` | G1 | In progress. Checks after the fetch built at `be20ee7`, `PASS WITH CONDITIONS`, with a fix batch in progress. The coverage check is built and not run |
| P2 Engine | Event-driven simulator, timing contract enforced in code, costs, funding, dynamic stops, trial registry, leak test suite | `developer` | `python-reviewer`, `leak-auditor` | G6 (engine) | In progress. On generated data, reviewed at `1c2dc23` and `be20ee7` with conditions. A fix batch is in progress |
| P3 Baselines | All strategies in `V0S` and `V0`, on `T0` and `T1` data | `developer` | `strategy-architect`, `leak-auditor` | G3 | In progress. `V0`, `V0S` and C15 placebos built on generated data and reviewed, with conditions. No market data yet |
| P4 Portfolio report | Full tear sheets and portfolio report from real baseline results | `developer`, `ui-designer` | `python-reviewer` | G6 | In progress. Portfolio view built on generated data and reviewed. No real results |
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

Updated 2026-11-05, after `2959bb9`. The research source is chosen (`D-29`) and research goes in two stages (`D-31`). The fold plan is frozen and reviewed, and
**it is not clean on one point: about 137 MB of `D-18` cannot be dated (`D-38`, `D-41`).** No S01 to S10 strategy has seen market data, the source stays off, and
**no gate is passed.**

**Built on generated data and reviewed, with conditions.** At `be20ee7`:

- the engine in `IDEAL-1M`, with the timing contract in code, the date guard, the read days, and `D-38`'s sentence on test and locked labels;
- the dated tick of `D-43`, `UNVERIFIED` until the file checks pass;
- `V0` of S01 to S06, S09 and S10 on official candles, and of S07 and S08 for bars from trades, which give no result on candles;
- `V0S` as its own stream, never in the portfolio figure, and C15 placebos with 200 hashed draws;
- the portfolio view on `D-35`'s line rule and `D-39`'s limits, and the trial registry, without whose declared costs a market run refuses to start;
- the candle path of the data layer, the checks after the fetch (F1 to F5, K1 to K5), and the coverage check, built and not run.

**The developer is fixing RC2-01 to RC2-03 and RB-01 to RB-03 now.** That batch needs its own code recheck and leak re-audit before the first run.

| Reviewed | Verdict | Commit | What it rests on |
|---|---|---|---|
| Candle path of the data layer, leak re-audit | `PASS WITH CONDITIONS` | `cf1880f` | Recheck section 17. Its open points, items 4 to 6 of the plan's section 7, are fixed |
| Data layer, code recheck | `PASS WITH CONDITIONS` | `cf1880f` | Section 14 of `docs/reviews/code/data_center_recheck_2026-11-04.md`. F-18 is closed |
| Engine, strategies and portfolio view, code review | `FAIL` | `cf1880f` | Fixed in `1c2dc23` |
| Engine, leak audit | `FAIL`, narrowly | `cf1880f` | Fixed in `1c2dc23` |
| Engine, placebos and `V0S`, code recheck | No single verdict: on correctness the first run may start, with conditions. C15 `PASS WITH CONDITIONS`, `V0S` `PASS` | `1c2dc23` | R-01 and R-02 fixed at `be20ee7`. R-03 is ruled in the plan's section 6 |
| Engine, leak re-audit | No single verdict: the first run may start once its items are done. No leak found | `1c2dc23` | Its test of funding to net is in at `be20ee7` |
| Coverage check's run plan | Either option may run once its items are done | `6a7dfc9` | Recheck section 17.6. Where it runs is the owner's choice |
| Fixes, dated tick and checks after the fetch, code recheck | `PASS WITH CONDITIONS` | `be20ee7` | RC2-01 to RC2-03, in the current batch. The dated tick `PASS` |
| The same, leak re-audit | No single verdict: the first run may start once its items are done. C16 and C7, the dated tick in code, and the checks after the fetch `PASS WITH CONDITIONS`, the rest `PASS` | `be20ee7` | RB-01 to RB-03, in the current batch. For `be20ee7` only |
| Fold plan and its amendment | `PASS WITH CONDITIONS` | `1e634fc`, `cd4daea` | Recheck sections 13 and 18.3. No date moved |
| Two-stage plan, `D-31` | `PASS WITH CONDITIONS` | | Reading only the first span is required, not merely convenient |
| `D-32` to `D-41`, apart from `D-37` | Stand, with notes | | Recheck section 18.4. `D-37` waits for the owner |
| Rulings after sight of the demonstration, through `ecc5e49` | Accepted, with notes. `ecc5e49`'s with conditions | | Recheck 18.1 and 18.2, and the re-audits at `1c2dc23` and `be20ee7`. All are rows in the plan's section 10 and go through the C-5 diff audit |
| Feature documents | `PASS WITH CONDITIONS`, source-independent parts only | `3f0db56` | Unchanged since. Their adoption of the read rule is still due |

Reports: `docs/reviews/leak/data_center_recheck_2026-11-04.md`, `docs/reviews/leak/engine_2026-11-05.md`, `docs/reviews/code/engine_review_2026-11-05.md`,
`docs/reviews/code/engine_recheck_2026-11-05.md`, `docs/reviews/code/fixes_recheck_2026-11-05.md`, `docs/reviews/code/data_center_recheck_2026-11-04.md`,
`docs/reviews/data/venue_facts_2026-11-05.md`, `docs/reviews/data/coverage_check_plan_2026-11-05.md`, `docs/reviews/leak/features_recheck_2026-11-05.md`,
`docs/reviews/leak/strategies_recheck_2026-11-04.md`.

- **Fold plan:** `docs/decisions/FOLD_PLAN_2026-11-05.md`. `T_start` 2020-01-01, which holds on file coverage, with the quarter check not yet run.
  First training span to 2023-12-31. Seven test quarters from 2024-01-01 to 2025-09-30. Locked block 2025-10-01 to 2026-09-30, read on 10 listed days (`D-27`).
  It stays the locked block, and a locked read rests on what can be shown to predate the demonstration. A run for a test block reads from `T_start` to that block's end,
  so its placebo has the span before it (section 6, a rule for later).
- **First run:** `V0` on official 1-minute candles and funding, on the first span only. S07 and S08 need trades, so **the owner's first view shows eight strategies, not ten.**
- **Before the first run:** the 18 items in section 7 of the fold plan. **Done:** items 1 to 7 fixed and reviewed, apart from freezing C15 and `V0S` in the C-5 commit, and
  item 10, the re-audit. **Wait on the developer's current batch:** items 11 to 16, then the first-span fetch, item 17. **Waits on the owner:** the coverage check, item 8.
  Then the C-5 commit, item 9, and the full suite at the commit that runs, item 18.
- **Tick table (`D-43`):** BTCUSDT 0.01 before 2022-02-15 03:30 UTC and 0.1 from then, ETHUSDT 0.01, dated only from the venue's published times. `UNVERIFIED` until K1 to K4
  pass on the fetched first-span files.
- **Sources:** Binance Vision is the research history (`D-29`, replacing `D-17`). Kraken is out (`D-23`), and the project pays for no
  data and asks no venue for a licence (`D-25`), so the routes in `D-20` and `D-22` no longer apply. **The live source stays open (`D-24`),** so the hourly
  poll has no source and there are no live paper positions.
- **Read record:** section 4 of the fold plan. The demonstration's 12 days are logged, 10 of them in the locked block. The 30 `D-18` dates `data-steward` could name all fall after it.
  The `bookDepth` file in test block 2024-Q2 is BTCUSDT on 2024-06-01, excluded on both symbols when that quarter opens. **About 137 MB of `D-18` cannot be dated, and size does not rule
  out closed dates.** So stage 1 goes on, and opening any date after 2023-12-31 is `BLOCKED` until the owner decides with this stated (`D-38`).
- **Network contact:** test runs reached a Bybit host by mistake and received no data. See `D-19`.
- **Results:** no S01 to S10 strategy has run on market data, so there are no strategy results of any kind. The demonstration (`D-32`) is a counted run and not a result.

### What happens next

| # | What | Who |
|---|---|---|
| 1 | The current batch: RC2-01 to RC2-03 and RB-01 to RB-03 | `developer` |
| 2 | Its code recheck and leak re-audit | `python-reviewer`, `leak-auditor` |
| 3 | Where the coverage check runs: Option A, a one-off Actions job on a throwaway branch, or Option B, a local run | **Owner** |
| 4 | The coverage check, once, both lists, logged. Before it: the approval recorded under `D-34` with the option and base commit, `leak-auditor`'s read of any diff beyond `be20ee7`, and for Option B the review of rule `check-root-after-run` | `data-steward`, `project-manager`, `leak-auditor`, `python-reviewer` for B |
| 5 | The first-span fetch, with F1 to F5 and K1 to K5 read before the run | `data-steward` |
| 6 | The read rule adopted in `GATE_SPEC.md` 8.2, 8.3 and 8.6 and matrix 3.1, and pooled `N` (H5) | `feature-integrator` |
| 7 | The C-5 checklist, section 11 of the plan: the files, the commit, host push times read from GitHub, the published diff and its audit, costs in the registry, the record | `project-manager`, the coordinator, `leak-auditor`, `developer` |
| 8 | The full suite at the commit that runs, with its output recorded | The coordinator |
| 9 | The first run, on the first span. Then the owner's private view | `developer`, `project-manager` |
| 10 | Stage 2: bars from trades, all ten strategies. Needs a reviewed rule for curated trades against the 4 GB cache | `developer`, `data-steward` |

**Merging this branch to `main` arms the schedule.** Before any merge, the source and the scheduled report must be confirmed off.

**Waiting for the owner.**

- **Where the coverage check runs.** Both options are allowed from the leak side (recheck 17.6). **Recommendation: Option A,** as `data-steward` also recommends. The
  closed-date files never sit on a machine where agents work, and it needs no new deletion rule. What it costs: one push of a throwaway branch, a public log of counts and
  fixed words only, and whether GitHub's runner regions are within Binance's terms is `UNVERIFIED`, which the owner confirms. Option B keeps everything local but needs
  rule `check-root-after-run` reviewed, and its clean-up does not survive a hard kill, so a search after the run must confirm no root is left.
- `D-37`, market data in the Actions cache, which does not block a local first run. Neither coverage option saves to the cache.

### Conditions from the data center leak audit

From section 5 of `docs/reviews/leak/data_center_2026-11-04.md`, with verdicts from its recheck at `dafe3f2`. Items named "stage 1" and "stage 2" are in section 10 of that recheck. The candle
path was re-audited at `cf1880f` (recheck section 17), and for the first run the list in section 7 of the fold plan takes the place of this table.

| Falls due | Condition | Owner | State |
|---|---|---|---|
| Before market data, by the recheck. Building on generated data is not held back | DC-01, DC-02, DC-04, DC-05, DC-07, DC-11 and DC-12 in code | `developer` | DC-05 and DC-12 `PASS`. DC-01, DC-02, DC-04, DC-07 and DC-11 `PASS WITH CONDITIONS`. Fixes in progress |
| Same | DC-03: the charter and C2 text, with its configuration keys and columns | `project-manager`, `strategy-architect`, `developer` | `FAIL` on the `IDEAL` columns, which is stage 2. Text and keys are met, and every value is a placeholder. The sentences for official candles are in, the charter's here and C2's at `389fcee` |
| Before a source is enabled | DC-06 and DC-08 | `developer` | DC-06 `PASS`. DC-08 `PASS WITH CONDITIONS` |
| Before bars from trades, stage 2 | The row-shape check of ruling 2 on the source, and `continuity` declared | `data-steward` | Pending. Neither applies to stage 1. Its estimator is declared in section 8 of the fold plan |
| Before bars from trades, stage 2 | The window `boundary_window_ms` frozen under C12 | `project-manager` | **Pending, and no value is chosen.** Its estimator is declared in section 8 of the fold plan, as one constant with the allowance. The value is computed on the first span. The value in `configs/pipeline.toml` is a placeholder and does not meet this condition |
| Before the first `V0` run | C-5 extended to the declared values | `project-manager` | Pending. The checklist is section 11 of the fold plan, and every part is open |
| Before gate G1 on the chosen source | DC-09 and DC-13 | `developer`, `data-steward` | Both `PASS WITH CONDITIONS`. The DC-13 allowances are placeholders, `UNVERIFIED` until measured |
| Before gate G1 on the chosen source | Empty minutes with and without proof reported per source | `developer`, `data-steward` | Required by the charter, section 5. The report is not built |
| Before the first `CYCLE` run | DC-10, and minute 7 or 23 settled | `developer`, `strategy-architect` | DC-10 `PASS WITH CONDITIONS`. Minute 7 is settled in C17, and the recheck finds it in the code |
| With the next pass over these files | DC-14 and DC-15 | `developer` | DC-14 `PASS`. DC-15 `PASS WITH CONDITIONS` |

The recheck requires a re-audit of items 0 to 4 before the candle run, and of items 8 to 12 before bars from trades, with its probes rerun.
