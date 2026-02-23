import asyncio
import logging
from typing import Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field
import datetime

from ..brokers.core.interface import BrokerDriver

logger = logging.getLogger(__name__)

class StrategyStatus(Enum):
    STOPPED = "Stopped"
    RUNNING = "Running"
    ERROR = "Error"

@dataclass
class StrategyState:
    name: str
    status: StrategyStatus = StrategyStatus.STOPPED
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    active_orders: int = 0
    current_position: str = "Flat"
    last_signal: str = "Awaiting..."
    trades_taken: int = 0
    open_trades: int = 0
    closed_trades: int = 0
    recent_logs: List[str] = field(default_factory=list)
    
    def dict(self):
        return {
            "name": self.name,
            "status": self.status.value,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "active_orders": self.active_orders,
            "current_position": self.current_position,
            "last_signal": self.last_signal,
            "trades_taken": self.trades_taken,
            "open_trades": self.open_trades,
            "closed_trades": self.closed_trades
        }

class BaseStrategy:
    """
    Unified abstract interface enforcing lifecycle mapping and zero-telemetry control bindings.
    """
    def __init__(self, name: str, broker: BrokerDriver, config: dict):
        self.name = name
        self.broker = broker
        self.config = config
        self.state = StrategyState(name=name)
        self._is_running = False
        self._run_task = None
        self._loop_sleep_delay = 1.0

    async def _main_loop(self):
        """Asynchronous wrapper guaranteeing safe execution intervals"""
        try:
            while self._is_running:
                await self.on_tick()
                await asyncio.sleep(self._loop_sleep_delay)
        except Exception as e:
            logger.error(f"Strategy {self.name} encountered error: {e}", exc_info=True)
            self.state.status = StrategyStatus.ERROR
            self.state.last_signal = f"Error: {str(e)}"
            self._is_running = False

    async def start(self) -> None:
        """Initializes dependencies and spawns the run loop safely"""
        if self._is_running:
            return
            
        logger.info(f"Starting Strategy: {self.name}")
        self.state.status = StrategyStatus.RUNNING
        self._is_running = True
        self.on_start()
        
        # Dispatch main loop to the current async context
        loop = asyncio.get_running_loop()
        self._run_task = loop.create_task(self._main_loop())

    async def stop(self) -> None:
        """Flags the loop exit, cancels pendings if overridden."""
        if not self._is_running:
            return
            
        logger.info(f"Stopping Strategy: {self.name}")
        self._is_running = False
        self.state.status = StrategyStatus.STOPPED
        
        if self._run_task:
            await self._run_task
            
        self.on_stop()

    def get_state(self) -> dict:
        """Returns normalized structured state dict to be broadcast via WebSockets"""
        return self.state.dict()
        
    def _update_signal(self, message: str):
        time_str = datetime.datetime.now().strftime("%H:%M:%S")
        self.state.last_signal = f"[{time_str}] {message}"
        self.state.recent_logs.append(self.state.last_signal)
        if len(self.state.recent_logs) > 50:
             self.state.recent_logs.pop(0)

    # ---------------------------------------------------------
    # Methods to be implemented by child classes
    # ---------------------------------------------------------

    def on_start(self):
        """Hook for initialization parameters. E.g. connect broker."""
        pass

    def on_stop(self):
        """Hook for shutdown logic. E.g., cancel orders."""
        pass

    async def on_tick(self):
        """Strategic logic executed inside the async loop interval"""
        raise NotImplementedError("Child strategies must implement on_tick")
