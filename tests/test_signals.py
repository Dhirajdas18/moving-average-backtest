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
