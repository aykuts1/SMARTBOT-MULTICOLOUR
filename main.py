"""
main.py
-------
Botun giris noktasi. Uc bagimsiz dongu paralel calisir (thread):

  1) candle_close_loop  -> her ~30 saniyede kontrol eder, yeni bir 1 saatlik
     mum kapandiginda: giris sinyali, ters-sinyal (piyasa sartlari tamamen
     degisti -> kapat+ters yonde ac) kontrolu, trend-flip cikisi, T3
     renk-flip kar kontrolu, mum-kapanis-zarar kontrolu ve hareketli TP
     bandi guncellemesi burada yapilir. Ayrica bu dongu, her tam mum-kapanis
     turunda kendi kayitlarini (state.json) Bybit'teki gercek acik
     pozisyonlarla IKI YONLU senkronize eder (bkz. sync_with_exchange).
  2) risk_loop           -> her 3 saniyede TUM sembollerin fiyatini TEK
     cagriyla ceker; acik pozisyonlar icin Loss Exit ve (hareketli) ALMA TP
     bandi kontrolunu yapar.
  3) command_and_report_loop -> Telegram /rapor ve /pozisyonlar komutlarini
     dinler, 12s/24s/haftalik periyodik ozetleri zamani geldiginde gonderir.

Baslarken state.json, Bybit'teki gercek acik pozisyonlarla karsilastirilip
senkronize edilir (sync_with_exchange, is_startup=True).
"""

import logging
import threading
import time

import config as cfgmod
import exchange as exch
import indicators as ind
import position_manager as pm
import reports
import signals as sig
import state as st
import telegram_notify as tg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")


def sync_with_exchange(exchange: exch.Exchange, state: st.State, telegram: tg.Telegram,
                        cfg: dict, slots: "pm.SlotManager | None" = None,
                        is_startup: bool = False) -> None:
    """
    Kendi kayitlarimizi (state.json) Bybit'teki GERCEK acik pozisyonlarla IKI
    YONLU senkronize eder:
      - Ikisinde de varsa (normal senkron)   -> kayitli bilgiyi (tp_band_price vb.) koru,
                                                 qty/entry_price'i canli veriyle guncelle
      - Sadece Bybit'te varsa (yetim)        -> takibe alinir, Telegram'a bildirilir,
                                                 tp_band_price bir sonraki mum
                                                 kapanisina kadar None kalir (Loss Exit
                                                 yine de korur). margin_usdt, cfg'deki
                                                 kaldirac kullanilarak TAHMIN EDILIR
                                                 (qty * entry_price / leverage) -- bos
                                                 birakilmiyor, cunku bu deger daha sonra
                                                 pozisyon kapatilirken kar/zarar
                                                 hesaplamak icin gerekli.
      - Sadece state.json'da varsa (hayalet) -> kayittan dusurulur, slot'tan
                                                 dusurulur, Telegram'a "dis etkenle
                                                 kapandi" bilgisi verilir.

    is_startup=True: bot yeni baslarken (Railway redeploy, cokme sonrasi vb.) cagirilir.
    is_startup=False: candle_close_loop icinden, her tam mum-kapanis turunde cagirilir --
                       boylece bot calisirken de (kullanici elle kapatti / borsa
                       likide etti / borsada elle acildi gibi durumlarda) kendini
                       borsayla senkron tutar.

    slots verilirse, SlotManager de bu senkronizasyona gore guncellenir (eklenen/
    dusen sembollere gore register_open/register_close cagrilir).
    """
    try:
        live = {p["symbol"]: p for p in exchange.get_open_positions()}
    except Exception as e:
        logger.exception("Senkronizasyon: acik pozisyonlar cekilemedi: %s", e)
        telegram.send_message(f"🔴 Bybit pozisyonlari okunamadi: {e}\n"
                                f"Bot state.json'daki kayitli bilgiyle devam ediyor, "
                                f"lutfen manuel kontrol et.")
        return

    saved = state.all_positions()
    merged = {}

    for symbol, live_pos in live.items():
        if symbol in saved:
            merged[symbol] = {**saved[symbol], "qty": live_pos["qty"],
                               "entry_price": live_pos["entry_price"]}
        else:
            # yetim pozisyon -- margin_usdt'yi bos birakmak yerine, botun her
            # zaman ayni config kaldiracini kullandigi varsayimiyla tahmin ediyoruz.
            estimated_margin = (live_pos["qty"] * live_pos["entry_price"]) / cfg["leverage"]
            merged[symbol] = {
                "symbol": symbol, "side": live_pos["side"],
                "entry_price": live_pos["entry_price"], "qty": live_pos["qty"],
                "margin_usdt": estimated_margin, "opened_at": time.time(), "tp_band_price": None,
            }
            telegram.send_message(
                f"⚠️ Yetim pozisyon bulundu ve takibe alindi: {symbol} "
                f"({live_pos['side'].upper()}, giris: {live_pos['entry_price']:.6g}). "
                f"TP bandi bir sonraki mum kapanisinda hesaplanacak, Loss Exit hemen aktif."
            )

    for symbol in saved:
        if symbol not in live:
            if is_startup:
                telegram.send_message(f"ℹ️ {symbol} pozisyonu bot offline iken kapanmis, kayittan dusuruldu.")
            else:
                telegram.send_message(f"ℹ️ {symbol} pozisyonu dis etkenle kapanmis (manuel/borsa), kayittan dusuruldu.")

    state.replace_all_positions(merged)

    if slots is not None:
        for symbol in merged:
            slots.register_open(symbol)
        for symbol in saved:
            if symbol not in merged:
                slots.register_close(symbol)

    if merged or saved:
        logger.info("Senkronizasyon tamamlandi: %d acik pozisyon.", len(merged))


def candle_close_loop(exchange: exch.Exchange, state: st.State, slots: pm.SlotManager,
                       telegram: tg.Telegram, cfg: dict) -> None:
    last_seen_start: dict[str, int] = {}

    while True:
        any_new_candle = False

        for symbol in cfg["symbols"]:
            try:
                df = exchange.get_klines(symbol, limit=cfg["kline_history_limit"])
                if len(df) < cfg["ema_slow_length"] + 5:
                    continue

                newest_start = int(df["start"].iloc[-1])

                # Bu sembolu bu bot calismasinda ILK KEZ goruyoruz -- yani su an
                # (bot yeni baslatilmis/redeploy edilmis olabilir, saatin ortasinda
                # olabiliriz). Bu durumda "yeni mum kapandi" varsayip hemen sinyal
                # degerlendirmesi YAPMIYORUZ -- sadece referans olarak kaydediyoruz.
                # Gercek giris/cikis degerlendirmesi ancak BIR SONRAKI gercek mum
                # kapanisinda (newest_start bu kayitli degerden farklilastiginda)
                # baslar.
                first_seen = symbol not in last_seen_start

                if last_seen_start.get(symbol) == newest_start:
                    continue  # yeni mum kapanmamis
                last_seen_start[symbol] = newest_start

                if first_seen:
                    continue  # ilk gorulen mum -- bu bir "kapanis olayi" degil, sadece baslangic referansi

                any_new_candle = True

                out = ind.compute_all(df, cfg)
                closed_row = out.iloc[-2]  # -1 = hala olusan mum, -2 = SON KAPANAN mum

                position = state.get_position(symbol)
                reverse_side = None  # ters-sinyal tetiklendiyse hangi yonde yeniden acilacagini tasir

                if position is not None:
                    current_price = exchange.get_last_price(symbol)
                    reason = None

                    # ONCELIKLI kontrol: piyasa sartlari tamamen degisti mi?
                    # (acik pozisyonun TAM TERSI yonde tam bir giris sinyali olustu mu)
                    # Bu, diger cikis kurallarinin tetiklenmesini beklemeden tek
                    # basina kapatma nedenidir.
                    triggered_reverse = sig.check_reverse_signal(position["side"], closed_row)
                    if triggered_reverse is not None:
                        reason = "reverse_signal"
                        reverse_side = triggered_reverse
                    elif sig.check_trend_flip_exit(position["side"], closed_row["trend"]):
                        reason = "trend_flip"
                    elif sig.check_candle_close_loss_exit(position["side"], position["entry_price"],
                                                           closed_row["close"], cfg["candle_close_loss_pct"]):
                        reason = "candle_close_loss"
                    elif sig.check_color_flip_exit(position["side"], closed_row["t3_color"],
                                                    position["entry_price"], current_price,
                                                    cfg["profit_threshold_pct"]):
                        reason = "color_flip_profit"

                    if reason:
                        pm.close_position(exchange, state, symbol, reason, current_price, telegram.notify)
                        slots.register_close(symbol)
                        position = None  # ayni mumda ters yon sarti varsa hemen giris icin
                    else:
                        pm.update_tp_band(state, symbol, closed_row, cfg)

                if position is None:
                    # ters-sinyal kapatmasi zaten hangi yone acilacagini biliyor;
                    # aksi halde normal giris sinyaline bakiliyor
                    side = reverse_side if reverse_side is not None else sig.check_entry_signal(closed_row)
                    if side is not None:
                        if slots.can_open(symbol):
                            new_pos = pm.open_position(exchange, state, cfg, symbol, side,
                                                        closed_row, telegram.notify)
                            if new_pos is not None:
                                slots.register_open(symbol)
                        else:
                            telegram.notify("slot_full", symbol=symbol, count=slots.count(),
                                             max_total=slots.max_total)

            except Exception as e:
                logger.exception("candle_close_loop hata (%s): %s", symbol, e)

        # bu turda en az bir sembolun mumu gercekten kapandiysa, kendi kayitlarimizi
        # Bybit'teki gercek acik pozisyonlarla iki yonlu senkronize et
        if any_new_candle:
            try:
                sync_with_exchange(exchange, state, telegram, cfg, slots=slots, is_startup=False)
            except Exception as e:
                logger.exception("candle_close_loop: senkronizasyon hata: %s", e)

        time.sleep(30)


def risk_loop(exchange: exch.Exchange, state: st.State, slots: pm.SlotManager,
              telegram: tg.Telegram, cfg: dict) -> None:
    while True:
        try:
            positions = state.all_positions()
            if positions:
                prices = exchange.get_all_tickers()

                for symbol, position in positions.items():
                    current_price = prices.get(symbol)
                    if current_price is None:
                        continue

                    if sig.check_loss_exit(position["side"], position["entry_price"],
                                            current_price, cfg["loss_exit_pct"]):
                        pm.close_position(exchange, state, symbol, "loss_exit",
                                           current_price, telegram.notify)
                        slots.register_close(symbol)
                        continue

                    band = position.get("tp_band_price")
                    if band is not None and sig.check_tp_exit(position["side"], current_price, band,
                                                                position["entry_price"],
                                                                cfg["profit_threshold_pct"]):
                        pm.close_position(exchange, state, symbol, "take_profit",
                                           current_price, telegram.notify)
                        slots.register_close(symbol)

        except Exception as e:
            logger.exception("risk_loop hata: %s", e)

        time.sleep(cfg["price_poll_seconds"])


def command_and_report_loop(exchange: exch.Exchange, state: st.State,
                             telegram: tg.Telegram, cfg: dict) -> None:
    while True:
        try:
            for command in telegram.get_new_commands():
                response = reports.handle_command(command, state, cfg, exchange)
                if response:
                    telegram.send_message(response)

            now = time.time()
            _maybe_send_periodic(state, telegram, "12h", cfg["report_12h_hours"], now)
            _maybe_send_periodic(state, telegram, "24h", cfg["report_24h_hours"], now)
            _maybe_send_periodic(state, telegram, "weekly", cfg["report_weekly_hours"], now)

        except Exception as e:
            logger.exception("command_and_report_loop hata: %s", e)

        time.sleep(15)


def _maybe_send_periodic(state: st.State, telegram: tg.Telegram, key: str, hours: float, now: float) -> None:
    last = state.get_last_report_time(key)
    if last is None:
        state.set_last_report_time(key, now)  # ilk aciliste hemen ozet atma, sadece referans al
        return
    if now - last >= hours * 3600:
        telegram.send_message(reports.build_period_summary(state, hours))
        state.set_last_report_time(key, now)


def main() -> None:
    cfg = cfgmod.load_config()
    exchange = exch.Exchange()
    state = st.State("state.json")
    telegram = tg.Telegram()
    slots = pm.SlotManager(max_total=cfg["max_positions"])

    try:
        starting_balance = exchange.get_available_balance()
    except Exception as e:
        logger.warning("Baslangic bakiyesi cekilemedi: %s", e)
        starting_balance = None

    telegram.notify(
        "bot_started",
        symbol_count=len(cfg["symbols"]),
        balance=starting_balance,
        leverage=cfg["leverage"],
        max_positions=cfg["max_positions"],
        position_size_pct=cfg["position_size_pct"],
        loss_exit_pct=cfg["loss_exit_pct"],
        profit_threshold_pct=cfg["profit_threshold_pct"],
    )

    sync_with_exchange(exchange, state, telegram, cfg, slots=slots, is_startup=True)

    threads = [
        threading.Thread(target=candle_close_loop, args=(exchange, state, slots, telegram, cfg),
                          daemon=True, name="candle_close_loop"),
        threading.Thread(target=risk_loop, args=(exchange, state, slots, telegram, cfg),
                          daemon=True, name="risk_loop"),
        threading.Thread(target=command_and_report_loop, args=(exchange, state, telegram, cfg),
                          daemon=True, name="command_and_report_loop"),
    ]
    for t in threads:
        t.start()

    logger.info("Bot calisiyor. 3 thread aktif: %s", [t.name for t in threads])

    try:
        while True:
            time.sleep(60)
            for t in threads:
                if not t.is_alive():
                    logger.error("Thread durdu: %s", t.name)
                    telegram.send_message(f"🔴 Kritik: {t.name} thread'i durdu, bot yeniden baslatilmali.")
    except KeyboardInterrupt:
        logger.info("Kapatiliyor...")


if __name__ == "__main__":
    main()
