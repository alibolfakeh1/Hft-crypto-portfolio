# Portfolio outputs

What the report engine must produce for every strategy and for the portfolio. The desktop app, the HTML
and PDF tear sheets, and Telegram all read the same results, so they can never disagree.

## 1. Ground rules

- **Labels.** Backtest results are `SIMULATED`, forward results are `PAPER`. The boundary between them is
  marked on every equity curve, and the two records are never merged into one statistic.
- **From inception.** Every strategy shows its full record from its first trade, not a selected period.
- **Net by default.** Results are net of fees, slippage and funding. Gross is shown beside net.
- **Comparison always available.** Every result can be compared with `V0`, its variants and the benchmarks:
  BTC buy and hold, ETH buy and hold, a 50/50 mix, and cash.
- **Equity basis.** Equity is mark-to-market, including open positions, fees and funding. Closed-trade
  equity is a separate series and is always named as such.
- **Calendar.** UTC, with 365 days per year.
- **Uncertainty.** Headline statistics come with a confidence interval or a sample size. A Sharpe ratio
  from 40 trades must look different from one based on 4,000.

## 2. Portfolio overview

One table with a row per strategy and a total row:

| Column | Definition |
|---|---|
| Strategy, version, gate | Current version and latest gate verdict |
| Start date, days live | Start of the record and days of `PAPER` record |
| Trades | Count, with long and short counts |
| Net P&L | In money and percent, with long and short split |
| CAGR | Compound annual growth rate of the mark-to-market equity |
| Max drawdown | Percent, with its duration |
| Sharpe, deflated Sharpe | Annualised Sharpe, and probability after adjusting for trials |
| Profit factor | Gross profit divided by gross loss, after costs |
| Win rate | Share of trades with a positive net result |
| Average trade | Net, in `R`, basis points and money |
| Current position | Flat, long or short, with open `R` and unrealised P&L |
| Share of risk | This strategy's share of portfolio risk |

## 3. Live positions

Defined in [section 8 of the charter](00_CHARTER.md#8-live-positions-and-publication).

- **Open positions:** strategy, symbol, side, entry time and price, size, `R`, current stop and target,
  distance to each, unrealised P&L in money and `R`, MAE and MFE so far, age, gate state at entry, and the
  history of stop and target moves.
- **Portfolio state:** net and gross exposure by symbol, total open risk in `R` and percent, largest
  position, current drawdown, and how close each risk limit is.
- **Recent events:** opened, stop moved, target moved, scaled out, closed, vetoed setups.
- **Feed status:** the age of the data behind every price shown. If the data is stale, the view says so.

## 4. Strategy tear sheet

### Returns

Total return, CAGR, monthly and yearly return tables, best and worst day, week and month, percent of
positive months, and rolling 30, 90 and 365-day returns.

### Risk

Annualised volatility, downside deviation, max drawdown in percent and money, longest drawdown, time under
water, average drawdown, table of the 10 worst drawdowns with start, trough and recovery, Ulcer index, VaR
and CVaR at 95% and 99%, skewness, excess kurtosis and tail ratio.

### Risk-adjusted

Sharpe, Sortino, Calmar, Omega, gain-to-pain, rolling Sharpe and rolling volatility.

### Trades

Count, win rate, average win and loss, payoff ratio, profit factor, expectancy, system quality number,
average and median trade, largest win and loss, longest winning and losing streaks, trades per month,
average holding time, time in market, and a full exportable trade list.

### Long and short

All of the sections above split by side, with long-only and short-only equity curves and net and gross
exposure over time.

### Charts

Equity on linear and log scales with underwater drawdown on the same time axis, monthly return heatmap,
distribution of daily returns, `R` multiple histogram, rolling metrics, and hour-of-day and day-of-week
heatmaps. A price chart with entries, exits and the path of the stop and target for any selected trade.

## 5. Stop and target analytics

Since stops and targets are dynamic, the report must show whether the dynamic logic helps.

- Exit reasons: initial stop, trailed stop, break-even, target, scale-out, time stop, invalidation, flow exit.
- MAE and MFE scatter by outcome, and edge ratio.
- **Giveback:** MFE minus realised result, in `R`.
- Entry and exit efficiency.
- Number and size of stop and target moves per trade.
- `V0` against `V0S`: what dynamic management added or cost, with a confidence interval.

## 6. Flow gate value

- Comparison of `V0`, `VE`, `VX` and `VEX`, with the difference and its confidence interval.
- **Veto analysis:** the counterfactual result of every vetoed setup. A good gate rejects bad trades, not
  just many trades.
- **Timing analysis:** price improvement and missed trades caused by `WAIT`.
- **Exit analysis:** what flow exits saved and what they cost by cutting winners short.
- Removing one feature at a time shows each feature's contribution.
- A warning when a variant improves the Sharpe ratio only by trading much less.

## 7. Cost and execution

Gross to net breakdown (fees, slippage, funding), cost as a share of gross profit, results at 1x, 2x and 3x
cost, break-even cost per trade, sensitivity to added latency, implementation shortfall, and funding paid
and received by side.

## 8. Regime analysis

Results by volatility state, trend state, liquidity state, sign of funding, weekday against weekend, UTC
session, and bull, bear and sideways periods. Regime labels use only information available at the time.

## 9. Portfolio construction

- Combined equity and drawdown, reported two ways: as a sum of separate strategy streams, and with positions
  netted across strategies by symbol.
- Contribution of each strategy to P&L and to risk.
- Correlation matrix of returns, plus drawdown overlap, since strategies often become correlated when they
  lose.
- Diversification ratio and effective number of independent strategies.
- Allocation methods compared: equal weight, inverse volatility, risk parity and hierarchical risk parity.
  All weights use past data only.
- Beta to BTC and ETH, rolling beta, and return after removing that beta.
- Turnover and an estimate of capacity.

## 10. Robustness and overfitting

| Output | Question it answers |
|---|---|
| Walk-forward results and efficiency | How much of in-sample performance survives out of sample? |
| Probabilistic and deflated Sharpe ratio | Is this Sharpe ratio real, given its sample and the number of trials? |
| Minimum track record length | How long a record is needed before this result is credible? |
| Probability of backtest overfitting | How often does the best in-sample choice fail out of sample? |
| Bootstrap confidence intervals | How uncertain are the headline numbers? |
| Monte Carlo equity and drawdown cone | What range of outcomes fits these trades? |
| Parameter sensitivity surface | Is this a plateau or an isolated spike? |
| Delay and cost stress | How quickly does the result decay? |
| Trial registry summary | How many things were tried before this one? |

Implementers read the original papers for these methods and cite them in the code documentation.

## 11. Live against simulation

Once a strategy runs on paper: forward results against the backtest's expected range, fill and slippage
differences, signals seen in one and not the other, and ledger integrity status.

## 12. Where each output appears

| Output | Desktop app | HTML/PDF tear sheet | Telegram channel |
|---|---|---|---|
| Portfolio overview | Yes | Yes | Daily summary |
| Live positions | Yes, updating | Snapshot | Each event |
| Strategy tear sheet | Yes | Yes | Weekly image |
| Stop and target analytics | Yes | Yes | No |
| Flow gate value | Yes | Yes | No |
| Cost, regime and portfolio construction | Yes | Yes | Monthly summary |
| Robustness and overfitting | Yes | Yes | Headline only |
| Machine-readable export | CSV and Parquet | CSV and Parquet | No |
