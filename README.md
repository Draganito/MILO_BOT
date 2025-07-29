# Binance Futures Trading Bot "MILOBOT"

## Einleitung

Der Binance Futures Trading Bot ist eine Python-basierte Plattform für den automatisierten Handel auf der Binance Futures API. Er richtet sich an professionelle Trader und Entwickler, die komplexe Handelsstrategien in Echtzeit umsetzen möchten. Der Bot unterstützt Echtzeit-Datenverarbeitung, technische Indikatoren, benutzerdefinierte Skripte und interaktive Chart-Visualisierung. Veröffentlicht unter der MIT-Lizenz, bietet er Flexibilität für Anpassungen und Erweiterungen.

## Risikoausschluss

**Wichtiger Hinweis**: Der Autor übernimmt **keine Verantwortung** für finanzielle Verluste, Schäden oder Fehlentscheidungen durch die Nutzung dieses Bots. Der Handel mit Kryptowährungen ist hochspekulativ und risikoreich. Testen Sie Strategien gründlich in einer Simulationsumgebung, bevor Sie echtes Kapital einsetzen. Dieser Bot stellt **keine Finanzberatung** dar. Verwenden Sie ihn auf eigenes Risiko.

## Technische Dokumentation

Der Bot ist modular und asynchron aufgebaut, basierend auf `asyncio`, um eine effiziente Verarbeitung von API-Anfragen, WebSocket-Daten und Datenbankoperationen zu gewährleisten. Die Kernkomponenten sind:

1. **`main.py`**:
   - Einstiegspunkt für Kommandozeilenargumente (`--script`, `--initdb`, `--print-indicators`, etc.).
   - Initialisiert Kernmodule (`DBManager`, `ApiClient`, `WebSocketManager`, `TradeManager`, `ScriptEngine`).
   - Startet periodische Tasks, z. B. Kapital-Updates (`trade_manager.update_capital`) und Datenbank-Optimierung (`db_manager.vacuum`, täglich).

2. **`api_client.py`**:
   - Kommuniziert mit der Binance Futures API (Endpunkte wie `/fapi/v1/klines`, `/fapi/v2/account`).
   - Verwendet signierte Anfragen (HMAC-SHA256) und Batch-Verarbeitung (`KLINES_BATCH_SIZE = 1000`).
   - Implementiert Rate-Limit-Schutz mit `RATE_LIMIT_SEMAPHORE` (max. 5 parallele Anfragen) und `API_DELAY = 0.2s`.
   - Verhindert ungültige Datenabrufe mit `min_timestamp` (Januar 2019).

3. **`db_manager.py`**:
   - Verwaltet SQLite-Datenbank (`binance_data.db`) für Klines, Symbol-Beschränkungen und Hebelgrenzen.
   - Optimiert mit `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `cache_size=-200000` (200 MB).
   - Synchronisiert Schreiboperationen mit `asyncio.Lock` für Thread-Sicherheit.
   - Führt tägliches `VACUUM/ANALYZE` für Performance-Optimierung durch.
   - Nutzt `asyncio.get_running_loop().run_in_executor` für synchrone SQLite-Aufrufe.

4. **`websocket_manager.py`**:
   - Ermöglicht Echtzeit-Daten über Binance WebSocket (`wss://fstream.binance.com`).
   - Unterstützt Live-Kerzen mit automatischer Wiederverbindung (`WS_RECONNECT_DELAY = 5s`).

5. **`trade_manager.py`**:
   - Verwaltet Positionen, Hebel, Stop-Loss, Take-Profit und Liquidationspreise.
   - Berücksichtigt Binance-Beschränkungen (`minQty`, `minNotional`, `stepSize`) via `api_client.get_symbol_constraints`.

6. **`script_engine.py` / `script_executor.py`**:
   - Führt benutzerdefinierte Skripte in einer sicheren Umgebung aus (`exec_env` mit eingeschränkten `builtins` wie `os`, `sys`).
   - Unterstützt asynchrone Indikator-Aufrufe mit `await` (z. B. `await calculate_rsi(data, 14)`).
   - Ermöglicht Live-Handelsaktionen (`long`, `short`) und Backtesting.

7. **`indicators.py`**:
   - Bietet asynchrone Indikatoren: SMA, EMA, RSI, MACD, ATR, OBV, Stochastic, ZigZag, Divergenzen.
   - Asynchrone Aufrufe (`await calculate_...`) delegieren an synchrone Funktionen (`calculate_..._sync`) via ThreadPoolExecutor.
   - Divergenzen: Reguläre und versteckte (`'bullish'`, `'bearish'`, `'hidden_bullish'`, `'hidden_bearish'`).

8. **`chart_handler.py` / `chart.js`**:
   - HTTP-Server für interaktive Charts (Canvas, JavaScript).
   - Visualisiert Kerzen, ZigZag-Linien, Divergenzen, aktualisiert alle 5 Sekunden (http://localhost:8080).

### Sicherheitsmaßnahmen
- **API-Schlüssel**: Verschlüsselt mit PBKDF2 in `keys.json` (`key_manager.py`), benötigt Passwort zur Entschlüsselung.
- **Thread-Sicherheit**: `asyncio.Lock` in `db_manager.py` verhindert Datenbankkonflikte bei parallelen Schreiboperationen.
- **Rate-Limit-Schutz**: `RATE_LIMIT_SEMAPHORE` (max. 5 Anfragen) und `API_DELAY = 0.2s` halten Binance-Limits ein (~1.200 Anfragen/Minute, ~2.400 Gewichtspunkte).
- **Sichere Skriptausführung**: Eingeschränkte `builtins` in `script_executor.py` verhindern gefährliche Operationen.
- **Datenintegrität**: `INSERT OR IGNORE` und Timestamp-Prüfungen in `db_manager.py` vermeiden Duplikate.

## Anwendungsgebiete

- **Live-Trading**: Automatisierte Strategien in Echtzeit (z. B. Divergenz-basierte Longs/Shorts).
- **Backtesting**: Testen von Strategien mit historischen Daten (z. B. RSI-Divergenzen).
- **Indikator-Analyse**: Ausgabe von Indikatorwerten für Marktforschung (`--print-indicators`).
- **Marktüberwachung**: Echtzeit-Chart-Visualisierung für Kerzen und Indikatoren (`--loop live`).
- **Datenakquise**: Initialisierung historischer Klines für mehrere Symbole (`--initdb`).

## Skriptsprache

Die Skriptsprache ist Python-basiert und läuft in einer sicheren Umgebung (`exec_env`). Sie betont asynchrone Programmierung mit `async/await` für nicht-blockierende Indikator-Aufrufe, um Echtzeit-Performance zu gewährleisten. Skripte definieren Handelslogik und greifen auf interne Indikatoren aus `indicators.py` zu.

### Syntax
- **Erforderliche Variablen**:
  - `timeframe`: Intervall (z. B. `"1m"`, `"1h"`, aus `Config.VALID_INTERVALS`).
  - `coin`: Symbol (z. B. `"BTCUSDT"`).
  - `condition_true`: Boolean, steuert Trade-Ausführung.
  - `action_if_true`, `action_if_false`: Aktionen (z. B. `"donothing"`, `"long(1%risk@10x,sl=2%,rr=3)"`, `"short(1%risk@10x,sl=2%,rr=3)"`).
- **Interne Indikatoren** (asynchron, mit `await`):
  - `calculate_sma(data, period)`: Simple Moving Average.
  - `calculate_ema(data, period)`: Exponential Moving Average.
  - `calculate_rsi(data, period)`: Relative Strength Index.
  - `calculate_macd(data)`: MACD (Line, Signal).
  - `calculate_atr(data)`: Average True Range.
  - `calculate_obv(data)`: On-Balance Volume.
  - `calculate_stochastic(data)`: Stochastic Oscillator (%K, %D).
  - `calculate_zigzag(data)`: ZigZag-Punkte.
  - `detect_divergences(rsi, zigzag_points, data, left_window, right_window)`: Divergenzen.
- **Daten**:
  - `data`: Liste von Kerzen-Dictionaries (`{'time', 'open', 'high', 'low', 'close', 'volume'}`).
  - `lastclose`: Schließkurs der letzten Kerze (`data[-1]['close']`).
- **Aktionen**:
  - `long(risk@leverage, sl=stop_loss, rr=risk_reward)`: Eröffnet Long-Position.
  - `short(risk@leverage, sl=stop_loss, rr=risk_reward)`: Eröffnet Short-Position.
  - `donothing`: Keine Aktion.

### Asynchrone Programmierung
Skripte nutzen `async/await` für Indikator-Aufrufe, um Blocking zu vermeiden:
```python
rsi = await calculate_rsi(data, 14)  # Asynchroner Aufruf
condition_true = rsi[-1] < 30
```
Dies ermöglicht parallele Verarbeitung von API-Anfragen, WebSocket-Daten und Indikator-Berechnungen.

## Installation

### Voraussetzungen
- Python 3.8+
- Abhängigkeiten: `aiohttp`, `websocket-client`, `numpy`
- Binance Futures API-Schlüssel

### Setup
1. Klone das Repository:
   ```bash
   git clone <repository-url>
   cd binance-futures-bot
   ```
2. Installiere Abhängigkeiten:
   ```bash
   pip install aiohttp websocket-client numpy
   ```
3. Erstelle `keys.json`:
   ```json
   {
       "api_key": "your_api_key",
       "api_secret": "your_api_secret",
       "password": "your_password"
   }
   ```
4. Initialisiere die Datenbank:
   ```bash
   python3 main.py --initdb BTCUSDT
   ```

## Beispielstrategien

Die folgenden Beispiele zeigen Live-Handelsstrategien mit internen Indikatoren aus `indicators.py`. Sie verwenden `coin = "BTCUSDT"`, `timeframe = "1h"`, `action_if_true = "long(1%risk@10x,sl=2%,rr=3)"` oder `short`.

### 1. Hidden Bullish RSI-Divergenz
Eröffnet Long-Positionen bei versteckten bullischen RSI-Divergenzen.

```python
timeframe = "1h"
coin = "BTCUSDT"
condition_true = False
action_if_true = "long(1%risk@10x,sl=2%,rr=3)"
action_if_false = "donothing"

rsi = await calculate_rsi(data, 14)
zigzag_points = await calculate_zigzag(data)
divergences = await detect_divergences(rsi, zigzag_points, data, 20, 0)
condition_true = any(div['type'] == 'hidden_bullish' for div in divergences)
print(f"Hidden Bullish Divergence: {condition_true}")
```

**Erklärung**: Nutzt `calculate_rsi`, `calculate_zigzag`, `detect_divergences`. Signal: Long bei versteckter bullischer Divergenz (Preis: höheres Tief, RSI: tieferes Tief). Geeignet für Trendfortsetzung.

### 2. MACD-Crossover
Eröffnet Long-Positionen bei MACD-Linie über Signallinie.

```python
timeframe = "1h"
coin = "BTCUSDT"
condition_true = False
action_if_true = "long(1%risk@10x,sl=2%,rr=3)"
action_if_false = "donothing"

macd_line, signal_line = await calculate_macd(data)
condition_true = macd_line[-1] > signal_line[-1]
print(f"MACD Line: {macd_line[-1]:.4f}, Signal Line: {signal_line[-1]:.4f}, Condition: {condition_true}")
```

**Erklärung**: Nutzt `calculate_macd`. Signal: Long bei MACD > Signallinie. Geeignet für Momentum-Trading.

### 3. Stochastic-RSI-Kombination
Eröffnet Long-Positionen bei RSI < 30 und Stochastic %K > %D im überverkauften Bereich.

```python
timeframe = "1h"
coin = "BTCUSDT"
condition_true = False
action_if_true = "long(1%risk@10x,sl=2%,rr=3)"
action_if_false = "donothing"

rsi = await calculate_rsi(data, 14)
k, d = await calculate_stochastic(data)
condition_true = rsi[-1] < 30 and k[-1] < 20 and k[-1] > d[-1]
print(f"RSI: {rsi[-1]:.4f}, Stochastic %K: {k[-1]:.4f}, %D: {d[-1]:.4f}, Condition: {condition_true}")
```

**Erklärung**: Nutzt `calculate_rsi`, `calculate_stochastic`. Signal: Long bei überverkauftem RSI und Stochastic-Crossover. Geeignet für Mean-Reversion.

## Verwendung

### Initialisierung
```bash
python3 main.py --initdb BTCUSDT
```
Lädt bis zu 5.000 Kerzen (`DATA_LIMIT = 5.000`).

### Indikatoren anzeigen
```bash
python3 main.py --print-indicators --symbol BTCUSDT --interval 1h
```

### Live-Trading
```bash
python3 main.py --script samples/hidden_bullish_divergence.script --loop live
```
Öffnet Chart unter http://localhost:8080.

## Tipps für Entwickler
- **Live-Trading**: Teste Strategien mit `--print-indicators` vor Live-Einsatz.
- **Symbole**: Füge `get_symbol_constraints` in `exec_env` hinzu für dynamische Beschränkungen.
- **Optimierung**: Variiere Parameter (z. B. `rsi_period`) für bessere Ergebnisse.
- **Fehlerbehandlung**: Überwache Logs für Rate-Limit-Warnungen (Status 429).

## Einschränkungen
- Fixierter MMR (0.004) in Skripten ist eine Vereinfachung.
- Keine Datenbankverschlüsselung oder automatische Backups.
- Live-Trading ignoriert Markttiefe und Liquidität.

## Lizenz

MIT License

Copyright (c) 2025 Dragan Bojovic

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
