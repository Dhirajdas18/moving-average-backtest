import numpy as np
import pandas as pd
import pytest

from mab.overfit import deflated_sharpe, expected_max_sharpe, pbo


def _noise(n_days=2520, n_strats=40, seed=0, edge=None):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 0.01, (n_days, n_strats))
    if edge is not None:
        x[:, 0] += edge
    return pd.DataFrame(x, index=pd.bdate_range("2010-01-01", periods=n_days))


def test_expected_max_sharpe_grows_with_the_number_of_trials():
    assert expected_max_sharpe(1, 0.01) == 0
    assert 0 < expected_max_sharpe(10, 0.01) < expected_max_sharpe(100, 0.01)


def test_deflated_sharpe_of_one_trial_is_the_plain_probability_sharpe_is_positive():
    r = _noise(n_strats=1, edge=0.0008)[0]
    one = deflated_sharpe(r, trial_sharpes=np.array([r.mean() / r.std()]))
    many = deflated_sharpe(r, trial_sharpes=np.r_[r.mean() / r.std(), np.linspace(-0.03, 0.03, 99)])
    assert one > 0.9  # a real 0.08% daily edge over 10 years
    assert many < one  # the same result counts for less when it was the best of 100 tries


def test_best_of_pure_noise_is_not_significant_after_deflation():
    m = _noise(n_strats=50, seed=3)
    sr = (m.mean() / m.std()).to_numpy()
    best = m.iloc[:, int(np.argmax(sr))]
    assert deflated_sharpe(best, sr) < 0.9


def test_pbo_averages_about_half_for_noise_and_is_near_zero_for_a_real_edge():
    # one sample's PBO is itself noisy (0.1-0.95 for noise), so average several
    noise = np.mean([pbo(_noise(seed=s, n_days=1260, n_strats=20), n_blocks=10)
                     for s in range(12)])
    assert 0.4 < noise < 0.7
    assert pbo(_noise(seed=2, edge=0.002), n_blocks=10) < 0.05


def test_pbo_rejects_odd_block_counts():
    with pytest.raises(ValueError):
        pbo(_noise(), n_blocks=9)
