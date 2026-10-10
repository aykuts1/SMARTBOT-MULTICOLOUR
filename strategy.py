# -*- coding: utf-8 -*-
"""
strategy.py
---------------------
Botun beyni: Q-Trend cizgileriyle giris/cikis, pozisyon acma/kapama,
Stop Loss yonetimi, borsayla iki yonlu senkronizasyon.

STRATEJI:
  - GIRIS: Fiyat Silver cizgisine degerse LONG, Gold cizgisine degerse SHORT.
  - CIKIS (hangisi once olursa):
      1) Kar Alma : ana cizgi (TP) - CANLI, anlik fiyatla her saniye kontrol edilir.
      2) Stop Loss: borsada GERCEK bir emir. Seviyesi, giris ile Bybit'in
         verdigi LIKIT fiyati arasi mesafenin %80'indedir
         (config.STOP_PLACEMENT_FRACTION). Capraz marjda likit fiyati
         degistigi icin bot, her dakika (reconcile ile birlikte) stop'u
         yeni seviyeye tasir. Likit fiyati bos gelirse stop konamaz ve
         Telegram'dan uyari gider (pozisyon acik kalir).
  - Her coinde ayni anda en fazla 1 islem; toplamda en fazla MAX_OPEN_POSITIONS.
  - Ayni mumda birden fazla islem acilip kapanabilir (mum basina islem siniri yok).

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
    """(bos marj, cuzdan bakiyesi): cuzdan bakiyesi - su an acik pozisyonlar
    icin ayrilmis stake'ler. Bakiye, acik islemlerdeki gecici kar/zarari
    icermez (bkz. bybit_client.get_wallet_balance)."""
    balance = client.get_wallet_balance()
    used = sum(p.allocated_amount for p in bot_state.all_positions())
    return balance - used, balance


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
# STOP LOSS (likit fiyatina gore)
# ------------------------------------------------------------
def compute_stop_price(side: str, entry_price: float, liq_price: float):
    """Giris ile likit fiyati arasi mesafenin STOP_PLACEMENT_FRACTION'i
    (varsayilan %80) kadar girisin likit tarafina ilerleyen seviye.
      long  : giris > stop > likit
      short : giris < stop < likit
    Likit fiyati girisin yanlis tarafindaysa (veri tutarsiz) None dondurur."""
    if not entry_price or not liq_price:
        return None
    if side == "long" and not (0 < liq_price < entry_price):
        return None
    if side == "short" and not (liq_price > entry_price):
        return None
    return entry_price + (liq_price - entry_price) * config.STOP_PLACEMENT_FRACTION


def _warn_stop_failed(bot_state, pos, reason: str):
    """Stop konamadi / guncellenemedi uyarisini pozisyon basina BIR kez gonderir
    (her dakika ayni mesaj tekrarlanmasin diye)."""
    if pos.sl_warned:
        return
    notify.notify_stop_failed(pos.symbol, pos.side, reason)
    bot_state.update_stop_info(pos.symbol, pos.side, pos.sl_price, pos.liq_price, sl_warned=True)


def sync_stop_for_position(client, bot_state, pos, exch_pos) -> bool:
    """Tek bir pozisyonun Stop Loss'unu, borsadaki guncel likit fiyatina gore
    gerekiyorsa yeni seviyeye tasir. exch_pos: borsadan gelen pozisyon kaydi
    (liqPrice, stopLoss, avgPrice icerir). Basarili / degisiklik gerekmiyorsa
    True, stop konamadiysa False doner."""
    liq = client.parse_price_field(exch_pos.get("liqPrice"))
    cur_sl = client.parse_price_field(exch_pos.get("stopLoss"))
    entry = client.parse_price_field(exch_pos.get("avgPrice")) or pos.entry_price

    if liq is None:
        bot_state.update_stop_info(pos.symbol, pos.side, cur_sl, None)
        _warn_stop_failed(bot_state, pos,
                          "Bybit likit fiyatini vermedi, stop seviyesi hesaplanamadi")
        return False

    target = compute_stop_price(pos.side, entry, liq)
    if target is None:
        bot_state.update_stop_info(pos.symbol, pos.side, cur_sl, liq)
        _warn_stop_failed(bot_state, pos,
                          f"Likit fiyati ({liq}) giris fiyatina ({entry}) gore tutarsiz")
        return False

    target = float(client._format_price(pos.symbol, target))
    tick = client.get_tick_size(pos.symbol)

    # Borsadaki stop zaten istenen seviyedeyse (tick'in yarisindan az fark) dokunma
    if cur_sl is not None and abs(cur_sl - target) < max(tick, 1e-12) * 0.5:
        bot_state.update_stop_info(pos.symbol, pos.side, cur_sl, liq, sl_warned=False)
        return True

    try:
        client.set_stop_loss(pos.symbol, target, pos.position_idx)
    except Exception as e:
        msg = str(e)
        if "not modified" in msg.lower() or "34040" in msg:
            # Bybit: stop zaten bu seviyede - zararsiz
            bot_state.update_stop_info(pos.symbol, pos.side, target, liq, sl_warned=False)
            return True
        print(f"[stop] {pos.symbol} {pos.side} stop ayarlanamadi: {e}")
        bot_state.update_stop_info(pos.symbol, pos.side, cur_sl, liq)
        _warn_stop_failed(bot_state, pos, f"Borsa stop emrini kabul etmedi: {msg[:200]}")
        return False

    bot_state.update_stop_info(pos.symbol, pos.side, target, liq, sl_warned=False)
    return True


def sync_stops(client, bot_state, exchange_by_key: dict):
    """Bot'un takip ettigi ve borsada da acik olan tum pozisyonlarin stop
    seviyesini gunceller. Tek pozisyondaki hata digerlerini durdurmaz."""
    for pos in list(bot_state.all_positions()):
        exch_pos = exchange_by_key.get((pos.symbol, pos.side))
        if exch_pos is None:
            continue
        try:
            sync_stop_for_position(client, bot_state, pos, exch_pos)
        except Exception as e:
            print(f"[stop] {pos.symbol} {pos.side} stop senkronizasyon hatasi: {e}")


def _place_initial_stop(client, bot_state, pos):
    """Pozisyon yeni acildiktan sonra borsadan likit fiyatini okuyup ilk
    stop'u koyar. Bybit likit fiyatini hemen vermeyebilir, bu yuzden birkac
    kez denenir."""
    exch_pos = None
    for _ in range(config.LIQ_FETCH_RETRIES):
        try:
            exch_pos = client.get_position_info(pos.symbol, pos.position_idx)
        except Exception as e:
            print(f"[stop] {pos.symbol} {pos.side} pozisyon bilgisi okunamadi: {e}")
            exch_pos = None
        if exch_pos is not None and client.parse_price_field(exch_pos.get("liqPrice")) is not None:
            break
        time.sleep(config.LIQ_FETCH_WAIT_SECONDS)

    if exch_pos is None:
        _warn_stop_failed(bot_state, pos, "Pozisyon borsadan okunamadi, stop konamadi")
        return
    sync_stop_for_position(client, bot_state, pos, exch_pos)


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


def _build_position_from_exchange(client, p: dict):
    """Tek bir borsa pozisyon kaydindan (get_open_positions sonucu) bir
    Position nesnesi olusturur. Stop ve likit bilgisi borsadan okunur;
    stop sonradan sync_stops ile likit fiyatina gore ayarlanir."""
    symbol = p["symbol"]
    pos_idx = int(p.get("positionIdx", 0))
    side = "long" if pos_idx == 1 else "short"
    entry_price = float(p["avgPrice"])
    qty = float(p["size"])
    leverage = float(p.get("leverage", 0) or 0)
    allocated_amount = (entry_price * qty) / leverage if leverage else 0.0

    return state_module.Position(
        symbol=symbol, side=side, position_idx=pos_idx,
        entry_price=entry_price,
        leverage=leverage, allocated_amount=allocated_amount, qty=qty,
        sl_price=client.parse_price_field(p.get("stopLoss")),
        liq_price=client.parse_price_field(p.get("liqPrice")),
    )


def reconcile_open_positions(client, bot_state):
    """Bot baslarken (main.py) bir kez cagrilir. Diskten (state.py) yuklenmis
    pozisyonlar korunur; diskte olmayip borsada bulunanlar kayda alinir.
    Sonra tum pozisyonlarin stop'u likit fiyatina gore ayarlanir."""
    exchange_by_key = _exchange_positions_by_key(client)

    for (symbol, side), p in exchange_by_key.items():
        if not bot_state.has_position(symbol, side):
            bot_state.add_position(_build_position_from_exchange(client, p))

    # Bot'ta (diskte) kayitli olup artik borsada olmayan pozisyonlar
    # (bot kapaliyken kapanmis olabilir) - kayittan temizle.
    for pos in list(bot_state.all_positions()):
        if (pos.symbol, pos.side) not in exchange_by_key:
            print(f"[reconcile] {pos.symbol} {pos.side}: bot kapaliyken borsada kapanmis, kayittan siliniyor")
            bot_state.remove_position(pos.symbol, pos.side)

    sync_stops(client, bot_state, exchange_by_key)

    for pos in bot_state.all_positions():
        notify.notify_position_found_on_restart(
            pos.symbol, pos.side, pos.entry_price, pos.sl_price, pos.leverage)


# ------------------------------------------------------------
# IKI YONLU RECONCILE (bot calisirken periyodik olarak cagrilir)
# ------------------------------------------------------------
def _classify_external_close(pos, last_price):
    """Borsada kapanmis (bot kapatmamis) bir pozisyonun sebebini ve cikis
    fiyatini tahmin eder: fiyat bizim stop seviyemizin ustundeyse/altindaysa
    borsadaki Stop Loss tetiklenmistir, degilse disaridan (elle) kapatilmistir."""
    if pos.sl_price:
        if pos.side == "long" and last_price <= pos.sl_price * 1.001:
            return "Stop Loss", pos.sl_price
        if pos.side == "short" and last_price >= pos.sl_price * 0.999:
            return "Stop Loss", pos.sl_price
    return "Dış Kapanış", last_price


def reconcile_with_exchange(client, bot_state):
    """main.py icinde RECONCILE_INTERVAL_SECONDS'ta (varsayilan 60sn)
    bir cagrilir. Botun kendi acik pozisyon kayitlarini borsayla IKI
    YONLU karsilastirir:

      1) Bot'ta acik gorunen ama borsada olmayan bir pozisyon varsa
         kapanmis demektir: fiyat stop seviyesindeyse "Stop Loss", degilse
         "Dış Kapanış" olarak islenir.

      2) Borsada acik olan ama bot'un bilmedigi bir pozisyon varsa kayda
         alinir ve uyari gonderilir.

      3) Tum acik pozisyonlarin Stop Loss'u, Bybit'in guncel likit fiyatina
         gore yeniden hesaplanip gerekiyorsa yeni seviyeye tasinir.
    """
    exchange_by_key = _exchange_positions_by_key(client)

    # 1) Bot'ta var, borsada yok -> kapanmis, kayittan sil
    for pos in list(bot_state.all_positions()):
        key = (pos.symbol, pos.side)
        if key in exchange_by_key:
            continue

        try:
            last_price = client.get_last_price(pos.symbol)
        except Exception:
            last_price = pos.entry_price

        reason, exit_price = _classify_external_close(pos, last_price)

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

    # 2) Borsada var, bot'ta yok -> kayda al
    newly_synced = []
    for (symbol, side), p in exchange_by_key.items():
        if bot_state.has_position(symbol, side):
            continue
        pos = _build_position_from_exchange(client, p)
        bot_state.add_position(pos)
        newly_synced.append(pos)

    # 3) Tum pozisyonlarin stop'unu likit fiyatina gore guncelle
    sync_stops(client, bot_state, exchange_by_key)

    for pos in newly_synced:
        cur = bot_state.get_position(pos.symbol, pos.side) or pos
        notify.notify_position_synced_from_exchange(
            cur.symbol, cur.side, cur.entry_price, cur.sl_price, cur.leverage)


# ------------------------------------------------------------
# COIN ISLEME (main.py her saniye, her coin icin cagirir)
# ------------------------------------------------------------
def process_symbol(client, bot_state, symbol, prev_price, last_price):
    base, fresh = _get_base(client, symbol)
    if base is None:
        return

    lv = indicators.live_levels(base["m_prev"], base["atr_prev"], last_price)

    # Once cikis (pozisyon yoksa fonksiyon kendiliginden bir sey yapmaz)
    for side in ("long", "short"):
        check_exits(client, bot_state, symbol, side, last_price, lv)

    # Yeni mum icin taze veri yoksa yeni giris acilmaz
    if not fresh:
        return

    check_entry_signals(client, bot_state, symbol, prev_price, last_price, lv)


# ------------------------------------------------------------
# CIKIS KONTROLU
# ------------------------------------------------------------
def check_exits(client, bot_state, symbol, side, last_price, lv):
    """Kar Alma: CANLI, her saniye kontrol edilir (fiyat >= ana cizgi
    long'da, fiyat <= ana cizgi short'ta). Zarar tarafini borsadaki Stop
    Loss emri korur (bkz. sync_stop_for_position)."""
    pos = bot_state.get_position(symbol, side)
    if not pos:
        return

    if side == "long":
        if last_price >= lv["m"]:
            close_position(client, bot_state, pos, last_price, "Kâr Alma")
    else:
        if last_price <= lv["m"]:
            close_position(client, bot_state, pos, last_price, "Kâr Alma")


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

    # 3) Acilis anindaki TP (ana cizgi)
    tp_price = lv["m"]

    _open_new_position(client, bot_state, symbol, side, last_price, tp_price)


def _open_new_position(client, bot_state, symbol, side, entry_price, tp_price):
    available_margin, wallet_balance = get_available_margin(client, bot_state)
    max_leverage = client.get_max_leverage(symbol)

    result = sizing.calculate_position(
        side=side, entry_price=entry_price, tp_price=tp_price,
        wallet_balance=wallet_balance, max_leverage_for_coin=max_leverage,
    )

    if result is None:
        print(f"[open_position] {symbol} {side}: gecersiz mesafe veya bakiye "
              "(TP yonu uymuyor / stake hesaplanamadi), islem acilmiyor")
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

    pos = state_module.Position(
        symbol=symbol, side=side, position_idx=position_idx,
        entry_price=entry_price,
        leverage=result.applied_leverage, allocated_amount=result.allocated_amount, qty=qty,
        tp_distance_at_entry=result.tp_distance,
        tp_price_at_entry=result.tp_price,
        entry_tp_percent=result.tp_percent,
        leverage_was_capped=result.leverage_was_capped,
    )
    bot_state.add_position(pos)

    # Pozisyon ACILDI: Bybit'ten likit fiyatini okuyup borsaya Stop Loss koy.
    # (Konamazsa uyari gider, pozisyon acik kalir.)
    _place_initial_stop(client, bot_state, pos)
    pos = bot_state.get_position(symbol, side) or pos

    notify.notify_position_opened(
        symbol, side, entry_price, result.tp_price,
        pos.sl_price, pos.liq_price, result.applied_leverage,
        result.allocated_amount, result.position_volume,
    )
