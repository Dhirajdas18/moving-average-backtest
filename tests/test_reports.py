import numpy as np
import pandas as pd

from mab.reports import WARMUP, evaluated
from mab.signals import above_ma


def test_rule_and_buy_and_hold_start_trading_on_the_same_day():
    idx = pd.bdate_range("2013-01-01", periods=900)
    c = pd.Series(100 * np.exp(np.linspace(0, 0.5, 900)), index=idx)
    bars = pd.DataFrame({"open": c, "close": c})
    rule = evaluated(bars, above_ma(c, 200))
    hold = evaluated(bars, pd.Series(1, index=idx))
    assert rule.equity.index[0] == hold.equity.index[0] == idx[WARMUP]
