"""
test_bot.py
-----------
Ag baglantisi gerektirmeyen dogrulama testleri: indikator hesaplarinin ve
sinyal/pozisyon mantiginin dogrulugunu kontrol eder. Gercek Bybit baglantisi
test EDILMEZ (o kisim canli ortamda dogrulanmali).

Calistirmak icin: pytest test_bot.py -v
"""

import numpy as np
import pandas as pd
import pytest

import indicators as ind
import signals as sig
import position_manager as pm


def make_trending_df(n=200, start=100.0, step=0.5, noise=0.0, seed=1):
    """Duzenli yukselen bir seri uretir (LONG trend + slope beklenir)."""
    rng = np.random.default_rng(seed)
    close = start + np.arange(n) * step + rng.normal(0, noise, n)
    open_ = np.roll(close, 1)
    open_[0] = close[0] - step
    high = np.maximum(open_, close) + abs(rng.normal(0.1, 0.05, n))
    low = np.minimum(open_, close) - abs(rng.normal(0.1, 0.05, n))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


DEFAULT_CFG = {
    "ema_fast_length": 21,
    "ema_slow_length": 50,
    "atr_length": 14,
    "alma_length": 9,
    "alma_offset": 0.85,
    "alma_sigma": 6.0,
    "band_multipliers": [1.5, 2, 3],
}


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------
def test_ema_matches_manual_recursive_calc():
    s = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19], dtype="float64")
    length = 3
    result = ind.ema(s, length)
    alpha = 2 / (length + 1)
    manual = [s.iloc[0]]
    for v in s.iloc[1:]:
        manual.append(alpha * v + (1 - alpha) * manual[-1])
    assert np.allclose(result.values, manual)


def test_ema_uptrend_is_above_downtrend_ema():
    df = make_trending_df(n=100, step=1.0)
    fast = ind.ema(df["close"], 21)
    slow = ind.ema(df["close"], 50)
    # net yukselen seride yakin donem EMA, uzun donem EMA'nin ustunde olmali
    assert fast.iloc[-1] > slow.iloc[-1]


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------
def test_atr_zero_range_is_zero():
    df = pd.DataFrame({
        "open": [10] * 20, "high": [10] * 20, "low": [10] * 20, "close": [10] * 20
    })
    result = ind.atr(df, 14)
    assert np.allclose(result.values, 0.0)


def test_atr_positive_for_moving_price():
    df = make_trending_df(n=50, step=1.0, noise=0.2)
    result = ind.atr(df, 14)
    assert (result.dropna() > 0).all()


# ---------------------------------------------------------------------------
# ALMA
# ---------------------------------------------------------------------------
def test_alma_constant_series_equals_constant():
    s = pd.Series([42.0] * 30)
    result = ind.alma(s, length=9, offset=0.85, sigma=6.0)
    valid = result.dropna()
    assert np.allclose(valid.values, 42.0)


def test_alma_weights_sum_to_one_reconstruction():
    # dogrudan agirlik toplaminin 1 oldugunu dolayli olarak dogrula:
    # sabit bir seri her zaman ayni sabiti vermeli (yukaridaki testle kismen
    # ortusuyor ama burada uc deger farkli length/offset/sigma ile de kontrol edelim)
    s = pd.Series([7.0] * 25)
    for length, offset, sigma in [(9, 0.85, 6.0), (14, 0.5, 3.0), (21, 0.9, 8.0)]:
        result = ind.alma(s, length, offset, sigma).dropna()
        assert np.allclose(result.values, 7.0)


def test_alma_tracks_trend_direction():
    df = make_trending_df(n=100, step=1.0)
    result = ind.alma(df["close"], 9, 0.85, 6.0).dropna()
    assert result.iloc[-1] > result.iloc[0]


# ---------------------------------------------------------------------------
# Heikin Ashi
# ---------------------------------------------------------------------------
def test_heikin_ashi_uptrend_is_mostly_green():
    df = make_trending_df(n=100, step=1.0, noise=0.05)
    ha = ind.heikin_ashi(df)
    green_ratio = (ha["ha_color"] == "green").mean()
    assert green_ratio > 0.8


def test_heikin_ashi_downtrend_is_mostly_red():
    df = make_trending_df(n=100, step=-1.0, noise=0.05)
    ha = ind.heikin_ashi(df)
    red_ratio = (ha["ha_color"] == "red").mean()
    assert red_ratio > 0.8


def test_heikin_ashi_smooths_noise_vs_raw_close():
    # HA govdesi, ham kapanistan daha az "titremeli" olmali (gurultu icin daha az yon degisimi)
    df = make_trending_df(n=200, step=0.0, noise=1.0, seed=3)
    ha = ind.heikin_ashi(df)
    raw_flips = (np.sign(df["close"].diff()).diff() != 0).sum()
    ha_flips = (ha["ha_color"] != ha["ha_color"].shift(1)).sum()
    assert ha_flips <= raw_flips


# ---------------------------------------------------------------------------
# compute_all butunluk kontrolu
# ---------------------------------------------------------------------------
def test_compute_all_produces_expected_columns():
    df = make_trending_df(n=100, step=1.0)
    out = ind.compute_all(df, DEFAULT_CFG)
    expected = {
        "ema_fast", "ema_slow", "trend", "slope", "atr", "alma",
        "alma_upper_1_5", "alma_upper_2", "alma_upper_3",
        "alma_lower_1_5", "alma_lower_2", "alma_lower_3",
        "ha_open", "ha_high", "ha_low", "ha_close", "ha_color",
    }
    assert expected.issubset(set(out.columns))


def test_uptrend_gives_long_trend_and_slope():
    df = make_trending_df(n=100, step=1.0)
    out = ind.compute_all(df, DEFAULT_CFG)
    last = out.iloc[-1]
    assert last["trend"] == "long"
    assert last["slope"] == "long"


def test_downtrend_gives_short_trend_and_slope():
    df = make_trending_df(n=100, step=-1.0)
    out = ind.compute_all(df, DEFAULT_CFG)
    last = out.iloc[-1]
    assert last["trend"] == "short"
    assert last["slope"] == "short"


def test_bands_are_ordered_around_alma():
    df = make_trending_df(n=100, step=0.3, noise=0.3, seed=5)
    out = ind.compute_all(df, DEFAULT_CFG)
    last = out.iloc[-1]
    # ust bantlar buyukten kucuge: 3 > 2 > 1.5 > alma > 1.5(alt) > 2(alt) > 3(alt)
    assert last["alma_upper_3"] > last["alma_upper_2"] > last["alma_upper_1_5"] > last["alma"]
    assert last["alma"] > last["alma_lower_1_5"] > last["alma_lower_2"] > last["alma_lower_3"]


def test_nearest_band_short_picks_closest_below_entry():
    df = make_trending_df(n=100, step=0.3, noise=0.2, seed=7)
    out = ind.compute_all(df, DEFAULT_CFG)
    last = out.iloc[-1]
    entry = last["alma"] + 5.0  # entry, alma'nin ustunde bir yerde varsayimsal
    band = ind.nearest_band(last, DEFAULT_CFG, "short", entry)
    assert band == last["alma_lower_1_5"]


def test_nearest_band_long_picks_closest_above_entry():
    df = make_trending_df(n=100, step=0.3, noise=0.2, seed=7)
    out = ind.compute_all(df, DEFAULT_CFG)
    last = out.iloc[-1]
    entry = last["alma"] - 5.0
    band = ind.nearest_band(last, DEFAULT_CFG, "long", entry)
    assert band == last["alma_upper_1_5"]


# ---------------------------------------------------------------------------
# signals.py
# ---------------------------------------------------------------------------
def test_short_entry_signal_fires_on_red_short_trend_short_slope():
    row = pd.Series({"ha_color": "red", "trend": "short", "slope": "short"})
    assert sig.check_entry_signal(row) == "short"


def test_long_entry_signal_fires_on_green_long_trend_long_slope():
    row = pd.Series({"ha_color": "green", "trend": "long", "slope": "long"})
    assert sig.check_entry_signal(row) == "long"


def test_no_entry_signal_on_mismatched_conditions():
    row = pd.Series({"ha_color": "red", "trend": "long", "slope": "short"})
    assert sig.check_entry_signal(row) is None
    row2 = pd.Series({"ha_color": "green", "trend": "short", "slope": "long"})
    assert sig.check_entry_signal(row2) is None


def test_trend_flip_exit_short_position_when_trend_turns_long():
    assert sig.check_trend_flip_exit(position_side="short", current_trend="long") is True
    assert sig.check_trend_flip_exit(position_side="short", current_trend="short") is False


def test_trend_flip_exit_long_position_when_trend_turns_short():
    assert sig.check_trend_flip_exit(position_side="long", current_trend="short") is True
    assert sig.check_trend_flip_exit(position_side="long", current_trend="long") is False


def test_color_flip_profit_exit_short_closes_when_green_and_profit_ge_threshold():
    # short pozisyon: kar = (entry - current) / entry
    entry = 100.0
    current = 99.85  # %0.15 kar
    result = sig.check_color_flip_exit(
        position_side="short", candle_color="green",
        entry_price=entry, current_price=current, threshold_pct=0.10
    )
    assert result is True


def test_color_flip_profit_exit_short_stays_open_below_threshold():
    entry = 100.0
    current = 99.95  # %0.05 kar -- esik altinda
    result = sig.check_color_flip_exit(
        position_side="short", candle_color="green",
        entry_price=entry, current_price=current, threshold_pct=0.10
    )
    assert result is False


def test_color_flip_no_check_when_color_matches_position_direction():
    # short pozisyonda mum hala kirmizi kapaniyorsa bu kural hic devreye girmez
    result = sig.check_color_flip_exit(
        position_side="short", candle_color="red",
        entry_price=100.0, current_price=90.0, threshold_pct=0.10
    )
    assert result is False


def test_color_flip_profit_exit_long_mirrors_short():
    entry = 100.0
    current = 100.15  # long icin %0.15 kar
    result = sig.check_color_flip_exit(
        position_side="long", candle_color="red",
        entry_price=entry, current_price=current, threshold_pct=0.10
    )
    assert result is True


def test_loss_exit_short_triggers_at_5_percent_adverse_move():
    entry = 100.0
    loss_price = 105.0  # short icin fiyat yukari gitmesi zarar
    assert sig.check_loss_exit(position_side="short", entry_price=entry,
                                current_price=loss_price, loss_pct=5.0) is True
    assert sig.check_loss_exit(position_side="short", entry_price=entry,
                                current_price=104.0, loss_pct=5.0) is False


def test_loss_exit_long_triggers_at_5_percent_adverse_move():
    entry = 100.0
    loss_price = 95.0
    assert sig.check_loss_exit(position_side="long", entry_price=entry,
                                current_price=loss_price, loss_pct=5.0) is True
    assert sig.check_loss_exit(position_side="long", entry_price=entry,
                                current_price=96.0, loss_pct=5.0) is False


def test_tp_exit_short_triggers_when_band_touched_and_profitable_enough():
    # entry=100, band=95 -> banda carpinca %5 kar, esik %0.10 -- rahat gecer
    assert sig.check_tp_exit(position_side="short", current_price=94.0, band_price=95.0,
                              entry_price=100.0, min_profit_pct=0.10) is True
    # banda henuz carpilmadi
    assert sig.check_tp_exit(position_side="short", current_price=96.0, band_price=95.0,
                              entry_price=100.0, min_profit_pct=0.10) is False


def test_tp_exit_long_triggers_when_band_touched_and_profitable_enough():
    assert sig.check_tp_exit(position_side="long", current_price=106.0, band_price=105.0,
                              entry_price=100.0, min_profit_pct=0.10) is True
    assert sig.check_tp_exit(position_side="long", current_price=104.0, band_price=105.0,
                              entry_price=100.0, min_profit_pct=0.10) is False


def test_tp_exit_blocked_when_band_touched_but_profit_below_threshold_short():
    # entry=100, band=99.95 -> banda carpsa bile kar sadece %0.05, esik %0.10 -- cikis YOK
    assert sig.check_tp_exit(position_side="short", current_price=99.9, band_price=99.95,
                              entry_price=100.0, min_profit_pct=0.10) is False


def test_tp_exit_blocked_when_band_touched_but_profit_below_threshold_long():
    assert sig.check_tp_exit(position_side="long", current_price=100.1, band_price=100.05,
                              entry_price=100.0, min_profit_pct=0.10) is False


def test_tp_exit_blocked_when_band_level_itself_is_a_loss():
    # entry=100, bant 99.5'e (entry'nin ALTINA) dusmus -- carpilsa bile zarar demek, cikis YOK
    assert sig.check_tp_exit(position_side="long", current_price=99.4, band_price=99.5,
                              entry_price=100.0, min_profit_pct=0.10) is False


# ---------------------------------------------------------------------------
# position_manager.py - slot / boyutlandirma mantigi
# ---------------------------------------------------------------------------
def test_position_size_is_five_percent_of_balance():
    size = pm.calc_position_size(balance=10000.0, pct=5.0, price=2.0, qty_step=0.1)
    # 10000 * 0.05 = 500 USDT nominal marj -> 20x ile pozisyon degeri ayri hesaplanir
    # burada sadece marj bazinda dogru yuzdeyi urettigini kontrol ediyoruz
    assert size["margin_usdt"] == 500.0


def test_slot_manager_enforces_max_total_and_per_coin():
    slots = pm.SlotManager(max_total=2)
    assert slots.can_open("BTCUSDT") is True
    slots.register_open("BTCUSDT")
    assert slots.can_open("BTCUSDT") is False  # ayni coinde ikinci pozisyon yok
    assert slots.can_open("ETHUSDT") is True
    slots.register_open("ETHUSDT")
    assert slots.can_open("SOLUSDT") is False  # toplam slot doldu
    slots.register_close("BTCUSDT")
    assert slots.can_open("SOLUSDT") is True


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
