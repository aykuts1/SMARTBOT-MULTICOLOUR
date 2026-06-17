import time
from ecosystem_base import EcosystemBase, Trade, HedgeTrade
from trade_table import create_red_table, create_red_sub_table
from logger_setup import get_logger

log = get_logger("ecosystem_red")


class RedEcosystem(EcosystemBase):
    def __init__(self, config, data_pool, trade_executor, telegram_bot=None):
        super().__init__("kirmizi", config, data_pool, trade_executor, telegram_bot)
        self.sub_trades_1 = []
        self.sub_trades_2 = []
        self.hedge_trades_1 = []
        self.hedge_trades_2 = []

    def get_trade_count(self):
        with self._lock:
            return len(self.trades) + len(self.sub_trades_1) + len(self.sub_trades_2)

    def _get_band_levels(self, symbol):
        ind = self.data_pool.get_indicators(symbol)
        ema48 = ind.get("ema48", [])
        atr48 = ind.get("atr48", [])
        if not ema48 or not atr48:
            return None
        ema = ema48[-1]
        atr = atr48[-1]
        if ema <= 0 or atr <= 0:
            return None
        return {"ema": ema, "atr": atr}

    def on_tick(self, symbol, price):
        if not self.active:
            return

        band = self._get_band_levels(symbol)
        if not band:
            return

        ema = band["ema"]
        atr = band["atr"]
        cfg = self.config

        flag_atr = cfg.get("flag_giris_atr", 1)
        entry_atr = cfg.get("islem_giris_atr", 2)

        short_alt1 = ema - flag_atr * atr
        short_alt2 = ema - entry_atr * atr
        long_ust1 = ema + flag_atr * atr
        long_ust2 = ema + entry_atr * atr

        # --- SHORT ---
        if price < short_alt1:
            if not self.has_flag(symbol, "short"):
                self.set_flag(symbol, "short", True)
        elif price > short_alt1:
            self.clear_flag(symbol, "short")

        if price < short_alt2 and self.has_flag(symbol, "short"):
            if self.can_open_trade():
                self._open_main_trade(symbol, price, ema, atr, "short")
                self.clear_flag(symbol, "short")

        # --- LONG (simetri) ---
        if price > long_ust1:
            if not self.has_flag(symbol, "long"):
                self.set_flag(symbol, "long", True)
        elif price < long_ust1:
            self.clear_flag(symbol, "long")

        if price > long_ust2 and self.has_flag(symbol, "long"):
            if self.can_open_trade():
                self._open_main_trade(symbol, price, ema, atr, "long")
                self.clear_flag(symbol, "long")

        # --- Alt işlemler (Kırmızı 1, Kırmızı 2) kontrolü ---
        self._check_sub_entries(symbol, price, ema, atr)

        # --- Hedge kontrolü ---
        self._check_hedge_entries(symbol, price)

        # --- Çıkış kontrolleri ---
        self._check_all_exits(symbol, price)

    def _open_main_trade(self, symbol, price, ema, atr, side):
        table = create_red_table(price, ema, atr, side)

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
            self.add_trade(trade)

            if self.telegram:
                self.telegram.send_trade_opened(trade_info, table)

            log.info("KIRMIZI %s acildi: %s @ %.4f", side.upper(), symbol, price)

    def _check_sub_entries(self, symbol, price, ema, atr):
        cfg = self.config
        k1_atr = cfg.get("kirmizi_1_giris_atr", 4)
        k2_atr = cfg.get("kirmizi_2_giris_atr", 6)

        with self._lock:
            main_trades = [t for t in self.trades if t.symbol == symbol]

        for main_trade in main_trades:
            side = main_trade.side

            if side == "short":
                k1_level = ema - k1_atr * atr
                k2_level = ema - k2_atr * atr

                has_k1 = any(t for t in self.sub_trades_1
                             if t.symbol == symbol and t.side == side)
                if not has_k1 and price < k1_level and self.can_open_trade():
                    self._open_sub_trade(symbol, price, atr, side, 1)

                has_k2 = any(t for t in self.sub_trades_2
                             if t.symbol == symbol and t.side == side)
                if not has_k2 and price < k2_level and self.can_open_trade():
                    self._open_sub_trade(symbol, price, atr, side, 2)
            else:
                k1_level = ema + k1_atr * atr
                k2_level = ema + k2_atr * atr

                has_k1 = any(t for t in self.sub_trades_1
                             if t.symbol == symbol and t.side == side)
                if not has_k1 and price > k1_level and self.can_open_trade():
                    self._open_sub_trade(symbol, price, atr, side, 1)

                has_k2 = any(t for t in self.sub_trades_2
                             if t.symbol == symbol and t.side == side)
                if not has_k2 and price > k2_level and self.can_open_trade():
                    self._open_sub_trade(symbol, price, atr, side, 2)

    def _open_sub_trade(self, symbol, price, atr, side, level):
        cfg = self.config
        if level == 1:
            le_atr = cfg.get("kirmizi_1_lose_exit_atr", 2)
            wr_atr = cfg.get("kirmizi_1_winrate_atr", 5)
            eco_name = "KIRMIZI1"
        else:
            le_atr = cfg.get("kirmizi_2_lose_exit_atr", 2)
            wr_atr = cfg.get("kirmizi_2_winrate_atr", 5)
            eco_name = "KIRMIZI2"

        table = create_red_sub_table(price, atr, le_atr, wr_atr, side)

        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem=eco_name, entry_price=price
        )

        if trade_info:
            trade = Trade(
                symbol=symbol, side=side, ecosystem=eco_name.lower(),
                entry_price=price, qty=trade_info["qty"], table=table,
                order_link_id=trade_info["order_link_id"],
                open_time=trade_info["open_time"],
                margin=trade_info["margin"],
                commission=trade_info["commission"],
                leverage=trade_info["leverage"],
                sl_price=trade_info["sl_price"],
                order_id=trade_info["order_id"]
            )

            with self._lock:
                if level == 1:
                    self.sub_trades_1.append(trade)
                else:
                    self.sub_trades_2.append(trade)

            if self.telegram:
                self.telegram.send_trade_opened(trade_info, table)

            log.info("KIRMIZI %d %s acildi: %s @ %.4f", level, side.upper(), symbol, price)

    def _check_hedge_entries(self, symbol, price):
        all_main = []
        with self._lock:
            all_main = list(self.trades) + list(self.sub_trades_1) + list(self.sub_trades_2)

        for main_trade in all_main:
            if main_trade.symbol != symbol:
                continue

            hedge_side = "long" if main_trade.side == "short" else "short"
            entry_line = main_trade.table.get("entry", 0)
            hedge_line = main_trade.table.get("hedge_entry", 0)

            flag_key = f"hedge_{id(main_trade)}"

            if hedge_side == "long":
                if price > entry_line:
                    if not self.has_flag(symbol, flag_key):
                        self.set_flag(symbol, flag_key, True)
                elif price < entry_line:
                    self.clear_flag(symbol, flag_key)

                if price > hedge_line and self.has_flag(symbol, flag_key):
                    existing = self.find_hedge_trades_for_parent(main_trade)
                    if not existing:
                        self._open_hedge(main_trade, symbol, price, hedge_side)
                        self.clear_flag(symbol, flag_key)
            else:
                if price < entry_line:
                    if not self.has_flag(symbol, flag_key):
                        self.set_flag(symbol, flag_key, True)
                elif price > entry_line:
                    self.clear_flag(symbol, flag_key)

                if price < hedge_line and self.has_flag(symbol, flag_key):
                    existing = self.find_hedge_trades_for_parent(main_trade)
                    if not existing:
                        self._open_hedge(main_trade, symbol, price, hedge_side)
                        self.clear_flag(symbol, flag_key)

    def _open_hedge(self, parent_trade, symbol, price, side):
        eco_prefix = parent_trade.ecosystem.upper()
        if "1" in eco_prefix:
            hedge_eco = "MAVI1"
        elif "2" in eco_prefix:
            hedge_eco = "MAVI2"
        else:
            hedge_eco = "MAVI"

        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem=hedge_eco, entry_price=price
        )

        if trade_info:
            table = {
                "side": side,
                "entry": parent_trade.table.get("entry", price),
                "lose_exit": parent_trade.table.get("lose_exit", 0),
                "hedge_entry": parent_trade.table.get("hedge_entry", 0),
            }

            hedge = HedgeTrade(
                parent_trade=parent_trade,
                symbol=symbol, side=side, ecosystem=hedge_eco.lower(),
                entry_price=price, qty=trade_info["qty"], table=table,
                order_link_id=trade_info["order_link_id"],
                open_time=trade_info["open_time"],
                margin=trade_info["margin"],
                commission=trade_info["commission"],
                leverage=trade_info["leverage"],
                sl_price=trade_info["sl_price"],
                order_id=trade_info["order_id"]
            )

            with self._lock:
                if "1" in hedge_eco:
                    self.hedge_trades_1.append(hedge)
                elif "2" in hedge_eco:
                    self.hedge_trades_2.append(hedge)
                else:
                    self.hedge_trades.append(hedge)

            if self.telegram:
                self.telegram.send_trade_opened(trade_info, table)

            log.info("%s %s acildi: %s @ %.4f", hedge_eco, side.upper(), symbol, price)

    def _check_all_exits(self, symbol, price):
        trades_to_close = []

        with self._lock:
            for trade in list(self.trades):
                if trade.symbol != symbol:
                    continue
                reason = self._check_exit_condition(trade, price)
                if reason:
                    trades_to_close.append((trade, reason, "main"))

            for trade in list(self.sub_trades_1):
                if trade.symbol != symbol:
                    continue
                reason = self._check_exit_condition(trade, price)
                if reason:
                    trades_to_close.append((trade, reason, "sub1"))

            for trade in list(self.sub_trades_2):
                if trade.symbol != symbol:
                    continue
                reason = self._check_exit_condition(trade, price)
                if reason:
                    trades_to_close.append((trade, reason, "sub2"))

        for trade, reason, trade_type in trades_to_close:
            self._close_trade(trade, reason, price, trade_type)

        # Hedge çıkışları
        hedge_to_close = []
        with self._lock:
            all_hedges = (
                list(self.hedge_trades) +
                list(self.hedge_trades_1) +
                list(self.hedge_trades_2)
            )

        for hedge in all_hedges:
            if hedge.symbol != symbol:
                continue
            should_close, reason = self.check_hedge_exit(hedge, price)
            if should_close:
                hedge_to_close.append((hedge, reason))

        for hedge, reason in hedge_to_close:
            self._close_hedge(hedge, reason, price)

    def _check_exit_condition(self, trade, price):
        if self.check_winrate(trade, price):
            return "Winrate"
        if self.check_lose_exit(trade, price):
            return "Lose Exit"
        if self.update_chandelier(trade, price):
            return "Chandelier"
        return None

    def _close_trade(self, trade, reason, price, trade_type):
        close_info = self.executor.close_trade(trade, reason, price)
        if close_info:
            with self._lock:
                if trade_type == "main":
                    if trade in self.trades:
                        self.trades.remove(trade)
                elif trade_type == "sub1":
                    if trade in self.sub_trades_1:
                        self.sub_trades_1.remove(trade)
                elif trade_type == "sub2":
                    if trade in self.sub_trades_2:
                        self.sub_trades_2.remove(trade)

            if self.telegram:
                self.telegram.send_trade_closed(close_info)

    def _close_hedge(self, hedge, reason, price):
        close_info = self.executor.close_trade(hedge, reason, price)
        if close_info:
            with self._lock:
                if hedge in self.hedge_trades:
                    self.hedge_trades.remove(hedge)
                if hedge in self.hedge_trades_1:
                    self.hedge_trades_1.remove(hedge)
                if hedge in self.hedge_trades_2:
                    self.hedge_trades_2.remove(hedge)

            if self.telegram:
                self.telegram.send_trade_closed(close_info)

    def check_hedge_exit(self, hedge, price):
        if not isinstance(hedge, HedgeTrade):
            return False, ""

        parent = hedge.parent_trade
        with self._lock:
            all_trades = list(self.trades) + list(self.sub_trades_1) + list(self.sub_trades_2)
        if parent not in all_trades:
            return True, "Bagli islem kapandi"

        entry_line = hedge.table.get("entry", 0)
        if hedge.side == "long" and price < entry_line:
            return True, "Islem giris cizgisini asagi kesti"
        elif hedge.side == "short" and price > entry_line:
            return True, "Islem giris cizgisini yukari kesti"

        # Lose Exit: mavi LONG için yukarıda (kar tarafı), mor SHORT için aşağıda
        le = hedge.table.get("lose_exit", 0)
        if le > 0:
            if hedge.side == "long" and price >= le:
                return True, "Lose Exit"
            elif hedge.side == "short" and price <= le:
                return True, "Lose Exit"

        return False, ""

    def find_hedge_trades_for_parent(self, parent_trade):
        with self._lock:
            all_hedges = (list(self.hedge_trades) +
                          list(self.hedge_trades_1) +
                          list(self.hedge_trades_2))
            return [h for h in all_hedges
                    if isinstance(h, HedgeTrade) and h.parent_trade is parent_trade]

    def get_all_trades(self):
        with self._lock:
            return (list(self.trades) + list(self.sub_trades_1) +
                    list(self.sub_trades_2) + list(self.hedge_trades) +
                    list(self.hedge_trades_1) + list(self.hedge_trades_2))
