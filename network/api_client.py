import aiohttp
import asyncio
import time
import math
import urllib.parse
import hmac
import hashlib
import datetime
import calendar
from typing import List, Dict, Any, Optional, Tuple
from config import Config, get_interval_ms, logger
from data.db_manager import DBManager
from security.key_manager import KeyManager

class ApiClient:
    def __init__(self, db_manager: DBManager) -> None:
        self.api_key, self.api_secret = KeyManager.load_keys(Config.KEY_FILE)
        self.db_manager = db_manager
        self.symbol_constraints: Dict[str, Dict[str, Any]] = {}
        self.time_offset: int = 0
        self.session = aiohttp.ClientSession()
        self.all_symbols: List[str] = []
        self.min_timestamp = int(datetime.datetime(2019, 1, 1).timestamp() * 1000)  # Binance Futures Startdatum (ca. 2019)

    async def close(self) -> None:
        await self.session.close()

    async def sync_time(self) -> None:
        try:
            data = await self.fetch_with_retry("/fapi/v1/time")
            server_time = data['serverTime']
            local_time = int(time.time() * 1000)
            self.time_offset = server_time - local_time
            logger.info(f"Time offset set to {self.time_offset} ms")
        except Exception as e:
            logger.error(f"Failed to sync time: {e}")

    async def signed_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None, method: str = "GET", retries: int = 5) -> Any:
        params = params or {}
        params["timestamp"] = int(time.time() * 1000) + self.time_offset
        params["recvWindow"] = Config.RECV_WINDOW
        query_string = urllib.parse.urlencode(params)
        signature = hmac.new(self.api_secret.encode("utf-8"), query_string.encode("utf-8"), hashlib.sha256).hexdigest()
        params["signature"] = signature
        headers = {"X-MBX-APIKEY": self.api_key}
        return await self.fetch_with_retry(endpoint, params, headers, method, retries=retries)

    async def fetch_with_retry(self, path: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None, method: str = "GET", body: Optional[Any] = None, retries: int = 5) -> Any:
        async with Config.RATE_LIMIT_SEMAPHORE:
            for attempt in range(retries):
                url = f"https://{Config.BASE_URL}{path}"
                try:
                    async with self.session.request(method, url, params=params, headers=headers, data=body) as response:
                        if response.status == 429:
                            logger.warning(f"Rate limit hit, retrying after {Config.API_DELAY}s")
                            await asyncio.sleep(Config.API_DELAY)
                            continue
                        if response.status != 200:
                            error_data = await response.text()
                            raise Exception(f"HTTP {response.status}: {error_data}")
                        data = await response.json()
                        return data
                except Exception as e:
                    if attempt == retries - 1:
                        raise
                    await asyncio.sleep(Config.API_DELAY)

    async def fetch_klines(self, symbol: str, interval: str, limit: int, start_time: Optional[int] = None, end_time: Optional[int] = None) -> List[List[float]]:
        if start_time and end_time and start_time > end_time:
            logger.warning(f"Skipping klines fetch for {symbol} {interval}: start_time {start_time} > end_time {end_time}")
            return []
        path = "/fapi/v1/klines"
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        return await self.fetch_with_retry(path, params)

    async def fetch_mark_price(self, symbol: str) -> float:
        path = "/fapi/v1/premiumIndex"
        params = {"symbol": symbol}
        data = await self.fetch_with_retry(path, params)
        price = float(data["markPrice"])
        if price <= 0 or price >= 1e9:
            raise Exception("Invalid mark price")
        return price

    async def fetch_account(self) -> Dict[str, Any]:
        return await self.signed_request("/fapi/v2/account")

    async def fetch_positions(self) -> List[Dict[str, Any]]:
        return await self.signed_request("/fapi/v2/positionRisk")

    async def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        return await self.signed_request("/fapi/v1/openOrders", params)

    async def fetch_user_trades(self, symbol: str) -> List[Dict[str, Any]]:
        params = {"symbol": symbol}
        return await self.signed_request("/fapi/v1/userTrades", params)

    async def cancel_all_open_orders(self, symbol: str) -> Dict[str, Any]:
        return await self.signed_request("/fapi/v1/allOpenOrders", {"symbol": symbol}, "DELETE")

    async def post_order(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return await self.signed_request("/fapi/v1/order", params, "POST")

    async def set_leverage(self, symbol: str, leverage: int) -> Dict[str, Any]:
        return await self.signed_request("/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, "POST")

    async def change_margin_type(self, symbol: str, margin_type: str) -> Optional[Dict[str, Any]]:
        try:
            return await self.signed_request("/fapi/v1/marginType", {"symbol": symbol, "marginType": margin_type}, "POST")
        except Exception as e:
            if "-4046" in str(e) or "NO_NEED_TO_CHANGE_MARGIN_TYPE" in str(e):
                logger.info(f"Margin type already set to {margin_type}. Proceeding.")
            else:
                logger.warning(f"Failed to set {margin_type} mode: {e}. Proceeding with trade.")
            return None

    async def fetch_leverage_bracket(self, symbol: str) -> List[Dict[str, Any]]:
        data = await self.signed_request("/fapi/v1/leverageBracket", {"symbol": symbol})
        return data[0]["brackets"]

    async def fetch_exchange_info(self) -> Dict[str, Any]:
        path = "/fapi/v1/exchangeInfo"
        return await self.fetch_with_retry(path)

    async def update_symbol_constraints_if_needed(self) -> None:
        last_updated = await self.db_manager.get_symbol_constraints_last_updated()
        current_time = int(time.time())
        if current_time - last_updated > Config.DAILY_UPDATE_THRESHOLD:
            logger.info("Updating symbol constraints from API...")
            try:
                data = await self.fetch_exchange_info()
                constraints = {}
                for s in data["symbols"]:
                    if s["contractType"] != "PERPETUAL" or s["quoteAsset"] != "USDT":
                        continue
                    lot_size = next((f for f in s["filters"] if f["filterType"] == "LOT_SIZE"), None)
                    min_notional = next((f for f in s["filters"] if f["filterType"] == "MIN_NOTIONAL"), None)
                    if lot_size and min_notional:
                        constraints[s["symbol"]] = {
                            "minQty": float(lot_size["minQty"]),
                            "stepSize": float(lot_size["stepSize"]),
                            "quantityPrecision": s["quantityPrecision"],
                            "minNotional": float(min_notional["notional"]),
                            "pricePrecision": s["pricePrecision"],
                        }
                await self.db_manager.insert_symbol_constraints(constraints)
                self.symbol_constraints = constraints
            except Exception as e:
                logger.error(f"Failed to update symbol constraints: {e}")
            self.symbol_constraints = await self.db_manager.get_symbol_constraints_from_db()
        else:
            logger.info("Using symbol constraints from DB.")
            self.symbol_constraints = await self.db_manager.get_symbol_constraints_from_db()
        self.all_symbols = list(self.symbol_constraints.keys())

    def get_symbol_constraints(self, symbol: str) -> Dict[str, Any]:
        if symbol not in self.symbol_constraints:
            asyncio.create_task(self.update_symbol_constraints_if_needed())
        return self.symbol_constraints.get(symbol, {
            "minQty": 0.001,
            "stepSize": 0.001,
            "quantityPrecision": 3,
            "minNotional": 5,
            "pricePrecision": 2,
        })

    async def initialize_historical_data(self, symbols: Optional[List[str]] = None) -> None:
        if symbols is None:
            symbols = self.all_symbols
        for symbol in symbols:
            for interval in Config.VALID_INTERVALS:
                await self.update_historical_klines(symbol, interval)
            await asyncio.sleep(Config.INITDB_SLEEP)

    async def update_historical_klines(self, symbol: str, interval: str) -> None:
        last_ts = await self.db_manager.get_last_timestamp(symbol, interval)
        current_time = int(time.time() * 1000)
        interval_ms = get_interval_ms(interval)
        if interval_ms == 0:
            logger.warning(f"Invalid interval {interval}, skipping update.")
            return
        if interval.endswith('M'):
            if last_ts is None:
                logger.info(f"Initializing historical data for {symbol} {interval}...")
                total_klines = Config.INITIAL_KLINES_LIMIT
                batch_size = Config.KLINES_BATCH_SIZE
                klines = []
                current_dt = datetime.datetime.now()
                current_month_start = current_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                for offset in range(0, total_klines, batch_size):
                    batch_limit = min(batch_size, total_klines - offset)
                    month_end = current_month_start - datetime.timedelta(days=1)
                    month_end = month_end.replace(hour=23, minute=59, second=59, microsecond=999999)
                    start_ms = int((month_end - datetime.timedelta(days=calendar.monthrange(month_end.year, month_end.month)[1] * batch_limit)).timestamp() * 1000)
                    end_ms = int(month_end.timestamp() * 1000)
                    if end_ms < self.min_timestamp:
                        logger.info(f"Reached earliest available data for {symbol} {interval} at {end_ms}. Stopping fetch.")
                        break
                    batch_klines = await self.fetch_klines(symbol, interval, batch_limit, start_ms, end_ms)
                    if batch_klines:
                        klines.extend(batch_klines)
                    current_month_start = month_end - datetime.timedelta(seconds=1)
                    await asyncio.sleep(Config.API_DELAY)
                if klines:
                    await self.db_manager.insert_klines(symbol, interval, klines)
                    logger.info(f"Initialized {len(klines)} klines for {symbol} {interval}")
            else:
                last_dt = datetime.datetime.fromtimestamp(last_ts / 1000)
                current_dt = datetime.datetime.now()
                months_gap = (current_dt.year - last_dt.year) * 12 + (current_dt.month - last_dt.month)
                if months_gap <= 0:
                    logger.info(f"No new closed months for {symbol} {interval}. Skipping update.")
                    return
                new_klines = []
                current_month_start = last_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=calendar.monthrange(last_dt.year, last_dt.month)[1])
                for _ in range(months_gap):
                    month_end = current_month_start + datetime.timedelta(days=calendar.monthrange(current_month_start.year, current_month_start.month)[1] - 1)
                    month_end = month_end.replace(hour=23, minute=59, second=59, microsecond=999999)
                    start_ms = int(current_month_start.timestamp() * 1000)
                    end_ms = int(month_end.timestamp() * 1000)
                    if end_ms < self.min_timestamp:
                        logger.info(f"Reached earliest available data for {symbol} {interval} at {end_ms}. Stopping fetch.")
                        break
                    klines = await self.fetch_klines(symbol, interval, 1, start_ms, end_ms)
                    if klines:
                        new_klines.extend(klines)
                    current_month_start = month_end + datetime.timedelta(seconds=1)
                    current_month_start = current_month_start.replace(day=1)
                if new_klines:
                    await self.db_manager.insert_klines(symbol, interval, new_klines)
                    logger.info(f"Updated {len(new_klines)} new klines for {symbol} {interval}")
            await self.db_manager.trim_klines(symbol, interval, Config.MAX_HISTORY_LENGTH)
        else:
            current_candle_start = (current_time // interval_ms) * interval_ms
            last_closed_end = current_candle_start - 1
            if last_ts is None:
                logger.info(f"Initializing historical data for {symbol} {interval}...")
                total_klines = Config.INITIAL_KLINES_LIMIT
                batch_size = Config.KLINES_BATCH_SIZE
                klines = []
                for offset in range(0, total_klines, batch_size):
                    batch_limit = min(batch_size, total_klines - offset)
                    end_time = last_closed_end - offset * interval_ms
                    if end_time < self.min_timestamp:
                        logger.info(f"Reached earliest available data for {symbol} {interval} at {end_time}. Stopping fetch.")
                        break
                    batch_klines = await self.fetch_klines(symbol, interval, batch_limit, end_time=end_time)
                    if batch_klines:
                        klines.extend(batch_klines)
                    await asyncio.sleep(Config.API_DELAY)
                if klines:
                    await self.db_manager.insert_klines(symbol, interval, klines)
                    logger.info(f"Initialized {len(klines)} klines for {symbol} {interval}")
            else:
                logger.info(f"Updating historical data for {symbol} {interval}...")
                expected_next_ts = last_ts + interval_ms
                if expected_next_ts > last_closed_end:
                    logger.info(f"No new closed candles for {symbol} {interval}. Skipping update.")
                    return
                gap_ms = last_closed_end - last_ts
                gap_candles = math.ceil(gap_ms / interval_ms)
                if gap_candles > Config.MAX_HISTORY_LENGTH:
                    logger.warning(f"Large gap detected ({gap_candles} candles), fetching latest {Config.MAX_HISTORY_LENGTH} candles for {symbol} {interval}...")
                    await self.executor(None, self._sync_delete_old_klines, symbol, interval)
                    total_klines = Config.MAX_HISTORY_LENGTH
                    batch_size = Config.KLINES_BATCH_SIZE
                    klines = []
                    for offset in range(0, total_klines, batch_size):
                        batch_limit = min(batch_size, total_klines - offset)
                        end_time = last_closed_end - offset * interval_ms
                        if end_time < self.min_timestamp:
                            logger.info(f"Reached earliest available data for {symbol} {interval} at {end_time}. Stopping fetch.")
                            break
                        batch_klines = await self.fetch_klines(symbol, interval, batch_limit, end_time=end_time)
                        if batch_klines:
                            klines.extend(batch_klines)
                        await asyncio.sleep(Config.API_DELAY)
                    if klines:
                        await self.db_manager.insert_klines(symbol, interval, klines)
                        logger.info(f"Updated {len(klines)} new klines for {symbol} {interval}")
                else:
                    new_klines = await self.fetch_klines(symbol, interval, min(gap_candles + 1, Config.KLINES_BATCH_SIZE), expected_next_ts, last_closed_end)
                    if new_klines:
                        if int(new_klines[0][0]) != expected_next_ts:
                            logger.warning(f"Warning: Gap or overlap detected for {symbol} {interval} (expected {expected_next_ts}, got {new_klines[0][0]}). Skipping update.")
                            return
                        await self.db_manager.insert_klines(symbol, interval, new_klines)
                        logger.info(f"Updated {len(new_klines)} new klines for {symbol} {interval}")
                await self.db_manager.trim_klines(symbol, interval, Config.MAX_HISTORY_LENGTH)

    def _sync_delete_old_klines(self, symbol: str, interval: str):
        self.db_manager.cursor.execute('''
        DELETE FROM klines WHERE symbol = ? AND interval = ?
        ''', (symbol, interval))
        self.db_manager.conn.commit()