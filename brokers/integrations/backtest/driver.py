from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime
import pandas as pd
import logging

logger = logging.getLogger(__name__)
from ...core.enums import Exchange, OrderType, ProductType, TransactionType
from ...core.interface import BrokerDriver
from ...core.schemas import (
    BrokerCapabilities,
    Funds,
    OrderRequest,
    OrderResponse,
    Position,
    Quote,
    Instrument,
)

class BacktestDriver(BrokerDriver):
    """
    Backtest driver for simulating trades using historical data.
    """

    def __init__(self, initial_capital: float = 100000.0) -> None:
        super().__init__()
        self.capabilities = BrokerCapabilities(
            supports_historical=True,
            supports_quotes=True,
            supports_funds=True,
            supports_positions=True,
            supports_place_order=True,
            supports_cancel_order=True,
            supports_orderbook=True,
            supports_tradebook=True,
            supports_master_contract=True,
        )
        self.initial_capital = initial_capital
        self.current_cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.orders: List[Dict[str, Any]] = []
        self.trades: List[Dict[str, Any]] = []
        self.current_time: Optional[datetime] = None
        self.current_prices: Dict[str, float] = {}
        self.instruments_df = None
        self.csv_provider = None

    def set_csv_provider(self, provider):
        self.csv_provider = provider

    def set_current_time(self, dt: datetime):
        self.current_time = dt

    def set_price(self, symbol: str, price: float):
        self.current_prices[symbol] = price
        # Update P&L for open positions
        if symbol in self.positions:
            pos = self.positions[symbol]
            pos.pnl = (price - pos.average_price) * pos.quantity_total
            if pos.quantity_total < 0: # Short position
                pos.pnl = (pos.average_price - price) * abs(pos.quantity_total)

    def get_funds(self) -> Funds:
        equity = self.current_cash
        used_margin = 0.0
        for pos in self.positions.values():
            equity += pos.pnl + (pos.quantity_total * pos.average_price)
            # Simple margin model: 1 Lakh per lot (50 qty) for short positions
            if pos.quantity_total < 0:
                used_margin += abs(pos.quantity_total / 50.0) * 100000.0
                
        return Funds(
            equity=equity,
            available_cash=self.current_cash,
            used_margin=used_margin,
            net=equity,
            raw={"initial_capital": self.initial_capital}
        )

    def get_positions(self) -> List[Position]:
        return list(self.positions.values())

    def place_order(self, request: OrderRequest) -> OrderResponse:
        quote = self.get_quote(request.symbol)
        price = quote.last_price
        if price == 0.0 or price is None:
            return OrderResponse(status="error", order_id=None, message=f"No price for {request.symbol}")

        # Margin Check (Simple model: 1 Lakh per lot)
        if request.transaction_type == "SELL":
            required_margin = (request.quantity / 50.0) * 100000.0
            funds = self.get_funds()
            available_margin = funds.equity - funds.used_margin
            if required_margin > available_margin:
                logger.warning(f"Insufficient Margin: Required {required_margin}, Available {available_margin}")
                return OrderResponse(status="error", order_id=None, message="Insufficient Margin")

        order_id = f"BT{len(self.orders) + 1}"
        order_entry = {
            "order_id": order_id,
            "symbol": request.symbol,
            "exchange": request.exchange,
            "transaction_type": request.transaction_type,
            "quantity": request.quantity,
            "order_type": request.order_type,
            "price": price, # Market execution at current simulated price
            "status": "COMPLETE",
            "timestamp": self.current_time.isoformat() if self.current_time else datetime.now().isoformat(),
            "tag": request.tag
        }
        self.orders.append(order_entry)
        
        # Immediate execution for market orders in backtest
        self._execute_trade(order_entry)
        
        return OrderResponse(status="ok", order_id=order_id, raw=order_entry)

    def _execute_trade(self, order: Dict[str, Any]):
        symbol = order["symbol"]
        qty = order["quantity"]
        price = order["price"]
        side = order["transaction_type"]

        trade_value = qty * price
        if side == TransactionType.BUY:
            self.current_cash -= trade_value
            if symbol in self.positions:
                pos = self.positions[symbol]
                new_qty = pos.quantity_total + qty
                if new_qty == 0:
                    del self.positions[symbol]
                else:
                    # Average price update
                    pos.average_price = (pos.average_price * pos.quantity_total + trade_value) / new_qty
                    pos.quantity_total = new_qty
                    pos.quantity_available = new_qty
            else:
                self.positions[symbol] = Position(
                    symbol=symbol,
                    exchange=order["exchange"],
                    quantity_total=qty,
                    quantity_available=qty,
                    average_price=price,
                    product_type=ProductType.MARGIN
                )
        else: # SELL
            self.current_cash += trade_value
            if symbol in self.positions:
                pos = self.positions[symbol]
                new_qty = pos.quantity_total - qty
                if new_qty == 0:
                    del self.positions[symbol]
                else:
                    # If we are selling from a long position, average price stays same for remaining
                    # If we are shorting (new_qty < 0), we need to track short avg price
                    pos.quantity_total = new_qty
                    pos.quantity_available = new_qty
            else:
                # Direct shorting
                self.positions[symbol] = Position(
                    symbol=symbol,
                    exchange=order["exchange"],
                    quantity_total=-qty,
                    quantity_available=-qty,
                    average_price=price,
                    product_type=ProductType.MARGIN
                )
        
        self.trades.append(order)


    def cancel_order(self, order_id: str) -> OrderResponse:
        return OrderResponse(status="ok", order_id=order_id, message="Order already executed or cancelled")

    def modify_order(self, order_id: str, updates: Dict[str, Any]) -> OrderResponse:
        return OrderResponse(status="error", order_id=order_id, message="Modification not supported in simple backtest")

    def get_orderbook(self) -> List[Dict[str, Any]]:
        return self.orders

    def get_tradebook(self) -> List[Dict[str, Any]]:
        return self.trades

    def get_quote(self, symbol: str) -> Quote:
        price = self.current_prices.get(symbol, 0.0)
        if (price == 0.0 or price is None) and self.csv_provider and self.current_time:
             # Try to get from CSV if it's an option symbol or the index
             if "NIFTY" in symbol and any(x in symbol for x in ["CE", "PE"]):
                 price = self.csv_provider.get_option_price(symbol, self.current_time)
             elif "NIFTY" in symbol:
                 price = self.csv_provider.get_index_price(self.current_time)
        
        return Quote(
            symbol=symbol.split(":")[-1] if ":" in symbol else symbol,
            exchange=Exchange.NFO if any(x in symbol for x in ["CE", "PE"]) else Exchange.NSE,
            last_price=price or 0.0,
            timestamp=self.current_time
        )

    def get_option_chain(self, symbol: str, expiry: datetime) -> Any:
        if self.csv_provider and self.current_time:
            return self.csv_provider.get_option_chain(self.current_time)
        return None

    def get_history(self, symbol: str, interval: str, start: str, end: str) -> List[Dict[str, Any]]:
        return [] # Driver doesn't hold history, Engine provides it

    def download_instruments(self) -> None:
        if self.csv_provider and self.current_time:
            chain = self.csv_provider.get_option_chain(self.current_time)
            if chain:
                df_ce = chain['CE']
                df_pe = chain['PE']
                # Create instruments DF
                inst_list = []
                for _, row in pd.concat([df_ce, df_pe]).iterrows():
                    inst_list.append({
                        'symbol': row['synth_symbol'],
                        'strike': row['Strike Price'],
                        'lot_size': 50,
                        'instrument_type': row['Option type'],
                        'segment': 'NFO-OPT'
                    })
                self.instruments_df = pd.DataFrame(inst_list)

    def get_instruments(self) -> Any:
        return self.instruments_df

    def set_instruments(self, df):
        self.instruments_df = df
