"""
Teknik gosterge hesaplamalari
- Bollinger Bands
- RSI
- ADX
- ATR
"""

import pandas as pd
import numpy as np


def klines_to_dataframe(klines):
    """
    Bybit'ten gelen mum verisini DataFrame'e cevirir.
    Bybit format: [timestamp, open, high, low, close, volume, turnover]
    """
    df = pd.DataFrame(klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume", "turnover"
    ])
    # String'leri float'a cevir
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        df[col] = df[col].astype(float)
    df["timestamp"] = df["timestamp"].astype(int)
    return df


# ============ BOLLINGER BANDS ============
def calculate_bollinger_bands(df, period=20, std_mult=2):
    """
    Bollinger Bands hesaplar.
    Doner: df'e 'bb_upper', 'bb_middle', 'bb_lower' kolonlari ekler
    """
    df = df.copy()
    df["bb_middle"] = df["close"].rolling(window=period).mean()
    df["bb_std"] = df["close"].rolling(window=period).std()
    df["bb_upper"] = df["bb_middle"] + (df["bb_std"] * std_mult)
    df["bb_lower"] = df["bb_middle"] - (df["bb_std"] * std_mult)
    return df


# ============ RSI ============
def calculate_rsi(df, period=14):
    """
    RSI hesaplar.
    Doner: df'e 'rsi' kolonu ekler
    """
    df = df.copy()
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


# ============ ATR ============
def calculate_atr(df, period=14):
    """
    ATR hesaplar.
    Doner: df'e 'atr' kolonu ekler
    """
    df = df.copy()
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=period).mean()
    return df


# ============ ADX ============
def calculate_adx(df, period=14):
    """
    ADX hesaplar.
    Doner: df'e 'adx' kolonu ekler
    """
    df = df.copy()

    # True Range
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    # Directional Movement
    up_move = df["high"] - df["high"].shift()
    down_move = df["low"].shift() - df["low"]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    # Smooth with Wilder's method (RMA)
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/period, adjust=False).mean() / atr)

    # DX ve ADX
    dx = 100 * (abs(plus_di - minus_di) / (plus_di + minus_di))
    df["adx"] = dx.ewm(alpha=1/period, adjust=False).mean()
    return df


# ============ TUM GOSTERGELERI HESAPLA ============
def calculate_all_indicators(klines, bb_period=20, bb_std=2, rsi_period=14,
                              adx_period=14, atr_period=14):
    """
    Mum verisinden tum gostergeleri hesaplar.
    Doner: DataFrame
    """
    df = klines_to_dataframe(klines)
    df = calculate_bollinger_bands(df, bb_period, bb_std)
    df = calculate_rsi(df, rsi_period)
    df = calculate_atr(df, atr_period)
    df = calculate_adx(df, adx_period)
    return df
