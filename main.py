import os
import sys
import time
import json
import threading
import signal
from datetime import datetime

from logger_setup import setup_logger, get_logger
from utils import load_config, get_config_mtime, format_usdt, format_duration, is_our_order
from bybit_client import BybitClient
from price_poller import PricePoller
from data_pool import DataPool
from indicators import compute_all_indicators
from trade_executor import TradeExecutor
from ecosystem_white import WhiteEcosystem
from ecosystem_yellow import YellowEcosystem
from ecosystem_black import BlackEcosystem
from ecosystem_gold import GoldEcosystem
from ecosystem_red import RedEcosystem
from telegram_bot import TelegramBot
import trade_history

setup_logger()
log = get_logger("main")


class BotManager:
    def __init__(self):
        self.config = load_config()
        self.config_mtime = get_config_mtime()
        self.running = False
        self.start_time = 0
        self.recent_events = []

        # Bileşenler
        self.bybit = BybitClient()
        self.data_pool = DataPool()
        self.telegram = TelegramBot(bot_manager=self)
        self.executor = TradeExecutor(self.bybit, self.config, self.telegram)

        # Ekosistemler
        self.ecosystems = {}
        self._init_ecosystems()

        # Price Poller
        self.poller = None

        # Periyodik rapor zamanlayıcı
        self._report_thread = None
        self._health_thread = None
        self._config_thread = None
        self._stop_event = threading.Event()

    def _init_ecosystems(self):
        cfg = self.config
        self.ecosystems["beyaz"] = WhiteEcosystem(
            cfg.get("beyaz", {}), self.data_pool, self.executor, self.telegram
        )
        self.ecosystems["sari"] = YellowEcosystem(
            cfg.get("sari", {}), self.data_pool, self.executor, self.telegram
        )
        self.ecosystems["siyah"] = BlackEcosystem(
            cfg.get("siyah", {}), self.data_pool, self.executor, self.telegram
        )
        self.ecosystems["altin"] = GoldEcosystem(
            cfg.get("altin", {}), self.data_pool, self.executor, self.telegram
        )
        self.ecosystems["kirmizi"] = RedEcosystem(
            cfg.get("kirmizi", {}), self.data_pool, self.executor, self.telegram
        )


    # === ANA BAŞLATMA ===

    def run(self):
        log.info("=" * 60)
        log.info("TRADE BOT BASLATILIYOR")
        log.info("=" * 60)

        # 1. Bybit bağlantı testi
        if not self.bybit.test_connection():
            log.critical("Bybit baglantisi kurulamadi!")
            return

        # 2. Coin listesi ve instrument bilgisi
        coins = self.config["global"]["coin_listesi"]
        self.bybit.load_instrument_info(coins)

        # 3. Hesap ayarları (leverage, margin, position mode)
        leverage = self.config["global"]["kaldirac"]
        self.bybit.setup_account(coins, leverage)

        # 4. Bakiye oku
        balance_info = self.bybit.get_balance()
        if not balance_info:
            log.critical("Bakiye alinamadi!")
            return
        log.info("Bakiye: %.2f USDT", balance_info["total"])

        # 5. Başlangıç mumlarını çek ve indikatörleri hesapla
        self._load_initial_data(coins)

        # 6. Mevcut pozisyonları kontrol et
        self._check_existing_positions()

        # 7. Price Poller başlat
        interval = self.config["global"]["timeframe"]
        self.poller = PricePoller(
            bybit_client=self.bybit,
            data_pool=self.data_pool,
            config=self.config,
            on_candle_close=self._on_candle_close
        )
        self.poller.start(coins, interval)

        # 8. Bot durumunu ayarla
        self.running = True
        self.start_time = time.time()
        self.telegram.daily_stats["start_balance"] = balance_info["total"]

        # 9. Telegram bot başlat
        self.telegram.setup_commands(self)
        self.telegram.start_polling()

        # 10. Bot başladı bildirimi
        eco_states = {n: e.active for n, e in self.ecosystems.items()}
        open_count = sum(e.get_total_count() for e in self.ecosystems.values())
        untagged = self._get_untagged_positions()
        margin_pct = self.config["global"]["marjin_orani"]
        self.telegram.send_bot_started(
            balance_info["total"], margin_pct, leverage,
            eco_states, open_count, untagged
        )

        self._add_event(f"Bot baslatildi | Bakiye: {format_usdt(balance_info['total'])} USDT")

        # 11. Arka plan thread'leri başlat
        self._start_background_threads()

        # 12. Ana döngü
        log.info("Bot calisiyor, Ctrl+C ile durdurulabilir")
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(1)
        except KeyboardInterrupt:
            log.info("Klavye ile durdurma istegi alindi")
        finally:
            self._shutdown()

    def _load_initial_data(self, coins):
        log.info("Baslangic verileri yukleniyor (%d coin, %d mum)...",
                 len(coins), self.config["global"]["baslangic_mum_sayisi"])

        limit = self.config["global"]["baslangic_mum_sayisi"]
        interval = self.config["global"]["timeframe"]

        for symbol in coins:
            candles = self.bybit.get_klines(symbol, interval, limit)
            if candles:
                self.data_pool.set_initial_candles(symbol, candles)
                indicators = compute_all_indicators(candles, self.config)
                self.data_pool.set_indicators(symbol, indicators)
                log.debug("%s: %d mum, indikatorler hesaplandi", symbol, len(candles))
            else:
                log.warning("%s: Mum verisi alinamadi!", symbol)
            time.sleep(0.2)  # Rate limit (5 req/sec, Bybit'in 10/sec limitinin altında)

        log.info("Baslangic verileri yuklendi")

    def _check_existing_positions(self):
        positions = self.bybit.get_positions()
        if not positions:
            log.info("Acik pozisyon bulunmuyor")
            return

        our_count = 0
        untagged_count = 0
        untracked = []
        for pos in positions:
            link_id = pos.get("order_link_id", "")
            if is_our_order(link_id):
                our_count += 1
                log.info("Bizim pozisyon: %s %s %s (%.6f)",
                         pos["symbol"], pos["side"], link_id, pos["size"])
                untracked.append(pos)
            else:
                untagged_count += 1
                log.warning("Etiketsiz pozisyon: %s %s (%.6f) - dokunulmayacak",
                            pos["symbol"], pos["side"], pos["size"])

        log.info("Pozisyon ozeti: %d bizim, %d etiketsiz", our_count, untagged_count)

        if untracked and self.telegram:
            self.telegram.send_untracked_positions(untracked)

    def _get_untagged_positions(self):
        positions = self.bybit.get_positions()
        untagged = []
        for pos in positions:
            link_id = pos.get("order_link_id", "")
            if not is_our_order(link_id) and pos["size"] > 0:
                untagged.append(pos)
        return untagged

    # === VERİ GERİ ÇAĞIRMALARI ===

    def _on_candle_close(self, symbol, candle):
        if not self.running:
            return

        # Mumu veri havuzuna ekle
        self.data_pool.add_candle(symbol, candle)

        # İndikatörleri yeniden hesapla
        candles = self.data_pool.get_candles(symbol)
        indicators = compute_all_indicators(candles, self.config)
        self.data_pool.set_indicators(symbol, indicators)

        log.debug("%s mum kapandi: C=%.4f", symbol, candle["close"])

        # Mum kapanışına göre çalışan ekosistemler: Beyaz, Sarı, Siyah
        for name in ["beyaz", "sari", "siyah", "altin", "kirmizi"]:
            eco = self.ecosystems[name]
            if eco.active:
                try:
                    eco.on_candle_close(symbol, candle)
                except Exception as e:
                    log.error("%s on_candle_close hatasi (%s): %s", name, symbol, e)

    # === ARKA PLAN THREAD'LERİ ===

    def _start_background_threads(self):
        # 5 saniyelik ekosistem tarama döngüsü
        self._scan_thread = threading.Thread(
            target=self._scan_loop, daemon=True, name="scan_loop"
        )
        self._scan_thread.start()

        # Periyodik raporlar
        self._report_thread = threading.Thread(
            target=self._report_loop, daemon=True, name="report_loop"
        )
        self._report_thread.start()

        # Sağlık kontrolü
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="health_loop"
        )
        self._health_thread.start()

        # Config değişiklik kontrolü
        self._config_thread = threading.Thread(
            target=self._config_watch_loop, daemon=True, name="config_watch"
        )
        self._config_thread.start()

        # SL emniyet kemeri
        self._sl_guard_thread = threading.Thread(
            target=self._sl_guard_loop, daemon=True, name="sl_guard"
        )
        self._sl_guard_thread.start()

    def _sl_guard_loop(self):
        sl_pct = self.config["global"].get("stop_loss_orani", 0.02)
        while not self._stop_event.is_set():
            self._stop_event.wait(5)
            if self._stop_event.is_set():
                break
            if not self.running:
                continue
            try:
                positions = self.bybit.get_positions()
                for pos in positions:
                    entry = pos["entry_price"]
                    size = pos["size"]
                    pnl = pos["unrealised_pnl"]
                    if entry <= 0 or size <= 0 or pnl >= 0:
                        continue
                    loss_pct = -pnl / (entry * size)
                    if loss_pct >= sl_pct:
                        symbol = pos["symbol"]
                        side = pos["side"]
                        log.warning("SL GUARD: %s %s zarar=%.2f%% - kapatiliyor", symbol, side, loss_pct * 100)
                        result = self.bybit.close_position(symbol, side, size)
                        if result["success"]:
                            for eco in self.ecosystems.values():
                                for trade in eco.find_trades_for_symbol(symbol, side):
                                    eco.remove_trade(trade)
                                with eco._lock:
                                    stale = [h for h in eco.hedge_trades if h.symbol == symbol and h.side == side]
                                for h in stale:
                                    eco.remove_hedge_trade(h)
                            exit_price = (entry + pnl / size) if side == "long" else (entry - pnl / size)
                            trade_history.record(symbol, side, "sl_guard", entry, exit_price, size, pnl, "SL Emniyet Kemeri")
                            if self.telegram:
                                self.telegram.send_sl_guard_close(symbol, side, entry, size, loss_pct)
            except Exception as e:
                log.error("SL guard hatasi: %s", e)

    def _scan_loop(self):
        coins = self.config["global"]["coin_listesi"]
        while not self._stop_event.is_set():
            self._stop_event.wait(5)
            if self._stop_event.is_set():
                break
            if not self.running:
                continue

            for symbol in coins:
                price = self.data_pool.get_price(symbol)
                if not price or price <= 0:
                    continue

                for name in ["beyaz", "sari", "siyah", "altin", "kirmizi"]:
                    eco = self.ecosystems[name]
                    if eco.active:
                        try:
                            eco.on_tick(symbol, price)
                        except Exception as e:
                            log.error("%s scan hatasi (%s): %s", name, symbol, e)

    def _report_loop(self):
        last_1h = time.time()
        last_6h = time.time()
        last_12h = time.time()
        last_24h = time.time()

        while not self._stop_event.is_set():
            self._stop_event.wait(60)
            if self._stop_event.is_set():
                break

            now = time.time()
            balance_info = self.bybit.get_balance()
            balance = balance_info["total"] if balance_info else 0
            open_counts = self._get_open_counts()

            cfg_tg = self.config.get("telegram", {})

            if now - last_1h >= 3600 and cfg_tg.get("periyodik_rapor_1s", True):
                self.telegram.send_hourly_report(balance, open_counts)
                last_1h = now

            if now - last_6h >= 21600 and cfg_tg.get("periyodik_rapor_6s", True):
                self.telegram.send_6h_report(balance, open_counts)
                last_6h = now

            if now - last_12h >= 43200 and cfg_tg.get("periyodik_rapor_12s", True):
                self.telegram.send_12h_report(balance, open_counts)
                last_12h = now

            if now - last_24h >= 86400 and cfg_tg.get("periyodik_rapor_24s", True):
                self.telegram.send_24h_report(balance, open_counts)
                last_24h = now

    def _sync_positions(self):
        try:
            bybit_positions = self.bybit.get_positions()
            bybit_keys = set()
            for p in bybit_positions:
                idx = p.get("position_idx", 0)
                bybit_keys.add((p["symbol"], idx))

            to_remove = []
            for eco in self.ecosystems.values():
                for trade in eco.get_all_trades():
                    pos_idx = 1 if trade.side == "long" else 2
                    if (trade.symbol, pos_idx) not in bybit_keys:
                        to_remove.append((eco, trade))

            for eco, trade in to_remove:
                log.warning("Dis kapanis tespit edildi: %s %s %s",
                            trade.ecosystem, trade.symbol, trade.side)
                if self.telegram:
                    self.telegram.send_external_close(trade)
                if hasattr(trade, "parent_trade"):
                    eco.remove_hedge_trade(trade)
                else:
                    eco.remove_trade(trade)
        except Exception as e:
            log.error("Pozisyon sync hatasi: %s", e)

    def _health_loop(self):
        was_ok = True
        lost_time = None
        last_sync = time.time()
        while not self._stop_event.is_set():
            self._stop_event.wait(30)
            if self._stop_event.is_set():
                break

            if self.poller:
                secs = self.poller.seconds_since_last_price
                is_ok = 0 <= secs < 60

                if was_ok and not is_ok:
                    lost_time = time.time()
                    log.warning("Fiyat verisi kesildi (son: %.0f sn once)", secs)
                    self.telegram.send_connection_lost()
                    self._add_event("Fiyat verisi kesildi")

                if not was_ok and is_ok:
                    downtime = time.time() - lost_time if lost_time else 0
                    lost_time = None
                    self.telegram.send_connection_restored(downtime)
                    self._add_event(f"Fiyat verisi yeniden geldi (kesinti: {format_duration(downtime)})")

                was_ok = is_ok

            if time.time() - last_sync >= 300:
                self._sync_positions()
                last_sync = time.time()

    def _config_watch_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(5)
            if self._stop_event.is_set():
                break

            try:
                current_mtime = get_config_mtime()
                if current_mtime != self.config_mtime:
                    log.info("Config degisikligi algilandi, yeniden yukleniyor...")
                    new_config = load_config()
                    self.config_mtime = current_mtime
                    self._apply_config(new_config)
                    self._add_event("Config guncellendi")
            except Exception as e:
                log.error("Config izleme hatasi: %s", e)

    def _apply_config(self, new_config):
        self.config = new_config
        self.executor.reload_config(new_config)

        eco_map = {
            "beyaz": "beyaz",
            "sari": "sari", "siyah": "siyah",
            "altin": "altin",
            "kirmizi": "kirmizi"
        }
        for config_key, eco_name in eco_map.items():
            if eco_name in self.ecosystems:
                eco_cfg = new_config.get(config_key, {})
                self.ecosystems[eco_name].reload_config(eco_cfg)

        log.info("Config uygulandı (acik islemler eski parametrelerle devam eder)")

    # === BOT YÖNETİMİ (Telegram komutları tarafından çağrılır) ===

    def stop_bot(self):
        log.info("Bot durduruluyor...")
        self.running = False

        eco_counts = {n: e.get_total_count() for n, e in self.ecosystems.items()}
        self.telegram.send_bot_stopped(eco_counts)
        self._add_event("Bot durduruldu")
        self._stop_event.set()

    def start_bot(self):
        log.info("Bot yeniden baslatiliyor...")
        self.running = True
        self.start_time = time.time()
        self._stop_event.clear()

        balance_info = self.bybit.get_balance()
        if balance_info:
            eco_states = {n: e.active for n, e in self.ecosystems.items()}
            open_count = sum(e.get_total_count() for e in self.ecosystems.values())
            untagged = self._get_untagged_positions()
            self.telegram.send_bot_started(
                balance_info["total"],
                self.config["global"]["marjin_orani"],
                self.config["global"]["kaldirac"],
                eco_states, open_count, untagged
            )
        self._add_event("Bot baslatildi")

    def stop_ecosystem(self, name):
        if name in self.ecosystems:
            self.ecosystems[name].active = False
            log.info("%s ekosistemi durduruldu", name)
            self._add_event(f"{name} ekosistemi durduruldu")

    def start_ecosystem(self, name):
        if name in self.ecosystems:
            self.ecosystems[name].active = True
            log.info("%s ekosistemi baslatildi", name)
            self._add_event(f"{name} ekosistemi baslatildi")

    def close_all(self):
        results = self.executor.close_all_positions()
        # Tüm ekosistem trade listelerini temizle
        for eco in self.ecosystems.values():
            eco.trades.clear()
            eco.hedge_trades.clear()
            if hasattr(eco, "sub_trades_1"):
                eco.sub_trades_1.clear()
            if hasattr(eco, "sub_trades_2"):
                eco.sub_trades_2.clear()
            if hasattr(eco, "hedge_trades_1"):
                eco.hedge_trades_1.clear()
            if hasattr(eco, "hedge_trades_2"):
                eco.hedge_trades_2.clear()
        self._add_event(f"Tum pozisyonlar kapatildi ({len(results)} adet)")
        return results

    def get_balance(self):
        return self.bybit.get_balance()

    def get_status_info(self):
        balance_info = self.bybit.get_balance()
        return {
            "running": self.running,
            "balance": balance_info["total"] if balance_info else 0,
            "uptime": time.time() - self.start_time if self.start_time > 0 else 0,
            "open_counts": self._get_open_counts(),
            "ecosystem_states": {n: e.active for n, e in self.ecosystems.items()},
            "price_ok": (self.poller.seconds_since_last_price < 60) if self.poller else False,
            "last_data_ago": self.poller.seconds_since_last_price if self.poller else -1
        }

    def get_all_positions(self):
        positions = []
        for name, eco in self.ecosystems.items():
            for trade in eco.get_all_trades():
                current_price = self.data_pool.get_price(trade.symbol)
                if trade.side == "short":
                    pnl = (trade.entry_price - current_price) * trade.qty
                else:
                    pnl = (current_price - trade.entry_price) * trade.qty
                pnl_pct = (pnl / (trade.entry_price * trade.qty)) * 100 if trade.entry_price * trade.qty > 0 else 0
                duration = time.time() - trade.open_time if trade.open_time > 0 else 0

                positions.append({
                    "symbol": trade.symbol,
                    "side": trade.side,
                    "ecosystem": trade.ecosystem,
                    "entry_price": trade.entry_price,
                    "current_price": current_price,
                    "qty": trade.qty,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                    "duration": duration
                })
        return positions

    def get_orphan_positions(self):
        bybit_positions = self.bybit.get_positions()

        bot_keys = set()
        for eco in self.ecosystems.values():
            for trade in eco.get_all_trades():
                idx = 1 if trade.side == "long" else 2
                bot_keys.add((trade.symbol, idx))

        orphans = []
        for pos in bybit_positions:
            idx = pos.get("position_idx", 0)
            if (pos["symbol"], idx) not in bot_keys:
                link_id = pos.get("order_link_id", "")
                orphans.append({
                    **pos,
                    "pos_type": "bizim" if is_our_order(link_id) else "yabanci"
                })
        return orphans

    def get_all_flags(self):
        all_flags = []
        for eco_name, eco in self.ecosystems.items():
            for flag in eco.get_open_flags():
                flag["ecosystem"] = eco_name
                all_flags.append(flag)
        return all_flags

    def get_recent_events(self, count=10):
        return self.recent_events[-count:]

    def _get_open_counts(self):
        return {n: e.get_total_count() for n, e in self.ecosystems.items()}

    def _add_event(self, text):
        ts = datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {text}"
        self.recent_events.append(entry)
        if len(self.recent_events) > 100:
            self.recent_events = self.recent_events[-100:]

    def _shutdown(self):
        log.info("Bot kapatiliyor...")
        self.running = False
        self._stop_event.set()

        if self.poller:
            self.poller.stop()

        log.info("Bot kapatildi")
        log.info("=" * 60)


def main():
    bot = BotManager()

    # Sinyal yakalama - bot önceden tanımlanmalı ki closure çalışsın
    def signal_handler(sig, frame):
        log.info("Sinyal alindi: %s", sig)
        bot._stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    bot.run()


if __name__ == "__main__":
    main()
