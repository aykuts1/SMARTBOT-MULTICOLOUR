import time
import threading
import logging
from bybit_client import BybitClient
from data_feed import DataFeed
from trade_table import RedTable, BlueTable

logger = logging.getLogger(__name__)


class RedThread:
    """
    Her coin için bir RedThread örneği çalışır.
    Flag → cross → işlem aç → CE/Winrate/LoseExit ile kapat.
    """

    def __init__(
        self,
        symbol: str,
        config: dict,
        client: BybitClient,
        feed: DataFeed,
        balance: float,
        coin_semaphore: threading.Semaphore,
        telegram,
        on_open_callback,    # blue/yellow thread'lere haber ver
        on_close_callback,
    ):
        self.symbol = symbol
        self.config = config
        self.client = client
        self.feed = feed
        self.balance = balance
        self.semaphore = coin_semaphore
        self.telegram = telegram
        self.on_open_callback = on_open_callback
        self.on_close_callback = on_close_callback

        self._running = False
        self._thread: threading.Thread | None = None

        self.short_flag = False
        self.long_flag = False

        self.table: RedTable | None = None
        self._acquired = False  # semaphore alındı mı

    # ------------------------------------------------------------------ #
    #  Yaşam döngüsü                                                      #
    # ------------------------------------------------------------------ #

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"Red-{self.symbol}", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------ #
    #  Ana döngü                                                           #
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
            ce_data = data["ce"]

            if prev_price is None:
                prev_price = price
                time.sleep(0.5)
                continue

            lower = bands["lower"]
            upper = bands["upper"]

            if self.table is None:
                self._check_entry(price, prev_price, lower, upper, bands)
            else:
                self._check_exit(price, ce_data)

            prev_price = price
            time.sleep(0.5)

    # ------------------------------------------------------------------ #
    #  Giriş mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_entry(self, price: float, prev: float, lower: list, upper: list, bands: dict):
        l1, l2 = lower[0], lower[1]
        u1, u2 = upper[0], upper[1]

        # --- SHORT FLAG ---
        if self._crossed_down(prev, price, l1):
            self.short_flag = True
            logger.debug(f"[{self.symbol}] Short flag açıldı")
        if self._crossed_up(prev, price, l1):
            self.short_flag = False

        # --- LONG FLAG ---
        if self._crossed_up(prev, price, u1):
            self.long_flag = True
            logger.debug(f"[{self.symbol}] Long flag açıldı")
        if self._crossed_down(prev, price, u1):
            self.long_flag = False

        # --- SHORT GİRİŞ ---
        if self.short_flag and self._crossed_down(prev, price, l2):
            if self.semaphore.acquire(blocking=False):
                self._acquired = True
                self.short_flag = False
                self._open_trade("short", bands)
            else:
                self.telegram.send(f"⛔ Slot dolu — {self.symbol} short açılamadı (10 coin limiti)")
                self.short_flag = False

        # --- LONG GİRİŞ ---
        elif self.long_flag and self._crossed_up(prev, price, u2):
            if self.semaphore.acquire(blocking=False):
                self._acquired = True
                self.long_flag = False
                self._open_trade("long", bands)
            else:
                self.telegram.send(f"⛔ Slot dolu — {self.symbol} long açılamadı (10 coin limiti)")
                self.long_flag = False

    # ------------------------------------------------------------------ #
    #  İşlem aç                                                           #
    # ------------------------------------------------------------------ #

    def _open_trade(self, direction: str, bands: dict):
        try:
            self.client.set_leverage(self.symbol, self.config["trading"]["leverage"])
            self.client.set_cross_margin(self.symbol)

            qty = self._calc_qty(bands)
            side = "Sell" if direction == "short" else "Buy"
            sl_pct = self.config["trading"]["sl_pct"]
            entry = bands["lower"][1] if direction == "short" else bands["upper"][1]
            sl_price = entry * (1 + sl_pct) if direction == "short" else entry * (1 - sl_pct)

            result = self.client.place_market_order(self.symbol, side, qty, sl_price)
            order_id = result.get("orderId", "")

            self.table = RedTable.from_bands(self.symbol, direction, bands, qty, order_id)

            logger.info(f"[{self.symbol}] Kırmızı {direction} açıldı — qty:{qty} sl:{sl_price:.4f}")

            self.telegram.trade_opened(
                symbol=self.symbol,
                direction=direction,
                thread="kırmızı" if direction == "short" else "yeşil",
                entry_price=entry,
                qty=qty,
                sl_price=sl_price,
            )

            blue = BlueTable.from_red_table(self.table)
            self.on_open_callback(self.symbol, self.table, blue)

        except Exception as e:
            logger.error(f"[{self.symbol}] İşlem açma hatası: {e}")
            self.telegram.error(f"İşlem açma hatası [{self.symbol}]: {e}")
            if self._acquired:
                self.semaphore.release()
                self._acquired = False

    # ------------------------------------------------------------------ #
    #  Çıkış mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_exit(self, price: float, ce_data: dict | None):
        t = self.table
        if t is None:
            return

        # CE değerini güncelle
        if ce_data:
            t.ce_value = ce_data["ce_short"] if t.direction == "short" else ce_data["ce_long"]

        reason = None

        if t.direction == "short":
            if t.ce_value and price >= t.ce_value:
                reason = "CE"
            elif price <= t.winrate:
                reason = "Winrate"
            elif price >= t.lose_exit:
                reason = "Lose Exit"
        else:
            if t.ce_value and price <= t.ce_value:
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
        t = self.table
        if t is None:
            return
        try:
            side = "Sell" if t.direction == "short" else "Buy"
            self.client.place_market_close(self.symbol, side, t.qty)
            self.client.cancel_sl(self.symbol)

            pnl = self._calc_pnl(t.entry_price, close_price, t.qty, t.direction)
            pnl_pct = (pnl / (t.qty * t.entry_price / self.config["trading"]["leverage"])) * 100

            logger.info(f"[{self.symbol}] Kırmızı kapatıldı — {reason} pnl:{pnl:.2f}")

            self.telegram.trade_closed(
                symbol=self.symbol,
                direction=t.direction,
                thread="kırmızı" if t.direction == "short" else "yeşil",
                close_price=close_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
            )

            self.on_close_callback(self.symbol, t)

        except Exception as e:
            logger.error(f"[{self.symbol}] İşlem kapatma hatası: {e}")
            self.telegram.error(f"İşlem kapatma hatası [{self.symbol}]: {e}")
        finally:
            self.table = None
            if self._acquired:
                self.semaphore.release()
                self._acquired = False

    # ------------------------------------------------------------------ #
    #  Yardımcı metodlar                                                  #
    # ------------------------------------------------------------------ #

    def _calc_qty(self, bands: dict) -> float:
        notional = self.balance * self.config["trading"]["balance_pct"] * self.config["trading"]["leverage"]
        price = bands["lower"][1] if bands else 1
        raw = notional / price
        return round(raw, 3)

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
