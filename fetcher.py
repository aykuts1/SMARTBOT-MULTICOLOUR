"""
SMARTBOT REDBLUE — fetcher.py
Merkezi veri cekici thread.
Her 5 saniyede tum coinler icin kline ve fiyat verisini API'den ceker,
state cache'ine yazar. Diger threadler API'ye gitmek yerine cache'ten okur.
"""

import threading
import time
from datetime import datetime

from state import state
from bybit_client import BybitClient
from telegram_notifier import notifier, msg_error


class FetcherThread(threading.Thread):
    def __init__(self, config: dict, bybit: BybitClient, stop_event: threading.Event):
        super().__init__(daemon=True, name="Fetcher_Thread")
        self.config = config
        self.bybit = bybit
        self.stop_event = stop_event
        self.scan_interval = config["scan"]["interval_seconds"]
        self.timeframe = config["band"]["timeframe"]
        self.coins = config["coins"]["list"]
        # Ayni hata art arda gelirse spam yapmasin diye basit kontrol
        self.last_error_per_coin = {}

    def run(self):
        while not self.stop_event.is_set():
            start = time.time()
            self.fetch_all_coins()
            # Bir sonraki tarama icin bekle (interval - gecen sure)
            elapsed = time.time() - start
            wait_time = max(0, self.scan_interval - elapsed)
            self.stop_event.wait(wait_time)

    def fetch_all_coins(self):
        for coin in self.coins:
            if self.stop_event.is_set():
                return
            try:
                klines = self.bybit.get_klines(coin, self.timeframe, limit=200)
                price = self.bybit.get_price(coin)
                state.set_cached_data(coin, klines, price)
                # Hata cache temizle
                if coin in self.last_error_per_coin:
                    del self.last_error_per_coin[coin]
            except Exception as e:
                # Ayni hata art arda gelirse tekrar bildirme
                err_str = str(e)[:80]
                if self.last_error_per_coin.get(coin) != err_str:
                    notifier.send(msg_error(self.name, coin, "Veri Cekme Hatasi", err_str))
                    self.last_error_per_coin[coin] = err_str
