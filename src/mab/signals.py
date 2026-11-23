"""Moving averages and rules built on them. Signal 1 = hold, 0 = cash, decided at the close."""

import pandas as pd


def sma(prices: pd.Series, window: int) -> pd.Series:
    """Simple moving average: the plain mean of the last `window` closes."""
    return prices.rolling(window).mean()


def above_ma(prices: pd.Series, window: int) -> pd.Series:
    """Hold while the close is above its `window`-day SMA; cash before the average exists."""
    ma = sma(prices, window)
    return (prices > ma).astype(int).where(ma.notna(), 0)
