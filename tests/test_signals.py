import numpy as np
import pandas as pd

from mab.signals import above_ma, sma


def test_sma_is_trailing_mean_with_warmup():
    p = pd.Series([1.0, 2, 3, 4, 5])
    assert sma(p, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    assert sma(p, 3).iloc[:2].isna().all()


def test_above_ma_is_flat_during_warmup_and_uses_only_the_past():
    p = pd.Series(np.r_[np.ones(5) * 10, [20, 5]])
    sig = above_ma(p, 3)
    assert sig.iloc[:2].tolist() == [0, 0]  # no average yet
    assert sig.iloc[5] == 1 and sig.iloc[6] == 0
    q = p.copy()
    q.iloc[-1] = 100  # change the last day only
    assert above_ma(q, 3).iloc[:-1].equals(sig.iloc[:-1])


def test_ema_weights_recent_prices_more_and_has_warmup():
    from mab.signals import ema

    p = pd.Series([10.0] * 10 + [20.0])
    e = ema(p, 5)
    assert e.iloc[:4].isna().all()  # needs `window` prices before it counts
    assert 10 < e.iloc[-1] < 20
    assert e.iloc[-1] > p.rolling(5).mean().iloc[-1]  # reacts more to the jump than SMA


def test_same_span_sma_and_ema_have_the_same_average_lag():
    from mab.signals import ema

    n = 21
    alpha = 2 / (n + 1)
    assert np.isclose((1 - alpha) / alpha, (n - 1) / 2)  # EMA centre of mass = SMA centre
    assert ema(pd.Series(np.ones(30)), n).dropna().eq(1).all()


def test_crossover_holds_when_fast_average_is_above_slow_and_ignores_the_future():
    from mab.signals import crossover

    p = pd.Series(np.r_[np.linspace(10, 5, 30), np.linspace(5, 15, 30)])
    sig = crossover(p, 3, 10)
    assert sig.iloc[:9].eq(0).all()  # slow average not ready
    assert sig.iloc[20] == 0 and sig.iloc[-1] == 1
    q = p.copy()
    q.iloc[-1] = 0
    assert crossover(q, 3, 10).iloc[:-1].equals(sig.iloc[:-1])


def test_above_ma_can_use_ema():
    p = pd.Series(np.r_[np.ones(10) * 10, [11.0]])
    assert above_ma(p, 5, kind="ema").iloc[-1] == 1
