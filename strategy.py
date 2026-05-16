"""
Strategy module - generates entry signals from indicator values.

Long signal (5min candle close):
  - EMA7(close) > EMA100(high)  on the just-closed candle
  - channel_width > avg(channel_width, 100)

Short signal:
  - EMA7(close) < EMA100(low)
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
    Evaluate the just-closed candle.
    Returns Signal if entry conditions met, else None.

    klines: list of dicts (oldest first) with open/high/low/close.
    The last element must be a CLOSED candle (caller ensures this).
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

    # Use the last completed candle (index -1)
    i = len(klines) - 1
    ema_h = ind["ema_high"][i]
    ema_l = ind["ema_low"][i]
    ema_t = ind["ema_trigger"][i]
    atr_v = ind["atr"][i]
    cw = ind["channel_width"][i]
    cw_avg = ind["channel_width_avg"][i]

    # All required values must be present
    if any(v is None for v in (ema_h, ema_l, ema_t, atr_v, cw, cw_avg)):
        return None

    # Channel width filter (avoids ranging market)
    if cw <= cw_avg:
        return None

    close_price = closes[i]

    # LONG: EMA7 closes above EMA100(High)
    if ema_t > ema_h:
        return Signal(
            side="Buy",
            symbol=symbol,
            entry_price=close_price,
            atr=atr_v,
            ema_high=ema_h,
            ema_low=ema_l,
            ema_trigger=ema_t,
            channel_width=cw,
            channel_width_avg=cw_avg,
        )

    # SHORT: EMA7 closes below EMA100(Low)
    if ema_t < ema_l:
        return Signal(
            side="Sell",
            symbol=symbol,
            entry_price=close_price,
            atr=atr_v,
            ema_high=ema_h,
            ema_low=ema_l,
            ema_trigger=ema_t,
            channel_width=cw,
            channel_width_avg=cw_avg,
        )

    return None


def check_reverse_signal(side: str, klines: List[Dict]) -> bool:
    """
    Check if EMA7 has crossed the opposite EMA100 channel on the latest closed candle.
    Used to force-close positions when strategy reverses.

    For a Long position: returns True if EMA7 < EMA100(Low).
    For a Short position: returns True if EMA7 > EMA100(High).
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
    if ema_h[i] is None or ema_l[i] is None or ema_t[i] is None:
        return False

    if side == "Buy":
        # Long position reverses if EMA7 dropped below EMA100(Low)
        return ema_t[i] < ema_l[i]
    else:
        # Short position reverses if EMA7 rose above EMA100(High)
        return ema_t[i] > ema_h[i]
