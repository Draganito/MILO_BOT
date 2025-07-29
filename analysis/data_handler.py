import asyncio
import math
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from config import Config, logger
from network.api_client import ApiClient
from network.websocket_manager import WebSocketManager
from data.db_manager import DBManager
from .indicators import Indicators

class DataHandler:
    def __init__(self, api_client: ApiClient, db_manager: DBManager, ws_manager: WebSocketManager):
        self.api_client = api_client
        self.db_manager = db_manager
        self.ws_manager = ws_manager
        self.chart_data: List[Dict[str, Any]] = []
        self.live_candle: Optional[Dict[str, Any]] = None
        self.indicators = Indicators()

    async def fetch_historical_data(self, symbol: str, interval: str = "1h") -> None:
        try:
            await self.api_client.update_historical_klines(symbol, interval)
            klines = await self.db_manager.get_klines_from_db(symbol, interval, Config.DATA_LIMIT)
            self.chart_data = [
                {
                    "time": int(k[0]),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "closed": True
                } for k in klines if not any(math.isnan(float(v)) for v in k[1:]) and float(k[2]) >= float(k[3])
            ]
            if not self.chart_data:
                raise Exception("No valid data")
            stream = f"{symbol.lower()}@kline_{interval}"
            await self.ws_manager.subscribe([stream])
            start_time = time.time()
            self.live_candle = self.ws_manager.get_live_candle(symbol, interval)
            while not self.live_candle and time.time() - start_time < Config.WS_LIVE_CANDLE_TIMEOUT:
                await asyncio.sleep(0.1)
                self.live_candle = self.ws_manager.get_live_candle(symbol, interval)
            if not self.live_candle:
                logger.warning("Timed out waiting for live candle")
        except Exception as e:
            logger.error(f"Failed to load chart data: {e}")
            self.chart_data = []
            self.live_candle = None

    async def print_indicators(self, symbol: str, interval: str) -> None:
        await self.fetch_historical_data(symbol, interval)
        data = self.chart_data.copy()
        if self.live_candle:
            data.append(self.live_candle)
        if not data:
            logger.warning(f"No data available for {symbol} on {interval}")
            return
        if self.live_candle:
            logger.info(f"Live Candle OHLC for {symbol} on {interval}:")
            logger.info(f"Open: {self.live_candle['open']:.4f}")
            logger.info(f"High: {self.live_candle['high']:.4f}")
            logger.info(f"Low: {self.live_candle['low']:.4f}")
            logger.info(f"Close: {self.live_candle['close']:.4f}")
            logger.info(f"Volume: {self.live_candle['volume']:.4f}")
            logger.info(f"Time: {datetime.fromtimestamp(self.live_candle['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')} (live update)")
        else:
            logger.info("No live candle available.")
        logger.info(f"Indicator Values for {symbol} on {interval} (including live candle if available):")
        sma_task = asyncio.create_task(self.indicators.calculate_sma(data, Config.SMA_PERIOD))
        ema_task = asyncio.create_task(self.indicators.calculate_ema(data, 14))
        dema_task = asyncio.create_task(self.indicators.calculate_dema([c["close"] for c in data], 14))
        rsi_task = asyncio.create_task(self.indicators.calculate_rsi(data))
        macd_task = asyncio.create_task(self.indicators.calculate_macd(data))
        avg_volume_task = asyncio.create_task(self.indicators.calculate_average_volume(data))
        obv_task = asyncio.create_task(self.indicators.calculate_obv(data))
        atr_task = asyncio.create_task(self.indicators.calculate_atr(data))
        zigzag_task = asyncio.create_task(self.indicators.calculate_zigzag(data))
        stochastic_task = asyncio.create_task(self.indicators.calculate_stochastic(data))
        sma = (await sma_task)[-1]
        logger.info(f"SMA ({Config.SMA_PERIOD}): {sma:.4f}")
        ema = (await ema_task)[-1]
        logger.info(f"EMA (14): {ema:.4f}")
        dema = (await dema_task)[-1]
        logger.info(f"DEMA (14): {dema:.4f}")
        rsi = await rsi_task
        logger.info(f"RSI ({Config.RSI_PERIOD}): {rsi[-1]:.4f}" if rsi else "N/A")
        macd_line, signal_line = await macd_task
        macd = macd_line[-1]
        signal = signal_line[-1]
        histogram = macd - signal
        logger.info(f"MACD: Line={macd:.4f}, Signal={signal:.4f}, Histogram={histogram:.4f}")
        avg_volume = await avg_volume_task
        logger.info(f"Average Volume ({Config.AVG_VOLUME_PERIOD}): {avg_volume:.4f}")
        obv = (await obv_task)[-1]
        logger.info(f"OBV: {obv:.4f}")
        atr = (await atr_task)[-1]
        logger.info(f"ATR (14): {atr:.4f}")
        k, d = await stochastic_task
        logger.info(f"Stochastic: %K={k[-1]:.4f}, %D={d[-1]:.4f}")
        zigzag_points = await zigzag_task
        classified_points = await self.indicators.classify_swing_points(zigzag_points, data)
        logger.info("ZigZag Points (factor=2.2):")
        for point in classified_points:
            time_str = datetime.fromtimestamp(data[point['index']]['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f" {point['label']} at index {point['index']}, value {point['value']:.4f}, time {time_str}")
        divergences = await self.indicators.detect_divergences(rsi, zigzag_points, data)
        logger.info("RSI Divergences:")
        for div in divergences:
            start_time = datetime.fromtimestamp(data[div['startIndex']]['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            end_time = datetime.fromtimestamp(data[div['endIndex']]['time'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
            logger.info(f" {div['type']} divergence: Start {div['startPrice']:.4f} (RSI {div['startRSI']:.2f}) at {start_time}, End {div['endPrice']:.4f} (RSI {div['endRSI']:.2f}) at {end_time}")

    def get_chart_data_for_js(self) -> Dict[str, Any]:
        historical = [
            {
                "time": datetime.fromtimestamp(c["time"] / 1000),
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": c["volume"]
            } for c in self.chart_data
        ]
        live = None
        if self.live_candle:
            live = {
                "time": datetime.fromtimestamp(self.live_candle["time"] / 1000),
                "open": self.live_candle["open"],
                "high": self.live_candle["high"],
                "low": self.live_candle["low"],
                "close": self.live_candle["close"],
                "volume": self.live_candle["volume"]
            }
        closes = [c["close"] for c in self.chart_data]
        rsi = self.indicators.calculate_rsi_sync(self.chart_data)
        zigzag_points = self.indicators.calculate_zigzag_sync(closes)
        classified_points = self.indicators.classify_swing_points_sync(zigzag_points, self.chart_data)
        zigzag_data = [
            {
                "index": p["index"],
                "value": p["value"],
                "type": p["type"],
                "label": p["label"],
                "time": datetime.fromtimestamp(self.chart_data[p["index"]]["time"] / 1000)
            } for p in classified_points
        ]
        divergences = self.indicators.detect_divergences_sync(rsi, zigzag_points, self.chart_data)
        divergences_data = [
            {
                "type": d["type"],
                "startIndex": d["startIndex"],
                "endIndex": d["endIndex"],
                "startPrice": d["startPrice"],
                "endPrice": d["endPrice"],
                "startRSI": d["startRSI"],
                "endRSI": d["endRSI"],
                "startTime": datetime.fromtimestamp(self.chart_data[d["startIndex"]]["time"] / 1000),
                "endTime": datetime.fromtimestamp(self.chart_data[d["endIndex"]]["time"] / 1000)
            } for d in divergences
        ]
        return {"historical": historical, "liveCandle": live, "zigzag": zigzag_data, "divergences": divergences_data}