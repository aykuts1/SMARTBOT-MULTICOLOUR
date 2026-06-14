import time
import threading
import logging
from bybit_client import BybitClient
from data_feed import DataFeed
from trade_table import BlueTable, RedTable

logger = logging.getLogger(__name__)


class BlueThread:
    """
    Mavi hedge thread.
    Kırmızı/Yeşil açıldığında oluşur ve hedge tablosunu izler.
    label: "mavi" | "mavi1" | "mavi2"  (sarı1/sarı2 için ayrı örnekler)
    """

    def __init__(
        self,
        symbol: str,
        label: str,
        blue_table: BlueTable,
        config: dict,
        client: BybitClient,
        feed: DataFeed,
        balance: float,
        telegram,
    ):
        self.symbol = symbol
        self.label = label
        self.table = blue_table
        self.config = config
        self.client = client
        self.feed = feed
        self.balance = balance
        self.telegram = telegram
        self.qty_step = self.client.get_qty_step(self.symbol)

        self._running = False
        self._thread: threading.Thread | None = None
        self._open = False
        self._qty = 0.0
        self._entry_price = 0.0

    # ------------------------------------------------------------------ #
    #  Yaşam döngüsü                                                      #
    # ------------------------------------------------------------------ #

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"Blue-{self.symbol}-{self.label}", daemon=True)
        self._thread.start()

    def stop(self):
        """Bağlı ana işlem kapandığında çağrılır — açık pozisyonu kapatır."""
        self._running = False
        if self._open:
            price = self.feed.get_price(self.symbol) or self._entry_price
            self._close_trade(price, "Bağlı işlem kapandı")

    # ------------------------------------------------------------------ #
    #  Ana döngü                                                           #
    # ------------------------------------------------------------------ #

    def _loop(self):
        prev_price: float | None = None

        while self._running:
            price = self.feed.get_price(self.symbol)
            if price is None:
                time.sleep(0.5)
                continue

            if prev_price is None:
                prev_price = price
                time.sleep(0.5)
                continue

            if not self._open:
                self._check_entry(price)
            else:
                self._check_exit(price)

            prev_price = price
            time.sleep(0.5)

    # ------------------------------------------------------------------ #
    #  Giriş mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_entry(self, price: float):
        t = self.table
        in_zone1 = t.zone1_low <= price <= t.zone1_high

        if t.direction == "long":
            if in_zone1:
                t.flag = True
            if t.flag and price >= t.zone2_low:
                self._open_trade()
        else:
            if in_zone1:
                t.flag = True
            if t.flag and price <= t.zone2_high:
                self._open_trade()

    # ------------------------------------------------------------------ #
    #  İşlem aç                                                           #
    # ------------------------------------------------------------------ #

    def _open_trade(self):
        try:
            qty = self._calc_qty()
            side = "Buy" if self.table.direction == "long" else "Sell"
            price = self.feed.get_price(self.symbol) or 0
            sl_pct = self.config["trading"]["sl_pct"]
            sl_price = price * (1 - sl_pct) if side == "Buy" else price * (1 + sl_pct)

            result = self.client.place_market_order(self.symbol, side, qty, sl_price)
            self._qty = qty
            self._entry_price = price
            self._open = True
            self.table.is_open = True

            logger.info(f"[{self.symbol}] {self.label} {self.table.direction} açıldı")

            self.telegram.trade_opened(
                symbol=self.symbol,
                direction=self.table.direction,
                thread=self.label,
                entry_price=price,
                qty=qty,
                sl_price=sl_price,
            )
        except Exception as e:
            logger.error(f"[{self.symbol}] {self.label} açma hatası: {e}")
            self.telegram.error(f"{self.label} açma hatası [{self.symbol}]: {e}")

    # ------------------------------------------------------------------ #
    #  Çıkış mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_exit(self, price: float):
        t = self.table
        reason = None

        # Lose Exit çizgisine çarpma
        if t.direction == "long" and price >= t.zone4_high:
            reason = "Lose Exit"
        elif t.direction == "short" and price <= t.zone4_low:
            reason = "Lose Exit"

        # Fiyat Zone1'in altına/üstüne çıkma
        if t.direction == "long" and price < t.zone1_low:
            reason = "Zone1 altına düştü"
        elif t.direction == "short" and price > t.zone1_high:
            reason = "Zone1 üstüne çıktı"

        if reason:
            self._close_trade(price, reason)

    # ------------------------------------------------------------------ #
    #  İşlem kapat                                                        #
    # ------------------------------------------------------------------ #

    def _close_trade(self, close_price: float, reason: str):
        if not self._open:
            return
        try:
            side = "Buy" if self.table.direction == "long" else "Sell"
            self.client.place_market_close(self.symbol, side, self._qty)
            self.client.cancel_sl(self.symbol)

            pnl = self._calc_pnl(self._entry_price, close_price, self._qty, self.table.direction)
            pnl_pct = (pnl / (self._qty * self._entry_price / self.config["trading"]["leverage"])) * 100

            logger.info(f"[{self.symbol}] {self.label} kapatıldı — {reason}")

            self.telegram.trade_closed(
                symbol=self.symbol,
                direction=self.table.direction,
                thread=self.label,
                close_price=close_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
            )
        except Exception as e:
            logger.error(f"[{self.symbol}] {self.label} kapatma hatası: {e}")
            self.telegram.error(f"{self.label} kapatma hatası [{self.symbol}]: {e}")
        finally:
            self._open = False
            self._running = False

    # ------------------------------------------------------------------ #
    #  Yardımcı                                                           #
    # ------------------------------------------------------------------ #

    def _calc_qty(self) -> float:
        price = self.feed.get_price(self.symbol) or 1
        notional = self.balance * self.config["trading"]["balance_pct"] * self.config["trading"]["leverage"]
        return self.client.round_qty(notional / price, self.qty_step)

    @staticmethod
    def _calc_pnl(entry: float, close: float, qty: float, direction: str) -> float:
        if direction == "long":
            return (close - entry) * qty
        return (entry - close) * qty
