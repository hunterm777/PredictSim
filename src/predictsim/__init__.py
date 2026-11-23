"""PredictSim: replay binary prediction-market order books and simulate how
a strategy would really have filled, after queue position, latency, fees and
settlement. Venue profiles for Kalshi, Polymarket and Hyperliquid HIP-4."""

from predictsim.backtest import BacktestConfig, Engine, run_backtest, run_many
from predictsim.book import BookError, OrderBook
from predictsim.events import Band, BookSide, Delta, Event, GridChange, Settle, Side, Snapshot, Trade
from predictsim.latency import Fixed, LatencyConfig, LogNormal, Uniform
from predictsim.metrics import BacktestResult, ManyResult, Summary
from predictsim.orders import Fill, Order, OrderStatus, OrderType, Outcome
from predictsim.queue import QueueModel
from predictsim.spec import Grid, MarketSpec, uniform_grid
from predictsim.strategy import Context, Strategy
from predictsim.units import from_centis, from_micros, to_centis, to_micros
from predictsim.venues import HIP4Profile, KalshiProfile, PolymarketProfile, PositionMode

__version__ = "0.1.0"

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "Band",
    "BookError",
    "BookSide",
    "Context",
    "Delta",
    "Engine",
    "Event",
    "Fill",
    "Fixed",
    "Grid",
    "GridChange",
    "HIP4Profile",
    "KalshiProfile",
    "LatencyConfig",
    "LogNormal",
    "ManyResult",
    "MarketSpec",
    "Order",
    "OrderBook",
    "OrderStatus",
    "OrderType",
    "Outcome",
    "PolymarketProfile",
    "PositionMode",
    "QueueModel",
    "Settle",
    "Side",
    "Snapshot",
    "Strategy",
    "Summary",
    "Trade",
    "Uniform",
    "from_centis",
    "from_micros",
    "run_backtest",
    "run_many",
    "to_centis",
    "to_micros",
    "uniform_grid",
]
