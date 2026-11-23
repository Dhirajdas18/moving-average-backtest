"""Interactive dashboard: one static HTML page of Plotly charts, built from the price table."""

import json
import re
from pathlib import Path
from string import Template

import pandas as pd
import plotly.graph_objects as go

from mab import plots
from mab.costs import ZERODHA_DELIVERY
from mab.data import INDEX, SYMBOLS, load_bars
from mab.engine import backtest
from mab.signals import above_ma, crossover
from mab.stats import split_growth, trade_stats
from mab.sweep import FAST, SLOW, crossover_grid
from mab.tax import INDIA_EQUITY

FONT = "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"

ICON = (
    "data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 16%22%3E"
    "%3Cpath d=%22M1 12 5 7l3 3 7-8%22 fill=%22none%22 stroke=%22%232a78d6%22"
    " stroke-width=%222%22/%3E"
    "%3C/svg%3E"
)

def _layout(fig: go.Figure, ytitle: str) -> go.Figure:
    fig.update_layout(
        paper_bgcolor=plots.SURFACE,
        plot_bgcolor=plots.SURFACE,
        font=dict(family=FONT, color=plots.TEXT_2, size=13),
        hovermode="x unified",
        margin=dict(l=56, r=24, t=96, b=40),
        legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, xanchor="left"),
        yaxis=dict(title=ytitle, gridcolor=plots.GRID, zeroline=False, automargin=True),
        xaxis=dict(
            gridcolor=plots.GRID,
            rangeslider=dict(visible=False),
            rangeselector=dict(
                buttons=[dict(count=n, label=f"{n}y", step="year", stepmode="backward")
                         for n in (1, 3, 5)] + [dict(step="all", label="All")],
                x=1, xanchor="right", y=1.08, yanchor="bottom", bgcolor="white",
            ),
        ),
    )
    end = max(pd.Timestamp(max(t.x)) for t in fig.data)
    fig.update_xaxes(range=[end - pd.DateOffset(years=3), end])  # open on the last 3 years
    return fig


def _symbol_dropdown(fig: go.Figure, symbols: list[str], per_symbol: int) -> None:
    """Dropdown that shows one symbol's group of traces at a time."""
    buttons = []
    for i, sym in enumerate(symbols):
        visible = [j // per_symbol == i for j in range(len(symbols) * per_symbol)]
        buttons.append(dict(label=sym, method="update", args=[{"visible": visible}]))
    fig.update_layout(updatemenus=[dict(buttons=buttons, x=0, xanchor="left", y=1.14,
                                        yanchor="bottom", bgcolor="white")])


def _line(fig: go.Figure, v: pd.Series, name: str, color: str, visible: bool) -> None:
    v = v.dropna() * 100
    # plain lists (not binary arrays) so the page script can read y; short dates keep it small
    fig.add_scatter(x=list(v.index.strftime("%Y-%m-%d")), y=v.round(1).tolist(), name=name,
                    visible=visible,
                    line=dict(color=color, width=2), hovertemplate="%{y:.1f}%")



RF = 0.065
CAPITAL = 1_000_000.0


def _thin(curve: pd.Series) -> pd.Series:
    """Weekly points for long equity curves (keeps the page light; the last day is kept)."""
    weekly = curve.resample("W-FRI").last().dropna()
    if len(curve) and (not len(weekly) or weekly.index[-1] != curve.index[-1]):
        weekly = pd.concat([weekly[weekly.index < curve.index[-1]], curve.iloc[-1:]])
    return weekly


def engine_figure(bars_by_symbol: dict[str, pd.DataFrame], window: int = 200) -> go.Figure:
    """Growth of ₹10 lakh: price-above-SMA rule vs buy and hold, both after costs and tax."""
    fig = go.Figure()
    symbols = list(bars_by_symbol)
    for i, sym in enumerate(symbols):
        bars = bars_by_symbol[sym]
        rule = backtest(bars, above_ma(bars["close"], window), ZERODHA_DELIVERY, INDIA_EQUITY,
                        CAPITAL, RF)
        hold = backtest(bars, pd.Series(1, index=bars.index), ZERODHA_DELIVERY, INDIA_EQUITY,
                        CAPITAL, RF)
        for name, res, color in ((f"above {window}-day SMA", rule, plots.SERIES[0]),
                                 ("buy and hold", hold, plots.TEXT)):
            w = res.equity / 1e5
            w = _thin(w)
            fig.add_scatter(x=list(w.index.strftime("%Y-%m-%d")), y=w.round(2).tolist(),
                            name=name, visible=i == 0, line=dict(color=color, width=2),
                            hovertemplate="₹%{y:.2f} lakh")
    _symbol_dropdown(fig, symbols, 2)
    fig = _layout(fig, "₹ lakh, after costs and tax")
    fig.update_xaxes(range=None)  # show the whole history
    return fig


RULES = {
    "SMA-200 filter": (lambda c: above_ma(c, 200), plots.SERIES[0]),
    "EMA-200 filter": (lambda c: above_ma(c, 200, "ema"), plots.SERIES[1]),
    "SMA 50/200 cross": (lambda c: crossover(c, 50, 200), plots.SERIES[2]),
    "EMA 50/200 cross": (lambda c: crossover(c, 50, 200, "ema"), plots.SERIES[6]),
}


def rules_figure(bars_by_symbol: dict[str, pd.DataFrame]) -> go.Figure:
    """Four textbook moving-average rules vs buy and hold, after costs and tax."""
    fig = go.Figure()
    symbols = list(bars_by_symbol)
    for i, sym in enumerate(symbols):
        bars = bars_by_symbol[sym]
        lines = {name: (make(bars["close"]), color) for name, (make, color) in RULES.items()}
        lines["buy and hold"] = (pd.Series(1, index=bars.index), plots.TEXT)
        for name, (target, color) in lines.items():
            w = backtest(bars, target, ZERODHA_DELIVERY, INDIA_EQUITY, CAPITAL, RF).equity / 1e5
            w = _thin(w)
            fig.add_scatter(x=list(w.index.strftime("%Y-%m-%d")), y=w.round(2).tolist(),
                            name=name, visible=i == 0, line=dict(color=color, width=2),
                            hovertemplate="₹%{y:.2f} lakh")
    _symbol_dropdown(fig, symbols, len(RULES) + 1)
    fig = _layout(fig, "₹ lakh, after costs and tax")
    fig.update_xaxes(range=None)
    return fig


def trades_table(bars_by_symbol: dict[str, pd.DataFrame]) -> str:
    """Trade statistics for the SMA-200 filter and SMA 50/200 cross, per symbol and rule."""
    head = ["", '<span class="text">Rule</span>', "Trades", "Win rate", "Payoff",
            "Break-even win rate", "Avg trade", "Median days, winners", "Median days, losers",
            "Best 3 alone", "All others"]
    rows = []
    for sym, bars in bars_by_symbol.items():
        for rule in ("SMA-200 filter", "SMA 50/200 cross"):
            t = backtest(bars, RULES[rule][0](bars["close"]), ZERODHA_DELIVERY, INDIA_EQUITY,
                         CAPITAL, RF).trades
            if len(t) < 4:
                continue
            st = trade_stats(t)
            best, rest = split_growth(t, 3)
            cells = [f"{st['trades']}", f"{st['win rate']:.0%}", f"{st['payoff ratio']:.1f}×",
                     f"{st['break-even win rate']:.0%}", f"{st['expectancy']:+.1%}",
                     f"{st['median days, winners']:.0f}", f"{st['median days, losers']:.0f}",
                     f"{best:+.0%}", f"{rest:+.0%}"]
            nums = "".join(f"<td>{c}</td>" for c in cells).replace("-", "\u2212")
            rows.append(f'<tr><th scope="row">{sym}</th><td class="text">{rule}</td>{nums}</tr>')
    ths = "".join(f'<th scope="col">{h}</th>' for h in head)
    return (f'<div class="table-scroll"><table class="data"><thead><tr>{ths}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _weekly(equity: pd.Series) -> list[float]:
    return (equity.resample("W-FRI").last() / 1e5).round(2).tolist()


def sweep_section(bars_by_symbol: dict[str, pd.DataFrame]) -> str:
    """Heatmap of every crossover pair's Sharpe; click a cell to plot that pair's equity curve."""
    symbols = list(bars_by_symbol)
    heat = go.Figure()
    data = {}
    scale = [[0, plots.SERIES[7]], [0.5, "#f1f0ec"], [1, plots.SERIES[0]]]
    for i, sym in enumerate(symbols):
        bars = bars_by_symbol[sym]
        m, _ = crossover_grid(bars)
        g = m["sharpe"].unstack("slow").reindex(index=list(FAST), columns=list(SLOW))
        hold = backtest(bars, pd.Series(1, index=bars.index), ZERODHA_DELIVERY, INDIA_EQUITY,
                        CAPITAL, RF)
        r = bars["close"].pct_change().iloc[max(SLOW):] - RF / 252
        hold_sr = float(r.mean() / r.std() * (252 ** 0.5))
        curves = {}
        for (f, sl) in m.index:
            res = backtest(bars, crossover(bars["close"], f, sl), ZERODHA_DELIVERY, INDIA_EQUITY,
                           CAPITAL, RF)
            curves[f"{f}/{sl}"] = _weekly(res.equity)
        best = m["sharpe"].idxmax()
        data[sym] = {"dates": list(hold.equity.resample("W-FRI").last().index.strftime("%Y-%m-%d")),
                     "hold": _weekly(hold.equity), "curves": curves, "best": f"{best[0]}/{best[1]}"}
        lim = float((g - hold_sr).abs().max().max())
        heat.add_heatmap(
            z=g.round(2).to_numpy(), x=[str(v) for v in SLOW], y=[str(v) for v in FAST],
            visible=i == 0, colorscale=scale, zmid=hold_sr, zmin=hold_sr - lim, zmax=hold_sr + lim,
            texttemplate="%{z:.2f}", showscale=False, name=sym,
            hovertemplate=f"{sym} %{{y}}/%{{x}}: Sharpe %{{z:.2f}} (buy and hold {hold_sr:.2f})"
                          "<extra></extra>")
    _symbol_dropdown(heat, symbols, 1)
    heat.update_layout(paper_bgcolor=plots.SURFACE, plot_bgcolor=plots.SURFACE, height=440,
                       font=dict(family=FONT, color=plots.TEXT_2, size=12),
                       margin=dict(l=64, r=24, t=64, b=48),
                       xaxis=dict(title="slow average, days", type="category"),
                       yaxis=dict(title="fast average, days", type="category",
                                  autorange="reversed"))
    first = symbols[0]
    line = go.Figure()
    d0 = data[first]
    for name, ys, color in ((f"{first} {d0['best']} crossover", d0["curves"][d0["best"]],
                             plots.SERIES[0]),
                            (f"{first} buy and hold", d0["hold"], plots.TEXT)):
        line.add_scatter(x=data[first]["dates"], y=ys, name=name, line=dict(color=color, width=2),
                         hovertemplate="₹%{y:.2f} lakh")
    line = _layout(line, "₹ lakh, after costs and tax")
    line.update_xaxes(range=None)
    cfg = {"displaylogo": False, "responsive": True}
    return (
        heat.to_html(full_html=False, include_plotlyjs=False, div_id="sweep-heat", config=cfg)
        + line.to_html(full_html=False, include_plotlyjs=False, div_id="sweep-line", config=cfg)
        + f'<script type="application/json" id="sweep-data">{json.dumps(data)}</script>'
        + """<script>
(() => {
  const heat = document.getElementById("sweep-heat"), line = document.getElementById("sweep-line");
  const data = JSON.parse(document.getElementById("sweep-data").textContent);
  const symbols = Object.keys(data);
  const show = (sym, pair) => {
    const d = data[sym];
    Plotly.restyle(line, {x: [d.dates, d.dates], y: [d.curves[pair], d.hold],
                          name: [sym + " " + pair + " crossover", sym + " buy and hold"]});
  };
  heat.on("plotly_click", (e) => {
    const p = e.points[0];
    const sym = symbols[heat.data.findIndex((t) => t.visible !== false)];
    const pair = p.y + "/" + p.x;
    if (data[sym].curves[pair]) show(sym, pair);
  });
  heat.on("plotly_update", () => {
    const sym = symbols[heat.data.findIndex((t) => t.visible !== false)];
    show(sym, data[sym].best);
  });
})();
</script>""")


def walkforward_figure(bars_by_symbol: dict[str, pd.DataFrame]) -> go.Figure | str:
    """Walk-forward vs hindsight-best vs fixed 50/200 vs buy and hold, over the test years."""
    from mab.reports import APPROACH_COLORS, walk_forward_run

    runs = {}
    for sym, bars in bars_by_symbol.items():
        try:
            runs[sym] = walk_forward_run(bars)
        except ValueError:  # too little history for three training years
            continue
    if not runs:
        return "<p>Not enough history for a walk-forward test.</p>"
    fig = go.Figure()
    symbols = list(runs)
    for i, sym in enumerate(symbols):
        for name, res in runs[sym]["results"].items():
            w = res.equity / 1e5
            w = _thin(w)
            fig.add_scatter(x=list(w.index.strftime("%Y-%m-%d")), y=w.round(2).tolist(),
                            name=name, visible=i == 0,
                            line=dict(color=APPROACH_COLORS[name], width=2),
                            hovertemplate="₹%{y:.2f} lakh")
    _symbol_dropdown(fig, symbols, 4)
    fig = _layout(fig, "₹ lakh, after costs and tax")
    fig.update_xaxes(range=None)
    return fig


def overlay_figure(bars_by_symbol: dict[str, pd.DataFrame]) -> go.Figure:
    """SMA-200 filter vs a fixed mix at the filter's average exposure vs buy and hold."""
    from mab.reports import overlay_compare

    fig = go.Figure()
    symbols = list(bars_by_symbol)
    for i, sym in enumerate(symbols):
        bars = bars_by_symbol[sym]
        c = overlay_compare(bars, "SMA-200 filter")
        hold = backtest(bars, pd.Series(1, index=bars.index), ZERODHA_DELIVERY, INDIA_EQUITY,
                        CAPITAL, RF)
        for name, res, color in (("SMA-200 filter", c["rule_result"], plots.SERIES[0]),
                                 (f"fixed {c['exposure']:.0%} invested", c["mix_result"],
                                  plots.TEXT),
                                 ("buy and hold", hold, plots.MUTED)):
            w = res.equity / 1e5
            w = _thin(w)
            fig.add_scatter(x=list(w.index.strftime("%Y-%m-%d")), y=w.round(2).tolist(),
                            name=name, visible=i == 0, line=dict(color=color, width=2),
                            hovertemplate="₹%{y:.2f} lakh")
    _symbol_dropdown(fig, symbols, 3)
    fig = _layout(fig, "₹ lakh, after costs and tax")
    fig.update_xaxes(range=None)
    return fig


SURVIVORSHIP_JSON = Path(__file__).resolve().parents[2] / "docs" / "data" / "survivorship.json"


def survivorship_table(_bars_by_symbol: dict[str, pd.DataFrame]) -> str:
    """Aggregate survivorship results written by `mab report survivorship` (local NSE data)."""
    if not SURVIVORSHIP_JSON.exists():
        return "<p>Run <code>mab report survivorship</code> with a local NSE data folder.</p>"
    d = json.loads(SURVIVORSHIP_JSON.read_text())
    rows = []
    for key, v in d["table"].items():
        universe, strategy = key.split(" | ")
        nums = (f"<td>{v['CAGR']:.1%}</td><td>{v['max drawdown']:.0%}</td>"
                f"<td>{v['Sharpe']:.2f}</td>").replace("-", "\u2212")
        rows.append(f'<tr><th scope="row">{universe}</th>'
                    f'<td class="text">{strategy}</td>{nums}</tr>')
    head = ("<th scope=\"col\"></th><th scope=\"col\"><span class=\"text\">Strategy</span></th>"
            "<th scope=\"col\">Growth a year</th><th scope=\"col\">Worst drawdown</th>"
            "<th scope=\"col\">Sharpe</th>")
    note = (f"<p>{d['start']} to {d['end']}, after costs, before tax. "
            f"{d['members dropped']} of the {d['start'][:4]} top 50 are not in today's list; "
            f"{d['dropped and lost over half']} of them lost more than half their value.</p>")
    return (f'<div class="table-scroll"><table class="data"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>{note}')


SECTIONS = [
    ("Realistic backtest",
     "Signal at each close, trade at the next open, Zerodha delivery charges and 0.05% slippage on "
     "every order, cash earning 6.5%, and capital-gains tax settled each April (20% short-term, "
     "12.5% long-term above ₹1.25 lakh, plus 4% cess). The rule holds while the price is above its "
     "200-day average.",
     engine_figure),
    ("Rule styles",
     "A price filter (hold while the close is above its 200-day average) against a 50/200 "
     "crossover (hold while the 50-day average is above the 200-day), each with a simple (SMA) "
     "or exponential (EMA) average. Filters trade about four times a year and most of their "
     "trades reverse within a month; crossovers trade under once a year but exit late.",
     rules_figure),
    ("Trade statistics",
     "Win rate is the share of trades that made money; payoff is the average win divided by the "
     "average loss; a rule breaks even when its win rate equals 1 / (1 + payoff). The last two "
     "columns compound the three best trades on their own, and every other trade together.",
     trades_table),
    ("Parameter sweep",
     "Sharpe ratio (after costs, before tax) of every fast/slow simple-average crossover. Blue "
     "cells beat buy and hold, red cells lose to it. Click any cell to plot that pair against "
     "buy and hold. The best cell is the one a backtest would brag about; on its own it proves "
     "little.",
     sweep_section),
    ("Walk-forward",
     "Each January, the crossover pair with the best Sharpe over the previous three years is "
     "chosen and traded for that year; the years are stitched together. This is what following the "
     "\u2018use the best setting\u2019 process would really have earned, next to the best pair "
     "picked with hindsight, a fixed 50/200 cross and buy and hold, all from 2018.",
     walkforward_figure),
    ("Trend filter as risk control",
     "Holding less stock lowers risk by itself, so the fair test of a trend filter is a fixed mix "
     "that holds the filter's average exposure steadily (rebalanced when it drifts 5%), after the "
     "same costs and tax. Any difference then comes from the timing alone.",
     overlay_figure),
    ("Survivorship bias",
     "Testing on today's 50 most-traded NSE stocks quietly drops every company that fell out of "
     "the top 50, including the ones that collapsed. The honest version uses the 50 most-traded "
     "stocks as known at each January, from NSE's daily files, including later delistings.",
     survivorship_table),
]

REPO = "https://github.com/Dhirajdas18/moving-average-backtest"
PAGE = Template((Path(__file__).with_name("page.html")).read_text(encoding="utf-8"))


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def build_html(bars_by_symbol: dict[str, pd.DataFrame]) -> str:
    parts, nav, loaded = [], [], False
    for title, blurb, make in SECTIONS:
        out = make(bars_by_symbol)
        if isinstance(out, str):
            body = out
        else:
            body = out.to_html(full_html=False, include_plotlyjs=False if loaded else "cdn",
                               config={"displaylogo": False, "responsive": True})
            loaded = True
        sid = _slug(title)
        nav.append(f'<li><a href="#{sid}">{title}</a></li>')
        parts.append(f'<section id="{sid}">\n<h2>{title}</h2>\n<p>{blurb}</p>\n{body}\n</section>')
    last = max(b.index[-1] for b in bars_by_symbol.values())
    return PAGE.substitute(
        icon=ICON, font=FONT, repo=REPO, updated=f"{last:%d %b %Y}",
        surface=plots.SURFACE, text=plots.TEXT, text2=plots.TEXT_2, grid=plots.GRID,
        accent=plots.SERIES[0], d_surface=plots.DARK[plots.SURFACE], d_text=plots.DARK[plots.TEXT],
        d_text2=plots.DARK[plots.TEXT_2], d_grid=plots.DARK[plots.GRID],
        d_accent=plots.DARK[plots.SERIES[0]],
        dark=json.dumps({k.lower(): v for k, v in plots.DARK.items()}),
        dark_lines=json.dumps({k.lower(): v for k, v in plots.DARK_LINES.items()}),
        nav="\n".join(nav), sections="\n".join(parts),
    )


def load_all() -> dict[str, pd.DataFrame]:
    return {s: load_bars(s) for s in [INDEX] + SYMBOLS}
