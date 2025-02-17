from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
import json
from datetime import datetime
import asyncio

app = FastAPI()

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TradingMonitor:
    def __init__(self, trader):
        self.trader = trader
        self.trade_history = []
    
    async def get_current_status(self):
        return {
            "timestamp": datetime.now().isoformat(),
            "base_price": self.trader.base_price,
            "current_price": self.trader.current_price,
            "grid_size": self.trader.grid_size,
            "volatility": await self.trader._calculate_volatility(),
            "win_rate": await self.trader.calculate_win_rate(),
            "total_assets": await self.trader.get_total_assets(),
            "position_ratio": await self.trader._get_position_ratio()
        }
    
    def add_trade(self, trade):
        self.trade_history.append(trade)
        if len(self.trade_history) > 50:  # 保留最近50条
            self.trade_history.pop(0)

@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await websocket.accept()
    while True:
        status = await monitor.get_current_status()
        await websocket.send_json(status)
        await asyncio.sleep(2)  # 2秒更新一次

@app.get("/api/trades")
async def get_trades():
    return monitor.trade_history[-10:]  # 返回最近10笔交易 