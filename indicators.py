"""
indicators.py
-------------
Strateji icin gereken tum indikator hesaplamalari: EMA21/EMA50, ALMA9 + 6 bant
(1.5 / 2 / 3 x ATR14), ATR14, ve Heikin Ashi mum serisi.

Tum bu hesaplamalar NORMAL (gercek) mum kapanislarindan yapilir.
Heikin Ashi sadece giris/cikis tetikleyici mumun renk kontrolu icin ayri
bir seri olarak hesaplanir; EMA/ALMA/ATR'yi etkilemez.

Girdi: pandas DataFrame, kolonlar = ['open', 'high', 'low', 'close'] (zaman
sirasina gore artan, en son satir = en son kapanan mum).
"""

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# EMA (Exponential Moving Average)
# ---------------------------------------------------------------------------
def ema(series: pd.Series, length: int) -> pd.Series:
    """adjust=False -> Wilder tarzi, TradingView'deki ta.ema ile tutarli sonuc verir."""
    return series.ewm(span=length, adjust=False).mean()


# ---------------------------------------------------------------------------
# ATR (Average True Range) - Wilder smoothing (TradingView ta.atr ile ayni)
# ---------------------------------------------------------------------------
def atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Wilder's RMA = ewm with alpha = 1/length, adjust=False
    return tr.ewm(alpha=1.0 / length, adjust=False).mean()


# ---------------------------------------------------------------------------
# ALMA (Arnaud Legoux Moving Average) - orijinal/standart parametreler
# ---------------------------------------------------------------------------
def alma(series: pd.Series, length: int = 9, offset: float = 0.85, sigma: float = 6.0) -> pd.Series:
    """
    Standart ALMA agirliklari onceden hesaplanip rolling pencereye uygulanir.
    offset=0.85, sigma=6 -> TradingView'in orijinal/varsayilan ALMA ayarlari.
    """
    m = offset * (length - 1)
    s = length / sigma
    idx = np.arange(length)
    weights = np.exp(-((idx - m) ** 2) / (2 * s * s))
    weights /= weights.sum()

    def _weighted(window: np.ndarray) -> float:
        return float(np.dot(window, weights))

    return series.rolling(window=length).apply(_weighted, raw=True)


# ---------------------------------------------------------------------------
# Heikin Ashi - sadece renk kontrolu icin ayri seri
# ---------------------------------------------------------------------------
def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0

    ha_open = pd.Series(index=df.index, dtype="float64")
    ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0

    ha_high = pd.concat([df["high"], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df["low"], ha_open, ha_close], axis=1).min(axis=1)

    # renk: close > open -> yesil (True), close < open -> kirmizi (False), esit -> None (notr)
    color = pd.Series(np.where(ha_close > ha_open, "green",
                       np.where(ha_close < ha_open, "red", "neutral")),
                       index=df.index)

    return pd.DataFrame({
        "ha_open": ha_open,
        "ha_high": ha_high,
        "ha_low": ha_low,
        "ha_close": ha_close,
        "ha_color": color,
    })


# ---------------------------------------------------------------------------
# Hepsini bir arada hesapla
# ---------------------------------------------------------------------------
def compute_all(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    df: ['open','high','low','close'] kolonlu, zaman artan sirali OHLC verisi.
    cfg: config.json'dan gelen strateji parametreleri.
    Donen DataFrame orijinal kolonlara ek olarak tum indikatorleri icerir.
    """
    out = df.copy()

    out["ema_fast"] = ema(out["close"], cfg["ema_fast_length"])   # EMA21
    out["ema_slow"] = ema(out["close"], cfg["ema_slow_length"])   # EMA50

    # trend: fast > slow -> long, fast < slow -> short
    out["trend"] = np.where(out["ema_fast"] > out["ema_slow"], "long",
                     np.where(out["ema_fast"] < out["ema_slow"], "short", "neutral"))

    # egim: EMA21'in bir onceki muma gore yonu
    prev_fast = out["ema_fast"].shift(1)
    out["slope"] = np.where(out["ema_fast"] > prev_fast, "long",
                     np.where(out["ema_fast"] < prev_fast, "short", "neutral"))

    out["atr"] = atr(out, cfg["atr_length"])
    out["alma"] = alma(out["close"], cfg["alma_length"], cfg["alma_offset"], cfg["alma_sigma"])

    for mult in cfg["band_multipliers"]:
        tag = str(mult).replace(".", "_")
        out[f"alma_upper_{tag}"] = out["alma"] + out["atr"] * mult
        out[f"alma_lower_{tag}"] = out["alma"] - out["atr"] * mult

    ha = heikin_ashi(out[["open", "high", "low", "close"]])
    out = pd.concat([out, ha], axis=1)

    return out


def nearest_band(row: pd.Series, cfg: dict, side: str, entry_price: float) -> float:
    """
    side='short' -> giris fiyatinin ALTINDAKI en yakin ALT ALMA bandi (TP hedefi)
    side='long'  -> giris fiyatinin USTUNDEKI en yakin UST ALMA bandi (TP hedefi)
    Bu fonksiyon her mum kapanisinda yeniden cagrilir (hareketli hedef) --
    entry_price sadece "hangi bandin en yakin oldugunu" belirlemek icin sabit
    referans olarak kullanilir, bandin KENDI DEGERI o anki (guncel) mum satirindan
    (row) okunur.
    """
    multipliers = sorted(cfg["band_multipliers"])
    candidates = []
    for mult in multipliers:
        tag = str(mult).replace(".", "_")
        if side == "short":
            candidates.append(row[f"alma_lower_{tag}"])
        else:
            candidates.append(row[f"alma_upper_{tag}"])

    if side == "short":
        # entry'nin altinda kalan bantlar arasinda entry'ye EN YAKIN (en buyuk) olani
        below = [c for c in candidates if c < entry_price]
        return max(below) if below else min(candidates)
    else:
        above = [c for c in candidates if c > entry_price]
        return min(above) if above else max(candidates)
