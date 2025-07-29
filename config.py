import logging
import asyncio
from datetime import datetime
import calendar

class Config:
    BASE_URL = "fapi.binance.com"
    WS_BASE_URL = "wss://fstream.binance.com"
    SMA_PERIOD = 55  # Periode für SMA-Berechnung
    RSI_PERIOD = 14
    AVG_VOLUME_PERIOD = 14
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    DATA_LIMIT = 5000  # Angepasst an dein neues Limit
    TAKER_FEE = 0.0004  # Default; fetch dynamically from API if needed
    KEY_FILE = "keys.json"
    VALID_INTERVALS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w", "1M"]
    RECV_WINDOW = 10000
    DB_FILE = "binance_data.db"
    KLINES_BATCH_SIZE = 1000
    API_DELAY = 0.2
    DAILY_UPDATE_THRESHOLD = 86400
    SAFETY_MARGIN_FACTOR = 0.8
    INITIAL_KLINES_LIMIT = DATA_LIMIT  # Direkt DATA_LIMIT, keine SMA-Anpassung
    MAX_HISTORY_LENGTH = 2 * DATA_LIMIT
    WS_RECONNECT_DELAY = 5
    WS_LIVE_CANDLE_TIMEOUT = 5
    RATE_LIMIT_SEMAPHORE = asyncio.Semaphore(5)
    INITDB_SLEEP = 1.0
    LOG_LEVEL = logging.INFO

def get_interval_ms(interval: str) -> int:
    if interval not in Config.VALID_INTERVALS:
        raise ValueError(f"Invalid interval: {interval}. Must be one of {Config.VALID_INTERVALS}")
    if interval.endswith('m'):
        return int(interval[:-1]) * 60 * 1000
    elif interval.endswith('h'):
        return int(interval[:-1]) * 3600 * 1000
    elif interval.endswith('d'):
        return int(interval[:-1]) * 86400 * 1000
    elif interval.endswith('w'):
        return int(interval[:-1]) * 604800 * 1000
    elif interval.endswith('M'):
        return int(interval[:-1]) * int(86400 * 30.437 * 1000)
    return 0

logging.basicConfig(level=Config.LOG_LEVEL, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)