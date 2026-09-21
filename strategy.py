# -*- coding: utf-8 -*-
"""
strategy.py
-----------
Botun beyni: giris sinyali kontrolu, TP/lose-exit kontrolu, pozisyon
acma/kapama ve yeniden baslatmada acik pozisyonlari tanima islemleri.

NOT: Bu dosya Bybit'ten veri cekme/onbellekleme islerine karismaz - o is
tamamen bybit_client.py'de (get_klines_cached). Bu dosya sadece o veriyi
kullanip karar verir.
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
    ceker ve gostergeleri hesaplar."""
    df = client.get_klines_cached(symbol)
    df = indicators.compute_all(df)
    return df


# ------------------------------------------------------------
# YENIDEN BASLATMA - ACIK POZISYONLARI TANI
# ------------------------------------------------------------
def reconcile_open_positions(client, bot_state):
    exchange_positions = client.get_open_positions()
    for p in exchange_positions:
        symbol = p["symbol"]
        if symbol not in config.COINS:
            continue
        pos_idx = int(p.get("positionIdx", 0))
        side = "long" if pos_idx == 1 else "short"
        entry_price = float(p["avgPrice"])
        qty = float(p["size"])
        leverage = float(p.get("leverage", 0) or 0)
        sl_price = float(p.get("stopLoss") or 0)

        if sl_price <= 0:
            # SL bulunamadi - guvenlik icin bu pozisyonu yine de takibe al
            # ama lose exit / SL degerleri bilinmiyor demektir.
            print(f"[reconcile] {symbol} {side}: SL bulunamadi, sadece giris takip edilecek")
            continue

        lose_exit_price, lose_exit_percent = state_module.reconstruct_lose_exit(
            entry_price, sl_price, side)

        allocated_amount = (entry_price * qty) / leverage if leverage else 0.0

        pos = state_module.Position(
            symbol=symbol, side=side, position_idx=pos_idx,
            entry_price=entry_price, lose_exit_price=lose_exit_price,
            lose_exit_percent=lose_exit_percent, sl_price=sl_price,
            leverage=leverage, allocated_amount=allocated_amount, qty=qty,
        )
        bot_state.add_position(pos)

        notify.notify_position_found_on_restart(
            symbol, side, entry_price, lose_exit_price, lose_exit_percent,
            sl_price, leverage,
        )


# ------------------------------------------------------------
# GIRIS SINYALI KONTROLU
# ------------------------------------------------------------
def check_entry(client, bot_state, symbol, df, prev_price, last_price):
    """Fiyat merkez cizgisine degdi mi (iki poll arasinda gecti mi) diye
    bakar, yon belirler ve uygunsa islemi acar."""
    last_row = df.iloc[-1]
    merkez_value = last_row["merkez"]
    merkez_ust = last_row["merkez_ust_bant"]
    merkez_alt = last_row["merkez_alt_bant"]
    t3_ust = last_row["t3_ust_bant"]
    t3_alt = last_row["t3_alt_bant"]

    if any(v != v for v in [merkez_value, merkez_ust, merkez_alt, t3_ust, t3_alt]):  # NaN kontrolu
        return  # gostergeler henuz yeterli veriyle hesaplanamadi

    if prev_price is None:
        return

    touched = (prev_price - merkez_value) * (last_price - merkez_value) <= 0

    if not touched:
        return

    # Yon: Merkez cizgisi T3 bantlarina gore nerede? (T3 sadece yon icin
    # kullanilir, mesafe/buyukluk hesabina girmez)
    if merkez_value > t3_ust:
        side = "long"
    elif merkez_value < t3_alt:
        side = "short"
    else:
        return  # merkez, iki bandin arasinda -> sinyal yok

    # Coin'in bu yonde zaten acik pozisyonu var mi?
    if bot_state.has_position(symbol, side):
        return

    # Toplam sistem slotu dolu mu?
    if bot_state.total_open_count() >= config.MAX_TOTAL_POSITIONS:
        notify.notify_slot_full(bot_state.total_open_count(), config.MAX_TOTAL_POSITIONS, symbol, side)
        return

    # Pozisyon buyuklugu/kaldirac icin mesafe artik Merkez'in kendi
    # ust/alt bandindan olculuyor (T3'ten degil)
    open_position(client, bot_state, symbol, side, last_price, merkez_value, merkez_ust, merkez_alt)


def open_position(client, bot_state, symbol, side, entry_price, merkez_value, merkez_ust, merkez_alt):
    available_margin, equity = get_available_margin(client, bot_state)

    band_price = merkez_ust if side == "long" else merkez_alt
    max_leverage = client.get_max_leverage(symbol)

    result = sizing.calculate_position(
        side=side, entry_price=entry_price, merkez_band_price=band_price,
        total_equity=equity, max_leverage_for_coin=max_leverage,
    )

    if result.allocated_amount > available_margin:
        notify.notify_insufficient_balance(symbol, side, result.allocated_amount, available_margin)
        return

    if result.leverage_was_capped:
        notify.notify_leverage_capped(symbol, side, result.calculated_leverage, max_leverage)

    qty = client.round_qty(symbol, result.qty)
    if qty <= 0:
        print(f"[open_position] {symbol} {side}: hesaplanan miktar cok kucuk, islem acilmiyor")
        return

    position_idx = 1 if side == "long" else 2
    order_side = "Buy" if side == "long" else "Sell"

    client.set_leverage(symbol, result.applied_leverage)
    client.open_market_position(symbol, order_side, qty, position_idx)
    client.set_stop_loss(symbol, result.sl_price, position_idx)

    pos = state_module.Position(
        symbol=symbol, side=side, position_idx=position_idx,
        entry_price=entry_price, lose_exit_price=result.lose_exit_price,
        lose_exit_percent=result.lose_exit_percent, sl_price=result.sl_price,
        leverage=result.applied_leverage, allocated_amount=result.allocated_amount,
        qty=qty,
    )
    bot_state.add_position(pos)

    notify.notify_position_opened(
        symbol, side, entry_price, merkez_value, band_price,
        result.lose_exit_price, result.lose_exit_percent, result.sl_price,
        result.applied_leverage, result.allocated_amount, result.position_volume,
    )


# ------------------------------------------------------------
# CIKIS KONTROLU (TP / LOSE EXIT)
# ------------------------------------------------------------
def check_exit(client, bot_state, symbol, df, last_price):
    last_row = df.iloc[-1]
    merkez_ust = last_row["merkez_ust_bant"]
    merkez_alt = last_row["merkez_alt_bant"]

    for side in ("long", "short"):
        pos = bot_state.get_position(symbol, side)
        if not pos:
            continue

        reason = None
        if side == "long":
            if last_price >= merkez_ust:
                reason = "Take Profit"
            elif last_price <= pos.lose_exit_price:
                reason = "Lose Exit"
        else:
            if last_price <= merkez_alt:
                reason = "Take Profit"
            elif last_price >= pos.lose_exit_price:
                reason = "Lose Exit"

        if reason:
            close_position(client, bot_state, pos, last_price, reason)


def close_position(client, bot_state, pos, exit_price, reason):
    position_idx = pos.position_idx
    close_side = "Sell" if pos.side == "long" else "Buy"

    try:
        client.close_market_position(pos.symbol, close_side, pos.qty, position_idx)
    except Exception as e:
        print(f"[close_position] {pos.symbol} kapatilirken hata: {e}")
        return

    if pos.side == "long":
        pnl = (exit_price - pos.entry_price) * pos.qty
    else:
        pnl = (pos.entry_price - exit_price) * pos.qty
    pnl_percent = (pnl / pos.allocated_amount * 100) if pos.allocated_amount else 0.0
    duration = time.time() - pos.open_time

    bot_state.remove_position(pos.symbol, pos.side)
    bot_state.record_closed_trade({
        "symbol": pos.symbol, "side": pos.side, "entry_price": pos.entry_price,
        "exit_price": exit_price, "reason": reason, "pnl": pnl,
        "pnl_percent": pnl_percent, "duration_seconds": duration,
        "leverage_capped": False,
    })

    notify.notify_position_closed(pos.symbol, pos.side, pos.entry_price, exit_price,
                                   reason, pnl, pnl_percent, duration)


# ------------------------------------------------------------
# BORSADA HARICI KAPANAN POZISYONLARI TESPIT ET (gercek SL tetiklendiyse)
# ------------------------------------------------------------
def reconcile_externally_closed(client, bot_state):
    exchange_positions = client.get_open_positions()
    exchange_keys = set()
    for p in exchange_positions:
        idx = int(p.get("positionIdx", 0))
        side = "long" if idx == 1 else "short"
        exchange_keys.add((p["symbol"], side))

    for pos in list(bot_state.all_positions()):
        if (pos.symbol, pos.side) not in exchange_keys:
            # Bot'un bilmeden kapandi -> gercek SL emri tetiklenmis olmali
            try:
                last_price = client.get_last_price(pos.symbol)
            except Exception:
                last_price = pos.sl_price
            if pos.side == "long":
                pnl = (last_price - pos.entry_price) * pos.qty
            else:
                pnl = (pos.entry_price - last_price) * pos.qty
            pnl_percent = (pnl / pos.allocated_amount * 100) if pos.allocated_amount else 0.0
            duration = time.time() - pos.open_time

            bot_state.remove_position(pos.symbol, pos.side)
            bot_state.record_closed_trade({
                "symbol": pos.symbol, "side": pos.side, "entry_price": pos.entry_price,
                "exit_price": last_price, "reason": "Stop Loss", "pnl": pnl,
                "pnl_percent": pnl_percent, "duration_seconds": duration,
                "leverage_capped": False,
            })
            notify.notify_position_closed(pos.symbol, pos.side, pos.entry_price, last_price,
                                           "Stop Loss", pnl, pnl_percent, duration)
