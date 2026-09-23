# -*- coding: utf-8 -*-
"""
indicators.py
-------------
Butun gosterge hesaplamalari burada: ATR, Supertrend (ana trend cizgisi
ve yon), ve Supertrend'e bagli iki cizgi: Gold cizgi ve Silver cizgi.

KOKLU GUNCELLEME (Gold/Silver adlandirma): Eskiden "Entry cizgisi" /
"Exit cizgisi" denen iki cizgi artik "Gold cizgi" (1.2 ATR) ve "Silver
cizgi" (2.4 ATR) olarak adlandiriliyor. Formuller AYNI - sadece isimler
degisti, cunku artik ikisi de hem giris hem cikis (TP) rolu oynuyor:
Gold islem Gold'dan girer Silver'a cikar; Silver islem Silver'dan girer
Gold'a cikar.

Supertrend hesabi dogasi geregi "kendine bagli" (recursive) bir hesap:
her mumun up/dn/trend degeri bir onceki mumun sonucuna bakar. Bu yuzden
pandas'ta vektorel degil, satir satir (dongu ile) hesaplaniyor.
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
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ============================================================
# SUPERTREND - kullanicinin verdigi orijinal Pine v4 kodundaki
# formulun birebir Python karsiligi.
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
        gold_line, silver_line,
        long_gold_line, long_silver_line, short_gold_line, short_silver_line

    trend: 1 = yukselis, -1 = dusus.

    gold_line / silver_line: Supertrend'in O ANKI aktif cizgisinden
    (trend=1 ise up, trend=-1 ise dn) fiyata dogru kaydirilmis iki cizgi -
    bunlar GIRIS sinyalleri icin kullanilir (hem Gold hem Silver islem
    hangi yonde acilacagini o anki trend'den belirledigi icin dogru
    secim budur - Gold trend yonunde, Silver bunun tersi yonde acilir,
    ama ikisi de AYNI trend okumasina bakar).

    long_gold_line / long_silver_line / short_gold_line / short_silver_line:
    "up" ve "dn" cizgileri HER ZAMAN, trend hangi yonde olursa olsun,
    paralel olarak hesaplanir. Bu yuzden ACIK BIR POZISYONUN TP hedefi
    kontrol edilirken, o anki genel "trend" bayragi degil, pozisyonun
    KENDI yonune karsilik gelen bu sabit-tarafli kolonlar kullanilmalidir
    (bkz. strategy.check_tp_exit). Aksi halde, mum henuz kapanmadan
    (saniyelik veriyle) genel trend gecici olarak ters donerse, hedef
    cizgi de karsi tarafin formulune gecer ve pozisyonun yonuyle
    uyusmayan bir seviye haline gelebilir; bu da zararli bir kapanisin
    yanlislikla "Take Profit" olarak etiketlenmesine yol acar (canli
    ortamda bu yasandi ve bu yuzden ayri sabit-tarafli kolonlar var).
    """
    out = df.copy()

    up, dn, trend, atr_deger = supertrend(out)
    out["atr_deger"] = atr_deger
    out["supertrend_up"] = up
    out["supertrend_dn"] = dn
    out["trend"] = trend

    out["long_gold_line"] = out["supertrend_up"] + config.GOLD_LINE_ATR_MULT * out["atr_deger"]
    out["long_silver_line"] = out["supertrend_up"] + config.SILVER_LINE_ATR_MULT * out["atr_deger"]
    out["short_gold_line"] = out["supertrend_dn"] - config.GOLD_LINE_ATR_MULT * out["atr_deger"]
    out["short_silver_line"] = out["supertrend_dn"] - config.SILVER_LINE_ATR_MULT * out["atr_deger"]

    is_up = out["trend"] == 1
    out["gold_line"] = np.where(is_up, out["long_gold_line"], out["short_gold_line"])
    out["silver_line"] = np.where(is_up, out["long_silver_line"], out["short_silver_line"])

    return out
