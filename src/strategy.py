"""
strategy.py
-----------
Latency-arbitrage strategy for BTC 5-minute Polymarket markets.

Core logic:
  reference_price (Orbmarkets) leads Polymarket by ~1-3 seconds.
  If reference_price > strike  AND  Polymarket YES price < fair_yes - edge_threshold → BUY YES
  If reference_price < strike  AND  Polymarket NO  price < fair_no  - edge_threshold → BUY NO

Fair price is modelled as a simple binary:
  fair_yes ≈ 1.0  if reference > strike (almost certain)
  fair_yes ≈ 0.0  if reference < strike

In practice you'd use a tighter probabilistic model, but this captures the
timing-edge framing from the spec.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional, Literal

from .price_monitor import PriceState

log = logging.getLogger(__name__)

Side = Literal["YES", "NO"]


@dataclass
class Signal:
    side: Side
    condition_id: str
    token_id: str
    market_price: float      # current Polymarket price we'll pay
    fair_value: float        # our estimate
    edge: float              # fair_value - market_price  (positive = opportunity)
    reference_price: float
    strike: float
    timestamp: float


def evaluate(
    state: PriceState,
    yes_token_id: str,
    no_token_id: str,
    min_edge: float,
) -> Optional[Signal]:
    """
    Called by the main loop after acquiring state.lock.
    Returns a Signal if a tradeable opportunity exists, else None.
    """
    if any(v is None for v in (
        state.reference_price,
        state.market_yes_price,
        state.market_no_price,
        state.question_usd_level,
        state.condition_id,
    )):
        return None

    ref   = state.reference_price
    strike = state.question_usd_level
    yes_p  = state.market_yes_price
    no_p   = state.market_no_price

    # Stale guard: discard if either feed is > 3 s old
    now = time.time()
    if now - state.reference_ts > 3.0 or now - state.market_ts > 3.0:
        log.debug("Stale data — skipping")
        return None

    # Simple binary fair-value: 0.95/0.05 to leave room for resolution uncertainty
    if ref > strike:
        fair_yes = 0.95
        side: Side = "YES"
        market_price = yes_p
        token_id = yes_token_id
    else:
        fair_yes = 0.05
        side = "NO"
        market_price = no_p
        token_id = no_token_id

    fair = fair_yes if side == "YES" else (1 - fair_yes)
    edge = fair - market_price

    if edge < min_edge:
        return None

    return Signal(
        side=side,
        condition_id=state.condition_id,
        token_id=token_id,
        market_price=market_price,
        fair_value=fair,
        edge=edge,
        reference_price=ref,
        strike=strike,
        timestamp=now,
    )
