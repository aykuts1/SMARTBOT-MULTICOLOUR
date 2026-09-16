"""
main.py
-------
Botun giris noktasi. Uc bagimsiz dongu paralel calisir (thread):

  1) candle_close_loop  -> her ~30 saniyede kontrol eder, yeni bir 1 saatlik
     mum kapandiginda: giris sinyali, trend-flip cikisi, renk-flip kar
     kontrolu ve hareketli TP bandi guncellemesi burada yapilir.
  2) risk_loop           -> her 3 saniyede TUM sembollerin fiyatini TEK
     cagriyla ceker; acik pozisyonlar icin Loss Exit ve (hareketli) ALMA TP
     bandi kontrolunu yapar.
  3) command_and_report_loop -> Telegram /rapor ve /pozisyonlar komutlarini
     dinler, 12s/24s/haftalik periyodik ozetleri zamani geldiginde gonderir.

Baslarken state.json, Bybit'teki gercek acik pozisyonlarla karsilastirilip
senkronize edilir (reconcile_positions).
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


def reconcile_positions(exchange: exch.Exchange, state: st.State, telegram: tg.Telegram) -> None:
    """
    Bot her yeniden basladiginda (Railway redeploy, cokme sonrasi vb.)
    state.json'daki kayitli pozisyonlari Bybit'teki GERCEK acik pozisyonlarla
    karsilastirir:
      - Ikisinde de varsa (normal senkron)  -> kayitli bilgiyi (tp_band_price vb.) koru
      - Sadece Bybit'te varsa (yetim)        -> takibe alinir, Telegram'a bildirilir,
                                                 tp_band_price bir sonraki mum
                                                 kapanisina kadar None kalir (Loss Exit
                                                 yine de korur)
      - Sadece state.json'da varsa (hayalet) -> kayittan dusurulur, Telegram'a
                                                 bilgi verilir
    """
    try:
        live = {p["symbol"]: p for p in exchange.get_open_positions()}
    except Exception as e:
        logger.exception("Reconciliation: acik pozisyonlar cekilemedi: %s", e)
        telegram.send_message(f"🔴 Baslangicta Bybit pozisyonlari okunamadi: {e}\n"
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
            merged[symbol] = {
                "symbol": symbol, "side": live_pos["side"],
                "entry_price": live_pos["entry_price"], "qty": live_pos["qty"],
                "margin_usdt": None, "opened_at": time.time(), "tp_band_price": None,
            }
            telegram.send_message(
                f"⚠️ Yetim pozisyon bulundu ve takibe alindi: {symbol} "
                f"({live_pos['side'].upper()}, giris: {live_pos['entry_price']:.6g}). "
                f"TP bandi bir sonraki mum kapanisinda hesaplanacak, Loss Exit hemen aktif."
            )

    for symbol in saved:
        if symbol not in live:
            telegram.send_message(f"ℹ️ {symbol} pozisyonu bot offline iken kapanmis, kayittan dusuruldu.")

    state.replace_all_positions(merged)
    if merged:
        logger.info("Reconciliation tamamlandi: %d acik pozisyon senkronize edildi.", len(merged))


def candle_close_loop(exchange: exch.Exchange, state: st.State, slots: pm.SlotManager,
                       telegram: tg.Telegram, cfg: dict) -> None:
    last_seen_start: dict[str, int] = {}

    while True:
        for symbol in cfg["symbols"]:
            try:
                df = exchange.get_klines(symbol, limit=cfg["kline_history_limit"])
                if len(df) < cfg["ema_slow_length"] + 5:
                    continue

                newest_start = int(df["start"].iloc[-1])
                if last_seen_start.get(symbol) == newest_start:
                    continue  # yeni mum kapanmamis
                last_seen_start[symbol] = newest_start

                out = ind.compute_all(df, cfg)
                closed_row = out.iloc[-2]  # -1 = hala olusan mum, -2 = SON KAPANAN mum

                position = state.get_position(symbol)

                if position is not None:
                    current_price = exchange.get_last_price(symbol)
                    reason = None
                    if sig.check_trend_flip_exit(position["side"], closed_row["trend"]):
                        reason = "trend_flip"
                    elif sig.check_color_flip_exit(position["side"], closed_row["ha_color"],
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
                    side = sig.check_entry_signal(closed_row)
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
                response = reports.handle_command(command, state, exchange)
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

    telegram.send_message(f"🤖 Bot baslatildi. Takip edilen {len(cfg['symbols'])} coin, "
                           f"kaldirac {cfg['leverage']}x, max {cfg['max_positions']} pozisyon.")

    reconcile_positions(exchange, state, telegram)
    for symbol in state.all_positions():
        slots.register_open(symbol)

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
