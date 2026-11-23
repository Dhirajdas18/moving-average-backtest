import numpy as np
import pandas as pd

from mab.site import build_html, engine_figure, rules_figure, sweep_section, trades_table


def _bars(seed):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2018-01-01", periods=600)
    c = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 600)))
    return pd.DataFrame({"open": c * 0.999, "close": c}, index=idx)


def test_engine_figure_two_lines_per_symbol_with_dropdown():
    fig = engine_figure({"NIFTY": _bars(0), "ITC": _bars(1)}, window=50)
    assert len(fig.data) == 4
    assert [b.label for b in fig.layout.updatemenus[0].buttons] == ["NIFTY", "ITC"]


def test_build_html_page_with_nav_and_one_plotly_load():
    html = build_html({"NIFTY": _bars(0)})
    assert html.startswith("<!doctype html>")
    assert html.count('src="https://cdn.plot.ly') == 1
    assert 'href="#realistic-backtest"' in html and 'id="realistic-backtest"' in html


def test_rules_figure_five_lines_per_symbol():
    fig = rules_figure({"NIFTY": _bars(0), "ITC": _bars(1)})
    assert len(fig.data) == 10
    assert fig.data[4].name == "buy and hold"


def test_trades_table_is_html_with_rows_per_symbol_and_rule():
    html = trades_table({"NIFTY": _bars(0)})
    assert html.startswith('<div class="table-scroll"><table class="data">')
    assert html.count('<th scope="row">NIFTY</th>') >= 1


def test_sweep_section_has_heatmap_line_and_embedded_curves():
    import json
    import re

    html = sweep_section({"NIFTY": _bars(0)})
    assert 'id="sweep-heat"' in html and 'id="sweep-line"' in html
    data = json.loads(re.search(r'id="sweep-data">(.*?)</script>', html).group(1))
    assert data["NIFTY"]["best"] in data["NIFTY"]["curves"]
    assert len(data["NIFTY"]["curves"]) == 40
