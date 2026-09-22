# -*- coding: utf-8 -*-
"""
strategy.py
-----------
Botun beyni: giris sinyali kontrolu, TP kontrolu, trend-donusu cikis
kontrolu, pozisyon acma/kapama ve yeniden baslatmada acik pozisyonlari
tanima islemleri.

KOKLU GUNCELLEME - yeni strateji ozeti:
- Yon: sadece o anki Supertrend yonunde islem acilir (long ya da short).
- Giris: fiyat (saniyelik) Entry cizgisine degerse, Supertrend yonunde
  islem acilir.
- Cikis 4 yoldan biriyle olur:
    1) TP: fiyat (saniyelik) Exit cizgisine degerse pozisyon kapanir.
    2) Trend donusu: Supertrend yon degistirirse pozisyon kapanir - ama
       bu SADECE mum kapanisinda kontrol edilir (saniyelik degil).
    3) Lose exit: acilista sabitlenen bir seviye - TP'nin ters yonunde,
       TP mesafesinin 1.5 kati uzakta (RR 1:1.5). Fiyat (saniyelik) bu
       seviyeye degerse pozisyon kapanir.
    4) Guvenlik SL: acilista sabitlenen, borsadaki gercek stop emri
       (TP mesafesinin 2 kati uzakta) tetiklenirse (bot cokerse/baglanti
       koparsa diye guvenlik agi - normal kosullarda lose exit ondan
       once devreye girer).
- Her coin'de ayni anda en fazla 1 acik islem olabilir (long VEYA short).

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


# ------------------------------------------------------------
# YENIDEN BASLATMA - ACIK POZISYONLARI TANI
# ------------------------------------------------------------
def reconcile_open_positions(client, bot_state):
    exchange_positions = client.get_open_positions()
    for p in exchange_positions:
        symbol = p["symbol"]
        if symbol not in config.COINS:
            continue

        if bot_state.has_position(symbol):
            # Borsada ayni coin icin ikinci bir pozisyon bulundu (ornegin
            # eski hedge-modu botundan kalma bir kalinti). Yeni strateji
            # coin basina tek pozisyon varsayiyor - ilk bulunani takibe
            # alir, digerini gozardi eder ve durumu bildirir.
            print(f"[reconcile] {symbol}: birden fazla acik pozisyon bulundu, "
                  "sadece ilki takibe alindi - digerini manuel kontrol et.")
            continue

        pos_idx = int(p.get("positionIdx", 0))
        side = "long" if pos_idx == 1 else "short"
        entry_price = float(p["avgPrice"])
        qty = float(p["size"])
        leverage = float(p.get("leverage", 0) or 0)
        sl_price = float(p.get("stopLoss") or 0)

        if sl_price <= 0:
            print(f"[reconcile] {symbol} {side}: SL bulunamadi, sadece giris takip edilecek")

        lose_exit_price = state_module.reconstruct_lose_exit(entry_price, sl_price, side)

        allocated_amount = (entry_price * qty) / leverage if leverage else 0.0

        pos = state_module.Position(
            symbol=symbol, side=side, position_idx=pos_idx,
            entry_price=entry_price, sl_price=sl_price, lose_exit_price=lose_exit_price,
            leverage=leverage, allocated_amount=allocated_amount, qty=qty,
        )
        bot_state.add_position(pos)

        notify.notify_position_found_on_restart(symbol, side, entry_price, sl_price, lose_exit_price, leverage)


# ------------------------------------------------------------
# GIRIS SINYALI KONTROLU (her saniye, anlik fiyatla)
# ------------------------------------------------------------
def check_entry(client, bot_state, symbol, df, prev_price, last_price):
    """Fiyat Entry cizgisine degdi mi (iki poll arasinda gecti mi) diye
    bakar; yon o anki Supertrend yonudur."""
    last_row = df.iloc[-1]
    # NOT: pandas/numpy tipleri (numpy.float64, numpy.int64) burada dogal
    # Python float/int'e cevriliyor - aksi halde bu degerler daha sonra
    # trade_history JSON dosyasina yazilirken (leverage_was_capped gibi
    # numpy.bool_ turetilen alanlarda) serilestirme hatasi verir.
    entry_line = float(last_row["entry_line"])
    trend = int(last_row["trend"])

    if entry_line != entry_line:  # NaN kontrolu
        return  # gostergeler henuz yeterli veriyle hesaplanamadi

    if prev_price is None:
        return

    touched = (prev_price - entry_line) * (last_price - entry_line) <= 0
    if not touched:
        return

    side = "long" if trend == 1 else "short"

    # Coin'in zaten acik islemi var mi? (coin basina max 1 islem)
    if bot_state.has_position(symbol):
        return

    # Toplam sistem slotu dolu mu?
    if bot_state.total_open_count() >= config.MAX_TOTAL_POSITIONS:
        notify.notify_slot_full(bot_state.total_open_count(), config.MAX_TOTAL_POSITIONS, symbol, side)
        bot_state.record_system_event("slot_full", symbol, side)
        return

    exit_line = float(last_row["exit_line"])
    open_position(client, bot_state, symbol, side, last_price, exit_line)


def open_position(client, bot_state, symbol, side, entry_price, exit_line_price):
    available_margin, equity = get_available_margin(client, bot_state)
    max_leverage = client.get_max_leverage(symbol)

    result = sizing.calculate_position(
        side=side, entry_price=entry_price, exit_line_price=exit_line_price,
        total_equity=equity, max_leverage_for_coin=max_leverage,
    )

    if result is None:
        print(f"[open_position] {symbol} {side}: gecersiz mesafe (0), islem acilmiyor")
        return

    if result.allocated_amount > available_margin:
        notify.notify_insufficient_balance(symbol, side, result.allocated_amount, available_margin)
        bot_state.record_system_event("insufficient_balance", symbol, side)
        return

    if result.leverage_was_capped:
        notify.notify_leverage_capped(symbol, side, result.calculated_leverage, max_leverage)
        bot_state.record_system_event("leverage_capped", symbol, side)

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
        entry_price=entry_price, sl_price=result.sl_price,
        lose_exit_price=result.lose_exit_price,
        leverage=result.applied_leverage, allocated_amount=result.allocated_amount,
        qty=qty, exit_line_at_entry=result.exit_line_price,
        entry_exit_percent=result.entry_exit_percent,
        leverage_was_capped=result.leverage_was_capped,
    )
    bot_state.add_position(pos)

    notify.notify_position_opened(
        symbol, side, entry_price, result.exit_line_price,
        result.lose_exit_price, result.sl_price, result.applied_leverage,
        result.allocated_amount, result.position_volume,
    )


# ------------------------------------------------------------
# TP KONTROLU (her saniye, anlik fiyatla - Exit cizgisine degme)
# ------------------------------------------------------------
def check_exit(client, bot_state, symbol, df, prev_price, last_price):
    pos = bot_state.get_position(symbol)
    if not pos:
        return

    last_row = df.iloc[-1]
    # ONEMLI: exit_line pozisyonun KENDI yonune gore secilir - o anki
    # genel "trend" bayragina gore degil. Aksi halde mum kapanmadan
    # (saniyelik veriyle) genel trend gecici olarak ters donerse, exit
    # cizgisi karsi tarafin formulune gecer ve pozisyonun yonuyle
    # uyusmayan bir seviye haline gelir - canli ortamda tam olarak bu
    # yasandi (zararli bir kapanis "Take Profit" diye etiketlendi).
    if pos.side == "long":
        exit_line = float(last_row["long_exit_line"])
    else:
        exit_line = float(last_row["short_exit_line"])

    if exit_line != exit_line:  # NaN kontrolu
        return

    if prev_price is None:
        return

    touched = (prev_price - exit_line) * (last_price - exit_line) <= 0
    if not touched:
        return

    # Ek guvenlik: "Take Profit" sadece GERCEKTEN kar/basabas durumunda
    # tetiklenir. Normal kosullarda exit_line zaten hep fiyatin lehte
    # tarafinda olur, ama olasi bir gosterge anomalisi (ornegin trend
    # tam donus noktasindayken) yuzunden zararli bir "degme" olusursa,
    # bu TP olarak kapatilmaz - pozisyon acik kalir ve trend-donusu ya
    # da guvenlik SL mekanizmalarina birakilir.
    if pos.side == "long":
        favorable = last_price >= pos.entry_price
    else:
        favorable = last_price <= pos.entry_price

    if favorable:
        close_position(client, bot_state, pos, last_price, "Take Profit")


# ------------------------------------------------------------
# LOSE EXIT KONTROLU (her saniye, anlik fiyatla - acilista sabitlenen seviye)
# ------------------------------------------------------------
def check_lose_exit(client, bot_state, symbol, prev_price, last_price):
    pos = bot_state.get_position(symbol)
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
# TREND DONUSU KONTROLU (SADECE mum kapanisinda cagrilir)
# ------------------------------------------------------------
def check_trend_flip_exit(client, bot_state, symbol, confirmed_trend, last_price):
    pos = bot_state.get_position(symbol)
    if not pos:
        return

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

    bot_state.remove_position(pos.symbol)
    bot_state.record_closed_trade({
        "symbol": pos.symbol, "side": pos.side, "entry_price": pos.entry_price,
        "exit_price": exit_price, "reason": reason, "pnl": pnl,
        "price_change_percent": price_change_percent, "duration_seconds": duration,
        "leverage": pos.leverage, "leverage_was_capped": pos.leverage_was_capped,
    })

    notify.notify_position_closed(pos.symbol, pos.side, pos.entry_price, exit_price,
                                   reason, pnl, price_change_percent, duration)


# ------------------------------------------------------------
# BORSADA HARICI KAPANAN POZISYONLARI TESPIT ET (gercek SL tetiklendiyse)
# ------------------------------------------------------------
def reconcile_externally_closed(client, bot_state):
    exchange_positions = client.get_open_positions()
    exchange_symbols = {p["symbol"] for p in exchange_positions}

    for pos in list(bot_state.all_positions()):
        if pos.symbol not in exchange_symbols:
            # Bot'un bilmeden kapandi -> gercek SL emri tetiklenmis olmali
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

            bot_state.remove_position(pos.symbol)
            bot_state.record_closed_trade({
                "symbol": pos.symbol, "side": pos.side, "entry_price": pos.entry_price,
                "exit_price": last_price, "reason": "Stop Loss", "pnl": pnl,
                "price_change_percent": price_change_percent, "duration_seconds": duration,
                "leverage": pos.leverage, "leverage_was_capped": pos.leverage_was_capped,
            })
            notify.notify_position_closed(pos.symbol, pos.side, pos.entry_price, last_price,
                                           "Stop Loss", pnl, price_change_percent, duration)
