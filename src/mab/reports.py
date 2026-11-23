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
from mab.walkforward import choose_by_year, splice

CAPITAL = 1_000_000.0
RF = 0.065
FREE = CostModel.free()


def _label_ends(ax, lines: dict, colors: dict, gap: float | None = None) -> None:
    """Direct labels at each line's right end, nudged apart so none overlap."""
    ends = {k: float(v.iloc[-1]) for k, v in lines.items()}
    gap = gap if gap is not None else (max(ends.values()) - min(ends.values()) + 1e-9) * 0.08 + 0.3
    floor = -1e18
    for name in sorted(ends, key=ends.get):
        floor = max(ends[name], floor + gap)
        plots.label_line_end(ax, lines[name].index[-1], floor, name, colors[name])


WARMUP = 300  # trading days before any comparison starts: the slowest average (300) must exist


def _cagr_run(res) -> float:
    return cagr_of(res.liquidation_after_tax, res.equity.index)


def evaluated(bars: pd.DataFrame, target: pd.Series, *args, **kwargs):
    """Backtest from day WARMUP, so every rule and buy and hold start trading on the same day.

    Signals are still computed from the full history; only the traded period is trimmed.
    """
    b = bars.iloc[WARMUP:]
    return backtest(b, target.reindex(b.index), *args, **kwargs)


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
    out = {}
    for name, (b, c, t) in layers.items():
        res = evaluated(b, target, c, t, CAPITAL, RF)
        out[name] = cagr_of(res.liquidation_after_tax, res.equity.index)
    return out


def report_engine(out_dir: Path) -> dict:
    """How much a 200-day moving-average rule loses as the backtest becomes realistic."""
    rows, hold = {}, {}
    for sym in [INDEX] + SYMBOLS:
        bars = load_bars(sym)
        rows[sym] = honesty_steps(bars, above_ma(bars["close"], 200))
        always = pd.Series(1, index=bars.index)
        hold[sym] = {
            "free": _cagr_run(evaluated(bars, always, FREE, None, CAPITAL, RF)),
            "real": _cagr_run(evaluated(bars, always, ZERODHA_DELIVERY, INDIA_EQUITY, CAPITAL, RF)),
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

    trades = {s: len(evaluated(load_bars(s), above_ma(load_bars(s)["close"], 200)).trades)
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
    res = evaluated(bars, target)
    years = (res.equity.index[-1] - res.equity.index[0]).days / 365.25
    w = res.equity
    t = res.trades
    return {
        "CAGR": _cagr_run(res),
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
            res = evaluated(bars, RULES[rule](bars["close"]))
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
    t = evaluated(bars, RULES["SMA-200 filter"](bars["close"])).trades
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


APPROACH_COLORS = {"walk-forward": plots.SERIES[0], "best pair in hindsight": plots.MUTED,
                   "fixed 50/200 cross": plots.SERIES[2], "buy and hold": plots.TEXT}


def walk_forward_run(bars: pd.DataFrame, train_years: int = 3) -> dict:
    """Walk-forward vs hindsight-best vs fixed 50/200 vs buy and hold over the same test years."""
    m, r = crossover_grid(bars)
    first = int(r.index[0].year) + train_years + (1 if r.index[0].month > 1 else 0)
    if first > int(r.index[-1].year):
        raise ValueError(f"not enough history for {train_years} training years")
    choices = choose_by_year(r, train_years, first)
    targets = {p: crossover(bars["close"], *p) for p in m.index}
    test = bars.loc[f"{first}-01-01":]
    approaches = {
        "walk-forward": splice(targets, choices),
        "best pair in hindsight": targets[m["sharpe"].idxmax()],
        "fixed 50/200 cross": targets[(50, 200)],
        "buy and hold": pd.Series(1, index=test.index),
    }
    results = {k: backtest(test, t.reindex(test.index).fillna(0)) for k, t in approaches.items()}
    decay = []
    for year, pair in choices.items():
        tr = r[(r.index.year >= year - train_years) & (r.index.year < year)][pair]
        te = r[r.index.year == year][pair]
        decay.append((tr.mean() / tr.std() * np.sqrt(252),
                      te.mean() / te.std() * np.sqrt(252) if te.std() > 0 else 0.0))
    pct = []
    for year, pair in choices.items():
        te = r[r.index.year == year]
        sr = te.mean() / te.std().replace(0, np.nan)
        pct.append(float((sr < sr[pair]).mean()))
    picks = list(choices.values())
    return {"first": first, "percentile next year": float(np.mean(pct)), "choices": choices,
            "results": results,
            "cagr": {k: cagr_of(v.liquidation_after_tax, test.index) for k, v in results.items()},
            "train sharpe": float(np.mean([d[0] for d in decay])),
            "next-year sharpe": float(np.mean([d[1] for d in decay])),
            "switches": sum(a != b for a, b in zip(picks, picks[1:], strict=False)),
            "years": len(picks)}


def report_walkforward(out_dir: Path) -> dict:
    """Choose the best crossover on the past 3 years, trade it for a year, repeat."""
    runs = {sym: walk_forward_run(load_bars(sym)) for sym in [INDEX] + SYMBOLS}
    five = {sym: walk_forward_run(load_bars(sym), 5) for sym in [INDEX] + SYMBOLS}
    cagr = pd.DataFrame({s: v["cagr"] for s, v in runs.items()}).T

    n = runs[INDEX]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    curves = {}
    for name, res in n["results"].items():
        w = res.equity / 1e5
        ax.plot(w.index, w, color=APPROACH_COLORS[name], lw=2.2 if name == "walk-forward" else 1.6)
        curves[name] = w
    _label_ends(ax, curves, APPROACH_COLORS)
    ax.set_ylabel("₹ lakh (started with 10), after costs and tax")
    ax.set_title(f"NIFTY {n['first']}–2026: the honest walk-forward result trails everything")
    plots.save(fig, out_dir, "wf_nifty")

    fig, ax = plt.subplots(figsize=(9, 4.6))
    y = np.arange(len(cagr))
    h = 0.2
    for k, name in enumerate(APPROACH_COLORS):
        ax.barh(y + (k - 1.5) * h, cagr[name] * 100, height=h * 0.9, color=APPROACH_COLORS[name],
                label=name)
    ax.axvline(0, color=plots.TEXT_2, lw=0.8)
    ax.set_yticks(y, cagr.index)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(f"growth, % a year after costs and tax ({n['first']}–2026)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=4, fontsize=8)
    ax.set_title("Walk-forward kept the least on every series", pad=28)
    plots.save(fig, out_dir, "wf_cagr")

    fig, ax = plt.subplots(figsize=(9, 4.6))
    syms = list(runs)
    for i, sym in enumerate(syms):
        a, b = runs[sym]["train sharpe"], runs[sym]["next-year sharpe"]
        ax.plot([a, b], [i, i], color=plots.GRID, lw=3, zorder=1)
        ax.scatter(a, i, color=plots.SERIES[0], s=70, zorder=3,
                   label="Sharpe in its 3 training years" if i == 0 else None)
        ax.scatter(b, i, color=plots.SERIES[7], s=70, zorder=3,
                   label="Sharpe in the year it was traded" if i == 0 else None)
    ax.axvline(0, color=plots.TEXT_2, lw=0.8)
    ax.set_yticks(range(len(syms)), syms)
    ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("annualised Sharpe ratio of the chosen pair (average over years)")
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    ax.set_title("The pair that looked best turned negative the year it was used", pad=28)
    plots.save(fig, out_dir, "wf_decay")

    return {
        "test years from": {s: v["first"] for s, v in runs.items()},
        "CAGR after costs and tax (3y training)": (cagr * 100).round(2).to_dict("index"),
        "walk-forward below fixed 50/200":
            int((cagr["walk-forward"] < cagr["fixed 50/200 cross"]).sum()),
        "walk-forward below buy and hold": int((cagr["walk-forward"] < cagr["buy and hold"]).sum()),
        "train vs next-year Sharpe": {
            s: (round(v["train sharpe"], 2), round(v["next-year sharpe"], 2))
            for s, v in runs.items()},
        "switches": {s: f"{v['switches']} of {v['years'] - 1}" for s, v in runs.items()},
        "chosen pair's percentile among all pairs, next year":
            {s: round(v["percentile next year"], 2) for s, v in runs.items()},
        "5y training: CAGR wf / hold": {s: (round(v["cagr"]["walk-forward"] * 100, 2),
                                            round(v["cagr"]["buy and hold"] * 100, 2))
                                        for s, v in five.items()},
        "NIFTY picks": {y: f"{p[0]}/{p[1]}" for y, p in n["choices"].items()},
    }


def _risk_stats(bars: pd.DataFrame, res) -> dict:
    w = res.equity
    r = res.returns.iloc[1:] - RF / 252
    yearly = w.resample("YE").last().pct_change().dropna()
    return {"CAGR": _cagr_run(res),
            "max drawdown": float((w / w.cummax() - 1).min()),
            "Sharpe": float(r.mean() / r.std() * np.sqrt(252)),
            "worst year": float(yearly.min())}


def overlay_compare(bars: pd.DataFrame, rule: str) -> dict:
    """A trend rule vs a fixed mix holding the rule's average exposure (rebalanced at 5% drift)."""
    res = evaluated(bars, RULES[rule](bars["close"]))
    exposure = float(res.position.mean())
    mix = evaluated(bars, pd.Series(exposure, index=bars.index))
    return {"exposure": exposure, "rule": _risk_stats(bars, res), "mix": _risk_stats(bars, mix),
            "rule_result": res, "mix_result": mix}


def report_overlay(out_dir: Path) -> dict:
    """Is a trend filter good risk control? Judged against the same exposure, held steadily."""
    rules = ("SMA-200 filter", "EMA 50/200 cross")
    rows = {}
    for sym in [INDEX] + SYMBOLS:
        bars = load_bars(sym)
        for rule in rules:
            c = overlay_compare(bars, rule)
            rows[(sym, rule)] = {"exposure": c["exposure"]} | {
                f"{side} {k}": v for side in ("rule", "mix") for k, v in c[side].items()}
            if sym == INDEX and rule == "SMA-200 filter":
                nifty = c
    table = pd.DataFrame(rows).T

    bars = load_bars(INDEX)
    hold = evaluated(bars, pd.Series(1, index=bars.index))
    lines = {"SMA-200 filter": (nifty["rule_result"], plots.SERIES[0]),
             f"fixed {nifty['exposure']:.0%} in NIFTY": (nifty["mix_result"], plots.TEXT),
             "buy and hold": (hold, plots.MUTED)}
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(9, 5.4), sharex=True,
                                  gridspec_kw={"height_ratios": [2, 1]})
    curves = {}
    for name, (res, color) in lines.items():
        w = res.equity / 1e5
        ax.plot(w.index, w, color=color, lw=2 if "filter" in name else 1.6)
        curves[name] = w
        ax2.plot(w.index, (w / w.cummax() - 1) * 100, color=color, lw=1.2)
    _label_ends(ax, curves, {k: v[1] for k, v in lines.items()})
    ax.set_ylabel("₹ lakh, after costs and tax")
    ax2.set_ylabel("drawdown, %")
    ax.set_title(f"NIFTY: holding {nifty['exposure']:.0%} steadily beat timing it with the 200-day "
                 "filter")
    plots.save(fig, out_dir, "overlay_nifty")

    labels = [f"{s} · {'filter' if 'filter' in r else 'cross'}" for s, r in table.index]
    fig, axes = plt.subplots(1, 2, figsize=(9, 5.2), sharey=True)
    y = np.arange(len(table))
    for ax, key, title, scale in ((axes[0], "CAGR", "growth, % a year", 100),
                                  (axes[1], "max drawdown", "worst drawdown, %", 100)):
        a, b = table[f"rule {key}"] * scale, table[f"mix {key}"] * scale
        for i in range(len(table)):
            ax.plot([a.iloc[i], b.iloc[i]], [i, i], color=plots.GRID, lw=3, zorder=1)
        ax.scatter(a, y, color=plots.SERIES[0], s=45, zorder=3, label="trend rule")
        ax.scatter(b, y, color=plots.TEXT, s=45, zorder=3, label="fixed mix, same exposure")
        ax.set_title(title, fontsize=10, fontweight="normal", color=plots.TEXT_2)
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(y, labels, fontsize=8)
    axes[0].invert_yaxis()
    axes[0].legend(loc="lower left", bbox_to_anchor=(0, 1.06), ncol=2)
    fig.suptitle("Same exposure, held steadily: more growth, and drawdowns just as small", x=0.06,
                 ha="left", fontsize=13, fontweight="semibold", color=plots.TEXT, y=1.03)
    plots.save(fig, out_dir, "overlay_compare")

    wins = {k: int((table[f"rule {k}"] > table[f"mix {k}"]).sum())
            for k in ("CAGR", "Sharpe", "max drawdown", "worst year")}
    return {"rule better than same-exposure mix (of 12)": wins,
            "table": table.astype(float).round(3).to_dict("index")}


SURVIVORSHIP_JSON = Path("docs/data/survivorship.json")


def report_survivorship(out_dir: Path) -> dict:
    """Point-in-time 50 most-traded stocks vs today's 50 applied to the past (MAB_LAKE_DIR)."""
    import json

    from mab.universe import load_lake, members_at, portfolio_returns

    prices, turnover = load_lake()
    days = prices.index
    rebal = [days[days.year == y][0] for y in sorted(set(days.year[days >= "2014-01-01"]))]
    pit = {d: members_at(turnover, d, 50) for d in rebal}
    today = members_at(turnover, days[-1], 50)
    surv = {d: [s for s in today if not np.isnan(prices.loc[d, s])] for d in rebal}
    signal = (prices > prices.rolling(200, min_periods=200).mean()).astype(int)
    p, sig = prices.loc[rebal[0]:], signal.loc[rebal[0]:]

    def stats(r):
        w = (1 + r).cumprod()
        x = r - RF / 252
        return {"CAGR": float(w.iloc[-1] ** (365.25 / (r.index[-1] - r.index[0]).days) - 1),
                "max drawdown": float((w / w.cummax() - 1).min()),
                "Sharpe": float(x.mean() / x.std() * np.sqrt(252))}

    runs = {(u, s): portfolio_returns(p, members, signal=sg)
            for u, members in (("point-in-time", pit), ("today's list", surv))
            for s, sg in (("buy and hold", None), ("200-day filter", sig))}
    frac = []
    for i, d in enumerate(p.index[1:], start=1):
        reb = max(x for x in rebal if x <= d)
        m = [s for s in pit[reb] if s in sig.columns]
        frac.append(float(sig.iloc[i - 1][m].mean()))
    exposure = float(np.mean(frac))
    runs[("point-in-time", f"fixed {exposure:.0%} mix")] = (
        exposure * runs[("point-in-time", "buy and hold")] + (1 - exposure) * RF / 252)
    table = {f"{u} | {s}": stats(r) for (u, s), r in runs.items()}

    colors = {("today's list", "buy and hold"): plots.MUTED,
              ("today's list", "200-day filter"): plots.SERIES[1],
              ("point-in-time", "buy and hold"): plots.TEXT,
              ("point-in-time", "200-day filter"): plots.SERIES[0]}
    fig, ax = plt.subplots(figsize=(9, 4.6))
    curves, cmap = {}, {}
    for key, color in colors.items():
        w = (1 + runs[key]).cumprod()
        name = f"{key[0]}: {key[1]}"
        ax.plot(w.index, w, color=color, lw=2 if key[0] == "point-in-time" else 1.6)
        curves[name], cmap[name] = w, color
    _label_ends(ax, curves, cmap, gap=0.9)
    ax.set_yscale("log")
    ax.set_ylabel("growth of ₹1 (log scale), after costs, before tax")
    end_surv = curves["today's list: buy and hold"].iloc[-1]
    end_pit = curves["point-in-time: buy and hold"].iloc[-1]
    ax.set_title(f"Buy and hold: today's list turns ₹1 into ₹{end_surv:.0f}; "
                 f"the honest universe into ₹{end_pit:.1f}")
    plots.save(fig, out_dir, "survivorship_growth")

    first = rebal[0]
    gone = [s for s in pit[first] if s not in today]
    total = {}
    for s in gone:
        x = prices[s].loc[first:].dropna()
        total[s] = float(x.iloc[-1] / x.iloc[0] - 1)
    tot = pd.Series(total).sort_values()
    fig, ax = plt.subplots(figsize=(9, 5.4))
    colors_b = [plots.SERIES[7] if v < -0.5 else plots.MUTED for v in tot]
    ax.barh(tot.index, tot * 100, color=colors_b, height=0.7)
    ax.axvline(0, color=plots.TEXT_2, lw=0.8)
    ax.set_xscale("symlog", linthresh=100)
    ax.tick_params(axis="y", labelsize=7)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(f"total return from {first:%b %Y} to the last trade, % (symmetric log scale)")
    ax.set_title(f"{len(gone)} of the 2014 top 50 aren't in today's list; red = lost over half")
    plots.save(fig, out_dir, "survivorship_gone")

    out = {"table": table, "exposure of filter": exposure,
           "₹1 grows to (buy and hold)": {"today's list": round(float(end_surv), 1),
                                         "point-in-time": round(float(end_pit), 2)},
           "members dropped": len(gone),
           "dropped and lost over half": int((tot < -0.5).sum()),
           "worst dropped": tot.head(8).round(3).to_dict(),
           "today's-list members trading in 2014": len(surv[first])}
    SURVIVORSHIP_JSON.parent.mkdir(parents=True, exist_ok=True)
    SURVIVORSHIP_JSON.write_text(json.dumps({k: v for k, v in out.items() if k != "worst dropped"}
                                            | {"start": f"{first:%Y-%m-%d}",
                                               "end": f"{days[-1]:%Y-%m-%d}"}, indent=1))
    return out


REPORTS = {"engine": report_engine, "rules": report_rules, "trades": report_trades,
           "sweep": report_sweep, "walkforward": report_walkforward, "overlay": report_overlay,
           "survivorship": report_survivorship}
