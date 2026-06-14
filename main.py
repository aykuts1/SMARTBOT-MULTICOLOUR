import json
import logging
import signal
import sys
import threading
from pathlib import Path

from bybit_client import BybitClient
from data_feed import DataFeed
from trade_table import RedTable, BlueTable
from telegram_bot import TelegramNotifier
from red_thread import RedThread
from blue_thread import BlueThread
from yellow_thread import YellowThread
from white_thread import WhiteThread
from purple_thread import PurpleThread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


def load_config() -> dict:
    path = Path(__file__).parent / "config.json"
    raw = ""
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.split("//")[0].rstrip()
            if stripped:
                raw += stripped + "\n"
    return json.loads(raw)


class TradeBot:
    def __init__(self):
        self.config = load_config()
        self.client = BybitClient()
        self.feed = DataFeed(self.config, self.client)
        self.telegram = TelegramNotifier(self.config)
        self.balance = 0.0

        self.coin_semaphore = threading.Semaphore(self.config["trading"]["max_open_coins"])
        self.white_semaphore = threading.Semaphore(self.config["white_ecosystem"]["max_open_coins"])

        # Her coin için thread yönetimi
        self.red_threads: dict[str, RedThread] = {}
        self.blue_threads: dict[str, BlueThread] = {}
        self.yellow1_threads: dict[str, YellowThread] = {}
        self.yellow2_threads: dict[str, YellowThread] = {}
        self.white_threads: dict[str, WhiteThread] = {}
        self.purple_threads: dict[str, PurpleThread] = {}

        self._running = False

    # ------------------------------------------------------------------ #
    #  Başlat / Durdur                                                    #
    # ------------------------------------------------------------------ #

    def start(self):
        self._running = True
        self.balance = self.client.get_balance()
        logger.info(f"Bakiye: {self.balance:.2f} USDT")

        if self.balance < 10:
            self.telegram.low_balance(self.balance)
            logger.warning("Yetersiz bakiye, bot durduruluyor.")
            return

        self.feed.start()
        self.telegram.set_stop_callback(self.stop)
        self.telegram.set_start_callback(self.start)
        self.telegram.start_scheduler(self.client.get_balance, self.balance)
        self.telegram.start_command_listener()
        self.telegram.bot_started(self.balance)

        for symbol in self.config["coins"]:
            rt = RedThread(
                symbol=symbol,
                config=self.config,
                client=self.client,
                feed=self.feed,
                balance=self.balance,
                coin_semaphore=self.coin_semaphore,
                telegram=self.telegram,
                on_open_callback=self._on_red_opened,
                on_close_callback=self._on_red_closed,
            )
            self.red_threads[symbol] = rt
            rt.start()

            wt = WhiteThread(
                symbol=symbol,
                config=self.config,
                client=self.client,
                feed=self.feed,
                balance=self.balance,
                coin_semaphore=self.white_semaphore,
                telegram=self.telegram,
                on_open_callback=self._on_white_opened,
                on_close_callback=self._on_white_closed,
            )
            self.white_threads[symbol] = wt
            wt.start()

        logger.info(f"{len(self.config['coins'])} coin için thread'ler başlatıldı.")

        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Ana thread bekle
        signal.pause() if hasattr(signal, "pause") else self._wait()

    def stop(self):
        if not self._running:
            return
        self._running = False
        logger.info("Bot durduruluyor...")

        for rt in self.red_threads.values():
            rt.stop()
        for bt in self.blue_threads.values():
            bt.stop()
        for yt in self.yellow1_threads.values():
            yt.force_stop()
        for yt in self.yellow2_threads.values():
            yt.force_stop()
        for wt in self.white_threads.values():
            wt.stop()
        for pt in self.purple_threads.values():
            pt.stop()

        self.feed.stop()
        self.telegram.stop_scheduler()
        self.telegram.bot_stopped()
        logger.info("Bot durduruldu.")

    # ------------------------------------------------------------------ #
    #  Callback'ler (red thread → blue/yellow başlat)                    #
    # ------------------------------------------------------------------ #

    def _on_red_opened(self, symbol: str, red_table: RedTable, blue_table: BlueTable):
        # Mavi thread
        bt = BlueThread(
            symbol=symbol,
            label="mavi",
            blue_table=blue_table,
            config=self.config,
            client=self.client,
            feed=self.feed,
            balance=self.balance,
            telegram=self.telegram,
        )
        self.blue_threads[symbol] = bt
        bt.start()

        # Sarı 1
        y1 = YellowThread(
            symbol=symbol,
            label="yellow1",
            red_table=red_table,
            config=self.config,
            client=self.client,
            feed=self.feed,
            balance=self.balance,
            telegram=self.telegram,
        )
        self.yellow1_threads[symbol] = y1
        y1.start()

        # Sarı 2
        y2 = YellowThread(
            symbol=symbol,
            label="yellow2",
            red_table=red_table,
            config=self.config,
            client=self.client,
            feed=self.feed,
            balance=self.balance,
            telegram=self.telegram,
        )
        self.yellow2_threads[symbol] = y2
        y2.start()

    def _on_white_opened(self, symbol: str, white_table, purple_table):
        pt = PurpleThread(
            symbol=symbol,
            purple_table=purple_table,
            config=self.config,
            client=self.client,
            feed=self.feed,
            balance=self.balance,
            telegram=self.telegram,
        )
        self.purple_threads[symbol] = pt
        pt.start()

    def _on_white_closed(self, symbol: str, white_table):
        if symbol in self.purple_threads:
            self.purple_threads[symbol].stop()
            del self.purple_threads[symbol]

    def _on_red_closed(self, symbol: str, red_table: RedTable):
        if symbol in self.blue_threads:
            self.blue_threads[symbol].stop()
            del self.blue_threads[symbol]
        # Sarı thread'ler kendi çıkışlarına göre devam eder (stop çağrılmaz)

    # ------------------------------------------------------------------ #
    #  Sinyal / bekleme                                                   #
    # ------------------------------------------------------------------ #

    def _handle_signal(self, signum, frame):
        self.stop()
        sys.exit(0)

    def _wait(self):
        import time
        while self._running:
            time.sleep(1)


if __name__ == "__main__":
    bot = TradeBot()
    bot.start()
