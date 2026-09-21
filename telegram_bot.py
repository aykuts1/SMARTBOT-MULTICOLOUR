# -*- coding: utf-8 -*-
"""
telegram_bot.py
-----------------
Telegram komutlarini dinler (/Z /X /Q /pozisyonlar /coinrapor /rapor.. /dur /yardim)
ve periyodik raporlari (12sa->Z, 24sa->X, haftalik->Q) zamaninda gonderir.
"""

import threading
import time
from datetime import datetime, timedelta

import requests

import config
from telegram_notifier import send_message, _now_str


HELP_TEXT = (
    "📋 *KOMUTLAR*\n"
    "/Z — Yüzeysel durum raporu\n"
    "/X — Detaylı durum raporu\n"
    "/Q — Çok detaylı durum raporu\n"
    "/pozisyonlar — Açık pozisyonları listele\n"
    "/coinrapor — Tüm coinlerin özet raporu\n"
    "/rapor{coinadi} — Belirli coinin detaylı raporu (örn: /raporARB)\n"
    "/dur — Botu acil durdur\n"
    "/yardim — Bu listeyi gösterir"
)


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h} saat {m} dk" if h else f"{m} dk"


class ReportBuilder:
    """state (BotState) ve bybit_client (BybitClient) kullanarak
    Z / X / Q raporlarini ve komut ciktilarini metne cevirir."""

    def __init__(self, state, client, start_equity_holder):
        self.state = state
        self.client = client
        self.start_equity_holder = start_equity_holder  # dict: {"value": float}

    def _live_position_lines(self, detailed=False):
        lines = []
        total_pnl = 0.0
        for pos in self.state.all_positions():
            try:
                last_price = self.client.get_last_price(pos.symbol)
            except Exception:
                last_price = pos.entry_price
            if pos.side == "long":
                pnl = (last_price - pos.entry_price) * pos.qty
                emoji = "🔵"
            else:
                pnl = (pos.entry_price - last_price) * pos.qty
                emoji = "🔴"
            total_pnl += pnl
            yon = "Long" if pos.side == "long" else "Short"
            coin = pos.symbol.replace("USDT", "")
            if detailed:
                lines.append(
                    f"{emoji} {coin} — {yon} — Giriş: {pos.entry_price:.4f} — "
                    f"Kaldıraç: {pos.leverage:.0f}x — Anlık K/Z: {pnl:+.2f} USDT"
                )
            else:
                lines.append(f"{emoji} {coin}/USDT — {yon} — K/Z: {pnl:+.2f} USDT")
        return lines, total_pnl

    def build_z(self) -> str:
        try:
            equity = self.client.get_total_equity()
        except Exception:
            equity = self.start_equity_holder.get("value", 0.0)

        closed_all = self.state.trades_since(365 * 24 * 3600)
        tp_count = sum(1 for t in closed_all if t.get("reason") == "Take Profit")
        sl_count = sum(1 for t in closed_all if t.get("reason") in ("Stop Loss", "Lose Exit"))
        _, open_pnl = self._live_position_lines()
        closed_pnl = sum(t.get("pnl", 0.0) for t in closed_all)
        net = open_pnl + closed_pnl
        net_pct = (net / equity * 100) if equity else 0.0

        return (
            f"📊 *Z RAPORU* — {_now_str()}\n"
            f"Açık işlem: {self.state.total_open_count()}/{config.MAX_TOTAL_POSITIONS}\n"
            f"Toplam varlık: {equity:.2f} USDT\n"
            f"Net: {net:+.2f} USDT (%{net_pct:+.1f})\n"
            f"Kapanan işlem: {len(closed_all)} ({tp_count} TP, {sl_count} SL)\n"
            "Durum: Aktif ✅"
        )

    def build_x(self) -> str:
        try:
            equity = self.client.get_total_equity()
        except Exception:
            equity = self.start_equity_holder.get("value", 0.0)

        open_lines, open_pnl = self._live_position_lines(detailed=True)
        closed_all = self.state.trades_since(24 * 3600)
        closed_lines = []
        for t in closed_all[-10:]:
            ok = "✅" if t.get("pnl", 0) >= 0 else "❌"
            closed_lines.append(
                f"{ok} {t['symbol'].replace('USDT','')} {t['side'].capitalize()} — "
                f"{t.get('reason','')} — {t.get('pnl',0):+.2f} USDT"
            )
        closed_pnl = sum(t.get("pnl", 0.0) for t in closed_all)
        net = open_pnl + closed_pnl
        net_pct = (net / equity * 100) if equity else 0.0

        parts = [
            f"📈 *X RAPORU* — {_now_str()}",
            "",
            "*Genel*",
            f"Toplam varlık: {equity:.2f} USDT",
            f"Net: {net:+.2f} USDT (%{net_pct:+.1f})",
            f"Açık işlem: {self.state.total_open_count()}/{config.MAX_TOTAL_POSITIONS}",
            "",
            "*Açık Pozisyonlar*",
        ]
        parts.extend(open_lines or ["(yok)"])
        parts.append("")
        parts.append("*Kapanan İşlemler (son 24 saat)*")
        parts.extend(closed_lines or ["(yok)"])
        return "\n".join(parts)

    def build_q(self) -> str:
        try:
            equity = self.client.get_total_equity()
        except Exception:
            equity = self.start_equity_holder.get("value", 0.0)

        parts = [f"🔬 *Q RAPORU* — {_now_str()}", "", "*Genel*",
                  f"Toplam varlık: {equity:.2f} USDT",
                  f"Açık işlem: {self.state.total_open_count()}/{config.MAX_TOTAL_POSITIONS}",
                  ""]

        for pos in self.state.all_positions():
            try:
                last_price = self.client.get_last_price(pos.symbol)
            except Exception:
                last_price = pos.entry_price
            if pos.side == "long":
                pnl = (last_price - pos.entry_price) * pos.qty
            else:
                pnl = (pos.entry_price - last_price) * pos.qty
            pnl_pct = (pnl / pos.allocated_amount * 100) if pos.allocated_amount else 0
            yon = "Long" if pos.side == "long" else "Short"
            coin = pos.symbol.replace("USDT", "")
            dur = _fmt_duration(time.time() - pos.open_time)
            parts.append(f"*Açık Pozisyon Detayı — {coin}/USDT ({yon})*")
            parts.append(f"Giriş: {pos.entry_price:.4f}")
            parts.append(f"Lose exit: {pos.lose_exit_price:.4f} (%{pos.lose_exit_percent:.2f}) | SL: {pos.sl_price:.4f}")
            parts.append(f"Kaldıraç: {pos.leverage:.0f}x | Ayrılan miktar: {pos.allocated_amount:.2f} USDT | Hacim: {pos.qty * pos.entry_price:.2f} USDT")
            parts.append(f"Anlık fiyat: {last_price:.4f} | Anlık K/Z: {pnl:+.2f} USDT (%{pnl_pct:+.2f})")
            parts.append(f"Açılış: {datetime.fromtimestamp(pos.open_time).strftime('%d.%m.%Y %H:%M')} | Süre: {dur}")
            parts.append("")

        closed_all = self.state.trades_since(7 * 24 * 3600)
        parts.append("*Kapanan İşlem Detayı (son 7 gün)*")
        for t in closed_all[-15:]:
            ok = "✅" if t.get("pnl", 0) >= 0 else "❌"
            parts.append(
                f"{ok} {t['symbol'].replace('USDT','')} {t['side'].capitalize()} — "
                f"Giriş {t.get('entry_price',0):.4f} → Çıkış ({t.get('reason','')}) {t.get('exit_price',0):.4f} — "
                f"{t.get('pnl',0):+.2f} USDT — Süre: {_fmt_duration(t.get('duration_seconds',0))}"
            )
        if not closed_all:
            parts.append("(yok)")

        capped = [t for t in closed_all if t.get("leverage_capped")]
        parts.append("")
        parts.append("*Slot/Sistem*")
        parts.append(f"Kaldıraç limiti düşürülen işlem (7 gün): {len(capped)}")
        return "\n".join(parts)

    def build_positions_command(self) -> str:
        lines, _ = self._live_position_lines(detailed=False)
        header = f"📍 *AÇIK POZİSYONLAR* ({self.state.total_open_count()}/{config.MAX_TOTAL_POSITIONS})"
        detailed = []
        for pos in self.state.all_positions():
            try:
                last_price = self.client.get_last_price(pos.symbol)
            except Exception:
                last_price = pos.entry_price
            if pos.side == "long":
                pnl = (last_price - pos.entry_price) * pos.qty
            else:
                pnl = (pos.entry_price - last_price) * pos.qty
            pnl_pct = (pnl / pos.allocated_amount * 100) if pos.allocated_amount else 0
            emoji = "🔵" if pos.side == "long" else "🔴"
            yon = "Long" if pos.side == "long" else "Short"
            coin = pos.symbol.replace("USDT", "")
            detailed.append(
                f"{emoji} {coin}/USDT — {yon}\n"
                f"Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} | K/Z: {pnl:+.2f} USDT (%{pnl_pct:+.2f})\n"
                f"SL: {pos.sl_price:.4f} | Kaldıraç: {pos.leverage:.0f}x"
            )
        return header + "\n\n" + "\n\n".join(detailed or ["(açık pozisyon yok)"])

    def build_coinrapor_command(self) -> str:
        parts = ["📊 *COİN RAPORU* — " + _now_str(), "", "*Açık Pozisyonlar*"]
        for symbol in config.COINS:
            coin = symbol.replace("USDT", "")
            has_any = False
            for side in ("long", "short"):
                pos = self.state.get_position(symbol, side)
                if pos:
                    has_any = True
                    try:
                        last_price = self.client.get_last_price(symbol)
                    except Exception:
                        last_price = pos.entry_price
                    if side == "long":
                        pnl = (last_price - pos.entry_price) * pos.qty
                    else:
                        pnl = (pos.entry_price - last_price) * pos.qty
                    emoji = "🔵" if side == "long" else "🔴"
                    yon = "Long" if side == "long" else "Short"
                    parts.append(f"{emoji} {coin} — {yon} — Giriş: {pos.entry_price:.4f} — Anlık: {last_price:.4f} — K/Z: {pnl:+.2f} USDT")
            if not has_any:
                parts.append(f"⚪ {coin} — Pozisyon yok")

        parts.append("")
        parts.append("*Coin Bazlı İşlem İstatistiği*")
        total_trades = 0
        total_win = 0
        total_pnl = 0.0
        for symbol in config.COINS:
            coin = symbol.replace("USDT", "")
            trades = [t for t in self.state.trade_history if t.get("symbol") == symbol]
            wins = sum(1 for t in trades if t.get("pnl", 0) >= 0)
            losses = len(trades) - wins
            pnl_sum = sum(t.get("pnl", 0.0) for t in trades)
            total_trades += len(trades)
            total_win += wins
            total_pnl += pnl_sum
            parts.append(f"{coin} — {len(trades)} işlem — {wins} kâr / {losses} zarar — Toplam: {pnl_sum:+.2f} USDT")

        parts.append("")
        parts.append("*Genel Özet*")
        parts.append(f"Toplam işlem: {total_trades} | Kâr: {total_win} | Zarar: {total_trades - total_win}")
        parts.append(f"Toplam K/Z: {total_pnl:+.2f} USDT")
        return "\n".join(parts)

    def build_rapor_coin_command(self, symbol: str) -> str:
        coin = symbol.replace("USDT", "")
        parts = [f"🔬 *{coin}/USDT — DETAYLI RAPOR* — {_now_str()}", ""]

        found_open = False
        for side in ("long", "short"):
            pos = self.state.get_position(symbol, side)
            if pos:
                found_open = True
                try:
                    last_price = self.client.get_last_price(symbol)
                except Exception:
                    last_price = pos.entry_price
                if side == "long":
                    pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    pnl = (pos.entry_price - last_price) * pos.qty
                pnl_pct = (pnl / pos.allocated_amount * 100) if pos.allocated_amount else 0
                yon = "Long" if side == "long" else "Short"
                dur = _fmt_duration(time.time() - pos.open_time)
                parts.append(f"*Açık Pozisyon ({yon})*")
                parts.append(f"Giriş: {pos.entry_price:.4f}")
                parts.append(f"Lose exit: {pos.lose_exit_price:.4f} (%{pos.lose_exit_percent:.2f}) | SL: {pos.sl_price:.4f}")
                parts.append(f"Kaldıraç: {pos.leverage:.0f}x | Ayrılan miktar: {pos.allocated_amount:.2f} USDT | Hacim: {pos.qty*pos.entry_price:.2f} USDT")
                parts.append(f"Anlık fiyat: {last_price:.4f} | Anlık K/Z: {pnl:+.2f} USDT (%{pnl_pct:+.2f})")
                parts.append(f"Açılış: {datetime.fromtimestamp(pos.open_time).strftime('%d.%m.%Y %H:%M')} | Süre: {dur}")
                parts.append("")
        if not found_open:
            parts.append("Açık pozisyon yok.")
            parts.append("")

        trades = [t for t in self.state.trade_history if t.get("symbol") == symbol]
        parts.append("*İşlem Geçmişi (son 5)*")
        for t in trades[-5:]:
            ok = "✅" if t.get("pnl", 0) >= 0 else "❌"
            parts.append(
                f"{ok} {t['side'].capitalize()} — Giriş {t.get('entry_price',0):.4f} → "
                f"Çıkış {t.get('exit_price',0):.4f} ({t.get('reason','')}) — "
                f"{t.get('pnl',0):+.2f} USDT — {_fmt_duration(t.get('duration_seconds',0))}"
            )
        if not trades:
            parts.append("(yok)")

        if trades:
            wins = [t for t in trades if t.get("pnl", 0) >= 0]
            losses = [t for t in trades if t.get("pnl", 0) < 0]
            total_pnl = sum(t.get("pnl", 0.0) for t in trades)
            avg_dur = sum(t.get("duration_seconds", 0) for t in trades) / len(trades)
            best = max(trades, key=lambda t: t.get("pnl", 0))
            worst = min(trades, key=lambda t: t.get("pnl", 0))
            parts.append("")
            parts.append("*Bu Coin İçin Toplam*")
            parts.append(f"İşlem: {len(trades)} | Kâr: {len(wins)} | Zarar: {len(losses)}")
            parts.append(f"Toplam K/Z: {total_pnl:+.2f} USDT")
            parts.append(f"Ortalama işlem süresi: {_fmt_duration(avg_dur)}")
            parts.append(f"En büyük kâr: {best.get('pnl',0):+.2f} USDT | En büyük zarar: {worst.get('pnl',0):+.2f} USDT")

        return "\n".join(parts)


class TelegramCommandListener:
    """Telegram'dan gelen komutlari (uzun-polling ile getUpdates) dinler."""

    def __init__(self, report_builder: ReportBuilder, stop_flag_holder: dict):
        self.report_builder = report_builder
        self.stop_flag_holder = stop_flag_holder  # {"stop": False} -> main.py bunu okur
        self._last_update_id = 0
        self._running = True

    def _get_updates(self):
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
        try:
            resp = requests.get(url, params={
                "offset": self._last_update_id + 1,
                "timeout": 25,
            }, timeout=30)
            return resp.json().get("result", [])
        except Exception as e:
            print(f"[telegram-cmd] getUpdates hatasi: {e}")
            return []

    def _handle_command(self, text: str):
        text = text.strip()
        low = text.lower()
        if low in ("/z",):
            send_message(self.report_builder.build_z())
        elif low in ("/x",):
            send_message(self.report_builder.build_x())
        elif low in ("/q",):
            send_message(self.report_builder.build_q())
        elif low in ("/pozisyonlar",):
            send_message(self.report_builder.build_positions_command())
        elif low in ("/coinrapor",):
            send_message(self.report_builder.build_coinrapor_command())
        elif low in ("/dur",):
            self.stop_flag_holder["stop"] = True
            open_count = self.report_builder.state.total_open_count()
            send_message(
                "🛑 *BOT DURDURULUYOR*\n"
                f"Açık pozisyonlar: {open_count} (kapatılmıyor, olduğu gibi bırakılıyor — SL'ler borsada aktif kalır)\n"
                "Yeni sinyal takibi: Durduruldu\n"
                "Veri akışı: Durduruldu\n"
                "Durum: Bot pasif — yeniden başlatmak için sunucudan manuel çalıştırılmalı\n"
                f"Saat: {_now_str()}"
            )
        elif low in ("/yardim", "/help"):
            send_message(HELP_TEXT)
        elif low.startswith("/rapor") and len(low) > len("/rapor"):
            coin_name = text[len("/rapor"):].upper()
            symbol = coin_name if coin_name.endswith("USDT") else coin_name + "USDT"
            if symbol in config.COINS:
                send_message(self.report_builder.build_rapor_coin_command(symbol))
            else:
                send_message(f"Bilinmeyen coin: {coin_name}")

    def poll_loop(self):
        while self._running and not self.stop_flag_holder.get("stop"):
            updates = self._get_updates()
            for u in updates:
                self._last_update_id = max(self._last_update_id, u["update_id"])
                msg = u.get("message", {})
                text = msg.get("text", "")
                if text.startswith("/"):
                    self._handle_command(text)

    def start(self):
        t = threading.Thread(target=self.poll_loop, daemon=True)
        t.start()
        return t


class PeriodicReportScheduler:
    """Ilk rapor 00:00'da, sonrasi periyodik: 12sa->Z, 24sa->X, haftalik->Q."""

    def __init__(self, report_builder: ReportBuilder, stop_flag_holder: dict):
        self.report_builder = report_builder
        self.stop_flag_holder = stop_flag_holder

    def _seconds_until_next_midnight(self) -> float:
        now = datetime.now()
        tomorrow_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)
        return (tomorrow_midnight - now).total_seconds()

    def run_loop(self):
        # Ilk rapor icin 00:00'a kadar bekle
        wait_s = self._seconds_until_next_midnight()
        print(f"[reports] Ilk periyodik rapora kadar bekleniyor: {wait_s/3600:.1f} saat")
        self._sleep_until(wait_s)
        if self.stop_flag_holder.get("stop"):
            return

        last_sent = {"Z": time.time(), "X": time.time(), "Q": time.time()}
        # ilk rapor - hepsini bir kerede gonder (00:00 raporu)
        send_message(self.report_builder.build_z())

        while not self.stop_flag_holder.get("stop"):
            now = time.time()
            if now - last_sent["Z"] >= config.REPORT_SCHEDULE["Z"]:
                send_message(self.report_builder.build_z())
                last_sent["Z"] = now
            if now - last_sent["X"] >= config.REPORT_SCHEDULE["X"]:
                send_message(self.report_builder.build_x())
                last_sent["X"] = now
            if now - last_sent["Q"] >= config.REPORT_SCHEDULE["Q"]:
                send_message(self.report_builder.build_q())
                last_sent["Q"] = now
            self._sleep_until(60)  # her dakika kontrol et

    def _sleep_until(self, seconds):
        end = time.time() + seconds
        while time.time() < end and not self.stop_flag_holder.get("stop"):
            time.sleep(min(5, end - time.time()))

    def start(self):
        t = threading.Thread(target=self.run_loop, daemon=True)
        t.start()
        return t
