# src/analysis/script_executor.py (updated with await on avg_volume, etc.)
import asyncio
import builtins
import textwrap
import math
import re
import time
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor
import contextvars
import inspect
from config import Config, get_interval_ms, logger
from trading.trade_manager import TradeManager
from network.api_client import ApiClient
from .script_validator import ScriptValidator
from .data_handler import DataHandler
from .indicators import Indicators

class ScriptExecutor:
    def __init__(self, api_client: ApiClient, trade_manager: TradeManager, data_handler: DataHandler, validator: ScriptValidator):
        self.api_client = api_client
        self.trade_manager = trade_manager
        self.data_handler = data_handler
        self.validator = validator
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.safe_builtins = {k: v for k, v in builtins.__dict__.items() if k not in ['eval', 'exec', 'open', 'compile', '__import__']}
        self.indicators = Indicators()

    async def execute_script(self, script: str, default_symbol: str = "BTCUSDT", default_interval: str = "1h", loop_mode: Optional[str] = None) -> None:
        self.validator.validate_script(script)
        script = script.strip()
        lines = script.splitlines()
        timeframe = default_interval
        symbol = default_symbol
        param_done = False
        code_lines = []
        for line in lines:
            stripped = line.strip()
            if not param_done:
                timeframe_match = re.match(r'^\s*timeframe\s*=\s*"(.*)"\s*$', stripped)
                if timeframe_match:
                    timeframe = timeframe_match.group(1).strip()
                    if timeframe not in Config.VALID_INTERVALS:
                        raise ValueError(f"Invalid timeframe: {timeframe}. Must be one of {Config.VALID_INTERVALS}")
                    continue
                coin_match = re.match(r'^\s*coin\s*=\s*"(.*)"\s*$', stripped)
                if coin_match:
                    symbol = coin_match.group(1).strip()
                    self.validator.validate_symbol(symbol)
                    continue
                else:
                    param_done = True
            code_lines.append(line)
        if symbol not in self.api_client.symbol_constraints:
            await self.api_client.update_symbol_constraints_if_needed()
        self.validator.validate_symbol(symbol)
        await self.data_handler.fetch_historical_data(symbol, timeframe)
        data = self.data_handler.chart_data.copy()
        if not data:
            raise Exception("No chart data available")
        live_candle = self.data_handler.live_candle
        if live_candle:
            data.append(live_candle)
        current_time = int(time.time() * 1000) + self.api_client.time_offset
        interval_ms = get_interval_ms(timeframe)
        last_candle_end = data[-1]["time"] + interval_ms
        is_last_candle_closed = current_time >= last_candle_end
        if not is_last_candle_closed and (loop_mode and loop_mode != "live"):
            logger.info("Live candle not closed. Skipping signal execution.")
            return
        last_candle = data[-1]
        last_close = last_candle["close"]
        last_open = last_candle["open"]
        last_high = last_candle["high"]
        last_low = last_candle["low"]
        last_volume = last_candle["volume"]
        previous_close = data[-2]["close"] if len(data) > 1 else float("nan")
        avg_volume = await self.indicators.calculate_average_volume(data)
        await self.trade_manager.update_capital()
        open_positions = await self.trade_manager.list_open_positions()
        var_dict = {
            "lastclose": last_close,
            "open": last_open,
            "high": last_high,
            "low": last_low,
            "volume": last_volume,
            "previousclose": previous_close,
            "averagevolume": avg_volume,
            "live_candle": live_candle,
            "available_balance": self.trade_manager.available_capital,
            "open_positions": open_positions
        }
        exec_env = {
            "__builtins__": self.safe_builtins,
            "math": math,
            "data": data,
            "chart_data": self.data_handler.chart_data,
            "live_candle": live_candle,
            "calculate_sma": self.indicators.calculate_sma,
            "calculate_ema": self.indicators.calculate_ema,
            "calculate_ema_internal": self.indicators.calculate_ema_internal,
            "calculate_dema": self.indicators.calculate_dema,
            "calculate_rsi": self.indicators.calculate_rsi,
            "calculate_macd": self.indicators.calculate_macd,
            "calculate_average_volume": self.indicators.calculate_average_volume,
            "calculate_obv": self.indicators.calculate_obv,
            "calculate_atr": self.indicators.calculate_atr,
            "calculate_zigzag": self.indicators.calculate_zigzag,
            "classify_swing_points": self.indicators.classify_swing_points,
            "find_extremum_in_window": self.indicators.find_extremum_in_window,
            "detect_divergences": self.indicators.detect_divergences,
            "calculate_stochastic": self.indicators.calculate_stochastic
        }
        exec_env.update(var_dict)
        user_code = '\n'.join(code_lines)
        user_code = textwrap.dedent(user_code)
        indented_code = textwrap.indent(user_code, '    ')
        wrapped_code = f"""
async def user_wrapped_script():
{indented_code}
    return locals()
"""
        exec(wrapped_code, exec_env)
        user_locals = await exec_env['user_wrapped_script']()
        if "condition_true" not in user_locals:
            raise Exception("Script must define 'condition_true' as a boolean")
        condition_true = user_locals["condition_true"]
        if not isinstance(condition_true, bool):
            raise Exception("condition_true must be a boolean")
        action_if_true = user_locals.get("action_if_true", "donothing")
        action_if_false = user_locals.get("action_if_false", "donothing")
        self.validator.validate_action(action_if_true)
        self.validator.validate_action(action_if_false)
        action = action_if_true if condition_true else action_if_false
        if action == "donothing":
            logger.info("No action taken")
            return
        match = re.match(r"^(long|short)\((\d+\.?\d*)%risk@(\d+\.?\d*)x(?:,sl=([\d.]+%?))?(?:,tp=([\d.]+%?))?(?:,rr=([\d.]+))?\)$", action)
        if not match:
            raise Exception(f"Invalid action: {action}")
        direction, risk_percent, leverage, sl, tp, rr_ratio = match.groups()
        risk_percent = float(risk_percent)
        leverage = float(leverage)
        if math.isnan(risk_percent) or risk_percent <= 0 or risk_percent > 100:
            raise Exception("Invalid risk percent")
        if math.isnan(leverage) or leverage < 1:
            raise Exception("Invalid leverage")
        tiers = await self.trade_manager.get_mmr_tiers(symbol)
        if not tiers:
            raise Exception("Failed to fetch leverage tiers")
        max_lev = tiers[0]["maxLeverage"]
        if leverage > max_lev:
            raise Exception(f"Invalid leverage: exceeds maximum {max_lev}x for {symbol}")
        await self.trade_manager.update_capital()
        if self.trade_manager.available_capital is None or self.trade_manager.available_capital == 0.0:
            raise Exception("Available capital is zero or could not be fetched, cannot place order")
        risk_amount = self.trade_manager.available_capital * risk_percent / 100
        position_size = risk_amount * leverage
        side = "BUY" if direction == "long" else "SELL"
        await self.trade_manager.place_order(symbol, side, position_size, leverage, risk_percent, sl, tp, rr_ratio, interval=timeframe)