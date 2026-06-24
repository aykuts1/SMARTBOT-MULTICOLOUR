import threading
import time
from logger_setup import get_logger

log = get_logger("ecosystem_blue")


class Trade:
    def __init__(self, info):
        self.symbol        = info["symbol"]
        self.side          = info["side"]
        self.ecosystem     = info["ecosystem"]
        self.entry_price   = info["entry_price"]
        self.qty           = info["qty"]
        self.margin        = info["margin"]
        self.leverage      = info["leverage"]
        self.sl_price      = info["sl_price"]
        self.commission    = info["commission"]
        self.order_id      = info["order_id"]
        self.order_link_id = info["order_link_id"]
        self.open_time     = info["open_time"]


class BlueFlag:
    def __init__(self, symbol, direction):
        self.symbol    = symbol
        self.direction = direction  # "short" veya "long"
        self.time      = time.time()


class BlueEcosystem:
    MAX_PER_SYMBOL = 1

    def __init__(self, config, data_pool, executor, telegram):
        self.config      = config
        self.data_pool   = data_pool
        self.executor    = executor
        self.telegram    = telegram
        self.active      = config.get("aktif", True)
        self._lock       = threading.Lock()
        self.trades      = []
        self.hedge_trades = []
        self._flags      = {}       # symbol -> BlueFlag veya None
        self._prev_above = {}       # symbol -> bool (fiyat merkez çizginin üstünde miydi)

    def reload_config(self, config):
        self.config = config

    # --- 5 saniyelik tick ---
    def on_tick(self, symbol, price):
        indicators = self.data_pool.get_indicators(symbol)
        if not indicators:
            return

        center = indicators.get("center_line", [])
        if not center:
            return

        center_val = center[-1]
        if center_val <= 0:
            return

        prev_above = self._prev_above.get(symbol)
        curr_above = price > center_val

        if prev_above is not None and prev_above != curr_above:
            if not curr_above:  # Aşağı cross → Short Flag
                with self._lock:
                    self._flags[symbol] = BlueFlag(symbol, "short")
                log.debug("Mavi Short Flag: %s @ %.4f (merkez=%.4f)", symbol, price, center_val)
            else:               # Yukarı cross → Long Flag
                with self._lock:
                    self._flags[symbol] = BlueFlag(symbol, "long")
                log.debug("Mavi Long Flag: %s @ %.4f (merkez=%.4f)", symbol, price, center_val)

        self._prev_above[symbol] = curr_above

        # Açık işlemlerin çıkış kontrolü
        with self._lock:
            symbol_trades = [t for t in self.trades if t.symbol == symbol]
        for trade in symbol_trades:
            self._check_exit(trade, price, indicators)

    # --- Mum kapanışı ---
    def on_candle_close(self, symbol, candle):
        with self._lock:
            flag = self._flags.get(symbol)
        if flag is None:
            return

        indicators = self.data_pool.get_indicators(symbol)
        if not indicators:
            return

        colors      = indicators.get("center_color", [])
        lower_tooth = indicators.get("lower_tooth",  [])
        upper_tooth = indicators.get("upper_tooth",  [])
        lower_winrate = indicators.get("lower_winrate", [])
        upper_winrate = indicators.get("upper_winrate", [])

        if not colors or not lower_tooth or not upper_tooth:
            return

        current_color = colors[-1]
        close_price   = candle["close"]

        if flag.direction == "short":
            # Merkez KIRMIZI + mum Alt Diş Bandın altında kapandı
            if current_color == "red" and close_price < lower_tooth[-1]:
                table = {
                    "lose_exit": upper_tooth[-1],
                    "winrate":   lower_winrate[-1] if lower_winrate else 0,
                    "dynamic":   False
                }
                self._try_open(symbol, "short", close_price, table)

        elif flag.direction == "long":
            # Merkez YEŞİL + mum Üst Diş Bandın üstünde kapandı
            if current_color == "green" and close_price > upper_tooth[-1]:
                table = {
                    "lose_exit": lower_tooth[-1],
                    "winrate":   upper_winrate[-1] if upper_winrate else 0,
                    "dynamic":   False
                }
                self._try_open(symbol, "long", close_price, table)

    def _try_open(self, symbol, side, price, table):
        max_islem = self.config.get("max_islem", 10)

        with self._lock:
            total        = len(self.trades)
            symbol_count = sum(1 for t in self.trades if t.symbol == symbol)

        if total >= max_islem:
            log.warning("Mavi slot dolu (%d/%d), %s atlaniyor", total, max_islem, symbol)
            if self.telegram:
                self.telegram.send_slot_full(symbol, "mavi", total)
            return

        if symbol_count >= self.MAX_PER_SYMBOL:
            return

        trade_info = self.executor.open_trade(symbol, side, "mavi", entry_price=price)
        if not trade_info:
            return

        trade = Trade(trade_info)
        with self._lock:
            self.trades.append(trade)
            self._flags[symbol] = None  # Giriş yapılınca flag silinir

        if self.telegram:
            self.telegram.send_trade_opened(trade_info, table)

    def _check_exit(self, trade, price, indicators):
        with self._lock:
            if trade not in self.trades:
                return

        side   = trade.side
        entry  = trade.entry_price
        tp_pct = self.config.get("tp_yuzde", 0.05)

        upper_tooth   = indicators.get("upper_tooth",   [])
        lower_tooth   = indicators.get("lower_tooth",   [])
        lower_winrate = indicators.get("lower_winrate", [])
        upper_winrate = indicators.get("upper_winrate", [])

        if not upper_tooth or not lower_tooth:
            return

        ut  = upper_tooth[-1]
        lt  = lower_tooth[-1]
        lwr = lower_winrate[-1] if lower_winrate else 0
        uwr = upper_winrate[-1] if upper_winrate else 0

        if side == "short":
            pnl_pct = (entry - price) / entry
            if ut > 0 and price >= ut:
                self._close_and_remove(trade, "ust_dis_bant", price)
                return
            if lwr > 0 and price <= lwr:
                self._close_and_remove(trade, "alt_winrate", price)
                return
        else:
            pnl_pct = (price - entry) / entry
            if lt > 0 and price <= lt:
                self._close_and_remove(trade, "alt_dis_bant", price)
                return
            if uwr > 0 and price >= uwr:
                self._close_and_remove(trade, "ust_winrate", price)
                return

        if pnl_pct >= tp_pct:
            self._close_and_remove(trade, "kar_al", price)

    def _close_and_remove(self, trade, reason, price):
        with self._lock:
            if trade not in self.trades:
                return
            self.trades.remove(trade)

        close_info = self.executor.close_trade(trade, reason, price)
        if close_info and self.telegram:
            self.telegram.send_trade_closed(close_info)

    # --- main.py arayüzü ---
    def get_all_trades(self):
        with self._lock:
            return list(self.trades)

    def get_total_count(self):
        with self._lock:
            return len(self.trades)

    def remove_trade(self, trade):
        with self._lock:
            if trade in self.trades:
                self.trades.remove(trade)

    def remove_hedge_trade(self, trade):
        pass

    def find_trades_for_symbol(self, symbol, side):
        with self._lock:
            return [t for t in self.trades if t.symbol == symbol and t.side == side]

    def get_open_flags(self):
        with self._lock:
            return [
                {"symbol": s, "direction": f.direction, "time": f.time}
                for s, f in self._flags.items()
                if f is not None
            ]
