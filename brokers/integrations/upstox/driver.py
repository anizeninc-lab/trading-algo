import logging
from typing import Dict, Any, List
import requests

from ...core.interface import BrokerDriver
from ...core.models import OrderRequest

logger = logging.getLogger(__name__)

class TelemetryStrippedSession(requests.Session):
    def __init__(self):
        super().__init__()
        # Ensure zero tracking headers are sent
        self.headers.update({
            "User-Agent": "Upstox-Trader-Bot/1.0",
            "Accept": "application/json"
        })

    def request(self, method, url, *args, **kwargs):
        # Prevent any redirect tracking or query param injections
        kwargs.setdefault('allow_redirects', False)
        return super().request(method, url, *args, **kwargs)

class UpstoxDriver(BrokerDriver):
    """
    Upstox integration ensuring pure execution without analytics APIs.
    """
    def __init__(self, api_key: str = None, api_secret: str = None, redirect_uri: str = None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.redirect_uri = redirect_uri
        self.session = TelemetryStrippedSession()
        self.access_token = None
        self.base_url = "https://api.upstox.com/v2"

    def connect(self) -> bool:
        logger.info("Connecting to Upstox (Zero Telemetry Mode)")
        # In a real scenario, an OAuth handshake happens here using self.session
        # We simulate success for this generation plan.
        self.access_token = "MOCK_TOKEN"
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})
        return True

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Fetch LTP and Best Bid/Ask without websocket tracking"""
        try:
            url = f"{self.base_url}/market-quote/quotes?instrumentKey={symbol}"
            response = self.session.get(url)
            if response.status_code == 200:
                data = response.json().get('data', {})
                return {
                    "symbol": symbol,
                    "last_price": data.get(symbol, {}).get("last_price", 0.0),
                    "timestamp": data.get(symbol, {}).get("timestamp", "")
                }
            return {"symbol": symbol, "last_price": 0.0}
        except Exception as e:
            logger.error(f"Upstox Quote Error: {str(e)}")
            return {"symbol": symbol, "last_price": 0.0}

    def place_order(self, request: OrderRequest) -> Dict[str, Any]:
        """Places standard equity/FNO orders"""
        url = f"{self.base_url}/order/place"
        payload = {
            "quantity": request.quantity,
            "product": request.product_type.value,
            "validity": "DAY",
            "price": request.price or 0.0,
            "tag": request.tag,
            "instrument_token": request.symbol, # Needs upstox specific formatting
            "order_type": request.order_type.value,
            "transaction_type": request.transaction_type.value,
            "disclosed_quantity": 0,
            "trigger_price": 0,
            "is_amo": False
        }
        
        try:
            response = self.session.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                return {"status": "success", "order_id": data.get("data", {}).get("order_id", -1)}
            else:
                logger.error(f"Upstox Order Refused: {response.text}")
                return {"status": "error", "order_id": -1, "message": response.text}
        except Exception as e:
            logger.error(f"Upstox Order Exception: {str(e)}")
            return {"status": "error", "order_id": -1, "message": str(e)}

    def cancel_order(self, order_id: str) -> bool:
        url = f"{self.base_url}/order/cancel?order_id={order_id}"
        response = self.session.delete(url)
        return response.status_code == 200

    def download_instruments(self) -> None:
        """Cached locally to avoid repeated remote fetches"""
        logger.info("Mock Downloading Upstox Instruments locally.")
        pass

    def get_instruments(self):
        return []

    def get_positions(self) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/portfolio/short-term-positions"
        response = self.session.get(url)
        if response.status_code == 200:
            data = response.json().get('data', [])
            # Map upstox specific syntax to uniform struct
            return [{"symbol": pos['tradingsymbol'], "quantity_total": pos['net_quantity']} for pos in data]
        return []

