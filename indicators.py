"""
indicators.py
-------------
Strateji icin gereken tum indikator hesaplamalari: EMA21/EMA50, ALMA9 + 6 bant
(1.5 / 2 / 3 x ATR14), ATR14, ve Tilson T3.

Tum bu hesaplamalar NORMAL (gercek) mum kapanislarindan yapilir.
Tilson T3, sadece giris/cikis tetikleyici "renk" kontrolu icin ayri bir
seri olarak hesaplanir (bir onceki muma gore yukari/asagi); EMA/ALMA/ATR'yi
etkilemez. (Onceki surumde bu is icin Heikin Ashi kullaniliyordu, artik
tamamen kaldirildi.)

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
# Tilson T3 - giris/cikis renk tetikleyicisi (Heikin Ashi'nin yerine)
# ---------------------------------------------------------------------------
def tilson_t3(series: pd.Series, length: int = 2, factor: float = 0.7) -> pd.Series:
    """
    Standart Tilson T3: 6 kat ust uste EMA'nin agirlikli birlesimi.
    factor (b) = 0.7, length = 2 -> kullanicinin verdigi Pine kodundaki
    varsayilan degerlerle birebir ayni.
    """
    b = factor
    c1 = -b ** 3
    c2 = 3 * b ** 2 + 3 * b ** 3
    c3 = -6 * b ** 2 - 3 * b - 3 * b ** 3
    c4 = 1 + 3 * b + b ** 3 + 3 * b ** 2

    e1 = ema(series, length)
    e2 = ema(e1, length)
    e3 = ema(e2, length)
    e4 = ema(e3, length)
    e5 = ema(e4, length)
    e6 = ema(e5, length)

    return c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3


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

    # Tilson T3 + renk (bir onceki muma gore yukari -> yesil/long, asagi -> kirmizi/short)
    out["t3"] = tilson_t3(out["close"], cfg["t3_period"], cfg["t3_factor"])
    prev_t3 = out["t3"].shift(1)
    out["t3_color"] = np.where(out["t3"] > prev_t3, "green",
                        np.where(out["t3"] < prev_t3, "red", "neutral"))

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
