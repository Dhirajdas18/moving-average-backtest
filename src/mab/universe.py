"""Survivorship bias: a point-in-time universe vs today's list applied to the past.

Data: a local NSE bhavcopy panel (set MAB_LAKE_DIR) with daily adj_close and turnover for every
stock that traded, including ones later delisted. Yahoo only has today's tickers, which is exactly
the bias being measured, so it can't be used here.

Portfolio maths (a bias study, simpler than the rupee engine): each member gets an equal sleeve at
each rebalance; a sleeve is in its stock or in cash (earning rf), using the signal from the previous
close and close-to-close returns; it pays `cost` each time it enters or leaves the stock. A stock
that stops trading leaves its sleeve in cash at its last price. Before tax.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def load_lake(lake_dir: str | Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(adjusted closes, turnover) as wide date x symbol frames from panel.parquet."""
    lake_dir = lake_dir or os.environ.get("MAB_LAKE_DIR")
    if not lake_dir:
        raise FileNotFoundError("set MAB_LAKE_DIR to a bhavcopy lake folder with panel.parquet")
    p = pd.read_parquet(Path(lake_dir) / "panel.parquet",
                        columns=["date", "symbol", "adj_close", "turnover"])
    wide = {f: p.pivot_table(index="date", columns="symbol", values=f) for f in
            ("adj_close", "turnover")}
    return wide["adj_close"].sort_index(), wide["turnover"].sort_index()


def members_at(turnover: pd.DataFrame, day: pd.Timestamp, n: int, window: int = 126) -> list[str]:
    """The `n` most-traded stocks by median daily turnover over the `window` days up to `day`."""
    past = turnover.loc[:day].iloc[-window:]
    med = past.median().dropna()
    return list(med.nlargest(n).index)


def portfolio_returns(prices: pd.DataFrame, rebalances: dict[pd.Timestamp, list[str]],
                      cost: float = 0.0016, rf: float = 0.065,
                      signal: pd.DataFrame | None = None) -> pd.Series:
    """Daily returns of equal sleeves per member, rebalanced on the given dates (see module doc)."""
    rets = prices.pct_change(fill_method=None)
    alive = prices.notna()
    days = prices.index
    reb = {d: m for d, m in rebalances.items()}
    value: dict[str, float] = {}
    invested: dict[str, bool] = {}
    out = np.zeros(len(days))
    total_prev = 1.0
    for k, day in enumerate(days):
        if day in reb:
            total = sum(value.values()) if value else total_prev
            for s in list(value):
                if s not in reb[day] and invested.get(s):
                    value[s] *= 1 - cost  # leaving the universe: sell
            total = sum(value.values()) if value else total
            members = [s for s in reb[day] if s in prices.columns]
            keep = {s: invested.get(s, False) for s in members}
            value = {s: total / len(members) for s in members}
            invested = keep
        if k > 0 and value:
            for s in value:
                if not alive.iloc[k - 1][s]:
                    invested[s] = False  # stopped trading earlier: stays in cash
                    want = False
                else:
                    want = bool(signal.iloc[k - 1][s]) if signal is not None else True
                if want != invested[s]:
                    value[s] *= 1 - cost
                    invested[s] = want
                r = rets.iloc[k][s]
                if invested[s] and not np.isnan(r):
                    value[s] *= 1 + r
                elif not invested[s]:
                    value[s] *= 1 + rf / TRADING_DAYS
        total = sum(value.values()) if value else total_prev
        out[k] = total / total_prev - 1 if k else 0.0
        total_prev = total
    return pd.Series(out, index=days)
