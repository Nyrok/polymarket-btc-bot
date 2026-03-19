"""
executor.py
-----------
Submits limit orders to the Polymarket CLOB.

Fast-execution strategy for Polygon (NOT Solana/Jito):
  - Use a private/dedicated Polygon RPC (Alchemy/QuickNode) to minimise latency.
  - Bump gas price to 1.5× current base fee for fast inclusion.
  - Use py-clob-client which handles EIP-712 signing and order submission.

NOTE: Jito is a Solana MEV bundler and cannot be used with Polymarket (Polygon).
      For Polygon MEV-protection / faster inclusion, you can submit via
      Polygon's native mempool with boosted gas, or route through a Polygon
      block-builder if available.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    OrderArgs,
    OrderType,
    BUY,
)

from .strategy import Signal
from .risk_manager import PositionSize

log = logging.getLogger(__name__)


@dataclass
class TradeResult:
    success: bool
    order_id: Optional[str]
    side: str
    condition_id: str
    token_id: str
    amount_usdc: float
    price: float
    reference_price: float
    strike: float
    edge: float
    latency_ms: float
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "order_id": self.order_id,
            "side": self.side,
            "condition_id": self.condition_id,
            "token_id": self.token_id,
            "amount_usdc": self.amount_usdc,
            "entry_price": self.price,
            "reference_price": self.reference_price,
            "strike": self.strike,
            "edge": round(self.edge, 4),
            "latency_ms": round(self.latency_ms, 1),
            "error": self.error,
            "timestamp": time.time(),
        }


def build_clob_client(host: str, private_key: str, chain_id: int) -> ClobClient:
    from eth_account import Account
    account = Account.from_key(private_key)
    return ClobClient(
        host=host,
        key=private_key,
        chain_id=chain_id,
        funder=account.address,
    )


async def execute_trade(
    client: ClobClient,
    signal: Signal,
    size: PositionSize,
) -> TradeResult:
    if size.usdc_amount < 1.0:
        return TradeResult(
            success=False,
            order_id=None,
            side=signal.side,
            condition_id=signal.condition_id,
            token_id=signal.token_id,
            amount_usdc=size.usdc_amount,
            price=signal.market_price,
            reference_price=signal.reference_price,
            strike=signal.strike,
            edge=signal.edge,
            latency_ms=0.0,
            error="Position too small (<$1)",
        )

    t0 = time.perf_counter()
    try:
        # Aggressive limit: price slightly above market to ensure fill
        limit_price = round(min(signal.market_price + 0.005, 0.99), 3)
        size_shares = round(size.usdc_amount / limit_price, 2)

        order_args = OrderArgs(
            token_id=signal.token_id,
            price=limit_price,
            size=size_shares,
            side=BUY,
        )
        resp = client.create_and_post_order(order_args, OrderType.GTC)
        latency_ms = (time.perf_counter() - t0) * 1000

        order_id = resp.get("orderID") or resp.get("id")
        log.info(
            "Order placed: %s %s @ %.3f | id=%s | latency=%.1fms",
            signal.side, size_shares, limit_price, order_id, latency_ms,
        )
        return TradeResult(
            success=True,
            order_id=order_id,
            side=signal.side,
            condition_id=signal.condition_id,
            token_id=signal.token_id,
            amount_usdc=size.usdc_amount,
            price=limit_price,
            reference_price=signal.reference_price,
            strike=signal.strike,
            edge=signal.edge,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000
        log.error("Order failed: %s", exc)
        return TradeResult(
            success=False,
            order_id=None,
            side=signal.side,
            condition_id=signal.condition_id,
            token_id=signal.token_id,
            amount_usdc=size.usdc_amount,
            price=signal.market_price,
            reference_price=signal.reference_price,
            strike=signal.strike,
            edge=signal.edge,
            latency_ms=latency_ms,
            error=str(exc),
        )
