import time
from ecosystem_base import EcosystemBase, Trade, HedgeTrade
from trade_table import create_red_table
from logger_setup import get_logger

log = get_logger("ecosystem_red")


class ScaleTrade(Trade):
    def __init__(self, parent_trade, **kwargs):
        super().__init__(**kwargs)
        self.parent_trade = parent_trade


class RedEcosystem(EcosystemBase):
    def __init__(self, config, data_pool, trade_executor, telegram_bot=None):
        super().__init__("kirmizi", config, data_pool, trade_executor, telegram_bot)
        self._prev_prices = {}
        self._scale_trades = []

    def get_trade_count(self):
        with self._lock:
            return len(self.trades) + len(self._scale_trades)

    def get_all_trades(self):
        with self._lock:
            return list(self.trades) + list(self._scale_trades) + list(self.hedge_trades)

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

        prev_price = self._prev_prices.get(symbol)
        self._prev_prices[symbol] = price

        if prev_price is not None:
            self._check_entries(symbol, price, prev_price)

        self._check_hedge_entries(symbol, price)
        self._check_all_exits(symbol, price)

    def _check_entries(self, symbol, price, prev_price):
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
        if prev_price > short_alt1 and price < short_alt1:
            if not self.has_flag(symbol, "short_block"):
                self.set_flag(symbol, "short", True)
                log.debug("KIRMIZI short bayrak acildi: %s", symbol)

        if prev_price < short_alt1 and price > short_alt1:
            self.clear_flag(symbol, "short")
            self.clear_flag(symbol, "short_block")

        if (prev_price > short_alt2 and price < short_alt2
                and self.has_flag(symbol, "short")
                and not self.has_flag(symbol, "short_block")):
            if self.can_open_trade() and not self.has_trade_for_symbol(symbol, "short"):
                self.set_flag(symbol, "short_block", True)
                self.clear_flag(symbol, "short")
                self._open_main_trade(symbol, price, ema, atr, "short")

        # --- LONG ---
        if prev_price < long_ust1 and price > long_ust1:
            if not self.has_flag(symbol, "long_block"):
                self.set_flag(symbol, "long", True)
                log.debug("KIRMIZI long bayrak acildi: %s", symbol)

        if prev_price > long_ust1 and price < long_ust1:
            self.clear_flag(symbol, "long")
            self.clear_flag(symbol, "long_block")

        if (prev_price < long_ust2 and price > long_ust2
                and self.has_flag(symbol, "long")
                and not self.has_flag(symbol, "long_block")):
            if self.can_open_trade() and not self.has_trade_for_symbol(symbol, "long"):
                self.set_flag(symbol, "long_block", True)
                self.clear_flag(symbol, "long")
                self._open_main_trade(symbol, price, ema, atr, "long")

        # --- Scale girişleri ---
        self._check_scale_entries(symbol, price, prev_price)

    def _check_scale_entries(self, symbol, price, prev_price):
        with self._lock:
            main_trades = [t for t in self.trades if t.symbol == symbol]

        for main_trade in main_trades:
            side = main_trade.side
            zone3 = main_trade.table.get("zone3_entry", 0)
            zone5 = main_trade.table.get("zone5_entry", 0)

            flag_z3 = f"scale_z3_{id(main_trade)}"
            flag_z5 = f"scale_z5_{id(main_trade)}"

            if side == "short":
                # Zone3 crossover aşağı
                if zone3 > 0 and prev_price > zone3 and price < zone3:
                    if not self.has_flag(symbol, flag_z3):
                        self.set_flag(symbol, flag_z3, True)
                        self._open_scale_trade(main_trade, symbol, price, side)

                # Zone5 crossover aşağı
                if zone5 > 0 and prev_price > zone5 and price < zone5:
                    if not self.has_flag(symbol, flag_z5):
                        self.set_flag(symbol, flag_z5, True)
                        self._open_scale_trade(main_trade, symbol, price, side)
            else:
                # Zone3 crossover yukarı
                if zone3 > 0 and prev_price < zone3 and price > zone3:
                    if not self.has_flag(symbol, flag_z3):
                        self.set_flag(symbol, flag_z3, True)
                        self._open_scale_trade(main_trade, symbol, price, side)

                # Zone5 crossover yukarı
                if zone5 > 0 and prev_price < zone5 and price > zone5:
                    if not self.has_flag(symbol, flag_z5):
                        self.set_flag(symbol, flag_z5, True)
                        self._open_scale_trade(main_trade, symbol, price, side)

    def _open_scale_trade(self, parent_trade, symbol, price, side):
        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="KIRMIZI", entry_price=price,
            fixed_qty=parent_trade.qty
        )

        if trade_info:
            atr = parent_trade.table.get("atr", 0)
            if side == "short":
                winrate = price - 2.5 * atr
                lose_exit = price + 1.0 * atr
            else:
                winrate = price + 2.5 * atr
                lose_exit = price - 1.0 * atr

            table = {
                "side": side,
                "entry": price,
                "lose_exit": lose_exit,
                "winrate": winrate,
                "atr": atr,
            }

            scale = ScaleTrade(
                parent_trade=parent_trade,
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

            with self._lock:
                self._scale_trades.append(scale)

            if self.telegram:
                self.telegram.send_trade_opened(trade_info, table)

            log.info("KIRMIZI SCALE %s acildi: %s @ %.4f (qty: %.6f)",
                     side.upper(), symbol, price, parent_trade.qty)

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

    def _check_hedge_entries(self, symbol, price):
        with self._lock:
            main_trades = list(self.trades)

        for main_trade in main_trades:
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
        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="MAVI", entry_price=price
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
            self.add_hedge_trade(hedge)

            if self.telegram:
                self.telegram.send_trade_opened(trade_info, table)

            log.info("MAVI %s acildi: %s @ %.4f", side.upper(), symbol, price)

    def _check_all_exits(self, symbol, price):
        trades_to_close = []

        with self._lock:
            for trade in list(self.trades):
                if trade.symbol != symbol:
                    continue
                reason = self._check_exit_condition(trade, price)
                if reason:
                    trades_to_close.append((trade, reason))

        for trade, reason in trades_to_close:
            self._close_trade(trade, reason, price)
            # Ana işlem CE veya Lose Exit ile kapandıysa scale trade'ler de kapanır
            if reason in ("Lose Exit", "Chandelier"):
                self._close_scales_for_parent(trade, reason, price)

        # Scale trade'lerin kendi winrate ve lose exit kontrolü
        scale_to_close = []
        with self._lock:
            for scale in list(self._scale_trades):
                if scale.symbol != symbol:
                    continue
                if self.check_winrate(scale, price):
                    scale_to_close.append((scale, "Winrate"))
                elif self.check_lose_exit(scale, price):
                    scale_to_close.append((scale, "Lose Exit"))

        for scale, reason in scale_to_close:
            self._close_scale_trade(scale, reason, price)

        hedge_to_close = []
        with self._lock:
            for hedge in list(self.hedge_trades):
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

    def _close_trade(self, trade, reason, price):
        close_info = self.executor.close_trade(trade, reason, price)
        if close_info:
            self.remove_trade(trade)
            if self.telegram:
                self.telegram.send_trade_closed(close_info)

    def _close_scales_for_parent(self, parent_trade, reason, price):
        with self._lock:
            scales = [s for s in self._scale_trades if s.parent_trade is parent_trade]
        for scale in scales:
            self._close_scale_trade(scale, reason, price)

    def _close_scale_trade(self, scale, reason, price):
        close_info = self.executor.close_trade(scale, reason, price)
        if close_info:
            with self._lock:
                if scale in self._scale_trades:
                    self._scale_trades.remove(scale)
            if self.telegram:
                self.telegram.send_trade_closed(close_info)

    def _close_hedge(self, hedge, reason, price):
        close_info = self.executor.close_trade(hedge, reason, price)
        if close_info:
            self.remove_hedge_trade(hedge)
            if self.telegram:
                self.telegram.send_trade_closed(close_info)
