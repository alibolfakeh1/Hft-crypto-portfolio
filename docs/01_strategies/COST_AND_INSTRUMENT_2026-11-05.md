# Cost and instrument: proposal for the owner

Date: 2026-11-05. Author: `strategy-architect`. Status: proposal, for the owner to decide. `leak-auditor` reads any resulting change afterwards. Nothing in C1, C9, C16 or any strategy document has changed.

This is arithmetic on the documents. Nothing has been tested, no market data was used, and nothing here says whether any strategy would make money.

**The decision.** C1, C9 and C16 assume a perpetual at about 10 bps round trip. The research source is open, and it may or may not be a perpetual. The owner chooses which cost band the research declares. The choice is free before the first `V0` run. After that, changing `RT` is a counted trial under C12, and it changes trade lists through the C9 floor.

## 1. Cost bands, `RT` and the floor

`RT = 2 * (fee_taker + slip)`, and the floor on the initial stop is `4 * RT * C_k` (C9). `slip` is 1 bp per side (C16). So C16's `RT = 12 bp` belongs to the about 10 bps band: 10 bps of fees plus 2 bps of slippage.

| Option | Band, fee round trip | Taker, bps | `RT`, bps | Floor, bps | `RT` at 2x and 3x, bps |
|---|---|---|---|---|---|
| **A** | About 10, perpetual-like | 5 | 12 | 48 | 24, 36 |
| **C** | About 50, a high spot tier | 25 | 52 | 208 | 104, 156 |
| **B** | About 160, a base spot tier | 80 | 162 | 648 | 324, 486 |

**Option A has two cases.**

- **A1: the approved history is the perpetual itself,** for example from a paid vendor. There is no proxy problem. Funding history must be included, and the sample starts no earlier than the first rate it holds. One vendor's listed prices are in `docs/03_DATA_SOURCES.md`. Whether a vendor's files carry funding is `UNVERIFIED` until read.
- **A2: the approved source is not the perpetual.** Its trades are a price and flow proxy. Funding is a declared flat charge of 1 bp per 8 hours against every open position, long or short, with reports at 0 and 3 bp. I have read no funding rate for any venue, so this value is a placeholder, `UNVERIFIED`. At S03's 10-day `H_max` it comes to 30 bps. A retest on the real perpetual is required before any live claim.

**Example only, not the project's venue.** Kraken's published schedule, as the coordinator read it on 2026-11-05, shows what these bands look like. Spot taker is 80 bps at $0+ of 30-day spot volume and 25 bps at $100K+, or at 200k of assets on the platform. Futures taker is 5 bps under $5M. Margin trades add fees of 2 to 4 bps at opening and closing, and a rollover per 4 hours, in rows that did not include BTC or ETH. Higher tiers were not read, and I did not open the page myself.

**What the about 50 bps band needs.** A tier is earned by real volume or real assets, and paper positions generate neither, so this band is a counterfactual until a real account qualifies. This document assumes no tier for the owner. With a threshold `V` per 30 days and `T` round trips per 30 days, the notional per side must be `V / (2 * T)`. For `V` of $100K and `T` of 10, that is $5,000.

## 2. S01 to S10 against each band

**Inputs.** Design stops are from section 13 of each document, and they are my judgement, not measurements. The rule limit is the stop cap in section 7.1, times the `VR` block, times the worked example's `ATR`. It is the widest stop a setup could have at the documents' `ATR` scale. Those `ATR` values are invented, so the limit shows scale only, and gate G3 replaces it with measured values.

**Verdict rule.** **Survives:** the floor is at or below the low end of the design stop. **Changes:** the floor is above the low end but within the rule limit, so cost sets the stop on some or all setups, and targets written as multiples of the stop move out. **Not mid-frequency:** the floor is above the rule limit, so a setup exists only when `ATR` is far above the documents' scale.

| Strategy, `T_d` | Design stop, bps | Rule limit, bps | Least `T1` distance at floors 208 and 648, bps, and time allowed | A, floor 48 | C, floor 208 | B, floor 648 |
|---|---|---|---|---|---|---|
| S01, 15m | 50 to 60 | 118 | 250, 778, in 4 h | Survives | Not mid-frequency | Not mid-frequency |
| S02, 1h | 80 to 120 | 255 | 312, 972, in 24 h | Survives | Changes | Not mid-frequency |
| S03, 1h | 150 to 250 | 361 | 260, 810, in 30 h | Survives | Changes, part of range | Not mid-frequency |
| S03, 4h | 300 to 500 | No 4h `ATR` given | As designed, 810, in 48 h | Survives | Survives | Changes at best |
| S04, 1h | 60 to 120 | 280 | 312, 972, in 24 h | Survives | Changes | Not mid-frequency |
| S05, 1h | 80 to 150 | 211 | 156, 486, in 18 h | Survives | Changes, at the edge | Not mid-frequency |
| S06, 15m | 50 to 70 | 107 | 208, 648, in 3 h | Survives | Not mid-frequency | Not mid-frequency |
| S07, 1h | 80 to 150 | 297 | 208, 648, in 24 h | Survives | Changes | Not mid-frequency |
| S08, 1h, rejection | 60 to 120 | 263 | 156, 486, in 8 h | Survives | Changes | Not mid-frequency |
| S09, 1h | 60 to 120 | 231 | 260, 810, within 11 h | Survives | Changes | Not mid-frequency |
| S10, 4h | 150 to 300 | 263, no `VR` block | 416, 1,296, in 72 h | Survives | Changes, part of range | Not mid-frequency |

**Reading it.**

- **Band A** is the band the documents were written for.
- **Band C.** S02, S04, S07, S08 and S09 pass their caps only with `VR` of about 1.4 to 1.8, and S05 only at about 1.97 against a block above 2.0. They would trade only when `ATR` is well above its 30-day median, which is a different strategy from the one documented. S01 and S06 cannot pass at this scale.
- **Band B.** The floor is above every design stop in the set. `T1` then lies at least 486 bps away, inside time limits of 3 to 72 hours, so a time stop looks like the likely exit. That last point is reasoning, not a measurement.

## 3. How shorts work

| Case | Short | Cost |
|---|---|---|
| A1 | Native to the instrument, with no borrow, and the mirror rule stands | Same fee as a long, and the actual funding rate, paid or received by side, under C10 |
| A2 | Simulated as a perpetual short on proxy prices, with no borrow, and the mirror rule stands | Same fee as a long, and the flat charge |
| C, B | Spot needs margin to short, so a short is no longer a mirror of a long | `RT` plus `2 * m` plus `r` per rollover. With `m` and `r` both taken at the example's 2 to 4 bps and a 4-hour rollover: 16 to 32 bps for 1 day, and 124 to 248 bps for S03's 10 days. Rates for BTC and ETH, and for any chosen venue, are `UNVERIFIED` |

Neither A case models margin or liquidation. C9 has one `RT`, so band C or B needs a declared short cost. Dropping shorts instead would make every strategy long-only, which removes the short side of every document and leaves the result tied to market direction.

## 4. Instrument and labels

Every label starts with `SIMULATED` or `PAPER`, as project rule 4 requires, and appears on every report, chart and post.

| Case | Paper positions priced on | Label continues |
|---|---|---|
| A1 | The perpetual's own live feed. A vendor's history does not by itself approve a live poll, and archive and poll must be shown to match | `<venue> <contract>. Declared taker 5 bps, slip 1 bp, not a real account's fees. Funding: actual.` |
| A2 | The approved source's live trades, not the perpetual | `Prices and flow: <source> <market>, a proxy. Costs: assumed perpetual, taker 5 bps, slip 1 bp, funding a flat assumption. No instrument has these prices and these costs. Not retested on a perpetual.` |
| C | The approved spot market's live trades | `<source> spot. Assumed high tier, taker 25 bps, not a real account's fees. Paper earns no tier. Shorts assume margin at <m>, <r>.` |
| B | The approved spot market's live trades | `<source> spot. Base tier, taker 80 bps. Shorts assume margin at <m>, <r>.` |

**What A2 cannot claim.** A perpetual-cost simulation on proxy prices is a research screen. It cannot claim:

- that anyone could have earned the result, because no instrument has those prices and those costs;
- that fills, stop touches or slippage would have matched the perpetual. The price difference between the two markets is not measured here, so a stop touched on one need not be touched on the other;
- anything about real funding, or any link between funding and the position's side, which a flat charge cannot show;
- anything about perpetual forced flow, which the mechanism sections of S03, S04, S06 and S10 refer to, or about perpetual order flow, because the flow measured is the proxy's;
- any live result. Gate G8 would show only that paper matches the simulation on the same proxy.

The retest uses the same frozen configuration, with no reselection, on the perpetual's own prices and actual funding. It is logged as a control, and its data source is declared before the first run.

## 5. What must change, if chosen

Listed only. Nothing below has been changed.

| Text | A1 | A2 | C and B |
|---|---|---|---|
| C1 | Stands. Names the contract once approved | Add that prices and flow are a declared proxy, and that no result is a perpetual result before the retest | Replace the perpetual with a spot market |
| C9 | Formula stands. `RT` 12 declared under C12 | As A1 | Formula stands. `RT` 52 or 162, plus a short cost. The owner decides whether the factor 4 stays |
| C10 | Stands. Funding history becomes a required input | Add the flat charge for proxy runs. Actual rates only in the retest | Remove funding. Add margin fees and rollover for shorts |
| C16 | Fee and slippage stop being "for arithmetic only" once a venue's fee is read. Examples stand | As A1 | New values, and all ten worked examples recomputed, since `RT` feeds `R_min` and `BE+` |
| Other conventions | C17 trade feed placeholders filled from this source | Report fields `price_source` and `cost_source`, the label above, and a retest rule, in the charter and `04_PORTFOLIO_OUTPUTS.md` through their owners | C12, C13 `m` and `H`, C17 risk and reward checks, C18 `H_max` and `A_max` |
| S01 to S10 | No rule changes. Funding schedule text in S03 and S09 read from the venue | No rule changes. One line in S03, S04, S06 and S10 that the proxy does not test forced flow | Sections 5, 7, 8, 13 and 14 as new versions, a stated reason for unequal shorts, and mechanism text on perpetual flow. S01 and S06 are rewritten or retired |

## 6. Cost reports and power

Under C9, `RT` is frozen at 1x, so the 2x and 3x reports change P&L and not the trade list.

| Cost in `R` at 1x, 2x, 3x | A | C | B |
|---|---|---|---|
| 60 bps stop, with no floor | 0.20, 0.40, 0.60 | 0.87, 1.73, 2.60 | 2.70, 5.40, 8.10 |
| 100 bps stop, with no floor | 0.12, 0.24, 0.36 | 0.52, 1.04, 1.56 | 1.62, 3.24, 4.86 |
| 200 bps stop, with no floor | 0.06, 0.12, 0.18 | 0.26, 0.52, 0.78 | 0.81, 1.62, 2.43 |
| Stop at the floor | 0.25, 0.50, 0.75 | 0.25, 0.50, 0.75 | 0.25, 0.50, 0.75 |

- **Removing the floor does not rescue bands C or B.** The stop stays as designed, and one round trip then costs about 0.5R to 1.6R at a 100 bps stop.
- **Band A's 3x, at 36 bps, is still below band C's 1x.** So its stress range says nothing about spot. Band A should add fixed P&L lines at `RT` 52 and 162 on the same trade list, labelled as not a spot design. The break-even cost in charter section 6 can be read against them.
- **Bands C and B.** A 2x or 3x multiple stresses a listed fee, which is not the uncertain part. Slippage needs its own stress.
- **Net tests.** With mean gross `g`, cost `c` and per-trade deviation `s`, the net t-statistic is `(g - c) / s * sqrt(n)`. `g` and `s` are unknown. A higher `c` lowers it at every `g`, and when `g < c` no number of trades helps.
- **Gate tests against a placebo** do not depend on `c` directly, only on `n`. By `GATE_SPEC.md` section 11, the detectable difference is about `7.33 / sqrt(n)` at an assumed `sigma` of 1.2. A 75 percent cut in `n` doubles it, and long-only multiplies it by about 1.41 on an even split, which is `UNVERIFIED`. Section 4 of `STRATEGY_FEATURE_MATRIX.md` already predicts `INCONCLUSIVE` for most at design counts. Under bands C and B the cut in `n` is `UNVERIFIED`, and `sigma` would change as well.
- **History.** The same section scales these figures by `sqrt(5 / years)`. A2 may have a longer history than A1, which is the one point in its favour, and only on a proxy. A1 is the only case where the design frequencies, "written with perpetuals in mind", rest on the instrument they describe.
- **Trial count.** The budget stays at 64 under A. Retiring S01 and S06 would leave 48. Before the first run, re-declaring values adds no penalty. After it, each change is counted.

## 7. Recommendation

**Option A, in case A1.** Make perpetual history with funding a requirement when the research source is chosen, ahead of a longer or cheaper history on another market. Use A2 only if no such history is approved, only as a research screen, under its label, with the retest declared before the first run. I do not recommend B.

- It is the only band where all ten strategies stand as audited. Band C changes eight and stops two, and that rewrite is a new strategy set needing a new audit.
- A1 tests the strategies on the instrument they were written for, with real funding and no proxy caveat.
- Band B needs no backtest to read. If a base spot tier is the real cost, the finding is that these designs do not fit it.

**What this gives up.** A band A result says nothing about trading on spot, and its fee is a declared value and not any real account's.

**What would change my recommendation.**

- **A real, quoted spot fee with taker at or below about 9 bps.** The floor is then at or below 80 bps, inside or below the design stop of every strategy except S01 and S06. I would take that over A2, because it needs no proxy, though shorts would still need the cost in section 3.
- **The owner decides the instrument is spot, or no perpetual can be approved for history, paper or a retest.** A2 then has no route to any live claim. I would move to band C, start from S03 and S10 at 4h, treat the rest as redesign, and say plainly that S01 and S06 do not fit.
- **A proxy check that fails.** Compare `V0` setup lists, with no outcomes read, on the proxy and the perpetual over any span where both exist. If they disagree beyond a threshold declared before the check, A2 is not a fair proxy and I would stop using it.
- **Measured values far from section 2.** If G3 finds `ATR` scales or stop sizes well away from my judgement, the verdicts are redone. A much higher `ATR` scale would make band C less damaging.
- **A perpetual history too short to test anything.** I would then use A2 for the longer span and hold A1 as the retest, with both declared before the first run.
