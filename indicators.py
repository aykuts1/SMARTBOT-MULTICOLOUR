"""
Technical indicators: EMA, ATR, Channel Width.
All functions are pure (no I/O) and operate on numeric lists.
"""
from typing import List, Optional


def ema(values: List[float], period: int) -> List[Optional[float]]:
    """
    Standard EMA. Returns list same length as input.
    First (period-1) elements are None; element at index (period-1) is the SMA seed.
    """
    if period <= 0 or len(values) < period:
        return [None] * len(values)

    out: List[Optional[float]] = [None] * len(values)
    # Seed with SMA of first `period` values
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    k = 2 / (period + 1)
    for i in range(period, len(values)):
        prev = out[i - 1]
        out[i] = (values[i] - prev) * k + prev
    return out


def true_range(highs: List[float], lows: List[float], closes: List[float]) -> List[float]:
    """
    True Range for each bar. TR[0] = high[0] - low[0] (no prior close).
    """
    n = len(highs)
    tr = [0.0] * n
    if n == 0:
        return tr
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        h_l = highs[i] - lows[i]
        h_pc = abs(highs[i] - closes[i - 1])
        l_pc = abs(lows[i] - closes[i - 1])
        tr[i] = max(h_l, h_pc, l_pc)
    return tr


def atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[Optional[float]]:
    """
    Wilder's ATR (RMA of True Range).
    Returns list same length as input; first `period-1` elements are None.
    """
    tr = true_range(highs, lows, closes)
    n = len(tr)
    out: List[Optional[float]] = [None] * n
    if n < period:
        return out
    # Seed with SMA of first `period` TRs
    seed = sum(tr[:period]) / period
    out[period - 1] = seed
    for i in range(period, n):
        prev = out[i - 1]
        out[i] = (prev * (period - 1) + tr[i]) / period
    return out


def channel_widths(ema_high: List[Optional[float]], ema_low: List[Optional[float]]) -> List[Optional[float]]:
    """
    Difference between EMA(high) and EMA(low) per bar.
    """
    n = len(ema_high)
    out: List[Optional[float]] = [None] * n
    for i in range(n):
        if ema_high[i] is not None and ema_low[i] is not None:
            out[i] = ema_high[i] - ema_low[i]
    return out


def rolling_average(values: List[Optional[float]], window: int) -> List[Optional[float]]:
    """
    Simple rolling average over `window` bars.
    Skips None values; returns None until enough data.
    """
    n = len(values)
    out: List[Optional[float]] = [None] * n
    for i in range(n):
        start = i - window + 1
        if start < 0:
            continue
        window_slice = values[start:i + 1]
        if any(v is None for v in window_slice):
            continue
        out[i] = sum(window_slice) / window  # type: ignore
    return out


def compute_all_indicators(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    ema_high_period: int,
    ema_low_period: int,
    ema_trigger_period: int,
    atr_period: int,
    channel_avg_period: int,
) -> dict:
    """
    Compute all indicators we need in one call.
    Returns dict with all series; caller usually only needs the last 2 values.
    """
    ema_h = ema(highs, ema_high_period)
    ema_l = ema(lows, ema_low_period)
    ema_t = ema(closes, ema_trigger_period)
    atr_v = atr(highs, lows, closes, atr_period)
    width = channel_widths(ema_h, ema_l)
    width_avg = rolling_average(width, channel_avg_period)
    return {
        "ema_high": ema_h,
        "ema_low": ema_l,
        "ema_trigger": ema_t,
        "atr": atr_v,
        "channel_width": width,
        "channel_width_avg": width_avg,
    }
