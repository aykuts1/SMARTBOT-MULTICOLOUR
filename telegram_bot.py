import os
import time
import threading
import requests as req_lib
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from logger_setup import get_logger
from utils import (
    format_usdt, format_pnl, format_duration, now_str,
    ecosystem_emoji, ecosystem_display_name, side_emoji, side_display
)

log = get_logger("telegram")


class TelegramBot:
    def __init__(self, bot_manager=None):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.bot_manager = bot_manager
        self.app = None
        self._running = False

        self.daily_stats = self._init_stats()
        self.hourly_stats = self._init_stats()
        self.stats_6h = self._init_stats()
        self.stats_12h = self._init_stats()

    def _init_stats(self):
        return {
            "opened": 0, "closed": 0, "skipped": 0,
            "wins": 0, "losses": 0, "pnl": 0.0, "commission": 0.0,
            "ecosystem_stats": {},
            "exit_reasons": {"Winrate": 0, "Lose Exit": 0, "Chandelier": 0},
            "best_coin": None, "best_pnl": 0,
            "worst_coin": None, "worst_pnl": 0,
            "start_balance": 0
        }

    def reset_stats(self, stats):
        for key in self._init_stats():
            stats[key] = self._init_stats()[key]

    def _get_eco_stats(self, stats, eco_name):
        if eco_name not in stats["ecosystem_stats"]:
            stats["ecosystem_stats"][eco_name] = {
                "opened": 0, "closed": 0, "open_count": 0,
                "wins": 0, "losses": 0, "pnl": 0.0
            }
        return stats["ecosystem_stats"][eco_name]

    def record_open(self, ecosystem):
        for stats in [self.daily_stats, self.hourly_stats, self.stats_6h, self.stats_12h]:
            stats["opened"] += 1
            eco = self._get_eco_stats(stats, ecosystem)
            eco["opened"] += 1

    def record_close(self, ecosystem, pnl, reason, symbol):
        for stats in [self.daily_stats, self.hourly_stats, self.stats_6h, self.stats_12h]:
            stats["closed"] += 1
            stats["pnl"] += pnl
            if pnl >= 0:
                stats["wins"] += 1
            else:
                stats["losses"] += 1
            if reason in stats["exit_reasons"]:
                stats["exit_reasons"][reason] += 1

            eco = self._get_eco_stats(stats, ecosystem)
            eco["closed"] += 1
            eco["pnl"] += pnl
            if pnl >= 0:
                eco["wins"] += 1
            else:
                eco["losses"] += 1

            if pnl > stats["best_pnl"]:
                stats["best_pnl"] = pnl
                stats["best_coin"] = symbol
            if pnl < stats["worst_pnl"]:
                stats["worst_pnl"] = pnl
                stats["worst_coin"] = symbol

    def record_skip(self):
        for stats in [self.daily_stats, self.hourly_stats, self.stats_6h, self.stats_12h]:
            stats["skipped"] += 1

    def send(self, text):
        if not self.token or not self.chat_id:
            log.warning("Telegram yapilandirilmamis (token veya chat_id eksik)")
            return
        try:
            import requests as req
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML"
            }
            resp = req.post(url, json=payload, timeout=10)
            if not resp.ok:
                log.error("Telegram gonderim hatasi: %s", resp.text)
        except Exception as e:
            log.error("Telegram gonderim hatasi: %s", e)

    # === OTOMATİK BİLDİRİMLER ===

    def send_bot_started(self, balance, margin, leverage, ecosystems, open_count, untagged):
        risk = balance * margin
        eco_lines = []
        for name, active in ecosystems.items():
            icon = "✅" if active else "⛔"
            eco_lines.append(f"  ● {ecosystem_display_name(name)}  {icon}")

        msg = f"""🟢 BOT BAŞLADI

🕐 {now_str()}

💰 Bakiye: {format_usdt(balance)} USDT
📐 Marjin: {format_usdt(risk)} USDT (%{margin*100:.0f})
⚡ Kaldıraç: {leverage}x
🎯 İşlem başına risk: {format_usdt(risk)} USDT

📊 Aktif Ekosistemler:
{chr(10).join(eco_lines)}

📌 Açık Pozisyon: {open_count}"""

        if untagged:
            for u in untagged:
                msg += f"\n⚠️ Etiketsiz Pozisyon: {u['symbol']} {u['side']} — dokunulmayacak"

        self.send(msg)

    def send_bot_stopped(self, eco_counts):
        lines = []
        for name, count in eco_counts.items():
            lines.append(f"  ● {ecosystem_display_name(name)}:  {count}")

        total = sum(eco_counts.values())
        msg = f"""🔴 BOT DURDURULDU

🕐 {now_str()}

📌 Açık Pozisyon: {total}
{chr(10).join(lines)}

⚠️ Açık pozisyonlar Bybit'te kalmaya devam ediyor.
Stop loss'lar aktif."""
        self.send(msg)

    def send_trade_opened(self, trade_info, table):
        side = trade_info.get("side", "")
        ecosystem = trade_info.get("ecosystem", "")
        symbol = trade_info.get("symbol", "")
        entry = trade_info.get("entry_price", 0)

        self.record_open(ecosystem.lower())

        is_hedge = ecosystem.lower() in ("mavi", "mavi1", "mavi2", "mor", "turuncu", "gri", "silver")
        is_dynamic = table.get("dynamic", False)

        msg = f"""{side_emoji(side)} İŞLEM AÇILDI — {side_display(side)}

🪙 {symbol}  |  {ecosystem_emoji(ecosystem.lower())} {ecosystem_display_name(ecosystem.lower())}
🕐 {now_str()}

💵 Giriş:      {format_usdt(entry)} USDT
📐 Marjin:     {format_usdt(trade_info.get('margin', 0))} USDT
📦 Miktar:     {trade_info.get('qty', 0):.6f}
⚡ Kaldıraç:   {trade_info.get('leverage', 50)}x
💸 Komisyon:   {format_usdt(trade_info.get('commission', 0))} USDT

🛡️ Stop Loss:  {format_usdt(trade_info.get('sl_price', 0))} USDT  (%2)"""

        # Lose Exit (opsiyonel, sadece geçerli değer varsa)
        le = table.get("lose_exit", 0)
        if le > 0:
            suffix = "  (dinamik, Üst 3)" if is_dynamic and side == "short" else (
                "  (dinamik, Alt 3)" if is_dynamic else "")
            msg += f"\n❌ Lose Exit:  {format_usdt(le)} USDT{suffix}"

        # Winrate (opsiyonel - hedge'lerde yok)
        wr = table.get("winrate", 0)
        if wr > 0 and not is_hedge:
            suffix = "  (dinamik, Alt 7)" if is_dynamic and side == "short" else (
                "  (dinamik, Üst 7)" if is_dynamic else "")
            msg += f"\n🎯 Winrate:    {format_usdt(wr)} USDT{suffix}"

        # Hedge ise ana işlem bilgisi de eklensin
        if is_hedge:
            msg += "\n\n🔗 Hedge işlemi — ana işlem ile bağlı"

        self.send(msg)

    def send_trade_closed(self, close_info):
        side = close_info.get("side", "")
        ecosystem = close_info.get("ecosystem", "")
        pnl = close_info.get("pnl", 0)
        pnl_pct = close_info.get("pnl_pct", 0)
        reason = close_info.get("reason", "")
        symbol = close_info.get("symbol", "")

        self.record_close(ecosystem, pnl, reason, symbol)

        duration_str = format_duration(close_info.get("duration", 0))
        pnl_str = format_pnl(pnl, pnl_pct)
        daily_pnl = self.daily_stats["pnl"]
        balance = 0
        if self.bot_manager:
            b = self.bot_manager.get_balance()
            if b:
                balance = b.get("total", 0)
        daily_pct = (daily_pnl / balance * 100) if balance > 0 else 0

        icon = "📉" if side == "short" else "📈"
        msg = f"""{icon} İŞLEM KAPANDI — {side_display(side)}

🪙 {symbol}  |  {ecosystem_emoji(ecosystem)} {ecosystem_display_name(ecosystem)}
🕐 {now_str()}

💵 Giriş:      {format_usdt(close_info.get('entry_price', 0))} USDT
💵 Çıkış:      {format_usdt(close_info.get('exit_price', 0))} USDT
⏱️ Süre:       {duration_str}

📦 Miktar:     {close_info.get('qty', 0):.6f}
💸 Komisyon:   {format_usdt(close_info.get('commission', 0))} USDT

💰 Kar/Zarar:  {pnl_str}
🏁 Sebep:      {reason}

📊 Günlük PnL: {"+" if daily_pnl >= 0 else ""}{format_usdt(daily_pnl)} USDT  |  {"+" if daily_pct >= 0 else ""}%{abs(daily_pct):.2f}"""
        self.send(msg)

    def send_insufficient_balance(self, symbol, ecosystem, available, required):
        self.record_skip()
        msg = f"""⚠️ YETERSİZ BAKİYE — İŞLEM ATLANDI

🪙 {symbol}  |  {ecosystem_emoji(ecosystem.lower())} {ecosystem_display_name(ecosystem.lower())}
🕐 {now_str()}

💰 Mevcut Bakiye:    {format_usdt(available)} USDT
📐 Gereken Marjin:   {format_usdt(required)} USDT

❌ İşlem açılamadı."""
        self.send(msg)

    def send_slot_full(self, symbol, ecosystem, current_count):
        self.record_skip()
        msg = f"""⚠️ SLOT DOLU — İŞLEM ATLANDI

🪙 {symbol}  |  {ecosystem_emoji(ecosystem.lower())} {ecosystem_display_name(ecosystem.lower())}
🕐 {now_str()}

📌 Açık İşlem:   {current_count} / 20

❌ İşlem açılamadı."""
        self.send(msg)

    def send_min_size_alert(self, symbol, ecosystem, calculated, minimum):
        self.record_skip()
        msg = f"""⚠️ MİNİMUM BÜYÜKLÜK — İŞLEM ATLANDI

🪙 {symbol}  |  {ecosystem_emoji(ecosystem.lower())} {ecosystem_display_name(ecosystem.lower())}
🕐 {now_str()}

📦 Hesaplanan Miktar:   {calculated:.6f}
📦 Minimum Miktar:      {minimum:.6f}

❌ İşlem açılamadı."""
        self.send(msg)

    def send_order_error(self, symbol, ecosystem, attempts, error):
        msg = f"""🔴 İŞLEM AÇMA HATASI

🪙 {symbol}  |  {ecosystem_emoji(ecosystem.lower())} {ecosystem_display_name(ecosystem.lower())}
🕐 {now_str()}

🔁 Deneme:     {attempts} / {attempts}
❌ Hata:       {error}

⛔ Sinyal atlandı."""
        self.send(msg)

    def send_close_error(self, symbol, ecosystem, reason, attempt, error, elapsed, first=True):
        if first:
            msg = f"""🚨 İŞLEM KAPATMA HATASI

🪙 {symbol}  |  {ecosystem_emoji(ecosystem.lower())} {ecosystem_display_name(ecosystem.lower())}
🕐 {now_str()}

🏁 Kapatma Sebebi:  {reason}
🔁 Deneme:          {attempt}
❌ Hata:            {error}

⏳ Yeniden deneniyor..."""
        else:
            msg = f"""🚨 İŞLEM KAPATMA HATASI — DEVAM EDİYOR

🪙 {symbol}  |  {ecosystem_emoji(ecosystem.lower())} {ecosystem_display_name(ecosystem.lower())}
🕐 {now_str()}

🏁 Kapatma Sebebi:  {reason}
🔁 Deneme:          {attempt}
⏱️ Geçen Süre:      {format_duration(elapsed)}
❌ Hata:            {error}

⏳ Yeniden deneniyor..."""
        self.send(msg)

    def send_connection_lost(self):
        msg = f"""🔴 BAĞLANTI KOPTU

🕐 {now_str()}

❌ Bybit websocket bağlantısı kesildi.
⏳ Yeniden bağlanılıyor..."""
        self.send(msg)

    def send_connection_restored(self, downtime):
        msg = f"""🟢 BAĞLANTI KURULDU

🕐 {now_str()}

✅ Bybit bağlantısı yeniden sağlandı.
⏱️ Kesinti Süresi: {format_duration(downtime)}"""
        self.send(msg)

    def send_critical_error(self, error):
        msg = f"""🚨 KRİTİK HATA — GÜVENLİK MODU

🕐 {now_str()}

❌ Hata:   {error}
⛔ Bot yeni işlem açmayı durdurdu.

⚠️ Manuel müdahale gerekiyor."""
        self.send(msg)

    # === PERİYODİK RAPORLAR ===

    def send_hourly_report(self, balance, open_counts):
        stats = self.hourly_stats
        pnl = stats["pnl"]
        pct = (pnl / balance * 100) if balance > 0 else 0

        eco_lines = []
        for name in ["kirmizi", "beyaz", "sari", "siyah", "gold"]:
            eco = stats["ecosystem_stats"].get(name, {})
            oc = open_counts.get(name, 0)
            closed = eco.get("closed", 0)
            epnl = eco.get("pnl", 0.0)
            eco_lines.append(
                f"  ● {ecosystem_display_name(name)}:  {oc} açık  |  {closed} kapandı  |  "
                f"{'+'if epnl>=0 else ''}{format_usdt(epnl)} USDT"
            )

        total_open = sum(open_counts.values())
        msg = f"""📊 1 SAATLİK RAPOR
🕐 {now_str()}

💰 Bakiye:       {format_usdt(balance)} USDT
📈 Saatlik PnL:  {"+"if pnl>=0 else ""}{format_usdt(pnl)} USDT  |  {"+"if pct>=0 else ""}%{abs(pct):.2f}

📌 Açık Pozisyonlar: {total_open}

🔁 Son 1 Saatte:
  ● Açılan:   {stats['opened']}
  ● Kapanan:  {stats['closed']}
  ● Atlanan:  {stats['skipped']}

📊 Ekosistem Özeti:
{chr(10).join(eco_lines)}"""
        self.send(msg)
        self.reset_stats(self.hourly_stats)

    def send_6h_report(self, balance, open_counts):
        stats = self.stats_6h
        pnl = stats["pnl"]
        pct = (pnl / balance * 100) if balance > 0 else 0
        total_open = sum(open_counts.values())

        best = f"🏆 En İyi:   {stats['best_coin']}  +%{abs(stats['best_pnl']):.2f}" if stats["best_coin"] else ""
        worst = f"💔 En Kötü:  {stats['worst_coin']}  -%{abs(stats['worst_pnl']):.2f}" if stats["worst_coin"] else ""

        eco_table = self._build_eco_table(stats, open_counts, show_winpct=False)
        eco_pnl = self._build_eco_pnl(stats)

        msg = f"""📊 6 SAATLİK RAPOR
🕐 {now_str()}

💰 Bakiye:        {format_usdt(balance)} USDT
📈 6 Saatlik PnL: {"+"if pnl>=0 else ""}{format_usdt(pnl)} USDT  |  {"+"if pct>=0 else ""}%{abs(pct):.2f}

📌 Açık Pozisyonlar: {total_open}

🔁 Son 6 Saatte:
  ● Açılan:   {stats['opened']}
  ● Kapanan:  {stats['closed']}
  ● Atlanan:  {stats['skipped']}

{best}
{worst}

{eco_table}

{eco_pnl}"""
        self.send(msg)
        self.reset_stats(self.stats_6h)

    def send_12h_report(self, balance, open_counts):
        stats = self.stats_12h
        pnl = stats["pnl"]
        pct = (pnl / balance * 100) if balance > 0 else 0
        total_open = sum(open_counts.values())

        best = f"🏆 En İyi:   {stats['best_coin']}  +%{abs(stats['best_pnl']):.2f}" if stats["best_coin"] else ""
        worst = f"💔 En Kötü:  {stats['worst_coin']}  -%{abs(stats['worst_pnl']):.2f}" if stats["worst_coin"] else ""

        eco_table = self._build_eco_table(stats, open_counts, show_winpct=True)
        eco_pnl = self._build_eco_pnl(stats, show_icon=True)
        exit_dist = self._build_exit_distribution(stats, show_pct=False)

        msg = f"""📊 12 SAATLİK RAPOR
🕐 {now_str()}

💰 Bakiye:         {format_usdt(balance)} USDT
📈 12 Saatlik PnL: {"+"if pnl>=0 else ""}{format_usdt(pnl)} USDT  |  {"+"if pct>=0 else ""}%{abs(pct):.2f}

📌 Açık Pozisyonlar: {total_open}

🔁 Son 12 Saatte:
  ● Açılan:   {stats['opened']}
  ● Kapanan:  {stats['closed']}
  ● Atlanan:  {stats['skipped']}

{best}
{worst}

{eco_table}

{eco_pnl}

{exit_dist}"""
        self.send(msg)
        self.reset_stats(self.stats_12h)

    def send_24h_report(self, balance, open_counts):
        stats = self.daily_stats
        pnl = stats["pnl"]
        start_bal = stats.get("start_balance", balance - pnl)
        pct = (pnl / start_bal * 100) if start_bal > 0 else 0
        total_open = sum(open_counts.values())
        total_closed = stats["closed"]
        winrate = (stats["wins"] / total_closed * 100) if total_closed > 0 else 0

        best = f"🏆 En İyi:   {stats['best_coin']}  {"+"if stats['best_pnl']>=0 else ""}{format_usdt(stats['best_pnl'])} USDT" if stats["best_coin"] else ""
        worst = f"💔 En Kötü:  {stats['worst_coin']}  {"+"if stats['worst_pnl']>=0 else ""}{format_usdt(stats['worst_pnl'])} USDT" if stats["worst_coin"] else ""

        eco_table = self._build_eco_table(stats, open_counts, show_winpct=True)
        eco_pnl = self._build_eco_pnl(stats, show_icon=True)
        exit_dist = self._build_exit_distribution(stats, show_pct=True)

        msg = f"""📊 24 SAATLİK RAPOR
🕐 {now_str()}

💰 Başlangıç Bakiye:  {format_usdt(start_bal)} USDT
💰 Bitiş Bakiye:      {format_usdt(balance)} USDT
📈 Günlük PnL:        {"+"if pnl>=0 else ""}{format_usdt(pnl)} USDT  |  {"+"if pct>=0 else ""}%{abs(pct):.2f}

📌 Gün İçinde:
  ● Açılan:    {stats['opened']}
  ● Kapanan:   {stats['closed']}
  ● Atlanan:   {stats['skipped']}
  ● Açık Kalan: {total_open}

{best}
{worst}

{eco_table}

{eco_pnl}

{exit_dist}

💸 Toplam Komisyon: {format_usdt(stats['commission'])} USDT
🏅 Genel Winrate:   %{winrate:.0f}  ({stats['wins']}W / {stats['losses']}L)"""
        self.send(msg)
        self.reset_stats(self.daily_stats)

    def _build_eco_table(self, stats, open_counts, show_winpct=False):
        header = "📊 Ekosistem Detayı:\n"
        lines = []
        for name in ["kirmizi", "beyaz", "sari", "siyah", "gold"]:
            eco = stats["ecosystem_stats"].get(name, {})
            oc = open_counts.get(name, 0)
            opened = eco.get("opened", 0)
            closed = eco.get("closed", 0)
            wins = eco.get("wins", 0)
            losses = eco.get("losses", 0)
            dn = ecosystem_display_name(name)
            line = f"  {dn}: {oc} açık | {opened} açılan | {closed} kapanan | {wins}W {losses}L"
            if show_winpct and closed > 0:
                wp = wins / closed * 100
                line += f" | %{wp:.0f}"
            lines.append(line)
        return header + "\n".join(lines)

    def _build_eco_pnl(self, stats, show_icon=False):
        lines = ["💰 Ekosistem PnL:"]
        for name in ["kirmizi", "beyaz", "sari", "siyah", "gold"]:
            eco = stats["ecosystem_stats"].get(name, {})
            epnl = eco.get("pnl", 0.0)
            sign = "+" if epnl >= 0 else ""
            icon = ""
            if show_icon:
                icon = "  ✅" if epnl >= 0 else "  ❌"
            lines.append(f"  ● {ecosystem_display_name(name)}:  {sign}{format_usdt(epnl)} USDT{icon}")
        return "\n".join(lines)

    def _build_exit_distribution(self, stats, show_pct=False):
        reasons = stats["exit_reasons"]
        total = sum(reasons.values())
        lines = ["🏅 Çıkış Dağılımı:"]
        for r in ["Winrate", "Lose Exit", "Chandelier"]:
            count = reasons.get(r, 0)
            if show_pct and total > 0:
                pct = count / total * 100
                lines.append(f"  ● {r}:    {count}  |  %{pct:.0f}")
            else:
                lines.append(f"  ● {r}:    {count}")
        return "\n".join(lines)

    # === TELEGRAM KOMUTLARI ===

    def setup_commands(self, bot_manager):
        self.bot_manager = bot_manager

    async def cmd_durdur(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "⚠️ ONAY GEREKİYOR\n\n"
            "Botu durdurmak istediğine emin misin?\n"
            "Açık pozisyonlar Bybit'te kalmaya devam edecek.\n"
            "Stop loss'lar aktif kalacak.\n\n"
            "✅ /durdur_onayla — Evet, durdur\n"
            "❌ /iptal — Hayır, vazgeç"
        )

    async def cmd_durdur_onayla(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_manager:
            self.bot_manager.stop_bot()
        await update.message.reply_text("🔴 Bot durduruldu.")

    async def cmd_baslat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_manager:
            self.bot_manager.start_bot()
        await update.message.reply_text("🟢 Bot başlatılıyor...")

    async def cmd_anlik(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_manager:
            return
        info = self.bot_manager.get_status_info()
        balance = info.get("balance", 0)
        pnl = self.daily_stats["pnl"]
        pct = (pnl / balance * 100) if balance > 0 else 0
        oc = info.get("open_counts", {})
        total = sum(oc.values())

        eco_lines = []
        for name in ["kirmizi", "beyaz", "sari", "siyah", "gold"]:
            eco = self.daily_stats["ecosystem_stats"].get(name, {})
            epnl = eco.get("pnl", 0.0)
            sign = "+" if epnl >= 0 else ""
            icon = "✅" if epnl >= 0 else "❌"
            eco_lines.append(f"  ● {ecosystem_display_name(name)}:  {sign}{format_usdt(epnl)} USDT  {icon}")

        msg = f"""📊 ANLIK RAPOR
🕐 {now_str()}

💰 Bakiye:       {format_usdt(balance)} USDT
📈 Günlük PnL:   {"+"if pnl>=0 else ""}{format_usdt(pnl)} USDT  |  {"+"if pct>=0 else ""}%{abs(pct):.2f}

📌 Açık Pozisyonlar: {total}

🔁 Bugün:
  ● Açılan:   {self.daily_stats['opened']}
  ● Kapanan:  {self.daily_stats['closed']}
  ● Atlanan:  {self.daily_stats['skipped']}

📊 Ekosistem Özeti:
{chr(10).join(eco_lines)}"""
        await update.message.reply_text(msg)

    async def cmd_durum(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_manager:
            return
        info = self.bot_manager.get_status_info()
        balance = info.get("balance", 0)
        pnl = self.daily_stats["pnl"]
        pct = (pnl / balance * 100) if balance > 0 else 0
        uptime = format_duration(info.get("uptime", 0))
        oc = info.get("open_counts", {})
        eco_states = info.get("ecosystem_states", {})
        ws_ok = info.get("ws_connected", False)
        last_data = info.get("last_data_ago", -1)

        eco_lines = []
        for name in ["kirmizi", "beyaz", "sari", "siyah", "gold"]:
            active = eco_states.get(name, False)
            icon = "✅" if active else "⛔"
            count = oc.get(name, 0)
            eco = self.daily_stats["ecosystem_stats"].get(name, {})
            epnl = eco.get("pnl", 0.0)
            eco_lines.append(
                f"  ● {ecosystem_display_name(name)}  {icon}  |  {count} açık  |  "
                f"{'+'if epnl>=0 else ''}{format_usdt(epnl)} USDT"
            )

        msg = f"""📋 DURUM RAPORU
🕐 {now_str()}

🤖 Bot:          {'Çalışıyor ✅' if info.get('running') else 'Durdu 🔴'}
⏱️ Çalışma Süresi: {uptime}

💰 Bakiye:       {format_usdt(balance)} USDT
📈 Günlük PnL:   {"+"if pnl>=0 else ""}{format_usdt(pnl)} USDT  |  {"+"if pct>=0 else ""}%{abs(pct):.2f}

📊 Ekosistemler:
{chr(10).join(eco_lines)}

🔁 Bugün:
  ● Açılan:   {self.daily_stats['opened']}
  ● Kapanan:  {self.daily_stats['closed']}
  ● Atlanan:  {self.daily_stats['skipped']}

🌐 Bybit Bağlantısı:  {'✅ Aktif' if ws_ok else '❌ Kopuk'}
📡 Websocket:         {'✅ Aktif' if ws_ok else '❌ Kopuk'}
🕐 Son Veri:          {f'{last_data:.0f} sn önce' if last_data >= 0 else 'Yok'}"""
        await update.message.reply_text(msg)

    async def cmd_pozisyonlar(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_manager:
            return
        positions = self.bot_manager.get_all_positions()
        if not positions:
            await update.message.reply_text("📌 Açık pozisyon bulunmuyor.")
            return

        msg = f"📌 AÇIK POZİSYONLAR\n🕐 {now_str()}\n\nToplam: {len(positions)} pozisyon\n"

        current_eco = ""
        for i, pos in enumerate(positions, 1):
            eco = pos.get("ecosystem", "")
            if eco != current_eco:
                current_eco = eco
                msg += f"\n─────────────────────\n{ecosystem_emoji(eco)} {ecosystem_display_name(eco).upper()}\n\n"

            pnl = pos.get("pnl", 0)
            pnl_pct = pos.get("pnl_pct", 0)
            duration = format_duration(pos.get("duration", 0))
            msg += f"""{i}. {pos['symbol']}  {side_display(pos['side'])}
   💵 Giriş:    {format_usdt(pos['entry_price'])}
   📊 Şu an:    {format_usdt(pos.get('current_price', 0))}
   💰 PnL:      {format_pnl(pnl, pnl_pct)}
   ⏱️ Süre:     {duration}\n\n"""

        await update.message.reply_text(msg[:4096])

    async def cmd_kapat_hepsi(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_manager:
            return
        positions = self.bot_manager.get_all_positions()
        total_pnl = sum(p.get("pnl", 0) for p in positions)

        await update.message.reply_text(
            f"⚠️ ONAY GEREKİYOR\n\n"
            f"Tüm açık pozisyonları kapatmak istediğine emin misin?\n\n"
            f"📌 Kapatılacak Pozisyon: {len(positions)}\n"
            f"💰 Tahmini PnL: {'+'if total_pnl>=0 else ''}{format_usdt(total_pnl)} USDT\n\n"
            f"✅ /kapat_hepsi_onayla — Evet, kapat\n"
            f"❌ /iptal — Hayır, vazgeç"
        )

    async def cmd_kapat_hepsi_onayla(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_manager:
            results = self.bot_manager.close_all()
            msg = f"⛔ TÜM POZİSYONLAR KAPATILDI\n🕐 {now_str()}\n\n"
            for r in results:
                status = "✅" if r["success"] else "❌"
                msg += f"{status} {r['symbol']} {side_display(r['side'])}    {format_usdt(r.get('pnl', 0))} USDT\n"
            await update.message.reply_text(msg)

    async def cmd_ekosistem_durdur(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Kullanım: /ekosistem_durdur [ad]\nÖrnek: /ekosistem_durdur siyah")
            return
        name = context.args[0].lower()
        await update.message.reply_text(
            f"⚠️ ONAY GEREKİYOR\n\n"
            f"{ecosystem_display_name(name)} ekosistemini durdurmak istediğine emin misin?\n\n"
            f"✅ /ekosistem_durdur_onayla {name}\n"
            f"❌ /iptal"
        )

    async def cmd_ekosistem_durdur_onayla(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or not self.bot_manager:
            return
        name = context.args[0].lower()
        self.bot_manager.stop_ecosystem(name)
        await update.message.reply_text(f"⛔ {ecosystem_display_name(name)} ekosistemi durduruldu.")

    async def cmd_ekosistem_baslat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args or not self.bot_manager:
            return
        name = context.args[0].lower()
        self.bot_manager.start_ecosystem(name)
        await update.message.reply_text(f"✅ {ecosystem_display_name(name)} ekosistemi başlatıldı.")

    async def cmd_bakiye(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_manager:
            return
        info = self.bot_manager.get_balance()
        if not info:
            await update.message.reply_text("❌ Bakiye alınamadı.")
            return
        margin_per = info["total"] * 0.02
        oc = self.bot_manager.get_status_info().get("open_counts", {})
        total = sum(oc.values())

        msg = f"""💰 BAKİYE
🕐 {now_str()}

💰 Toplam Bakiye:     {format_usdt(info['total'])} USDT
📐 Kullanılan Marjin: {format_usdt(info['used'])} USDT
💵 Serbest Bakiye:    {format_usdt(info['available'])} USDT

🎯 İşlem başına marjin: {format_usdt(margin_per)} USDT (%2)
📌 Açık Pozisyon: {total}"""
        await update.message.reply_text(msg)

    async def cmd_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_manager:
            return
        balance = self.bot_manager.get_balance()
        bal = balance["total"] if balance else 0
        daily = self.daily_stats["pnl"]
        d_pct = (daily / bal * 100) if bal > 0 else 0
        wr = (self.daily_stats["wins"] / self.daily_stats["closed"] * 100) if self.daily_stats["closed"] > 0 else 0

        eco_lines = []
        for name in ["kirmizi", "beyaz", "sari", "siyah", "gold"]:
            eco = self.daily_stats["ecosystem_stats"].get(name, {})
            epnl = eco.get("pnl", 0.0)
            sign = "+" if epnl >= 0 else ""
            icon = "✅" if epnl >= 0 else "❌"
            eco_lines.append(f"  ● {ecosystem_display_name(name)}:  {sign}{format_usdt(epnl)} USDT  {icon}")

        msg = f"""📈 KAR / ZARAR RAPORU
🕐 {now_str()}

💰 Günlük PnL:    {"+"if daily>=0 else ""}{format_usdt(daily)} USDT  |  {"+"if d_pct>=0 else ""}%{abs(d_pct):.2f}

📊 Ekosistem PnL (Bugün):
{chr(10).join(eco_lines)}

🏅 Bugün Winrate:  %{wr:.0f}  ({self.daily_stats['wins']}W / {self.daily_stats['losses']}L)
💸 Bugün Komisyon: {format_usdt(self.daily_stats['commission'])} USDT"""
        await update.message.reply_text(msg)

    async def cmd_log(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_manager:
            return
        events = self.bot_manager.get_recent_events(10)
        if not events:
            await update.message.reply_text("📋 Kayıtlı olay bulunmuyor.")
            return
        msg = f"📋 SON 10 OLAY\n🕐 {now_str()}\n\n"
        for i, ev in enumerate(events, 1):
            msg += f"{i}. {ev}\n"
        await update.message.reply_text(msg[:4096])

    async def cmd_panic(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "🚨 ACİL DURDURMA — ONAY GEREKİYOR\n\n"
            "Tüm pozisyonlar kapatılacak ve bot durdurulacak!\n\n"
            "✅ /panic_onayla — Evet, tümünü kapat ve durdur\n"
            "❌ /iptal — Hayır, vazgeç"
        )

    async def cmd_panic_onayla(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.bot_manager:
            results = self.bot_manager.close_all()
            self.bot_manager.stop_bot()
            msg = f"🚨 ACİL DURDURMA GERÇEKLEŞTİRİLDİ\n🕐 {now_str()}\n\n"
            for r in results:
                status = "✅" if r["success"] else "❌"
                msg += f"{status} {r['symbol']} {side_display(r['side'])}    {format_usdt(r.get('pnl', 0))} USDT\n"
            msg += "\n🔴 BOT DURDURULDU."
            await update.message.reply_text(msg)

    async def cmd_flagler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.bot_manager:
            return
        flags = self.bot_manager.get_all_flags()
        if not flags:
            await update.message.reply_text("🚩 Şu an açık flag bulunmuyor.")
            return

        msg = f"🚩 AÇIK FLAGLER\n🕐 {now_str()}\n\nToplam: {len(flags)} flag\n"
        for f in flags:
            elapsed = time.time() - f.get("time", time.time())
            msg += f"\n{f['symbol']}  {f['flag_name']}\n   🕐 {format_duration(elapsed)} önce"
            if "extra" in f:
                msg += f"\n   🔁 {f['extra']}"
            msg += "\n"
        await update.message.reply_text(msg[:4096])

    async def cmd_iptal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("❌ İşlem iptal edildi.")

    def start_polling(self):
        if not self.token:
            log.warning("Telegram token bulunamadi, komutlar devre disi")
            return
        thread = threading.Thread(target=self._run_polling, daemon=True)
        thread.start()
        log.info("Telegram polling thread baslatildi")

    def _run_polling(self):
        # Webhook varsa sil (webhook aktifken polling çalışmaz)
        try:
            resp = req_lib.get(
                f"https://api.telegram.org/bot{self.token}/deleteWebhook",
                params={"drop_pending_updates": True},
                timeout=10
            )
            log.info("Webhook silindi: %s", resp.json().get("description", ""))
        except Exception as e:
            log.warning("Webhook silme hatasi: %s", e)

        try:
            app = Application.builder().token(self.token).build()

            app.add_handler(CommandHandler("durdur", self.cmd_durdur))
            app.add_handler(CommandHandler("durdur_onayla", self.cmd_durdur_onayla))
            app.add_handler(CommandHandler("baslat", self.cmd_baslat))
            app.add_handler(CommandHandler("anlik", self.cmd_anlik))
            app.add_handler(CommandHandler("durum", self.cmd_durum))
            app.add_handler(CommandHandler("pozisyonlar", self.cmd_pozisyonlar))
            app.add_handler(CommandHandler("kapat_hepsi", self.cmd_kapat_hepsi))
            app.add_handler(CommandHandler("kapat_hepsi_onayla", self.cmd_kapat_hepsi_onayla))
            app.add_handler(CommandHandler("ekosistem_durdur", self.cmd_ekosistem_durdur))
            app.add_handler(CommandHandler("ekosistem_durdur_onayla", self.cmd_ekosistem_durdur_onayla))
            app.add_handler(CommandHandler("ekosistem_baslat", self.cmd_ekosistem_baslat))
            app.add_handler(CommandHandler("bakiye", self.cmd_bakiye))
            app.add_handler(CommandHandler("pnl", self.cmd_pnl))
            app.add_handler(CommandHandler("log", self.cmd_log))
            app.add_handler(CommandHandler("panic", self.cmd_panic))
            app.add_handler(CommandHandler("panic_onayla", self.cmd_panic_onayla))
            app.add_handler(CommandHandler("flagler", self.cmd_flagler))
            app.add_handler(CommandHandler("iptal", self.cmd_iptal))

            log.info("Telegram komut handler'lari eklendi, polling basliyor...")
            app.run_polling(drop_pending_updates=True, allowed_updates=["message"])
        except Exception as e:
            log.error("Telegram polling hatasi: %s", e, exc_info=True)
