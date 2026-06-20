import time
import threading
from logger_setup import get_logger
from utils import (
    calc_position_size, calc_sl_price, calc_pnl,
    generate_order_link_id, format_usdt, qty_round_down, sl_round
)
import trade_history

log = get_logger("trade_executor")


class TradeExecutor:
    def __init__(self, bybit_client, config, telegram_bot=None):
        self.client = bybit_client
        self.config = config
        self.telegram = telegram_bot
        self._closing_threads = {}

    def reload_config(self, config):
        self.config = config

    def open_trade(self, symbol, side, ecosystem, entry_price=None, fixed_qty=None):
        cfg = self.config.get("global", {})
        max_retries = cfg.get("islem_acma_deneme", 3)
        retry_delay = cfg.get("islem_acma_bekleme_sn", 2)

        balance_info = self.client.get_balance()
        if not balance_info:
            log.error("%s %s: Bakiye alinamadi", symbol, ecosystem)
            return None

        balance = balance_info["total"]
        margin_pct = cfg.get("marjin_orani", 0.02)
        leverage = cfg.get("kaldirac", 50)
        sl_pct = cfg.get("stop_loss_orani", 0.02)

        price = entry_price or 0
        if price <= 0:
            log.error("%s: Fiyat alinamadi", symbol)
            return None

        if not self.client.instrument_info.get(symbol):
            log.warning("%s: Instrument bilgisi eksik, yeniden yukleniyor...", symbol)
            self.client.load_instrument_info([symbol])
            if not self.client.instrument_info.get(symbol):
                log.error("%s %s: Instrument bilgisi yuklenemedi, islem atlanıyor", symbol, ecosystem)
                return None

        min_qty = self.client.get_min_qty(symbol)
        qty_step = self.client.get_qty_step(symbol)

        if fixed_qty is not None:
            rounded_qty = fixed_qty
            actual_notional = rounded_qty * price
            margin = actual_notional / leverage
        else:
            qty, margin, notional = calc_position_size(balance, margin_pct, leverage, price)
            rounded_qty = qty_round_down(qty, qty_step)

        if rounded_qty < min_qty:
            log.warning("%s %s: Minimum buyukluk altinda (%.6f < %.6f)",
                        symbol, ecosystem, rounded_qty, min_qty)
            if self.telegram:
                self.telegram.send_min_size_alert(
                    symbol, ecosystem, rounded_qty, min_qty
                )
            return None

        if margin > balance_info["available"]:
            log.warning("%s %s: Yetersiz bakiye (%.2f > %.2f)",
                        symbol, ecosystem, margin, balance_info["available"])
            if self.telegram:
                self.telegram.send_insufficient_balance(
                    symbol, ecosystem, balance_info["available"], margin
                )
            return None

        sl_price = calc_sl_price(price, sl_pct, side)
        # SL'yi tick_size'a göre koruyucu yönde yuvarla (Telegram'da doğru göstermek için)
        tick_size = self.client.get_tick_size(symbol)
        sl_price = sl_round(0, sl_price, tick_size, side)
        order_link_id = generate_order_link_id(ecosystem.upper(), side.upper(), symbol)

        for attempt in range(1, max_retries + 1):
            result = self.client.place_order(
                symbol=symbol,
                side=side,
                qty=rounded_qty,
                sl_price=sl_price,
                order_link_id=order_link_id
            )

            if result["success"]:
                # Komisyonu yuvarlanmış miktarla hesapla (gerçek emir miktarı)
                actual_notional = rounded_qty * price
                commission = actual_notional * 0.00055
                actual_margin = actual_notional / leverage

                trade_info = {
                    "symbol": symbol,
                    "side": side,
                    "ecosystem": ecosystem,
                    "entry_price": price,
                    "qty": rounded_qty,
                    "margin": actual_margin,
                    "leverage": leverage,
                    "sl_price": sl_price,
                    "commission": commission,
                    "order_id": result["order_id"],
                    "order_link_id": order_link_id,
                    "open_time": time.time()
                }

                log.info("ISLEM ACILDI: %s %s %s giris=%.4f qty=%.6f",
                         symbol, side, ecosystem, price, rounded_qty)
                return trade_info

            log.warning("%s %s: Emir denemesi %d/%d basarisiz: %s",
                        symbol, ecosystem, attempt, max_retries, result.get("error", ""))

            if attempt < max_retries:
                time.sleep(retry_delay)

        log.error("%s %s: %d deneme basarisiz, sinyal atlaniyor",
                  symbol, ecosystem, max_retries)
        if self.telegram:
            self.telegram.send_order_error(
                symbol, ecosystem, max_retries, result.get("error", "Bilinmeyen hata")
            )
        return None

    def close_trade(self, trade, reason, current_price=None):
        # trade hem Trade objesi hem dict olabilir, ikisini de destekle
        if hasattr(trade, "symbol"):
            symbol = trade.symbol
            side = trade.side
            qty = trade.qty
            ecosystem = trade.ecosystem
            entry_price = trade.entry_price
            open_time = getattr(trade, "open_time", time.time())
            prev_commission = getattr(trade, "commission", 0)
        else:
            symbol = trade["symbol"]
            side = trade["side"]
            qty = trade["qty"]
            ecosystem = trade["ecosystem"]
            entry_price = trade["entry_price"]
            open_time = trade.get("open_time", time.time())
            prev_commission = trade.get("commission", 0)

        cfg = self.config.get("global", {})
        retry_delay = cfg.get("islem_kapatma_bekleme_sn", 2)
        alert_interval = cfg.get("kapatma_hatasi_bildirim_aralik_sn", 300)

        attempt = 0
        start_time = time.time()
        last_alert_time = 0
        first_error_sent = False

        while True:
            attempt += 1
            result = self.client.close_position(symbol, side, qty)

            if result["success"]:
                exit_price = current_price or entry_price
                pnl, pnl_pct = calc_pnl(entry_price, exit_price, qty, side)
                duration = time.time() - open_time
                commission = abs(exit_price * qty) * 0.00055
                total_commission = prev_commission + commission

                close_info = {
                    "symbol": symbol,
                    "side": side,
                    "ecosystem": ecosystem,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "qty": qty,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "duration": duration,
                    "reason": reason,
                    "commission": total_commission
                }

                log.info("ISLEM KAPANDI: %s %s %s cikis=%.4f pnl=%.2f (%s)",
                         symbol, side, ecosystem, exit_price, pnl, reason)
                trade_history.record(symbol, side, ecosystem, entry_price, exit_price, qty, pnl, reason)
                return close_info

            elapsed = time.time() - start_time

            if not first_error_sent:
                first_error_sent = True
                last_alert_time = time.time()
                log.error("KAPATMA HATASI: %s %s %s deneme=%d hata=%s",
                          symbol, side, ecosystem, attempt, result.get("error", ""))
                if self.telegram:
                    self.telegram.send_close_error(
                        symbol, ecosystem, reason, attempt,
                        result.get("error", ""), elapsed, first=True
                    )
            elif time.time() - last_alert_time >= alert_interval:
                last_alert_time = time.time()
                log.error("KAPATMA HATASI DEVAM: %s %s deneme=%d sure=%.0f sn",
                          symbol, ecosystem, attempt, elapsed)
                if self.telegram:
                    self.telegram.send_close_error(
                        symbol, ecosystem, reason, attempt,
                        result.get("error", ""), elapsed, first=False
                    )

            time.sleep(retry_delay)

    def close_trade_async(self, trade, reason, current_price=None):
        if hasattr(trade, "symbol"):
            sym = trade.symbol
            eco = trade.ecosystem
            sd = trade.side
        else:
            sym = trade["symbol"]
            eco = trade["ecosystem"]
            sd = trade["side"]
        key = f"{sym}_{eco}_{sd}"

        if key in self._closing_threads and self._closing_threads[key].is_alive():
            log.warning("Zaten kapatma islemi devam ediyor: %s", key)
            return

        t = threading.Thread(
            target=self.close_trade,
            args=(trade, reason, current_price),
            daemon=True,
            name=f"close_{key}"
        )
        self._closing_threads[key] = t
        t.start()

    def close_all_positions(self):
        positions = self.client.get_positions()
        results = []
        for pos in positions:
            result = self.client.close_position(
                pos["symbol"], pos["side"], pos["size"]
            )
            results.append({
                "symbol": pos["symbol"],
                "side": pos["side"],
                "size": pos["size"],
                "success": result["success"],
                "pnl": pos.get("unrealised_pnl", 0)
            })
        return results
