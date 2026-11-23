"""Walk-forward optimisation: choose parameters on past data only, trade them, repeat.

Each January the pair with the best Sharpe over the previous `train_years` is chosen and traded for
that calendar year. Stitching those years together gives the result someone following the process
would really have had, unlike the best pair picked with hindsight over the whole history.
"""

import numpy as np
import pandas as pd


def choose_by_year(returns: pd.DataFrame, train_years: int, first_test_year: int,
                   last_test_year: int | None = None) -> dict[int, tuple]:
    """For each test year, the column with the best Sharpe over the preceding `train_years`."""
    last = last_test_year or int(returns.index[-1].year)
    out = {}
    for year in range(first_test_year, last + 1):
        train = returns[(returns.index.year >= year - train_years) & (returns.index.year < year)]
        sharpe = train.mean() / train.std().replace(0, np.nan)
        out[year] = sharpe.idxmax()
    return out


def splice(targets: dict[tuple, pd.Series], choices: dict[int, tuple]) -> pd.Series:
    """One target series: in each year, the target of that year's chosen pair."""
    parts = []
    for year, pair in sorted(choices.items()):
        t = targets[pair]
        parts.append(t[t.index.year == year])
    return pd.concat(parts)
