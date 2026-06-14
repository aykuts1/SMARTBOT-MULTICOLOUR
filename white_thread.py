import time
import threading
import logging
from bybit_client import BybitClient
from data_feed import DataFeed
from trade_table import WhiteTable, PurpleTable

logger = logging.getLogger(__name__)


class WhiteThread:
    """
    Beyaz ekosistem ana thread'i.
    Stochastic + MACD çift kesişimine göre, mum kapanışında işlem açar.
    Her coin için bir örnek çalışır.
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
        on_open_callback,
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
        self._acquired = False

        self.table: WhiteTable | None = None

        self._white_flag = False
        self._flag_direction: str | None = None
        self._flag_triggered_by: str | None = None
        self._flag_candle_count: int = 0
        self._last_candle_time: int | None = None

    # ------------------------------------------------------------------ #
    #  Yaşam döngüsü                                                      #
    # ------------------------------------------------------------------ #

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"White-{self.symbol}", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------ #
    #  Ana döngü — sadece yeni mum kapanışında tetiklenir                 #
    # ------------------------------------------------------------------ #

    def _loop(self):
        while self._running:
            data = self.feed.get(self.symbol)
            if not data or not data["bands"]:
                time.sleep(0.5)
                continue

            candle_time = data.get("last_closed_candle_time")
            if candle_time is None or candle_time == self._last_candle_time:
                time.sleep(0.5)
                continue

            self._last_candle_time = candle_time
            close_price = data.get("last_closed_price", data["price"])

            if self.table is None:
                self._check_entry(data, close_price)
            else:
                self._check_exit(close_price)

    # ------------------------------------------------------------------ #
    #  Giriş mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_entry(self, data: dict, close_price: float):
        stoch = data.get("stoch")
        macd_data = data.get("macd")
        bands = data["bands"]
        ema = bands["ema"]
        atr = bands["atr"]

        if stoch is None or macd_data is None:
            return

        stoch_down = stoch["k_prev"] > stoch["d_prev"] and stoch["k_curr"] <= stoch["d_curr"]
        stoch_up   = stoch["k_prev"] < stoch["d_prev"] and stoch["k_curr"] >= stoch["d_curr"]
        macd_down  = macd_data["macd_prev"] > macd_data["signal_prev"] and macd_data["macd_curr"] <= macd_data["signal_curr"]
        macd_up    = macd_data["macd_prev"] < macd_data["signal_prev"] and macd_data["macd_curr"] >= macd_data["signal_curr"]

        if not self._white_flag:
            # Her iki gösterge aynı mumda kesişirse → anında sinyal
            if stoch_down and macd_down:
                if close_price < ema:
                    self._open_trade("short", close_price, atr)
                return
            if stoch_up and macd_up:
                if close_price > ema:
                    self._open_trade("long", close_price, atr)
                return
            # Tek gösterge kesişimi → flag başlat
            if stoch_down or macd_down:
                self._white_flag = True
                self._flag_direction = "short"
                self._flag_triggered_by = "stoch" if stoch_down else "macd"
                self._flag_candle_count = 0
            elif stoch_up or macd_up:
                self._white_flag = True
                self._flag_direction = "long"
                self._flag_triggered_by = "stoch" if stoch_up else "macd"
                self._flag_candle_count = 0
        else:
            self._flag_candle_count += 1

            if self._flag_candle_count > 5:
                self._clear_flag()
                return

            direction     = self._flag_direction
            triggered_by  = self._flag_triggered_by

            if direction == "short":
                other_crossed = macd_down if triggered_by == "stoch" else stoch_down
                if other_crossed:
                    if close_price < ema:
                        self._open_trade("short", close_price, atr)
                    self._clear_flag()
            else:
                other_crossed = macd_up if triggered_by == "stoch" else stoch_up
                if other_crossed:
                    if close_price > ema:
                        self._open_trade("long", close_price, atr)
                    self._clear_flag()

    def _clear_flag(self):
        self._white_flag = False
        self._flag_direction = None
        self._flag_triggered_by = None
        self._flag_candle_count = 0

    # ------------------------------------------------------------------ #
    #  İşlem aç                                                           #
    # ------------------------------------------------------------------ #

    def _open_trade(self, direction: str, price: float, atr: float):
        if not self.semaphore.acquire(blocking=False):
            self.telegram.send(f"⛔ Beyaz slot dolu — {self.symbol} {direction} açılamadı (10 coin limiti)")
            return
        self._acquired = True
        try:
            self.client.set_leverage(self.symbol, self.config["trading"]["leverage"])
            self.client.set_cross_margin(self.symbol)

            qty = self._calc_qty(price)
            side = "Sell" if direction == "short" else "Buy"

            self.table = WhiteTable.from_entry(self.symbol, direction, price, atr, qty)
            sl_price = self.table.lose_exit

            result = self.client.place_market_order(self.symbol, side, qty, sl_price)
            self.table.order_id = result.get("orderId", "")

            logger.info(f"[{self.symbol}] Beyaz {direction} açıldı — qty:{qty} sl:{sl_price:.4f}")

            self.telegram.trade_opened(
                symbol=self.symbol,
                direction=direction,
                thread="beyaz",
                entry_price=price,
                qty=qty,
                sl_price=sl_price,
            )

            purple = PurpleTable.from_white_table(self.table)
            self.on_open_callback(self.symbol, self.table, purple)

        except Exception as e:
            logger.error(f"[{self.symbol}] Beyaz açma hatası: {e}")
            self.telegram.error(f"Beyaz açma hatası [{self.symbol}]: {e}")
            self.table = None
            if self._acquired:
                self.semaphore.release()
                self._acquired = False

    # ------------------------------------------------------------------ #
    #  Çıkış mantığı                                                      #
    # ------------------------------------------------------------------ #

    def _check_exit(self, close_price: float):
        t = self.table
        if t is None:
            return

        reason = None
        if t.direction == "short":
            if close_price >= t.lose_exit:
                reason = "Lose Exit"
            elif close_price <= t.winrate:
                reason = "Winrate"
        else:
            if close_price <= t.lose_exit:
                reason = "Lose Exit"
            elif close_price >= t.winrate:
                reason = "Winrate"

        if reason:
            self._close_trade(close_price, reason)

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

            logger.info(f"[{self.symbol}] Beyaz kapatıldı — {reason} pnl:{pnl:.2f}")

            self.telegram.trade_closed(
                symbol=self.symbol,
                direction=t.direction,
                thread="beyaz",
                close_price=close_price,
                pnl=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
            )

            self.on_close_callback(self.symbol, t)

        except Exception as e:
            logger.error(f"[{self.symbol}] Beyaz kapatma hatası: {e}")
            self.telegram.error(f"Beyaz kapatma hatası [{self.symbol}]: {e}")
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
        return round(notional / price, 3)

    @staticmethod
    def _calc_pnl(entry: float, close: float, qty: float, direction: str) -> float:
        if direction == "short":
            return (entry - close) * qty
        return (close - entry) * qty
