# -*- coding: utf-8 -*-
"""
fayttrend_main.py
-----------------
FAYTTREND botunu baslatan dosya. Calistirmak icin:

    python fayttrend_main.py

Once .env dosyasini doldurmayi unutma (.env.example'a bak).

Ana dongu her saniye, her coin icin: bantlari hesaplar, lose exit
kontrolu yapar, sonra alt/ust banda degme sinyaline bakar.
"""

import time
from datetime import datetime

import fayttrend_config as config
from fayttrend_bybit_client import BybitClient
from fayttrend_state import BotState
import fayttrend_strategy as strategy
import fayttrend_telegram_notifier as notify
from fayttrend_telegram_bot import ReportBuilder, TelegramCommandListener, PeriodicReportScheduler


def main():
    print("FAYTTREND baslatiliyor...")
    client = BybitClient()
    bot_state = BotState()

    # 1) Hesap ayarlarini garanti et (hedge modu, cross margin)
    client.setup_account()

    # 2) Yeniden baslatma - acik pozisyonlari tani
    strategy.reconcile_open_positions(client, bot_state)

    # 3) Baslangic bildirimini gonder + ilk equity anlik goruntusu
    try:
        equity = client.get_total_equity()
    except Exception as e:
        print(f"[main] Baslangic bakiyesi alinamadi: {e}")
        equity = 0.0
    notify.notify_bot_started(equity)
    bot_state.record_equity_snapshot(equity)

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

    connection_lost = False
    last_success_time = time.time()
    last_reconcile_time = time.time()
    last_equity_snapshot_time = time.time()

    print("Bot aktif, dongu basliyor.")
    while not stop_flag_holder["stop"]:
        loop_start = time.time()
        try:
            for symbol in config.COINS:
                df = strategy.compute_indicators_for_symbol(client, symbol)
                last_price = float(df.iloc[-1]["close"])

                # Lose exit kontrolu: coin basina hem long hem short slotu icin
                # (pozisyon yoksa fonksiyon kendiliginden hicbir sey yapmaz).
                for side in ("long", "short"):
                    strategy.check_lose_exit(client, bot_state, symbol, side, prev_prices[symbol], last_price)

                # Bant sinyali: alt banda degdi -> long, ust banda degdi -> short
                # (karsi yondeki pozisyon kapatilir).
                strategy.check_band_signals(client, bot_state, symbol, df, prev_prices[symbol], last_price)

                prev_prices[symbol] = last_price

            # Botun kendi acik pozisyon kayitlarini borsayla periyodik
            # olarak IKI YONLU karsilastir
            if time.time() - last_reconcile_time >= config.RECONCILE_INTERVAL_SECONDS:
                strategy.reconcile_with_exchange(client, bot_state)
                last_reconcile_time = time.time()

            # Varlik (equity) anlik goruntusunu periyodik kaydet
            if time.time() - last_equity_snapshot_time >= config.EQUITY_SNAPSHOT_INTERVAL_SECONDS:
                try:
                    equity_now = client.get_total_equity()
                    bot_state.record_equity_snapshot(equity_now)
                except Exception as e:
                    print(f"[main] Equity anlik goruntusu alinamadi: {e}")
                last_equity_snapshot_time = time.time()

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
