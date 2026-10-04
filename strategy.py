# -*- coding: utf-8 -*-
"""
strategy.py
---------------------
Botun beyni: Faytterro Bands sinyali, lose exit kontrolu, pozisyon
acma/kapama, borsayla iki yonlu senkronizasyon.

STRATEJI (stop-and-reverse):
  - Fiyat ALT banda degerse: acik SHORT varsa kapatilir, LONG acilir
    (short yoksa dogrudan long acilir).
  - Fiyat UST banda degerse: acik LONG varsa kapatilir, SHORT acilir
    (long yoksa dogrudan short acilir).
  - Lose exit: giris aninda karsi banda olan mesafe (D) olculur; lose exit
    girisin D kadar ters yonune, guvenlik SL ise 2xD kadar ters yonune
    acilista SABITLENIR (bkz. sizing.py).
  - Cikis yollari: karsi banda degme (Bant Donusu), Lose Exit, Stop Loss.

Bir coin'de ayni anda en fazla 1 long + 1 short acik olabilir. Toplam
sistem slotu LONG ve SHORT icin AYRI AYRI sinirli (MAX_POSITIONS_PER_SIDE).

NOT: Bu dosya Bybit'ten veri cekme/onbellekleme islerine karismaz - o is
tamamen bybit_client.py'de (get_klines_cached).
"""

import time

import config
import indicators
import sizing
import state as state_module
import telegram_notifier as notify


def get_available_margin(client, bot_state):
    """Toplam varlik - su an acik pozisyonlar icin ayrilmis miktarlar."""
    equity = client.get_total_equity()
    used = sum(p.allocated_amount for p in bot_state.all_positions())
    return equity - used, equity


def compute_indicators_for_symbol(client, symbol):
    """Mum verisini (onbellekli - bkz. bybit_client.get_klines_cached)
    ceker ve bantlari hesaplar."""
    df = client.get_klines_cached(symbol)
    df = indicators.compute_all(df)
    return df


# ------------------------------------------------------------
# YENIDEN BASLATMA / SENKRONIZASYON ORTAK YARDIMCILARI
# ------------------------------------------------------------
def _exchange_positions_by_key(client) -> dict:
    """Borsadaki acik pozisyonlari, takip edilen coin listesiyle
    sinirlandirip (sembol, yon) -> pozisyon sozlugune cevirir."""
    exchange_positions = client.get_open_positions()
    by_key = {}
    for p in exchange_positions:
        symbol = p["symbol"]
        if symbol not in config.COINS:
            continue
        pos_idx = int(p.get("positionIdx", 0))
        side = "long" if pos_idx == 1 else "short"
        key = (symbol, side)
        if key in by_key:
            print(f"[reconcile] {symbol} {side}: borsada birden fazla kayit bulundu, "
                  "sadece ilki dikkate alindi - digerini manuel kontrol et.")
            continue
        by_key[key] = p
    return by_key


def _build_position_from_exchange(p: dict):
    """Tek bir borsa pozisyon kaydindan (get_open_positions sonucu) bir
    Position nesnesi olusturur. Guvenlik SL borsadan dogrudan okunur;
    lose exit bu SL'den GERI HESAPLANIR."""
    symbol = p["symbol"]
    pos_idx = int(p.get("positionIdx", 0))
    side = "long" if pos_idx == 1 else "short"
    entry_price = float(p["avgPrice"])
    qty = float(p["size"])
    leverage = float(p.get("leverage", 0) or 0)
    sl_price = float(p.get("stopLoss") or 0)

    lose_exit_price = state_module.reconstruct_lose_exit(entry_price, sl_price, side)
    allocated_amount = (entry_price * qty) / leverage if leverage else 0.0

    return state_module.Position(
        symbol=symbol, side=side, position_idx=pos_idx,
        entry_price=entry_price, sl_price=sl_price, lose_exit_price=lose_exit_price,
        leverage=leverage, allocated_amount=allocated_amount, qty=qty,
    )


def reconcile_open_positions(client, bot_state):
    """Bot baslarken (main.py) bir kez cagrilir - borsadaki tum acik
    pozisyonlari bastan takibe alir."""
    for (symbol, side), p in _exchange_positions_by_key(client).items():
        pos = _build_position_from_exchange(p)
        if pos.sl_price <= 0:
            print(f"[reconcile] {symbol} {side}: SL bulunamadi, sadece giris takip edilecek")
        bot_state.add_position(pos)
        notify.notify_position_found_on_restart(
            symbol, side, pos.entry_price, pos.sl_price, pos.lose_exit_price, pos.leverage)


# ------------------------------------------------------------
# IKI YONLU RECONCILE (bot calisirken periyodik olarak cagrilir)
# ------------------------------------------------------------
def reconcile_with_exchange(client, bot_state):
    """main.py icinde RECONCILE_INTERVAL_SECONDS'ta (varsayilan 60sn)
    bir cagrilir. Botun kendi acik pozisyon kayitlarini borsayla IKI
    YONLU karsilastirir:

      1) Bot'ta acik gorunen ama borsada olmayan bir pozisyon varsa,
         dis bir etkenle (gercek SL tetiklenmesi, elle kapatma vb.)
         kapandigi varsayilir - kayittan silinir ve "Stop Loss" olarak
         islenir.

      2) Borsada acik olan ama bot'un bilmedigi bir pozisyon varsa,
         gereken tum hesaplamalar yapilarak kayda alinir.
    """
    exchange_by_key = _exchange_positions_by_key(client)

    # 1) Bot'ta var, borsada yok -> disaridan kapanmis, kayittan sil
    for pos in list(bot_state.all_positions()):
        key = (pos.symbol, pos.side)
        if key in exchange_by_key:
            continue

        try:
            last_price = client.get_last_price(pos.symbol)
        except Exception:
            last_price = pos.sl_price

        if pos.side == "long":
            pnl = (last_price - pos.entry_price) * pos.qty
            price_change_percent = (last_price - pos.entry_price) / pos.entry_price * 100
        else:
            pnl = (pos.entry_price - last_price) * pos.qty
            price_change_percent = (pos.entry_price - last_price) / pos.entry_price * 100
        duration = time.time() - pos.open_time

        bot_state.remove_position(pos.symbol, pos.side)
        bot_state.record_closed_trade({
            "symbol": pos.symbol, "side": pos.side,
            "entry_price": pos.entry_price, "exit_price": last_price, "reason": "Stop Loss",
            "pnl": pnl, "price_change_percent": price_change_percent, "duration_seconds": duration,
            "leverage": pos.leverage, "leverage_was_capped": pos.leverage_was_capped,
        })
        notify.notify_position_closed(pos.symbol, pos.side, pos.entry_price,
                                       last_price, "Stop Loss", pnl, price_change_percent, duration)

    # 2) Borsada var, bot'ta yok -> hesaplamalarini yapip kayda al
    for (symbol, side), p in exchange_by_key.items():
        if bot_state.has_position(symbol, side):
            continue

        pos = _build_position_from_exchange(p)
        bot_state.add_position(pos)
        notify.notify_position_synced_from_exchange(
            symbol, side, pos.entry_price, pos.sl_price, pos.lose_exit_price, pos.leverage)


# ------------------------------------------------------------
# BANT SINYALLERI (her saniye, anlik fiyatla)
# ------------------------------------------------------------
def check_band_signals(client, bot_state, symbol, df, prev_price, last_price):
    """Fiyat alt/ust banda degdi mi (iki poll arasinda gecti mi) diye bakar.

      alt banda degdi -> short kapat (varsa) + long ac
      ust banda degdi -> long kapat (varsa) + short ac
    """
    if prev_price is None:
        return

    last_row = df.iloc[-1]
    upper = float(last_row["upper_band"])
    lower = float(last_row["lower_band"])

    if upper != upper or lower != lower:  # NaN kontrolu
        return

    touched_lower = (prev_price - lower) * (last_price - lower) <= 0
    touched_upper = (prev_price - upper) * (last_price - upper) <= 0

    if touched_lower:
        _handle_band_touch(client, bot_state, symbol, "long", "short", last_price, upper, lower)
    elif touched_upper:
        _handle_band_touch(client, bot_state, symbol, "short", "long", last_price, upper, lower)


def _handle_band_touch(client, bot_state, symbol, new_side, opposite_side, last_price, upper, lower):
    # 1) Karsi yondeki pozisyon varsa once onu kapat. Kapatilamazsa yeni
    #    pozisyon acilmaz (bir sonraki saniye yeniden denenir).
    opposite_pos = bot_state.get_position(symbol, opposite_side)
    if opposite_pos:
        if not close_position(client, bot_state, opposite_pos, last_price, "Bant Dönüşü"):
            return

    # 2) Ayni yonde zaten pozisyon aciksa yenisi acilmaz
    if bot_state.has_position(symbol, new_side):
        return

    # 3) Long/short icin ayri ayri toplam limit
    if bot_state.open_count_for_side(new_side) >= config.MAX_POSITIONS_PER_SIDE:
        notify.notify_slot_full(bot_state.open_count_for_side(new_side),
                                 config.MAX_POSITIONS_PER_SIDE, symbol, new_side)
        bot_state.record_system_event("slot_full", symbol, new_side)
        return

    # 4) Karsi banda olan mesafe (D)
    if new_side == "long":
        opposite_band_price = upper
        band_distance = upper - last_price
    else:
        opposite_band_price = lower
        band_distance = last_price - lower

    _open_new_position(client, bot_state, symbol, new_side, last_price,
                       band_distance, opposite_band_price)


def _open_new_position(client, bot_state, symbol, side, entry_price, band_distance, opposite_band_price):
    available_margin, equity = get_available_margin(client, bot_state)
    max_leverage = client.get_max_leverage(symbol)

    result = sizing.calculate_position(
        side=side, entry_price=entry_price, band_distance=band_distance,
        opposite_band_price=opposite_band_price,
        total_equity=equity, max_leverage_for_coin=max_leverage,
    )

    if result is None:
        print(f"[open_position] {symbol} {side}: gecersiz mesafe, islem acilmiyor")
        return

    if result.allocated_amount > available_margin:
        notify.notify_insufficient_balance(symbol, side, result.allocated_amount, available_margin)
        bot_state.record_system_event("insufficient_balance", symbol, side)
        return

    if result.leverage_was_capped:
        notify.notify_leverage_capped(symbol, side, result.calculated_leverage, max_leverage)
        bot_state.record_system_event("leverage_capped", symbol, side)

    if result.position_volume < config.MIN_ORDER_VALUE_USDT:
        # Borsanin minimum emir degerinin altinda - emir denemeden atla.
        # (Denenirse borsa reddeder ve sinyal her saniye ayni basarisiz
        # emri tekrar tekrar dener.)
        print(f"[open_position] {symbol} {side}: islem hacmi "
              f"({result.position_volume:.2f} USDT) borsanin minimum emir degerinin "
              f"({config.MIN_ORDER_VALUE_USDT:.2f} USDT) altinda, islem acilmiyor")
        notify.notify_below_min_order_value(symbol, side, result.position_volume,
                                             config.MIN_ORDER_VALUE_USDT)
        bot_state.record_system_event("below_min_order_value", symbol, side)
        return

    qty = client.round_qty(symbol, result.qty)
    if qty <= 0:
        print(f"[open_position] {symbol} {side}: hesaplanan miktar cok kucuk, islem acilmiyor")
        return

    position_idx = 1 if side == "long" else 2
    order_side = "Buy" if side == "long" else "Sell"

    # Emir gonderme adimlari kendi try/except'i icinde: bir emrin
    # reddedilmesi ana donguye yukselip YANLISLIKLA "baglanti koptu"
    # olarak bildirilmesin.
    try:
        client.set_leverage(symbol, result.applied_leverage)
        client.open_market_position(symbol, order_side, qty, position_idx)
        client.set_stop_loss(symbol, result.sl_price, position_idx)
    except Exception as e:
        print(f"[open_position] {symbol} {side} acilirken emir hatasi: {e}")
        return

    pos = state_module.Position(
        symbol=symbol, side=side, position_idx=position_idx,
        entry_price=entry_price, sl_price=result.sl_price, lose_exit_price=result.lose_exit_price,
        leverage=result.applied_leverage, allocated_amount=result.allocated_amount, qty=qty,
        band_distance_at_entry=result.band_distance,
        opposite_band_at_entry=result.opposite_band_price,
        entry_lose_exit_percent=result.lose_exit_percent,
        leverage_was_capped=result.leverage_was_capped,
    )
    bot_state.add_position(pos)

    notify.notify_position_opened(
        symbol, side, entry_price, result.opposite_band_price,
        result.lose_exit_price, result.sl_price, result.applied_leverage,
        result.allocated_amount, result.position_volume,
    )


# ------------------------------------------------------------
# LOSE EXIT KONTROLU (her saniye, anlik fiyatla - acilista sabitlenen seviye)
# ------------------------------------------------------------
def check_lose_exit(client, bot_state, symbol, side, prev_price, last_price):
    pos = bot_state.get_position(symbol, side)
    if not pos:
        return

    lose_exit_price = pos.lose_exit_price
    if not lose_exit_price:
        return
    if prev_price is None:
        return

    touched = (prev_price - lose_exit_price) * (last_price - lose_exit_price) <= 0
    if touched:
        close_position(client, bot_state, pos, last_price, "Lose Exit")


def close_position(client, bot_state, pos, exit_price, reason) -> bool:
    """Pozisyonu kapatir. Basarili olursa True, borsa emri hata verirse
    False doner (kayit silinmez, bir sonraki saniye yeniden denenir)."""
    close_side = "Sell" if pos.side == "long" else "Buy"

    try:
        client.close_market_position(pos.symbol, close_side, pos.qty, pos.position_idx)
    except Exception as e:
        print(f"[close_position] {pos.symbol} {pos.side} kapatilirken hata: {e}")
        return False

    if pos.side == "long":
        pnl = (exit_price - pos.entry_price) * pos.qty
        price_change_percent = (exit_price - pos.entry_price) / pos.entry_price * 100
    else:
        pnl = (pos.entry_price - exit_price) * pos.qty
        price_change_percent = (pos.entry_price - exit_price) / pos.entry_price * 100
    duration = time.time() - pos.open_time

    bot_state.remove_position(pos.symbol, pos.side)
    bot_state.record_closed_trade({
        "symbol": pos.symbol, "side": pos.side,
        "entry_price": pos.entry_price, "exit_price": exit_price, "reason": reason,
        "pnl": pnl, "price_change_percent": price_change_percent, "duration_seconds": duration,
        "leverage": pos.leverage, "leverage_was_capped": pos.leverage_was_capped,
    })

    notify.notify_position_closed(pos.symbol, pos.side, pos.entry_price,
                                   exit_price, reason, pnl, price_change_percent, duration)
    return True
