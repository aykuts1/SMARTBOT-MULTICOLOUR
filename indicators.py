import numpy as np
from logger_setup import get_logger

log = get_logger("indicators")


def calc_ema(closes, period):
    if len(closes) < period:
        return []
    ema = [0.0] * len(closes)
    multiplier = 2.0 / (period + 1)
    ema[period - 1] = np.mean(closes[:period])
    for i in range(period, len(closes)):
        ema[i] = (closes[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema


def calc_atr(highs, lows, closes, period):
    if len(closes) < 2:
        return []
    tr = [0.0] * len(closes)
    tr[0] = highs[0] - lows[0]
    for i in range(1, len(closes)):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1])
        )
    atr = [0.0] * len(closes)
    if len(tr) < period:
        return atr
    atr[period - 1] = np.mean(tr[:period])
    for i in range(period, len(closes)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def calc_stochastic(highs, lows, closes, k_length, k_smoothing, d_period):
    n = len(closes)
    if n < k_length:
        return [], []

    raw_k = [0.0] * n
    for i in range(k_length - 1, n):
        high_max = max(highs[i - k_length + 1:i + 1])
        low_min = min(lows[i - k_length + 1:i + 1])
        if high_max - low_min > 0:
            raw_k[i] = ((closes[i] - low_min) / (high_max - low_min)) * 100
        else:
            raw_k[i] = 50.0

    k_line = _sma_smooth(raw_k, k_smoothing, k_length - 1)
    d_line = _sma_smooth(k_line, d_period, k_length + k_smoothing - 2)

    return k_line, d_line


def _sma_smooth(data, period, start_from=0):
    n = len(data)
    result = [0.0] * n
    for i in range(start_from + period - 1, n):
        result[i] = np.mean(data[i - period + 1:i + 1])
    return result


def calc_macd(closes, fast_period, slow_period, signal_period):
    if len(closes) < slow_period:
        return [], [], []

    fast_ema = calc_ema(closes, fast_period)
    slow_ema = calc_ema(closes, slow_period)

    macd_line = [0.0] * len(closes)
    for i in range(slow_period - 1, len(closes)):
        macd_line[i] = fast_ema[i] - slow_ema[i]

    signal_line = [0.0] * len(closes)
    start = slow_period - 1
    valid_macd = macd_line[start:]
    if len(valid_macd) >= signal_period:
        sig_ema = calc_ema(valid_macd, signal_period)
        for i in range(len(sig_ema)):
            signal_line[start + i] = sig_ema[i]

    histogram = [0.0] * len(closes)
    for i in range(len(closes)):
        histogram[i] = macd_line[i] - signal_line[i]

    return macd_line, signal_line, histogram


def calc_bollinger(closes, period, std_dev):
    n = len(closes)
    if n < period:
        return [], [], []

    upper = [0.0] * n
    middle = [0.0] * n
    lower = [0.0] * n

    for i in range(period - 1, n):
        window = closes[i - period + 1:i + 1]
        mean = np.mean(window)
        std = np.std(window, ddof=0)
        middle[i] = mean
        upper[i] = mean + std_dev * std
        lower[i] = mean - std_dev * std

    return upper, middle, lower


def calc_keltner_with_outer(closes, highs, lows, ema_period, atr_period, multiplier, outer_multiplier):
    n = len(closes)
    ema = calc_ema(closes, ema_period)
    atr = calc_atr(highs, lows, closes, atr_period)

    upper = [0.0] * n
    lower = [0.0] * n
    outer_upper = [0.0] * n
    outer_lower = [0.0] * n

    for i in range(n):
        if ema[i] > 0:
            upper[i] = ema[i] + multiplier * atr[i]
            lower[i] = ema[i] - multiplier * atr[i]
            outer_upper[i] = ema[i] + outer_multiplier * atr[i]
            outer_lower[i] = ema[i] - outer_multiplier * atr[i]

    return upper, ema, lower, outer_upper, outer_lower


def calc_kdj(highs, lows, closes, period=9, k_smooth=3, d_smooth=3):
    n = len(closes)
    k_vals = [0.0] * n
    d_vals = [0.0] * n
    j_vals = [0.0] * n

    if n < period:
        return k_vals, d_vals, j_vals

    prev_k = 50.0
    prev_d = 50.0

    for i in range(period - 1, n):
        high_max = max(highs[i - period + 1:i + 1])
        low_min = min(lows[i - period + 1:i + 1])
        rsv = (closes[i] - low_min) / (high_max - low_min) * 100.0 if high_max > low_min else 50.0
        k = (prev_k * (k_smooth - 1) + rsv) / k_smooth
        d = (prev_d * (d_smooth - 1) + k) / d_smooth
        k_vals[i] = k
        d_vals[i] = d
        j_vals[i] = 3.0 * k - 2.0 * d
        prev_k = k
        prev_d = d

    return k_vals, d_vals, j_vals


def calc_keltner(closes, highs, lows, ema_period, atr_period, multiplier):
    n = len(closes)
    ema = calc_ema(closes, ema_period)
    atr = calc_atr(highs, lows, closes, atr_period)

    upper = [0.0] * n
    lower = [0.0] * n

    for i in range(n):
        if ema[i] > 0:
            upper[i] = ema[i] + multiplier * atr[i]
            lower[i] = ema[i] - multiplier * atr[i]

    return upper, ema, lower


def calc_donchian(highs, lows, period):
    n = len(highs)
    if n < period:
        return [], []

    upper = [0.0] * n
    lower = [0.0] * n

    for i in range(period - 1, n):
        upper[i] = max(highs[i - period + 1:i + 1])
        lower[i] = min(lows[i - period + 1:i + 1])

    return upper, lower


def detect_crossover_down(fast, slow, index):
    if index < 1:
        return False
    return fast[index - 1] >= slow[index - 1] and fast[index] < slow[index]


def detect_crossover_up(fast, slow, index):
    if index < 1:
        return False
    return fast[index - 1] <= slow[index - 1] and fast[index] > slow[index]


def compute_all_indicators(candles, config):
    if not candles or len(candles) < 2:
        return {}

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]

    result = {}

    ema_period = config.get("beyaz", {}).get("ema_periyodu", 48)
    atr_period = config.get("beyaz", {}).get("atr_periyodu", 48)
    ema_main = calc_ema(closes, ema_period)
    atr_main = calc_atr(highs, lows, closes, atr_period)
    result["ema_main"] = ema_main
    result["atr_main"] = atr_main

    beyaz = config.get("beyaz", {})
    k_line, d_line = calc_stochastic(
        highs, lows, closes,
        beyaz.get("stokastik_k_length", 50),
        beyaz.get("stokastik_k_smoothing", 21),
        beyaz.get("stokastik_d", 8)
    )
    result["stoch_k"] = k_line
    result["stoch_d"] = d_line

    macd_line, signal_line, histogram = calc_macd(
        closes,
        beyaz.get("macd_hizli", 21),
        beyaz.get("macd_yavas", 50),
        beyaz.get("macd_signal", 9)
    )
    result["macd"] = macd_line
    result["macd_signal"] = signal_line
    result["macd_hist"] = histogram

    sari = config.get("sari", {})
    bb_upper, bb_middle, bb_lower = calc_bollinger(
        closes,
        sari.get("bollinger_periyot", 20),
        sari.get("bollinger_sapma", 2)
    )
    result["bb_upper"] = bb_upper
    result["bb_middle"] = bb_middle
    result["bb_lower"] = bb_lower

    siyah = config.get("siyah", {})
    dc_upper, dc_lower = calc_donchian(
        highs, lows,
        siyah.get("donchian_periyodu", 50)
    )
    result["dc_upper"] = dc_upper
    result["dc_lower"] = dc_lower

    altin = config.get("altin", {})
    kdj_k, kdj_d, kdj_j = calc_kdj(
        highs, lows, closes,
        altin.get("kdj_periyot", 9),
        altin.get("kdj_k_smooth", 3),
        altin.get("kdj_d_smooth", 3)
    )
    result["kdj_k"] = kdj_k
    result["kdj_d"] = kdj_d
    result["kdj_j"] = kdj_j

    kc_upper, kc_middle, kc_lower = calc_keltner(
        closes, highs, lows,
        altin.get("keltner_ema_periyot", 200),
        altin.get("keltner_atr_periyot", 200),
        altin.get("keltner_carpan", 1.0)
    )
    result["kc_upper"] = kc_upper
    result["kc_middle"] = kc_middle
    result["kc_lower"] = kc_lower

    kirmizi = config.get("kirmizi", {})
    kc_red_upper, kc_red_middle, kc_red_lower, kc_red_outer_upper, kc_red_outer_lower = calc_keltner_with_outer(
        closes, highs, lows,
        kirmizi.get("keltner_ema_periyot", 48),
        kirmizi.get("keltner_atr_periyot", 48),
        kirmizi.get("keltner_carpan", 1.0),
        kirmizi.get("keltner_dis_carpan", 1.5)
    )
    result["kc_red_upper"] = kc_red_upper
    result["kc_red_middle"] = kc_red_middle
    result["kc_red_lower"] = kc_red_lower
    result["kc_red_outer_upper"] = kc_red_outer_upper
    result["kc_red_outer_lower"] = kc_red_outer_lower

    result["closes"] = closes
    result["highs"] = highs
    result["lows"] = lows

    return result
