"""
main.py — Polymarket BTC 5-min latency-arb bot
------------------------------------------------
Architecture:
  ┌─────────────────────────────────────────────┐
  │  PriceState (shared in-memory object)        │
  │   • reference_price  ← Orbmarkets WS feed   │
  │   • market_yes/no    ← Polymarket CLOB poll  │
  └───────────────┬─────────────────────────────┘
                  │ read every 250 ms
           Strategy.evaluate()
                  │ signal found
           RiskManager.size_position()
                  │
           Executor.execute_trade()
                  │
           TradeLogger.log_trade()

Fast-execution note:
  Polymarket is on Polygon. We achieve low-latency execution by:
    1. Using a private, geographically-close RPC (set POLYGON_RPC in .env)
    2. Bumping gas price (1.5× base fee) via py-clob-client's gas settings
    3. Keeping a persistent aiohttp session to avoid TCP handshake overhead
  Jito/Solana MEV bundling is NOT applicable here — Jito only works on Solana.
"""

import asyncio
import logging
import time

import aiohttp

from src.config import (
    PRIVATE_KEY,
    POLYMARKET_HOST,
    POLYMARKET_CHAIN_ID,
    ORBMARKETS_WS,
    MAX_RISK_FRACTION,
    MIN_EDGE_THRESHOLD,
    POLL_INTERVAL_S,
)
from src.price_monitor import PriceState, run_orbmarkets_feed, run_polymarket_price_poll
from src.strategy import evaluate
from src.risk_manager import size_position
from src.executor import build_clob_client, execute_trade
from src.trade_logger import log_trade, get_pnl_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
)
log = logging.getLogger("main")

STRATEGY_LOOP_INTERVAL = 0.25  # seconds between strategy evaluations
CAPITAL_REFRESH_INTERVAL = 30  # seconds between balance fetches


async def fetch_usdc_balance(client) -> float:
    """Fetch current USDC balance from Polymarket."""
    try:
        bal = client.get_balance()
        return float(bal)
    except Exception as exc:
        log.warning("Balance fetch failed: %s", exc)
        return 0.0


async def strategy_loop(state: PriceState, client, capital_holder: list) -> None:
    """
    Main decision loop: evaluate → size → execute → log.
    capital_holder is a 1-element list so we can mutate it from this coroutine.
    """
    last_trade_condition: str = ""   # avoid double-trading same window
    last_capital_refresh = 0.0

    while True:
        now = time.time()

        # Refresh balance periodically
        if now - last_capital_refresh > CAPITAL_REFRESH_INTERVAL:
            capital_holder[0] = await fetch_usdc_balance(client)
            last_capital_refresh = now
            log.info("Capital: $%.2f USDC | P&L: %s", capital_holder[0], get_pnl_summary())

        capital = capital_holder[0]
        if capital < 1.0:
            await asyncio.sleep(STRATEGY_LOOP_INTERVAL)
            continue

        async with state.lock:
            # Build token ID map from state (simplified — real impl: cache from market fetch)
            yes_token_id = f"{state.condition_id}_YES" if state.condition_id else ""
            no_token_id  = f"{state.condition_id}_NO"  if state.condition_id else ""
            signal = evaluate(state, yes_token_id, no_token_id, MIN_EDGE_THRESHOLD)

        if signal is None:
            await asyncio.sleep(STRATEGY_LOOP_INTERVAL)
            continue

        # Don't re-enter same market window
        if signal.condition_id == last_trade_condition:
            await asyncio.sleep(STRATEGY_LOOP_INTERVAL)
            continue

        log.info(
            "SIGNAL  side=%s  ref=$%.2f  strike=$%.2f  market_p=%.3f  edge=%.3f",
            signal.side, signal.reference_price, signal.strike,
            signal.market_price, signal.edge,
        )

        size = size_position(signal, capital, MAX_RISK_FRACTION)
        result = await execute_trade(client, signal, size)

        log_trade(result.to_dict(), cost_usdc=size.usdc_amount if result.success else None)

        if result.success:
            last_trade_condition = signal.condition_id
            capital_holder[0] -= size.usdc_amount  # optimistic deduction

        await asyncio.sleep(STRATEGY_LOOP_INTERVAL)


async def main() -> None:
    log.info("Starting Polymarket BTC 5-min arb bot")

    clob_client = build_clob_client(POLYMARKET_HOST, PRIVATE_KEY, POLYMARKET_CHAIN_ID)
    capital = await fetch_usdc_balance(clob_client)
    log.info("Initial capital: $%.2f USDC", capital)

    state = PriceState()
    capital_holder = [capital]

    async with aiohttp.ClientSession() as session:
        await asyncio.gather(
            run_orbmarkets_feed(state, ORBMARKETS_WS),
            run_polymarket_price_poll(state, session, POLYMARKET_HOST, POLL_INTERVAL_S),
            strategy_loop(state, clob_client, capital_holder),
        )


if __name__ == "__main__":
    asyncio.run(main())
