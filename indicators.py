# -*- coding: utf-8 -*-
"""
indicators.py
-----------------------
Q-Trend (Pine v5, tarasenko_) gostergesinin Python karsiligi.
Botun kullandigi parcalar: ana cizgi (m), Gold, Silver, Gold loss,
Silver loss. BUY/SELL ve STRONG sinyalleri KULLANILMAZ.

Pine mantigi (bar_index > p icin):
    atr      = ta.atr(14)[1]            -> bir ONCEKI mumun ATR'si
    epsilon  = mult * atr
    m(onceki)= bir onceki mumun SON ana cizgi degeri
    src > m + epsilon  -> m = m + epsilon   (bir basamak yukari)
    src < m - epsilon  -> m = m - epsilon   (bir basamak asagi)
    aksi halde m yerinde kalir
    ls          = "B" (change_up) / "S" (change_down) / onceki ls
    renk        = ls == "B" ? YESIL : KIRMIZI   (ana cizginin rengi; ls bos ise kirmizi)
    Gold        = m + GOLD_MULT        * atr
    Silver      = m - SILVER_MULT      * atr
    Gold loss   = m + GOLD_LOSS_MULT   * atr
    Silver loss = m - SILVER_LOSS_MULT * atr
(Ilk p mumdaki baslangic mantigi da aynen uygulanir - bkz. _qtrend_walk.)

Bot iki parcali calisir:
  1) closed_state(): KAPANMIS mumlardan "bir onceki mumun ana cizgisi" ve
     "bir onceki mumun ATR'si" hesaplanir. Mum basina BIR kez yapilir.
  2) live_levels(): her saniye anlik fiyatla canli mumun cizgileri hesaplanir
     (Pine'in canli mumda yaptigiyla ayni).

NOT: Ana cizgi gecmise baglidir (basamak basamak ilerler). TradingView'daki
grafik cok daha eski mumlardan basladigi icin botun ana cizgisi grafikle
birebir ayni cikmayabilir; bu yuzden mumlar mumkun olan en fazla (1000)
cekilir. Canliya gecmeden birkac coinde grafikle karsilastirmak gerekir.
"""

import math

import numpy as np
import pandas as pd

import config


def _wilder_atr(high, low, close, n: int) -> np.ndarray:
    """Pine ta.atr: gercek araligin (TR) RMA'si. Ilk deger ilk n TR'nin
    basit ortalamasi, sonrasi (onceki*(n-1)+TR)/n. Ilk mumda TR = high-low."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    size = len(c)
    atr = np.full(size, np.nan)
    if size == 0:
        return atr
    tr = np.empty(size)
    tr[0] = h[0] - l[0]
    if size > 1:
        pc = c[:-1]
        tr[1:] = np.maximum(h[1:] - l[1:],
                            np.maximum(np.abs(h[1:] - pc), np.abs(l[1:] - pc)))
    if size >= n:
        atr[n - 1] = tr[:n].mean()
        for i in range(n, size):
            atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def _qtrend_walk(src: np.ndarray, atr_prev: np.ndarray, hi: np.ndarray, lo: np.ndarray):
    """Her mum icin ana cizginin (m) SON degerini ve son sinyal yonunu (ls)
    hesaplar. (m_dizisi, ls_dizisi) dondurur; ls: "B" / "S" / "".
    Pine kodunun
    satir satir karsiligi:

        m  = (h + l) / 2
        m := bar_index > p ? m[1] : m
        change_up   = src > m + epsilon
        change_down = src < m - epsilon
        m := (change_up or change_down) and m != m[1] ? m
             : change_up ? m + epsilon : change_down ? m - epsilon : nz(m[1], m)
        ls := change_up ? "B" : change_down ? "S" : ls[1]

    atr_prev[i] = (i-1). mumun ATR'si (Pine'daki ta.atr()[1]).
    hi/lo       = son p mumun src en yuksegi / en dusugu."""
    p = config.QT_TREND_PERIOD
    mult = config.QT_ATR_MULT
    size = len(src)
    m_final = np.full(size, np.nan)
    ls_final = [""] * size
    prev = math.nan
    ls_prev = ""
    for i in range(size):
        h = float(hi[i])
        l = float(lo[i])
        mid = (h + l) / 2.0 if not (math.isnan(h) or math.isnan(l)) else math.nan
        m0 = prev if i > p else mid
        eps = mult * float(atr_prev[i])
        s = float(src[i])
        up = s > m0 + eps       # NaN ile karsilastirma False doner (Pine'daki na gibi)
        dn = s < m0 - eps
        prev_ok = not math.isnan(prev)
        if (up or dn) and prev_ok and m0 != prev:
            cur = m0
        elif up:
            cur = m0 + eps
        elif dn:
            cur = m0 - eps
        else:
            cur = prev if prev_ok else m0
        m_final[i] = cur
        prev = cur
        if up:
            ls_prev = "B"
        elif dn:
            ls_prev = "S"
        ls_final[i] = ls_prev
    return m_final, ls_final


def _series_arrays(df: pd.DataFrame):
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    atr = _wilder_atr(high, low, close, config.QT_ATR_PERIOD)
    atr_prev = np.concatenate(([np.nan], atr[:-1]))
    s = pd.Series(close)
    p = config.QT_TREND_PERIOD
    hi = s.rolling(p).max().to_numpy()
    lo = s.rolling(p).min().to_numpy()
    m, ls = _qtrend_walk(close, atr_prev, hi, lo)
    return atr, atr_prev, m, ls


def closed_state(df_closed: pd.DataFrame):
    """KAPANMIS mumlardan canli mumun hesabi icin gereken iki degeri verir:
        m_prev   : son kapanmis mumun ana cizgisi
        atr_prev : son kapanmis mumun ATR'si
        ls_prev  : son kapanmis mumdaki son sinyal yonu ("B" / "S" / "");
                   ana cizginin rengi buradan gelir ("B" = yesil)
    Yeterli veri yoksa None."""
    if df_closed is None or len(df_closed) < config.QT_TREND_PERIOD + config.QT_ATR_PERIOD + 2:
        return None
    atr, _atr_prev, m, ls = _series_arrays(df_closed)
    m_last = float(m[-1])
    atr_last = float(atr[-1])
    if math.isnan(m_last) or math.isnan(atr_last) or atr_last <= 0:
        return None
    return {"m_prev": m_last, "atr_prev": atr_last, "ls_prev": ls[-1]}


def live_levels(m_prev: float, atr_prev: float, price: float, ls_prev: str = "") -> dict:
    """Canli mumun cizgileri (anlik fiyatla). QT_INTRABAR_STEP=True ise ana
    cizgi, fiyata gore Pine'daki gibi bir basamak oynar.

    Ana cizginin rengi (Pine'daki ls): fiyat m_prev + eps'in ustundeyse "B"
    (yesil), m_prev - eps'in altindaysa "S" (kirmizi), araliktaysa onceki
    mumdan gelen ls_prev korunur. ls bos ise Pine'da cizgi kirmizidir."""
    eps = config.QT_ATR_MULT * atr_prev
    m = m_prev
    ls = ls_prev
    if price > m_prev + eps:
        ls = "B"
    elif price < m_prev - eps:
        ls = "S"
    if config.QT_INTRABAR_STEP:
        if price > m_prev + eps:
            m = m_prev + eps
        elif price < m_prev - eps:
            m = m_prev - eps
    return {
        "m": m,
        "ls": ls,
        "trend_up": ls == "B",      # True = ana cizgi YESIL (long), False = KIRMIZI (short)
        "atr": atr_prev,
        "gold": m + config.GOLD_MULT * atr_prev,
        "silver": m - config.SILVER_MULT * atr_prev,
        "gold_loss": m + config.GOLD_LOSS_MULT * atr_prev,
        "silver_loss": m - config.SILVER_LOSS_MULT * atr_prev,
    }


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Tum mumlar icin cizgileri hesaplar (raporlar / kontrol icin; botun
    saniyelik dongusu bunu KULLANMAZ). Son satir = canli mum.
    Eklenen kolonlar: m, ls, atr, gold_line, silver_line, gold_loss_line,
    silver_loss_line. Eski raporlarla uyum icin upper_band = gold_line,
    lower_band = silver_line olarak da verilir."""
    out = df.copy()
    _atr, atr_prev, m, ls = _series_arrays(out)
    out["m"] = m
    out["ls"] = ls
    out["atr"] = atr_prev
    out["gold_line"] = m + config.GOLD_MULT * atr_prev
    out["silver_line"] = m - config.SILVER_MULT * atr_prev
    out["gold_loss_line"] = m + config.GOLD_LOSS_MULT * atr_prev
    out["silver_loss_line"] = m - config.SILVER_LOSS_MULT * atr_prev
    out["upper_band"] = out["gold_line"]
    out["lower_band"] = out["silver_line"]
    return out
