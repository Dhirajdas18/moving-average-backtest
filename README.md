# Moving-Average Backtest

[![CI](https://github.com/Dhirajdas18/moving-average-backtest/actions/workflows/ci.yml/badge.svg)](https://github.com/Dhirajdas18/moving-average-backtest/actions/workflows/ci.yml)
[![Dashboard](https://github.com/Dhirajdas18/moving-average-backtest/actions/workflows/pages.yml/badge.svg)](https://dhirajdas18.github.io/moving-average-backtest/)

A backtester for moving-average trading rules on NSE stocks (RELIANCE, HDFCBANK, INFY, TCS, ITC) and the
NIFTY 50, built to give the answer you would actually have got: trades fill at the next open, every order
pays Indian charges and slippage, and capital-gains tax is settled each financial year.

**Live dashboard: [dhirajdas18.github.io/moving-average-backtest](https://dhirajdas18.github.io/moving-average-backtest/)**,
rebuilt weekly from fresh data by GitHub Actions.

## Features

- [x] Rupee-accurate engine: next-open fills, Zerodha delivery charges, slippage, cash interest, STCG/LTCG
  tax with loss set-off and carry-forward, after-tax liquidation value
- [x] SMA vs EMA; price filter vs fast/slow crossover
- [ ] Trade statistics: win rate, payoff, expectancy, exposure, tax drag
- [ ] Parameter sweep, deflated Sharpe ratio, probability of backtest overfitting
- [ ] Walk-forward optimisation
- [ ] Trend filter vs a same-exposure fixed mix
- [ ] Survivorship bias

## Findings

### 1. A realistic backtest takes 1.7–2.3 points a year off a 200-day rule, two to three times what buy and hold pays

<table><tr>
<td><a href="docs/img/engine_waterfall.png"><picture><source media="(prefers-reduced-motion: reduce)" srcset="docs/img/engine_waterfall.png"><img src="docs/img/engine_waterfall.gif" alt="NIFTY 200-day rule growth as fills, costs and tax are added"></picture></a></td>
<td><a href="docs/img/engine_drag.png"><picture><source media="(prefers-reduced-motion: reduce)" srcset="docs/img/engine_drag.png"><img src="docs/img/engine_drag.gif" alt="Growth lost to costs and tax: 200-day rule vs buy and hold, six NSE series"></picture></a></td>
</tr></table>

The rule holds while the close is above its 200-day simple moving average and sits in cash (earning
6.5%) otherwise. It traded 48–72 times over 2013–2026, about 4–5 round trips a year.

- **NIFTY:** 8.4% a year in the common naive backtest (trade at the signal's own close, no costs, no tax),
  6.8% after next-open fills, costs and tax. Buy and hold kept 10.2% after the same costs and tax.
- **Costs** took 1.2–1.8 points a year from the rule on every series, and **tax** another 0.2–1.0. Buy and
  hold lost 0.6–1.0 points in total, mostly the long-term tax on selling at the end.
- **Filling at the next open instead of the signal close** moved results by −1.2 to +0.4 points, in both
  directions (HDFCBANK −1.2, TCS +0.4). The overnight gap is noise for a slow rule, but it is real money
  for a fast one.
- On these six series, the 200-day rule kept less than buy and hold on every one. Whether that is the
  rule or just these years is the subject of later sections.

### 2. Filters whipsaw, crossovers lag, and buy and hold beat both on five of six series

<table><tr>
<td><a href="docs/img/rules_2020.png"><picture><source media="(prefers-reduced-motion: reduce)" srcset="docs/img/rules_2020.png"><img src="docs/img/rules_2020.gif" alt="NIFTY 2020 with 50 and 200-day SMAs and the sell and buy points of a filter and a crossover"></picture></a></td>
<td><a href="docs/img/rules_whipsaw.png"><picture><source media="(prefers-reduced-motion: reduce)" srcset="docs/img/rules_whipsaw.png"><img src="docs/img/rules_whipsaw.gif" alt="Round trips a year and share of trades under 30 days for four moving-average rules"></picture></a></td>
</tr></table>

Four textbook rules at standard settings (not tuned, so no parameter was chosen with hindsight): a price
filter (hold while the close is above its 200-day average) and a 50/200 crossover (hold while the 50-day
average is above the 200-day), each with a simple (SMA) or exponential (EMA) average.

- **Filters whipsaw.** They made 4.2–4.3 round trips a year, and 72–73% of their trades ended within 30 days,
  mostly at a small loss (win rate 22–23%). Each false signal pays costs and often short-term tax.
- **Crossovers lag.** They traded 0.6–0.7 times a year with few whipsaws, but exit late. In 2020 the SMA
  50/200 cross sold NIFTY on 19 Mar, 33% below the peak and four days before the bottom, and bought back
  on 21 Aug, 49% above the low. The SMA filter sold on 26 Feb (6% below the peak) but also bought back
  late (17 Jul, +43% from the low).
- **An EMA and an SMA of the same length have the same average lag** ((N−1)/2 days); the EMA just reacts to
  a new move sooner. The EMA version kept more on 6 of 6 series for the crossover and 4 of 6 for the filter.

<a href="docs/img/rules_cagr.png"><picture><source media="(prefers-reduced-motion: reduce)" srcset="docs/img/rules_cagr.png"><img src="docs/img/rules_cagr.gif" alt="Growth after costs and tax by rule and symbol, with buy and hold" width="720"></picture></a>

- **No rule style won consistently.** Crossovers beat filters on only 3 of 6 series (SMA) and 4 of 6 (EMA);
  the higher averages come from a few series.
- **Buy and hold kept the most on 5 of 6 series.** The exception was ITC, where the EMA cross kept 8.0% a
  year against 6.3%. The rules did cut the worst drawdown (33–38% on average, against 47%), which section
  6 tests against a fair same-exposure benchmark.

## Assumptions

Capital ₹10 lakh. Zerodha delivery charges as of Nov 2026 ([zerodha.com/charges](https://zerodha.com/charges)):
STT 0.1% each side, stamp duty 0.015% on buys, NSE 0.00322%, SEBI 0.0001%, GST 18% on fees, ₹16 DP charge
per sell, plus 0.05% slippage each side. Tax with today's rules for every year: 20% short-term, 12.5%
long-term above ₹1.25 lakh a year, 4% cess; STT is not deductible; losses set off and carried forward.
Fractional shares, dividends reinvested, NIFTY traded as if it were an index fund. Not investment or tax
advice.

## Quick start

```bash
uv sync
uv run python scripts/fetch_data.py          # Yahoo Finance -> data/prices.parquet
uv run mab run --symbol NIFTY --window 200   # one rule, after costs and tax
uv run mab report engine                     # also: rules. Charts -> out/, numbers printed
uv run python scripts/build_site.py          # dashboard -> site/index.html
uv run pytest
```

## Design

- `src/mab/engine.py`: the backtest loop, in rupees, one long-or-flat position.
- `src/mab/costs.py`, `src/mab/tax.py`: charges per order; Indian capital-gains tax per financial year.
- `src/mab/signals.py`: moving averages and the rules built on them.
- `src/mab/reports.py`: README findings, reproducible with `mab report <topic>`.
- `src/mab/site.py`: the dashboard, one static Plotly page; no server, no committed data.

MIT licence.
