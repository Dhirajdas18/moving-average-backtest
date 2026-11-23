"""Command line: `mab report <topic>` or `mab run --symbol NIFTY --window 200`."""

import argparse
from pathlib import Path

OUT = Path("out")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mab", description="Moving-average backtests on NSE data")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="build a topic's charts and print its numbers")
    rep.add_argument("topic")
    run = sub.add_parser("run", help="backtest one rule on one symbol")
    run.add_argument("--symbol", default="NIFTY")
    run.add_argument("--window", type=int, default=200, help="hold while price > this-day SMA")
    run.add_argument("--capital", type=float, default=1_000_000)
    run.add_argument("--no-tax", action="store_true")
    args = parser.parse_args(argv)

    from mab import plots, reports

    if args.cmd == "report":
        if args.topic not in reports.REPORTS:
            parser.error(f"unknown topic {args.topic!r}; topics: {', '.join(reports.REPORTS)}")
        plots.style()
        for key, value in reports.REPORTS[args.topic](OUT).items():
            print(f"{key}: {value}")
        print(f"charts -> {OUT.resolve()}")
        return 0

    from mab.costs import ZERODHA_DELIVERY
    from mab.data import load_bars
    from mab.engine import backtest
    from mab.signals import above_ma
    from mab.tax import INDIA_EQUITY

    bars = load_bars(args.symbol)
    res = backtest(bars, above_ma(bars["close"], args.window), ZERODHA_DELIVERY,
                   None if args.no_tax else INDIA_EQUITY, args.capital, reports.RF)
    print(f"{args.symbol}, price above {args.window}-day SMA, {bars.index[0]:%Y-%m-%d} to "
          f"{bars.index[-1]:%Y-%m-%d}")
    print(f"  kept after costs{'' if args.no_tax else ' and tax'}: "
          f"₹{res.liquidation_after_tax:,.0f} from ₹{args.capital:,.0f} "
          f"({reports.cagr_of(res.liquidation_after_tax, bars.index, args.capital):.2%} a year)")
    print(f"  trades {len(res.trades)}, costs ₹{res.costs_paid.sum():,.0f}, "
          f"tax ₹{res.tax_paid.sum():,.0f}, time invested {res.position.gt(0).mean():.0%}")
    return 0
