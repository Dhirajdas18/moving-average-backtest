import pytest

from mab.costs import ZERODHA_DELIVERY, CostModel
from mab.tax import INDIA_EQUITY, Carry, fy_tax


def test_zerodha_round_trip_cost():
    c = ZERODHA_DELIVERY
    n = 100_000
    buy, sell = c.buy_cost(n), c.sell_cost(n)
    exch, sebi = 0.0000307 * n, 0.000001 * n
    gst = 0.18 * (exch + sebi)
    assert buy == pytest.approx(0.001 * n + 0.00015 * n + exch + sebi + gst)
    assert sell == pytest.approx(0.001 * n + exch + sebi + gst + 15.34)
    # about 0.222% + DP for a round trip, before slippage
    assert (buy + sell - 15.34) / n == pytest.approx(0.002223, abs=0.00002)


def test_free_cost_model_charges_nothing():
    free = CostModel.free()
    assert free.buy_cost(1e6) == 0 and free.sell_cost(1e6) == 0 and free.slippage == 0


def test_short_term_gain_taxed_at_20_percent_plus_cess():
    tax, carry = fy_tax(st_gain=100_000, lt_gain=0, carry=Carry())
    assert tax == pytest.approx(100_000 * 0.20 * 1.04)
    assert carry == Carry()


def test_long_term_gain_gets_the_exemption():
    tax, _ = fy_tax(st_gain=0, lt_gain=200_000, carry=Carry())
    assert tax == pytest.approx((200_000 - 125_000) * 0.125 * 1.04)


def test_short_term_loss_offsets_long_term_gain_before_exemption():
    tax, _ = fy_tax(st_gain=-50_000, lt_gain=300_000, carry=Carry())
    assert tax == pytest.approx((300_000 - 50_000 - 125_000) * 0.125 * 1.04)


def test_long_term_loss_cannot_offset_short_term_gain_and_carries_forward():
    tax, carry = fy_tax(st_gain=80_000, lt_gain=-30_000, carry=Carry())
    assert tax == pytest.approx(80_000 * 0.20 * 1.04)
    assert carry.long == pytest.approx(30_000)


def test_carried_short_term_loss_used_next_year():
    _, carry = fy_tax(st_gain=-40_000, lt_gain=0, carry=Carry())
    tax, carry2 = fy_tax(st_gain=100_000, lt_gain=0, carry=carry)
    assert tax == pytest.approx(60_000 * 0.20 * 1.04)
    assert carry2 == Carry()


def test_zero_gains_owe_no_tax_and_carry_nothing():
    assert fy_tax(0.0, 0.0, Carry()) == (0.0, Carry())
    assert INDIA_EQUITY.stcg_rate == 0.20 and INDIA_EQUITY.ltcg_rate == 0.125
