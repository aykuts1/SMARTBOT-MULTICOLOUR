"""
Strategy module - generates entry signals from indicator values.

Long signal (5min candle close):
  - Previous candle: EMA7(close) <= EMA100(high)
  - Last closed candle: EMA7(close) > EMA100(high)   ← crossover up
  - channel_width > avg(channel_width, 100)

Short signal:
  - Previous candle: EMA7(close) >= EMA100(low)
  - Last closed candle: EMA7(close) < EMA100(low)    ← crossover down
  - channel_width > avg(channel_width, 100)
"""
from typing import Optional, Dict, List
from dataclasses import dataclass

import indicators
import config


@dataclass
class Signal:
    side: str           # "Buy" or "Sell"
    symbol: str
    entry_price: float  # close of signal candle
    atr: float          # ATR at signal candle
    ema_high: float
    ema_low: float
    ema_trigger: float
    channel_width: float
    channel_width_avg: float


def evaluate_entry(symbol: str, klines: List[Dict]) -> Optional[Signal]:
    """
    Evaluate the just-closed candle for a CROSSOVER signal.
    Returns Signal if entry conditions met, else None.

    klines: list of dicts (oldest first) with open/high/low/close.
    The last element must be a CLOSED candle (caller strips the open one).
    """
    if len(klines) < max(config.EMA_HIGH_PERIOD, config.CHANNEL_AVG_PERIOD) + 5:
        return None

    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    closes = [k["close"] for k in klines]

    ind = indicators.compute_all_indicators(
        highs=highs,
        lows=lows,
        closes=closes,
        ema_high_period=config.EMA_HIGH_PERIOD,
        ema_low_period=config.EMA_LOW_PERIOD,
        ema_trigger_period=config.EMA_TRIGGER_PERIOD,
        atr_period=config.ATR_PERIOD,
        channel_avg_period=config.CHANNEL_AVG_PERIOD,
    )

    # Last closed candle index and previous candle index
    i = len(klines) - 1
    j = i - 1

    ema_h_now = ind["ema_high"][i]
    ema_l_now = ind["ema_low"][i]
    ema_t_now = ind["ema_trigger"][i]
    ema_h_prev = ind["ema_high"][j]
    ema_l_prev = ind["ema_low"][j]
    ema_t_prev = ind["ema_trigger"][j]
    atr_v = ind["atr"][i]
    cw = ind["channel_width"][i]
    cw_avg = ind["channel_width_avg"][i]

    # All required values must be present
    if any(v is None for v in (
        ema_h_now, ema_l_now, ema_t_now,
        ema_h_prev, ema_l_prev, ema_t_prev,
        atr_v, cw, cw_avg,
    )):
        return None

    # Channel width filter (avoids ranging market)
    if cw <= cw_avg:
        return None

    close_price = closes[i]

    # LONG crossover: EMA7 was at/below EMA100(High), now above
    if ema_t_prev <= ema_h_prev and ema_t_now > ema_h_now:
        return Signal(
            side="Buy",
            symbol=symbol,
            entry_price=close_price,
            atr=atr_v,
            ema_high=ema_h_now,
            ema_low=ema_l_now,
            ema_trigger=ema_t_now,
            channel_width=cw,
            channel_width_avg=cw_avg,
        )

    # SHORT crossover: EMA7 was at/above EMA100(Low), now below
    if ema_t_prev >= ema_l_prev and ema_t_now < ema_l_now:
        return Signal(
            side="Sell",
            symbol=symbol,
            entry_price=close_price,
            atr=atr_v,
            ema_high=ema_h_now,
            ema_low=ema_l_now,
            ema_trigger=ema_t_now,
            channel_width=cw,
            channel_width_avg=cw_avg,
        )

    return None


def check_reverse_signal(side: str, klines: List[Dict]) -> bool:
    """
    Check if EMA7 has crossed the opposite EMA100 channel on the latest closed candle.
    Used to force-close positions when strategy reverses.

    For a Long position: returns True if EMA7 crossed BELOW EMA100(Low) on last candle.
    For a Short position: returns True if EMA7 crossed ABOVE EMA100(High) on last candle.
    """
    if len(klines) < config.EMA_HIGH_PERIOD + 2:
        return False

    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    closes = [k["close"] for k in klines]

    ema_h = indicators.ema(highs, config.EMA_HIGH_PERIOD)
    ema_l = indicators.ema(lows, config.EMA_LOW_PERIOD)
    ema_t = indicators.ema(closes, config.EMA_TRIGGER_PERIOD)

    i = len(klines) - 1
    j = i - 1
    if any(v is None for v in (ema_h[i], ema_l[i], ema_t[i], ema_h[j], ema_l[j], ema_t[j])):
        return False

    if side == "Buy":
        # Long reverses on bearish crossover of EMA100(Low)
        return ema_t[j] >= ema_l[j] and ema_t[i] < ema_l[i]
    else:
        # Short reverses on bullish crossover of EMA100(High)
        return ema_t[j] <= ema_h[j] and ema_t[i] > ema_h[i]
