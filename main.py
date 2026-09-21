# -*- coding: utf-8 -*-
"""
main.py
-------
Botu baslatan dosya. Calistirmak icin:

    python main.py

Once .env dosyasini doldurmayi unutma (.env.example'a bak).
"""

import time
from datetime import datetime

import config
from bybit_client import BybitClient
from state import BotState
import strategy
import telegram_notifier as notify
from telegram_bot import ReportBuilder, TelegramCommandListener, PeriodicReportScheduler


def main():
    print("Bot baslatiliyor...")
    client = BybitClient()
    bot_state = BotState()

    # 1) Hesap ayarlarini garanti et (hedge modu, cross margin)
    client.setup_account()

    # 2) Yeniden baslatma - acik pozisyonlari tani
    strategy.reconcile_open_positions(client, bot_state)

    # 3) Baslangic bildirimini gonder
    try:
        equity = client.get_total_equity()
    except Exception as e:
        print(f"[main] Baslangic bakiyesi alinamadi: {e}")
        equity = 0.0
    notify.notify_bot_started(equity)

    # 4) Telegram komut dinleyici ve periyodik rapor zamanlayici baslat
    stop_flag_holder = {"stop": False}
    start_equity_holder = {"value": equity}
    report_builder = ReportBuilder(bot_state, client, start_equity_holder)

    cmd_listener = TelegramCommandListener(report_builder, stop_flag_holder)
    cmd_listener.start()

    report_scheduler = PeriodicReportScheduler(report_builder, stop_flag_holder)
    report_scheduler.start()

    # 5) Ana dongu
    prev_prices = {symbol: None for symbol in config.COINS}
    indicator_cache = {}       # symbol -> gosterge hesaplanmis dataframe
    last_indicator_refresh = {symbol: 0.0 for symbol in config.COINS}
    connection_lost = False
    last_success_time = time.time()
    reconcile_counter = 0

    print("Bot aktif, dongu basliyor.")
    while not stop_flag_holder["stop"]:
        loop_start = time.time()
        try:
            for symbol in config.COINS:
                # Agir istek (300 mum cekme + gosterge hesaplama): sadece
                # INDICATOR_REFRESH_SECONDS'te bir yenilenir.
                now = time.time()
                needs_refresh = (
                    symbol not in indicator_cache
                    or now - last_indicator_refresh[symbol] >= config.INDICATOR_REFRESH_SECONDS
                )
                if needs_refresh:
                    indicator_cache[symbol] = strategy.compute_indicators_for_symbol(client, symbol)
                    last_indicator_refresh[symbol] = now
                df = indicator_cache[symbol]

                # Hafif istek (tek fiyat): her saniye - "fiyat degdi mi" tetigi icin
                last_price = client.get_last_price(symbol)

                strategy.check_entry(client, bot_state, symbol, df, prev_prices[symbol], last_price)
                strategy.check_exit(client, bot_state, symbol, df, last_price)

                prev_prices[symbol] = last_price

            # Her 5 saniyede bir, borsadaki gercek SL'in tetiklenip
            # tetiklenmedigini kontrol et (bot kacirdiysa diye)
            reconcile_counter += 1
            if reconcile_counter >= 5:
                strategy.reconcile_externally_closed(client, bot_state)
                reconcile_counter = 0

            if connection_lost:
                downtime = time.time() - last_success_time
                notify.notify_connection_restored(downtime)
                connection_lost = False
            last_success_time = time.time()

        except Exception as e:
            print(f"[main] Dongu hatasi: {e}")
            if not connection_lost:
                last_success_str = datetime.fromtimestamp(last_success_time).strftime("%d.%m.%Y %H:%M:%S")
                notify.notify_connection_lost(last_success_str)
                connection_lost = True

        elapsed = time.time() - loop_start
        sleep_time = max(0.0, config.POLL_INTERVAL_SECONDS - elapsed)
        time.sleep(sleep_time)

    print("Bot durduruldu (/dur komutu alindi).")


if __name__ == "__main__":
    main()
