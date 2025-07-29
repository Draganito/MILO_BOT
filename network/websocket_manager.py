# src/network/websocket_manager.py
import asyncio
import json
import websockets
import threading
from typing import Dict, Any, Optional, List, Set
from config import Config, logger

class WebSocketManager:
    def __init__(self, live_candle_callback: callable) -> None:
        self.live_candles: Dict[str, Dict[str, Any]] = {}
        self.subscriptions: Set[str] = set()
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running: bool = True
        self.connected: asyncio.Event = asyncio.Event()
        self.live_candle_callback: callable = live_candle_callback
        self.time_offset: int = 0
        self.lock = threading.Lock()  # For thread-safe access to live_candles

    async def connect(self) -> None:
        while self.running:
            self.connected.clear()
            try:
                async with websockets.connect(Config.WS_BASE_URL + "/ws") as ws:
                    self.ws = ws
                    self.connected.set()
                    if self.subscriptions:
                        await self.subscribe(list(self.subscriptions))
                    async for message in ws:
                        data = json.loads(message)
                        if data.get("e") == "kline":
                            await self.process_kline(data)
            except Exception as e:
                self.connected.clear()
                logger.error(f"WS disconnected: {e}. Reconnecting in {Config.WS_RECONNECT_DELAY}s...")
                await asyncio.sleep(Config.WS_RECONNECT_DELAY)

    async def subscribe(self, streams: List[str]) -> None:
        await self.connected.wait()
        self.subscriptions.update(streams)
        params = {"method": "SUBSCRIBE", "params": streams, "id": 1}
        await self.ws.send(json.dumps(params))

    async def process_kline(self, data: Dict[str, Any]) -> None:
        k = data["k"]
        symbol = k["s"]
        interval = k["i"]
        key = f"{symbol}_{interval}"
        # Check for valid floats
        try:
            candle = {
                "time": k["t"],
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "closed": k["x"]
            }
            if any(float('nan') == v for v in [candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]]):
                raise ValueError("Invalid float values in kline")
        except (ValueError, KeyError) as e:
            logger.warning(f"Invalid kline data for {key}: {e}")
            return
        with self.lock:
            self.live_candles[key] = candle.copy()
        if k["x"]:
            asyncio.create_task(self.live_candle_callback(symbol, interval, candle))
            logger.info(f"Updated live candle for {symbol} {interval}")

    def get_live_candle(self, symbol: str, interval: str) -> Optional[Dict[str, Any]]:
        key = f"{symbol}_{interval}"
        with self.lock:
            return self.live_candles.get(key).copy() if key in self.live_candles else None

    def stop(self) -> None:
        self.running = False
        if self.ws:
            asyncio.create_task(self.ws.close())