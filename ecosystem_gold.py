import time
from ecosystem_base import EcosystemBase, Trade, HedgeTrade
from logger_setup import get_logger

log = get_logger("ecosystem_gold")


class GoldEcosystem(EcosystemBase):
    def __init__(self, config, data_pool, trade_executor, telegram_bot=None):
        super().__init__("gold", config, data_pool, trade_executor, telegram_bot)

    def _get_band_levels(self, symbol):
        ind = self.data_pool.get_indicators(symbol)
        ema21 = ind.get("ema21", [])
        atr21 = ind.get("atr21", [])
        if not ema21 or not atr21:
            return None
        ema = ema21[-1]
        atr = atr21[-1]
        if ema <= 0 or atr <= 0:
            return None

        carpanlar = self.config.get("bant_carpanlari", [0.25, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])

        levels = {"ema": ema, "atr": atr}
        for i, c in enumerate(carpanlar, 1):
            levels[f"ust{i}"] = ema + c * atr
            levels[f"alt{i}"] = ema - c * atr

        return levels

    def on_tick(self, symbol, price):
        if not self.active:
            return

        levels = self._get_band_levels(symbol)
        if not levels:
            return

        ema = levels["ema"]
        atr = levels["atr"]
        alt1 = levels.get("alt1", 0)
        alt2 = levels.get("alt2", 0)
        ust1 = levels.get("ust1", 0)
        ust2 = levels.get("ust2", 0)
        ust3 = levels.get("ust3", 0)
        alt3 = levels.get("alt3", 0)
        alt7 = levels.get("alt7", 0)
        ust7 = levels.get("ust7", 0)

        # --- SHORT ---
        # Flag: fiyat EMA21'i aşağı keserse
        if price < ema:
            if not self.has_flag(symbol, "short"):
                self.set_flag(symbol, "short", True)
        elif price > ema:
            self.clear_flag(symbol, "short")

        # Giriş: Alt 1'i aşağı keserse + Flag açıksa
        if price < alt1 and self.has_flag(symbol, "short"):
            if self.can_open_trade():
                self._open_trade(symbol, price, levels, "short")
                self.clear_flag(symbol, "short")

        # --- LONG (simetri) ---
        if price > ema:
            if not self.has_flag(symbol, "long"):
                self.set_flag(symbol, "long", True)
        elif price < ema:
            self.clear_flag(symbol, "long")

        if price > ust1 and self.has_flag(symbol, "long"):
            if self.can_open_trade():
                self._open_trade(symbol, price, levels, "long")
                self.clear_flag(symbol, "long")

        # --- Hedge kontrolü ---
        self._check_hedge_entries(symbol, price, levels)

        # --- Çıkış kontrolleri (dinamik seviyeler) ---
        self._check_exits(symbol, price, levels)

    def _open_trade(self, symbol, price, levels, side):
        atr = levels["atr"]

        # Gold dinamik seviyeli; açılış anındaki referans değerleri tabloya yaz (info amaçlı)
        if side == "short":
            lose_exit_initial = levels.get("ust3", 0)
            winrate_initial = levels.get("alt7", 0)
        else:
            lose_exit_initial = levels.get("alt3", 0)
            winrate_initial = levels.get("ust7", 0)

        table = {
            "side": side,
            "entry": price,
            "lose_exit": lose_exit_initial,
            "winrate": winrate_initial,
            "chandelier_distance": self.config.get("chandelier_atr_carpani", 1) * atr,
            "atr": atr,
            "chandelier_started": False,
            "dynamic": True  # Gold dinamik - değerler bilgi amaçlı, gerçek kontrol _check_exits'te
        }

        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="GOLD", entry_price=price
        )

        if trade_info:
            trade = Trade(
                symbol=symbol, side=side, ecosystem="gold",
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

            log.info("GOLD %s acildi: %s @ %.4f", side.upper(), symbol, price)

    def _check_exits(self, symbol, price, levels):
        atr = levels["atr"]
        ust3 = levels.get("ust3", 0)
        alt3 = levels.get("alt3", 0)
        alt7 = levels.get("alt7", 0)
        ust7 = levels.get("ust7", 0)
        alt2 = levels.get("alt2", 0)
        ust2 = levels.get("ust2", 0)

        trades_to_close = []

        with self._lock:
            for trade in list(self.trades):
                if trade.symbol != symbol:
                    continue

                chandelier_dist = self.config.get("chandelier_atr_carpani", 1) * atr

                if trade.side == "short":
                    # Chandelier başlangıç: Alt 2'yi aşağı kesince başlar
                    if not trade.chandelier_active and price < alt2:
                        trade.chandelier_active = True
                        trade.chandelier_extreme = price
                        trade.table["chandelier_distance"] = chandelier_dist
                        log.debug("GOLD short chandelier basladi: %s @ %.4f", symbol, price)

                    # Chandelier kontrolü
                    if trade.chandelier_active:
                        trade.table["chandelier_distance"] = chandelier_dist
                        if price < trade.chandelier_extreme:
                            trade.chandelier_extreme = price
                        chandelier_level = trade.chandelier_extreme + chandelier_dist
                        if price >= chandelier_level:
                            trades_to_close.append((trade, "Chandelier"))
                            continue

                    # Lose Exit: Üst 3 (dinamik)
                    if price >= ust3:
                        trades_to_close.append((trade, "Lose Exit"))
                        continue

                    # Winrate: Alt 7 (dinamik)
                    if price <= alt7:
                        trades_to_close.append((trade, "Winrate"))
                        continue

                else:  # long
                    # Chandelier başlangıç: Üst 2'yi yukarı kesince başlar
                    if not trade.chandelier_active and price > ust2:
                        trade.chandelier_active = True
                        trade.chandelier_extreme = price
                        trade.table["chandelier_distance"] = chandelier_dist
                        log.debug("GOLD long chandelier basladi: %s @ %.4f", symbol, price)

                    if trade.chandelier_active:
                        trade.table["chandelier_distance"] = chandelier_dist
                        if price > trade.chandelier_extreme:
                            trade.chandelier_extreme = price
                        chandelier_level = trade.chandelier_extreme - chandelier_dist
                        if price <= chandelier_level:
                            trades_to_close.append((trade, "Chandelier"))
                            continue

                    # Lose Exit: Alt 3 (dinamik)
                    if price <= alt3:
                        trades_to_close.append((trade, "Lose Exit"))
                        continue

                    # Winrate: Üst 7 (dinamik)
                    if price >= ust7:
                        trades_to_close.append((trade, "Winrate"))
                        continue

        for trade, reason in trades_to_close:
            close_info = self.executor.close_trade(trade, reason, price)
            if close_info:
                self.remove_trade(trade)
                if self.telegram:
                    self.telegram.send_trade_closed(close_info)

        # Hedge çıkışları
        hedge_to_close = []
        with self._lock:
            for hedge in list(self.hedge_trades):
                if hedge.symbol != symbol:
                    continue

                if isinstance(hedge, HedgeTrade):
                    parent = hedge.parent_trade
                    if parent not in self.trades:
                        hedge_to_close.append((hedge, "Bagli islem kapandi"))
                        continue

                if hedge.side == "long":
                    alt1 = levels.get("alt1", 0)
                    if price < alt1:
                        hedge_to_close.append((hedge, "Alt 1 altina dustu"))
                        continue
                    if price >= ust3:
                        hedge_to_close.append((hedge, "Ust 3 hedefine ulasti"))
                        continue
                else:
                    ust1 = levels.get("ust1", 0)
                    if price > ust1:
                        hedge_to_close.append((hedge, "Ust 1 ustune cikti"))
                        continue
                    if price <= alt3:
                        hedge_to_close.append((hedge, "Alt 3 hedefine ulasti"))
                        continue

        for hedge, reason in hedge_to_close:
            close_info = self.executor.close_trade(hedge, reason, price)
            if close_info:
                self.remove_hedge_trade(hedge)
                if self.telegram:
                    self.telegram.send_trade_closed(close_info)

    def _check_hedge_entries(self, symbol, price, levels):
        ema = levels["ema"]
        alt1 = levels.get("alt1", 0)
        ust1 = levels.get("ust1", 0)

        with self._lock:
            main_trades = [t for t in self.trades if t.symbol == symbol]

        for main_trade in main_trades:
            flag_key = f"silver_hedge_{id(main_trade)}"

            if main_trade.side == "short":
                # Silver Long: Flag → Alt 1'i yukarı keserse, Giriş → EMA21'i yukarı keserse
                if price > alt1:
                    if not self.has_flag(symbol, flag_key):
                        self.set_flag(symbol, flag_key, True)

                if price > ema and self.has_flag(symbol, flag_key):
                    existing = self.find_hedge_trades_for_parent(main_trade)
                    if not existing:
                        self._open_hedge(main_trade, symbol, price, "long")
                        self.clear_flag(symbol, flag_key)

                if price < alt1:
                    self.clear_flag(symbol, flag_key)

            else:  # main long
                # Silver Short: Flag → Üst 1'i aşağı keserse, Giriş → EMA21'i aşağı keserse
                if price < ust1:
                    if not self.has_flag(symbol, flag_key):
                        self.set_flag(symbol, flag_key, True)

                if price < ema and self.has_flag(symbol, flag_key):
                    existing = self.find_hedge_trades_for_parent(main_trade)
                    if not existing:
                        self._open_hedge(main_trade, symbol, price, "short")
                        self.clear_flag(symbol, flag_key)

                if price > ust1:
                    self.clear_flag(symbol, flag_key)

    def _open_hedge(self, parent_trade, symbol, price, side):
        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="SILVER", entry_price=price
        )

        if trade_info:
            table = {
                "side": side,
                "entry": price,
            }

            hedge = HedgeTrade(
                parent_trade=parent_trade,
                symbol=symbol, side=side, ecosystem="silver",
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

            log.info("SILVER %s acildi: %s @ %.4f", side.upper(), symbol, price)
