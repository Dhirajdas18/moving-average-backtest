"""Indian capital-gains tax on listed equity (STT paid), applied with today's rules to every year.

Short-term (held 12 months or less, s.111A): 20%. Long-term (s.112A): 12.5% above a ₹1.25 lakh
exemption per financial year (April-March). Both from 23 July 2024. Plus 4% health and education
cess. Short-term losses offset short- or long-term gains; long-term losses only long-term gains; the
rest carries forward. Interest on cash is taxed at an assumed 30% slab rate. Surcharge, advance
tax dates and the 8-year carry-forward limit are ignored. Not tax advice.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaxRules:
    stcg_rate: float = 0.20
    ltcg_rate: float = 0.125
    ltcg_exemption: float = 125_000.0
    cess: float = 0.04
    long_term_months: int = 12  # held more than this many months = long-term
    interest_slab: float = 0.30  # interest on idle cash is taxed at your slab rate (assumed 30%)


INDIA_EQUITY = TaxRules()


@dataclass(frozen=True)
class Carry:
    """Unused losses carried into the next financial year (positive numbers)."""

    short: float = 0.0
    long: float = 0.0


def fy_tax(st_gain: float, lt_gain: float, carry: Carry, rules: TaxRules = INDIA_EQUITY):
    """Tax for one financial year's net short- and long-term gains. Returns (tax, carry forward)."""
    st, lt = st_gain, lt_gain
    # this year's losses first: a short-term loss may reduce long-term gains
    if st < 0 and lt > 0:
        used = min(-st, lt)
        st, lt = st + used, lt - used
    # then losses brought forward: short-term carry hits short then long gains, long only long
    cs, cl = carry.short, carry.long
    use = min(cs, max(st, 0.0))
    st, cs = st - use, cs - use
    use = min(cs, max(lt, 0.0))
    lt, cs = lt - use, cs - use
    use = min(cl, max(lt, 0.0))
    lt, cl = lt - use, cl - use
    new_carry = Carry(short=cs + max(-st, 0.0), long=cl + max(-lt, 0.0))
    taxable_lt = max(lt - rules.ltcg_exemption, 0.0)
    tax = (rules.stcg_rate * max(st, 0.0) + rules.ltcg_rate * taxable_lt) * (1 + rules.cess)
    return tax, new_carry
