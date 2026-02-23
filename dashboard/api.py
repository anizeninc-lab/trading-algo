import asyncio
import json
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Trading Unified Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logger = logging.getLogger(__name__)

# Strategy Manager stub: Singleton controlling algorithmic logic
class StrategyManager:
    def __init__(self):
        self.strategies = {} # Will hold instantiated BaseStrategy descendants
        self._lock = asyncio.Lock()
        self.global_pnl = 0.0
        self.risk_controller = None

    def register(self, strategy_obj):
        self.strategies[strategy_obj.name] = strategy_obj
        
    def set_risk_controller(self, risk_obj):
        self.risk_controller = risk_obj

    def set_auto_start_flags(self, strategy_names: list):
        # We spawn a background task to await the loop starting
        async def auto_start_task():
            await asyncio.sleep(2) # brief buffer for fastAPI to mount
            for name in strategy_names:
                await self.start_strategy(name)
        asyncio.create_task(auto_start_task())

    async def start_strategy(self, name: str):
        if name in self.strategies:
            await self.strategies[name].start()
            return {"status": "started"}
        return {"error": "Strategy not found"}
        
    async def stop_strategy(self, name: str):
        if name in self.strategies:
            await self.strategies[name].stop()
            return {"status": "stopped"}
        return {"error": "Strategy not found"}

    def get_all_states(self):
        states = {name: strat.get_state() for name, strat in self.strategies.items()}
        # Calculate and forward Global PNL to risk controller simultaneously
        current_global_pnl = sum([s['realized_pnl'] + s['unrealized_pnl'] for s in states.values()])
        if self.risk_controller:
             # Route exact split if needed, using combined for basic halt validation
             self.risk_controller.update_global_pnl(current_global_pnl, 0.0)
        return states

manager = StrategyManager()

# -------- REST API Routes -------- #

class StrategyAction(BaseModel):
    action: str  # "start" or "stop"

@app.post("/api/strategy/{name}")
async def control_strategy(name: str, payload: StrategyAction):
    if payload.action == "start":
         return await manager.start_strategy(name)
    elif payload.action == "stop":
         return await manager.stop_strategy(name)
    return {"error": "Invalid action"}

@app.get("/api/status")
async def get_status():
    """Initial fetch for frontend load"""
    return {
         "strategies": manager.get_all_states(),
         "global_pnl": sum([s['realized_pnl'] + s['unrealized_pnl'] for s in manager.get_all_states().values()]),
         "brokers": {"upstox": "Connected", "icici": "Disconnected"} # Simulated state
    }

# -------- WEBSOCKETS -------- #

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

ws_manager = ConnectionManager()

@app.websocket("/ws/status")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Pipelined data stream to UI
            data = {
                 "strategies": manager.get_all_states(),
                 "global_pnl": sum([s['realized_pnl'] + s['unrealized_pnl'] for s in manager.get_all_states().values()])
            }
            await ws_manager.broadcast(json.dumps(data))
            await asyncio.sleep(1.0) # Refresh frequency 1 sec
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WS Error: {e}")
        ws_manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
