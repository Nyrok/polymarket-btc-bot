"""
trade_logger.py
---------------
Appends JSON trade records to trades.jsonl (one JSON object per line).
Also tracks a running P&L summary.
"""

import json
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

LOG_PATH = Path("trades.jsonl")


@dataclass
class PnLTracker:
    total_staked: float = 0.0
    total_returned: float = 0.0
    open_positions: dict = field(default_factory=dict)   # order_id → entry cost

    @property
    def realised_pnl(self) -> float:
        return self.total_returned - self.total_staked

    def open(self, order_id: str, cost: float) -> None:
        self.open_positions[order_id] = cost
        self.total_staked += cost

    def close(self, order_id: str, payout: float) -> None:
        self.open_positions.pop(order_id, None)
        self.total_returned += payout

    def summary(self) -> dict:
        return {
            "total_staked": round(self.total_staked, 2),
            "total_returned": round(self.total_returned, 2),
            "realised_pnl": round(self.realised_pnl, 2),
            "open_positions": len(self.open_positions),
        }


_tracker = PnLTracker()


def log_trade(record: dict, cost_usdc: Optional[float] = None) -> None:
    """Append a trade record to the JSONL log."""
    record["log_ts"] = time.time()
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    if cost_usdc and record.get("order_id"):
        _tracker.open(record["order_id"], cost_usdc)
    log.info("TRADE LOGGED: %s", json.dumps(record))


def log_resolution(order_id: str, payout_usdc: float) -> None:
    """Call when a market resolves to track P&L."""
    _tracker.close(order_id, payout_usdc)
    record = {
        "event": "resolution",
        "order_id": order_id,
        "payout_usdc": payout_usdc,
        "pnl_snapshot": _tracker.summary(),
        "log_ts": time.time(),
    }
    with LOG_PATH.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def get_pnl_summary() -> dict:
    return _tracker.summary()
