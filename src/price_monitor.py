"""
price_monitor.py
----------------
Maintains two price streams:
  - reference_price : live BTC mid from Orbmarkets.io (WebSocket)
  - market_price    : implied BTC price from the active Polymarket 5-min market

Both are updated in-place so the strategy loop can compare them at any moment.
"""

import asyncio
import json
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import aiohttp
import websockets

log = logging.getLogger(__name__)


@dataclass
class PriceState:
    reference_price: Optional[float] = None   # Orbmarkets mid price
    reference_ts: float = 0.0

    market_yes_price: Optional[float] = None  # Polymarket YES token price [0-1]
    market_no_price: Optional[float] = None   # Polymarket NO  token price [0-1]
    market_ts: float = 0.0

    condition_id: Optional[str] = None        # active Polymarket condition
    question_usd_level: Optional[float] = None  # strike e.g. 70_500

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def run_orbmarkets_feed(state: PriceState, ws_url: str) -> None:
    """Connect to Orbmarkets WebSocket and keep reference_price fresh."""
    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20) as ws:
                log.info("Orbmarkets WebSocket connected")
                async for raw in ws:
                    data = json.loads(raw)
                    # Expected payload: {"symbol": "BTCUSDT", "bid": ..., "ask": ..., "ts": ...}
                    bid = float(data.get("bid") or data.get("price", 0))
                    ask = float(data.get("ask") or data.get("price", 0))
                    mid = (bid + ask) / 2 if (bid and ask) else (bid or ask)
                    if mid:
                        async with state.lock:
                            state.reference_price = mid
                            state.reference_ts = time.time()
        except Exception as exc:
            log.warning("Orbmarkets feed error: %s — reconnecting in 1s", exc)
            await asyncio.sleep(1)


async def run_polymarket_price_poll(
    state: PriceState,
    session: aiohttp.ClientSession,
    host: str,
    poll_interval: float,
) -> None:
    """
    Poll the Polymarket CLOB for the current YES/NO prices of the active
    5-minute BTC market.  Also re-discovers the active condition every cycle
    in case the window rolled over.
    """
    while True:
        try:
            condition_id = await _find_active_5min_btc_market(session, host)
            if condition_id:
                prices = await _fetch_market_prices(session, host, condition_id)
                if prices:
                    yes_p, no_p, strike = prices
                    async with state.lock:
                        state.condition_id = condition_id
                        state.question_usd_level = strike
                        state.market_yes_price = yes_p
                        state.market_no_price = no_p
                        state.market_ts = time.time()
        except Exception as exc:
            log.warning("Polymarket poll error: %s", exc)
        await asyncio.sleep(poll_interval)


async def _find_active_5min_btc_market(
    session: aiohttp.ClientSession, host: str
) -> Optional[str]:
    """Return the condition_id of the soonest-expiring BTC 5-min market."""
    url = f"{host}/markets"
    params = {"active": "true", "tag": "btc", "closed": "false"}
    async with session.get(url, params=params) as resp:
        body = await resp.json()

    markets = body.get("data", [])
    candidates = [
        m for m in markets
        if "BTC" in m.get("question", "").upper()
        and "5" in m.get("question", "")
        and m.get("active")
        and not m.get("closed")
    ]
    if not candidates:
        return None
    # Pick the one expiring soonest
    candidates.sort(key=lambda m: m.get("end_date_iso", ""))
    return candidates[0]["condition_id"]


async def _fetch_market_prices(
    session: aiohttp.ClientSession,
    host: str,
    condition_id: str,
) -> Optional[tuple[float, float, float]]:
    """Return (yes_price, no_price, strike_usd) or None."""
    url = f"{host}/markets/{condition_id}"
    async with session.get(url) as resp:
        m = await resp.json()

    tokens = m.get("tokens", [])
    if len(tokens) < 2:
        return None

    yes_tok = next((t for t in tokens if t.get("outcome", "").upper() == "YES"), tokens[0])
    no_tok  = next((t for t in tokens if t.get("outcome", "").upper() == "NO"),  tokens[1])

    yes_price = float(yes_tok.get("price", 0.5))
    no_price  = float(no_tok.get("price",  0.5))

    # Parse the strike from the question, e.g. "Will BTC be above $70,500 at 14:05?"
    import re
    question = m.get("question", "")
    match = re.search(r"\$([0-9,]+(?:\.[0-9]+)?)", question)
    strike = float(match.group(1).replace(",", "")) if match else 0.0

    return yes_price, no_price, strike
