"""Topic reports: build charts into out/ and return the key numbers quoted in the README."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mab import plots
from mab.costs import ZERODHA_DELIVERY, CostModel
from mab.data import INDEX, SYMBOLS, load_bars
from mab.engine import backtest
from mab.signals import above_ma
from mab.tax import INDIA_EQUITY

CAPITAL = 1_000_000.0
RF = 0.065
FREE = CostModel.free()


def cagr_of(value: float, idx: pd.DatetimeIndex, start: float = CAPITAL) -> float:
    return (value / start) ** (365.25 / (idx[-1] - idx[0]).days) - 1


def honesty_steps(bars: pd.DataFrame, target: pd.Series) -> dict[str, float]:
    """CAGR of the same rule as each layer of realism is added."""
    same_close = bars.assign(open=bars["close"].shift(1).fillna(bars["open"]))
    layers = {
        "trade at the signal close, free": (same_close, FREE, None),
        "trade at the next open": (bars, FREE, None),
        "+ costs and slippage": (bars, ZERODHA_DELIVERY, None),
        "+ capital-gains tax": (bars, ZERODHA_DELIVERY, INDIA_EQUITY),
    }
    return {name: cagr_of(backtest(b, target, c, t, CAPITAL, RF).liquidation_after_tax, bars.index)
            for name, (b, c, t) in layers.items()}


def report_engine(out_dir: Path) -> dict:
    """How much a 200-day moving-average rule loses as the backtest becomes realistic."""
    rows, hold = {}, {}
    for sym in [INDEX] + SYMBOLS:
        bars = load_bars(sym)
        rows[sym] = honesty_steps(bars, above_ma(bars["close"], 200))
        always = pd.Series(1, index=bars.index)
        hold[sym] = {
            "free": cagr_of(backtest(bars, always, FREE, None, CAPITAL, RF).liquidation_after_tax,
                            bars.index),
            "real": cagr_of(backtest(bars, always, ZERODHA_DELIVERY, INDIA_EQUITY, CAPITAL,
                                     RF).liquidation_after_tax, bars.index),
        }
    steps = pd.DataFrame(rows).T
    hold = pd.DataFrame(hold).T

    nifty = steps.loc[INDEX] * 100
    fig, ax = plt.subplots(figsize=(9, 4.6))
    colors = [plots.MUTED, plots.SERIES[0], plots.SERIES[0], plots.SERIES[0]]
    ax.bar(range(len(nifty)), nifty, color=colors, width=0.6)
    for i, v in enumerate(nifty):
        ax.text(i, v + 0.15, f"{v:.1f}%", ha="center", color=plots.TEXT, fontsize=10)
    ax.axhline(hold.loc[INDEX, "real"] * 100, color=plots.TEXT, lw=1.2, ls="--")
    ax.text(0.99, hold.loc[INDEX, "real"] * 100 + 0.25,
            f"buy and hold, after costs and tax: {hold.loc[INDEX, 'real']:.1%}",
            transform=ax.get_yaxis_transform(), ha="right", va="bottom", color=plots.TEXT_2,
            fontsize=9)
    ax.set_xticks(range(len(nifty)), [s.replace(" and ", " &\n").replace("trade at the ",
                                      "").replace(", free", "\n(free)") for s in nifty.index])
    ax.set_ylabel("growth, % a year (2013–2026)")
    ax.set_ylim(0, max(nifty.max(), hold.loc[INDEX, "real"] * 100) * 1.2)
    ax.grid(axis="x", visible=False)
    ax.set_title("NIFTY above its 200-day average: each layer of realism costs growth")
    plots.save(fig, out_dir, "engine_waterfall")

    drag = pd.DataFrame({
        "rule: costs": (steps["trade at the next open"] - steps["+ costs and slippage"]) * 100,
        "rule: tax": (steps["+ costs and slippage"] - steps["+ capital-gains tax"]) * 100,
        "hold: costs + tax": (hold["free"] - hold["real"]) * 100,
    })
    fig, ax = plt.subplots(figsize=(9, 4.6))
    y = np.arange(len(drag))
    ax.barh(y - 0.2, drag["rule: costs"], height=0.38, color=plots.SERIES[0], label="rule: costs")
    ax.barh(y - 0.2, drag["rule: tax"], left=drag["rule: costs"], height=0.38,
            color=plots.SERIES[1], label="rule: tax")
    ax.barh(y + 0.2, drag["hold: costs + tax"], height=0.38, color=plots.MUTED,
            label="buy and hold: costs + tax")
    ax.set_yticks(y, drag.index)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("growth lost, percentage points a year")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3)
    ax.set_title("Trading 4–5 times a year costs the rule 2–3× what buy and hold pays", pad=28)
    plots.save(fig, out_dir, "engine_drag")

    trades = {s: len(backtest(load_bars(s), above_ma(load_bars(s)["close"], 200)).trades)
              for s in [INDEX] + SYMBOLS}
    return {
        "CAGR by layer (200-day rule)": (steps * 100).round(2).to_dict("index"),
        "buy and hold CAGR free / real": (hold * 100).round(2).to_dict("index"),
        "drag, points a year": drag.round(2).to_dict("index"),
        "trades": trades,
    }


REPORTS = {"engine": report_engine}
