"""Moving averages and rules built on them. Signal 1 = hold, 0 = cash, decided at the close."""

import pandas as pd


def sma(prices: pd.Series, window: int) -> pd.Series:
    """Simple moving average: the plain mean of the last `window` closes."""
    return prices.rolling(window).mean()


def ema(prices: pd.Series, window: int) -> pd.Series:
    """Exponential moving average with span `window` (weight 2/(window+1) on the newest close).

    Same average lag as an SMA of the same length ((window-1)/2 days), but it reacts to a new move
    sooner and forgets an old one gradually. Blank for the first window-1 days, like the SMA.
    """
    return prices.ewm(span=window, adjust=False).mean().where(
        prices.expanding().count() >= window)


MA = {"sma": sma, "ema": ema}


def above_ma(prices: pd.Series, window: int, kind: str = "sma") -> pd.Series:
    """Hold while the close is above its moving average; cash before the average exists."""
    ma = MA[kind](prices, window)
    return (prices > ma).astype(int).where(ma.notna(), 0)


def crossover(prices: pd.Series, fast: int, slow: int, kind: str = "sma") -> pd.Series:
    """Hold while the fast moving average is above the slow one (50/200 = the 'golden cross')."""
    f, s = MA[kind](prices, fast), MA[kind](prices, slow)
    return (f > s).astype(int).where(f.notna() & s.notna(), 0)
