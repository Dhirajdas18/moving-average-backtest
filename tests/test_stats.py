import numpy as np
import pandas as pd
import pytest

from mab.stats import top_share, trade_stats


def _trades(rets, days=None):
    days = days or [10] * len(rets)
    return pd.DataFrame({"return": rets, "days": days, "invested": 100.0,
                         "proceeds": [100 * (1 + r) for r in rets]})


def test_trade_stats_on_a_known_set():
    t = _trades([0.30, -0.05, -0.05, -0.05, 0.10], days=[200, 5, 8, 12, 90])
    s = trade_stats(t)
    assert s["trades"] == 5
    assert s["win rate"] == pytest.approx(0.4)
    assert s["avg win"] == pytest.approx(0.20) and s["avg loss"] == pytest.approx(-0.05)
    assert s["payoff ratio"] == pytest.approx(4.0)
    assert s["break-even win rate"] == pytest.approx(1 / (1 + 4.0))
    assert s["expectancy"] == pytest.approx(np.mean([0.30, -0.05, -0.05, -0.05, 0.10]))
    assert s["profit factor"] == pytest.approx(40 / 15)
    assert s["median days, winners"] == 145 and s["median days, losers"] == 8


def test_top_share_is_the_fraction_of_compounded_growth_from_the_best_trades():
    t = _trades([0.50, 0.10, -0.10, 0.05])
    g = np.log1p([0.50, 0.10, -0.10, 0.05])
    assert top_share(t, 1) == pytest.approx(g[0] / g.sum())


def test_split_growth_best_alone_and_the_rest_together():
    from mab.stats import split_growth

    best, rest = split_growth(_trades([0.50, 0.10, -0.10, 0.05]), 1)
    assert best == pytest.approx(0.50) and rest == pytest.approx(1.10 * 0.90 * 1.05 - 1)


def test_engine_records_gains_by_financial_year_split_short_and_long():
    from mab.costs import CostModel
    from mab.engine import backtest
    from mab.tax import INDIA_EQUITY

    idx = pd.bdate_range("2022-01-03", "2023-06-30")
    px = np.where(idx < pd.Timestamp("2022-02-01"), 100.0, 120.0)
    bars = pd.DataFrame({"open": px, "close": px}, index=idx)
    # hold Jan 2022 -> sell Mar 2022 (short-term), buy again, sell Apr 2023 (long-term, > 365 days)
    t = pd.Series(0, index=idx)
    t[(idx >= "2022-01-03") & (idx < "2022-03-01")] = 1
    t[(idx >= "2022-03-03") & (idx < "2023-04-05")] = 1
    out = backtest(bars, t, CostModel.free(), INDIA_EQUITY, 1_000_000, 0.0)
    g = out.gains
    assert list(g.columns) == ["short_term", "long_term", "tax"]
    assert g.loc[2021, "short_term"] == pytest.approx(200_000)  # FY 2021-22 (Jan-Mar 2022)
    assert g.loc[2021, "tax"] == pytest.approx(200_000 * 0.20 * 1.04)
