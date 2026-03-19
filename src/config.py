import os
from dotenv import load_dotenv

load_dotenv()

PRIVATE_KEY: str = os.environ["PRIVATE_KEY"]
POLYMARKET_HOST: str = os.getenv("POLYMARKET_HOST", "https://clob.polymarket.com")
POLYMARKET_CHAIN_ID: int = int(os.getenv("POLYMARKET_CHAIN_ID", "137"))
POLYGON_RPC: str = os.environ["POLYGON_RPC"]
ORBMARKETS_WS: str = os.getenv("ORBMARKETS_WS", "wss://stream.orbmarkets.io/ws/btc")

# Risk parameters
MAX_RISK_FRACTION: float = float(os.getenv("MAX_RISK_FRACTION", "0.30"))
MIN_EDGE_THRESHOLD: float = float(os.getenv("MIN_EDGE_THRESHOLD", "0.03"))

# Execution tuning
GAS_MULTIPLIER: float = float(os.getenv("GAS_MULTIPLIER", "1.5"))   # 1.5x base gas for fast inclusion
POLL_INTERVAL_S: float = float(os.getenv("POLL_INTERVAL_S", "0.5")) # Polymarket price poll fallback
