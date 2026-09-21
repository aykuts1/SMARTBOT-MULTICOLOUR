# -*- coding: utf-8 -*-
"""
indicators.py
-------------
Butun gosterge hesaplamalari burada: Tilson T3, Merkez cizgisi (ALMA),
ATR ve bunlarin ust/alt bantlari.

Bu dosyadaki formuller, kullanicinin verdigi orijinal Pine Script
kodlariyla ayni matematigi kullanir - sadece Python/pandas'a cevrilmistir.
"""

import numpy as np
import pandas as pd

import config


# ============================================================
# TILSON T3
# ============================================================
def _ema(series: pd.Series, length: int) -> pd.Series:
    """Pine'daki ema() ile ayni: klasik ussel hareketli ortalama."""
    return series.ewm(span=length, adjust=False).mean()


def tilson_t3(close: pd.Series, period: int = None, factor: float = None) -> pd.Series:
    """
    Tilson T3 - kullanicinin verdigi orijinal Pine kodundaki formulun
    birebir Python karsiligi (6 katmanli EMA + c1..c4 katsayilari).
    """
    period = period or config.T3_PERIOD
    b = factor if factor is not None else config.T3_VOLUME_FACTOR

    c1 = -b ** 3
    c2 = 3 * b ** 2 + 3 * b ** 3
    c3 = -6 * b ** 2 - 3 * b - 3 * b ** 3
    c4 = 1 + 3 * b + b ** 3 + 3 * b ** 2

    e1 = _ema(close, period)
    e2 = _ema(e1, period)
    e3 = _ema(e2, period)
    e4 = _ema(e3, period)
    e5 = _ema(e4, period)
    e6 = _ema(e5, period)

    t3 = c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3
    return t3


# ============================================================
# MERKEZ CIZGISI (ALMA - Arnaud Legoux Moving Average)
# ============================================================
def merkez_cizgisi(close: pd.Series, length: int = None, offset: float = None,
                    sigma: float = None) -> pd.Series:
    """
    ALMA formulu - kullanicinin verdigi orijinal Pine kodundaki
    ta.alma() ile matematiksel olarak ayni. Bot icinde bu cizgi
    "Merkez cizgisi" olarak adlandirilir.
    """
    length = length or config.MERKEZ_LENGTH
    offset = offset if offset is not None else config.MERKEZ_OFFSET
    sigma = sigma if sigma is not None else config.MERKEZ_SIGMA

    m = offset * (length - 1)
    s = length / sigma

    weights = np.array([np.exp(-((i - m) ** 2) / (2 * s * s)) for i in range(length)])
    weights /= weights.sum()

    def _weighted(window):
        return np.dot(window, weights)

    return close.rolling(window=length).apply(_weighted, raw=True)


# ============================================================
# ATR (Average True Range) - Wilder's smoothing (TradingView standardi)
# ============================================================
def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = None) -> pd.Series:
    period = period or config.ATR_PERIOD
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Wilder's RMA (TradingView'in ta.atr'sinin kullandigi yontem)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ============================================================
# HEPSINI BIR ARADA HESAPLA
# ============================================================
def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    df: 'high','low','close' kolonlari olan, eskiden yeniye siralanmis
    mum verisi. Geri donen dataframe'e su kolonlar eklenir:
        t3, t3_ust_bant, t3_alt_bant,
        merkez, merkez_ust_bant, merkez_alt_bant,
        atr_deger
    """
    out = df.copy()

    out["atr_deger"] = atr(out["high"], out["low"], out["close"])

    out["t3"] = tilson_t3(out["close"])
    out["t3_ust_bant"] = out["t3"] + out["atr_deger"] * config.T3_BAND_ATR_MULT
    out["t3_alt_bant"] = out["t3"] - out["atr_deger"] * config.T3_BAND_ATR_MULT

    out["merkez"] = merkez_cizgisi(out["close"])
    out["merkez_ust_bant"] = out["merkez"] + out["atr_deger"] * config.MERKEZ_BAND_ATR_MULT
    out["merkez_alt_bant"] = out["merkez"] - out["atr_deger"] * config.MERKEZ_BAND_ATR_MULT

    return out
