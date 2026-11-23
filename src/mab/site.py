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
            fig.add_scatter(x=list(w.index.strftime("%Y-%m-%d")), y=w.round(2).tolist(),
                            name=name, visible=i == 0, line=dict(color=color, width=2),
                            hovertemplate="₹%{y:.2f} lakh")
    _symbol_dropdown(fig, symbols, 2)
    fig = _layout(fig, "₹ lakh (started with 10), after costs and tax paid so far")
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
            fig.add_scatter(x=list(w.index.strftime("%Y-%m-%d")), y=w.round(2).tolist(),
                            name=name, visible=i == 0, line=dict(color=color, width=2),
                            hovertemplate="₹%{y:.2f} lakh")
    _symbol_dropdown(fig, symbols, len(RULES) + 1)
    fig = _layout(fig, "₹ lakh (started with 10), after costs and tax paid so far")
    fig.update_xaxes(range=None)
    return fig


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
