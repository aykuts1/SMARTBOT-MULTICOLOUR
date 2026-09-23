# -*- coding: utf-8 -*-
"""
strategy.py
-----------
Botun beyni: giris sinyali kontrolu (Gold + Silver), TP kontrolu,
trend-donusu cikis kontrolu (sadece Gold), lose exit kontrolu, pozisyon
acma/kapama, borsayla iki yonlu senkronizasyon.

KOKLU GUNCELLEME - GOLD ve SILVER islem turleri:

GOLD ISLEM (eski tek stratejinin aynisi, sadece isimler Gold/Silver oldu):
  - Giris: fiyat (saniyelik) Gold cizgisine degerse, o anki Supertrend
    YONUNDE acilir.
  - TP hedefi: Silver cizgisi (dinamik, pozisyonun KENDI yonune gore -
    genel trend bayragina gore degil, bkz. check_tp_exit).
  - Lose exit: Gold-Silver mesafesinin 1.5 kati (RR 1:1.5), sabit.
  - Trend donusu: Supertrend yon degistirirse kapanir - SADECE mum
    kapanisinda kontrol edilir.
  - Guvenlik SL: mesafenin 2 kati, sabit.

SILVER ISLEM (yeni):
  - Giris: fiyat (saniyelik) Silver cizgisine degerse, o anki Supertrend'in
    TERSI yonunde acilir.
  - TP hedefi: Gold cizgisi (dinamik, pozisyonun KENDI yonune gore).
  - Lose exit: Gold-Silver mesafesinin 1.0 kati (RR 1:1), sabit.
  - Trend donusu cikisi YOK.
  - Guvenlik SL: mesafenin 2 kati, sabit (Gold ile AYNI carpan).

Bir coin'de ayni anda en fazla 1 long + 1 short acik olabilir (Gold ve
Silver hep ters yonde actigi icin bu, borsanin hedge kapasitesiyle
birebir ortusuyor - bkz. state.py'nin "SYMBOL_side" anahtarlamasi).
Toplam sistem slotu LONG ve SHORT icin AYRI AYRI sinirli: en fazla
MAX_POSITIONS_PER_SIDE (varsayilan 12) long VE en fazla o kadar short
ayni anda acik olabilir (birlesik degil, ayri sayaçlar).

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


def get_confirmed_trend(df):
    """Trend donusu kontrolu icin kullanilan, 'kapanmis' son mumun trend
    degeri. df'nin son satiri her saniye anlik fiyatla guncellenen, henuz
    kapanmamis mum oldugu icin (bkz. bybit_client), trend donusu kontrolu
    bunun yerine bir onceki (kapanmis) mumu kullanir."""
    if len(df) >= 2:
        return int(df.iloc[-2]["trend"])
    return int(df.iloc[-1]["trend"])


def _lose_exit_mult_for(trade_type: str) -> float:
    return (config.LOSE_EXIT_DISTANCE_MULT_GOLD if trade_type == "gold"
            else config.LOSE_EXIT_DISTANCE_MULT_SILVER)


# ------------------------------------------------------------
# YENIDEN BASLATMA / SENKRONIZASYON ORTAK YARDIMCILARI
# ------------------------------------------------------------
def _exchange_positions_by_key(client) -> dict:
    """Borsadaki acik pozisyonlari, takip edilen coin listesiyle
    sinirlandirip (sembol, yon) -> pozisyon sozlugune cevirir. Ayni
    (sembol, yon) icin birden fazla kayit bulunursa (beklenmedik bir
    durum - borsa bunu zaten tek positionIdx ile sinirlar) sadece
    ilkini alir ve durumu loglar."""
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


def _infer_trade_type(client, symbol: str, side: str) -> str:
    """Bir pozisyonun turu (Gold/Silver) bot'un kendi kaydinda yoksa
    (ornegin elle acilmis bir pozisyon), o anki Supertrend yonuyle
    karsilastirilarak TAHMIN edilir: pozisyonun yonu trend'le ayniysa
    Gold (trend yonunde acilir), tersiyse Silver (trend'in tersi yonde
    acilir) varsayilir."""
    try:
        df = compute_indicators_for_symbol(client, symbol)
        trend = int(df.iloc[-1]["trend"])
    except Exception as e:
        print(f"[reconcile] {symbol}: tur tahmini icin trend okunamadi ({e}), Gold varsayildi")
        return "gold"

    side_trend = 1 if side == "long" else -1
    return "gold" if side_trend == trend else "silver"


def _build_position_from_exchange(bot_state, client, p: dict) -> tuple:
    """Tek bir borsa pozisyon kaydindan (get_open_positions sonucu) bir
    Position nesnesi olusturur. Guvenlik SL borsadan dogrudan okunur;
    lose exit bu SL'den (turun oranina gore) GERI HESAPLANIR.
    Donen deger: (Position, type_was_inferred: bool)"""
    symbol = p["symbol"]
    pos_idx = int(p.get("positionIdx", 0))
    side = "long" if pos_idx == 1 else "short"
    entry_price = float(p["avgPrice"])
    qty = float(p["size"])
    leverage = float(p.get("leverage", 0) or 0)
    sl_price = float(p.get("stopLoss") or 0)

    remembered_type = bot_state.get_remembered_type(symbol, side)
    type_was_inferred = remembered_type is None
    trade_type = remembered_type or _infer_trade_type(client, symbol, side)
    if type_was_inferred:
        print(f"[reconcile] {symbol} {side}: tur kaydi bulunamadi, tahmin edildi -> {trade_type}")

    lose_exit_mult = _lose_exit_mult_for(trade_type)
    lose_exit_price = state_module.reconstruct_lose_exit(entry_price, sl_price, side, lose_exit_mult)
    allocated_amount = (entry_price * qty) / leverage if leverage else 0.0

    pos = state_module.Position(
        symbol=symbol, side=side, position_idx=pos_idx, trade_type=trade_type,
        entry_price=entry_price, sl_price=sl_price, lose_exit_price=lose_exit_price,
        leverage=leverage, allocated_amount=allocated_amount, qty=qty,
    )
    return pos, type_was_inferred


def reconcile_open_positions(client, bot_state):
    """Bot baslarken (main.py) bir kez cagrilir - borsadaki tum acik
    pozisyonlari bastan takibe alir."""
    for (symbol, side), p in _exchange_positions_by_key(client).items():
        pos, _inferred = _build_position_from_exchange(bot_state, client, p)
        if pos.sl_price <= 0:
            print(f"[reconcile] {symbol} {side}: SL bulunamadi, sadece giris takip edilecek")
        bot_state.add_position(pos)
        notify.notify_position_found_on_restart(
            symbol, side, pos.trade_type, pos.entry_price, pos.sl_price,
            pos.lose_exit_price, pos.leverage)


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
         gereken tum hesaplamalar (tur tahmini, lose exit) yapilarak
         kayda alinir - tipki restart'ta oldugu gibi, ama bot CALISIRKEN.
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
            "symbol": pos.symbol, "side": pos.side, "trade_type": pos.trade_type,
            "entry_price": pos.entry_price, "exit_price": last_price, "reason": "Stop Loss",
            "pnl": pnl, "price_change_percent": price_change_percent, "duration_seconds": duration,
            "leverage": pos.leverage, "leverage_was_capped": pos.leverage_was_capped,
        })
        notify.notify_position_closed(pos.symbol, pos.side, pos.trade_type, pos.entry_price,
                                       last_price, "Stop Loss", pnl, price_change_percent, duration)

    # 2) Borsada var, bot'ta yok -> hesaplamalarini yapip kayda al
    for (symbol, side), p in exchange_by_key.items():
        if bot_state.has_position(symbol, side):
            continue

        pos, type_was_inferred = _build_position_from_exchange(bot_state, client, p)
        bot_state.add_position(pos)
        notify.notify_position_synced_from_exchange(
            symbol, side, pos.trade_type, pos.entry_price, pos.sl_price,
            pos.lose_exit_price, pos.leverage, inferred=type_was_inferred)


# ------------------------------------------------------------
# GIRIS SINYALLERI (her saniye, anlik fiyatla)
# ------------------------------------------------------------
def check_entry_gold(client, bot_state, symbol, df, prev_price, last_price):
    """Fiyat Gold cizgisine degdi mi (iki poll arasinda gecti mi) diye
    bakar; yon o anki Supertrend yonudur."""
    last_row = df.iloc[-1]
    gold_line = float(last_row["gold_line"])
    trend = int(last_row["trend"])

    if gold_line != gold_line:  # NaN kontrolu
        return
    if prev_price is None:
        return

    touched = (prev_price - gold_line) * (last_price - gold_line) <= 0
    if not touched:
        return

    side = "long" if trend == 1 else "short"

    if bot_state.has_position(symbol, side):
        return
    if bot_state.open_count_for_side(side) >= config.MAX_POSITIONS_PER_SIDE:
        notify.notify_slot_full(bot_state.open_count_for_side(side), config.MAX_POSITIONS_PER_SIDE, symbol, side, "gold")
        bot_state.record_system_event("slot_full", symbol, side)
        return

    silver_line = float(last_row["silver_line"])
    _open_new_position(client, bot_state, symbol, side, "gold", last_price, silver_line)


def check_entry_silver(client, bot_state, symbol, df, prev_price, last_price):
    """Fiyat Silver cizgisine degdi mi diye bakar; yon o anki Supertrend'in
    TERSIDIR."""
    last_row = df.iloc[-1]
    silver_line = float(last_row["silver_line"])
    trend = int(last_row["trend"])

    if silver_line != silver_line:  # NaN kontrolu
        return
    if prev_price is None:
        return

    touched = (prev_price - silver_line) * (last_price - silver_line) <= 0
    if not touched:
        return

    side = "short" if trend == 1 else "long"  # TERS yon

    if bot_state.has_position(symbol, side):
        return
    if bot_state.open_count_for_side(side) >= config.MAX_POSITIONS_PER_SIDE:
        notify.notify_slot_full(bot_state.open_count_for_side(side), config.MAX_POSITIONS_PER_SIDE, symbol, side, "silver")
        bot_state.record_system_event("slot_full", symbol, side)
        return

    gold_line = float(last_row["gold_line"])
    _open_new_position(client, bot_state, symbol, side, "silver", last_price, gold_line)


def _open_new_position(client, bot_state, symbol, side, trade_type, entry_price, target_line_price):
    available_margin, equity = get_available_margin(client, bot_state)
    max_leverage = client.get_max_leverage(symbol)
    lose_exit_mult = _lose_exit_mult_for(trade_type)

    result = sizing.calculate_position(
        side=side, entry_price=entry_price, target_line_price=target_line_price,
        total_equity=equity, max_leverage_for_coin=max_leverage, lose_exit_mult=lose_exit_mult,
    )

    if result is None:
        print(f"[open_position] {symbol} {side} ({trade_type}): gecersiz mesafe (0), islem acilmiyor")
        return

    if result.allocated_amount > available_margin:
        notify.notify_insufficient_balance(symbol, side, trade_type, result.allocated_amount, available_margin)
        bot_state.record_system_event("insufficient_balance", symbol, side)
        return

    if result.leverage_was_capped:
        notify.notify_leverage_capped(symbol, side, trade_type, result.calculated_leverage, max_leverage)
        bot_state.record_system_event("leverage_capped", symbol, side)

    qty = client.round_qty(symbol, result.qty)
    if qty <= 0:
        print(f"[open_position] {symbol} {side} ({trade_type}): hesaplanan miktar cok kucuk, islem acilmiyor")
        return

    position_idx = 1 if side == "long" else 2
    order_side = "Buy" if side == "long" else "Sell"

    client.set_leverage(symbol, result.applied_leverage)
    client.open_market_position(symbol, order_side, qty, position_idx)
    client.set_stop_loss(symbol, result.sl_price, position_idx)

    pos = state_module.Position(
        symbol=symbol, side=side, position_idx=position_idx, trade_type=trade_type,
        entry_price=entry_price, sl_price=result.sl_price, lose_exit_price=result.lose_exit_price,
        leverage=result.applied_leverage, allocated_amount=result.allocated_amount, qty=qty,
        target_line_at_entry=result.target_line_price, entry_target_percent=result.entry_target_percent,
        entry_lose_exit_percent=result.entry_lose_exit_percent,
        leverage_was_capped=result.leverage_was_capped,
    )
    bot_state.add_position(pos)

    notify.notify_position_opened(
        symbol, side, trade_type, entry_price, result.target_line_price,
        result.lose_exit_price, result.sl_price, result.applied_leverage,
        result.allocated_amount, result.position_volume,
    )


# ------------------------------------------------------------
# TP KONTROLU (her saniye, anlik fiyatla - hedef cizgiye degme)
# ------------------------------------------------------------
def check_tp_exit(client, bot_state, symbol, side, df, prev_price, last_price):
    """Gold islem icin hedef Silver cizgisi, Silver islem icin hedef
    Gold cizgisidir - HER IKISI DE pozisyonun KENDI yonune gore secilir
    (o anki genel trend bayragina gore degil - bkz. indicators.py'nin
    ustundeki aciklama)."""
    pos = bot_state.get_position(symbol, side)
    if not pos:
        return

    last_row = df.iloc[-1]
    if pos.trade_type == "gold":
        target_col = "long_silver_line" if side == "long" else "short_silver_line"
    else:
        target_col = "long_gold_line" if side == "long" else "short_gold_line"
    target_line = float(last_row[target_col])

    if target_line != target_line:  # NaN kontrolu
        return
    if prev_price is None:
        return

    touched = (prev_price - target_line) * (last_price - target_line) <= 0
    if not touched:
        return

    # Ek guvenlik: "Take Profit" sadece GERCEKTEN kar/basabas durumunda
    # tetiklenir (bkz. eski hata: mum kapanmadan trend gecici donerse
    # zararli bir kapanis yanlislikla TP diye etiketleniyordu).
    if side == "long":
        favorable = last_price >= pos.entry_price
    else:
        favorable = last_price <= pos.entry_price

    if favorable:
        close_position(client, bot_state, pos, last_price, "Take Profit")


# ------------------------------------------------------------
# LOSE EXIT KONTROLU (her saniye, anlik fiyatla - acilista sabitlenen seviye)
# ------------------------------------------------------------
def check_lose_exit(client, bot_state, symbol, side, prev_price, last_price):
    """Hem Gold hem Silver icin AYNI mekanizma - fark sadece acilista
    hesaplanan mesafede (bkz. sizing.py), burada ayrim yapmaya gerek yok."""
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


# ------------------------------------------------------------
# TREND DONUSU KONTROLU (SADECE Gold islemler icin, SADECE mum kapanisinda)
# ------------------------------------------------------------
def check_trend_flip_exit(client, bot_state, symbol, side, confirmed_trend, last_price):
    pos = bot_state.get_position(symbol, side)
    if not pos:
        return
    if pos.trade_type != "gold":
        return  # Silver'da trend donusu cikisi yok

    pos_trend = 1 if pos.side == "long" else -1
    if confirmed_trend != pos_trend:
        close_position(client, bot_state, pos, last_price, "Trend Dönüşü")


def close_position(client, bot_state, pos, exit_price, reason):
    close_side = "Sell" if pos.side == "long" else "Buy"

    try:
        client.close_market_position(pos.symbol, close_side, pos.qty, pos.position_idx)
    except Exception as e:
        print(f"[close_position] {pos.symbol} kapatilirken hata: {e}")
        return

    if pos.side == "long":
        pnl = (exit_price - pos.entry_price) * pos.qty
        price_change_percent = (exit_price - pos.entry_price) / pos.entry_price * 100
    else:
        pnl = (pos.entry_price - exit_price) * pos.qty
        price_change_percent = (pos.entry_price - exit_price) / pos.entry_price * 100
    duration = time.time() - pos.open_time

    bot_state.remove_position(pos.symbol, pos.side)
    bot_state.record_closed_trade({
        "symbol": pos.symbol, "side": pos.side, "trade_type": pos.trade_type,
        "entry_price": pos.entry_price, "exit_price": exit_price, "reason": reason,
        "pnl": pnl, "price_change_percent": price_change_percent, "duration_seconds": duration,
        "leverage": pos.leverage, "leverage_was_capped": pos.leverage_was_capped,
    })

    notify.notify_position_closed(pos.symbol, pos.side, pos.trade_type, pos.entry_price,
                                   exit_price, reason, pnl, price_change_percent, duration)
