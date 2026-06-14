import os
import time
import logging
import threading
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

TAKER_FEE = 0.00055  # Bybit USDT perpetual taker fee


class TelegramNotifier:
    def __init__(self, config: dict):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = os.environ["TELEGRAM_CHAT_ID"]
        self.config = config
        self._bot = Bot(token=self.token)
        self._lock = threading.Lock()
        self._scheduler = BackgroundScheduler()

        self._open_flags: dict = {}     # {key: {symbol, direction, thread}}
        self._open_trades: dict = {}    # {symbol_thread: {symbol, direction, thread, entry, qty, opened_at}}
        self._closed_trades: list = []  # [{symbol, direction, thread, pnl, pnl_pct, reason, entry, close, qty, duration_sec, commission}]
        self._total_pnl = 0.0
        self._start_balance = 0.0
        self._peak_pnl = 0.0
        self._max_drawdown = 0.0

        self._stop_callback = None
        self._start_callback = None
        self._balance_getter = None

    # ------------------------------------------------------------------ #
    #  Zamanlayıcı                                                        #
    # ------------------------------------------------------------------ #

    def start_scheduler(self, balance_getter, start_balance: float = 0.0):
        self._balance_getter = balance_getter
        self._start_balance = start_balance
        cfg = self.config["telegram"]["report_intervals"]
        self._scheduler.add_job(self._report_hourly,     "interval", minutes=cfg["hourly_minutes"])
        self._scheduler.add_job(self._report_half_daily, "interval", minutes=cfg["half_daily_minutes"])
        self._scheduler.add_job(self._report_daily,      "interval", minutes=cfg["daily_minutes"])
        self._scheduler.start()

    def stop_scheduler(self):
        self._scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------ #
    #  Callback bağlantıları                                              #
    # ------------------------------------------------------------------ #

    def set_stop_callback(self, cb):
        self._stop_callback = cb

    def set_start_callback(self, cb):
        self._start_callback = cb

    # ------------------------------------------------------------------ #
    #  Telegram komut dinleyici                                           #
    # ------------------------------------------------------------------ #

    def start_command_listener(self):
        t = threading.Thread(target=self._run_command_listener, name="TelegramCommands", daemon=True)
        t.start()

    def _run_command_listener(self):
        import asyncio

        notifier = self

        async def cmd_acik(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if str(update.effective_chat.id) != str(notifier.chat_id):
                return
            balance = notifier._balance_getter() if notifier._balance_getter else 0

            flag_lines  = [f"  • `{v['symbol']}` {v['direction'].upper()} [{v['thread']}]"
                           for v in notifier._open_flags.values()]
            trade_lines = [f"  • `{v['symbol']}` {v['direction'].upper()} [{v['thread']}] @ `{v['entry']}`"
                           for v in notifier._open_trades.values()]

            msg = (
                f"📋 *Açık Durum*\n\n"
                f"*Flagler ({len(flag_lines)}):*\n" + ("\n".join(flag_lines) if flag_lines else "  Yok") + "\n\n"
                + f"*Açık İşlemler ({len(trade_lines)}):*\n" + ("\n".join(trade_lines) if trade_lines else "  Yok") + "\n\n"
                + f"Bakiye: `{balance:.2f} USDT`"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")

        async def cmd_rapor(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if str(update.effective_chat.id) != str(notifier.chat_id):
                return
            notifier._report_hourly()

        async def cmd_durdur(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if str(update.effective_chat.id) != str(notifier.chat_id):
                return
            await update.message.reply_text("🛑 Bot durduruluyor...")
            if notifier._stop_callback:
                threading.Thread(target=notifier._stop_callback, daemon=True).start()

        async def cmd_basla(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if str(update.effective_chat.id) != str(notifier.chat_id):
                return
            await update.message.reply_text("▶️ Bot başlatılıyor...")
            if notifier._start_callback:
                threading.Thread(target=notifier._start_callback, daemon=True).start()

        async def cmd_yardim(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
            if str(update.effective_chat.id) != str(notifier.chat_id):
                return
            msg = (
                "*Komutlar:*\n"
                "/acik — Açık flagler, işlemler, bakiye\n"
                "/rapor — Anlık K/Z özeti\n"
                "/durdur — Botu durdur\n"
                "/basla — Botu başlat\n"
                "/yardim — Bu liste"
            )
            await update.message.reply_text(msg, parse_mode="Markdown")

        async def run():
            app = ApplicationBuilder().token(notifier.token).build()
            app.add_handler(CommandHandler("acik",   cmd_acik))
            app.add_handler(CommandHandler("rapor",  cmd_rapor))
            app.add_handler(CommandHandler("durdur", cmd_durdur))
            app.add_handler(CommandHandler("basla",  cmd_basla))
            app.add_handler(CommandHandler("yardim", cmd_yardim))
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)
            await asyncio.Event().wait()

        asyncio.run(run())

    # ------------------------------------------------------------------ #
    #  Flag bildirimleri                                                  #
    # ------------------------------------------------------------------ #

    def flag_opened(self, symbol: str, direction: str, thread: str):
        key = f"{symbol}_{direction}_{thread}"
        self._open_flags[key] = {"symbol": symbol, "direction": direction, "thread": thread}

    def flag_closed(self, symbol: str, direction: str, thread: str):
        key = f"{symbol}_{direction}_{thread}"
        self._open_flags.pop(key, None)

    # ------------------------------------------------------------------ #
    #  Anlık bildirimler                                                  #
    # ------------------------------------------------------------------ #

    def bot_started(self, balance: float):
        t = self.config["trading"]
        b = self.config["band"]
        msg = (
            f"✅ *Bot başladı*\n"
            f"Bakiye: `{balance:.2f} USDT`\n\n"
            f"*İşlem Parametreleri*\n"
            f"Kaldıraç: `{t['leverage']}x`\n"
            f"İşlem Büyüklüğü: `%{int(t['balance_pct'] * 100)}`\n"
            f"Stop Loss: `%{int(t['sl_pct'] * 100)}`\n\n"
            f"*Bant Ayarları*\n"
            f"Timeframe: `{b['timeframe']} dk`\n"
            f"EMA: `{b['ema_period']}`\n"
            f"ATR: `{b['atr_period']}`\n"
            f"Bant Sayısı: `{b['band_levels']}`"
        )
        self.send(msg)

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
        key = f"{symbol}_{thread}"
        self._open_trades[key] = {
            "symbol": symbol, "direction": direction,
            "thread": thread, "entry": entry_price, "qty": qty,
            "opened_at": time.time(),
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
        trade = self._open_trades.pop(key, {})
        opened_at  = trade.get("opened_at", time.time())
        entry      = trade.get("entry", 0)
        qty        = trade.get("qty", 0)
        commission = qty * entry * TAKER_FEE * 2 if entry and qty else 0

        self._closed_trades.append({
            "symbol": symbol, "direction": direction, "thread": thread,
            "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason,
            "entry": entry, "close": close_price, "qty": qty,
            "duration_sec": time.time() - opened_at,
            "commission": commission,
        })
        self._total_pnl += pnl

        if self._total_pnl > self._peak_pnl:
            self._peak_pnl = self._total_pnl
        dd = self._peak_pnl - self._total_pnl
        if dd > self._max_drawdown:
            self._max_drawdown = dd

    def error(self, message: str):
        self.send(f"⚠️ *Hata*\n`{message}`")

    def low_balance(self, balance: float, symbol: str = None, direction: str = None, thread: str = None):
        msg = f"⚠️ *Yetersiz Bakiye*\nBakiye: `{balance:.2f} USDT`"
        if symbol and direction and thread:
            msg += (
                f"\n\n*İşlem Açılamadı*\n"
                f"Coin: `{symbol}`\n"
                f"Yön: `{direction.upper()}`\n"
                f"Thread: `{thread}`"
            )
        self.send(msg)

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
    #  Yardımcı                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fmt_dur(sec: float) -> str:
        if sec < 60:   return f"{int(sec)}s"
        if sec < 3600: return f"{int(sec // 60)}dk"
        return f"{int(sec // 3600)}sa {int((sec % 3600) // 60)}dk"

    # ------------------------------------------------------------------ #
    #  Periyodik raporlar                                                 #
    # ------------------------------------------------------------------ #

    def _report_hourly(self):
        flag_lines   = [f"  • `{v['symbol']}` {v['direction'].upper()} [{v['thread']}]"
                        for v in self._open_flags.values()]
        trade_lines  = [f"  • `{v['symbol']}` {v['direction'].upper()} [{v['thread']}] @ `{v['entry']}`"
                        for v in self._open_trades.values()]
        closed_lines = [f"  • `{t['symbol']}` {t['direction'].upper()} [{t['thread']}] `{t['pnl']:+.2f}` ({t['reason']})"
                        for t in self._closed_trades[-10:]]

        msg = (
            f"📊 *1 Saatlik Rapor*\n\n"
            f"*Flagler ({len(flag_lines)}):*\n" + ("\n".join(flag_lines) if flag_lines else "  Yok") + "\n\n"
            + f"*Açık İşlemler ({len(trade_lines)}):*\n" + ("\n".join(trade_lines) if trade_lines else "  Yok") + "\n\n"
            + f"*Son Kapanan İşlemler:*\n" + ("\n".join(closed_lines) if closed_lines else "  Yok") + "\n\n"
            + f"Toplam K/Z: `{self._total_pnl:+.2f} USDT`"
        )
        self.send(msg)

    def _report_half_daily(self):
        trades   = self._closed_trades
        total    = len(trades)
        winners  = [t for t in trades if t["pnl"] > 0]
        losers   = [t for t in trades if t["pnl"] <= 0]
        winrate  = (len(winners) / total * 100) if total else 0
        balance  = self._balance_getter() if self._balance_getter else 0
        best     = max(trades, key=lambda t: t["pnl"], default=None)
        worst    = min(trades, key=lambda t: t["pnl"], default=None)

        thread_stats: dict = {}
        coin_stats:   dict = {}
        reason_stats: dict = {}
        for t in trades:
            ts = thread_stats.setdefault(t["thread"],  {"pnl": 0.0, "w": 0, "l": 0})
            cs = coin_stats.setdefault(t["symbol"],    {"pnl": 0.0, "w": 0, "l": 0})
            ts["pnl"] += t["pnl"]; cs["pnl"] += t["pnl"]
            if t["pnl"] > 0: ts["w"] += 1; cs["w"] += 1
            else:             ts["l"] += 1; cs["l"] += 1
            reason_stats[t["reason"]] = reason_stats.get(t["reason"], 0) + 1

        def wr(s): return f"{(s['w'] / (s['w']+s['l']) * 100):.0f}" if (s['w']+s['l']) else "0"

        flag_lines   = [f"  • `{v['symbol']}` {v['direction'].upper()} [{v['thread']}]"          for v in self._open_flags.values()]
        trade_lines  = [f"  • `{v['symbol']}` {v['direction'].upper()} [{v['thread']}] @ `{v['entry']}`" for v in self._open_trades.values()]
        closed_lines = [f"  • `{t['symbol']}` {t['direction'].upper()} [{t['thread']}] `{t['pnl']:+.2f}` ({t['reason']})" for t in trades]
        thread_lines = [f"  `{th}`: `{s['pnl']:+.2f}` | {s['w']}W/{s['l']}L | WR%`{wr(s)}`" for th, s in thread_stats.items()]
        coin_lines   = [f"  `{cn}`: `{s['pnl']:+.2f}` | {s['w']}W/{s['l']}L | WR%`{wr(s)}`" for cn, s in coin_stats.items()]
        reason_lines = [f"  `{r}`: {c}" for r, c in reason_stats.items()]

        msg = (
            f"📊 *12 Saatlik Rapor (Z)*\n\n"
            f"*Genel Özet*\n"
            f"Toplam: `{total}` | W:`{len(winners)}` L:`{len(losers)}` | WR%`{winrate:.1f}`\n"
            f"Bakiye: `{balance:.2f} USDT`\n\n"
            + (f"*En İyi:* `{best['symbol']}` {best['direction'].upper()} `{best['pnl']:+.2f} USDT`\n"  if best  else "")
            + (f"*En Kötü:* `{worst['symbol']}` {worst['direction'].upper()} `{worst['pnl']:+.2f} USDT`\n\n" if worst else "\n")
            + f"*Flagler ({len(flag_lines)}):*\n"         + ("\n".join(flag_lines)   if flag_lines   else "  Yok") + "\n\n"
            + f"*Açık İşlemler ({len(trade_lines)}):*\n"  + ("\n".join(trade_lines)  if trade_lines  else "  Yok") + "\n\n"
            + f"*Kapanan İşlemler ({total}):*\n"          + ("\n".join(closed_lines) if closed_lines else "  Yok") + "\n\n"
            + f"*Thread Bazlı:*\n"  + ("\n".join(thread_lines) if thread_lines else "  Yok") + "\n\n"
            + f"*Coin Bazlı:*\n"    + ("\n".join(coin_lines)   if coin_lines   else "  Yok") + "\n\n"
            + f"*Kapanış Nedeni:*\n" + ("\n".join(reason_lines) if reason_lines else "  Yok") + "\n\n"
            + f"Toplam K/Z: `{self._total_pnl:+.2f} USDT`"
        )
        self.send(msg)

    def _report_daily(self):
        trades   = self._closed_trades
        total    = len(trades)
        winners  = [t for t in trades if t["pnl"] > 0]
        losers   = [t for t in trades if t["pnl"] <= 0]
        winrate  = (len(winners) / total * 100) if total else 0
        balance  = self._balance_getter() if self._balance_getter else 0
        bal_chg  = balance - self._start_balance
        bal_pct  = (bal_chg / self._start_balance * 100) if self._start_balance else 0
        avg_win  = (sum(t["pnl"] for t in winners) / len(winners)) if winners else 0
        avg_loss = (sum(t["pnl"] for t in losers)  / len(losers))  if losers  else 0
        rr       = abs(avg_win / avg_loss) if avg_loss else 0
        total_commission = sum(t.get("commission", 0) for t in trades)
        net_pnl  = self._total_pnl - total_commission
        fastest  = min(trades, key=lambda t: t["duration_sec"], default=None)
        longest  = max(trades, key=lambda t: t["duration_sec"], default=None)
        best     = max(trades, key=lambda t: t["pnl"], default=None)
        worst    = min(trades, key=lambda t: t["pnl"], default=None)

        thread_stats: dict = {}
        coin_stats:   dict = {}
        reason_stats: dict = {}
        for t in trades:
            ts = thread_stats.setdefault(t["thread"], {"pnl": 0.0, "w": 0, "l": 0})
            cs = coin_stats.setdefault(t["symbol"],   {"pnl": 0.0, "w": 0, "l": 0})
            ts["pnl"] += t["pnl"]; cs["pnl"] += t["pnl"]
            if t["pnl"] > 0: ts["w"] += 1; cs["w"] += 1
            else:             ts["l"] += 1; cs["l"] += 1
            reason_stats[t["reason"]] = reason_stats.get(t["reason"], 0) + 1

        def wr(s): return f"{(s['w'] / (s['w']+s['l']) * 100):.0f}" if (s['w']+s['l']) else "0"

        flag_lines   = [f"  • `{v['symbol']}` {v['direction'].upper()} [{v['thread']}]"          for v in self._open_flags.values()]
        trade_lines  = [f"  • `{v['symbol']}` {v['direction'].upper()} [{v['thread']}] @ `{v['entry']}`" for v in self._open_trades.values()]
        closed_lines = [f"  • `{t['symbol']}` {t['direction'].upper()} [{t['thread']}] `{t['pnl']:+.2f}` ({t['reason']})" for t in trades]
        thread_lines = [f"  `{th}`: `{s['pnl']:+.2f}` | {s['w']}W/{s['l']}L | WR%`{wr(s)}`" for th, s in thread_stats.items()]
        coin_lines   = [f"  `{cn}`: `{s['pnl']:+.2f}` | {s['w']}W/{s['l']}L | WR%`{wr(s)}`" for cn, s in coin_stats.items()]
        reason_lines = [f"  `{r}`: {c}" for r, c in reason_stats.items()]

        msg = (
            f"📊 *24 Saatlik Rapor (X)*\n\n"
            f"*Genel Özet*\n"
            f"Toplam: `{total}` | W:`{len(winners)}` L:`{len(losers)}` | WR%`{winrate:.1f}`\n"
            f"Bakiye: `{self._start_balance:.2f}` → `{balance:.2f} USDT` (`{bal_pct:+.1f}%`)\n\n"
            + (f"*En İyi:* `{best['symbol']}` {best['direction'].upper()} `{best['pnl']:+.2f} USDT`\n"  if best  else "")
            + (f"*En Kötü:* `{worst['symbol']}` {worst['direction'].upper()} `{worst['pnl']:+.2f} USDT`\n\n" if worst else "\n")
            + f"*Flagler ({len(flag_lines)}):*\n"         + ("\n".join(flag_lines)   if flag_lines   else "  Yok") + "\n\n"
            + f"*Açık İşlemler ({len(trade_lines)}):*\n"  + ("\n".join(trade_lines)  if trade_lines  else "  Yok") + "\n\n"
            + f"*Kapanan İşlemler ({total}):*\n"          + ("\n".join(closed_lines) if closed_lines else "  Yok") + "\n\n"
            + f"*Thread Bazlı:*\n"  + ("\n".join(thread_lines) if thread_lines else "  Yok") + "\n\n"
            + f"*Coin Bazlı:*\n"    + ("\n".join(coin_lines)   if coin_lines   else "  Yok") + "\n\n"
            + f"*Kapanış Nedeni:*\n" + ("\n".join(reason_lines) if reason_lines else "  Yok") + "\n\n"
            + f"*Performans*\n"
            f"Maks Drawdown: `{self._max_drawdown:.2f} USDT`\n"
            f"Ort. Kazanç: `{avg_win:+.2f}` | Ort. Kayıp: `{avg_loss:+.2f}`\n"
            f"Risk/Ödül: `{rr:.2f}`\n"
            + (f"En Hızlı: `{fastest['symbol']}` `{self._fmt_dur(fastest['duration_sec'])}`\n" if fastest else "")
            + (f"En Uzun: `{longest['symbol']}` `{self._fmt_dur(longest['duration_sec'])}`\n\n" if longest else "\n")
            + f"*Özet*\n"
            f"Komisyon: `{total_commission:.2f} USDT`\n"
            f"Brüt K/Z: `{self._total_pnl:+.2f} USDT`\n"
            f"Net K/Z: `{net_pnl:+.2f} USDT`"
        )
        self.send(msg)
        self._closed_trades.clear()
        self._total_pnl    = 0.0
        self._peak_pnl     = 0.0
        self._max_drawdown = 0.0
