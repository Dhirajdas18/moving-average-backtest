import pandas as pd
import pytest

from mab.data import load_bars


def test_load_bars_scales_open_by_the_same_factor_as_close(tmp_path):
    idx = pd.DatetimeIndex(["2020-01-02", "2020-01-01", "2020-01-03"], name="date")
    cols = pd.MultiIndex.from_tuples(
        [("open", "ITC"), ("close", "ITC"), ("adj_close", "ITC")], names=["field", "symbol"])
    df = pd.DataFrame([[101.0, 102.0, 51.0], [99.0, 100.0, 50.0], [103.0, None, None]],
                      index=idx, columns=cols)
    path = tmp_path / "p.parquet"
    df.to_parquet(path)
    bars = load_bars("ITC", path=path)
    assert list(bars.columns) == ["open", "close"]
    assert bars.index.is_monotonic_increasing and len(bars) == 2  # row with no close dropped
    assert bars["close"].tolist() == [50.0, 51.0]
    assert bars["open"].iloc[0] == pytest.approx(99.0 * 0.5)


def test_load_bars_unknown_symbol(tmp_path):
    cols = pd.MultiIndex.from_tuples([("open", "ITC"), ("close", "ITC"), ("adj_close", "ITC")],
                                     names=["field", "symbol"])
    df = pd.DataFrame([[1.0, 1.0, 1.0]], columns=cols,
                      index=pd.DatetimeIndex(["2020-01-01"], name="date"))
    df.to_parquet(tmp_path / "p.parquet")
    with pytest.raises(KeyError):
        load_bars("TCS", path=tmp_path / "p.parquet")
