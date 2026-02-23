import logging
import uvicorn
import yaml
import os
import argparse
import asyncio
from fastapi.staticfiles import StaticFiles

from dashboard.api import app, manager
from strategy.survivor import SurvivorStrategy
from strategy.wave import WaveStrategy
from strategy.saviour import SaviourComboStrategy
from brokers.registry import BrokerRegistry
from brokers.risk import MasterRiskController

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load configurations
with open("strategy/configs/survivor.yml", "r") as f:
    survivor_config = yaml.safe_load(f).get("default", {})
    
with open("strategy/configs/wave.yml", "r") as f:
    wave_config = yaml.safe_load(f).get("default", {})

def main():
    parser = argparse.ArgumentParser(description="Autonomous Trading Hub")
    parser.add_argument("--paper", action="store_true", help="Launch entirely in Backtest/Paper Trading sandbox mode")
    parser.add_argument("--auto-start", action="store_true", help="Auto-start designated strategies on boot without UI click")
    args = parser.parse_args()

    logger.info(f"Initializing AlgoTrading Hub (Autonomous Mode: {args.auto_start})")
    
    # 1. Initialize Primary Broker or Sandbox
    broker_name = "backtest" if args.paper else os.getenv("ACTIVE_BROKER", "upstox")
    raw_broker = BrokerRegistry.create(broker_name)
    
    # 2. Wrap in Master Risk Controller
    safe_broker = MasterRiskController(raw_broker)
    
    # 3. Instantiate Strategies
    survivor = SurvivorStrategy(safe_broker, survivor_config)
    wave = WaveStrategy(safe_broker, wave_config)
    saviour = SaviourComboStrategy(safe_broker, {"max_drawdown_percent": 5.0, "check_frequency": 5})

    # 4. Register with Manager
    manager.register(survivor)
    manager.register(wave)
    manager.register(saviour)
    
    # Pass the risk controller to the manager so it can feed the global PNL for halting
    manager.set_risk_controller(safe_broker)

    # 5. Handle Autonomous Starting
    if args.auto_start:
         logger.info("Autonomous Start Triggered. Strategies will arm automatically once event loop initializes.")
         manager.set_auto_start_flags(["Survivor", "Wave Extractor", "Saviour Combo"])

    # 6. Mount Static Frontend (Dashboard UI)
    app.mount("/", StaticFiles(directory="dashboard", html=True), name="dashboard")

    # 7. Start ASGI Server
    logger.info("Starting local Dashboard at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)

if __name__ == "__main__":
    main()
