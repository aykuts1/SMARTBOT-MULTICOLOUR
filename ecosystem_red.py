import threading
from logger_setup import get_logger

log = get_logger("ecosystem_red")


class Trade:
    def __init__(self, info):
        self.symbol       = info["symbol"]
        self.side         = info["side"]
        self.ecosystem    = info["ecosystem"]
        self.entry_price  = info["entry_price"]
        self.qty          = info["qty"]
        self.margin       = info["margin"]
        self.leverage     = info["leverage"]
        self.sl_price     = info["sl_price"]
        self.commission   = info["commission"]
        self.order_id     = info["order_id"]
        self.order_link_id = info["order_link_id"]
        self.open_time    = info["open_time"]
        self.chandelier_active    = False
        self.chandelier_trail_pct = 0.02
        self.extreme_price        = info["entry_price"]


class RedEcosystem:
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

    def reload_config(self, config):
        self.config = config

    # --- Mum kapanışı ---
    def on_candle_close(self, symbol, candle):
        indicators = self.data_pool.get_indicators(symbol)
        if not indicators:
            return

        colors = indicators.get("center_color", [])
        if len(colors) < 2:
            return

        current_color = colors[-1]
        prev_color    = colors[-2]

        if not current_color or not prev_color or current_color == prev_color:
            return

        price = candle["close"]

        # Önce bu coindeki mevcut işlemi kapat
        with self._lock:
            existing = [t for t in self.trades if t.symbol == symbol]
        for trade in existing:
            self._close_and_remove(trade, "renk_degisimi", price)

        # Yeni yön
        new_side = "long" if current_color == "green" else "short"

        # Slot kontrolü
        max_islem = self.config.get("max_islem", 10)
        with self._lock:
            total        = len(self.trades)
            symbol_count = sum(1 for t in self.trades if t.symbol == symbol)

        if total >= max_islem:
            log.warning("Kirmizi slot dolu (%d/%d), %s atlaniyor", total, max_islem, symbol)
            if self.telegram:
                self.telegram.send_slot_full(symbol, "kirmizi", total)
            return

        if symbol_count >= self.MAX_PER_SYMBOL:
            return

        trade_info = self.executor.open_trade(symbol, new_side, "kirmizi", entry_price=price)
        if not trade_info:
            return

        trade = Trade(trade_info)
        with self._lock:
            self.trades.append(trade)

        if self.telegram:
            cfg = self.config
            sl_pct = cfg.get("sl_yuzde", 0.02)
            tp_pct = cfg.get("tp_yuzde", 0.10)
            if new_side == "short":
                table = {"lose_exit": price * (1 + sl_pct), "winrate": price * (1 - tp_pct), "dynamic": False}
            else:
                table = {"lose_exit": price * (1 - sl_pct), "winrate": price * (1 + tp_pct), "dynamic": False}
            self.telegram.send_trade_opened(trade_info, table)

    # --- 5 saniyelik tick ---
    def on_tick(self, symbol, price):
        with self._lock:
            symbol_trades = [t for t in self.trades if t.symbol == symbol]
        for trade in symbol_trades:
            self._check_exit(trade, price)

    def _check_exit(self, trade, price):
        with self._lock:
            if trade not in self.trades:
                return

        entry = trade.entry_price
        side  = trade.side
        cfg   = self.config

        sl_pct      = cfg.get("sl_yuzde",             0.02)
        tp_pct      = cfg.get("tp_yuzde",             0.10)
        ch_start    = cfg.get("chandelier_baslangic",  0.05)
        ch_sikistir = cfg.get("chandelier_sikistir",   0.07)
        trail1      = cfg.get("chandelier_trail_1",    0.02)
        trail2      = cfg.get("chandelier_trail_2",    0.01)

        pnl_pct = (entry - price) / entry if side == "short" else (price - entry) / entry

        if pnl_pct <= -sl_pct:
            self._close_and_remove(trade, "stop_loss", price)
            return

        if pnl_pct >= tp_pct:
            self._close_and_remove(trade, "take_profit", price)
            return

        if pnl_pct >= ch_start and not trade.chandelier_active:
            trade.chandelier_active    = True
            trade.chandelier_trail_pct = trail1
            trade.extreme_price        = price
            log.debug("Chandelier aktif: %s %s @ %.4f", trade.symbol, side, price)
            if self.telegram:
                level = price * (1 + trail1) if side == "short" else price * (1 - trail1)
                self.telegram.send_chandelier_activated(
                    trade.symbol, "kirmizi", side, entry, price, level
                )

        if trade.chandelier_active:
            if side == "short":
                if price < trade.extreme_price:
                    trade.extreme_price = price
            else:
                if price > trade.extreme_price:
                    trade.extreme_price = price

            if pnl_pct >= ch_sikistir:
                trade.chandelier_trail_pct = trail2

            if side == "short":
                trail_price = trade.extreme_price * (1 + trade.chandelier_trail_pct)
                if price >= trail_price:
                    self._close_and_remove(trade, "chandelier", price)
            else:
                trail_price = trade.extreme_price * (1 - trade.chandelier_trail_pct)
                if price <= trail_price:
                    self._close_and_remove(trade, "chandelier", price)

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
        return []
