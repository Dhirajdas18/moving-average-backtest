"""How much of a backtest's best result is luck from trying many variants.

- Deflated Sharpe ratio (Bailey & López de Prado, 2014): the probability that the best strategy's
  true Sharpe ratio is above zero, after raising the bar for the number of variants tried and for
  skew and fat tails.
- Probability of backtest overfitting (Bailey, Borwein, López de Prado & Zhu, 2017), by
  combinatorially symmetric cross-validation: how often the variant that looks best on one half of
  the data ranks below the median on the other half. One sample's PBO is itself noisy.

All Sharpe ratios here are per period (daily), not annualised.
"""

from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats

EULER = 0.5772156649


def expected_max_sharpe(n_trials: int, sharpe_std: float) -> float:
    """Sharpe ratio the best of `n_trials` unskilled variants would reach by luck alone."""
    if n_trials <= 1:
        return 0.0
    z1 = stats.norm.ppf(1 - 1 / n_trials)
    z2 = stats.norm.ppf(1 - 1 / (n_trials * np.e))
    return float(sharpe_std * ((1 - EULER) * z1 + EULER * z2))


def deflated_sharpe(best: pd.Series, trial_sharpes: np.ndarray) -> float:
    """Probability the chosen strategy's true daily Sharpe is above the luck threshold.

    `best`: daily (excess) returns of the chosen variant. `trial_sharpes`: daily Sharpe of every
    variant tried, the chosen one included.
    """
    x = best.dropna()
    sr = x.mean() / x.std()
    sr0 = expected_max_sharpe(len(trial_sharpes), float(np.std(trial_sharpes, ddof=1))
                              if len(trial_sharpes) > 1 else 0.0)
    skew, kurt = stats.skew(x), stats.kurtosis(x, fisher=False)
    denom = np.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr**2)
    return float(stats.norm.cdf((sr - sr0) * np.sqrt(len(x) - 1) / denom))


def pbo(returns: pd.DataFrame, n_blocks: int = 10) -> float:
    """Share of splits where the in-sample winner ranks at or below the median out of sample.

    The rows (days) are cut into `n_blocks` equal blocks; every way of choosing half of them as the
    in-sample set is tried, the rest being out of sample. About 0.5 means picking the best variant
    was no better than picking at random.
    """
    if n_blocks % 2:
        raise ValueError("n_blocks must be even")
    x = returns.dropna().to_numpy()
    blocks = np.array_split(np.arange(len(x)), n_blocks)
    sums = np.array([x[b].sum(axis=0) for b in blocks])
    sq = np.array([(x[b] ** 2).sum(axis=0) for b in blocks])
    counts = np.array([len(b) for b in blocks])
    below = 0
    combos = list(combinations(range(n_blocks), n_blocks // 2))
    for ins in combos:
        out = [b for b in range(n_blocks) if b not in ins]

        def sharpe(idx):
            n = counts[list(idx)].sum()
            m = sums[list(idx)].sum(axis=0) / n
            v = sq[list(idx)].sum(axis=0) / n - m**2
            return m / np.sqrt(np.maximum(v, 1e-18))

        winner = int(np.argmax(sharpe(ins)))
        oos = sharpe(out)
        rank = (oos < oos[winner]).sum() + 0.5 * ((oos == oos[winner]).sum() - 1)
        omega = (rank + 1) / (len(oos) + 1)  # relative rank in (0, 1)
        below += omega <= 0.5
    return below / len(combos)
