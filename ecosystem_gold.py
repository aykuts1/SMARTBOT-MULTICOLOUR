from ecosystem_base import EcosystemBase, Trade
from trade_table import create_gold_table
from logger_setup import get_logger

log = get_logger("ecosystem_gold")


class GoldEcosystem(EcosystemBase):
    def __init__(self, config, data_pool, trade_executor, telegram_bot=None):
        super().__init__("altin", config, data_pool, trade_executor, telegram_bot)
        self.max_trades = config.get("max_altin_islem", 10)
        self._prev_prices = {}

    def on_candle_close(self, symbol, candle):
        if not self.active:
            return

        ind = self.data_pool.get_indicators(symbol)
        if not ind:
            return

        kdj_j = ind.get("kdj_j", [])
        kc_upper = ind.get("kc_upper", [])
        kc_lower = ind.get("kc_lower", [])

        if len(kdj_j) < 2 or not kc_upper or not kc_lower:
            return

        current_j = kdj_j[-1]
        prev_j = kdj_j[-2]
        current_kc_upper = kc_upper[-1]
        current_kc_lower = kc_lower[-1]

        if current_kc_upper <= 0 or current_kc_lower <= 0:
            return

        close = candle["close"]
        candle_high = candle["high"]
        candle_low = candle["low"]

        # SHORT: J 100'ün altına cross + fiyat Keltner altında + tüm mum bandın altında
        if (prev_j >= 100 and current_j < 100
                and close < current_kc_lower
                and candle_high < current_kc_lower):
            if self.can_open_trade():
                self._open_trade(symbol, close, "short")

        # LONG: J 0'ın üstüne cross + fiyat Keltner üstünde + tüm mum bandın üstünde
        if (prev_j <= 0 and current_j > 0
                and close > current_kc_upper
                and candle_low > current_kc_upper):
            if self.can_open_trade():
                self._open_trade(symbol, close, "long")

        self._check_exits_candle(symbol, close)

    def _open_trade(self, symbol, price, side):
        table = create_gold_table(price, side, self.config)

        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="ALTIN", entry_price=price
        )

        if trade_info:
            trade = Trade(
                symbol=symbol, side=side, ecosystem="altin",
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

            log.info("ALTIN %s acildi: %s @ %.4f", side.upper(), symbol, price)

    def on_tick(self, symbol, price):
        if not self.active:
            return
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

    def _check_exits_candle(self, symbol, price):
        self._check_exits_tick(symbol, price)

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
