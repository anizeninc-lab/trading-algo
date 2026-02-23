from __future__ import annotations

from typing import Callable, Dict

from .core.interface import BrokerDriver
import logging



class BrokerRegistry:
    _registry: Dict[str, Callable[[], BrokerDriver]] = {}

    @classmethod
    def register(cls, name: str, factory: Callable[[], BrokerDriver]) -> None:
        cls._registry[name.lower()] = factory

    @classmethod
    def create(cls, name: str) -> BrokerDriver:
        key = name.lower()
        if key not in cls._registry:
            # Attempt to auto-register defaults
            try:
                register_default_brokers()
            except Exception:
                pass
        if key not in cls._registry:
            raise ValueError(f"Unknown broker '{name}'. Registered: {list(cls._registry)}")
        return cls._registry[key]()


def register_default_brokers() -> None:
    try:
        from .integrations.upstox.driver import UpstoxDriver
        BrokerRegistry.register("upstox", lambda: UpstoxDriver())
    except Exception:
        logging.error("Error registering upstox driver", exc_info=True)

    try:
        from .integrations.icici.driver import ICICIDriver
        BrokerRegistry.register("icici", lambda: ICICIDriver())
    except Exception:
        logging.error("Error registering icici driver", exc_info=True)

    try:
        from .integrations.backtest.driver import BacktestDriver
        BrokerRegistry.register("backtest", lambda: BacktestDriver())
    except Exception:
        logging.error("Error registering backtest driver", exc_info=True)


