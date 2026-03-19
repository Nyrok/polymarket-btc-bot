"""
risk_manager.py
---------------
Kelly-inspired position sizing capped at MAX_RISK_FRACTION of current capital.

Kelly fraction: f* = (b*p - q) / b
  where b = net odds (1/price - 1), p = win prob (fair_value), q = 1 - p

We then cap at MAX_RISK_FRACTION regardless.
"""

import logging
from dataclasses import dataclass

from .strategy import Signal

log = logging.getLogger(__name__)


@dataclass
class PositionSize:
    usdc_amount: float
    kelly_fraction: float
    capped: bool


def size_position(
    signal: Signal,
    capital_usdc: float,
    max_risk_fraction: float,
    kelly_fraction_cap: float = 0.25,  # never bet more than 25% even if Kelly says more
) -> PositionSize:
    """
    Returns the USDC amount to stake for this signal.
    """
    p = signal.fair_value
    q = 1 - p
    price = signal.market_price  # cost per share (0-1)

    if price <= 0 or price >= 1:
        return PositionSize(usdc_amount=0.0, kelly_fraction=0.0, capped=False)

    # Net odds if we win: (1 - price) / price
    b = (1 - price) / price
    kelly_f = (b * p - q) / b
    kelly_f = max(0.0, kelly_f)

    # Apply caps
    capped = False
    if kelly_f > kelly_fraction_cap:
        kelly_f = kelly_fraction_cap
        capped = True
    if kelly_f > max_risk_fraction:
        kelly_f = max_risk_fraction
        capped = True

    usdc_amount = round(capital_usdc * kelly_f, 2)

    log.info(
        "Sizing: Kelly=%.3f → capped=%.3f → $%.2f USDC (capital $%.2f)",
        kelly_f, kelly_f, usdc_amount, capital_usdc,
    )
    return PositionSize(usdc_amount=usdc_amount, kelly_fraction=kelly_f, capped=capped)
