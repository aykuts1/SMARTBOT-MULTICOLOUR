# -*- coding: utf-8 -*-
"""
telegram_bot.py
-----------------
Telegram komutlarini dinler (/Z /X /Q /pozisyonlar /coinrapor /rapor..
/coinperformans /dur /yardim) ve periyodik raporlari (12sa->Z, 24sa->X,
haftalik->Q) zamaninda gonderir.

KOKLU GUNCELLEME:
- Z/X/Q raporlari artik cok daha detayli: varlik gecmisine dayanarak
  onceki-donem varligi, gun ici/haftalik en yuksek-dusuk, drawdown,
  kazanma orani, en iyi/kotu islem, kapanis sebebi dagilimi vb. iceriyor.
- /coinrapor ve /rapor{coinadi} artik Supertrend yonunu ve Entry/Exit
  cizgisi seviyelerini de gosteriyor; eski "lose exit" alanlari kaldirildi.
- Yeni komut: /coinperformans - her coin'in tum-zamanlar toplam
  islem/kar/zarar/kazanma orani ozeti.
- Yuzdeler artik (kaldiracli getiri degil) ham fiyat degisim yuzdesi.
"""

import threading
import time
from datetime import datetime, timedelta

import requests

import config
import strategy
from telegram_notifier import send_message, _now_str


HELP_TEXT = (
    "📋 *KOMUTLAR*\n"
    "/Z — Yüzeysel durum raporu\n"
    "/X — Detaylı durum raporu\n"
    "/Q — Çok detaylı haftalık rapor\n"
    "/pozisyonlar — Açık pozisyonları listele\n"
    "/coinrapor — Tüm coinlerin özet raporu\n"
    "/rapor{coinadi} — Belirli coinin detaylı raporu (örn: /raporARB)\n"
    "/coinperformans — Her coin'in tüm zamanlar performans özeti\n"
    "/dur — Botu acil durdur\n"
    "/yardim — Bu listeyi gösterir"
)


def _fmt_duration(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h} saat {m} dk" if h else f"{m} dk"


def _time_ago_str(ts: float) -> str:
    delta = time.time() - ts
    if delta < 3600:
        return f"{max(1, int(delta // 60))} dakika önce"
    if delta < 86400:
        return f"{delta / 3600:.0f} saat önce"
    return f"{delta / 86400:.0f} gün önce"


def _price_change_percent(side: str, entry_price: float, last_price: float) -> float:
    """Ham fiyat degisim yuzdesi (kaldiracsiz), islem yonune gore isaretli."""
    if not entry_price:
        return 0.0
    if side == "long":
        return (last_price - entry_price) / entry_price * 100
    return (entry_price - last_price) / entry_price * 100


def _longest_streak(trades: list, win: bool) -> int:
    longest = 0
    current = 0
    for t in trades:
        is_win = t.get("pnl", 0) >= 0
        if is_win == win:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


class ReportBuilder:
    """state (BotState) ve client (BybitClient) kullanarak Z / X / Q
    raporlarini ve komut ciktilarini metne cevirir."""

    def __init__(self, state, client, start_equity_holder):
        self.state = state
        self.client = client
        self.start_equity_holder = start_equity_holder  # dict: {"value": float}

    # ------------------------------------------------------------
    # Z - YUZEYSEL
    # ------------------------------------------------------------
    def build_z(self) -> str:
        try:
            equity = self.client.get_total_equity()
        except Exception:
            equity = self.start_equity_holder.get("value", 0.0)

        window = config.REPORT_SCHEDULE["Z"]
        before = self.state.equity_before(window)
        closed = self.state.trades_since(window)
        wins = sum(1 for t in closed if t.get("pnl", 0) >= 0)
        losses = len(closed) - wins
        net = (equity - before) if before is not None else sum(t.get("pnl", 0.0) for t in closed)

        parts = [
            "📊 *Z RAPORU (Yüzeysel)*",
            f"Tarih: {_now_str()}",
            f"Toplam varlık: {equity:.2f} USDT",
        ]
        if before:
            parts.append(f"12s önceki varlık: {before:.2f} USDT (%{(equity - before) / before * 100:+.2f})")
        parts.append(f"Açık işlem sayısı: {self.state.total_open_count()}/{config.MAX_TOTAL_POSITIONS}")
        parts.append(f"Son 12 saatte kapanan işlem: {len(closed)} ({wins} kâr, {losses} zarar)")
        parts.append(f"Net Kâr/Zarar: {net:+.2f} USDT")

        if self.state.trade_history:
            last_t = self.state.trade_history[-1]
            coin = last_t["symbol"].replace("USDT", "")
            yon = "LONG" if last_t["side"] == "long" else "SHORT"
            parts.append(
                f"En son işlem: {coin}/USDT {yon} kapandı, {last_t.get('pnl', 0):+.2f} USDT "
                f"({_time_ago_str(last_t['closed_at'])})"
            )

        return "\n".join(parts)

    # ------------------------------------------------------------
    # X - DETAYLI
    # ------------------------------------------------------------
    def build_x(self) -> str:
        try:
            equity = self.client.get_total_equity()
        except Exception:
            equity = self.start_equity_holder.get("value", 0.0)

        window = config.REPORT_SCHEDULE["X"]
        before = self.state.equity_before(window)
        high, low = self.state.equity_high_low_since(window)

        parts = [
            "📈 *X RAPORU (Detaylı)*",
            f"Tarih: {_now_str()}",
            f"Toplam varlık: {equity:.2f} USDT",
        ]
        if before:
            parts.append(f"24s önceki varlık: {before:.2f} USDT (%{(equity - before) / before * 100:+.2f})")
        if high is not None:
            parts.append(f"Gün içi en yüksek varlık: {high:.2f} USDT")
            parts.append(f"Gün içi en düşük varlık: {low:.2f} USDT")

        parts.append("")
        parts.append(f"*Açık pozisyonlar ({self.state.total_open_count()}/{config.MAX_TOTAL_POSITIONS})*")
        open_lines = []
        for pos in self.state.all_positions():
            try:
                last_price = self.client.get_last_price(pos.symbol)
            except Exception:
                last_price = pos.entry_price
            pct = _price_change_percent(pos.side, pos.entry_price, last_price)
            coin = pos.symbol.replace("USDT", "")
            yon = "LONG" if pos.side == "long" else "SHORT"
            dur = _fmt_duration(time.time() - pos.open_time)
            open_lines.append(
                f"- {coin}/USDT {yon} | Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} "
                f"(%{pct:+.2f}) | Kaldıraç: {pos.leverage:.0f}x | Süre: {dur}"
            )
        parts.extend(open_lines or ["(yok)"])

        parts.append("")
        closed = self.state.trades_since(window)
        wins = [t for t in closed if t.get("pnl", 0) >= 0]
        losses = [t for t in closed if t.get("pnl", 0) < 0]
        win_rate = (len(wins) / len(closed) * 100) if closed else 0.0
        net = (equity - before) if before is not None else sum(t.get("pnl", 0.0) for t in closed)

        parts.append(f"Son 24 saatte kapanan işlemler ({len(closed)}): {len(wins)} kâr, {len(losses)} zarar | Kazanma oranı: %{win_rate:.1f}")
        parts.append(f"Net Kâr/Zarar: {net:+.2f} USDT")

        if closed:
            best = max(closed, key=lambda t: t.get("pnl", 0))
            worst = min(closed, key=lambda t: t.get("pnl", 0))
            parts.append(
                f"En iyi işlem: {best['symbol'].replace('USDT', '')}/USDT {best.get('pnl', 0):+.2f} USDT "
                f"(%{best.get('price_change_percent', 0):+.2f} fiyat değişimi)"
            )
            parts.append(
                f"En kötü işlem: {worst['symbol'].replace('USDT', '')}/USDT {worst.get('pnl', 0):+.2f} USDT "
                f"(%{worst.get('price_change_percent', 0):+.2f} fiyat değişimi)"
            )
            avg_dur = sum(t.get("duration_seconds", 0) for t in closed) / len(closed)
            parts.append(f"Ortalama işlem süresi: {_fmt_duration(avg_dur)}")

            tp_count = sum(1 for t in closed if t.get("reason") == "Take Profit")
            flip_count = sum(1 for t in closed if t.get("reason") == "Trend Dönüşü")
            sl_count = sum(1 for t in closed if t.get("reason") == "Stop Loss")
            parts.append(f"Kapanış sebebi dağılımı: Take Profit {tp_count} | Trend Dönüşü {flip_count} | Stop Loss {sl_count}")

        return "\n".join(parts)

    # ------------------------------------------------------------
    # Q - COK DETAYLI (HAFTALIK)
    # ------------------------------------------------------------
    def build_q(self) -> str:
        try:
            equity = self.client.get_total_equity()
        except Exception:
            equity = self.start_equity_holder.get("value", 0.0)

        window = config.REPORT_SCHEDULE["Q"]
        before = self.state.equity_before(window)
        high, low = self.state.equity_high_low_since(window)
        max_dd = self.state.max_drawdown_since(window)
        closed = self.state.trades_since(window)

        period_start = datetime.fromtimestamp(time.time() - window).strftime("%d.%m.%Y")
        period_end = datetime.now().strftime("%d.%m.%Y")

        parts = [
            "📑 *Q RAPORU (Çok Detaylı - Haftalık)*",
            f"Dönem: {period_start} - {period_end}",
        ]
        if before:
            total_return = (equity - before) / before * 100
            parts.append(f"Başlangıç varlık: {before:.2f} USDT | Şimdiki: {equity:.2f} USDT")
            parts.append(f"Toplam getiri: %{total_return:+.2f}")
        else:
            parts.append(f"Şimdiki varlık: {equity:.2f} USDT")
        if high is not None:
            parts.append(f"Haftalık en yüksek varlık: {high:.2f} USDT | En düşük: {low:.2f} USDT")
            parts.append(f"Maks düşüş (drawdown): %{max_dd:.2f}")
        parts.append("")

        wins = [t for t in closed if t.get("pnl", 0) >= 0]
        losses = [t for t in closed if t.get("pnl", 0) < 0]
        win_rate = (len(wins) / len(closed) * 100) if closed else 0.0

        parts.append(f"Toplam kapanan işlem: {len(closed)} ({len(wins)} kâr, {len(losses)} zarar) | Kazanma oranı: %{win_rate:.1f}")
        if wins:
            avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins)
            avg_win_pct = sum(t.get("price_change_percent", 0) for t in wins) / len(wins)
            parts.append(f"Ortalama kâr: {avg_win:+.2f} USDT (%{avg_win_pct:+.2f} fiyat değişimi)")
        if losses:
            avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses)
            avg_loss_pct = sum(t.get("price_change_percent", 0) for t in losses) / len(losses)
            parts.append(f"Ortalama zarar: {avg_loss:+.2f} USDT (%{avg_loss_pct:+.2f} fiyat değişimi)")

        parts.append(f"En uzun kâr serisi: {_longest_streak(closed, True)} işlem üst üste")
        parts.append(f"En uzun zarar serisi: {_longest_streak(closed, False)} işlem üst üste")
        if closed:
            avg_dur = sum(t.get("duration_seconds", 0) for t in closed) / len(closed)
            parts.append(f"Ortalama işlem süresi: {_fmt_duration(avg_dur)}")
            avg_lev = sum(t.get("leverage", 0) for t in closed) / len(closed)
            parts.append(f"Ortalama kullanılan kaldıraç: {avg_lev:.1f}x")
        parts.append("")

        parts.append("*Coin bazlı dağılım*")
        coin_stats = []
        for symbol in config.COINS:
            trades = [t for t in closed if t.get("symbol") == symbol]
            if not trades:
                continue
            w = sum(1 for t in trades if t.get("pnl", 0) >= 0)
            pnl_sum = sum(t.get("pnl", 0.0) for t in trades)
            coin_stats.append((symbol.replace("USDT", ""), len(trades), w / len(trades) * 100, pnl_sum))
        coin_stats.sort(key=lambda s: s[1], reverse=True)
        for coin, count, wr, pnl_sum in coin_stats:
            parts.append(f"- {coin}: {count} işlem, %{wr:.0f} kazanma, {pnl_sum:+.2f} USDT")
        no_trade_coins = [s.replace("USDT", "") for s in config.COINS
                           if not any(t.get("symbol") == s for t in closed)]
        if no_trade_coins:
            parts.append(f"(diğer coinler: işlem yok — {', '.join(no_trade_coins)})")
        parts.append("")

        parts.append("*Kapanış sebebi dağılımı*")
        total_closed = len(closed) or 1
        tp_count = sum(1 for t in closed if t.get("reason") == "Take Profit")
        flip_count = sum(1 for t in closed if t.get("reason") == "Trend Dönüşü")
        sl_count = sum(1 for t in closed if t.get("reason") == "Stop Loss")
        parts.append(f"- Take Profit: {tp_count} işlem (%{tp_count / total_closed * 100:.1f})")
        parts.append(f"- Trend Dönüşü: {flip_count} işlem (%{flip_count / total_closed * 100:.1f})")
        parts.append(f"- Stop Loss: {sl_count} işlem (%{sl_count / total_closed * 100:.1f})")
        parts.append("")

        insuf = len(self.state.system_events_since(window, "insufficient_balance"))
        slot_full = len(self.state.system_events_since(window, "slot_full"))
        lev_capped = len(self.state.system_events_since(window, "leverage_capped"))
        parts.append(f"Bakiye yetersiz nedeniyle atlanan sinyal: {insuf}")
        parts.append(f"Slot dolu nedeniyle atlanan sinyal: {slot_full}")
        parts.append(f"Kaldıraç limiti aşılan işlem: {lev_capped}")

        return "\n".join(parts)

    # ------------------------------------------------------------
    # /pozisyonlar
    # ------------------------------------------------------------
    def build_positions_command(self) -> str:
        header = f"📂 *AÇIK POZİSYONLAR* ({self.state.total_open_count()}/{config.MAX_TOTAL_POSITIONS})"
        blocks = []
        for pos in self.state.all_positions():
            try:
                last_price = self.client.get_last_price(pos.symbol)
            except Exception:
                last_price = pos.entry_price
            pct = _price_change_percent(pos.side, pos.entry_price, last_price)
            if pos.side == "long":
                pnl = (last_price - pos.entry_price) * pos.qty
            else:
                pnl = (pos.entry_price - last_price) * pos.qty
            emoji = "🔵" if pos.side == "long" else "🔴"
            yon = "Long" if pos.side == "long" else "Short"
            coin = pos.symbol.replace("USDT", "")
            blocks.append(
                f"{emoji} {coin}/USDT — {yon}\n"
                f"Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} | "
                f"K/Z: {pnl:+.2f} USDT (%{pct:+.2f} fiyat değişimi)\n"
                f"SL: {pos.sl_price:.4f} | Kaldıraç: {pos.leverage:.0f}x"
            )
        return header + "\n\n" + "\n\n".join(blocks or ["(açık pozisyon yok)"])

    # ------------------------------------------------------------
    # /coinrapor
    # ------------------------------------------------------------
    def build_coinrapor_command(self) -> str:
        parts = ["📋 *COIN RAPORU*", f"Tarih: {_now_str()}", ""]

        total_open_pnl = 0.0
        for symbol in config.COINS:
            coin = symbol.replace("USDT", "")

            try:
                df = strategy.compute_indicators_for_symbol(self.client, symbol)
                trend_yonu = "Long" if df.iloc[-1]["trend"] == 1 else "Short"
            except Exception:
                trend_yonu = "?"

            pos = self.state.get_position(symbol)
            if pos:
                try:
                    last_price = self.client.get_last_price(symbol)
                except Exception:
                    last_price = pos.entry_price
                pct = _price_change_percent(pos.side, pos.entry_price, last_price)
                if pos.side == "long":
                    pnl = (last_price - pos.entry_price) * pos.qty
                else:
                    pnl = (pos.entry_price - last_price) * pos.qty
                total_open_pnl += pnl
                dur = _fmt_duration(time.time() - pos.open_time)
                yon = pos.side.upper()
                parts.append(
                    f"*{coin}/USDT*\n"
                    f"  Durum: {yon} açık | Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} (%{pct:+.2f})\n"
                    f"  Kaldıraç: {pos.leverage:.0f}x | Süre: {dur} | Supertrend yönü: {trend_yonu}"
                )
            else:
                trades = self.state.trades_for_symbol(symbol)
                if trades:
                    last_t = trades[-1]
                    son_islem = f"{_time_ago_str(last_t['closed_at'])} ({last_t.get('pnl', 0):+.2f} USDT)"
                else:
                    son_islem = "yok"
                parts.append(
                    f"*{coin}/USDT*\n"
                    f"  Durum: Pozisyon yok | Supertrend yönü: {trend_yonu} | Son işlem: {son_islem}"
                )
            parts.append("")

        parts.append(
            f"Özet: {self.state.total_open_count()} pozisyon açık, {len(config.COINS)} coin izlemede | "
            f"Toplam anlık Kâr/Zarar: {total_open_pnl:+.2f} USDT"
        )
        return "\n".join(parts)

    # ------------------------------------------------------------
    # /rapor{coinadi}
    # ------------------------------------------------------------
    def build_rapor_coin_command(self, symbol: str) -> str:
        coin = symbol.replace("USDT", "")
        parts = [f"🔍 *{coin}/USDT — DETAY*", f"Tarih: {_now_str()}", ""]

        try:
            df = strategy.compute_indicators_for_symbol(self.client, symbol)
            last_row = df.iloc[-1]
            trend_yonu = "Long" if last_row["trend"] == 1 else "Short"
            parts.append("*Anlık durum*")
            parts.append(f"  Fiyat: {last_row['close']:.4f} | Supertrend yönü: {trend_yonu}")
            parts.append(f"  Entry çizgisi: {last_row['entry_line']:.4f} | Exit çizgisi: {last_row['exit_line']:.4f}")
        except Exception as e:
            parts.append(f"(Anlık gösterge verisi alınamadı: {e})")
        parts.append("")

        pos = self.state.get_position(symbol)
        if pos:
            try:
                last_price = self.client.get_last_price(symbol)
            except Exception:
                last_price = pos.entry_price
            pct = _price_change_percent(pos.side, pos.entry_price, last_price)
            if pos.side == "long":
                pnl = (last_price - pos.entry_price) * pos.qty
            else:
                pnl = (pos.entry_price - last_price) * pos.qty
            yon = "LONG" if pos.side == "long" else "SHORT"
            dur = _fmt_duration(time.time() - pos.open_time)
            parts.append("*Açık pozisyon*")
            parts.append(f"  Yön: {yon} | Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} (%{pct:+.2f})")
            if pos.exit_line_at_entry:
                exit_mesafe = (pos.exit_line_at_entry - pos.entry_price) / pos.entry_price * 100
                parts.append(f"  Exit çizgisi (TP, açılış anı): {pos.exit_line_at_entry:.4f} (mesafe: %{exit_mesafe:+.2f})")
            sl_mesafe = (pos.sl_price - pos.entry_price) / pos.entry_price * 100
            parts.append(f"  Güvenlik SL: {pos.sl_price:.4f} (mesafe: %{sl_mesafe:+.2f})")
            parts.append(
                f"  Kaldıraç: {pos.leverage:.0f}x | Stake: {pos.allocated_amount:.2f} USDT | "
                f"İşlem hacmi: {pos.qty * pos.entry_price:.2f} USDT"
            )
            parts.append(f"  Anlık Kâr/Zarar: {pnl:+.2f} USDT")
            parts.append(f"  Açılış: {datetime.fromtimestamp(pos.open_time).strftime('%d.%m.%Y %H:%M')} | Süre: {dur}")
        else:
            parts.append("Açık pozisyon: Yok")
        parts.append("")

        window = 7 * 24 * 3600
        cutoff = time.time() - window
        trades = [t for t in self.state.trades_for_symbol(symbol) if t.get("closed_at", 0) >= cutoff]
        parts.append("*Bu coin'in geçmişi (son 7 gün)*")
        if trades:
            wins = [t for t in trades if t.get("pnl", 0) >= 0]
            win_rate = len(wins) / len(trades) * 100
            net = sum(t.get("pnl", 0.0) for t in trades)
            avg_dur = sum(t.get("duration_seconds", 0) for t in trades) / len(trades)
            last_t = trades[-1]
            yon = "LONG" if last_t["side"] == "long" else "SHORT"
            parts.append(f"  Toplam işlem: {len(trades)} ({len(wins)} kâr, {len(trades) - len(wins)} zarar) | Kazanma oranı: %{win_rate:.1f}")
            parts.append(f"  Net Kâr/Zarar: {net:+.2f} USDT")
            parts.append(f"  Ortalama süre: {_fmt_duration(avg_dur)}")
            parts.append(
                f"  Son kapanan işlem: {datetime.fromtimestamp(last_t['closed_at']).strftime('%d.%m.%Y')}, "
                f"{yon}, {last_t.get('pnl', 0):+.2f} USDT, {last_t.get('reason', '')}"
            )
        else:
            parts.append("  (yok)")

        return "\n".join(parts)

    # ------------------------------------------------------------
    # /coinperformans - tum zamanlar, coin bazli performans
    # ------------------------------------------------------------
    def build_coinperformans_command(self) -> str:
        parts = ["📊 *COIN PERFORMANS RAPORU*", "Bot başlangıcından bu yana", f"({_now_str()} itibarıyla)", ""]

        per_coin_stats = []
        total_trades = 0
        total_win = 0
        total_pnl = 0.0

        for symbol in config.COINS:
            trades = self.state.trades_for_symbol(symbol)
            if not trades:
                continue
            wins = [t for t in trades if t.get("pnl", 0) >= 0]
            losses = [t for t in trades if t.get("pnl", 0) < 0]
            pnl_sum = sum(t.get("pnl", 0.0) for t in trades)
            avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0.0
            avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else 0.0
            best_t = max(trades, key=lambda t: t.get("pnl", 0))
            worst_t = min(trades, key=lambda t: t.get("pnl", 0))

            per_coin_stats.append({
                "coin": symbol.replace("USDT", ""), "count": len(trades),
                "wins": len(wins), "losses": len(losses),
                "win_rate": len(wins) / len(trades) * 100, "pnl": pnl_sum,
                "avg_win": avg_win, "avg_loss": avg_loss,
                "best": best_t.get("pnl", 0), "worst": worst_t.get("pnl", 0),
            })
            total_trades += len(trades)
            total_win += len(wins)
            total_pnl += pnl_sum

        per_coin_stats.sort(key=lambda s: s["count"], reverse=True)

        for s in per_coin_stats:
            parts.append(
                f"*{s['coin']}/USDT*\n"
                f"  Toplam işlem: {s['count']} | Kâr: {s['wins']} | Zarar: {s['losses']} | Kazanma oranı: %{s['win_rate']:.1f}\n"
                f"  Net Kâr/Zarar: {s['pnl']:+.2f} USDT\n"
                f"  Ortalama kâr: {s['avg_win']:+.2f} USDT | Ortalama zarar: {s['avg_loss']:+.2f} USDT\n"
                f"  En iyi işlem: {s['best']:+.2f} USDT | En kötü işlem: {s['worst']:+.2f} USDT"
            )
            parts.append("")

        if not per_coin_stats:
            parts.append("(henüz kapanan işlem yok)")
            parts.append("")

        parts.append("────────────────────")
        parts.append("*TOPLAM (tüm coinler)*")
        win_rate_total = (total_win / total_trades * 100) if total_trades else 0.0
        parts.append(f"Toplam işlem: {total_trades} | Kâr: {total_win} | Zarar: {total_trades - total_win} | Kazanma oranı: %{win_rate_total:.1f}")
        parts.append(f"Net Kâr/Zarar: {total_pnl:+.2f} USDT")
        if per_coin_stats:
            best_coin = max(per_coin_stats, key=lambda s: s["pnl"])
            worst_coin = min(per_coin_stats, key=lambda s: s["pnl"])
            most_traded = max(per_coin_stats, key=lambda s: s["count"])
            parts.append(f"En kârlı coin: {best_coin['coin']} ({best_coin['pnl']:+.2f} USDT)")
            parts.append(f"En zararlı coin: {worst_coin['coin']} ({worst_coin['pnl']:+.2f} USDT)")
            parts.append(f"En çok işlem yapılan coin: {most_traded['coin']} ({most_traded['count']} işlem)")

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
        if low == "/z":
            send_message(self.report_builder.build_z())
        elif low == "/x":
            send_message(self.report_builder.build_x())
        elif low == "/q":
            send_message(self.report_builder.build_q())
        elif low == "/pozisyonlar":
            send_message(self.report_builder.build_positions_command())
        elif low == "/coinrapor":
            send_message(self.report_builder.build_coinrapor_command())
        elif low == "/coinperformans":
            send_message(self.report_builder.build_coinperformans_command())
        elif low == "/dur":
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
        elif low.startswith("/rapor") and len(low) > len("/rapor") and not low.startswith("/raporlar"):
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
