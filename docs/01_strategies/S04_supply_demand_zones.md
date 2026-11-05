# S04 Supply and demand zones

Status: revised after the leak audit of 2026-11-04, awaiting re-audit. Not tested. Tier `T0`. Default `T_d` 1h. Long and
short. Live-eligible at 1h and 4h, see section 14.
Common rules C1 to C18 are in [00_INDEX.md](00_INDEX.md#5-common-conventions) and apply throughout.

## 1. Idea and mechanism

A market falls, pauses in a tight base, then leaves upward fast. The story is that large buyers used the base and
the speed of the departure left part of their interest unfilled. When price returns to the base, that interest can
act again. This is the drop-base-rally (DBR) demand zone, and rally-base-drop (RBD) is its supply mirror.

**Who is on the other side.** Traders selling into the return, often momentum followers on a lower timeframe, who
meet resting or slowly worked interest. Research on order flow supports part of this: visible liquidity is thin,
large orders are split and worked over long periods, and much of the market's liquidity is latent
([Bouchaud, Farmer, Lillo](https://ar5iv.labs.arxiv.org/html/0809.0822)).

**How much of this is folklore.** Most of it. That review is about stocks and futures, and says nothing about a
candle pattern. Nobody can observe "unfilled orders" from candles. In crypto, a fast departure is also often forced
flow, which means liquidations, not patient buyers, and a liquidation leaves no parent order behind to finish. The
quality score below includes a guard for that, but it is a judgement call. Practitioners themselves note that good
departures are far easier to see in hindsight
([LuxAlgo](https://www.luxalgo.com/library/concept/supply-and-demand-zones.md)).

## 2. Evidence

**Grade for the rule: `NONE`.** I searched and found no test of zones with outcomes. This is one of the most popular
retail ideas in the set and has no real evidence behind it.

| Source | What it shows | Limits |
|---|---|---|
| [LuxAlgo, supply and demand zones](https://www.luxalgo.com/library/concept/supply-and-demand-zones.md) | Conventions for base, departure, proximal and distal lines, and freshness | No statistics |
| [MQL5, statistical validation](https://www.mql5.com/en/articles/20904) | Describes the candle geometry of 9,663 candidate pairs on one gold M5 file | Despite the title, outcomes were never measured, and no random baseline |
| [Bouchaud, Farmer, Lillo](https://ar5iv.labs.arxiv.org/html/0809.0822) (adjacent) | Large orders are split, order flow has long memory, liquidity is latent | Review of equity and futures microstructure. No link to zones. I read the first part only |
| [Kavajecz and Odders-White](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html) (adjacent) | Support and resistance coincide with depth peaks | Stocks. Abstract only |
| [Chung and Bellotti](https://ar5iv.labs.arxiv.org/html/2101.07410) (adjacent) | Levels from rolling extremes attract further bounces, and the effect decays over hundreds of minutes in EURUSD | Not zones. Suggests zones should age out fast. Their result that more bounces mean more future bounces conflicts with freshness folklore |

**Reading.** The freshness convention and the literature pull in opposite directions, so touch count is in the grid.
The result must be judged against the [placebo](00_INDEX.md#c15-placebo-control), with no benefit of the doubt.

## 3. Definitions

**Base.** A run of 1 to 5 consecutive bars ending at `base_end`, with `ATR_base = ATR_(base_end)`:

- every bar has `H_i - L_i <= 1.0 * ATR_base` and `abs(C_i - O_i) <= 0.5 * ATR_base`,
- the whole run has `max(H) - min(L) <= 1.5 * ATR_base`.

**Departure, demand.** The 1 to 3 bars after `base_end`, ending at bar `e`:

| # | Condition |
|---|---|
| a | Every departure bar has `C > O` |
| b | At least one departure bar has `H - L >= 1.2 * ATR_base` |
| c | Mean `CLV` over the departure bars is at least 0.60 |
| d | `C_e > max(H over base)` |
| e | `C_e - prox >= 1.5 * ATR_base` |

**Zone lines, demand.**

```text
prox = max over base of max(O_i, C_i)                          # top of the bodies
dist = min(L over base bars and the first departure bar)       # lowest wick
h    = prox - dist                                             # require 0.1*ATR_base <= h <= 1.5*ATR_base
```

**Arrival, demand (DBR).** `O_(base_start-3) - C_(base_start-1) >= 1.0 * ATR_base`. Price came down into the base.

**Search order at each close `e`.** Try departure length 1, then 2, then 3, and take the first that satisfies the
conditions. Then take the longest valid base ending just before it. If a zone with the same `base_end` already exists,
do nothing. Supply zones (RBD) are the exact mirror, with `prox = min over base of min(O_i, C_i)` and
`dist = max(H ...)`.

**Stack zone.** The same detection without the arrival condition. It is used only for trailing stops in 7.2, never for
entries.

**Quality score.**

```text
D = min(1, (C_e - prox) / (3 * ATR_base))           # departure strength, frozen at birth
    if the largest departure bar range > 4 * ATR_base: D = min(D, 0.5)      # likely forced flow
T = 1 - min(1, h / (1.5 * ATR_base))                # base tightness, frozen at birth
F = 0.5 ^ touches_before * max(0, 1 - age / MaxAge)        # freshness, updated over time
Q = 100 * (0.5*D + 0.3*T + 0.2*F)
```

The weights are declared constants, fixed by judgement and not fitted. `MaxAge` is 14 days of bars. `age` is the number of bars
from `e` to the close being evaluated.

**Touch.** A bar with `L <= prox` after birth. Consecutive such bars count as one touch, counted at the close of its first bar.
`touches_before` at bar `k` counts touches whose first bar closed before `t_k`. A touch that began at `k-1` and continues at `k` is
therefore included, and one that begins at `k` is not.

**Register.** Zones follow [C4](00_INDEX.md#c4-swing-pivots-and-registers): `valid_from = t_e`, state events carry their own times, and
every read is as of a time. A zone is active at `t` when it has no `broken_at`, `dead_at` or `superseded_at` at or before `t`.

**Zone end.** `broken_at` is the close with `C < dist - 0.25 * ATR`, which passes the zone to S05. `dead_at` is the first close with
`age > MaxAge`.

**Overlap.** If a new zone overlaps an active same-side zone by more than half of its own height, the one with the higher `Q` at the
new zone's `t_e` stands, and the older zone wins a tie. The loser gets `superseded_at = t_e` of the new zone. An older loser was valid
until that moment, and stays usable for every read before it. A new loser is registered with its state and is never active. Both stay
in the register. This rule applies among entry zones only. Stack zones are a separate list, and they neither supersede an entry zone nor are superseded by one.

## 4. Knowable times

| Object | Knowable at |
|---|---|
| Zone, `prox`, `dist`, `D`, `T` | `t_e`, the close of the last departure bar. Never at the base |
| `ATR_base` | `t_base_end`, so the departure cannot inflate its own yardstick |
| `touches_before` | At `t_k`, counts touches whose first bar closed before `t_k` |
| `F`, `Q` | Evaluated at the current close, with `age` at that close and `touches_before` as above |
| Broken, dead, superseded | The close that causes it. Earlier reads are unchanged |
| Stack zone, new opposing zone | Their own `t_e`, effective next bar |

## 5. Setup rules

**Long,** at `t_k`, at a demand zone:

| # | Condition |
|---|---|
| a | Zone active, and `touches_before` is within the limit (default 0) |
| b | `Q_k >= Q_min` (default 60, a grid value) |
| c | `C_(k-1) > prox` and `L_k <= prox` |
| d | `L_k >= dist - 0.25 * ATR_k` |
| e | `C_k > prox` and `CLV_k >= 0.50` |
| f | `VR_k <= 2.0` |
| g | `T1` from 7.3 exists |

**Short.** The exact mirror at a supply zone.

| Setup field | Value |
|---|---|
| `side` | Long or short |
| `level_or_zone` | Zone id, `prox`, `dist` |
| `invalidation` | `S0` |
| `targets` | `T1`, `T2` |
| `expiry` | 4 bars after `t_k` |

## 6. Entry trigger for `V0`

Taker entry at `t_k + latency` on the rejection close, per [C6](00_INDEX.md#c6-entry-fill-r-and-size). Many
practitioners place a limit order at `prox`. This one waits for a close back above, which pays a worse price, needs no
passive fill model, and skips the zones that break straight through.

## 7. Dynamic stop and target model

### 7.1 Initial stop

```text
S_struct = dist - 0.25 * clip(VR_k, 0.8, 1.5) * ATR_k
S0       = min(S_struct, C_k - R_min(0.75))
```

Skip if `C_k - S0 > 2.5 * ATR_k`.

### 7.2 Stop updates

Schedule: every `T_d` close. All go through [C8](00_INDEX.md#c8-stop-ratchet-and-be). `mid = (prox + dist) / 2`.

| Rule | When | `S_cand`, long |
|---|---|---|
| Reaction test | At `n = 3`, `C_b < prox + 0.5 * ATR_b` | `dist` |
| Zone spent | `C_b >= fill + 1R` | `mid` |
| Break-even | `T1` filled | `BE+` |
| Zone stack | A stack zone is born after entry, with `Q >= Q_min` and `dist_new` above the current stop | `dist_new - 0.25 * ATR_b` |

### 7.3 Target logic

**Candidates, ascending,** at `t_k`: the `prox` of every active supply zone above `C_k` with at least `Q = 45` and fewer
than 2 touches, and `HHz`, the highest high between the zone's birth and `t_k`.

- `T1` is the lowest candidate at or above `C_k + 1.5 * (C_k - S0)`. If none exists within `6 * (C_k - S0)`, then
  `T1 = C_k + 2.5 * (C_k - S0)`.
- `T2` is the next candidate above `T1`. If none exists, `T2 = T1 + 1.5 * (C_k - S0)`.

**Recompute** at each close, for the next unfilled target `T`:

1. If a new supply zone is born with `prox_new` between `C_b + 0.5 * ATR_b` and `T`, then `T = prox_new`.
2. If the zone that `T` came from is broken upward, `T` becomes the next candidate above `C_b + 0.5 * ATR_b`.

### 7.4 Scale-out

50 percent at `T1`, the rest at `T2`.

### 7.5 Regime scaling

- The stop buffer scales with `VR`.
- `VR_k > 2.0` blocks new entries. During shocks, zones form in a different volatility regime from the one they are
  tested in.
- A departure bar over `4 * ATR_base` caps `D` at 0.5, so a likely liquidation departure rarely clears `Q_min` on its own.

### 7.6 Floors

`R_min(0.75)` from [C9](00_INDEX.md#c9-floors). Tight bases often make the structure stop small, so the cost term can
bind at 1h.

### 7.7 Time stop

| `T_d` | `T1` not hit by | Absolute limit | `V0S` `H` |
|---|---|---|---|
| 1h | `n = 24` | `n = 96` | 48 |
| 4h | `n = 12` | `n = 42` | 24 |

### 7.8 Invalidation

**Absorption.** For `n <= 6`, if `C_b < mid`, the zone has been absorbed rather than defended: exit at the next open.

### 7.9 Same-bar conflicts

[C7](00_INDEX.md#c7-exit-engine) applies. If a bar could hit both the stop and a target, the stop is taken. A zone born
at a close never affects that bar.

### 7.10 `V0S` control

`S0` from 7.1, `m = 2.5`, `H` from the table in 7.7.

### 7.11 Why this model suits this strategy

Zones fail in a recognisable way: price returns and neither bounces nor breaks at once, but slowly digests the zone,
which means whatever interest existed is being used up. The reaction test and the absorption exit act on exactly that,
and the structure stop is kept for the fast break. After a clean departure, the zone has been used once, and the next
visit is a second touch with less behind it, so the stop moves into the zone at `+1R`. As the trade works it can create
new demand of its own, and each new zone gives a stop level expressed in the strategy's own language. Targets come from
opposing zones because that is where the theory says the next orders wait, so a newly formed opposing zone rightly pulls
the target in.

### 7.12 Worked example, long

Invented numbers, for checking arithmetic only. `T_d = 1h`, ETH. `VR = 1.0` held flat. Zone formation, with `ATR_base = 20`:

| Bar | O | H | L | C | Role |
|---|---|---|---|---|---|
| b1 | 3,205 | 3,212 | 3,198 | 3,204 | Base, after a drop of over 20 from 3,250 |
| b2 | 3,204 | 3,209 | 3,196 | 3,207 | Base |
| b3 | 3,207 | 3,213 | 3,201 | 3,205 | Base |
| d1 | 3,205 | 3,232 | 3,203 | 3,230 | Departure, range 29, net 23 below the required 30 |
| d2 | 3,230 | 3,256 | 3,228 | 3,252 | Departure, net 45. Zone knowable at this close |

- `prox = 3,207`, `dist = 3,196`, `h = 11`, `mid = 3,201.5`.
- `D = 45 / 60 = 0.75`, `T = 1 - 11/30 = 0.633`, `F = 1` at birth. `Q = 100 * (0.375 + 0.19 + 0.20) = 76.5`.

Price rises to `HHz = 3,290`. 48 bars later, with `ATR = 18`, the first return comes, so `age = 48` and `touches_before = 0`.
`F = 1 - 48/336 = 0.857`, so `Q = 73.6`, above the default `Q_min = 60`. Trigger bar closes 14:00: `O 3,222, H 3,225, L 3,203, C 3,216`,
`CLV = 0.59`.

- `S_struct = 3,196 - 4.5 = 3,191.5`. `R_min = max(13.5, 15.4)`. `S0 = 3,191.50`, and `C - S0 = 24.5`.
- Threshold for `T1` is 3,252.75. An active supply zone has `prox = 3,262`, `dist = 3,270`, so `T1 = 3,262`. `T2 = HHz = 3,290`.
- `R_dec = 24.50`. The collar is 3,225, and the next open of 3,215.5 is inside it.
- So `fill = 3,215.82`, `R = 24.32`, `BE+ = 3,219.68`.

| `n` | Close | O | H | L | C | Event at this close | Stop after close | Next target |
|---|---|---|---|---|---|---|---|---|
| 1 | 15:00 | 3,215.5 | 3,222 | 3,211 | 3,219 | Absorption check passes | 3,191.50 | `T1` 3,262 |
| 2 | 16:00 | 3,219 | 3,228 | 3,216 | 3,226 | | 3,191.50 | `T1` 3,262 |
| 3 | 17:00 | 3,226 | 3,233 | 3,221 | 3,231 | Reaction test passes: `C >= 3,216` | 3,191.50 | `T1` 3,262 |
| 4 | 18:00 | 3,231 | 3,244 | 3,229 | 3,241 | `C >= fill + 1R`: zone spent, stop to `mid` | 3,201.50 | `T1` 3,262 |
| 5 | 19:00 | 3,241 | 3,249 | 3,236 | 3,238 | | 3,201.50 | `T1` 3,262 |
| 6 | 20:00 | 3,238 | 3,243 | 3,233 | 3,236 | | 3,201.50 | `T1` 3,262 |
| 7 | 21:00 | 3,236 | 3,240 | 3,230 | 3,238 | | 3,201.50 | `T1` 3,262 |
| 8 | 22:00 | 3,238 | 3,258 | 3,236 | 3,255 | | 3,201.50 | `T1` 3,262 |
| 9 | 23:00 | 3,255 | 3,268 | 3,253 | 3,266 | `H > T1`: 50% out at 3,262 (`+1.90R`). `BE+` | 3,219.68 | `T2` 3,290 |
| 10 | 00:00 | 3,266 | 3,276 | 3,264 | 3,274 | Stack zone born: base bars 5 to 7, `prox 3,241`, `dist 3,230`, `Q = 68.3`. Stop `3,230 - 4.5` | 3,225.50 | `T2` 3,290 |
| 11 | 01:00 | 3,274 | 3,286 | 3,272 | 3,284 | | 3,225.50 | `T2` 3,290 |
| 12 | 02:00 | 3,284 | 3,287 | 3,280 | 3,282 | | 3,225.50 | `T2` 3,290 |
| 13 | 03:00 | 3,282 | 3,285 | 3,279 | 3,281 | | 3,225.50 | `T2` 3,290 |
| 14 | 04:00 | 3,281 | 3,282 | 3,258 | 3,260 | | 3,225.50 | `T2` 3,290 |
| 15 | 05:00 | 3,260 | 3,262 | 3,248 | 3,250 | Supply zone born: base bars 12 and 13, `prox 3,281`, net 31. Target pulled in | 3,225.50 | `T2` 3,281 |
| 16 | 06:00 | 3,250 | 3,262 | 3,246 | 3,258 | | 3,225.50 | `T2` 3,281 |
| 17 | 07:00 | 3,258 | 3,270 | 3,255 | 3,268 | | 3,225.50 | `T2` 3,281 |
| 18 | 08:00 | 3,268 | 3,283 | 3,266 | 3,279 | `H > T2`: 50% out at 3,281 (`+2.68R`) | closed | |

Result before costs: `0.5 * 1.90 + 0.5 * 2.68 = 2.29R`. `Result_B = (0.5 * 46.18 + 0.5 * 65.18) / 24.50 = 2.27`. `R` stayed 24.32
throughout. This path was chosen to exercise
the rules and does not represent a typical outcome. Had bar 2 closed at 3,200, below `mid`, the position would have
exited at the next open by absorption, at about `-0.65R`.

## 8. Parameters

| Parameter | Grid | Reason |
|---|---|---|
| `T_d` | 1h, 4h | Zones on 15m and below are mostly noise relative to taker cost. 4h zones may be more meaningful and are rarer |
| `Q_min` | 45, 60 | Loose and strict. Finer steps would only add trials |
| Touch limit | 0 only, up to 1 | Freshness folklore against the bounce-memory results |

Total: 8 configurations. Score weights, `MaxAge` and all stop and target constants are frozen.

## 9. BTC and ETH notes

- Same constants on both, since everything is in `ATR`.
- ETH's thinner book may mean departures are more often mechanical. In my judgement, the 4-`ATR` forced-flow cap may
  bite more there. Report how often it fires per symbol.
- A market-wide liquidation creates simultaneous zones on BTC and ETH, which means one event with two sets of trades.
  Layer 5 should treat them as linked.

## 10. Regime expectations

| Regime | Expectation | How I would tell |
|---|---|---|
| Ranges with clear swings | Should work best if it works at all | Result by day type measured afterwards, and by `Q` band |
| Strong trends against the zone | Should fail, with zones breaking directly | Stop exits with little `MFE` |
| Slow grinding markets | Should fail by absorption | High share of absorption exits |
| After liquidation events | Zones are suspect | Compare zones with and without the forced-flow cap |
| Any regime | A higher `Q` should mean a better result | If results do not rise with `Q`, the score is decoration. Report by band, and do not re-weight on test data |

## 11. Flow hooks

Questions for `feature-integrator`.

- **Setup qualification:** was the departure carried by broad aggressive buying, or by a burst of forced flow?
- **Entry gate:** as price enters the zone, does aggressive selling slow and fail to move price?
- **Entry timing:** does taker flow turn positive before or after the rejection close?
- **Early exit:** during the first six bars, does flow show the zone being absorbed before a close below `mid` appears?
- **Stop tightening:** when an opposing zone is approached, does flow weaken?

## 12. Leak traps

| Trap | Concrete failure | Guard |
|---|---|---|
| Zone dated by its base | Treating a base at 10:00 as a zone at 10:00, when the departure finished at 13:00 | Knowable at `t_e` only. A touch before `t_e` cannot exist for this zone |
| Score using later data | `D` measured to the eventual top of the rally | `D` uses `C_e` only |
| `ATR_base` from after departure | The departure inflating the yardstick | `ATR` at `base_end` |
| Freshness with later touches | `F` using all touches in the zone's life | Touches whose first bar closed before the evaluated bar only |
| Survivorship of zones | Testing only zones that held | Every zone that passes the definition stays in the register, including those that broke before any trade |
| Later zone removes an earlier one | Zone A born Monday, overlapped by a stronger zone B born Wednesday. A final register deletes A for Tuesday as well | A stays valid until `superseded_at = t_e` of B. Reads are as of a time, and truncation invariance is required |
| Target from a zone not yet known | A supply zone born at bar 15 used as a target at entry | Candidates at `t_k` only, then recomputed at each later birth |
| Stack stop too early | Using a base's low before its departure completes | Only at the stack zone's `t_e`, effective next bar |
| Search order hindsight | Trying all departure lengths and keeping the best | The first valid length, in increasing order, at each close |

## 13. Expected frequency and cost sensitivity

**Frequency (design estimate, unmeasured).** About 60 to 150 trades per year across BTC and ETH at 1h with the default
`Q_min`, and fewer at 4h.

**Cost.** Typical `R` about 60 to 120 bp at 1h by my judgement. At the declared `RT = 12 bp`, that is about `0.10R`
to `0.20R` at 1x, and `0.3R` to `0.6R` at 3x. A gross `+0.2R` on an 80 bp stop dies at `RT = 16 bp`. The close-based
entry costs a further part of `R` compared with a limit at `prox`, which is a price I accept for honest fills. A stop exit pays `stop_slip` in place of `slip`, so 16 bp in all at 1x, under [C16](00_INDEX.md#c16-rounding-and-arithmetic-in-examples).

## 14. Live on an hourly cycle

**Verdict: eligible. Lowest live-eligible `T_d`: 1h. 4h also eligible.** The zone stays valid for days, but the rejection
reaction is quick, so this is the most delay-sensitive of the 1h strategies. The checks are correspondingly tight.

**Late entries.** General checks are in [C17](00_INDEX.md#c17-hourly-live-cycle). Values for this strategy:

| Check | Value for a long, short mirrored |
|---|---|
| `A_max` | 75 minutes at 1h, 150 minutes at 4h, after the trigger close |
| Path | `S0` or `T1` touched, or a `T_d` close below `mid` since `t_k`, voids the setup |
| Chase | `abs(P_dec - C_k) <= 0.5 * ATR_k` |
| Risk | `P_dec - S0` between the setup's `R_min(0.75)` and `2.5 * ATR_k` |
| `RR_late` | `T1 - P_dec >= 1.25 * (P_dec - S0)` |
| Thesis | `P_dec > prox`: the zone must still be below the price |

Using the example in 7.12, with `C_k = 3,216`, `S0 = 3,191.50`, `T1 = 3,262`, `ATR = 18`:

- `P_dec = 3,224` at a late run: chase 8 passes against 9, but risk is 32.5 and reward 38, below the required 40.6.
  Result: `STALE_SETUP`, reason `RR_LATE`.
- `P_dec = 3,218`: chase 2, risk 26.5, reward 44. All pass.

A zone found late stays usable, because its inputs are closed bars. A zone born at the 13:00 close and first processed
by a 14:21 run can serve a trigger bar closing at 14:00, since all of that is at or before that run's `t_cut`. Bars are processed in
time order so touch counts stay correct.

**Stops and targets between runs.**

- Touches between runs are resolved from 1m bars at the next run, with `event_time` and `detection_time` recorded. Inside
  one 1m bar, the stop is first.
- Reaction test, zone spent, zone stack and target recomputes are computed at each processed `T_d` close, in time order,
  with position state as of that close, and act from `effective_from`. `n` counts `T_d` closes from the bar containing the fill. A
  late fill can make `n = 1` a later bar than in `IDEAL`, but after the fill a late run does not move a test to a different bar.
- The absorption exit fills after the run that saw it, so a long gap makes it more costly. `CYCLE` must show this.
- Stops only tighten: the `P_dec` clamp in C17 can reduce a candidate, and the ratchet then keeps the old stop.

**Backtest reproduction.** `CYCLE` under [C17](00_INDEX.md#c17-hourly-live-cycle), with `C-LATE` for selection, and the zone
register replayed by simulated run in time order. Report the count of `STALE_SETUP` by reason, and absorption exit prices
in both modes. I expect a noticeable `IDEAL` minus `CYCLE` gap here, because good reactions leave `RR_late` behind quickly.
That is untested. On the candle stage (`D-31`) no `CYCLE` run may start, so this selection does not run there, under [C18](00_INDEX.md#c18-selection-purge-and-retirement). Any choice between 1h and 4h for live is a selection, made on training folds only and logged, under
[C18](00_INDEX.md#c18-selection-purge-and-retirement).
