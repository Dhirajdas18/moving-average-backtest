import numpy as np
import pandas as pd

from mab.walkforward import choose_by_year, splice


def _matrix(seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", "2016-12-31")
    cols = pd.MultiIndex.from_tuples([(5, 20), (10, 50), (50, 200)], names=["fast", "slow"])
    return pd.DataFrame(rng.normal(0, 0.01, (len(idx), 3)), index=idx, columns=cols)


def test_choice_is_the_best_sharpe_in_the_training_window():
    m = _matrix()
    m.loc["2011":"2013", (10, 50)] += 0.003  # clearly best in 2011-2013
    choices = choose_by_year(m, train_years=3, first_test_year=2014)
    assert choices[2014] == (10, 50)


def test_a_years_choice_ignores_that_year_and_later():
    m = _matrix(1)
    base = choose_by_year(m, train_years=3, first_test_year=2014)
    m2 = m.copy()
    m2.loc["2015":, (50, 200)] += 0.05  # make the future spectacular for one pair
    after = choose_by_year(m2, train_years=3, first_test_year=2014)
    assert after[2014] == base[2014] and after[2015] == base[2015]


def test_splice_uses_each_years_chosen_target():
    idx = pd.bdate_range("2014-01-01", "2015-12-31")
    targets = {(5, 20): pd.Series(1, index=idx), (10, 50): pd.Series(0, index=idx)}
    out = splice(targets, {2014: (5, 20), 2015: (10, 50)})
    assert out["2014"].eq(1).all() and out["2015"].eq(0).all()


def test_walk_forward_run_refuses_too_little_history():
    import pytest

    from mab.reports import walk_forward_run

    idx = pd.bdate_range("2018-01-01", periods=600)
    c = pd.Series(np.linspace(100, 150, 600), index=idx)
    with pytest.raises(ValueError, match="not enough history"):
        walk_forward_run(pd.DataFrame({"open": c, "close": c}))
