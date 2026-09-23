# -*- coding: utf-8 -*-
"""
telegram_bot.py
-----------------
Telegram komutlarini dinler (/Z /X /Q /pozisyonlar /coinrapor /rapor..
/coinperformans /dur /yardim) ve periyodik raporlari (12sa->Z, 24sa->X,
haftalik->Q) zamaninda gonderir.

KOKLU GUNCELLEME (Gold/Silver): Bir coin'de artik ayni anda hem 1 long
hem 1 short acik olabilir (Gold ve Silver farkli yonlerde actigi icin).
Tum raporlar buna gore guncellendi:
- /pozisyonlar, /coinrapor, /rapor{coin}: coin basina 0, 1 ya da 2 acik
  pozisyon blogu gosterebilir, her biri tur (Gold/Silver) etiketiyle.
- /coinperformans: her coin icin Gold ve Silver satirlari AYRI AYRI
  gosterilir, altinda coin toplami; en altta Gold/Silver/genel toplam.
- Z/X/Q: acik pozisyon listelerinde tur etiketi var; "kapanis sebebi
  dagilimi" artik Gold/Silver kirilimiyla gosteriliyor.
"""

import threading
import time
from datetime import datetime, timedelta

import requests

import config
import strategy
from telegram_notifier import send_message, _now_str, _tur_etiket


HELP_TEXT = (
    "📋 *KOMUTLAR*\n"
    "/Z — Yüzeysel durum raporu\n"
    "/X — Detaylı durum raporu\n"
    "/Q — Çok detaylı haftalık rapor\n"
    "/pozisyonlar — Açık pozisyonları listele\n"
    "/coinrapor — Tüm coinlerin özet raporu\n"
    "/rapor{coinadi} — Belirli coinin detaylı raporu (örn: /raporARB)\n"
    "/coinperformans — Her coin'in tüm zamanlar performans özeti (Gold/Silver ayrı)\n"
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


def _slot_summary(state) -> str:
    """'N (Long: x/12, Short: y/12)' formatinda ozet - long/short icin
    ayri limit oldugu icin (bkz. config.MAX_POSITIONS_PER_SIDE)."""
    long_count = state.open_count_for_side("long")
    short_count = state.open_count_for_side("short")
    return (f"{state.total_open_count()} (Long: {long_count}/{config.MAX_POSITIONS_PER_SIDE}, "
            f"Short: {short_count}/{config.MAX_POSITIONS_PER_SIDE})")


def _agg_stats(trades: list):
    """Bir islem listesi icin toplu istatistik. Bos listede None doner."""
    if not trades:
        return None
    wins = [t for t in trades if t.get("pnl", 0) >= 0]
    losses = [t for t in trades if t.get("pnl", 0) < 0]
    pnl_sum = sum(t.get("pnl", 0.0) for t in trades)
    avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0.0
    avg_loss = sum(t.get("pnl", 0) for t in losses) / len(losses) if losses else 0.0
    best = max(trades, key=lambda t: t.get("pnl", 0)).get("pnl", 0)
    worst = min(trades, key=lambda t: t.get("pnl", 0)).get("pnl", 0)
    return {
        "count": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(trades) * 100, "pnl": pnl_sum,
        "avg_win": avg_win, "avg_loss": avg_loss, "best": best, "worst": worst,
    }


def _reason_breakdown_lines(closed: list) -> list:
    """Her kapanis sebebi icin toplam + Gold/Silver kirilimi."""
    lines = []
    for reason in ("Take Profit", "Trend Dönüşü", "Lose Exit", "Stop Loss"):
        subset = [t for t in closed if t.get("reason") == reason]
        gold = sum(1 for t in subset if t.get("trade_type") == "gold")
        silver = sum(1 for t in subset if t.get("trade_type") == "silver")
        lines.append(f"{reason}: {len(subset)} ({gold} Gold, {silver} Silver)")
    return lines


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
        parts.append(f"Açık işlem sayısı: {_slot_summary(self.state)}")
        parts.append(f"Son 12 saatte kapanan işlem: {len(closed)} ({wins} kâr, {losses} zarar)")
        parts.append(f"Net Kâr/Zarar: {net:+.2f} USDT")

        if self.state.trade_history:
            last_t = self.state.trade_history[-1]
            coin = last_t["symbol"].replace("USDT", "")
            yon = "LONG" if last_t["side"] == "long" else "SHORT"
            tur = _tur_etiket(last_t.get("trade_type", "gold"))
            parts.append(
                f"En son işlem: {coin}/USDT {yon} ({tur}) kapandı, {last_t.get('pnl', 0):+.2f} USDT "
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
        parts.append(f"*Açık pozisyonlar — {_slot_summary(self.state)}*")
        open_lines = []
        for pos in self.state.all_positions():
            try:
                last_price = self.client.get_last_price(pos.symbol)
            except Exception:
                last_price = pos.entry_price
            pct = _price_change_percent(pos.side, pos.entry_price, last_price)
            coin = pos.symbol.replace("USDT", "")
            yon = "LONG" if pos.side == "long" else "SHORT"
            tur = _tur_etiket(pos.trade_type)
            dur = _fmt_duration(time.time() - pos.open_time)
            open_lines.append(
                f"- {coin}/USDT {yon} ({tur}) | Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} "
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
                f"En iyi işlem: {best['symbol'].replace('USDT', '')}/USDT ({_tur_etiket(best.get('trade_type','gold'))}) "
                f"{best.get('pnl', 0):+.2f} USDT (%{best.get('price_change_percent', 0):+.2f} fiyat değişimi)"
            )
            parts.append(
                f"En kötü işlem: {worst['symbol'].replace('USDT', '')}/USDT ({_tur_etiket(worst.get('trade_type','gold'))}) "
                f"{worst.get('pnl', 0):+.2f} USDT (%{worst.get('price_change_percent', 0):+.2f} fiyat değişimi)"
            )
            avg_dur = sum(t.get("duration_seconds", 0) for t in closed) / len(closed)
            parts.append(f"Ortalama işlem süresi: {_fmt_duration(avg_dur)}")

            parts.append("Kapanış sebebi dağılımı:")
            parts.extend(f"  {line}" for line in _reason_breakdown_lines(closed))

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
        gold_closed = [t for t in closed if t.get("trade_type") == "gold"]
        silver_closed = [t for t in closed if t.get("trade_type") == "silver"]
        parts.append(f"  Gold: {len(gold_closed)} işlem | Silver: {len(silver_closed)} işlem")
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
        parts.extend(f"- {line}" for line in _reason_breakdown_lines(closed))
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
        header = f"📂 *AÇIK POZİSYONLAR* — {_slot_summary(self.state)}"
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
            tur = _tur_etiket(pos.trade_type)
            coin = pos.symbol.replace("USDT", "")
            blocks.append(
                f"{emoji} {coin}/USDT — {yon} ({tur})\n"
                f"Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} | "
                f"K/Z: {pnl:+.2f} USDT (%{pct:+.2f} fiyat değişimi)\n"
                f"Lose exit: {pos.lose_exit_price:.4f} | SL: {pos.sl_price:.4f} | Kaldıraç: {pos.leverage:.0f}x"
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

            open_positions = [self.state.get_position(symbol, s) for s in ("long", "short")]
            open_positions = [p for p in open_positions if p is not None]

            if open_positions:
                block_lines = [f"*{coin}/USDT* — Supertrend yönü: {trend_yonu}"]
                for pos in open_positions:
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
                    tur = _tur_etiket(pos.trade_type)
                    block_lines.append(
                        f"  {yon} ({tur}) açık | Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} (%{pct:+.2f}) | "
                        f"Kaldıraç: {pos.leverage:.0f}x | Süre: {dur}"
                    )
                parts.append("\n".join(block_lines))
            else:
                trades = self.state.trades_for_symbol(symbol)
                if trades:
                    last_t = trades[-1]
                    son_islem = (f"{_time_ago_str(last_t['closed_at'])} "
                                 f"({_tur_etiket(last_t.get('trade_type','gold'))}, {last_t.get('pnl', 0):+.2f} USDT)")
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
            parts.append(f"  Gold çizgisi: {last_row['gold_line']:.4f} | Silver çizgisi: {last_row['silver_line']:.4f}")
        except Exception as e:
            parts.append(f"(Anlık gösterge verisi alınamadı: {e})")
        parts.append("")

        open_positions = [self.state.get_position(symbol, s) for s in ("long", "short")]
        open_positions = [p for p in open_positions if p is not None]

        if open_positions:
            for pos in open_positions:
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
                tur = _tur_etiket(pos.trade_type)
                hedef_adi = "Silver çizgisi" if pos.trade_type == "gold" else "Gold çizgisi"
                dur = _fmt_duration(time.time() - pos.open_time)
                parts.append(f"*Açık pozisyon — {yon} ({tur})*")
                parts.append(f"  Giriş: {pos.entry_price:.4f} | Anlık: {last_price:.4f} (%{pct:+.2f})")
                if pos.target_line_at_entry:
                    hedef_mesafe = (pos.target_line_at_entry - pos.entry_price) / pos.entry_price * 100
                    parts.append(f"  TP hedefi ({hedef_adi}, açılış anı): {pos.target_line_at_entry:.4f} (mesafe: %{hedef_mesafe:+.2f})")
                lose_mesafe = (pos.lose_exit_price - pos.entry_price) / pos.entry_price * 100
                parts.append(f"  Lose exit: {pos.lose_exit_price:.4f} (mesafe: %{lose_mesafe:+.2f})")
                sl_mesafe = (pos.sl_price - pos.entry_price) / pos.entry_price * 100
                parts.append(f"  Güvenlik SL: {pos.sl_price:.4f} (mesafe: %{sl_mesafe:+.2f})")
                parts.append(
                    f"  Kaldıraç: {pos.leverage:.0f}x | Stake: {pos.allocated_amount:.2f} USDT | "
                    f"İşlem hacmi: {pos.qty * pos.entry_price:.2f} USDT"
                )
                parts.append(f"  Anlık Kâr/Zarar: {pnl:+.2f} USDT")
                parts.append(f"  Açılış: {datetime.fromtimestamp(pos.open_time).strftime('%d.%m.%Y %H:%M')} | Süre: {dur}")
                parts.append("")
        else:
            parts.append("Açık pozisyon: Yok")
            parts.append("")

        window = 7 * 24 * 3600
        cutoff = time.time() - window
        trades = [t for t in self.state.trades_for_symbol(symbol) if t.get("closed_at", 0) >= cutoff]
        parts.append("*Bu coin'in geçmişi (son 7 gün, Gold+Silver birlikte)*")
        if trades:
            wins = [t for t in trades if t.get("pnl", 0) >= 0]
            win_rate = len(wins) / len(trades) * 100
            net = sum(t.get("pnl", 0.0) for t in trades)
            avg_dur = sum(t.get("duration_seconds", 0) for t in trades) / len(trades)
            last_t = trades[-1]
            yon = "LONG" if last_t["side"] == "long" else "SHORT"
            tur = _tur_etiket(last_t.get("trade_type", "gold"))
            parts.append(f"  Toplam işlem: {len(trades)} ({len(wins)} kâr, {len(trades) - len(wins)} zarar) | Kazanma oranı: %{win_rate:.1f}")
            parts.append(f"  Net Kâr/Zarar: {net:+.2f} USDT")
            parts.append(f"  Ortalama süre: {_fmt_duration(avg_dur)}")
            parts.append(
                f"  Son kapanan işlem: {datetime.fromtimestamp(last_t['closed_at']).strftime('%d.%m.%Y')}, "
                f"{yon} ({tur}), {last_t.get('pnl', 0):+.2f} USDT, {last_t.get('reason', '')}"
            )
        else:
            parts.append("  (yok)")

        return "\n".join(parts)

    # ------------------------------------------------------------
    # /coinperformans - tum zamanlar, coin + tur bazli performans
    # ------------------------------------------------------------
    def build_coinperformans_command(self) -> str:
        parts = ["📊 *COIN PERFORMANS RAPORU*", "Bot başlangıcından bu yana", f"({_now_str()} itibarıyla)", ""]

        coin_blocks = []  # (symbol, total_count, total_pnl, block_text)
        grand_gold, grand_silver = [], []

        for symbol in config.COINS:
            trades = self.state.trades_for_symbol(symbol)
            if not trades:
                continue

            gold_trades = [t for t in trades if t.get("trade_type") == "gold"]
            silver_trades = [t for t in trades if t.get("trade_type") == "silver"]
            grand_gold.extend(gold_trades)
            grand_silver.extend(silver_trades)

            coin = symbol.replace("USDT", "")
            lines = [f"*{coin}/USDT*"]
            for label, sub_trades in (("Gold", gold_trades), ("Silver", silver_trades)):
                s = _agg_stats(sub_trades)
                if s is None:
                    lines.append(f"  {label} — işlem yok")
                    continue
                lines.append(
                    f"  {label} — Toplam: {s['count']} | Kâr: {s['wins']} | Zarar: {s['losses']} | "
                    f"Kazanma: %{s['win_rate']:.1f}\n"
                    f"    Net K/Z: {s['pnl']:+.2f} USDT | Ort. kâr: {s['avg_win']:+.2f} | "
                    f"Ort. zarar: {s['avg_loss']:+.2f} | En iyi: {s['best']:+.2f} | En kötü: {s['worst']:+.2f}"
                )
            coin_total = _agg_stats(trades)
            lines.append(f"  Coin toplamı: {coin_total['count']} işlem, Net K/Z: {coin_total['pnl']:+.2f} USDT")

            coin_blocks.append((symbol, coin_total["count"], coin_total["pnl"], "\n".join(lines)))

        coin_blocks.sort(key=lambda b: b[1], reverse=True)
        for _, _, _, block in coin_blocks:
            parts.append(block)
            parts.append("")

        if not coin_blocks:
            parts.append("(henüz kapanan işlem yok)")
            parts.append("")

        parts.append("────────────────────")
        parts.append("*TOPLAM (tüm coinler)*")

        all_trades = grand_gold + grand_silver
        total_stats = _agg_stats(all_trades)
        gold_stats = _agg_stats(grand_gold)
        silver_stats = _agg_stats(grand_silver)

        if total_stats:
            parts.append(
                f"Toplam işlem: {total_stats['count']} | Kâr: {total_stats['wins']} | "
                f"Zarar: {total_stats['losses']} | Kazanma oranı: %{total_stats['win_rate']:.1f}"
            )
            parts.append(f"Net Kâr/Zarar: {total_stats['pnl']:+.2f} USDT")
        if gold_stats:
            parts.append(f"Gold toplamı: {gold_stats['count']} işlem, Net K/Z: {gold_stats['pnl']:+.2f} USDT (%{gold_stats['win_rate']:.1f} kazanma)")
        if silver_stats:
            parts.append(f"Silver toplamı: {silver_stats['count']} işlem, Net K/Z: {silver_stats['pnl']:+.2f} USDT (%{silver_stats['win_rate']:.1f} kazanma)")

        if coin_blocks:
            best_coin = max(coin_blocks, key=lambda b: b[2])
            worst_coin = min(coin_blocks, key=lambda b: b[2])
            most_traded = max(coin_blocks, key=lambda b: b[1])
            parts.append(f"En kârlı coin: {best_coin[0].replace('USDT','')} ({best_coin[2]:+.2f} USDT)")
            parts.append(f"En zararlı coin: {worst_coin[0].replace('USDT','')} ({worst_coin[2]:+.2f} USDT)")
            parts.append(f"En çok işlem yapılan coin: {most_traded[0].replace('USDT','')} ({most_traded[1]} işlem)")

        return "\n".join(parts)


class TelegramCommandListener:
    """Telegram'dan gelen komutlari (uzun-polling ile getUpdates) dinler.

    ONEMLI GUVENLIK DUZELTMESI: Bot her baslatildiginda, Telegram
    sunucusunda BEKLEYEN (bot kapaliyken ya da onceki bir calistirmada
    islenmemis) eski komutlar otomatik olarak ATLANIR - calistirilmaz.
    Bunun sebebi: _last_update_id her process yeniden basladiginda 0'dan
    baslar (diske kaydedilmiyor), bu yuzden bu koruma olmazsa, GECMISTE
    herhangi bir noktada gonderilmis bir komut (ornegin eski bir "/dur")
    botun HER yeniden baslamasinda yeniden calisir. Canli ortamda tam
    olarak bu yasandi: bot her baslatildiginda, gecmiste bir yerde
    gonderilmis eski bir "/dur" komutunu bulup hemen kendini durduruyordu.
    Bu yuzden poll_loop, dinlemeye baslamadan once mevcut butun bekleyen
    guncellemeleri (calistirmadan) "gorulmus" olarak isaretler - bot
    sadece BUNDAN SONRA gelen komutlara tepki verir.
    """

    def __init__(self, report_builder: ReportBuilder, stop_flag_holder: dict):
        self.report_builder = report_builder
        self.stop_flag_holder = stop_flag_holder  # {"stop": False} -> main.py bunu okur
        self._last_update_id = 0
        self._running = True

    def _discard_pending_updates(self):
        """Baslangicta bekleyen (gecmis) guncellemeleri calistirmadan
        atlar - bkz. sinif docstring'i."""
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
        try:
            resp = requests.get(url, params={"offset": -1, "limit": 1}, timeout=10)
            results = resp.json().get("result", [])
            if results:
                self._last_update_id = results[-1]["update_id"]
                print(f"[telegram-cmd] Baslangicta bekleyen eski komutlar atlandi "
                      f"(son gorulen update_id: {self._last_update_id})")
        except Exception as e:
            print(f"[telegram-cmd] Baslangic senkronizasyonu basarisiz: {e}")

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
        self._discard_pending_updates()
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
        wait_s = self._seconds_until_next_midnight()
        print(f"[reports] Ilk periyodik rapora kadar bekleniyor: {wait_s/3600:.1f} saat")
        self._sleep_until(wait_s)
        if self.stop_flag_holder.get("stop"):
            return

        last_sent = {"Z": time.time(), "X": time.time(), "Q": time.time()}
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
            self._sleep_until(60)

    def _sleep_until(self, seconds):
        end = time.time() + seconds
        while time.time() < end and not self.stop_flag_holder.get("stop"):
            time.sleep(min(5, end - time.time()))

    def start(self):
        t = threading.Thread(target=self.run_loop, daemon=True)
        t.start()
        return t
