import time
from ecosystem_base import EcosystemBase, Trade
from trade_table import create_white_table
from indicators import detect_crossover_down, detect_crossover_up
from logger_setup import get_logger

log = get_logger("ecosystem_white")


class WhiteEcosystem(EcosystemBase):
    def __init__(self, config, data_pool, trade_executor, telegram_bot=None):
        super().__init__("beyaz", config, data_pool, trade_executor, telegram_bot)
        self.max_trades = config.get("max_beyaz_islem", 10)
        self.pending_signals = {}
        self._last_scan = {}

    def on_candle_close(self, symbol, candle):
        if not self.active:
            return

        ind = self.data_pool.get_indicators(symbol)
        if not ind:
            return

        stoch_k = ind.get("stoch_k", [])
        stoch_d = ind.get("stoch_d", [])
        macd = ind.get("macd", [])
        macd_sig = ind.get("macd_signal", [])
        ema_main = ind.get("ema_main", [])
        atr_main = ind.get("atr_main", [])

        if not stoch_k or not stoch_d or not macd or not macd_sig:
            return
        if not ema_main or not atr_main:
            return

        idx = len(stoch_k) - 1
        if idx < 1:
            return

        current_ema = ema_main[-1]
        current_atr = atr_main[-1]
        current_price = candle["close"]

        if current_ema <= 0 or current_atr <= 0:
            return

        stoch_down = detect_crossover_down(stoch_k, stoch_d, idx)
        stoch_up = detect_crossover_up(stoch_k, stoch_d, idx)
        macd_down = detect_crossover_down(macd, macd_sig, idx)
        macd_up = detect_crossover_up(macd, macd_sig, idx)

        # --- SHORT ---
        self._process_signal(
            symbol, current_price, current_ema, current_atr,
            stoch_down, macd_down, "short"
        )

        # --- LONG (simetri) ---
        self._process_signal(
            symbol, current_price, current_ema, current_atr,
            stoch_up, macd_up, "long"
        )

        self._age_pending_signals(symbol)
        self._check_exits_candle(symbol, current_price)

    def _process_signal(self, symbol, price, ema, atr, signal_a, signal_b, side):
        cfg = self.config
        max_wait = cfg.get("bekleme_mum_sayisi", 5)
        key = f"{symbol}||{side}"

        both_same_candle = signal_a and signal_b

        if both_same_candle:
            if side == "short" and price >= ema:
                return
            if side == "long" and price <= ema:
                return

            if self.can_open_trade():
                self._open_trade(symbol, price, atr, side)
            return

        if signal_a or signal_b:
            if key not in self.pending_signals:
                first = "stoch" if signal_a else "macd"
                self.pending_signals[key] = {
                    "first_signal": first,
                    "candles_remaining": max_wait,
                    "time": time.time()
                }
                log.debug("BEYAZ %s flag acildi: %s (%s kesti)", side, symbol, first)
                return

        if key in self.pending_signals:
            pending = self.pending_signals[key]
            second_signal = False

            if pending["first_signal"] == "stoch" and signal_b:
                second_signal = True
            elif pending["first_signal"] == "macd" and signal_a:
                second_signal = True

            if second_signal:
                if side == "short" and price >= ema:
                    del self.pending_signals[key]
                    log.debug("BEYAZ %s sinyal atlandi (EMA ustu): %s", side, symbol)
                    return
                if side == "long" and price <= ema:
                    del self.pending_signals[key]
                    log.debug("BEYAZ %s sinyal atlandi (EMA alti): %s", side, symbol)
                    return

                del self.pending_signals[key]
                if self.can_open_trade():
                    self._open_trade(symbol, price, atr, side)

    def _age_pending_signals(self, symbol):
        keys_to_remove = []
        for key, pending in self.pending_signals.items():
            if key.startswith(f"{symbol}||"):
                pending["candles_remaining"] -= 1
                if pending["candles_remaining"] <= 0:
                    keys_to_remove.append(key)
                    log.debug("BEYAZ flag suresi doldu: %s", key)

        for key in keys_to_remove:
            del self.pending_signals[key]

    def _open_trade(self, symbol, price, atr, side):
        table = create_white_table(price, atr, self.config, side)

        trade_info = self.executor.open_trade(
            symbol=symbol, side=side,
            ecosystem="BEYAZ", entry_price=price
        )

        if trade_info:
            trade = Trade(
                symbol=symbol, side=side, ecosystem="beyaz",
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

            log.info("BEYAZ %s acildi: %s @ %.4f", side.upper(), symbol, price)

    def on_tick(self, symbol, price):
        if not self.active:
            return
        self._check_exits_tick(symbol, price)

    def _check_exits_candle(self, symbol, price):
        self._check_exits_tick(symbol, price)

    def _activate_chandelier_if_ready(self, trade, price):
        if trade.chandelier_active:
            return
        atr = trade.table.get("atr", 0)
        entry = trade.table.get("entry", trade.entry_price)
        if atr <= 0:
            return
        activated = False
        if trade.side == "short" and price <= entry - atr:
            trade.chandelier_active = True
            trade.chandelier_extreme = price
            activated = True
        elif trade.side == "long" and price >= entry + atr:
            trade.chandelier_active = True
            trade.chandelier_extreme = price
            activated = True

        if activated and self.telegram:
            chandelier_dist = trade.table.get("chandelier_distance", 0)
            if trade.side == "short":
                chandelier_level = price + chandelier_dist
            else:
                chandelier_level = price - chandelier_dist
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
        for key, val in self.pending_signals.items():
            parts = key.split("||", 1)
            if len(parts) == 2:
                flags.append({
                    "symbol": parts[0],
                    "flag_name": f"beyaz_{parts[1]}_pending",
                    "time": val.get("time", 0),
                    "extra": f"{val['first_signal']} kesti, {val['candles_remaining']}/5 mum"
                })
        return flags
