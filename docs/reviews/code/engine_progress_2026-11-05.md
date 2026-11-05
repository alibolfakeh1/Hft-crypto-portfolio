# Engine progress note

Date: 2026-11-05. Author: `developer`. A working note, not a review. No reviewer has read this code and no verdict is
claimed. Everything here ran on generated data only. Nothing here says whether any strategy would make money.

## Done

| Item | State |
|---|---|
| Simulator in `IDEAL-1M`, with the timing contract in code | Runs. `src/hft_crypto/engine/` |
| `V0` of S01 to S06, S09 and S10 | Coded. Each matches its document's worked table, within the rounding noted below |
| `V0` of S07 and S08 | Coded for bars from trades. On candles they give no result and log why. `T0-APPROX` is not built |
| All 60 grid lines, default first, portfolio line as an input (`D-35`) | Runs. Nothing is ranked or picked |
| Date range checked against the fold plan's opened blocks | Runs. A run opens no file outside its range |
| Setups reaching an unopened date or a read day | Left out, never simulated, counted, with the strategy flat across them (FP-06, FP-07) |
| Risk per trade, leverage cap, gross cap | Required inputs, printed on every output. Placeholders under `D-28` |
| JSON outputs, trial registry, C12 declared costs | Run |
| Command | `python -m hft_crypto.engine` |

## Not built

| Item | Why |
|---|---|
| C15 placebos | Possible on candles from the documents, for all eight. C15 wants the draw count declared in advance, and no count or seed list is declared yet. S03 and S10 also do not say how many entries to draw per block, and the level placebos do not say whether distances pool across level kinds |
| `V0S` | Outside this brief. The fold plan's owner view asks for it |
| C18 selection for S01 and S06 | Left out, as the brief allows. No line is picked anywhere |
| C14 counterfactuals, `NO_RETEST` counterfactual, G5 target stress, netted portfolio, deflated Sharpe | Listed in `run.json` under `not_built` |

## Open with other owners

| Item | Owner |
|---|---|
| What S09's profile does with a missing or zero-volume hour. It fails closed under C2 for now | `strategy-architect` |
| `candle_allowance_ms` is now 10000 in `pipeline.toml`, as `D-33` declares. The engine reads it from there and holds no copy, and `synthetic.py` still builds its generated root with 250 ms | `developer` of the data layer |
| The reader now leaves the next day's part shut for bars on a midnight cut, but trades and funding still read the part named by the cut's date. So a range ending before the last opened date still gives up its last minute. A range ending on that date, such as the first span, reads it. No position feels this, because a setup reaching the range's end is left out under FP-07 | `developer` of the data layer |
| The real risk limits, `D-28` | Owner |
