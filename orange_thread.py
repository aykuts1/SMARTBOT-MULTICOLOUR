import time
import threading
import logging
from bybit_client import BybitClient
from data_feed import DataFeed
from trade_table import OrangeTable, TealTable

logger = logging.getLogger(__name__)

ORANGE_CONFIG = {
    "turuncu1": {"entry_idx": 1},
    "turuncu2": {"entry_idx": 2},
    "turuncu3": {"entry_idx": 3},
    "turuncu4": {"entry_idx": 4},
}


class OrangeThread:
    """
    Turuncu ana thread.
    Her coin için 4 ayrı örnek çalışır (turuncu1..4).
    EMA48 filtresi + bant kesişimi ile işlem açar.
    Flag sistemi yok — koşul oluşunca direkt açılır.
    """

    def __init__(
        self,
        symbol: str,
        label: str,
        config: dict,
        client: BybitClient,
        feed: DataFeed,
        balance: float,
        semaphore: threading.Semaphore,
        telegram,
        on_open_callback,
        on_close_callback,
    ):
        self.symbol = symbol
        self.label = label
        self.config = config
        self.client = client
        self.feed = feed
        self.balance = balance
        self.semaphore = semaphore
        self.telegram = telegram
        self.on_open_callback = on_open_callback
        self.on_close_callback = on_close_callback
        self.qty_step = self.client.get_qty_step(self.symbol)
        self.entry_idx = ORANGE_CONFIG[label]["entry_idx"]

        self._running = False
        self._thread: threading.Thread | None = None
        self._acquired = False

        self.table: OrangeTable | None = None

    # ------------------------------------------------------------------ #
    #  Yaşam döngüsü                                                      #
    # ------------------------------------------------------------------ #

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name=f"Orange-{self.symbol}-{self.label}", daemon=True
        )
        self._thread.start()

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------ #
    #  Ana döngü                                                          #
    # ------------------------------------------------------------------ #

    def _loop(self):
        prev_price: float | None = None

        while self._running:
            data = self.feed.get(self.symbol)
            if not data or not data["bands"]:
                time.sleep(0.5)
                continue

            price = data["price"]
            bands = data["bands"]

            if prev_price is None:
                prev_price = price
                time.sleep(0.5)
                continue

            if self.table is None:
                self._check_entry(price, prev_price, bands)
            else:
                self._check_exit(price)

            prev_price = price
            time.sleep(0.5)

    # ------------------------------------------------------------------ #
    #  Giriş mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_entry(self, price: float, prev: float, bands: dict):
        ema   = bands["ema"]
        lower = bands["lower"]
        upper = bands["upper"]
        idx   = self.entry_idx

        if price < ema and self._crossed_down(prev, price, lower[idx]):
            self._open_trade("short", bands)
        elif price > ema and self._crossed_up(prev, price, upper[idx]):
            self._open_trade("long", bands)

    # ------------------------------------------------------------------ #
    #  İşlem aç                                                           #
    # ------------------------------------------------------------------ #

    def _open_trade(self, direction: str, bands: dict):
        if not self.semaphore.acquire(blocking=False):
            self.telegram.send(
                f"⛔ Turuncu slot dolu — {self.symbol} {self.label} {direction} açılamadı (20 limit)"
            )
            return
        self._acquired = True
        try:
            self.client.set_leverage(self.symbol, self.config["trading"]["leverage"])
            self.client.set_cross_margin(self.symbol)

            self.balance = self.client.get_balance()
            idx   = self.entry_idx
            lower = bands["lower"]
            upper = bands["upper"]
            price = lower[idx] if direction == "short" else upper[idx]
            qty   = self._calc_qty(price)
            side  = "Sell" if direction == "short" else "Buy"

            sl_pct   = self.config["trading"]["sl_pct"]
            sl_price = price * (1 + sl_pct) if direction == "short" else price * (1 - sl_pct)

            result = self.client.place_market_order(self.symbol, side, qty, sl_price)
            order_id = result.get("orderId", "")

            self.table = OrangeTable.from_bands(
                self.symbol, direction, self.label, bands, idx, qty
            )
            self.table.order_id = order_id

            logger.info(f"[{self.symbol}] {self.label} {direction} açıldı — qty:{qty} sl:{sl_price:.4f}")

            self.telegram.trade_opened(
                symbol=self.symbol,
                direction=direction,
                thread=self.label,
                entry_price=price,
                qty=qty,
                sl_price=sl_price,
            )

            teal_table = TealTable.from_orange_table(self.table)
            self.on_open_callback(self.symbol, self.label, self.table, teal_table)

        except Exception as e:
            logger.error(f"[{self.symbol}] {self.label} açma hatası: {e}")
            self.telegram.error(f"{self.label} açma hatası [{self.symbol}]: {e}")
            self.table = None
            if self._acquired:
                self.semaphore.release()
                self._acquired = False

    # ------------------------------------------------------------------ #
    #  Çıkış mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_exit(self, price: float):
        t = self.table
        if t is None:
            return

        reason = None
        if t.direction == "short":
            if price >= t.lose_exit:
                reason = "Lose Exit"
            elif price <= t.winrate:
                reason = "Winrate"
        else:
            if price <= t.lose_exit:
                reason = "Lose Exit"
            elif price >= t.winrate:
                reason = "Winrate"

        if reason:
            self._close_trade(price, reason)

    # ------------------------------------------------------------------ #
    #  İşlem kapat                                                        #
    # ------------------------------------------------------------------ #

    def _close_trade(self, close_price: float, reason: str):
        t = self.table
        if t is None:
            return
        try:
            side = "Sell" if t.direction == "short" else "Buy"
            self.client.place_market_close(self.symbol, side, t.qty)
            self.client.cancel_sl(self.symbol, side)

            pnl     = self._calc_pnl(t.entry_price, close_price, t.qty, t.direction)
            pnl_pct = (pnl / (t.qty * t.entry_price / self.config["trading"]["leverage"])) * 100

            logger.info(f"[{self.symbol}] {self.label} kapatıldı — {reason} pnl:{pnl:.2f}")

            self.telegram.trade_closed(
                symbol=self.symbol,
                direction=t.direction,
                thread=self.label,
                close_price=close_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
            )

            self.on_close_callback(self.symbol, self.label)

        except Exception as e:
            logger.error(f"[{self.symbol}] {self.label} kapatma hatası: {e}")
            self.telegram.error(f"{self.label} kapatma hatası [{self.symbol}]: {e}")
        finally:
            self.table = None
            if self._acquired:
                self.semaphore.release()
                self._acquired = False

    # ------------------------------------------------------------------ #
    #  Yardımcı                                                           #
    # ------------------------------------------------------------------ #

    def _calc_qty(self, price: float) -> float:
        notional = self.balance * self.config["trading"]["balance_pct"] * self.config["trading"]["leverage"]
        return self.client.round_qty(notional / price, self.qty_step)

    @staticmethod
    def _calc_pnl(entry: float, close: float, qty: float, direction: str) -> float:
        if direction == "short":
            return (entry - close) * qty
        return (close - entry) * qty

    @staticmethod
    def _crossed_down(prev: float, curr: float, level: float) -> bool:
        return prev > level >= curr

    @staticmethod
    def _crossed_up(prev: float, curr: float, level: float) -> bool:
        return prev < level <= curr
