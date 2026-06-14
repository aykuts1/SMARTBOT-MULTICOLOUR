import time
import threading
import logging
from bybit_client import BybitClient
from data_feed import DataFeed
from trade_table import RedTable, YellowTable, BlueTable
from blue_thread import BlueThread

logger = logging.getLogger(__name__)

# Sarı 1 → Alt4/Üst4 (index 3), Zone 3 girişi
# Sarı 2 → Alt6/Üst6 (index 5), Zone 5 girişi
YELLOW_CONFIG = {
    "yellow1": {"entry_band_idx": 3, "trigger_zone": "zone3"},
    "yellow2": {"entry_band_idx": 5, "trigger_zone": "zone5"},
}


class YellowThread:
    """
    Sarı 1 ve Sarı 2 thread'ini yönetir.
    Kırmızı/Yeşil açıkken ilgili zone'a girilince işlem açar.
    Her biri kendi Mavi (Mavi1/Mavi2) thread'ini yönetir.
    """

    def __init__(
        self,
        symbol: str,
        label: str,              # "yellow1" | "yellow2"
        red_table: RedTable,
        config: dict,
        client: BybitClient,
        feed: DataFeed,
        balance: float,
        telegram,
    ):
        self.symbol = symbol
        self.label = label
        self.red_table = red_table
        self.config = config
        self.client = client
        self.feed = feed
        self.balance = balance
        self.telegram = telegram

        self._running = False
        self._thread: threading.Thread | None = None

        self.yellow_table: YellowTable | None = None
        self._open = False
        self._qty = 0.0
        self._entry_price = 0.0
        self._ce_value = 0.0

        self._blue: BlueThread | None = None
        self._blue_label = "mavi1" if label == "yellow1" else "mavi2"

    # ------------------------------------------------------------------ #
    #  Yaşam döngüsü                                                      #
    # ------------------------------------------------------------------ #

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"Yellow-{self.symbol}-{self.label}", daemon=True)
        self._thread.start()

    def stop(self):
        """Kırmızı/Yeşil kapandığında çağrılır. Sarı kendi çıkışlarına göre devam eder, sadece flag temizlenir."""
        # Sarı kırmızı kapanınca KAPANMAZ — kendi çıkışlarını bekler.
        pass

    def force_stop(self):
        """Bot tamamen durduğunda çağrılır."""
        self._running = False
        if self._blue:
            self._blue.stop()

    # ------------------------------------------------------------------ #
    #  Ana döngü                                                           #
    # ------------------------------------------------------------------ #

    def _loop(self):
        prev_price: float | None = None
        cfg = YELLOW_CONFIG[self.label]

        while self._running:
            data = self.feed.get(self.symbol)
            if not data or not data["bands"]:
                time.sleep(0.5)
                continue

            price = data["price"]
            bands = data["bands"]
            ce_data = data["ce"]

            if prev_price is None:
                prev_price = price
                time.sleep(0.5)
                continue

            if not self._open:
                self._check_entry(price, prev_price, bands, cfg)
            else:
                self._check_exit(price, ce_data)

            prev_price = price
            time.sleep(0.5)

    # ------------------------------------------------------------------ #
    #  Giriş                                                              #
    # ------------------------------------------------------------------ #

    def _check_entry(self, price: float, prev: float, bands: dict, cfg: dict):
        rt = self.red_table
        direction = rt.direction
        idx = cfg["entry_band_idx"]

        lower = bands["lower"]
        upper = bands["upper"]

        if direction == "short":
            trigger_level = lower[idx]   # Alt4 veya Alt6
            in_zone = price < trigger_level
            crossed = prev > trigger_level >= price
        else:
            trigger_level = upper[idx]   # Üst4 veya Üst6
            in_zone = price > trigger_level
            crossed = prev < trigger_level <= price

        if crossed and in_zone:
            self._open_trade(direction, bands, idx)

    # ------------------------------------------------------------------ #
    #  İşlem aç                                                           #
    # ------------------------------------------------------------------ #

    def _open_trade(self, direction: str, bands: dict, entry_band_idx: int):
        try:
            qty = self._calc_qty(bands, direction)
            side = "Sell" if direction == "short" else "Buy"
            price = self.feed.get_price(self.symbol) or 0
            sl_pct = self.config["trading"]["sl_pct"]
            sl_price = price * (1 + sl_pct) if direction == "short" else price * (1 - sl_pct)

            result = self.client.place_market_order(self.symbol, side, qty, sl_price)

            self.yellow_table = YellowTable.from_bands(
                symbol=self.symbol,
                direction=direction,
                label=self.label,
                bands=bands,
                entry_band_idx=entry_band_idx,
                qty=qty,
            )
            self._qty = qty
            self._entry_price = price
            self._open = True

            logger.info(f"[{self.symbol}] {self.label} {direction} açıldı")

            self.telegram.trade_opened(
                symbol=self.symbol,
                direction=direction,
                thread=self.label,
                entry_price=price,
                qty=qty,
                sl_price=sl_price,
            )

            # Mavi1 / Mavi2 başlat
            blue_table = BlueTable.from_red_table(
                type("FakeRed", (), {
                    "symbol": self.symbol,
                    "direction": direction,
                    "entry_price": self.yellow_table.entry_price,
                    "lose_exit": self.yellow_table.lose_exit,
                })()
            )
            self._blue = BlueThread(
                symbol=self.symbol,
                label=self._blue_label,
                blue_table=blue_table,
                config=self.config,
                client=self.client,
                feed=self.feed,
                balance=self.balance,
                telegram=self.telegram,
            )
            self._blue.start()

        except Exception as e:
            logger.error(f"[{self.symbol}] {self.label} açma hatası: {e}")
            self.telegram.error(f"{self.label} açma hatası [{self.symbol}]: {e}")

    # ------------------------------------------------------------------ #
    #  Çıkış                                                              #
    # ------------------------------------------------------------------ #

    def _check_exit(self, price: float, ce_data: dict | None):
        t = self.yellow_table
        if t is None:
            return

        if ce_data:
            self._ce_value = ce_data["ce_short"] if t.direction == "short" else ce_data["ce_long"]

        reason = None

        if t.direction == "short":
            if self._ce_value and price >= self._ce_value:
                reason = "CE"
            elif price <= t.winrate:
                reason = "Winrate"
            elif price >= t.lose_exit:
                reason = "Lose Exit"
        else:
            if self._ce_value and price <= self._ce_value:
                reason = "CE"
            elif price >= t.winrate:
                reason = "Winrate"
            elif price <= t.lose_exit:
                reason = "Lose Exit"

        if reason:
            self._close_trade(price, reason)

    # ------------------------------------------------------------------ #
    #  İşlem kapat                                                        #
    # ------------------------------------------------------------------ #

    def _close_trade(self, close_price: float, reason: str):
        t = self.yellow_table
        if t is None:
            return
        try:
            side = "Sell" if t.direction == "short" else "Buy"
            self.client.place_market_close(self.symbol, side, self._qty)
            self.client.cancel_sl(self.symbol)

            pnl = self._calc_pnl(self._entry_price, close_price, self._qty, t.direction)
            pnl_pct = (pnl / (self._qty * self._entry_price / self.config["trading"]["leverage"])) * 100

            logger.info(f"[{self.symbol}] {self.label} kapatıldı — {reason}")

            self.telegram.trade_closed(
                symbol=self.symbol,
                direction=t.direction,
                thread=self.label,
                close_price=close_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
            )

            if self._blue:
                self._blue.stop()
                self._blue = None

        except Exception as e:
            logger.error(f"[{self.symbol}] {self.label} kapatma hatası: {e}")
            self.telegram.error(f"{self.label} kapatma hatası [{self.symbol}]: {e}")
        finally:
            self._open = False
            self.yellow_table = None
            self._running = False

    # ------------------------------------------------------------------ #
    #  Yardımcı                                                           #
    # ------------------------------------------------------------------ #

    def _calc_qty(self, bands: dict, direction: str) -> float:
        price = bands["lower"][1] if direction == "short" else bands["upper"][1]
        notional = self.balance * self.config["trading"]["balance_pct"] * self.config["trading"]["leverage"]
        return round(notional / price, 3)

    @staticmethod
    def _calc_pnl(entry: float, close: float, qty: float, direction: str) -> float:
        if direction == "short":
            return (entry - close) * qty
        return (close - entry) * qty
