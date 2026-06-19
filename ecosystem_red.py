from ecosystem_base import EcosystemBase, Trade
from trade_table import create_red_table
from logger_setup import get_logger

log = get_logger("ecosystem_red")


class RedEcosystem(EcosystemBase):
    def __init__(self, config, data_pool, trade_executor, telegram_bot=None):
        super().__init__("kirmizi", config, data_pool, trade_executor, telegram_bot)
        self.max_kirmizi = config.get("max_kirmizi_islem", 10)
        self.max_mavi = config.get("max_mavi_islem", 10)
        self._prev_prices = {}

    def _count_kirmizi(self):
        with self._lock:
            return sum(1 for t in self.trades if t.ecosystem == "kirmizi")

    def _count_mavi(self):
        with self._lock:
            return sum(1 for t in self.trades if t.ecosystem == "mavi")

    def can_open_kirmizi(self):
        return self.active and self._count_kirmizi() < self.max_kirmizi

    def can_open_mavi(self):
        return self.active and self._count_mavi() < self.max_mavi

    def _has_trade_eco(self, symbol, ecosystem):
        with self._lock:
            return any(t.symbol == symbol and t.ecosystem == ecosystem for t in self.trades)

    def on_candle_close(self, symbol, candle):
        pass

    def _open_kirmizi(self, symbol, price, lose_exit_price, side):
        table = create_red_table(price, lose_exit_price, side, self.config)

        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="KIRMIZI", entry_price=price
        )

        if trade_info:
            trade = Trade(
                symbol=symbol, side=side, ecosystem="kirmizi",
                entry_price=price, qty=trade_info["qty"], table=table,
                order_link_id=trade_info["order_link_id"],
                open_time=trade_info["open_time"],
                margin=trade_info["margin"],
                commission=trade_info["commission"],
                leverage=trade_info["leverage"],
                sl_price=trade_info["sl_price"],
                order_id=trade_info["order_id"]
            )
            trade.chandelier_active = False
            self.add_trade(trade)

            if self.telegram:
                self.telegram.send_trade_opened(trade_info, table)

            log.info("KIRMIZI %s acildi: %s @ %.4f", side.upper(), symbol, price)

    def on_tick(self, symbol, price):
        if not self.active:
            return
        prev_price = self._prev_prices.get(symbol)
        self._prev_prices[symbol] = price
        self._check_kirmizi_flags(symbol, price, prev_price)
        self._check_mavi_flags(symbol, price, prev_price)
        self._check_kirmizi_exits_tick(symbol, price)
        self._check_mavi_exits_tick(symbol, price, prev_price)

    def _check_kirmizi_flags(self, symbol, price, prev_price):
        if prev_price is None:
            return

        ind = self.data_pool.get_indicators(symbol)
        if not ind:
            return

        kc_middle = ind.get("kc_red_middle", [])
        kc_upper = ind.get("kc_red_upper", [])
        kc_lower = ind.get("kc_red_lower", [])

        if not kc_middle or not kc_upper or not kc_lower:
            return

        current_ema = kc_middle[-1]
        current_kc_upper = kc_upper[-1]
        current_kc_lower = kc_lower[-1]

        if current_ema <= 0:
            return

        # EMA cross aşağı → short flag aç, long flag sil
        if prev_price >= current_ema and price < current_ema:
            if not self.has_flag(symbol, "kirmizi_short_ema"):
                self.set_flag(symbol, "kirmizi_short_ema", True)
            self.clear_flag(symbol, "kirmizi_long_ema")

        # EMA cross yukarı → long flag aç, short flag sil
        if prev_price <= current_ema and price > current_ema:
            if not self.has_flag(symbol, "kirmizi_long_ema"):
                self.set_flag(symbol, "kirmizi_long_ema", True)
            self.clear_flag(symbol, "kirmizi_short_ema")

        # SHORT: alt bandı aşağı kes + flag → işlem aç
        if (prev_price >= current_kc_lower and price < current_kc_lower
                and self.has_flag(symbol, "kirmizi_short_ema")):
            if self.can_open_kirmizi() and not self._has_trade_eco(symbol, "kirmizi"):
                self._open_kirmizi(symbol, price, current_kc_upper, "short")
                self.clear_flag(symbol, "kirmizi_short_ema")

        # LONG: üst bandı yukarı kes + flag → işlem aç
        if (prev_price <= current_kc_upper and price > current_kc_upper
                and self.has_flag(symbol, "kirmizi_long_ema")):
            if self.can_open_kirmizi() and not self._has_trade_eco(symbol, "kirmizi"):
                self._open_kirmizi(symbol, price, current_kc_lower, "long")
                self.clear_flag(symbol, "kirmizi_long_ema")

    def _check_mavi_flags(self, symbol, price, prev_price):
        if prev_price is None:
            return

        ind = self.data_pool.get_indicators(symbol)
        if not ind:
            return

        kc_upper = ind.get("kc_red_upper", [])
        kc_lower = ind.get("kc_red_lower", [])
        kc_outer_upper = ind.get("kc_red_outer_upper", [])
        kc_outer_lower = ind.get("kc_red_outer_lower", [])

        if not kc_upper or not kc_outer_upper:
            return

        cur_upper = kc_upper[-1]
        cur_lower = kc_lower[-1]
        cur_outer_upper = kc_outer_upper[-1]
        cur_outer_lower = kc_outer_lower[-1]

        # --- MAVI SHORT ---
        # Dış üst bandı aşağı keserse → flag aç
        if prev_price >= cur_outer_upper and price < cur_outer_upper:
            if not self.has_flag(symbol, "mavi_short"):
                self.set_flag(symbol, "mavi_short", True)
        # Dış üst bandı yukarı keserse → flag sil
        if prev_price <= cur_outer_upper and price > cur_outer_upper:
            self.clear_flag(symbol, "mavi_short")
        # Üst bandı aşağı keserse + flag → işlem aç
        if (prev_price >= cur_upper and price < cur_upper
                and self.has_flag(symbol, "mavi_short")):
            if self.can_open_mavi() and not self._has_trade_eco(symbol, "mavi"):
                self._open_mavi(symbol, price, "short")
                self.clear_flag(symbol, "mavi_short")

        # --- MAVI LONG ---
        # Dış alt bandı yukarı keserse → flag aç
        if prev_price <= cur_outer_lower and price > cur_outer_lower:
            if not self.has_flag(symbol, "mavi_long"):
                self.set_flag(symbol, "mavi_long", True)
        # Dış alt bandı aşağı keserse → flag sil
        if prev_price >= cur_outer_lower and price < cur_outer_lower:
            self.clear_flag(symbol, "mavi_long")
        # Alt bandı yukarı keserse + flag → işlem aç
        if (prev_price <= cur_lower and price > cur_lower
                and self.has_flag(symbol, "mavi_long")):
            if self.can_open_mavi() and not self._has_trade_eco(symbol, "mavi"):
                self._open_mavi(symbol, price, "long")
                self.clear_flag(symbol, "mavi_long")

    def _open_mavi(self, symbol, price, side):
        table = {
            "side": side,
            "entry": price,
        }

        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="MAVI", entry_price=price
        )

        if trade_info:
            trade = Trade(
                symbol=symbol, side=side, ecosystem="mavi",
                entry_price=price, qty=trade_info["qty"], table=table,
                order_link_id=trade_info["order_link_id"],
                open_time=trade_info["open_time"],
                margin=trade_info["margin"],
                commission=trade_info["commission"],
                leverage=trade_info["leverage"],
                sl_price=trade_info["sl_price"],
                order_id=trade_info["order_id"]
            )
            trade.chandelier_active = False
            self.add_trade(trade)

            if self.telegram:
                self.telegram.send_trade_opened(trade_info, table)

            log.info("MAVI %s acildi: %s @ %.4f", side.upper(), symbol, price)

    def _activate_chandelier_if_ready(self, trade, price):
        if trade.chandelier_active:
            return
        distance = trade.table.get("distance", 0)
        entry = trade.table.get("entry", trade.entry_price)
        if distance <= 0:
            return
        if trade.side == "short" and price <= entry - distance:
            trade.chandelier_active = True
            trade.chandelier_extreme = price
            if self.telegram:
                chandelier_level = price + trade.table.get("chandelier_distance", distance)
                self.telegram.send_chandelier_activated(
                    trade.symbol, trade.ecosystem, trade.side,
                    trade.entry_price, price, chandelier_level
                )
        elif trade.side == "long" and price >= entry + distance:
            trade.chandelier_active = True
            trade.chandelier_extreme = price
            if self.telegram:
                chandelier_level = price - trade.table.get("chandelier_distance", distance)
                self.telegram.send_chandelier_activated(
                    trade.symbol, trade.ecosystem, trade.side,
                    trade.entry_price, price, chandelier_level
                )

    def _check_kirmizi_exits_tick(self, symbol, price):
        to_close = []
        with self._lock:
            for trade in list(self.trades):
                if trade.symbol != symbol or trade.ecosystem != "kirmizi":
                    continue
                self._activate_chandelier_if_ready(trade, price)
                if self.check_winrate(trade, price):
                    to_close.append((trade, "Winrate"))
                elif self.check_lose_exit(trade, price):
                    to_close.append((trade, "Lose Exit"))
                elif self.update_chandelier(trade, price):
                    to_close.append((trade, "Chandelier"))

        for trade, reason in to_close:
            close_info = self.executor.close_trade(trade, reason, price)
            if close_info:
                self.remove_trade(trade)
                if self.telegram:
                    self.telegram.send_trade_closed(close_info)

    def _check_mavi_exits_tick(self, symbol, price, prev_price):
        ind = self.data_pool.get_indicators(symbol)
        if not ind:
            return

        kc_upper = ind.get("kc_red_upper", [])
        kc_lower = ind.get("kc_red_lower", [])
        kc_outer_upper = ind.get("kc_red_outer_upper", [])
        kc_outer_lower = ind.get("kc_red_outer_lower", [])

        if not kc_upper or not kc_lower:
            return

        cur_upper = kc_upper[-1]
        cur_lower = kc_lower[-1]
        cur_outer_upper = kc_outer_upper[-1]
        cur_outer_lower = kc_outer_lower[-1]

        to_close = []
        with self._lock:
            for trade in list(self.trades):
                if trade.symbol != symbol or trade.ecosystem != "mavi":
                    continue
                if trade.side == "short":
                    if price <= cur_lower:
                        to_close.append((trade, "Alt Bant"))
                    elif (prev_price is not None
                          and prev_price <= cur_outer_upper and price > cur_outer_upper):
                        to_close.append((trade, "Dis Ust Bant"))
                else:
                    if price >= cur_upper:
                        to_close.append((trade, "Ust Bant"))
                    elif (prev_price is not None
                          and prev_price >= cur_outer_lower and price < cur_outer_lower):
                        to_close.append((trade, "Dis Alt Bant"))

        for trade, reason in to_close:
            close_info = self.executor.close_trade(trade, reason, price)
            if close_info:
                self.remove_trade(trade)
                if self.telegram:
                    self.telegram.send_trade_closed(close_info)
