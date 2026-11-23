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


def test_fractional_target_invests_that_share_of_equity():
    bars = _bars([100, 100, 200], [100, 100, 200])
    out = backtest(bars, pd.Series(0.5, index=bars.index), FREE, None, 1000, 0.0,
                   rebalance_band=1.0)  # never rebalance after the first buy
    assert out.position.iloc[1] == pytest.approx(0.5)
    assert out.equity.iloc[-1] == pytest.approx(500 * 2 + 500)


def test_drift_beyond_the_band_rebalances_back_to_target():
    bars = _bars([100, 100, 100, 200], [100, 100, 200, 200])  # doubles during day 2
    out = backtest(bars, pd.Series(0.5, index=bars.index), FREE, None, 1000, 0.0,
                   rebalance_band=0.05)
    # after the doubling the weight is 2/3 at the close; the next open trades back to 1/2
    assert out.position.iloc[2] == pytest.approx(2 / 3)
    assert out.position.iloc[3] == pytest.approx(0.5)


def test_partial_sells_use_the_oldest_lot_first_for_long_term_status():
    idx = pd.bdate_range("2022-01-03", "2023-06-30")
    px = np.where(idx < pd.Timestamp("2022-06-01"), 100.0, 200.0)
    bars = pd.DataFrame({"open": px, "close": px}, index=idx)
    t = pd.Series(1.0, index=idx)
    t[idx >= pd.Timestamp("2023-02-01")] = 0.5  # trim after more than a year: long-term
    out = backtest(bars, t, FREE, INDIA_EQUITY, 1_000_000, 0.0, rebalance_band=0.05)
    g = out.gains.loc[2022]  # FY 2022-23 (Feb 2023)
    assert g["short_term"] == pytest.approx(0.0)
    # half of the 2,000,000 position sold at 200 from shares bought at 100
    assert g["long_term"] == pytest.approx((200 - 100) * 1_000_000 / 200, rel=1e-6)


def test_open_trade_at_the_end_is_counted_once_with_tax_on():
    idx = pd.bdate_range("2023-01-02", periods=60)
    px = np.linspace(100, 110, 60)
    bars = pd.DataFrame({"open": px, "close": px}, index=idx)
    out = backtest(bars, pd.Series(1, index=idx), FREE, INDIA_EQUITY, 1_000_000, 0.0)
    t = out.trades.iloc[-1]
    assert t["open"]
    assert t["return"] == pytest.approx(110 / px[1] - 1, rel=1e-6)  # bought at day 1's open


def test_long_term_means_more_than_twelve_calendar_months():
    from mab.engine import is_long_term

    assert not is_long_term(pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-01"))  # 366 days
    assert is_long_term(pd.Timestamp("2024-01-01"), pd.Timestamp("2025-01-02"))


def test_cash_interest_is_taxed_at_the_slab_rate_each_april():
    idx = pd.bdate_range("2023-01-02", "2023-04-28")
    bars = pd.DataFrame({"open": 100.0, "close": 100.0}, index=idx)
    out = backtest(bars, pd.Series(0, index=idx), FREE, INDIA_EQUITY, 1_000_000, 0.0504)
    march = out.equity[out.equity.index < "2023-04-01"].iloc[-1]
    interest = march - 1_000_000
    assert out.tax_paid.sum() == pytest.approx(interest * 0.30 * 1.04, rel=1e-6)


def test_forced_sale_pays_the_tax_when_fully_invested():
    idx = pd.bdate_range("2023-01-02", "2023-05-31")
    px = np.where(idx < pd.Timestamp("2023-02-01"), 100.0, 150.0)
    bars = pd.DataFrame({"open": px, "close": px}, index=idx)
    t = pd.Series(1, index=idx)
    t[(idx >= "2023-03-01") & (idx < "2023-03-06")] = 0  # realise a short-term gain, buy back
    out = backtest(bars, t, FREE, INDIA_EQUITY, 1_000_000, 0.0)
    april = out.tax_paid[out.tax_paid > 0]
    assert len(april) == 1
    day = april.index[0]
    # equity drops by exactly the tax on the day it is paid (shares sold at the same price)
    before = out.equity[out.equity.index < day].iloc[-1]
    assert out.equity[day] == pytest.approx(before - april.iloc[0], rel=1e-9)
    assert out.position[day] == pytest.approx(1.0, abs=1e-9)


def test_short_term_loss_carries_into_the_next_year_through_the_engine():
    idx = pd.bdate_range("2022-01-03", "2023-12-29")
    px = np.select([idx < pd.Timestamp("2022-02-01"), idx < pd.Timestamp("2023-01-02")],
                   [100.0, 80.0], 120.0)
    bars = pd.DataFrame({"open": px, "close": px}, index=idx)
    t = pd.Series(0, index=idx)
    t[idx < pd.Timestamp("2022-03-01")] = 1   # buy at 100, sell at 80: loss in FY2021-22
    t[(idx >= "2022-12-01") & (idx < "2023-02-01")] = 1  # buy at 80, sell at 120 in FY2022-23
    out = backtest(bars, t, FREE, INDIA_EQUITY, 1_000_000, 0.0)
    loss = 1_000_000 * 0.2
    capital2 = 1_000_000 - loss
    gain = capital2 * 0.5
    assert out.gains.loc[2022, "tax"] == pytest.approx((gain - loss) * 0.20 * 1.04, rel=1e-6)
