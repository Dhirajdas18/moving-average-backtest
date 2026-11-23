import numpy as np
import pandas as pd
import pytest

from mab.costs import ZERODHA_DELIVERY, CostModel
from mab.engine import backtest
from mab.tax import INDIA_EQUITY

FREE = CostModel.free()


def _bars(opens, closes, start="2020-01-01"):
    idx = pd.bdate_range(start, periods=len(opens))
    return pd.DataFrame({"open": opens, "close": closes}, index=idx, dtype=float)


def test_buy_happens_at_the_next_open_not_the_signal_close():
    bars = _bars([100, 100, 110, 120], [100, 105, 115, 120])
    target = pd.Series([0, 1, 1, 1], index=bars.index)  # decided at day 1's close
    out = backtest(bars, target, costs=FREE, tax=None, capital=1000, rf=0.0)
    first = out.trades.iloc[0]
    assert first["entry_date"] == bars.index[2] and first["entry_price"] == 110
    assert out.equity.iloc[-1] == pytest.approx(1000 * 120 / 110)


def test_overnight_gap_belongs_to_the_old_position():
    # flat at day 1's close, buy at day 2's open: the jump from 100 to 150 overnight is missed
    bars = _bars([100, 100, 150], [100, 100, 150])
    out = backtest(bars, pd.Series([0, 1, 1], index=bars.index), FREE, None, 1000, 0.0)
    assert out.equity.iloc[-1] == pytest.approx(1000)


def test_tomorrows_signal_cannot_change_today():
    rng = np.random.default_rng(0)
    p = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))
    bars = _bars(p * 0.999, p)
    t = pd.Series((np.arange(300) // 20) % 2, index=bars.index)
    t2 = t.copy()
    t2.iloc[-1] = 1 - t2.iloc[-1]
    a = backtest(bars, t, ZERODHA_DELIVERY, INDIA_EQUITY, 1_000_000, 0.065)
    b = backtest(bars, t2, ZERODHA_DELIVERY, INDIA_EQUITY, 1_000_000, 0.065)
    pd.testing.assert_series_equal(a.equity, b.equity)


def test_always_in_with_no_frictions_is_buy_at_first_open_and_hold():
    bars = _bars([100, 102, 99, 105], [101, 100, 104, 108])
    out = backtest(bars, pd.Series(1, index=bars.index), FREE, None, 1000, 0.0)
    assert out.equity.iloc[-1] == pytest.approx(1000 * 108 / 102)  # first fill is day 2's open


def test_round_trip_costs_and_slippage_are_charged_exactly():
    bars = _bars([100] * 5, [100] * 5)
    t = pd.Series([1, 1, 0, 0, 0], index=bars.index)
    c = ZERODHA_DELIVERY
    out = backtest(bars, t, c, None, 1_000_000, 0.0)
    buy_px, sell_px = 100 * (1 + c.slippage), 100 * (1 - c.slippage)
    # buy notional n solves n + buy_cost(n) = capital
    n = 1_000_000 / (1 + c.buy_cost(1e6) / 1e6)
    shares = n / buy_px
    proceeds = shares * sell_px
    assert out.equity.iloc[-1] == pytest.approx(proceeds - c.sell_cost(proceeds), rel=1e-9)


def test_cash_earns_the_risk_free_rate():
    bars = _bars([100] * 253, [100] * 253)
    out = backtest(bars, pd.Series(0, index=bars.index), FREE, None, 1000, 0.0504)
    assert out.equity.iloc[-1] == pytest.approx(1000 * (1 + 0.0504 / 252) ** 253, rel=1e-9)


def test_short_term_gain_is_taxed_at_the_start_of_the_next_financial_year():
    idx = pd.bdate_range("2023-01-02", "2023-05-31")
    px = np.where(idx < pd.Timestamp("2023-02-01"), 100.0, 150.0)
    bars = pd.DataFrame({"open": px, "close": px}, index=idx)
    t = pd.Series(np.where(idx < pd.Timestamp("2023-03-01"), 1, 0), index=idx)
    out = backtest(bars, t, FREE, INDIA_EQUITY, 1_000_000, 0.0)
    gain = 1_000_000 * 0.5
    assert out.tax_paid.sum() == pytest.approx(gain * 0.20 * 1.04)
    assert out.tax_paid[out.tax_paid > 0].index[0] >= pd.Timestamp("2023-04-01")
    assert out.equity.iloc[-1] == pytest.approx(1_500_000 - gain * 0.20 * 1.04)


def test_after_tax_liquidation_value_taxes_unrealised_gains_at_the_end():
    idx = pd.bdate_range("2023-01-02", periods=300)
    px = np.linspace(100, 200, 300)
    bars = pd.DataFrame({"open": px, "close": px}, index=idx)
    out = backtest(bars, pd.Series(1, index=idx), FREE, INDIA_EQUITY, 1_000_000, 0.0)
    assert out.liquidation_after_tax < out.equity.iloc[-1]
