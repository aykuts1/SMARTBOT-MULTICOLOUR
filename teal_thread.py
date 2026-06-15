import time
import threading
import logging
from bybit_client import BybitClient
from data_feed import DataFeed
from trade_table import TealTable

logger = logging.getLogger(__name__)


class TealThread:
    """
    Turkuaz hedge thread.
    Her Turuncu açılışında bire bir eşleşir.
    Turuncu SHORT ise LONG açar, Turuncu LONG ise SHORT açar.
    Fiyat LZ2'ye girince işlem açılır.
    Turuncu kapanınca stop() ile durdurulur.
    """

    def __init__(
        self,
        symbol: str,
        label: str,
        teal_table: TealTable,
        config: dict,
        client: BybitClient,
        feed: DataFeed,
        balance: float,
        telegram,
    ):
        self.symbol = symbol
        self.label = label
        self.table = teal_table
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
        self._thread = threading.Thread(
            target=self._loop, name=f"Teal-{self.symbol}-{self.label}", daemon=True
        )
        self._thread.start()

    def stop(self):
        """Bağlı Turuncu kapandığında çağrılır — açık pozisyonu kapatır."""
        self._running = False
        if self._open:
            price = self.feed.get_price(self.symbol) or self._entry_price
            self._close_trade(price, "Turuncu kapandı")

    # ------------------------------------------------------------------ #
    #  Ana döngü                                                          #
    # ------------------------------------------------------------------ #

    def _loop(self):
        while self._running:
            price = self.feed.get_price(self.symbol)
            if price is None:
                time.sleep(0.5)
                continue

            if not self._open:
                self._check_entry(price)
            else:
                self._check_exit(price)

            time.sleep(0.5)

    # ------------------------------------------------------------------ #
    #  Giriş mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_entry(self, price: float):
        t = self.table
        if t.direction == "long":
            if price >= t.zone2_low:
                self._open_trade()
        else:
            if price <= t.zone2_high:
                self._open_trade()

    # ------------------------------------------------------------------ #
    #  İşlem aç                                                           #
    # ------------------------------------------------------------------ #

    def _open_trade(self):
        try:
            self.balance = self.client.get_balance()
            price = self.feed.get_price(self.symbol) or 0
            qty   = self._calc_qty(price)
            side  = "Buy" if self.table.direction == "long" else "Sell"

            sl_pct   = self.config["trading"]["sl_pct"]
            sl_price = price * (1 - sl_pct) if side == "Buy" else price * (1 + sl_pct)

            result = self.client.place_market_order(self.symbol, side, qty, sl_price)
            self._qty         = qty
            self._entry_price = price
            self._open        = True
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

        if t.direction == "long":
            if price < t.entry_price:
                reason = "Turuncu giriş altına düştü"
            elif price > t.zone4_high:
                reason = "LZ4 üstüne çıktı"
        else:
            if price > t.entry_price:
                reason = "Turuncu giriş üstüne çıktı"
            elif price < t.zone4_low:
                reason = "LZ4 altına düştü"

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
            self.client.cancel_sl(self.symbol, side)

            pnl     = self._calc_pnl(self._entry_price, close_price, self._qty, self.table.direction)
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

    # ------------------------------------------------------------------ #
    #  Yardımcı                                                           #
    # ------------------------------------------------------------------ #

    def _calc_qty(self, price: float) -> float:
        notional = self.balance * self.config["trading"]["balance_pct"] * self.config["trading"]["leverage"]
        return self.client.round_qty(notional / price, self.qty_step)

    @staticmethod
    def _calc_pnl(entry: float, close: float, qty: float, direction: str) -> float:
        if direction == "long":
            return (close - entry) * qty
        return (entry - close) * qty
