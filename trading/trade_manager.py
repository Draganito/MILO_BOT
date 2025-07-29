# src/trading/trade_manager.py (complete with await on DB calls)
import asyncio
import math
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from config import Config, logger
from network.api_client import ApiClient
from data.db_manager import DBManager
from network.websocket_manager import WebSocketManager

class TradeManager:
    def __init__(self, api_client: ApiClient, db_manager: DBManager, ws_manager: WebSocketManager) -> None:
        self.api_client = api_client
        self.db_manager = db_manager
        self.ws_manager = ws_manager
        self.available_capital: Optional[float] = None
        self.trade_lock = False

    async def update_leverage_brackets_if_needed(self, symbol: str) -> None:
        last_updated = await self.db_manager.get_leverage_brackets_last_updated(symbol)
        current_time = int(time.time())
        if current_time - last_updated > Config.DAILY_UPDATE_THRESHOLD:
            logger.info(f"Updating leverage brackets for {symbol} from API...")
            try:
                brackets = await self.api_client.fetch_leverage_bracket(symbol)
                await self.db_manager.insert_leverage_brackets(symbol, brackets)
            except Exception as e:
                logger.error(f"Failed to update leverage brackets for {symbol}: {e}")

    async def get_mmr_tiers(self, symbol: str) -> List[Dict[str, Any]]:
        await self.update_leverage_brackets_if_needed(symbol)
        return await self.db_manager.get_leverage_brackets_from_db(symbol)

    async def get_maintenance_margin(self, notional: float, symbol: str) -> float:
        tiers = await self.get_mmr_tiers(symbol)
        maint_margin = 0
        prev_max = 0
        for tier in tiers:
            if notional <= tier["maxNotional"]:
                maint_margin = tier["maintAmount"] + (notional - prev_max) * tier["mmr"]
                break
            maint_margin = tier["maintAmount"] + (tier["maxNotional"] - prev_max) * tier["mmr"]
            prev_max = tier["maxNotional"]
        return maint_margin

    async def calculate_liquidation_price(self, side: str, entry_price: float, leverage: int, margin: float, symbol: str) -> float:
        mark_price = await self.api_client.fetch_mark_price(symbol)
        notional = margin * leverage
        mm = await self.get_maintenance_margin(notional, symbol)
        mmr = mm / notional if notional > 0 else 0
        if side == "LONG":
            return mark_price * (1 - 1 / leverage + mmr)
        return mark_price * (1 + 1 / leverage - mmr)

    async def calculate_quantity(self, symbol: str, position_size: float, price: float, risk_amount: float, user_leverage: int) -> Dict[str, Any]:
        if not price or price <= 0:
            return {"quantity": 0, "adjustedPositionSize": 0, "usedMargin": 0, "leverage": user_leverage, "error": "Invalid price"}
        constraints = self.api_client.get_symbol_constraints(symbol)
        tiers = await self.get_mmr_tiers(symbol)
        if not tiers:
            return {"quantity": 0, "adjustedPositionSize": 0, "usedMargin": 0, "leverage": user_leverage, "error": "Failed to fetch leverage tiers"}
        min_qty = constraints["minQty"]
        min_notional = constraints["minNotional"] / price
        effective_min_qty = max(min_qty, min_notional)
        min_position_size = effective_min_qty * price
        min_margin = min_position_size / user_leverage
        if min_margin > risk_amount:
            return {
                "quantity": 0,
                "adjustedPositionSize": 0,
                "usedMargin": 0,
                "leverage": user_leverage,
                "error": f"Position Size 0: Insufficient margin ({risk_amount:.2f} USDT) to meet minimum quantity ({effective_min_qty:.{constraints['quantityPrecision']}f} {symbol} requiring {min_margin:.2f} USDT at {user_leverage}x leverage)"
            }
        global_max_leverage = tiers[0]["maxLeverage"]
        quantity = position_size / price
        steps = math.floor(quantity / constraints["stepSize"])
        quantity = steps * constraints["stepSize"]
        if quantity < effective_min_qty:
            quantity = math.ceil(effective_min_qty / constraints["stepSize"]) * constraints["stepSize"]
        quantity = round(quantity, constraints["quantityPrecision"])
        adjusted_position_size = quantity * price
        leverage = math.ceil(adjusted_position_size / risk_amount) if risk_amount > 0 else 1
        leverage = min(leverage, user_leverage, global_max_leverage)
        used_margin = adjusted_position_size / leverage
        notional = adjusted_position_size
        bracket_max_leverage = tiers[0]["maxLeverage"]
        for tier in tiers:
            if notional <= tier["maxNotional"]:
                bracket_max_leverage = tier["maxLeverage"]
                break
        if leverage > bracket_max_leverage:
            leverage = bracket_max_leverage
            used_margin = adjusted_position_size / leverage
        if used_margin > risk_amount:
            max_position_size = risk_amount * leverage
            quantity = max_position_size / price
            steps = math.floor(quantity / constraints["stepSize"])
            quantity = steps * constraints["stepSize"]
            if quantity < effective_min_qty:
                return {
                    "quantity": 0,
                    "adjustedPositionSize": 0,
                    "usedMargin": 0,
                    "leverage": leverage,
                    "error": f"Position Size 0: Required margin exceeds risk amount after adjusting for bracket max leverage ({bracket_max_leverage}x)"
                }
            quantity = round(quantity, constraints["quantityPrecision"])
            adjusted_position_size = quantity * price
            used_margin = adjusted_position_size / leverage
        if used_margin > risk_amount:
            return {
                "quantity": 0,
                "adjustedPositionSize": 0,
                "usedMargin": 0,
                "leverage": user_leverage,
                "error": f"Position Size 0: Required margin ({used_margin:.2f} USDT) exceeds risk amount ({risk_amount:.2f} USDT) for quantity {quantity:.{constraints['quantityPrecision']}f} {symbol} at {leverage}x leverage"
            }
        return {
            "quantity": quantity,
            "adjustedPositionSize": adjusted_position_size,
            "usedMargin": used_margin,
            "leverage": leverage,
            "error": None
        }

    async def update_capital(self) -> float:
        try:
            data = await self.api_client.fetch_account()
            usdt_asset = next((asset for asset in data["assets"] if asset["asset"] == "USDT"), None)
            if usdt_asset and "availableBalance" in usdt_asset:
                self.available_capital = float(usdt_asset["availableBalance"])
            else:
                self.available_capital = 0.0
                logger.warning("No USDT asset found, setting available capital to 0.0")
        except Exception as e:
            self.available_capital = 0.0
            logger.error(f"Failed to fetch account balance: {e}. Setting available capital to 0.0")
        return self.available_capital

    async def place_order(self, symbol: str, side: str, position_size: float, leverage: int, risk_percent: float, sl: Optional[str] = None, tp: Optional[str] = None, rr_ratio: Optional[str] = None, use_isolated: bool = True, interval: str = "1h") -> None:
        if self.trade_lock:
            logger.warning("Trade lock active - skipping duplicate trade")
            return
        self.trade_lock = True
        try:
            live_candle = self.ws_manager.get_live_candle(symbol, interval)
            if not live_candle:
                raise Exception("No live candle available")
            price = live_candle["close"]
            if self.available_capital is None:
                raise Exception("Available capital is None, cannot calculate risk amount")
            risk_amount = self.available_capital * risk_percent / 100
            calc = await self.calculate_quantity(symbol, position_size, price, risk_amount, leverage)
            if calc["error"]:
                raise Exception(calc["error"])
            constraints = self.api_client.get_symbol_constraints(symbol)
            effective_min_qty = max(constraints["minQty"], constraints["minNotional"] / price)
            if calc["quantity"] < effective_min_qty:
                raise Exception(f"Quantity below effective minimum ({effective_min_qty:.{constraints['quantityPrecision']}f})")
            if abs(calc["adjustedPositionSize"] - position_size) / position_size > 0.1 or calc["usedMargin"] > risk_amount:
                logger.info(f"Adjusted position size to {calc['adjustedPositionSize']:.2f} USDT (Margin: {calc['usedMargin']:.2f} USDT, Leverage: {calc['leverage']}x)")
            position_side = "LONG" if side == "BUY" else "SHORT"
            positions = await self.api_client.fetch_positions()
            if any(p["symbol"] == symbol and p["positionSide"] == position_side and float(p["positionAmt"]) != 0 for p in positions):
                raise Exception("Already have an open position in this direction")
            if use_isolated:
                await self.api_client.change_margin_type(symbol, "ISOLATED")
            await self.api_client.set_leverage(symbol, calc["leverage"])
            entry_params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": str(calc["quantity"]),
                "positionSide": position_side
            }
            await self.api_client.post_order(entry_params)
            close_side = "SELL" if side == "BUY" else "BUY"
            if sl:
                if sl.endswith("%"):
                    sl_percent = float(sl.rstrip("%"))
                    sl_distance = sl_percent / 100
                    stop_price = price * (1 - sl_distance) if side == "BUY" else price * (1 + sl_distance)
                else:
                    stop_price = float(sl)
                stop_price = round(stop_price, constraints["pricePrecision"])
                sl_params = {
                    "symbol": symbol,
                    "side": close_side,
                    "type": "STOP_MARKET",
                    "stopPrice": str(stop_price),
                    "closePosition": "true",
                    "positionSide": position_side
                }
                await self.api_client.post_order(sl_params)
            if rr_ratio:
                if tp:
                    raise Exception("Cannot specify both TP and RR")
                rr_ratio = float(rr_ratio)
                net_profit = calc["usedMargin"] * rr_ratio
                fees = calc["adjustedPositionSize"] * Config.TAKER_FEE * 2
                gross_profit = net_profit + fees
                tp_distance = gross_profit / calc["adjustedPositionSize"]
                take_price = price * (1 + tp_distance) if side == "BUY" else price * (1 - tp_distance)
                take_price = round(take_price, constraints["pricePrecision"])
                tp_params = {
                    "symbol": symbol,
                    "side": close_side,
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": str(take_price),
                    "closePosition": "true",
                    "positionSide": position_side
                }
                await self.api_client.post_order(tp_params)
            elif tp:
                if tp.endswith("%"):
                    tp_percent = float(tp.rstrip("%"))
                    take_price = price * (1 + tp_percent / 100) if side == "BUY" else price * (1 - tp_percent / 100)
                else:
                    take_price = float(tp)
                take_price = round(take_price, constraints["pricePrecision"])
                tp_params = {
                    "symbol": symbol,
                    "side": close_side,
                    "type": "TAKE_PROFIT_MARKET",
                    "stopPrice": str(take_price),
                    "closePosition": "true",
                    "positionSide": position_side
                }
                await self.api_client.post_order(tp_params)
            await self.update_capital()
            logger.info(f"{side} position opened: Quantity={calc['quantity']:.{constraints['quantityPrecision']}f}, Value={calc['adjustedPositionSize']:.2f} USDT, Margin={calc['usedMargin']:.2f} USDT, Leverage={calc['leverage']}x{' SL='+str(sl) if sl else ''}{' TP='+str(take_price) if tp else ''}{' RR='+str(rr_ratio) if rr_ratio else ''}")
        except Exception as e:
            logger.error(f"Order failed: {e}")
        finally:
            self.trade_lock = False

    async def list_open_positions(self) -> List[Dict[str, Any]]:
        positions = await self.api_client.fetch_positions()
        open_positions = [p for p in positions if float(p["positionAmt"]) != 0]
        if not open_positions:
            logger.info("No open positions.")
            return []
        logger.info("Open Positions:")
        logger.info("{:<5} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10}".format(
            "#", "Symbol", "Side", "Entry", "Notional", "PnL", "Liq.", "SL", "TP", "Leverage", "Type", "Margin"
        ))
        for i, pos in enumerate(open_positions, start=1):
            symbol = pos["symbol"]
            notional = f"{float(pos['notional']):.2f}"
            open_orders = await self.api_client.fetch_open_orders(symbol)
            sl_price = next((order["stopPrice"] for order in open_orders if order["type"] == "STOP_MARKET" and order["closePosition"] and order["positionSide"] == pos["positionSide"]), "N/A")
            if sl_price != "N/A":
                sl_price = f"{float(sl_price):.2f}"
            tp_price = next((order["stopPrice"] for order in open_orders if order["type"] == "TAKE_PROFIT_MARKET" and order["closePosition"] and order["positionSide"] == pos["positionSide"]), "N/A")
            if tp_price != "N/A":
                tp_price = f"{float(tp_price):.2f}"
            logger.info("{:<5} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10} {:<10}".format(
                i,
                pos["symbol"],
                pos["positionSide"],
                f"{float(pos['entryPrice']):.2f}",
                notional,
                f"{float(pos['unRealizedProfit']):.2f}",
                f"{float(pos['liquidationPrice']):.2f}",
                sl_price,
                tp_price,
                f"{float(pos['leverage']):.2f}",
                pos["marginType"],
                f"{float(pos['isolatedMargin']):.2f}"
            ))
        return open_positions

    async def close_all_positions(self) -> None:
        positions = await self.api_client.fetch_positions()
        open_positions = [p for p in positions if float(p["positionAmt"]) != 0]
        if not open_positions:
            logger.info("No open positions to close.")
            return
        tasks = []
        for pos in open_positions:
            symbol = pos["symbol"]
            quantity = abs(float(pos["positionAmt"]))
            side = "SELL" if pos["positionSide"] == "LONG" else "BUY"
            logger.info(f"Closing {pos['positionSide']} position for {symbol} with quantity {quantity}")
            close_params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": str(quantity),
                "positionSide": pos["positionSide"]
            }
            tasks.append(self.api_client.post_order(close_params))
            tasks.append(self.api_client.cancel_all_open_orders(symbol))
        await asyncio.gather(*tasks)

    async def close_position(self, index: int) -> None:
        open_positions = await self.list_open_positions()
        if not open_positions:
            return
        if index < 1 or index > len(open_positions):
            logger.warning(f"Invalid position number: {index}. Must be between 1 and {len(open_positions)}.")
            return
        pos = open_positions[index - 1]
        symbol = pos["symbol"]
        quantity = abs(float(pos["positionAmt"]))
        side = "SELL" if pos["positionSide"] == "LONG" else "BUY"
        logger.info(f"Closing position #{index}: {pos['positionSide']} {symbol} with quantity {quantity}")
        close_params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity),
            "positionSide": pos["positionSide"]
        }
        await self.api_client.post_order(close_params)
        await self.api_client.cancel_all_open_orders(symbol)