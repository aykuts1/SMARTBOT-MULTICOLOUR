# -*- coding: utf-8 -*-
"""
indicators.py
-------------
Butun gosterge hesaplamalari burada: ATR, Supertrend (ana trend cizgisi
ve yon), ve Supertrend'e bagli iki cizgi: Entry cizgisi ve Exit cizgisi.

KOKLU GUNCELLEME: Eski Tilson T3 ve Merkez (ALMA) gostergeleri tamamen
kaldirildi. Strateji artik tamamen Supertrend tabanli.

Supertrend hesabi dogasi geregi "kendine bagli" (recursive) bir hesap:
her mumun up/dn/trend degeri bir onceki mumun sonucuna bakar. Bu yuzden
pandas'ta vektorel degil, satir satir (dongu ile) hesaplaniyor - tipki
TradingView'in Pine Script'te yaptigi gibi. 300 mumluk bir seri icin bu
dongu maliyeti onemsizdir.
"""

import numpy as np
import pandas as pd

import config


# ============================================================
# ATR (Average True Range) - Wilder's smoothing (TradingView standardi)
# ============================================================
def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    # Wilder's RMA (TradingView'in ta.atr'sinin kullandigi yontem)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ============================================================
# SUPERTREND - kullanicinin verdigi orijinal Pine v4 kodundaki
# formulun birebir Python karsiligi.
#
# Pine mantigi (ozet):
#   src = hl2
#   basic_up = src - Multiplier*atr
#   basic_dn = src + Multiplier*atr
#   up1 = onceki barin nihai "up" degeri (yoksa bu barin basic_up'i)
#   up  = onceki kapanis > up1 ise max(basic_up, up1), degilse basic_up
#   dn1 = onceki barin nihai "dn" degeri (yoksa bu barin basic_dn'i)
#   dn  = onceki kapanis < dn1 ise min(basic_dn, dn1), degilse basic_dn
#   trend: -1'den 1'e, kapanis dn1'in ustune cikinca; 1'den -1'e, kapanis
#          up1'in altina inince doner. Aksi halde onceki trend korunur.
# ============================================================
def supertrend(df: pd.DataFrame, period: int = None, multiplier: float = None):
    """df: 'high','low','close' kolonlari olan, eskiden yeniye siralanmis
    mum verisi. Donen deger: (up, dn, trend, atr_deger) - hepsi df ile
    ayni index'e sahip pandas Series."""
    period = period or config.SUPERTREND_ATR_PERIOD
    multiplier = multiplier if multiplier is not None else config.SUPERTREND_MULTIPLIER

    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    close = df["close"].to_numpy()
    src = (high + low) / 2.0  # hl2

    atr_deger = atr(df["high"], df["low"], df["close"], period).to_numpy()

    n = len(df)
    up = np.full(n, np.nan)
    dn = np.full(n, np.nan)
    trend = np.ones(n, dtype=int)  # Pine'da baslangic: trend = 1

    for i in range(n):
        basic_up = src[i] - multiplier * atr_deger[i]
        basic_dn = src[i] + multiplier * atr_deger[i]

        if i == 0:
            up[i] = basic_up
            dn[i] = basic_dn
            trend[i] = 1
            continue

        up1 = up[i - 1] if not np.isnan(up[i - 1]) else basic_up
        up[i] = max(basic_up, up1) if close[i - 1] > up1 else basic_up

        dn1 = dn[i - 1] if not np.isnan(dn[i - 1]) else basic_dn
        dn[i] = min(basic_dn, dn1) if close[i - 1] < dn1 else basic_dn

        prev_trend = trend[i - 1]
        if prev_trend == -1 and close[i] > dn1:
            trend[i] = 1
        elif prev_trend == 1 and close[i] < up1:
            trend[i] = -1
        else:
            trend[i] = prev_trend

    idx = df.index
    return (
        pd.Series(up, index=idx),
        pd.Series(dn, index=idx),
        pd.Series(trend, index=idx),
        pd.Series(atr_deger, index=idx),
    )


# ============================================================
# HEPSINI BIR ARADA HESAPLA
# ============================================================
def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    df: 'high','low','close' kolonlari olan, eskiden yeniye siralanmis
    mum verisi. Geri donen dataframe'e su kolonlar eklenir:
        atr_deger, supertrend_up, supertrend_dn, trend,
        entry_line, exit_line

    trend: 1 = yukselis (long yonu), -1 = dusus (short yonu)
    entry_line / exit_line: Supertrend'in o anki aktif cizgisinden
    (trend=1 ise up, trend=-1 ise dn) fiyata dogru kaydirilmis iki cizgi.
    """
    out = df.copy()

    up, dn, trend, atr_deger = supertrend(out)
    out["atr_deger"] = atr_deger
    out["supertrend_up"] = up
    out["supertrend_dn"] = dn
    out["trend"] = trend

    is_up = out["trend"] == 1
    out["entry_line"] = np.where(
        is_up,
        out["supertrend_up"] + config.ENTRY_LINE_ATR_MULT * out["atr_deger"],
        out["supertrend_dn"] - config.ENTRY_LINE_ATR_MULT * out["atr_deger"],
    )
    out["exit_line"] = np.where(
        is_up,
        out["supertrend_up"] + config.EXIT_LINE_ATR_MULT * out["atr_deger"],
        out["supertrend_dn"] - config.EXIT_LINE_ATR_MULT * out["atr_deger"],
    )

    return out
