# -*- coding: utf-8 -*-
"""
main.py
-------
Botu baslatan dosya. Calistirmak icin:

    python main.py

Once .env dosyasini doldurmayi unutma (.env.example'a bak).

KOKLU GUNCELLEME: Ana donguye ek parcalar eklendi:
  1) "Mum yeni kapandi mi?" tespiti - trend donusu cikisi SADECE bu anda
     kontrol edilir (fiyat girisi/TP/lose exit hala her saniye kontrol edilir).
  2) Periyodik varlik (equity) anlik goruntusu kaydi - detayli raporlarin
     (X/12s-24s once varlik, gun ici en yuksek/dusuk, drawdown) dayandigi
     gecmis buradan besleniyor.
  3) Periyodik iki-yonlu reconcile (RECONCILE_INTERVAL_SECONDS, varsayilan
     60sn) - botun acik pozisyon kayitlari borsayla karsilastirilir.
"""

import time
from datetime import datetime

import config
from bybit_client import BybitClient
from state import BotState
import strategy
import telegram_notifier as notify
from telegram_bot import ReportBuilder, TelegramCommandListener, PeriodicReportScheduler


def _current_candle_bucket() -> int:
    """Suanki 'mum dilimi' numarasi (bkz. bybit_client._current_kline_bucket
    ile ayni mantik) - bu sayi degistiginde bir onceki mum kapanmis demektir."""
    interval_seconds = int(config.KLINE_INTERVAL) * 60
    return int(time.time() // interval_seconds)


def main():
    print("Bot baslatiliyor...")
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
    confirmed_trend = {}  # sembol -> son KAPANMIS mumun trend degeri
    prev_bucket = _current_candle_bucket()

    connection_lost = False
    last_success_time = time.time()
    last_reconcile_time = time.time()
    last_equity_snapshot_time = time.time()

    print("Bot aktif, dongu basliyor.")
    while not stop_flag_holder["stop"]:
        loop_start = time.time()
        try:
            current_bucket = _current_candle_bucket()
            candle_just_closed = current_bucket != prev_bucket

            for symbol in config.COINS:
                df = strategy.compute_indicators_for_symbol(client, symbol)
                last_price = float(df.iloc[-1]["close"])

                if symbol not in confirmed_trend:
                    # Ilk dongu - baslangic referans degeri
                    confirmed_trend[symbol] = strategy.get_confirmed_trend(df)

                # Giris, TP ve lose exit kontrolu: her saniye, anlik fiyatla
                strategy.check_entry(client, bot_state, symbol, df, prev_prices[symbol], last_price)
                strategy.check_exit(client, bot_state, symbol, df, prev_prices[symbol], last_price)
                strategy.check_lose_exit(client, bot_state, symbol, prev_prices[symbol], last_price)

                # Trend donusu kontrolu: SADECE mum yeni kapandiysa
                if candle_just_closed:
                    new_trend = strategy.get_confirmed_trend(df)
                    if new_trend != confirmed_trend[symbol]:
                        strategy.check_trend_flip_exit(client, bot_state, symbol, new_trend, last_price)
                    confirmed_trend[symbol] = new_trend

                prev_prices[symbol] = last_price

            prev_bucket = current_bucket

            # Botun kendi acik pozisyon kayitlarini borsayla periyodik
            # olarak IKI YONLU karsilastir (bkz. RECONCILE_INTERVAL_SECONDS)
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
