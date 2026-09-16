"""
reports.py
----------
Iki tur rapor var:
  1) Otomatik/periyodik: 12 saatlik, 24 saatlik, haftalik ozet (main.py'daki
     dongu tarafindan zamani geldiginde tetiklenir).
  2) Komutla calisan (Telegram'dan /komut ile istenen): coin bazli P&L
     dokumu ve o anki acik pozisyonlar listesi.

Komutlar:
  /rapor        -> coin bazli kar/zarar dokumu (tum gecmis)
  /pozisyonlar  -> su an acik olan pozisyonlar
"""

import time
from collections import defaultdict


def build_period_summary(state, hours: float) -> str:
    since = time.time() - hours * 3600
    trades = state.get_trades_since(since)
    if not trades:
        return f"📊 Son {_period_label(hours)}: kapanan islem yok."

    total_pnl_usdt = sum(t.get("pnl_usdt", 0.0) for t in trades)
    wins = [t for t in trades if t["pnl_pct"] >= 0]
    losses = [t for t in trades if t["pnl_pct"] < 0]

    lines = [
        f"📊 <b>Son {_period_label(hours)} Ozet</b>",
        f"Kapanan islem: {len(trades)}  (Kazanan: {len(wins)}, Kaybeden: {len(losses)})",
        f"Toplam P&L: {total_pnl_usdt:.2f} USDT",
    ]
    return "\n".join(lines)


def build_per_coin_report(state) -> str:
    trades = state.all_trades()
    if not trades:
        return "📈 Henuz kapanan islem yok."

    by_symbol = defaultdict(lambda: {"count": 0, "pnl_usdt": 0.0})
    for t in trades:
        entry = by_symbol[t["symbol"]]
        entry["count"] += 1
        entry["pnl_usdt"] += t.get("pnl_usdt", 0.0)

    rows = sorted(by_symbol.items(), key=lambda kv: kv[1]["pnl_usdt"], reverse=True)
    lines = ["📈 <b>Coin Bazli Kar/Zarar</b>"]
    for symbol, data in rows:
        lines.append(f"{symbol}: {data['pnl_usdt']:.2f} USDT ({data['count']} islem)")
    return "\n".join(lines)


def build_open_positions_report(state, exchange=None) -> str:
    positions = state.all_positions()
    if not positions:
        return "📭 Su an acik pozisyon yok."

    lines = [f"📭 <b>Acik Pozisyonlar ({len(positions)}/16)</b>"]
    for symbol, p in positions.items():
        current_price = None
        if exchange is not None:
            try:
                current_price = exchange.get_last_price(symbol)
            except Exception:
                current_price = None

        pnl_str = ""
        if current_price is not None:
            if p["side"] == "short":
                pnl_pct = (p["entry_price"] - current_price) / p["entry_price"] * 100.0
            else:
                pnl_pct = (current_price - p["entry_price"]) / p["entry_price"] * 100.0
            pnl_str = f"  |  anlik: {pnl_pct:+.2f}%"

        opened_minutes = int((time.time() - p["opened_at"]) / 60)
        lines.append(f"{symbol} {p['side'].upper()}  giris: {p['entry_price']:.6g}"
                      f"{pnl_str}  ({opened_minutes} dk)")
    return "\n".join(lines)


def _period_label(hours: float) -> str:
    if hours == 12:
        return "12 Saat"
    if hours == 24:
        return "24 Saat"
    if hours == 24 * 7:
        return "1 Hafta"
    return f"{hours:.0f} Saat"


def handle_command(command: str, state, exchange=None) -> str | None:
    cmd = command.split()[0].lower()
    if cmd in ("/rapor", "/report"):
        return build_per_coin_report(state)
    if cmd in ("/pozisyonlar", "/positions", "/pozisyon"):
        return build_open_positions_report(state, exchange)
    return None
