"""
Sinyal filtreleri
1. Bollinger Bands - tetikleyici
2. RSI - teyit
3. ADX - yatay piyasa kontrolu
"""

import pandas as pd
from config import (
    RSI_LONG_THRESHOLD, RSI_SHORT_THRESHOLD, ADX_THRESHOLD
)


def check_bollinger_signal(df):
    """
    Bollinger Bands sinyali kontrol eder.

    LONG: Onceki mum alt bandin DISINDA, son mum alt bandin ICINDE kapandi
    SHORT: Onceki mum ust bandin DISINDA, son mum ust bandin ICINDE kapandi

    Doner: "LONG", "SHORT" veya None
    """
    if len(df) < 2:
        return None

    # Son iki kapanmis mum
    prev_candle = df.iloc[-2]
    last_candle = df.iloc[-1]

    # NaN kontrolu
    if (prev_candle[["close", "bb_lower", "bb_upper"]].isna().any() or
        last_candle[["close", "bb_lower", "bb_upper"]].isna().any()):
        return None

    # LONG sinyali
    if (prev_candle["close"] < prev_candle["bb_lower"] and
        last_candle["close"] >= last_candle["bb_lower"]):
        return "LONG"

    # SHORT sinyali
    if (prev_candle["close"] > prev_candle["bb_upper"] and
        last_candle["close"] <= last_candle["bb_upper"]):
        return "SHORT"

    return None


def check_rsi_filter(df, signal):
    """
    RSI filtresini kontrol eder.
    LONG icin RSI < 35
    SHORT icin RSI > 65
    """
    if len(df) < 1:
        return False

    last_rsi = df.iloc[-1]["rsi"]

    if pd.isna(last_rsi):
        return False

    if signal == "LONG":
        return last_rsi < RSI_LONG_THRESHOLD
    elif signal == "SHORT":
        return last_rsi > RSI_SHORT_THRESHOLD

    return False


def check_adx_filter(df):
    """
    ADX filtresini kontrol eder.
    ADX < 25 ise yatay piyasa - sinyal gecerli
    """
    if len(df) < 1:
        return False

    last_adx = df.iloc[-1]["adx"]

    if pd.isna(last_adx):
        return False

    return last_adx < ADX_THRESHOLD


def check_all_filters(df):
    """
    Tum filtreleri sirayla kontrol eder.
    Doner: ("LONG"/"SHORT", details_dict) veya (None, details_dict)
    """
    details = {
        "bb_signal": None,
        "rsi_value": None,
        "adx_value": None,
        "rsi_passed": False,
        "adx_passed": False
    }

    # Filtre 1 - Bollinger Bands
    bb_signal = check_bollinger_signal(df)
    details["bb_signal"] = bb_signal

    if bb_signal is None:
        return None, details

    # Son mum bilgileri (loglama icin)
    last_candle = df.iloc[-1]
    details["rsi_value"] = round(last_candle["rsi"], 2) if not pd.isna(last_candle["rsi"]) else None
    details["adx_value"] = round(last_candle["adx"], 2) if not pd.isna(last_candle["adx"]) else None

    # Filtre 2 - RSI
    rsi_passed = check_rsi_filter(df, bb_signal)
    details["rsi_passed"] = rsi_passed

    if not rsi_passed:
        return None, details

    # Filtre 3 - ADX
    adx_passed = check_adx_filter(df)
    details["adx_passed"] = adx_passed

    if not adx_passed:
        return None, details

    # Tum filtreler gecti
    return bb_signal, details
