"""Trading costs for NSE delivery trades (Zerodha), as rupee amounts per order.

Rates as of 2026-11 (zerodha.com/charges), matching the reference spec §6. Check the broker's
calculator before relying on them; they change.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    brokerage: float = 0.0  # fraction of notional
    stt: float = 0.001  # securities transaction tax, buy and sell
    stamp: float = 0.00015  # stamp duty, buy only
    exchange: float = 0.0000307  # NSE transaction charge (zerodha.com/charges, Nov 2026)
    sebi: float = 0.000001
    gst: float = 0.18  # on brokerage + exchange + SEBI fees
    dp_charge: float = 15.34  # rupees per stock per sell day, GST included
    slippage: float = 0.0005  # fill this fraction worse than the open, each side

    @classmethod
    def free(cls) -> "CostModel":
        return cls(0, 0, 0, 0, 0, 0, 0, 0)

    def _fees(self, n: float) -> float:
        base = (self.brokerage + self.exchange + self.sebi) * n
        return base + self.gst * base + self.stt * n

    def buy_cost(self, notional: float) -> float:
        return self._fees(notional) + self.stamp * notional

    def sell_cost(self, notional: float) -> float:
        return self._fees(notional) + self.dp_charge

    def stt_part(self, notional: float) -> float:
        """STT is not deductible when computing capital gains; the other charges are."""
        return self.stt * notional


ZERODHA_DELIVERY = CostModel()
