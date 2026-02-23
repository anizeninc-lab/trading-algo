import logging
import time
from typing import Dict, Any, List
import requests

from ...core.interface import BrokerDriver
from ...core.models import OrderRequest

logger = logging.getLogger(__name__)

class ICICIDriver(BrokerDriver):
    """
    ICICIDirect integration using Breeze-like REST endpoints.
    Ensures zero analytic tracking and enforces internal rate limits.
    """
    def __init__(self, app_key: str = None, secret_key: str = None, session_token: str = None):
        self.app_key = app_key
        self.secret_key = secret_key
        self.session_token = session_token
        self.session = requests.Session()
        
        # Strip telemetry
        self.session.headers.update({
            "User-Agent": "ICICI-Bot/1.0",
            "Accept": "application/json"
        })
        
        self.base_url = "https://api.icicidirect.com/breezeapi/api/v1"
        self.last_api_call = 0
        self.RATE_LIMIT_DELAY = 0.5 # 2 calls per second max

    def _rate_limit(self):
        """Internal queue enforcement to prevent HTTP 429s"""
        now = time.time()
        elapsed = now - self.last_api_call
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)
        self.last_api_call = time.time()

    def connect(self) -> bool:
        logger.info("Connecting to ICICIDirect (Zero Telemetry Mode)")
        self.session.headers.update({
            "apikey": self.app_key,
            "sessiontoken": self.session_token
        })
        return True

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        self._rate_limit()
        try:
            # Requires mapping standard NFO symbol to ICICI convention
            url = f"{self.base_url}/quotes"
            payload = {"stock_code": symbol, "exchange_code": "NFO"}
            response = self.session.get(url, json=payload)
            if response.status_code == 200:
                data = response.json().get('Success', [{}])[0]
                return {
                    "symbol": symbol,
                    "last_price": float(data.get("ltp", 0.0)),
                    "timestamp": data.get("datetime", "")
                }
            return {"symbol": symbol, "last_price": 0.0}
        except Exception as e:
            logger.error(f"ICICI Quote Error: {str(e)}")
            return {"symbol": symbol, "last_price": 0.0}

    def place_order(self, request: OrderRequest) -> Dict[str, Any]:
        self._rate_limit()
        url = f"{self.base_url}/order"
        payload = {
            "stock_code": request.symbol, # Mapping needed here
            "exchange_code": request.exchange.value if hasattr(request.exchange, 'value') else "NFO",
            "product_type": request.product_type.value if hasattr(request.product_type, 'value') else "options",
            "action": request.transaction_type.value if hasattr(request.transaction_type, 'value') else "buy",
            "quantity": str(request.quantity),
            "price": str(request.price) if request.price else "0",
            "order_type": request.order_type.value if hasattr(request.order_type, 'value') else "limit",
            "validity": "day",
            "disclosed_quantity": "0",
        }
        
        try:
            response = self.session.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                return {"status": "success", "order_id": data.get("Success", {}).get("order_id", -1)}
            else:
                logger.error(f"ICICI Order Refused: {response.text}")
                return {"status": "error", "order_id": -1, "message": response.text}
        except Exception as e:
            logger.error(f"ICICI Order Exception: {str(e)}")
            return {"status": "error", "order_id": -1, "message": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        self._rate_limit()
        url = f"{self.base_url}/order"
        payload = {"order_id": order_id}
        response = self.session.delete(url, json=payload)
        return response.status_code == 200

    def download_instruments(self) -> None:
        logger.info("Mock Downloading ICICIDirect Instruments locally.")
        pass

    def get_instruments(self):
        return []

    def get_positions(self) -> List[Dict[str, Any]]:
        self._rate_limit()
        url = f"{self.base_url}/portfolio/positions"
        response = self.session.get(url)
        if response.status_code == 200:
            data = response.json().get('Success', [])
            return [{"symbol": pos['stock_code'], "quantity_total": int(pos['quantity'])} for pos in data]
        return []

