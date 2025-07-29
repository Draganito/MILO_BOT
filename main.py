import os
import argparse
import asyncio
import time
from typing import Dict, Any, Optional
from datetime import datetime
from config import Config, logger
from data.db_manager import DBManager
from network.api_client import ApiClient
from network.websocket_manager import WebSocketManager
from trading.trade_manager import TradeManager
from analysis.script_engine import ScriptEngine
from visualization.chart_handler import ChartHTTPRequestHandler
import threading
import socketserver
import webbrowser

async def main() -> None:
    async def ws_candle_callback(symbol: str, interval: str, candle: Dict[str, Any]) -> None:
        await db_manager.insert_klines(symbol, interval, [[candle["time"], candle["open"], candle["high"], candle["low"], candle["close"], candle["volume"]]])
        logger.info(f"Closed candle inserted to DB for {symbol} {interval}")

    parser = argparse.ArgumentParser(description="Binance Futures Trading Bot")
    parser.add_argument("--script", help="Path to script file")
    parser.add_argument("--loop", nargs="?", const="normal", default=None, help="Run script in loop. Use --loop live for live candle mode without close check")
    parser.add_argument("--balance", action="store_true", help="Query account balance")
    parser.add_argument("--listopenpositions", action="store_true", help="List open positions")
    parser.add_argument("--closeallpositions", action="store_true", help="Close all open positions")
    parser.add_argument("--closeposition", type=int, help="Close a specific position by number")
    parser.add_argument("--initdb", nargs='*', help="Initialize database with historical data for specific symbols or all if none provided")
    parser.add_argument("--print-indicators", action="store_true", help="Print indicator values for a symbol and interval")
    parser.add_argument("--symbol", help="Symbol for --print-indicators (e.g., BTCUSDT)", default="BTCUSDT")
    parser.add_argument("--interval", help="Interval for --print-indicators (e.g., 1h)", default="1h")
    args = parser.parse_args()
    if not any([args.script, args.balance, args.listopenpositions, args.closeallpositions, args.closeposition is not None, args.initdb is not None, args.print_indicators]):
        parser.error("At least one flag is required")
    db_manager = DBManager()
    api_client = ApiClient(db_manager)
    await api_client.sync_time()
    await api_client.update_symbol_constraints_if_needed()
    ws_manager = WebSocketManager(ws_candle_callback)
    asyncio.create_task(ws_manager.connect())
    trade_manager = TradeManager(api_client, db_manager, ws_manager)
    script_engine = None
    try:
        async def periodic_maintenance() -> None:
            while True:
                await trade_manager.update_capital()
                await db_manager.vacuum()  # Täglicher VACUUM/ANALYZE
                await asyncio.sleep(86400)  # Einmal täglich
        asyncio.create_task(periodic_maintenance())
        if args.initdb is not None:
            logger.info("Initializing database...")
            symbols = args.initdb if args.initdb else None
            await api_client.initialize_historical_data(symbols)
        if args.balance:
            balance = await trade_manager.update_capital()
            logger.info(f"Available Balance: {balance:.2f} USDT")
        if args.listopenpositions:
            await trade_manager.list_open_positions()
        if args.closeallpositions:
            await trade_manager.close_all_positions()
        if args.closeposition is not None:
            await trade_manager.close_position(args.closeposition)
        if args.print_indicators:
            script_engine = ScriptEngine(api_client, trade_manager, db_manager, ws_manager)
            await script_engine.print_indicators(args.symbol, args.interval)
        if args.script:
            script_engine = ScriptEngine(api_client, trade_manager, db_manager, ws_manager)
            with open(args.script, "r") as f:
                script = f.read()
            async def run_script(loop_mode: Optional[str] = args.loop) -> None:
                try:
                    await script_engine.execute_script(script, loop_mode=loop_mode)
                except Exception as e:
                    logger.error(f"Script execution failed: {e}")
            if args.loop:
                if args.loop == "live":
                    def start_chart_server() -> None:
                        Handler = lambda *args, **kwargs: ChartHTTPRequestHandler(*args, script_engine=script_engine, **kwargs)
                        with socketserver.TCPServer(("", 8080), Handler) as httpd:
                            logger.info("Chart visualization server started at http://localhost:8080")
                            webbrowser.open("http://localhost:8080")
                            httpd.serve_forever()
                    server_thread = threading.Thread(target=start_chart_server, daemon=True)
                    server_thread.start()
                while True:
                    await run_script(args.loop)
                    await asyncio.sleep(5)
            else:
                await run_script(False)
    except Exception as e:
        logger.error(f"Operation failed: {e}")
    finally:
        ws_manager.stop()
        await api_client.close()
        db_manager.close()

if __name__ == "__main__":
    asyncio.run(main())