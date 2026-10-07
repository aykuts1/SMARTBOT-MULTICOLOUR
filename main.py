# -*- coding: utf-8 -*-
"""
main.py
-----------------
FAYTTREND botunu baslatan dosya. Calistirmak icin:

    python main.py

Once .env dosyasini doldurmayi unutma (.env.example'a bak).

Ana dongu her saniye: tum coinlerin fiyatini TEK istekle ceker, saat
basinda mumlari paralel yeniler, sonra her coin icin Q-Trend cizgilerine
gore cikis ve giris kontrolu yapar. Tek bir coinin hatasi diger coinleri
durdurmaz.
"""

import time
from datetime import datetime

import config
from bybit_client import BybitClient
from state import BotState
import strategy
import telegram_notifier as notify
from telegram_bot import ReportBuilder, TelegramCommandListener, PeriodicReportScheduler


def _validate_coin_list(client):
    """config.COINS icindeki sembolleri Bybit'in canli listesiyle
    karsilastirir; bulunmayanlari listeden cikarir ve haber verir.
    Liste YERINDE degistirilir (diger dosyalardaki config.COINS referanslari
    da guncel kalsin diye)."""
    try:
        tradable = client.get_tradable_symbols()
    except Exception as e:
        print(f"[main] Sembol listesi dogrulanamadi, liste oldugu gibi kullaniliyor: {e}")
        return
    if not tradable:
        print("[main] Bybit sembol listesi bos geldi, liste oldugu gibi kullaniliyor")
        return
    missing = [c for c in config.COINS if c not in tradable]
    if missing:
        print(f"[main] Bybit'te bulunamayan coinler listeden cikarildi: {missing}")
        config.COINS[:] = [c for c in config.COINS if c in tradable]
        notify.notify_symbols_missing(missing)


def main():
    print("FAYTTREND (Q-Trend) baslatiliyor...")
    client = BybitClient()
    bot_state = BotState()

    # 1) Hesap ayarlarini garanti et (hedge modu, cross margin)
    client.setup_account()

    # 2) Coin listesini Bybit'le dogrula
    _validate_coin_list(client)

    # 3) Yeniden baslatma - acik pozisyonlari tani
    strategy.reconcile_open_positions(client, bot_state)

    # 4) Baslangic bildirimini gonder + ilk equity anlik goruntusu
    try:
        equity = client.get_total_equity()
    except Exception as e:
        print(f"[main] Baslangic bakiyesi alinamadi: {e}")
        equity = 0.0
    notify.notify_bot_started(equity)
    bot_state.record_equity_snapshot(equity)

    # 5) Telegram komut dinleyici ve periyodik rapor zamanlayici baslat
    stop_flag_holder = {"stop": False}
    start_equity_holder = {"value": equity}
    report_builder = ReportBuilder(bot_state, client, start_equity_holder)

    cmd_listener = TelegramCommandListener(report_builder, stop_flag_holder)
    cmd_listener.start()

    report_scheduler = PeriodicReportScheduler(report_builder, stop_flag_holder)
    report_scheduler.start()

    # 6) Ana dongu
    prev_prices = {}

    connection_lost = False
    last_success_time = time.time()
    last_reconcile_time = time.time()
    last_equity_snapshot_time = time.time()
    last_kline_warn_time = 0.0

    print(f"Bot aktif, {len(config.COINS)} coin taraniyor, dongu basliyor.")
    while not stop_flag_holder["stop"]:
        loop_start = time.time()
        try:
            # Tum coinlerin son fiyati - TEK istek
            prices = client.get_all_last_prices()

            # Yeni mum dilimi basladiysa mumlari paralel yenile
            failed = client.refresh_klines(config.COINS)
            if failed and time.time() - last_kline_warn_time > 30:
                last_kline_warn_time = time.time()
                print(f"[main] Mumu henuz hazir olmayan coinler ({len(failed)}): "
                      f"{', '.join(s.replace('USDT', '') for s in failed)}")

            for symbol in list(config.COINS):
                price = prices.get(symbol)
                if price is None:
                    continue
                try:
                    strategy.process_symbol(client, bot_state, symbol,
                                            prev_prices.get(symbol), price)
                except Exception as e:
                    # Tek coinin hatasi digerlerini durdurmasin
                    print(f"[main] {symbol} islenirken hata: {e}")
                prev_prices[symbol] = price

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
