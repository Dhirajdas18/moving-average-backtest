"""Topic reports: build charts into out/ and return the key numbers quoted in the README."""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mab import plots
from mab.costs import ZERODHA_DELIVERY, CostModel
from mab.data import INDEX, SYMBOLS, load_bars
from mab.engine import backtest
from mab.overfit import deflated_sharpe, pbo
from mab.signals import above_ma, crossover, sma
from mab.stats import split_growth, top_share, trade_stats
from mab.sweep import FAST, SLOW, crossover_grid
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


RULES = {
    "SMA-200 filter": lambda c: above_ma(c, 200),
    "EMA-200 filter": lambda c: above_ma(c, 200, "ema"),
    "SMA 50/200 cross": lambda c: crossover(c, 50, 200),
    "EMA 50/200 cross": lambda c: crossover(c, 50, 200, "ema"),
}
RULE_COLORS = {"SMA-200 filter": plots.SERIES[0], "EMA-200 filter": plots.SERIES[1],
               "SMA 50/200 cross": plots.SERIES[2], "EMA 50/200 cross": plots.SERIES[6],
               "buy and hold": plots.TEXT}


def _rule_stats(bars: pd.DataFrame, target: pd.Series) -> dict:
    res = backtest(bars, target)
    years = (bars.index[-1] - bars.index[0]).days / 365.25
    w = res.equity
    t = res.trades
    return {
        "CAGR": cagr_of(res.liquidation_after_tax, bars.index),
        "trades / yr": len(t) / years,
        "share under 30 days": float((t["days"] < 30).mean()) if len(t) else 0.0,
        "win rate": float((t["return"] > 0).mean()) if len(t) else 1.0,
        "max drawdown": float((w / w.cummax() - 1).min()),
        "time invested": float(res.position.gt(0).mean()),
    }


def report_rules(out_dir: Path) -> dict:
    """SMA vs EMA, price filter vs 50/200 crossover, at textbook settings (not tuned)."""
    rows = []
    for sym in [INDEX] + SYMBOLS:
        bars = load_bars(sym)
        for name, make in RULES.items():
            rows.append({"symbol": sym, "rule": name} | _rule_stats(bars, make(bars["close"])))
        rows.append({"symbol": sym, "rule": "buy and hold"}
                    | _rule_stats(bars, pd.Series(1, index=bars.index)))
    df = pd.DataFrame(rows)
    cagr = df.pivot(index="symbol", columns="rule", values="CAGR").reindex([INDEX] + SYMBOLS)
    avg = df.groupby("rule").mean(numeric_only=True).reindex(list(RULE_COLORS))

    c = load_bars(INDEX)["close"]
    span = c["2019-10-01":"2020-10-31"]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.plot(span.index, span, color=plots.TEXT, lw=1.6, label="NIFTY")
    for name, series, color in (("200-day SMA", sma(c, 200), plots.SERIES[0]),
                                ("50-day SMA", sma(c, 50), plots.SERIES[2])):
        ax.plot(span.index, series[span.index], color=color, lw=1.4, label=name)
    peak = c["2020-01-01":"2020-03-31"].idxmax()
    bottom = c["2020-02-01":"2020-06-30"].idxmin()
    lag = {}
    for name, marker in (("SMA-200 filter", "o"), ("SMA 50/200 cross", "s")):
        ch = RULES[name](c).diff()
        out = ch[(ch < 0) & (ch.index >= peak - pd.Timedelta(days=60))].index[0]
        back = ch[(ch > 0) & (ch.index > bottom)].index[0]
        lag[name] = {"exit": f"{out:%Y-%m-%d} ({c[out] / c[peak] - 1:+.0%} from peak)",
                     "re-entry": f"{back:%Y-%m-%d} ({c[back] / c[bottom] - 1:+.0%} from bottom)"}
        for day, verb in ((out, "sell"), (back, "buy")):
            ax.scatter(day, c[day], marker=marker, s=60, zorder=4, color=RULE_COLORS[name],
                       edgecolor=plots.SURFACE, linewidth=1.5)
            ax.annotate(f"{name.split()[1] if 'cross' in name else 'filter'} {verb}",
                        (day, c[day]), xytext=(6, -14 if verb == "sell" else 8),
                        textcoords="offset points", fontsize=8, color=plots.TEXT_2)
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%b %Y"))
    ax.legend(loc="lower right")
    ax.set_title("2020: the filter sold early; the 50/200 cross sold four days before the bottom")
    plots.save(fig, out_dir, "rules_2020")

    fig, ax = plt.subplots(figsize=(9, 4.6))
    y = np.arange(len(cagr))
    for rule in RULE_COLORS:
        ax.scatter(cagr[rule] * 100, y, s=70 if rule != "buy and hold" else 90,
                   color=RULE_COLORS[rule], marker="D" if rule == "buy and hold" else "o",
                   label=rule, zorder=3, edgecolor=plots.SURFACE, linewidth=1.2)
    ax.set_yticks(y, cagr.index)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("growth, % a year after costs and tax (2013–2026)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=3, fontsize=8)
    ax.set_title("Buy and hold won on 5 of 6 series; no rule style won consistently", pad=40)
    plots.save(fig, out_dir, "rules_cagr")

    fig, axes = plt.subplots(1, 2, figsize=(9, 4.6))
    names = list(RULES)
    panels = ((axes[0], "trades / yr", "round trips a year", 1),
              (axes[1], "share under 30 days", "trades lasting under 30 days, %", 100))
    for ax, col, title, scale in panels:
        vals = avg.loc[names, col] * scale
        ax.barh(names, vals, color=[RULE_COLORS[n] for n in names], height=0.6)
        for i, v in enumerate(vals):
            ax.text(v, i, f" {v:.1f}" if scale == 1 else f" {v:.0f}%", va="center", fontsize=9,
                    color=plots.TEXT_2)
        ax.set_title(title, fontsize=10, fontweight="normal", color=plots.TEXT_2)
        ax.grid(axis="y", visible=False)
        ax.invert_yaxis()
    axes[1].set_yticks([])
    fig.suptitle("Price filters whipsaw: most of their trades reverse within a month", x=0.06,
                 ha="left", fontsize=13, fontweight="semibold", color=plots.TEXT)
    plots.save(fig, out_dir, "rules_whipsaw")

    beats = {
        "EMA > SMA (filter)": int((cagr["EMA-200 filter"] > cagr["SMA-200 filter"]).sum()),
        "EMA > SMA (cross)": int((cagr["EMA 50/200 cross"] > cagr["SMA 50/200 cross"]).sum()),
        "cross > filter (SMA)": int((cagr["SMA 50/200 cross"] > cagr["SMA-200 filter"]).sum()),
        "cross > filter (EMA)": int((cagr["EMA 50/200 cross"] > cagr["EMA-200 filter"]).sum()),
        "any rule > buy and hold": int((cagr[names].max(axis=1) > cagr["buy and hold"]).sum()),
    }
    return {
        "CAGR after costs and tax": (cagr * 100).round(2).to_dict("index"),
        "averages across six series": avg.round(3).to_dict("index"),
        "series won (of 6)": beats,
        "NIFTY 2020": lag,
    }


def report_trades(out_dir: Path) -> dict:
    """Trades: win rate vs payoff, holding periods, profit concentration, tax mix."""
    rows, split = {}, {}
    for sym in [INDEX] + SYMBOLS:
        bars = load_bars(sym)
        for rule in ("SMA-200 filter", "SMA 50/200 cross"):
            res = backtest(bars, RULES[rule](bars["close"]))
            st = trade_stats(res.trades)
            g = res.gains
            pos_st, pos_lt = g["short_term"].clip(lower=0).sum(), g["long_term"].clip(lower=0).sum()
            rows[(sym, rule)] = st | {
                "top-3 share of profit": top_share(res.trades, 3),
                "short-term share of gains": pos_st / (pos_st + pos_lt) if pos_st + pos_lt else 0,
            }
            if rule == "SMA-200 filter":
                best, rest = split_growth(res.trades, 3)
                split[sym] = {"best 3 trades": best, "all other trades": rest,
                              "count": len(res.trades)}
    table = pd.DataFrame(rows).T

    bars = load_bars(INDEX)
    t = backtest(bars, RULES["SMA-200 filter"](bars["close"])).trades
    st = trade_stats(t)
    fig, ax = plt.subplots(figsize=(9, 4.6))
    r = t["return"] * 100
    bins = np.arange(np.floor(r.min() / 2) * 2, r.max() + 4, 2)
    ax.hist(r[r <= 0], bins=bins, color=plots.SERIES[7], alpha=0.85, label="losing trades")
    ax.hist(r[r > 0], bins=bins, color=plots.SERIES[0], alpha=0.9, label="winning trades")
    ax.axvline(0, color=plots.TEXT_2, lw=0.8)
    ax.set_xlabel("return per trade after costs, %")
    ax.set_ylabel("number of trades")
    ax.legend(loc="upper right")
    ax.text(0.98, 0.70, f"{len(t)} trades\nwin rate {st['win rate']:.0%}\n"
            f"avg win {st['avg win']:+.1%}, avg loss {st['avg loss']:+.1%}\n"
            f"payoff {st['payoff ratio']:.1f}×, "
            f"break-even win rate {st['break-even win rate']:.0%}",
            transform=ax.transAxes, ha="right", va="top", fontsize=9, color=plots.TEXT_2)
    ax.set_title("NIFTY 200-day filter: many small losses, a few large wins")
    plots.save(fig, out_dir, "trades_hist")

    sp = pd.DataFrame(split).T
    fig, ax = plt.subplots(figsize=(9, 4.6))
    y = np.arange(len(sp))
    ax.barh(y, sp["best 3 trades"] * 100, color=plots.SERIES[0], height=0.6,
            label="best 3 trades alone")
    ax.barh(y, sp["all other trades"] * 100, color=plots.SERIES[7], height=0.6,
            label="all other trades, compounded")
    for i, row in enumerate(sp.itertuples()):
        ax.text(row[1] * 100, i, f"  3 of {int(row[3])} trades", ha="left", va="center",
                fontsize=8, color=plots.TEXT_2)
    ax.set_xlim(right=sp["best 3 trades"].max() * 100 * 1.25)
    ax.axvline(0, color=plots.TEXT_2, lw=0.8)
    ax.set_yticks(y, sp.index)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("compounded return, % (after costs)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    ax.set_title("200-day filter: three trades made the money; the rest lost it", pad=28)
    plots.save(fig, out_dir, "trades_concentration")

    cols = ["trades", "win rate", "payoff ratio", "break-even win rate", "expectancy",
            "profit factor", "median days, winners", "median days, losers",
            "top-3 share of profit", "short-term share of gains"]
    return {"trade stats": table[cols].astype(float).round(3).to_dict("index"),
            "filter best-3 alone vs rest compounded": sp.round(3).to_dict("index")}


def _hold_sharpe(bars: pd.DataFrame) -> float:
    r = bars["close"].pct_change().iloc[max(SLOW):] - RF / 252
    return float(r.mean() / r.std() * np.sqrt(252))


def report_sweep(out_dir: Path) -> dict:
    """Every fast/slow SMA crossover: heatmap, deflated Sharpe of the best, overfitting odds."""
    rows, grids = {}, {}
    for sym in [INDEX] + SYMBOLS:
        bars = load_bars(sym)
        m, r = crossover_grid(bars)
        daily = (r.mean() / r.std()).to_numpy()
        best = m["sharpe"].idxmax()
        rows[sym] = {"best pair": f"{best[0]}/{best[1]}", "best Sharpe": m["sharpe"].max(),
                     "median Sharpe": m["sharpe"].median(),
                     "buy-and-hold Sharpe": _hold_sharpe(bars),
                     "deflated Sharpe": deflated_sharpe(r[best], daily),
                     "no-deflation PSR": deflated_sharpe(
                         r[best], np.array([r[best].mean() / r[best].std()])),
                     "PBO": pbo(r, 10),
                     "pairs": len(m)}
        grids[sym] = m["sharpe"]
    table = pd.DataFrame(rows).T

    g = grids[INDEX].unstack("slow").reindex(index=list(FAST), columns=list(SLOW))
    hold = table.loc[INDEX, "buy-and-hold Sharpe"]
    lim = float(np.nanmax(np.abs(g.to_numpy() - hold)))
    cmap = plt.matplotlib.colors.LinearSegmentedColormap.from_list(
        "div", [plots.SERIES[7], "#f1f0ec", plots.SERIES[0]])
    fig, ax = plt.subplots(figsize=(9, 4.6))
    ax.imshow(g.to_numpy(), cmap=cmap, vmin=hold - lim, vmax=hold + lim, aspect="auto")
    for (i, j), v in np.ndenumerate(g.to_numpy()):
        if not np.isnan(v):
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if abs(v - hold) > lim * 0.6 else plots.TEXT)
    bi, bj = list(FAST).index(int(table.loc[INDEX, "best pair"].split("/")[0])), \
        list(SLOW).index(int(table.loc[INDEX, "best pair"].split("/")[1]))
    ax.add_patch(plt.Rectangle((bj - 0.5, bi - 0.5), 1, 1, fill=False, ec=plots.TEXT, lw=2))
    ax.set_xticks(range(len(SLOW)), SLOW)
    ax.set_yticks(range(len(FAST)), FAST)
    ax.set_xlabel("slow average, days")
    ax.set_ylabel("fast average, days")
    ax.tick_params(length=0)
    ax.grid(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.set_title(f"NIFTY: Sharpe of 40 crossovers (blue beats buy and hold's {hold:.2f})")
    plots.save(fig, out_dir, "sweep_heatmap")

    fig, axes = plt.subplots(1, 2, figsize=(9, 4.6), sharey=True)
    y = np.arange(len(table))
    for ax, col, line, title, fmt in (
            (axes[0], "deflated Sharpe", 0.95, "deflated Sharpe of the best pair", "{:.2f}"),
            (axes[1], "PBO", 0.5, "probability of backtest overfitting", "{:.2f}")):
        vals = table[col].astype(float)
        ax.barh(y, vals, color=plots.SERIES[0] if col != "PBO" else plots.SERIES[7], height=0.6)
        for i, v in enumerate(vals):
            ax.text(v, i, " " + fmt.format(v), va="center", fontsize=9, color=plots.TEXT_2)
        ax.axvline(line, color=plots.TEXT, lw=1, ls="--")
        ax.text(line, len(table) - 0.45, f" {line}", fontsize=8, color=plots.TEXT_2, va="top")
        ax.set_xlim(0, 1.12)
        ax.set_title(title, fontsize=10, fontweight="normal", color=plots.TEXT_2)
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(y, table.index)
    axes[0].invert_yaxis()
    fig.suptitle("No best pair clears 0.95; overfitting odds are 50% or more on 5 of 6", x=0.06,
                 ha="left", fontsize=13, fontweight="semibold", color=plots.TEXT)
    plots.save(fig, out_dir, "sweep_overfit")

    return {"per series": table.round(3).to_dict("index"),
            "best beat buy and hold (in sample)":
                int((table["best Sharpe"] > table["buy-and-hold Sharpe"]).sum()),
            "median pair beat buy and hold":
                int((table["median Sharpe"] > table["buy-and-hold Sharpe"]).sum())}


REPORTS = {"engine": report_engine, "rules": report_rules, "trades": report_trades,
           "sweep": report_sweep}
