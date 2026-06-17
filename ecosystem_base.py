import threading
from logger_setup import get_logger

log = get_logger("ecosystem_base")


class Trade:
    def __init__(self, symbol, side, ecosystem, entry_price, qty, table,
                 order_link_id="", open_time=0, margin=0, commission=0,
                 leverage=50, sl_price=0, order_id=""):
        self.symbol = symbol
        self.side = side
        self.ecosystem = ecosystem
        self.entry_price = entry_price
        self.qty = qty
        self.table = table
        self.order_link_id = order_link_id
        self.open_time = open_time
        self.margin = margin
        self.commission = commission
        self.leverage = leverage
        self.sl_price = sl_price
        self.order_id = order_id

        self.chandelier_extreme = entry_price
        self.chandelier_active = True
        self.chandelier_started = False

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "side": self.side,
            "ecosystem": self.ecosystem,
            "entry_price": self.entry_price,
            "qty": self.qty,
            "order_link_id": self.order_link_id,
            "open_time": self.open_time,
            "margin": self.margin,
            "commission": self.commission,
            "leverage": self.leverage,
            "sl_price": self.sl_price,
            "order_id": self.order_id
        }


class HedgeTrade(Trade):
    def __init__(self, parent_trade, **kwargs):
        super().__init__(**kwargs)
        self.parent_trade = parent_trade
        # Hedge'lerin chandelier'i yoktur, kendi çıkış mantığı vardır
        self.chandelier_active = False


class EcosystemBase:
    def __init__(self, name, config, data_pool, trade_executor, telegram_bot=None):
        self.name = name
        self.config = config
        self.data_pool = data_pool
        self.executor = trade_executor
        self.telegram = telegram_bot

        self._lock = threading.Lock()
        self.trades = []
        self.hedge_trades = []
        self.flags = {}
        self.active = config.get("aktif", True)
        self.max_trades = 20

    def reload_config(self, config):
        self.config = config
        self.active = config.get("aktif", True)

    def get_trade_count(self):
        with self._lock:
            return len(self.trades)

    def get_total_count(self):
        with self._lock:
            return len(self.trades) + len(self.hedge_trades)

    def can_open_trade(self):
        return self.active and self.get_trade_count() < self.max_trades

    def add_trade(self, trade):
        with self._lock:
            self.trades.append(trade)

    def remove_trade(self, trade):
        with self._lock:
            if trade in self.trades:
                self.trades.remove(trade)

    def add_hedge_trade(self, trade):
        with self._lock:
            self.hedge_trades.append(trade)

    def remove_hedge_trade(self, trade):
        with self._lock:
            if trade in self.hedge_trades:
                self.hedge_trades.remove(trade)

    def get_all_trades(self):
        with self._lock:
            return list(self.trades) + list(self.hedge_trades)

    def get_flag(self, symbol, flag_name):
        key = f"{symbol}||{flag_name}"
        return self.flags.get(key, None)

    def set_flag(self, symbol, flag_name, value=True):
        key = f"{symbol}||{flag_name}"
        if value:
            self.flags[key] = {
                "active": True,
                "time": __import__("time").time(),
                "symbol": symbol,
                "flag_name": flag_name
            }
            log.debug("%s: Flag acildi %s %s", self.name, symbol, flag_name)
        else:
            if key in self.flags:
                del self.flags[key]
                log.debug("%s: Flag silindi %s %s", self.name, symbol, flag_name)

    def clear_flag(self, symbol, flag_name):
        self.set_flag(symbol, flag_name, False)

    def has_flag(self, symbol, flag_name):
        key = f"{symbol}||{flag_name}"
        flag = self.flags.get(key)
        return flag is not None and flag.get("active", False)

    def get_open_flags(self):
        result = []
        for key, val in self.flags.items():
            if val.get("active"):
                result.append({
                    "symbol": val.get("symbol", ""),
                    "flag_name": val.get("flag_name", ""),
                    "time": val.get("time", 0)
                })
        return result

    def find_trades_for_symbol(self, symbol, side=None):
        with self._lock:
            result = []
            for t in self.trades:
                if t.symbol == symbol and (side is None or t.side == side):
                    result.append(t)
            return result

    def find_hedge_trades_for_parent(self, parent_trade):
        with self._lock:
            result = []
            for h in self.hedge_trades:
                if isinstance(h, HedgeTrade) and h.parent_trade is parent_trade:
                    result.append(h)
            return result

    def update_chandelier(self, trade, current_price):
        if not trade.chandelier_active:
            return False

        if trade.side == "short":
            if current_price < trade.chandelier_extreme:
                trade.chandelier_extreme = current_price

            chandelier_level = trade.chandelier_extreme + trade.table.get("chandelier_distance", 0)

            if current_price >= chandelier_level:
                return True
        else:
            if current_price > trade.chandelier_extreme:
                trade.chandelier_extreme = current_price

            chandelier_level = trade.chandelier_extreme - trade.table.get("chandelier_distance", 0)

            if current_price <= chandelier_level:
                return True

        return False

    def check_lose_exit(self, trade, current_price):
        le = trade.table.get("lose_exit", 0)
        if le <= 0:
            return False
        if trade.side == "short":
            return current_price >= le
        else:
            return current_price <= le

    def check_winrate(self, trade, current_price):
        wr = trade.table.get("winrate", 0)
        if wr <= 0:
            return False
        if trade.side == "short":
            return current_price <= wr
        else:
            return current_price >= wr

    def check_hedge_exit(self, hedge_trade, current_price):
        if not isinstance(hedge_trade, HedgeTrade):
            return False, ""

        parent = hedge_trade.parent_trade
        if parent not in self.trades:
            return True, "Bagli islem kapandi"

        entry_line = hedge_trade.table.get("entry", 0)
        if hedge_trade.side == "long":
            if current_price <= entry_line:
                return True, "Islem giris cizgisini asagi kesti"
        else:
            if current_price >= entry_line:
                return True, "Islem giris cizgisini yukari kesti"

        # Lose Exit: ana işlemin Lose Exit'idir
        # Mavi LONG hedge (ana SHORT): Lose Exit yukarıda → fiyat ≥ LE ise hedge KAR'da kapanır
        # Mor SHORT hedge (ana LONG): Lose Exit aşağıda → fiyat ≤ LE ise hedge KAR'da kapanır
        le = hedge_trade.table.get("lose_exit", 0)
        if le > 0:
            if hedge_trade.side == "long" and current_price >= le:
                return True, "Lose Exit"
            elif hedge_trade.side == "short" and current_price <= le:
                return True, "Lose Exit"

        return False, ""

    def on_tick(self, symbol, price):
        pass

    def on_candle_close(self, symbol, candle):
        pass

    def check_exits(self, symbol, price):
        pass
