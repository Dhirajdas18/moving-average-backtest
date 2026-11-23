import numpy as np
import pandas as pd
import pytest

from mab.universe import members_at, portfolio_returns


def _wide(values, start="2014-01-01"):
    idx = pd.bdate_range(start, periods=len(values))
    return pd.DataFrame(values, index=idx)


def test_members_use_only_past_turnover():
    idx = pd.bdate_range("2014-01-01", periods=200)
    t = pd.DataFrame({"A": 10.0, "B": 5.0, "C": 1.0}, index=idx)
    day = idx[150]
    assert members_at(t, day, 2, window=50) == ["A", "B"]
    t2 = t.copy()
    t2.loc[idx[151]:, "C"] = 1e9  # C becomes huge only in the future
    assert members_at(t2, day, 2, window=50) == ["A", "B"]


def test_buy_and_hold_sleeves_drift_and_a_delisted_stock_stops_at_its_last_price():
    # two stocks, equal start; A doubles, B halves then disappears (NaN)
    prices = pd.DataFrame({"A": [100.0, 150.0, 200.0, 200.0],
                           "B": [100.0, 50.0, np.nan, np.nan]},
                          index=pd.bdate_range("2014-01-01", periods=4))
    r = portfolio_returns(prices, {prices.index[0]: ["A", "B"]}, cost=0.0, rf=0.0)
    wealth = (1 + r).cumprod()
    assert wealth.iloc[-1] == pytest.approx(0.5 * 2.0 + 0.5 * 0.5)


def test_signal_moves_a_sleeve_to_cash_and_charges_costs():
    prices = pd.DataFrame({"A": [100.0, 100.0, 50.0, 50.0]},
                          index=pd.bdate_range("2014-01-01", periods=4))
    hold = pd.DataFrame({"A": [1, 0, 0, 0]}, index=prices.index)
    r = portfolio_returns(prices, {prices.index[0]: ["A"]}, cost=0.001, rf=0.0, signal=hold)
    wealth = (1 + r).cumprod()
    # held for day 1 (flat), out from day 2 (misses the halving): one entry and one exit cost
    assert wealth.iloc[-1] == pytest.approx((1 - 0.001) ** 2)
