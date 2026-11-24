"""PredictSim: replay prediction-market order books and simulate how a
strategy would really have filled, after queue position, latency, fees and
settlement. Venue profiles for Kalshi, Polymarket and Hyperliquid HIP-4, with
portfolio mode, multi-outcome groups, parameter sweeps and walk-forward."""

from predictsim.backtest import BacktestConfig, Engine, run_backtest, run_many
from predictsim.book import BookError, OrderBook
from predictsim.events import Band, BookSide, Delta, Event, GridChange, Settle, Side, Snapshot, Trade
from predictsim.latency import Fixed, LatencyConfig, LogNormal, Uniform
from predictsim.metrics import BacktestResult, ManyResult, Summary
from predictsim.multi import HIP4Question, NegRiskEvent
from predictsim.orders import Fill, Order, OrderStatus, OrderType, Outcome
from predictsim.portfolio import PortfolioResult, run_portfolio
from predictsim.queue import QueueModel
from predictsim.spec import Grid, MarketSpec, uniform_grid
from predictsim.stats import Performance, TradeStats
from predictsim.strategy import Context, Strategy
from predictsim.sweep import SweepResult, param_grid, run_sweep
from predictsim.trades import RoundTrip
from predictsim.units import from_centis, from_micros, to_centis, to_micros
from predictsim.venues import HIP4Profile, KalshiProfile, PolymarketProfile, PositionMode
from predictsim.walkforward import Fold, WalkForwardResult, walk_forward, walk_forward_splits

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
    "Fold",
    "Grid",
    "GridChange",
    "HIP4Profile",
    "HIP4Question",
    "KalshiProfile",
    "LatencyConfig",
    "LogNormal",
    "ManyResult",
    "MarketSpec",
    "NegRiskEvent",
    "Order",
    "OrderBook",
    "OrderStatus",
    "OrderType",
    "Outcome",
    "Performance",
    "PolymarketProfile",
    "PortfolioResult",
    "PositionMode",
    "QueueModel",
    "RoundTrip",
    "Settle",
    "Side",
    "Snapshot",
    "Strategy",
    "Summary",
    "SweepResult",
    "Trade",
    "TradeStats",
    "Uniform",
    "WalkForwardResult",
    "from_centis",
    "from_micros",
    "param_grid",
    "run_backtest",
    "run_many",
    "run_portfolio",
    "run_sweep",
    "to_centis",
    "to_micros",
    "uniform_grid",
    "walk_forward",
    "walk_forward_splits",
]
