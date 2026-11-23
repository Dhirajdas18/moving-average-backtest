"""Run a whole grid of moving-average rules and collect what's needed to judge overfitting."""

import numpy as np
import pandas as pd

from mab.costs import ZERODHA_DELIVERY
from mab.engine import backtest
from mab.signals import crossover

FAST = (5, 10, 20, 30, 50, 75, 100)
SLOW = (20, 50, 100, 150, 200, 250, 300)
TRADING_DAYS = 252


def crossover_grid(bars: pd.DataFrame, fast=FAST, slow=SLOW, kind: str = "sma",
                   rf: float = 0.065) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Backtest every fast < slow crossover after costs (before tax, so daily returns are clean).

    Returns (metrics per pair, daily excess returns with one column per pair). Days before the
    slowest average exists are dropped so every pair is judged on the same dates.
    """
    rows, rets = {}, {}
    for f in fast:
        for s in slow:
            if f >= s:
                continue
            res = backtest(bars, crossover(bars["close"], f, s, kind), ZERODHA_DELIVERY, None,
                           1_000_000, rf)
            r = res.returns - rf / TRADING_DAYS
            rets[(f, s)] = r
            years = (bars.index[-1] - bars.index[0]).days / 365.25
            rows[(f, s)] = {"sharpe": float(r.iloc[max(slow):].mean() / r.iloc[max(slow):].std()
                                            * np.sqrt(TRADING_DAYS)),
                            "trades / yr": len(res.trades) / years}
    metrics = pd.DataFrame(rows).T
    metrics.index.names = ["fast", "slow"]
    returns = pd.DataFrame(rets).iloc[max(slow):]
    returns.columns = metrics.index
    return metrics, returns
