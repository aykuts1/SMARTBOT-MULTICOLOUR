# -*- coding: utf-8 -*-
"""
strategy.py
---------------------
Botun beyni: Q-Trend cizgileriyle giris/cikis, pozisyon acma/kapama,
borsayla iki yonlu senkronizasyon.

STRATEJI:
  - GIRIS: Fiyat Silver cizgisine degerse LONG, Gold cizgisine degerse SHORT.
  - CIKIS (hangisi once olursa):
      1) Kar Alma     : ana cizgi (TP) - canli, ana cizgiyle birlikte kayar.
      2) Hareketli Zarar: long'da Silver loss, short'ta Gold loss - canli.
      3) Lose Exit    : acilista (giris-TP mesafesi x 1.5) ters yonde SABITLENEN seviye.
      4) Stop Loss    : borsadaki guvenlik SL'si (sabit lose exit mesafesinin 2 kati).
  - Her coinde ayni anda en fazla 1 islem; toplamda en fazla MAX_OPEN_POSITIONS.
  - Ayni mumda birden fazla islem acilip kapanabilir (zararla kapanis sonrasi dahil;
    mum basina islem siniri yok).

NOT: Bu dosya Bybit'ten veri cekme/onbellekleme islerine karismaz - o is
tamamen bybit_client.py'de.
"""

import time

import config
import indicators
import sizing
import state as state_module
import telegram_notifier as notify

# Coin basina mum dilimi basina bir kez hesaplanan "kapanmis mum" degerleri
_qt_cache = {}
_warned_no_data = set()


def get_available_margin(client, bot_state):
    """Toplam varlik - su an acik pozisyonlar icin ayrilmis miktarlar."""
    equity = client.get_total_equity()
    used = sum(p.allocated_amount for p in bot_state.all_positions())
    return equity - used, equity


def compute_indicators_for_symbol(client, symbol):
    """Raporlar icin: mum verisini ceker ve Q-Trend cizgilerini tum
    mumlar icin hesaplar. (Botun saniyelik dongusu bunu kullanmaz.)"""
    df = client.get_klines_cached(symbol)
    return indicators.compute_all(df)


# ------------------------------------------------------------
# Q-TREND TABAN DEGERLERI (mum basina bir kez)
# ------------------------------------------------------------
def _get_base(client, symbol):
    """(base, taze_mi) dondurur. base: {'bucket','m_prev','atr_prev'}.
    Yeni mum dilimi icin veri henuz hazir degilse eski taban (varsa)
    dondurulur ve taze_mi=False olur: bu durumda sadece CIKIS kontrolu
    yapilir, yeni giris acilmaz."""
    bucket = client.current_bucket()
    cached = _qt_cache.get(symbol)
    if cached and cached["bucket"] == bucket:
        return cached, True

    df = client.get_cached_klines(symbol)
    if df is not None:
        # Son satir canli mum; kapanmis mumlar = geri kalani
        st = indicators.closed_state(df.iloc[:-1])
        if st is None:
            if symbol not in _warned_no_data:
                _warned_no_data.add(symbol)
                print(f"[strategy] {symbol}: Q-Trend icin yeterli mum verisi yok, coin atlaniyor")
            return None, False
        base = {"bucket": bucket, "m_prev": st["m_prev"], "atr_prev": st["atr_prev"]}
        _qt_cache[symbol] = base
        _warned_no_data.discard(symbol)
        return base, True

    return cached, False


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
    sabit lose exit bu SL'den GERI HESAPLANIR."""
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
# COIN ISLEME (main.py her saniye, her coin icin cagirir)
# ------------------------------------------------------------
def process_symbol(client, bot_state, symbol, prev_price, last_price):
    base, fresh = _get_base(client, symbol)
    if base is None:
        return

    lv = indicators.live_levels(base["m_prev"], base["atr_prev"], last_price)

    # Once cikislar (pozisyon yoksa fonksiyonlar kendiliginden bir sey yapmaz)
    for side in ("long", "short"):
        check_exits(client, bot_state, symbol, side, last_price, lv)

    # Yeni mum icin taze veri yoksa yeni giris acilmaz
    if not fresh:
        return

    check_entry_signals(client, bot_state, symbol, prev_price, last_price, lv)


# ------------------------------------------------------------
# CIKIS KONTROLU (her saniye, anlik fiyatla)
# ------------------------------------------------------------
def check_exits(client, bot_state, symbol, side, last_price, lv):
    """Long icin:
         fiyat >= ana cizgi                      -> Kar Alma
         fiyat <= Silver loss (canli)            -> Hareketli Zarar
         fiyat <= sabit lose exit                -> Lose Exit
       Short icin ayni sey aynadan (Gold loss, yukari).
       Zarar tarafinda birden fazla seviye asilmissa fiyatin ONCE ulastigi
       (girise en yakin) seviyenin adi sebep olarak yazilir."""
    pos = bot_state.get_position(symbol, side)
    if not pos:
        return

    reason = None
    if side == "long":
        if last_price >= lv["m"]:
            reason = "Kâr Alma"
        else:
            hits = []
            if last_price <= lv["silver_loss"]:
                hits.append((lv["silver_loss"], "Hareketli Zarar"))
            if pos.lose_exit_price and last_price <= pos.lose_exit_price:
                hits.append((pos.lose_exit_price, "Lose Exit"))
            if hits:
                reason = max(hits)[1]
    else:
        if last_price <= lv["m"]:
            reason = "Kâr Alma"
        else:
            hits = []
            if last_price >= lv["gold_loss"]:
                hits.append((lv["gold_loss"], "Hareketli Zarar"))
            if pos.lose_exit_price and last_price >= pos.lose_exit_price:
                hits.append((pos.lose_exit_price, "Lose Exit"))
            if hits:
                reason = min(hits)[1]

    if reason:
        close_position(client, bot_state, pos, last_price, reason)


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


# ------------------------------------------------------------
# GIRIS SINYALI (her saniye, anlik fiyatla)
# ------------------------------------------------------------
def check_entry_signals(client, bot_state, symbol, prev_price, last_price, lv):
    """Fiyat Silver/Gold cizgisine degdi mi (iki poll arasinda gecti mi)?
      Silver'a degdi -> LONG ;  Gold'a degdi -> SHORT
    Cizgi degeri olarak ANLIK (canli) cizgi kullanilir; boylece cizginin
    kendisi kayarken (yeni mum / basamak) sahte 'degme' uretilmez, sadece
    FIYATIN hareketiyle cizgiye ulasmasi sayilir."""
    if prev_price is None:
        return

    silver = lv["silver"]
    gold = lv["gold"]
    touched_silver = (prev_price - silver) * (last_price - silver) <= 0
    touched_gold = (prev_price - gold) * (last_price - gold) <= 0

    if touched_silver:
        _try_open_position(client, bot_state, symbol, "long", last_price, lv)
    elif touched_gold:
        _try_open_position(client, bot_state, symbol, "short", last_price, lv)


def _try_open_position(client, bot_state, symbol, side, last_price, lv):
    # 1) Her coinde sadece 1 islem
    if bot_state.has_any_position(symbol):
        return

    # 2) Toplam acik islem limiti (long + short birlikte)
    open_count = bot_state.total_open_count()
    if open_count >= config.MAX_OPEN_POSITIONS:
        notify.notify_slot_full(open_count, config.MAX_OPEN_POSITIONS, symbol, side)
        bot_state.record_system_event("slot_full", symbol, side)
        return

    # 3) Acilis anindaki TP (ana cizgi) ve risk cizgisi (Silver loss / Gold loss)
    tp_price = lv["m"]
    risk_line = lv["silver_loss"] if side == "long" else lv["gold_loss"]

    _open_new_position(client, bot_state, symbol, side, last_price, tp_price, risk_line)


def _open_new_position(client, bot_state, symbol, side, entry_price, tp_price, risk_line_price):
    available_margin, equity = get_available_margin(client, bot_state)
    max_leverage = client.get_max_leverage(symbol)

    result = sizing.calculate_position(
        side=side, entry_price=entry_price, tp_price=tp_price,
        risk_line_price=risk_line_price,
        total_equity=equity, max_leverage_for_coin=max_leverage,
    )

    if result is None:
        print(f"[open_position] {symbol} {side}: gecersiz mesafe (TP/risk cizgisi yonu uymuyor), islem acilmiyor")
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

    # Borsanin minimum lot adimi miktari yukari zorlamis olabilir (ornegin
    # dusuk varlikta BTC/ETH). Gercek hacim hedefin cok ustundeyse acilmaz.
    actual_volume = qty * entry_price
    if actual_volume > result.position_volume * config.MAX_LOT_OVERSHOOT:
        print(f"[open_position] {symbol} {side}: minimum lot yuzunden gercek hacim "
              f"({actual_volume:.2f} USDT) hedefin ({result.position_volume:.2f} USDT) "
              "cok ustunde, islem acilmiyor")
        notify.notify_min_lot_too_large(symbol, side, result.position_volume, actual_volume)
        bot_state.record_system_event("min_lot_too_large", symbol, side)
        return

    position_idx = 1 if side == "long" else 2
    order_side = "Buy" if side == "long" else "Sell"

    # Emir gonderme adimlari kendi try/except'i icinde: bir emrin
    # reddedilmesi ana donguye yukselip YANLISLIKLA "baglanti koptu"
    # olarak bildirilmesin.
    try:
        client.set_leverage(symbol, result.applied_leverage)
        client.open_market_position(symbol, order_side, qty, position_idx)
    except Exception as e:
        print(f"[open_position] {symbol} {side} acilirken emir hatasi: {e}")
        return

    # Pozisyon ACILDI. Guvenlik SL'si basarisiz olursa pozisyon yine de
    # kayda alinir (bot onu sabit lose exit ile takip eder) ve uyari gider.
    sl_ok = False
    for attempt in range(2):
        try:
            client.set_stop_loss(symbol, result.sl_price, position_idx)
            sl_ok = True
            break
        except Exception as e:
            print(f"[open_position] {symbol} {side} SL konulamadi (deneme {attempt + 1}): {e}")
            time.sleep(0.5)

    pos = state_module.Position(
        symbol=symbol, side=side, position_idx=position_idx,
        entry_price=entry_price, sl_price=result.sl_price, lose_exit_price=result.lose_exit_price,
        leverage=result.applied_leverage, allocated_amount=result.allocated_amount, qty=qty,
        band_distance_at_entry=result.tp_distance,
        opposite_band_at_entry=result.tp_price,
        entry_lose_exit_percent=result.risk_percent,
        leverage_was_capped=result.leverage_was_capped,
    )
    bot_state.add_position(pos)

    if not sl_ok:
        notify.notify_stop_loss_failed(symbol, side, result.sl_price)

    notify.notify_position_opened(
        symbol, side, entry_price, result.tp_price, result.risk_line_price,
        result.lose_exit_price, result.sl_price, result.applied_leverage,
        result.allocated_amount, result.position_volume,
    )
