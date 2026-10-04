# -*- coding: utf-8 -*-
"""
indicators.py
-----------------------
Faytterro Bands (Pine v5) gostergesinin Python karsiligi.

Pine kodunda botun baktigi deger, "extrapolation" dizisinin SON elemani:
    diz[len-1]  -> ust bant, SU ANKI muma denk gelen nokta
    diz2[len-1] -> alt bant, SU ANKI muma denk gelen nokta
(gostergenin kendi alarmi da close ile tam bu iki degeri karsilastirir).

k = len-1 icin Pine'daki uzun toplama formulu sadelesir:
    agirliklar  = len - i   (i = 0..len-1, yani en yeni mum en agir)
    bolen       = len*len - (len-1)*len/2 = len*(len+1)/2
Bu da dogrusal agirlikli ortalamanin (WMA) ta kendisidir. Yani:
    ust bant = WMA(src, len) + WMA(dev, len)
    alt bant = WMA(src, len) - WMA(dev, len)
    dev      = StdDev_carpani * stdev(src, len)     (Pine'in ta.stdev'i
               populasyon sapmasidir, bu yuzden ddof=0)
    src      = hlc3 = (yuksek + dusuk + kapanis) / 3

NOT: Gosterge son mumlarda sinirli olarak yeniden cizer (repaint). Mum
henuz kapanmadigi icin bantlar her saniye taze hesaplanir.
"""

import pandas as pd

import config


def wma(series: pd.Series, n: int) -> pd.Series:
    """Dogrusal agirlikli ortalama (Pine ta.wma): en yeni deger n, bir
    onceki n-1, ... en eski 1 agirlikla toplanir."""
    total_weight = n * (n + 1) / 2
    acc = None
    for j in range(n):
        part = (n - j) * series.shift(j)
        acc = part if acc is None else acc + part
    return acc / total_weight


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    df: 'high','low','close' kolonlari olan, eskiden yeniye siralanmis
    mum verisi. Geri donen dataframe'e su kolonlar eklenir:
        src, band_mid, band_dev, upper_band, lower_band
    """
    out = df.copy()
    n = config.BANDS_LENGTH

    src = (out["high"] + out["low"] + out["close"]) / 3.0       # hlc3
    dev = config.BANDS_STDDEV_MULT * src.rolling(n).std(ddof=0)  # mult * stdev

    mid = wma(src, n)
    dev_w = wma(dev, n)

    out["src"] = src
    out["band_mid"] = mid
    out["band_dev"] = dev_w
    out["upper_band"] = mid + dev_w
    out["lower_band"] = mid - dev_w
    return out
