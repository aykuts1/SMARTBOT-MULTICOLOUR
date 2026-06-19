import time
from ecosystem_base import EcosystemBase, Trade
from trade_table import create_yellow_table
from logger_setup import get_logger

log = get_logger("ecosystem_yellow")


class YellowEcosystem(EcosystemBase):
    def __init__(self, config, data_pool, trade_executor, telegram_bot=None):
        super().__init__("sari", config, data_pool, trade_executor, telegram_bot)
        self.max_trades = config.get("max_sari_islem", 10)
        self.touch_counters = {}
        self._prev_prices = {}
        self._last_scan = {}

    def on_candle_close(self, symbol, candle):
        if not self.active:
            return

        ind = self.data_pool.get_indicators(symbol)
        if not ind:
            return

        bb_upper = ind.get("bb_upper", [])
        bb_middle = ind.get("bb_middle", [])
        bb_lower = ind.get("bb_lower", [])

        if not bb_upper or not bb_middle or not bb_lower:
            return

        current_bb_upper = bb_upper[-1]
        current_bb_middle = bb_middle[-1]
        current_bb_lower = bb_lower[-1]

        if current_bb_lower <= 0 or current_bb_upper <= 0:
            return

        candle_low = candle["low"]
        candle_high = candle["high"]
        required = self.config.get("ardarda_temas_sayisi", 3)

        # --- SHORT: low Bollinger alt çizgisine temas ---
        short_key = f"{symbol}||short"
        if candle_low <= current_bb_lower:
            self.touch_counters[short_key] = self.touch_counters.get(short_key, 0) + 1
            log.debug("SARI short temas: %s %d/%d",
                      symbol, self.touch_counters[short_key], required)

            if self.touch_counters[short_key] >= required:
                self.touch_counters[short_key] = 0
                if self.can_open_trade() and not self.has_trade_for_symbol(symbol, "short"):
                    self._open_trade(symbol, candle["close"], current_bb_middle, "short")
        else:
            if short_key in self.touch_counters:
                self.touch_counters[short_key] = 0

        # --- LONG (simetri): high Bollinger üst çizgisine temas ---
        long_key = f"{symbol}||long"
        if candle_high >= current_bb_upper:
            self.touch_counters[long_key] = self.touch_counters.get(long_key, 0) + 1
            log.debug("SARI long temas: %s %d/%d",
                      symbol, self.touch_counters[long_key], required)

            if self.touch_counters[long_key] >= required:
                self.touch_counters[long_key] = 0
                if self.can_open_trade() and not self.has_trade_for_symbol(symbol, "long"):
                    self._open_trade(symbol, candle["close"], current_bb_middle, "long")
        else:
            if long_key in self.touch_counters:
                self.touch_counters[long_key] = 0

        self._check_exits_candle(symbol, candle["close"])

    def _open_trade(self, symbol, price, bb_middle, side):
        table = create_yellow_table(price, bb_middle, self.config, side)

        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="SARI", entry_price=price
        )

        if trade_info:
            trade = Trade(
                symbol=symbol, side=side, ecosystem="sari",
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

            log.info("SARI %s acildi: %s @ %.4f", side.upper(), symbol, price)

    def on_tick(self, symbol, price):
        if not self.active:
            return
        self._check_exits_tick(symbol, price)

    def _check_exits_candle(self, symbol, price):
        self._check_exits_tick(symbol, price)

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

    def _check_exits_tick(self, symbol, price):
        trades_to_close = []
        with self._lock:
            for trade in list(self.trades):
                if trade.symbol != symbol:
                    continue
                self._activate_chandelier_if_ready(trade, price)
                if self.check_winrate(trade, price):
                    trades_to_close.append((trade, "Winrate"))
                elif self.check_lose_exit(trade, price):
                    trades_to_close.append((trade, "Lose Exit"))
                elif self.update_chandelier(trade, price):
                    trades_to_close.append((trade, "Chandelier"))

        for trade, reason in trades_to_close:
            close_info = self.executor.close_trade(trade, reason, price)
            if close_info:
                self.remove_trade(trade)
                if self.telegram:
                    self.telegram.send_trade_closed(close_info)

    def get_open_flags(self):
        flags = super().get_open_flags()
        for key, count in self.touch_counters.items():
            if count > 0:
                parts = key.split("||", 1)
                if len(parts) == 2:
                    flags.append({
                        "symbol": parts[0],
                        "flag_name": f"sari_{parts[1]}_temas",
                        "time": time.time(),
                        "extra": f"Temas: {count}/{self.config.get('ardarda_temas_sayisi', 3)}"
                    })
        return flags
