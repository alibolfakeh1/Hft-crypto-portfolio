# Code review: engine, strategies and portfolio report

Reviewer: `python-reviewer`. Date: 2026-11-05. Code at commit `cf1880f`, branch `pipeline/first-data-run`. It was read and run from a frozen copy of that commit, because the C15 placebo work was changing
`src/hft_crypto/engine/`, `strategies/`, `reports/portfolio.py` and `configs/engine*.toml` in the working tree during this review. That uncommitted work is not reviewed here, and it may already change lines cited below.

Governing documents: `docs/01_strategies/00_INDEX.md`, each S document, `docs/04_PORTFOLIO_OUTPUTS.md`. All data is generated, with invented prices. Nothing touched a network. This report says nothing about whether any strategy works.

## 1. Verdict: `FAIL`

**The money arithmetic is right.** I found no error in how a trade is booked, in the equity curve, or in any total. A long and a short worked by hand agree to the cent, and every figure in a full run recomputes from its trade rows. No future leak showed up.

The verdict rests on something narrower. **Ten items would change the trade list or a net figure of the first candle run.** Under C12 and rule 6, a rule changed after that run is a new document version and a counted trial, and the reading of the first span is counted too. So fixing them afterwards costs more than fixing them before. Section 2 lists them in order. None is large. A recheck of those lines is enough.

| Area | Verdict | Why |
|---|---|---|
| Booking: fills, sizes, fees, slippage, target and stop prices | `PASS` | Section 4 |
| Funding | `FAIL` | E-01, E-02, E-03 |
| Equity, drawdown, Sharpe, CAGR, totals, gross cap | `PASS` | Section 4 |
| Cost lines and labels in the report | `PASS WITH CONDITIONS` | E-11 to E-14 |
| C2 on a missing bar | `FAIL` | E-04 |
| S01 | `PASS` | Every clause mapped. One reading noted in section 6 |
| S02 | `PASS WITH CONDITIONS` | E-10, E-15, E-16 |
| S03 | `FAIL` | E-05, and a reading in section 6 |
| S04 | `FAIL` | E-06, and a reading in section 6 |
| S05 | `FAIL` | E-07, E-06, and a reading in section 6 |
| S06 | `FAIL` | E-08, E-09 |
| S07 | `PASS` on trades. Does not run on candles | No result on the first run, by design. E-17 |
| S08 | `PASS` on trades. Does not run on candles | No result on the first run, by design |
| S09 | `PASS` | Every clause mapped |
| S10 | `FAIL` | E-05 |
| Run command, date range, registry | `PASS WITH CONDITIONS` | E-14 |

## 2. What must be fixed before the first candle run, in order

| # | ID | Why it comes here |
|---|---|---|
| 1 | E-01 | A missing funding month reads as no funding, and nothing says so. It moves every net figure over that span |
| 2 | E-02 | A settlement inside a hole in the rows is skipped |
| 3 | E-03 | A trade taken as stopped at a gap still pays funding for after the stop |
| 4 | E-04 | A hole of a whole bar is invisible to every register |
| 5 | E-05 | S03 and S10: the stall exit fires later than the documents say |
| 6 | E-06 | S04 and S05: a zone can trade on the bar that creates it |
| 7 | E-07 | S05: a flip that should be dead still trades |
| 8 | E-08 | S06: a swing pool swept during its wait is treated as fresh |
| 9 | E-09 | S06: a UTC roll at `n = 1` does not recompute `T2` |
| 10 | E-10 | S02: a weekly level trades once a week, not once per UTC day. Non-default lines only, but they run |

**Then these readings, which need `strategy-architect` before the run and not after:** section 6.

**Then:** E-16 and E-17 can change a trade, rarely, so decide them with those readings. E-11 to E-15 change no trade, only what is printed, and they should still be fixed before the figures are read.

**Still open from the owner and other reviewers, and not code defects:** the tick sizes in `configs/engine.toml` are marked to be read from the venue before the first run. The risk limits are placeholders under `D-28`, and every output prints that. S09 fails closed on one missing hour, so expect lost quarters on real candles, counted in `no_setup_reasons`, and do not read those as a result.

## 3. Findings

### E-01, High. A settlement with no rate is silent

`src/hft_crypto/engine/run.py:173-186`, `src/hft_crypto/engine/simulator.py:692-714`.

`funding = "required"` only refuses a symbol with no rows at all. I gave a long held over six settlements at 10 bp only the first two rates. It paid 20.00 and not 60.00, with empty counters and no event. C17 says "A missing rate is logged as DATA_GAP for funding and is not assumed", and C10 says a rate not yet arrived stays open as a reported liability. Neither exists in the engine, by search and by this run. A failed monthly funding file would leave a month of net figures flattered or hurt, with the header still saying "Funding is charged at actual settlement times".

**Fix:** from the file's own cadence, find every settlement with no rate, per symbol. Count them in the manifest and the header. For a position open across one, log the event and report the amount as unresolved. The strictest form is to refuse the run on a gap, which the first span can afford because `data-steward` records 48 of 48 monthly files.

### E-02, Medium. A settlement inside a hole in the rows is skipped

`src/hft_crypto/engine/simulator.py:697-698`.

The cursor skips every settlement at or before the current row's open. With rows 198 to 201 missing and a settlement at the end of row 199, a long pays 0.00 where 10.00 is owed. The same settlement in a stretch of zero-trade rows that do exist is charged correctly, so the hole is the only cause.

**Fix:** keep the close of the last walked row, and charge every settlement in `(that close, this close]` once the fill is before it.

### E-03, Medium. A trade taken as stopped at a gap still pays later funding

`src/hft_crypto/engine/simulator.py:859-880`, `_net_of` at `:882-893`.

C2's headline treats the position as stopped at the start of the gap. The alternative legs stop there, but `funding` keeps every charge of the recorded path. Case: long, `q0` 10, stop 900, fill 1000, gap at minute 200, a 1% settlement at minute 300. Headline net -1,100.00, where -1,000.00 is right. On a short receiving funding the same line flatters the result, and it can also choose the wrong one of the two ways as the worse.

**Fix:** in the alternative, keep only charges with `settle_us <= gap_start`.

### E-04, Medium. A whole bar with no rows is invisible

`src/hft_crypto/engine/tape.py:291-301`, `:329-331`, `src/hft_crypto/strategies/registers.py:51-60`.

`_spans` makes buckets only from rows that exist. A decision bar with no rows gets no `Bar`, and the next bar is `gap = False`, `complete = True`, with `index` running on as if it were adjacent. ATR is reset, but C3 and C4 use `atr_last` for registers, so the rest carries on. Case: 1h bars, hour 20 empty, a swing high at the bar closing 20:00. `SwingList` adds it at 24:00 although its right-hand window crosses the missing bar. C2 says the object is not computed. The same applies to S01's role, S02's `C_(k-1)`, S04's bases, S06's `C_(s-1)` and PSH, S10's box and band, and every count in bars.

**Fix:** emit a `Bar` with `gap = True` for each empty bucket on the grid, the way a bar with no price is already handled at `tape.py:354-359`. Then the existing `any(bar.gap ...)` checks do their work.

### E-05, Medium. The stall exit runs from `n` on, where the documents say at `n`

`src/hft_crypto/strategies/s03_market_structure.py:216`, `src/hft_crypto/strategies/s10_volatility_compression.py:199`.

S03 section 7.7 is headed "Stall exit: no BOS since entry and `C_b < fill + 1R` at", with `n = 30` and `n = 12`. S10's is "at", `n = 36` and `n = 18`, in the same table as a thesis check at `n = 12`, which the code tests with `==`. The stall uses `>=`, so a trade that clears the check at `n = 36` and falls back at `n = 40` exits. By the table it does not. At `n = 35` for S03 and `n = 40` for S10, my hand cases exit with `TIME_STOP`.

On 150 generated days no stall exit fired past the tabled bar, so the effect is uncommon. It would still change trades on four years.

**Fix:** use `==`, or have `strategy-architect` say the rule runs from that bar on, before the run. Neither the document nor a test settles it today.

### E-06, Medium. A zone can trade on the bar that creates it

`src/hft_crypto/strategies/s04_supply_demand_zones.py:88-94`, `:100-117`, with `src/hft_crypto/strategies/zones.py:84-91`.

S04 section 7.9: "A zone born at a close never affects that bar", and a touch is defined as "after birth". `ZoneBook.update` adds the new zone before the setup loop reads it, and nothing checks the birth bar. Case: base bars ending at index 4, departure bars 5 and 6, where bar 6 opens 1013, dips to 1001.5, below the new `prox` of 1002, and closes 1019. The zone is born at bar 6, and the same close gives a long with `S0` 995.5. No leak, since all of it is known at that close, but the rule says otherwise. S05 reads the same book, for `new_entry` targets, though not for entries.

**Fix:** in `_qualifies`, require `zone.birth_index < bar.index`.

### E-07, Medium. In S05, a first retest bar closing below `mid` does not kill the flip

`src/hft_crypto/strategies/s05_zone_polarity_flip.py:150-153`, `:157-161`.

`in_retest` is read before the bar can open the retest. Section 3: "any close below `mid` during the retest". Case: top 1000, bottom 980, mid 990, X 1030. A bar with low 985 and close 986 opens the retest, closes below `mid`, and the flip lives. The next bar closes 1010 and triggers. That trade should not exist.

**Fix:** after line 161, test the same close against `mid` on the bar that opened the retest.

### E-08, Medium. In S06, a swing pool swept during its wait is treated as fresh

`src/hft_crypto/strategies/s06_liquidity_sweep_reclaim.py:113-124`, `:132-134`, `:188-213`.

A pool is registered only once it is tradable, 8 `T_d` bars after confirmation. Section 3 says a pool is consumed by its first sweep or by any close beyond it, and that the swing must be unswept. Case: swing low 1000, confirmed. During the wait a bar closes at 990. Once ready, the pool registers with `consumed_at = None`, and it can give a trade.

**Fix:** track consumption from the swing's `valid_from`, and apply the 8-bar wait only as a gate on trading.

### E-09, Low to Medium. In S06, a UTC roll at `n = 1` does not recompute `T2`

`src/hft_crypto/strategies/s06_liquidity_sweep_reclaim.py:320-326`.

`first_look and position.n == 1` returns without acting, on the reasoning that those are the pools the setup saw. When the close of `n = 1` is itself the roll, they are not, and the next close sees no change. Case: roll at `n = 1`, no target move. Any new pool at that close is lost the same way. About one setup in 96 on 15m falls on it.

**Fix:** store the setup's pools in its memo, and compare with those at `n = 1`.

### E-10, Low to Medium. In S02, a weekly level trades once a week

`src/hft_crypto/strategies/s02_pivot_breakout_retest.py:108-112`.

Section 5: "At most one trade per level per UTC day". `_traded &= live` keeps a weekly level's id through the daily roll, since it is still live. In a hand case it stays in the set on the next day. This reaches only the `weekly_levels = true` lines.

**Fix:** key `_traded` by level and UTC day.

### E-11, Medium. The break-even cost multiple ignores funding

`src/hft_crypto/reports/portfolio.py:272`.

Net at a multiple `m` is `gross - m * costs - funding`, and that is how the 2x and 3x lines are computed, correctly, on the line above. The break-even uses `gross / costs`. Case: gross 400.00, costs 11.20, funding 100.00. Printed 35.71, where net is -100.00. The true multiple is 26.79. `break_even_rt_bps` carries the same error, and it flatters any stream that pays funding.

**Fix:** `(gross - funding) / costs`.

### Low

| ID | Where | Case and wrong output | Fix |
|---|---|---|---|
| E-12 | `reports/portfolio.py:310-317` | `unrealised_pnl` on a part-closed trade is the whole trade's net. Half out at +1,000, the rest open at its fill: prints 1,000.00, and 0.00 is open. `open_r` uses the whole mark move and says nothing of size | Value only the open quantity, as `unrealised_cents` already can |
| E-13 | `reports/portfolio.py:367`, `engine/simulator.py:896-903` | Two labels. The capped row's `exit_reasons` counts refused trades: 2 reasons for 1 trade. And a stop hit at the old level in the minute before a new stop acts is named from the newest planned stop: `STOP_TRAILED` at the initial stop | Filter by scale. Name the stop from `position.stop`, the one in force |
| E-14 | `engine/run.py:233-257`, `engine/registry.py:120-128` | On candles the registry counts 120 distinct trials, 16 of them S07 and S08 lines that ran nothing. On trades, S08 counts once per run and the index says twice. It is the count the deflated Sharpe will rest on | Count by what ran, with S08's two branches. The working tree seems to be adding this, so recheck it there |
| E-15 | `strategies/s02_pivot_breakout_retest.py:180-182` | `NO_RETEST` is logged at age 12 for a sequence whose retest came and traded. Its counterfactual is not built yet, so nothing reads it today | Delete the sequence when a setup is sent |
| E-16 | `strategies/s02_pivot_breakout_retest.py:117`, `:127-131` | Two small differences. A retest bar needs its own `SRV` though no retest condition uses it, and when the nearest level's setup fails it tries the next, where section 3 says use the nearest | Check `srv` only for acceptance. Decide on the fallback |
| E-17 | `engine/indicators.py:30`, every `CLV` threshold | `CLV` of exactly 0.5 in decimal comes out as 0.49999999999991507 on mirrored prices, so one S07 setup exists only on one side of the mirror. Results are repeatable, so this is an asymmetry at a tie and not noise between runs | Compare with a small tolerance, or on integer ticks |

The hourly marks behind max drawdown are not named in the output (`equity_timeframe_minutes` is 60). Add it to the header, since a drawdown inside an hour does not show.

The entry gross cap in `engine/portfolio.py` reads a trade's final legs at each moment. Those legs are only read up to that moment, but two things in them were not known then: an entry decided at the same moment that later missed its collar is absent, and a headline stop at a gap can come from a flag known later. Both change room by very little. For `leak-auditor`.

## 4. What holds

**Hand cases, all to the cent unless stated.**

| Case | Hand | Code |
|---|---|---|
| Long, half at target, trailed stop, two settlements: net | 414.6874 | 414.69 |
| The same: gross, funding | 550.00, -0.05 | 550.00, -0.05 |
| Marks at the settlement hour and after the scale-out | 100,229.825, 101,204.325 | 100,229.82, 101,204.32 |
| Final equity | capital + net | Equal in cents |
| Entry through the stop: net | -157.5803 | -157.58, no `R`, counted out and printed |
| The 2x and 3x cost lines against a real re-run at those costs | 279.34, 144.01 | 279.33, 143.97 |
| Gross cap: 2000, 1500, 1500 and a later 1500, limit 3000 | Scales 1, 2/3, 0, 1 | The same |

**Rules checked by a run:** funding on each side of C10's boundary, in 7 cases. A stop before a target in one minute. An update acting only from the first minute at or after close + delay. The C8 clamp, and no stop moving back. A pending exit on a gapped open, labelled by the decision at `slip`. A gap beyond a target fills at the target. A touch without a trade-through does not fill. The collar, on and past its limit.

**Mirror.** On 150 generated days with costs off, every grid line of S01 to S06 and S09 gives the same trades and the same money, side for side. S08's bin width and S10's `BBW` scale with price, so they cannot mirror by design, and the differences there are that and not a side bug. S07 differs by one setup in 47, which is E-17.

**Every grid line of every strategy:** final equity = capital + net, long + short = all, and no hold past `H_max`, so FP-07 cannot read past the span on this evidence.

**The whole command, end to end,** on 200 generated days: two runs give byte-identical files, and 283 trades recompute from their own rows with my own arithmetic: fill, every leg price by exit type, fees, net, gross, `R`, `Result_B`, `q0`, `R_dec`, and no fill before its decision. Stream and portfolio totals, final equity, max drawdown, Sharpe on 365 days and CAGR all agree.

## 5. A market that cannot be predicted

This is the check that matters most for a system whose bugs look like good results. On a driftless walk with changing volatility, no causal rule can have a mean gross result away from zero, whatever it does. An edge here would mean a leak or an unfair fill.

| Strategy, default line, 12 seeds of 300 days | Trades | Mean gross `Result_B` | t |
|---|---|---:|---:|
| S01 | 824 | -0.0333 | -0.77 |
| S02 | 757 | +0.0674 | +1.43 |
| S03 | 337 | -0.0482 | -0.89 |
| S04 | 45 | -0.0309 | -0.16 |
| S05 | 12 | -0.4632 | -3.24 |
| S06 | 787 | -0.0154 | -0.36 |
| S07, on trades | 1,973 | +0.0179 | +0.84 |
| S08, on trades | 490 | -0.0491 | -1.54 |
| S09 | 527 | +0.0354 | +0.86 |
| S10 | 114 | +0.0223 | +0.19 |
| **All** | **5,866** | **+0.0035** | **+0.25** |

No edge from nowhere. S05's -3.24 rested on 12 trades, so I ran every S05 line on 60 more seeds: 155 trades, mean -0.1399, t -1.66. That is not a finding.

**Truncation, my own:** each strategy's default line on 200 days and on 300 days of one seed. Every event knowable by the cut is identical, for all ten.

## 6. Readings that need `strategy-architect` before the run

These are not defects. The code took one reading and the text allows another, and either choice changes trades.

| Where | Text | What the code does |
|---|---|---|
| S03, `registers.py:110-121`, `s03_market_structure.py:147` | "`SL_last`... confirmed before the BOS bar" | A swing low confirmed at the BOS close is skipped and the one before it is used. A stricter reading says no higher low exists there |
| S04, `zones.py:141-143` | "take the first that satisfies the conditions" | The search stops at the first departure that fits, even if it lacks the arrival an entry zone needs, so a longer departure with arrival is not tried |
| S05, `s05_zone_polarity_flip.py:159` | "The first bar after travel" | The bar that completes travel can also open the retest |
| S01, `s01_floor_pivot_rejection.py:139` | "A touch of support is a bar with `L <= l + b`" | Followed exactly. A level first seen above the price has already touched, so on the default first-touch line its first real retest from above is its second touch. Worth confirming this is what was meant |
| S09, section 3 | Hours by open, `h_peak` as a clock time | `peak_hour` is the busiest bar by its open, and the schedule step falls at the close at that clock time, which is an hour before that bar's own close. It matches the text as written |

## 7. Clause mapping

I read sections 3 to 8 of every S document against its code, constant by constant, plus C2 to C11, C16 and C18 of the index against the engine. Constants all agree: band and buffer multiples, floors, time stops, `H_max`, scale-outs, grid values, default lines, cost values.

**Clauses with no line, each declared in `run.json` under `not_built`:** `V0S`, C14 counterfactuals, `NO_RETEST` counterfactual, G5 target stress, netted portfolio, deflated Sharpe, share of risk, and benchmarks joined to the output. C18 selection is off. `CYCLE` and `IDEAL` are not run, and the header says why.

**Not declared there:** C17's funding `DATA_GAP` (E-01). The closed-trade equity series of `docs/04` section 1, the monthly and rolling tables, confidence intervals on the headline figures (a sample size is printed), and the S01 `confluence` log, which the file header of S01 does state. These are later work and not errors, but `not_built` should list them.

**Lines with no clause:** the leverage cap acting on `q0`, under `D-28`. When it binds, `Result_B` is money over the full budget, so C10's second form of the formula no longer holds exactly. That is consistent with its first form.

## 8. Commands and output

Run under Git Bash on Python 3.12, from a frozen copy of `cf1880f` outside the repository, with `PYTHONPATH` set to it.

```text
$ python -m pytest -q tests/engine tests/leak/test_strategy_leak.py tests/leak/test_candle_bars_leak.py tests/reports/test_portfolio_rows.py
369 passed in 504.41s
```

| Probe, all outside the repository | Checks | Deviations |
|---|---|---|
| Accounting by hand | 39 | 2: E-02, E-12 |
| Accounting by hand, second set | 7 | 4: E-03, E-11, E-01, E-13 |
| Every grid line: mirror, reconcile, holds | 120 | 13: all mirror, on S07, S08, S10, explained above |
| Whole command, every figure recomputed | 10 | 0 |
| Strategy logic by hand | 11 | 10: E-05 twice, E-07 twice, E-08, E-09, E-10, E-15, E-06, and the S05 reading |
| Missing bar, capped row, trial count | 3 | 3: E-04, E-13, E-14 |
| Driftless market, and truncation | 21 | 1: S05 on 12 trades, gone on 155 |

## 9. What I did not check

- **The full suite.** The developer reports `1657 passed, 2 skipped`, and I did not repeat it. `mypy src` is clean on 63 files, and `ruff format` is clean. `ruff check` finds 4 `E501` in `tests/child_guard/sitecustomize.py`, none in the engine. See the recheck addition.
- **Real data of any kind.** Tick history, candle quirks, and how many bars real gaps touch are unknown. How E-04 and S09's fail-closed profile behave on real candles can only be seen there.
- **A run at full length.** All lines at 150 days took 46 s, which suggests minutes per symbol for four years, but no four-year run was made.
- **My own mutation run on the engine.** One test file set takes 8 minutes, so I spent the time on independent cases instead. The developer's worked-table tests were not used as evidence.
- **The uncommitted C15 placebo work,** and whatever it changes in the files above.
