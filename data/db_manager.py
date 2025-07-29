import sqlite3
import time
import asyncio
from typing import List, Dict, Any, Optional
from config import Config, logger

class DBManager:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(Config.DB_FILE, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.executor = asyncio.get_running_loop().run_in_executor
        self.lock = asyncio.Lock()  # Lock für Schreiboperationen
        self.optimize_pragmas()
        self.create_tables()
        self.create_indexes()

    def optimize_pragmas(self) -> None:
        self.cursor.execute("PRAGMA journal_mode=WAL")
        self.cursor.execute("PRAGMA synchronous=NORMAL")
        self.cursor.execute("PRAGMA cache_size=-200000")  # 200MB cache
        self.conn.commit()

    def create_tables(self) -> None:
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS klines (
            symbol TEXT,
            interval TEXT,
            timestamp INTEGER,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (symbol, interval, timestamp)
        )
        ''')
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS symbol_constraints (
            symbol TEXT PRIMARY KEY,
            minQty REAL,
            stepSize REAL,
            quantityPrecision INTEGER,
            minNotional REAL,
            pricePrecision INTEGER,
            last_updated INTEGER
        )
        ''')
        self.cursor.execute('''
        CREATE TABLE IF NOT EXISTS leverage_brackets (
            symbol TEXT,
            bracket_id INTEGER,
            maxNotional REAL,
            notionalFloor REAL,
            maintAmount REAL,
            mmr REAL,
            maxLeverage INTEGER,
            last_updated INTEGER,
            PRIMARY KEY (symbol, bracket_id)
        )
        ''')
        self.conn.commit()

    def create_indexes(self) -> None:
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_klines_symbol_interval_timestamp ON klines (symbol, interval, timestamp)')
        self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_klines_timestamp ON klines (timestamp)')
        self.conn.commit()

    async def vacuum(self) -> None:
        async with self.lock:
            await self.executor(None, self._sync_vacuum)

    def _sync_vacuum(self) -> None:
        self.cursor.execute("VACUUM")
        self.cursor.execute("ANALYZE")
        self.conn.commit()
        logger.info("Database vacuumed and analyzed")

    async def insert_klines(self, symbol: str, interval: str, klines: List[List[Any]]) -> None:
        if not klines:
            return
        params = [(symbol, interval, int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in klines]
        async with self.lock:
            await self.executor(None, self._sync_insert_klines, params)

    def _sync_insert_klines(self, params):
        self.cursor.executemany('''
        INSERT OR IGNORE INTO klines (symbol, interval, timestamp, open, high, low, close, volume)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', params)
        self.conn.commit()

    async def get_last_timestamp(self, symbol: str, interval: str) -> Optional[int]:
        return await self.executor(None, self._sync_get_last_timestamp, symbol, interval)

    def _sync_get_last_timestamp(self, symbol: str, interval: str) -> Optional[int]:
        self.cursor.execute('''
        SELECT MAX(timestamp) FROM klines WHERE symbol = ? AND interval = ?
        ''', (symbol, interval))
        result = self.cursor.fetchone()
        return result[0] if result else None

    async def get_klines_from_db(self, symbol: str, interval: str, limit: int) -> List[List[float]]:
        return await self.executor(None, self._sync_get_klines_from_db, symbol, interval, limit)

    def _sync_get_klines_from_db(self, symbol: str, interval: str, limit: int) -> List[List[float]]:
        self.cursor.execute('''
        SELECT timestamp, open, high, low, close, volume FROM klines
        WHERE symbol = ? AND interval = ?
        ORDER BY timestamp DESC LIMIT ?
        ''', (symbol, interval, limit))
        rows = self.cursor.fetchall()
        return [[row[0], row[1], row[2], row[3], row[4], row[5]] for row in reversed(rows)]

    async def insert_symbol_constraints(self, constraints: Dict[str, Dict[str, Any]]) -> None:
        if not constraints:
            return
        current_time = int(time.time())
        params = [(symbol, data["minQty"], data["stepSize"], data["quantityPrecision"], data["minNotional"], data["pricePrecision"], current_time) for symbol, data in constraints.items()]
        async with self.lock:
            await self.executor(None, self._sync_insert_symbol_constraints, params)

    def _sync_insert_symbol_constraints(self, params):
        self.cursor.executemany('''
        INSERT OR REPLACE INTO symbol_constraints (symbol, minQty, stepSize, quantityPrecision, minNotional, pricePrecision, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', params)
        self.conn.commit()

    async def get_symbol_constraints_from_db(self) -> Dict[str, Dict[str, Any]]:
        return await self.executor(None, self._sync_get_symbol_constraints_from_db)

    def _sync_get_symbol_constraints_from_db(self) -> Dict[str, Dict[str, Any]]:
        self.cursor.execute('''
        SELECT * FROM symbol_constraints
        ''')
        rows = self.cursor.fetchall()
        constraints = {}
        for row in rows:
            constraints[row[0]] = {
                "minQty": row[1],
                "stepSize": row[2],
                "quantityPrecision": row[3],
                "minNotional": row[4],
                "pricePrecision": row[5]
            }
        return constraints

    async def get_symbol_constraints_last_updated(self) -> int:
        return await self.executor(None, self._sync_get_symbol_constraints_last_updated)

    def _sync_get_symbol_constraints_last_updated(self) -> int:
        self.cursor.execute('''
        SELECT MAX(last_updated) FROM symbol_constraints
        ''')
        result = self.cursor.fetchone()
        return result[0] if result and result[0] is not None else 0

    async def insert_leverage_brackets(self, symbol: str, brackets: List[Dict[str, Any]]) -> None:
        if not brackets:
            return
        current_time = int(time.time())
        params = [(symbol, i, b["notionalCap"], b["notionalFloor"], b["cum"], b["maintMarginRatio"], b["initialLeverage"], current_time) for i, b in enumerate(brackets)]
        async with self.lock:
            await self.executor(None, self._sync_insert_leverage_brackets, params)

    def _sync_insert_leverage_brackets(self, params):
        self.cursor.executemany('''
        INSERT OR REPLACE INTO leverage_brackets (symbol, bracket_id, maxNotional, notionalFloor, maintAmount, mmr, maxLeverage, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', params)
        self.conn.commit()

    async def get_leverage_brackets_from_db(self, symbol: str) -> List[Dict[str, Any]]:
        return await self.executor(None, self._sync_get_leverage_brackets_from_db, symbol)

    def _sync_get_leverage_brackets_from_db(self, symbol: str) -> List[Dict[str, Any]]:
        self.cursor.execute('''
        SELECT maxNotional, notionalFloor, maintAmount, mmr, maxLeverage FROM leverage_brackets
        WHERE symbol = ? ORDER BY bracket_id
        ''', (symbol,))
        rows = self.cursor.fetchall()
        brackets = []
        for row in rows:
            brackets.append({
                "maxNotional": row[0],
                "notionalFloor": row[1],
                "maintAmount": row[2],
                "mmr": row[3],
                "maxLeverage": row[4]
            })
        if brackets:
            brackets[-1]["maxNotional"] = float("inf")
        return brackets

    async def get_leverage_brackets_last_updated(self, symbol: str) -> int:
        return await self.executor(None, self._sync_get_leverage_brackets_last_updated, symbol)

    def _sync_get_leverage_brackets_last_updated(self, symbol: str) -> int:
        self.cursor.execute('''
        SELECT MAX(last_updated) FROM leverage_brackets WHERE symbol = ?
        ''', (symbol,))
        result = self.cursor.fetchone()
        return result[0] if result and result[0] is not None else 0

    async def trim_klines(self, symbol: str, interval: str, max_length: int) -> None:
        async with self.lock:
            await self.executor(None, self._sync_trim_klines, symbol, interval, max_length)

    def _sync_trim_klines(self, symbol: str, interval: str, max_length: int) -> None:
        self.cursor.execute('''
        SELECT COUNT(*) FROM klines WHERE symbol = ? AND interval = ?
        ''', (symbol, interval))
        count = self.cursor.fetchone()[0]
        if count > max_length:
            self.cursor.execute('''
            SELECT timestamp FROM klines WHERE symbol = ? AND interval = ?
            ORDER BY timestamp ASC LIMIT ?
            ''', (symbol, interval, count - max_length))
            old_timestamps = [row[0] for row in self.cursor.fetchall()]
            if old_timestamps:
                self.cursor.executemany('''
                DELETE FROM klines WHERE symbol = ? AND interval = ? AND timestamp = ?
                ''', [(symbol, interval, ts) for ts in old_timestamps])
                self.conn.commit()
                logger.info(f"Trimmed {len(old_timestamps)} old klines for {symbol} {interval}")

    def close(self) -> None:
        self.conn.close()