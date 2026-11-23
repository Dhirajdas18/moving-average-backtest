"""Trade-level statistics: what a rule's individual trades look like, not just its equity curve."""

import numpy as np
import pandas as pd


def trade_stats(trades: pd.DataFrame) -> dict:
    """Win rate, payoff, expectancy and friends from a trades table (`return`, `days` columns).

    payoff ratio = average win / average loss (size). The break-even win rate, 1 / (1 + payoff), is
    the win rate at which wins and losses cancel: a rule can win rarely and still make money if its
    wins are big enough.
    """
    r = trades["return"]
    wins, losses = r[r > 0], r[r <= 0]
    payoff = wins.mean() / -losses.mean() if len(wins) and len(losses) else np.nan
    pnl = trades["proceeds"] - trades["invested"]
    return {
        "trades": len(r),
        "win rate": float((r > 0).mean()) if len(r) else np.nan,
        "avg win": float(wins.mean()) if len(wins) else np.nan,
        "avg loss": float(losses.mean()) if len(losses) else np.nan,
        "payoff ratio": float(payoff),
        "break-even win rate": float(1 / (1 + payoff)) if payoff == payoff else np.nan,
        "expectancy": float(r.mean()) if len(r) else np.nan,
        "profit factor": float(pnl[pnl > 0].sum() / -pnl[pnl <= 0].sum())
        if (pnl <= 0).any() else np.inf,
        "median days, winners": float(trades.loc[r > 0, "days"].median())
        if len(wins) else np.nan,
        "median days, losers": float(trades.loc[r <= 0, "days"].median())
        if len(losses) else np.nan,
    }


def top_share(trades: pd.DataFrame, k: int) -> float:
    """Share of the strategy's compounded growth that came from its `k` best trades.

    Measured in log returns so trade size doesn't matter (later trades are bigger in rupees only
    because the account grew). Above 1 means all the other trades together lost money.
    """
    g = np.log1p(trades["return"]).sort_values(ascending=False)
    return float(g.iloc[:k].sum() / g.sum())


def split_growth(trades: pd.DataFrame, k: int) -> tuple[float, float]:
    """Compounded return of the `k` best trades alone, and of all the other trades together."""
    g = np.log1p(trades["return"]).sort_values(ascending=False)
    return float(np.expm1(g.iloc[:k].sum())), float(np.expm1(g.iloc[k:].sum()))
