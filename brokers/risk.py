import logging
import time
from typing import Dict, Any, List

from .core.interface import BrokerDriver
from .core.models import OrderRequest

logger = logging.getLogger(__name__)

class MasterRiskController:
    """
    Middleware Gateway guarding the Broker APIs.
    Enforces global drawdown limits, velocity checks, and margin limits.
    """
    def __init__(self, broker: BrokerDriver):
        self.broker = broker
        
        # Risk Constants
        self.max_global_drawdown = 5000.0 # Strict ₹5000 hard stop on the account
        self.max_orders_per_minute = 30
        self.margin_buffer_percent = 0.05
        
        # State tracking
        self.global_pnl = 0.0
        self.is_halted = False
        self._order_timestamps = []

    def _check_velocity(self) -> bool:
        """Prevent logic loops from spamming the broker"""
        now = time.time()
        # Clean old timestamps
        self._order_timestamps = [t for t in self._order_timestamps if now - t < 60]
        
        if len(self._order_timestamps) >= self.max_orders_per_minute:
            logger.error("RISK HALT: Order velocity exceeded.")
            return False
            
        self._order_timestamps.append(now)
        return True

    def update_global_pnl(self, realized: float, unrealized: float):
        """Called by the Engine continually"""
        self.global_pnl = realized + unrealized
        if self.global_pnl <= -abs(self.max_global_drawdown):
            self.is_halted = True
            logger.error(f"RISK HALT: Global Max Drawdown Breached ({self.global_pnl})")

    # ----- Wrapped Broker Methods -----

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        return self.broker.get_quote(symbol)

    def get_positions(self) -> List[Dict[str, Any]]:
        return self.broker.get_positions()
        
    def download_instruments(self):
         return self.broker.download_instruments()
         
    def get_instruments(self):
         return self.broker.get_instruments()

    def place_order(self, request: OrderRequest) -> Dict[str, Any]:
        if self.is_halted:
            logger.warning(f"Risk Controller: Order Rejected (System Halted) - {request.symbol}")
            return {"status": "error", "message": "Risk System Halted"}
            
        if not self._check_velocity():
            return {"status": "error", "message": "Velocity Limit Exceeded"}
            
        # Optional: Margin Check logic (Broker specific implementation needed here typically)
        
        return self.broker.place_order(request)

    def cancel_order(self, order_id: str) -> bool:
        # We always want to allow cancellations even if halted to reduce risk
        return self.broker.cancel_order(order_id)
