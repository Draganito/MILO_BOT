import asyncio
import math
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any, Optional, Tuple
from config import Config

class Indicators:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=4)

    def calculate_sma_sync(self, data: List[Dict[str, float]], period: int) -> List[float]:
        sma = []
        for i in range(len(data)):
            start = max(0, i - period + 1)
            slice_data = [c["close"] for c in data[start:i+1]]
            sma.append(sum(slice_data) / len(slice_data) if slice_data else float("nan"))
        return sma

    async def calculate_sma(self, data: List[Dict[str, float]], period: int) -> List[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_sma_sync, data, period)

    def calculate_ema_internal_sync(self, src: List[float], length: int) -> List[float]:
        k = 2 / (length + 1)
        ema = []
        for i, val in enumerate(src):
            if i == 0:
                ema.append(val)
            else:
                ema.append(val * k + ema[-1] * (1 - k))
        return ema

    async def calculate_ema_internal(self, src: List[float], length: int) -> List[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_ema_internal_sync, src, length)

    async def calculate_ema(self, data: List[Dict[str, float]], length: int) -> List[float]:
        closes = [c["close"] for c in data]
        return await self.calculate_ema_internal(closes, length)

    async def calculate_dema(self, src: List[float], length: int) -> List[float]:
        ma1 = await self.calculate_ema_internal(src, length)
        ma2 = await self.calculate_ema_internal(ma1, length)
        return [2 * m1 - m2 for m1, m2 in zip(ma1, ma2)]

    def calculate_rsi_sync(self, data: List[Dict[str, float]], period: int = Config.RSI_PERIOD) -> List[Optional[float]]:
        n = len(data)
        if n < period + 1:
            return [None] * n
        rsi = [None] * n
        gain_sum = 0
        loss_sum = 0
        for i in range(1, period + 1):
            delta = data[i]['close'] - data[i - 1]['close']
            if delta > 0:
                gain_sum += delta
            else:
                loss_sum += -delta
        avg_gain = gain_sum / period
        avg_loss = loss_sum / period
        first_rsi = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
        rsi[period] = first_rsi
        for i in range(period + 1, n):
            delta = data[i]['close'] - data[i - 1]['close']
            gain = delta if delta > 0 else 0
            loss = -delta if delta < 0 else 0
            avg_gain = (avg_gain * (period - 1) + gain) / period
            avg_loss = (avg_loss * (period - 1) + loss) / period
            current_rsi = 100 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
            rsi[i] = current_rsi
        return rsi

    async def calculate_rsi(self, data: List[Dict[str, float]], period: int = Config.RSI_PERIOD) -> List[Optional[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_rsi_sync, data, period)

    def calculate_macd_sync(self, data: List[Dict[str, float]]) -> Tuple[List[float], List[float]]:
        closes = [c["close"] for c in data]
        fast_ema = self.calculate_ema_internal_sync(closes, Config.MACD_FAST)
        slow_ema = self.calculate_ema_internal_sync(closes, Config.MACD_SLOW)
        macd = [f - s for f, s in zip(fast_ema, slow_ema)]
        signal = self.calculate_ema_internal_sync(macd, Config.MACD_SIGNAL)
        return macd, signal

    async def calculate_macd(self, data: List[Dict[str, float]]) -> Tuple[List[float], List[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_macd_sync, data)

    def calculate_average_volume_sync(self, data: List[Dict[str, float]]) -> float:
        if len(data) < Config.AVG_VOLUME_PERIOD:
            return float("nan")
        volumes = [c["volume"] for c in data[-Config.AVG_VOLUME_PERIOD:]]
        return sum(volumes) / len(volumes)

    async def calculate_average_volume(self, data: List[Dict[str, float]]) -> float:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_average_volume_sync, data)

    def calculate_obv_sync(self, data: List[Dict[str, float]]) -> List[float]:
        if not data:
            return []
        obv = [0]
        for i in range(1, len(data)):
            if data[i]["close"] > data[i-1]["close"]:
                obv.append(obv[-1] + data[i]["volume"])
            elif data[i]["close"] < data[i-1]["close"]:
                obv.append(obv[-1] - data[i]["volume"])
            else:
                obv.append(obv[-1])
        return obv

    async def calculate_obv(self, data: List[Dict[str, float]]) -> List[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_obv_sync, data)

    def calculate_atr_sync(self, data: List[Dict[str, float]], period: int = 14) -> List[float]:
        if len(data) < 2:
            return [float("nan")] * len(data)
        tr = []
        for i in range(1, len(data)):
            high_low = data[i]["high"] - data[i]["low"]
            high_prev = abs(data[i]["high"] - data[i-1]["close"])
            low_prev = abs(data[i]["low"] - data[i-1]["close"])
            tr.append(max(high_low, high_prev, low_prev))
        if len(tr) < period:
            return [float("nan")] * (len(data) - 1) + [sum(tr) / len(tr) if tr else float("nan")]
        atr = [sum(tr[:period]) / period]
        for t in tr[period:]:
            atr.append((atr[-1] * (period - 1) + t) / period)
        return [float("nan")] + atr

    async def calculate_atr(self, data: List[Dict[str, float]], period: int = 14) -> List[float]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_atr_sync, data, period)

    def calculate_dynamic_threshold_sync(self, closes: List[float], factor: float = 2.2) -> float:
        if len(closes) < 2:
            return 0.005
        sum_abs_pct = 0
        for i in range(1, len(closes)):
            pct_change = abs((closes[i] - closes[i-1]) / closes[i-1]) * 100
            sum_abs_pct += pct_change
        avg_pct_change = sum_abs_pct / (len(closes) - 1)
        return (avg_pct_change * factor) / 100

    async def calculate_dynamic_threshold(self, closes: List[float], factor: float = 2.2) -> float:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_dynamic_threshold_sync, closes, factor)

    def calculate_zigzag_sync(self, closes: List[float], threshold_percent: Optional[float] = None, factor: float = 2.2) -> List[Dict[str, Any]]:
        if threshold_percent is None:
            threshold_percent = self.calculate_dynamic_threshold_sync(closes, factor)
        zigzag = []
        if len(closes) < 2:
            return zigzag
        last_index = 0
        last_value = closes[0]
        direction = 1 if closes[1] > closes[0] else -1
        initial_type = 'low' if direction == 1 else 'peak'
        zigzag.append({'index': 0, 'value': last_value, 'type': initial_type})
        for i in range(1, len(closes)):
            change = (closes[i] - last_value) / last_value
            if direction * change < -threshold_percent:
                ext_type = 'peak' if direction == 1 else 'low'
                zigzag.append({'index': last_index, 'value': last_value, 'type': ext_type})
                direction = -direction
                last_index = i
                last_value = closes[i]
            elif direction * (closes[i] - last_value) > 0:
                last_index = i
                last_value = closes[i]
        if last_index > zigzag[-1]['index']:
            last_type = 'peak' if direction == 1 else 'low'
            zigzag.append({'index': last_index, 'value': last_value, 'type': last_type})
        return zigzag

    async def calculate_zigzag(self, data: List[Dict[str, float]], threshold_percent: Optional[float] = None, factor: float = 2.2) -> List[Dict[str, Any]]:
        closes = [c['close'] for c in data]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_zigzag_sync, closes, threshold_percent, factor)

    def classify_swing_points_sync(self, zigzag_points: List[Dict[str, Any]], data: List[Dict[str, float]]) -> List[Dict[str, Any]]:
        classified = []
        peaks = [p for p in zigzag_points if p['type'] == 'peak']
        lows = [p for p in zigzag_points if p['type'] == 'low']
        for i in range(len(peaks)):
            label = 'H'
            if i > 0:
                prev_peak_value = data[peaks[i-1]['index']]['close']
                curr_peak_value = data[peaks[i]['index']]['close']
                label = 'HH' if curr_peak_value > prev_peak_value else 'LH'
            classified.append({**peaks[i], 'label': label})
        for i in range(len(lows)):
            label = 'L'
            if i > 0:
                prev_low_value = data[lows[i-1]['index']]['close']
                curr_low_value = data[lows[i]['index']]['close']
                label = 'HL' if curr_low_value > prev_low_value else 'LL'
            classified.append({**lows[i], 'label': label})
        classified.sort(key=lambda x: x['index'])
        return classified

    async def classify_swing_points(self, zigzag_points: List[Dict[str, Any]], data: List[Dict[str, float]]) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.classify_swing_points_sync, zigzag_points, data)

    def find_extremum_in_window_sync(self, rsi_values: List[Optional[float]], index: int, left_window: int, right_window: int, is_min: bool) -> Dict[str, Any]:
        start = max(0, index - left_window)
        end = min(len(rsi_values) - 1, index + right_window)
        extremum_value = rsi_values[index]
        extremum_index = index
        if extremum_value is None:
            return {'value': None, 'index': index}
        for i in range(start, end + 1):
            if rsi_values[i] is None:
                continue
            if (is_min and rsi_values[i] < extremum_value) or (not is_min and rsi_values[i] > extremum_value):
                extremum_value = rsi_values[i]
                extremum_index = i
        return {'value': extremum_value, 'index': extremum_index}

    async def find_extremum_in_window(self, rsi_values: List[Optional[float]], index: int, left_window: int, right_window: int, is_min: bool) -> Dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.find_extremum_in_window_sync, rsi_values, index, left_window, right_window, is_min)

    def detect_divergences_sync(self, rsi_values: List[Optional[float]], zigzag_points: List[Dict[str, Any]], data: List[Dict[str, float]], left_window: int = 3, right_window: int = 0) -> List[Dict[str, Any]]:
        divergences = []
        lows = [p for p in zigzag_points if p['type'] == 'low']
        peaks = [p for p in zigzag_points if p['type'] == 'peak']
        for i in range(1, len(lows)):
            prev_low = lows[i - 1]
            curr_low = lows[i]
            prev_price = data[prev_low['index']]['close']
            curr_price = data[curr_low['index']]['close']
            prev_rsi_info = self.find_extremum_in_window_sync(rsi_values, prev_low['index'], left_window, right_window, True)
            curr_rsi_info = self.find_extremum_in_window_sync(rsi_values, curr_low['index'], left_window, right_window, True)
            if prev_rsi_info['value'] is None or curr_rsi_info['value'] is None:
                continue
            if curr_price < prev_price and curr_rsi_info['value'] > prev_rsi_info['value']:
                divergences.append({
                    'type': 'bullish',
                    'startIndex': prev_rsi_info['index'],
                    'endIndex': curr_rsi_info['index'],
                    'startPrice': prev_price,
                    'endPrice': curr_price,
                    'startRSI': prev_rsi_info['value'],
                    'endRSI': curr_rsi_info['value']
                })
            if curr_price > prev_price and curr_rsi_info['value'] < prev_rsi_info['value']:
                divergences.append({
                    'type': 'hidden_bullish',
                    'startIndex': prev_rsi_info['index'],
                    'endIndex': curr_rsi_info['index'],
                    'startPrice': prev_price,
                    'endPrice': curr_price,
                    'startRSI': prev_rsi_info['value'],
                    'endRSI': curr_rsi_info['value']
                })
        for i in range(1, len(peaks)):
            prev_peak = peaks[i - 1]
            curr_peak = peaks[i]
            prev_price = data[prev_peak['index']]['close']
            curr_price = data[curr_peak['index']]['close']
            prev_rsi_info = self.find_extremum_in_window_sync(rsi_values, prev_peak['index'], left_window, right_window, False)
            curr_rsi_info = self.find_extremum_in_window_sync(rsi_values, curr_peak['index'], left_window, right_window, False)
            if prev_rsi_info['value'] is None or curr_rsi_info['value'] is None:
                continue
            if curr_price > prev_price and curr_rsi_info['value'] < prev_rsi_info['value']:
                divergences.append({
                    'type': 'bearish',
                    'startIndex': prev_rsi_info['index'],
                    'endIndex': curr_rsi_info['index'],
                    'startPrice': prev_price,
                    'endPrice': curr_price,
                    'startRSI': prev_rsi_info['value'],
                    'endRSI': curr_rsi_info['value']
                })
            if curr_price < prev_price and curr_rsi_info['value'] > prev_rsi_info['value']:
                divergences.append({
                    'type': 'hidden_bearish',
                    'startIndex': prev_rsi_info['index'],
                    'endIndex': curr_rsi_info['index'],
                    'startPrice': prev_price,
                    'endPrice': curr_price,
                    'startRSI': prev_rsi_info['value'],
                    'endRSI': curr_rsi_info['value']
                })
        return divergences

    async def detect_divergences(self, rsi_values: List[Optional[float]], zigzag_points: List[Dict[str, Any]], data: List[Dict[str, float]], left_window: int = 3, right_window: int = 0) -> List[Dict[str, Any]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.detect_divergences_sync, rsi_values, zigzag_points, data, left_window, right_window)

    def calculate_stochastic_sync(self, data: List[Dict[str, float]], k_period: int = 14, d_period: int = 3) -> Tuple[List[float], List[float]]:
        k = []
        for i in range(len(data)):
            if i < k_period - 1:
                k.append(float("nan"))
                continue
            lows = [c["low"] for c in data[i - k_period + 1:i + 1]]
            highs = [c["high"] for c in data[i - k_period + 1:i + 1]]
            lowest = min(lows)
            highest = max(highs)
            if highest == lowest:
                k.append(50.0)
            else:
                k.append(100 * (data[i]["close"] - lowest) / (highest - lowest))
        d = self.calculate_sma_sync([{"close": val} for val in k if not math.isnan(val)], d_period)
        return k, d[-len(k):] if len(d) < len(k) else d  # Adjust length if needed

    async def calculate_stochastic(self, data: List[Dict[str, float]], k_period: int = 14, d_period: int = 3) -> Tuple[List[float], List[float]]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self.executor, self.calculate_stochastic_sync, data, k_period, d_period)