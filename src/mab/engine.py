"""Backtest one long-or-flat position in rupees, the way it would actually trade.

- The target position (1 = invested, 0 = in cash) is decided at each day's close and traded at the
  next day's open, so the overnight gap belongs to the position you already held.
- Every order pays slippage and the broker's charges; cash earns the risk-free rate.
- Realised gains are taxed at the start of each new financial year (April); if cash can't cover the
  bill, enough shares are sold at that day's open, which itself realises gains for the new year.
- `liquidation_after_tax` is what you'd keep if you sold everything at the last close and paid tax.

Fractional shares are allowed. Dividends are assumed reinvested (adjusted prices), without
dividend tax.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from mab.costs import ZERODHA_DELIVERY, CostModel
from mab.returns import TRADING_DAYS
from mab.tax import INDIA_EQUITY, Carry, TaxRules, fy_tax


def financial_year(d: pd.Timestamp) -> int:
    """Indian financial year label: April 2023 - March 2024 is 2023."""
    return d.year if d.month >= 4 else d.year - 1


@dataclass
class Result:
    equity: pd.Series  # rupees at each close, after any tax already paid
    position: pd.Series  # share of equity invested at each close
    tax_paid: pd.Series
    costs_paid: pd.Series
    trades: pd.DataFrame
    liquidation_after_tax: float
    gains: pd.DataFrame  # per financial year: short_term, long_term, tax (last row = liquidation)

    @property
    def returns(self) -> pd.Series:
        return self.equity.pct_change().fillna(0.0)


def backtest(
    bars: pd.DataFrame,
    target: pd.Series,
    costs: CostModel = ZERODHA_DELIVERY,
    tax: TaxRules | None = INDIA_EQUITY,
    capital: float = 1_000_000.0,
    rf: float = 0.065,
) -> Result:
    """`bars`: adjusted 'open' and 'close' per day. `target`: desired position at each close."""
    idx = bars.index
    opens, closes = bars["open"].to_numpy(float), bars["close"].to_numpy(float)
    want = target.reindex(idx).fillna(0).to_numpy(float)
    buy_rate = costs.buy_cost(1.0)  # buy charges are proportional
    sell_rate = costs.sell_cost(1.0) - costs.dp_charge
    daily_rf = rf / TRADING_DAYS

    cash, shares, basis, entry = float(capital), 0.0, 0.0, None
    gains: dict[int, list[float]] = {}  # financial year -> [short-term, long-term]
    carry = Carry()
    fy_rows: dict[int, tuple[float, float, float]] = {}
    trades, open_trade = [], None
    eq, pos, taxes, fees = (np.zeros(len(idx)) for _ in range(4))

    def realise(day, n_shares, fill):
        """Sell n_shares at fill; book cash, gain (net of deductible charges) and costs."""
        nonlocal cash, shares, basis
        proceeds = n_shares * fill
        cost = costs.sell_cost(proceeds)
        part = basis * n_shares / shares
        gain = proceeds - (cost - costs.stt_part(proceeds)) - part
        long = (day - entry).days > (tax.long_term_days if tax else 365)
        gains.setdefault(financial_year(day), [0.0, 0.0])[1 if long else 0] += gain
        cash += proceeds - cost
        basis -= part
        shares -= n_shares
        return cost, proceeds - cost

    for i, day in enumerate(idx):
        o = opens[i]
        # 1. tax for the financial year that just ended
        if tax is not None and i > 0 and financial_year(day) != financial_year(idx[i - 1]):
            fy = financial_year(idx[i - 1])
            st, lt = gains.pop(fy, [0.0, 0.0])
            due, carry = fy_tax(st, lt, carry, tax)
            fy_rows[fy] = (st, lt, due)
            taxes[i] = due
            if due > cash and shares > 0:
                fill = o * (1 - costs.slippage)
                need = (due - cash + costs.dp_charge) / (1 - sell_rate)
                fees[i] += realise(day, min(need / fill, shares), fill)[0]
            cash -= due
        # 2. trade at the open toward yesterday's target
        desired = want[i - 1] if i > 0 else 0.0
        if desired > 0 and shares == 0 and cash > 0:
            fill = o * (1 + costs.slippage)
            notional = cash / (1 + buy_rate)
            cost = costs.buy_cost(notional)
            shares, cash = notional / fill, 0.0
            basis, entry = notional + cost - costs.stt_part(notional), day
            fees[i] += cost
            open_trade = {"entry_date": day, "entry_price": fill, "shares": shares,
                          "invested": notional + cost}
        elif desired == 0 and shares > 0:
            fill = o * (1 - costs.slippage)
            cost, net = realise(day, shares, fill)
            fees[i] += cost
            if open_trade is not None:
                trades.append(open_trade | {"exit_date": day, "exit_price": fill,
                                            "proceeds": net})
                open_trade = None
        # 3. close: cash earns interest, mark the position
        cash *= 1 + daily_rf
        eq[i] = cash + shares * closes[i]
        pos[i] = shares * closes[i] / eq[i] if eq[i] else 0.0

    # what you'd keep after selling everything at the last close and settling tax
    final = cash
    if shares > 0:
        fill = closes[-1] * (1 - costs.slippage)
        final += shares * fill - costs.sell_cost(shares * fill)
        if tax is not None:
            realise(idx[-1], shares, fill)
    if tax is not None:
        fy = financial_year(idx[-1])
        st, lt = gains.pop(fy, [0.0, 0.0])
        due = fy_tax(st, lt, carry, tax)[0]
        fy_rows[fy] = (st, lt, due)
        final -= due

    if open_trade is not None:  # still invested at the end: value it at the last close
        trades.append(open_trade | {"exit_date": idx[-1], "exit_price": closes[-1],
                                    "proceeds": open_trade["shares"] * closes[-1], "open": True})
    t = pd.DataFrame(trades, columns=["entry_date", "entry_price", "shares", "invested",
                                      "exit_date", "exit_price", "proceeds", "open"])
    t["open"] = t["open"].eq(True)
    if len(t):
        t["return"] = t["proceeds"] / t["invested"] - 1
        t["days"] = (t["exit_date"] - t["entry_date"]).dt.days
    return Result(
        equity=pd.Series(eq, index=idx, name="equity"),
        position=pd.Series(pos, index=idx, name="position"),
        tax_paid=pd.Series(taxes, index=idx, name="tax"),
        costs_paid=pd.Series(fees, index=idx, name="costs"),
        trades=t,
        liquidation_after_tax=float(final),
        gains=pd.DataFrame.from_dict(fy_rows, orient="index",
                                     columns=["short_term", "long_term", "tax"]).sort_index(),
    )
