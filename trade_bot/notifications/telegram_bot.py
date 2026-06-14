import os
import logging
import threading
from telegram import Bot
from telegram.ext import ApplicationBuilder
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, config: dict):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = os.environ["TELEGRAM_CHAT_ID"]
        self.config = config
        self._bot = Bot(token=self.token)
        self._lock = threading.Lock()
        self._scheduler = BackgroundScheduler()

        # Periyodik raporlar için veri toplayıcı
        self._open_trades: dict = {}       # {symbol: {direction, thread, entry, qty}}
        self._closed_trades: list = []     # kapanan işlemler (gün içi)
        self._total_pnl = 0.0

    # ------------------------------------------------------------------ #
    #  Zamanlayıcı                                                        #
    # ------------------------------------------------------------------ #

    def start_scheduler(self, balance_getter):
        self._balance_getter = balance_getter
        cfg = self.config["telegram"]["report_intervals"]

        self._scheduler.add_job(self._report_hourly, "interval", minutes=cfg["hourly_minutes"])
        self._scheduler.add_job(self._report_half_daily, "interval", minutes=cfg["half_daily_minutes"])
        self._scheduler.add_job(self._report_daily, "interval", minutes=cfg["daily_minutes"])
        self._scheduler.start()

    def stop_scheduler(self):
        self._scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    #  Anlık bildirimler                                                  #
    # ------------------------------------------------------------------ #

    def bot_started(self, balance: float):
        self.send(f"✅ *Bot başladı*\nBakiye: `{balance:.2f} USDT`")

    def bot_stopped(self):
        self.send("🛑 *Bot durdu*")

    def trade_opened(self, symbol: str, direction: str, thread: str,
                     entry_price: float, qty: float, sl_price: float):
        dir_emoji = "🔴" if direction == "short" else "🟢"
        msg = (
            f"{dir_emoji} *İşlem Açıldı*\n"
            f"Coin: `{symbol}`\n"
            f"Yön: `{direction.upper()}`\n"
            f"Thread: `{thread}`\n"
            f"Giriş: `{entry_price}`\n"
            f"Miktar: `{qty}`\n"
            f"SL: `{sl_price:.4f}`"
        )
        self.send(msg)
        self._open_trades[f"{symbol}_{thread}"] = {
            "symbol": symbol, "direction": direction,
            "thread": thread, "entry": entry_price, "qty": qty,
        }

    def trade_closed(self, symbol: str, direction: str, thread: str,
                     close_price: float, pnl: float, pnl_pct: float, reason: str):
        pnl_emoji = "💰" if pnl >= 0 else "📉"
        msg = (
            f"{pnl_emoji} *İşlem Kapandı*\n"
            f"Coin: `{symbol}`\n"
            f"Yön: `{direction.upper()}`\n"
            f"Thread: `{thread}`\n"
            f"Kapanış: `{close_price}`\n"
            f"K/Z: `{pnl:+.2f} USDT` (`{pnl_pct:+.2f}%`)\n"
            f"Neden: `{reason}`"
        )
        self.send(msg)
        key = f"{symbol}_{thread}"
        self._open_trades.pop(key, None)
        self._closed_trades.append({"symbol": symbol, "direction": direction, "thread": thread,
                                    "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason})
        self._total_pnl += pnl

    def error(self, message: str):
        self.send(f"⚠️ *Hata*\n`{message}`")

    def low_balance(self, balance: float):
        self.send(f"⚠️ *Yetersiz bakiye*\nBakiye: `{balance:.2f} USDT`")

    def send(self, text: str):
        with self._lock:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    self._bot.send_message(
                        chat_id=self.chat_id,
                        text=text,
                        parse_mode="Markdown",
                    )
                )
                loop.close()
            except Exception as e:
                logger.warning(f"Telegram gönderme hatası: {e}")

    # ------------------------------------------------------------------ #
    #  Periyodik raporlar                                                 #
    # ------------------------------------------------------------------ #

    def _report_hourly(self):
        open_count = len(self._open_trades)
        msg = (
            f"📊 *1 Saatlik Rapor*\n"
            f"Açık işlem: `{open_count}`\n"
            f"Anlık toplam K/Z: `{self._total_pnl:+.2f} USDT`"
        )
        self.send(msg)

    def _report_half_daily(self):
        coin_pnl: dict = {}
        for t in self._closed_trades:
            coin_pnl.setdefault(t["symbol"], 0.0)
            coin_pnl[t["symbol"]] += t["pnl"]

        lines = [f"`{s}`: {p:+.2f} USDT" for s, p in coin_pnl.items()]
        body = "\n".join(lines) if lines else "İşlem yok"
        msg = (
            f"📊 *12 Saatlik Rapor*\n"
            f"Tamamlanan işlem: `{len(self._closed_trades)}`\n"
            f"Coin bazlı K/Z:\n{body}\n"
            f"Toplam K/Z: `{self._total_pnl:+.2f} USDT`"
        )
        self.send(msg)

    def _report_daily(self):
        thread_pnl: dict = {}
        win = 0
        total = len(self._closed_trades)

        for t in self._closed_trades:
            thread_pnl.setdefault(t["thread"], 0.0)
            thread_pnl[t["thread"]] += t["pnl"]
            if t["pnl"] > 0:
                win += 1

        winrate = (win / total * 100) if total else 0
        thread_lines = [f"`{th}`: {p:+.2f} USDT" for th, p in thread_pnl.items()]
        balance = self._balance_getter() if hasattr(self, "_balance_getter") else 0

        msg = (
            f"📊 *24 Saatlik Rapor*\n"
            f"Tamamlanan işlem: `{total}`\n"
            f"Winrate: `{winrate:.1f}%`\n"
            f"Thread bazlı K/Z:\n" + "\n".join(thread_lines) + "\n"
            f"Toplam K/Z: `{self._total_pnl:+.2f} USDT`\n"
            f"Güncel bakiye: `{balance:.2f} USDT`"
        )
        self.send(msg)
        # Günlük sıfırla
        self._closed_trades.clear()
        self._total_pnl = 0.0
