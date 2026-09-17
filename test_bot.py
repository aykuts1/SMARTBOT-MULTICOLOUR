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
import reports


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
    "t3_period": 2,
    "t3_factor": 0.7,
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
# Tilson T3
# ---------------------------------------------------------------------------
def test_t3_constant_series_equals_constant():
    s = pd.Series([42.0] * 50)
    result = ind.tilson_t3(s, length=2, factor=0.7)
    valid = result.dropna()
    assert np.allclose(valid.values, 42.0, atol=1e-6)


def test_t3_tracks_uptrend():
    df = make_trending_df(n=100, step=1.0)
    result = ind.tilson_t3(df["close"], length=2, factor=0.7).dropna()
    assert result.iloc[-1] > result.iloc[0]


def test_t3_tracks_downtrend():
    df = make_trending_df(n=100, step=-1.0)
    result = ind.tilson_t3(df["close"], length=2, factor=0.7).dropna()
    assert result.iloc[-1] < result.iloc[0]


def test_t3_smooths_noise_less_lag_than_long_ema():
    # T3 (period=2), uzun donem EMA50'ye gore fiyat degisimine daha hizli tepki vermeli
    df = make_trending_df(n=150, step=1.0, noise=0.1, seed=4)
    t3 = ind.tilson_t3(df["close"], length=2, factor=0.7)
    ema50 = ind.ema(df["close"], 50)
    # trend baslangicindan itibaren T3, fiyata EMA50'den daha yakin seyretmeli
    close_diff_t3 = (df["close"] - t3).abs().dropna().mean()
    close_diff_ema50 = (df["close"] - ema50).abs().dropna().mean()
    assert close_diff_t3 < close_diff_ema50


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
        "t3", "t3_color",
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
    row = pd.Series({"t3_color": "red", "trend": "short", "slope": "short"})
    assert sig.check_entry_signal(row) == "short"


def test_long_entry_signal_fires_on_green_long_trend_long_slope():
    row = pd.Series({"t3_color": "green", "trend": "long", "slope": "long"})
    assert sig.check_entry_signal(row) == "long"


def test_no_entry_signal_on_mismatched_conditions():
    row = pd.Series({"t3_color": "red", "trend": "long", "slope": "short"})
    assert sig.check_entry_signal(row) is None
    row2 = pd.Series({"t3_color": "green", "trend": "short", "slope": "long"})
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
        position_side="short", t3_color="green",
        entry_price=entry, current_price=current, threshold_pct=0.10
    )
    assert result is True


def test_color_flip_profit_exit_short_stays_open_below_threshold():
    entry = 100.0
    current = 99.95  # %0.05 kar -- esik altinda
    result = sig.check_color_flip_exit(
        position_side="short", t3_color="green",
        entry_price=entry, current_price=current, threshold_pct=0.10
    )
    assert result is False


def test_color_flip_no_check_when_color_matches_position_direction():
    # short pozisyonda T3 hala kirmizi ise bu kural hic devreye girmez
    result = sig.check_color_flip_exit(
        position_side="short", t3_color="red",
        entry_price=100.0, current_price=90.0, threshold_pct=0.10
    )
    assert result is False


def test_color_flip_profit_exit_long_mirrors_short():
    entry = 100.0
    current = 100.15  # long icin %0.15 kar
    result = sig.check_color_flip_exit(
        position_side="long", t3_color="red",
        entry_price=entry, current_price=current, threshold_pct=0.10
    )
    assert result is True


def test_loss_exit_short_triggers_at_5_75_percent_adverse_move():
    entry = 100.0
    loss_price = 106.0  # short icin fiyat yukari gitmesi zarar (%6 hareket)
    assert sig.check_loss_exit(position_side="short", entry_price=entry,
                                current_price=loss_price, loss_pct=5.75) is True
    assert sig.check_loss_exit(position_side="short", entry_price=entry,
                                current_price=105.5, loss_pct=5.75) is False


def test_loss_exit_long_triggers_at_5_75_percent_adverse_move():
    entry = 100.0
    loss_price = 94.0
    assert sig.check_loss_exit(position_side="long", entry_price=entry,
                                current_price=loss_price, loss_pct=5.75) is True
    assert sig.check_loss_exit(position_side="long", entry_price=entry,
                                current_price=94.5, loss_pct=5.75) is False


def test_candle_close_loss_exit_short_triggers_at_4_percent():
    entry = 100.0
    assert sig.check_candle_close_loss_exit(position_side="short", entry_price=entry,
                                              candle_close_price=104.5, loss_pct=4.0) is True
    assert sig.check_candle_close_loss_exit(position_side="short", entry_price=entry,
                                              candle_close_price=103.0, loss_pct=4.0) is False


def test_candle_close_loss_exit_long_triggers_at_4_percent():
    entry = 100.0
    assert sig.check_candle_close_loss_exit(position_side="long", entry_price=entry,
                                              candle_close_price=95.5, loss_pct=4.0) is True
    assert sig.check_candle_close_loss_exit(position_side="long", entry_price=entry,
                                              candle_close_price=97.0, loss_pct=4.0) is False


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


def test_leverage_from_position_falls_back_to_one_when_margin_unknown():
    # yetim pozisyon eski bir kayittan geliyorsa (margin_usdt None) hesap COKMEMELI
    position = {"qty": 10.0, "entry_price": 5.0, "margin_usdt": None}
    assert pm._leverage_from_position(position) == 1.0


# ---------------------------------------------------------------------------
# reports.py - /coinrapor ve /rapor<coin> mantigi
# ---------------------------------------------------------------------------
def test_match_symbol_accepts_short_and_full_names():
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert reports.match_symbol("btc", symbols) == "BTCUSDT"
    assert reports.match_symbol("BTC", symbols) == "BTCUSDT"
    assert reports.match_symbol("btcusdt", symbols) == "BTCUSDT"
    assert reports.match_symbol("doge", symbols) is None
    assert reports.match_symbol("", symbols) is None


def test_coin_stats_computes_win_rate_and_averages():
    trades = [
        {"pnl_pct": 2.0, "pnl_usdt": 10.0},
        {"pnl_pct": -1.0, "pnl_usdt": -5.0},
        {"pnl_pct": 3.0, "pnl_usdt": 15.0},
    ]
    stats = reports._coin_stats(trades)
    assert stats["count"] == 3
    assert stats["wins"] == 2
    assert stats["losses"] == 1
    assert stats["win_rate"] == pytest.approx(200 / 3)
    assert stats["avg_pnl_pct"] == pytest.approx((2.0 - 1.0 + 3.0) / 3)
    assert stats["total_pnl_usdt"] == pytest.approx(20.0)


def test_coin_stats_empty_trades_is_all_zero():
    stats = reports._coin_stats([])
    assert stats["count"] == 0
    assert stats["win_rate"] == 0.0
    assert stats["avg_pnl_pct"] == 0.0
    assert stats["total_pnl_usdt"] == 0.0


class _FakeState:
    """reports.py fonksiyonlarini State/exchange olmadan test etmek icin minimal sahte durum."""

    def __init__(self, trades=None, positions=None):
        self._trades = trades or []
        self._positions = positions or {}

    def all_trades(self):
        return list(self._trades)

    def get_trades_since(self, ts):
        return [t for t in self._trades if t.get("closed_at", 0) >= ts]

    def all_positions(self):
        return dict(self._positions)

    def get_position(self, symbol):
        return self._positions.get(symbol)


def test_build_coin_summary_report_lists_all_configured_symbols():
    cfg = {"symbols": ["BTCUSDT", "ETHUSDT"]}
    trades = [
        {"symbol": "BTCUSDT", "pnl_pct": 1.0, "pnl_usdt": 5.0},
        {"symbol": "BTCUSDT", "pnl_pct": -0.5, "pnl_usdt": -2.5},
    ]
    state = _FakeState(trades=trades)
    report = reports.build_coin_summary_report(state, cfg)
    assert "BTCUSDT" in report
    assert "ETHUSDT" in report
    assert "henuz islem yok" in report  # ETHUSDT icin


def test_handle_command_routes_coin_detail_report():
    cfg = {"symbols": ["BTCUSDT", "ETHUSDT"], "max_positions": 10}
    trades = [
        {"symbol": "BTCUSDT", "side": "long", "entry_price": 100.0, "exit_price": 102.0,
         "pnl_pct": 2.0, "pnl_usdt": 8.0, "reason": "take_profit",
         "opened_at": 1000.0, "closed_at": 4600.0},
    ]
    state = _FakeState(trades=trades)
    response = reports.handle_command("/raporbtc", state, cfg)
    assert response is not None
    assert "BTCUSDT" in response
    assert "Toplam islem: 1" in response


def test_handle_command_unknown_coin_lists_available_symbols():
    cfg = {"symbols": ["BTCUSDT", "ETHUSDT"], "max_positions": 10}
    state = _FakeState()
    response = reports.handle_command("/rapordoge", state, cfg)
    assert "bulunamadi" in response
    assert "BTC" in response and "ETH" in response


def test_handle_command_coinrapor_routes_to_summary():
    cfg = {"symbols": ["BTCUSDT"], "max_positions": 10}
    state = _FakeState()
    response = reports.handle_command("/coinrapor", state, cfg)
    assert "Coin Bazli Detayli Rapor" in response


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
