"""
reports.py
----------
Uc tur rapor var:
  1) Otomatik/periyodik: 12 saatlik, 24 saatlik, haftalik ozet (main.py'daki
     dongu tarafindan zamani geldiginde tetiklenir).
  2) Komutla calisan (Telegram'dan /komut ile istenen):
     - /rapor        -> coin bazli toplam kar/zarar dokumu (tum gecmis, ozet)
     - /pozisyonlar   -> su an acik olan pozisyonlar
     - /coinrapor     -> TAKIP EDILEN HER COIN icin: islem sayisi, kazanan/
                          kaybeden sayisi, ortalama kar/zarar % ve toplam PnL (USDT)
     - /rapor<coin>   -> ORN. /raporbtc -> tek bir coin icin cok detayli dokum
                          (istatistikler + varsa acik pozisyon + son islemler listesi)
"""

import time
from collections import defaultdict


REASON_LABELS = {
    "loss_exit": "Loss Exit",
    "take_profit": "ALMA TP",
    "trend_flip": "Trend Degisimi",
    "color_flip_profit": "T3 Renk Donusu / Kar",
    "candle_close_loss": "Mum Kapanis Zarar",
    "reverse_signal": "Ters Sinyal / Yon Degisimi",
}


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


def build_open_positions_report(state, exchange=None, cfg=None) -> str:
    positions = state.all_positions()
    max_total = cfg["max_positions"] if cfg else "?"
    if not positions:
        return f"📭 Su an acik pozisyon yok. (0/{max_total})"

    lines = [f"📭 <b>Acik Pozisyonlar ({len(positions)}/{max_total})</b>"]
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


# ---------------------------------------------------------------------------
# /coinrapor -- takip edilen HER coin icin ozet istatistik
# ---------------------------------------------------------------------------
def _coin_stats(trades: list) -> dict:
    """Bir coine ait kapanan islem listesinden ozet istatistik cikarir."""
    count = len(trades)
    wins = [t for t in trades if t.get("pnl_pct", 0.0) >= 0]
    losses = [t for t in trades if t.get("pnl_pct", 0.0) < 0]
    win_rate = (len(wins) / count * 100.0) if count else 0.0
    avg_pnl_pct = (sum(t.get("pnl_pct", 0.0) for t in trades) / count) if count else 0.0
    total_pnl_usdt = sum(t.get("pnl_usdt", 0.0) for t in trades)
    return {
        "count": count, "wins": len(wins), "losses": len(losses),
        "win_rate": win_rate, "avg_pnl_pct": avg_pnl_pct, "total_pnl_usdt": total_pnl_usdt,
    }


def build_coin_summary_report(state, cfg: dict) -> str:
    """
    Config'de takip edilen HER coin icin (islem hic yapilmamis olsa bile) tek
    satirlik ozet: islem sayisi, kazanan/kaybeden, ortalama kar/zarar % (kapanan
    islemlerin pnl_pct'lerinin ortalamasi) ve toplam PnL (USDT).
    """
    all_trades = state.all_trades()
    by_symbol = defaultdict(list)
    for t in all_trades:
        by_symbol[t["symbol"]].append(t)

    rows = []
    for symbol in cfg["symbols"]:
        stats = _coin_stats(by_symbol.get(symbol, []))
        rows.append((symbol, stats))

    # en cok kazandiran ustte, hic islemi olmayanlar en altta
    rows.sort(key=lambda r: (r[1]["count"] == 0, -r[1]["total_pnl_usdt"]))

    lines = ["📊 <b>Coin Bazli Detayli Rapor</b>"]
    for symbol, s in rows:
        if s["count"] == 0:
            lines.append(f"{symbol}: henuz islem yok")
            continue
        lines.append(
            f"<b>{symbol}</b>: {s['count']} islem ({s['wins']} kazanan / {s['losses']} kaybeden, "
            f"%{s['win_rate']:.0f} basari) | Ort: {s['avg_pnl_pct']:+.2f}% | Toplam: {s['total_pnl_usdt']:+.2f} USDT"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /rapor<coin> -- TEK bir coin icin cok detayli dokum
# ---------------------------------------------------------------------------
def _format_duration(seconds: float) -> str:
    if seconds is None or seconds < 0:
        return "-"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.0f} dk"
    hours = minutes / 60.0
    if hours < 24:
        return f"{hours:.1f} saat"
    days = hours / 24.0
    return f"{days:.1f} gun"


def match_symbol(suffix: str, symbols: list) -> str | None:
    """
    '/raporbtc' -> 'btc' gibi bir suffix'i cfg['symbols'] listesindeki gercek
    sembole ('BTCUSDT') esler. Hem kisa isim ('btc') hem de tam sembol
    ('btcusdt') kabul edilir. Eslesme yoksa None doner.
    """
    if not suffix:
        return None
    candidate = suffix.upper()
    if candidate in symbols:
        return candidate
    candidate_with_usdt = candidate + "USDT"
    if candidate_with_usdt in symbols:
        return candidate_with_usdt
    return None


def build_coin_detail_report(state, exchange, cfg: dict, symbol: str, last_n: int = 10) -> str:
    """
    Tek bir coin icin cok detayli rapor:
      - toplam islem / kazanan / kaybeden / basari orani
      - ortalama kar/zarar % ve toplam PnL (USDT)
      - en iyi ve en kotu islem
      - ortalama islem suresi
      - varsa acik pozisyonun anlik durumu
      - son N kapanan islemin tek tek listesi
    """
    all_trades = [t for t in state.all_trades() if t["symbol"] == symbol]
    stats = _coin_stats(all_trades)

    lines = [f"🔎 <b>{symbol} Detayli Rapor</b>"]

    # -- acik pozisyon (varsa) --
    open_pos = state.get_position(symbol)
    if open_pos is not None:
        current_price = None
        if exchange is not None:
            try:
                current_price = exchange.get_last_price(symbol)
            except Exception:
                current_price = None

        pnl_str = "bilinmiyor"
        if current_price is not None:
            if open_pos["side"] == "short":
                pnl_pct = (open_pos["entry_price"] - current_price) / open_pos["entry_price"] * 100.0
            else:
                pnl_pct = (current_price - open_pos["entry_price"]) / open_pos["entry_price"] * 100.0
            pnl_str = f"{pnl_pct:+.2f}%"

        opened_ago = _format_duration(time.time() - open_pos["opened_at"])
        band = open_pos.get("tp_band_price")
        band_str = f"{band:.6g}" if band is not None else "henuz hesaplanmadi"
        lines.append(
            f"\n🟢 <b>Su an ACIK</b>: {open_pos['side'].upper()}  giris: {open_pos['entry_price']:.6g}  "
            f"anlik: {pnl_str}  ({opened_ago} once acildi)\nTP bandi: {band_str}"
        )
    else:
        lines.append("\nSu an bu coinde acik pozisyon yok.")

    # -- genel istatistikler --
    if stats["count"] == 0:
        lines.append("\nBu coin icin henuz kapanan islem yok.")
        return "\n".join(lines)

    lines.append(
        f"\n<b>Genel</b>\n"
        f"Toplam islem: {stats['count']}\n"
        f"Kazanan: {stats['wins']}  |  Kaybeden: {stats['losses']}  |  Basari orani: %{stats['win_rate']:.1f}\n"
        f"Ortalama kar/zarar: {stats['avg_pnl_pct']:+.2f}%\n"
        f"Toplam PnL: {stats['total_pnl_usdt']:+.2f} USDT"
    )

    # -- en iyi / en kotu islem --
    best = max(all_trades, key=lambda t: t.get("pnl_pct", 0.0))
    worst = min(all_trades, key=lambda t: t.get("pnl_pct", 0.0))
    lines.append(
        f"\n<b>En iyi islem</b>: {best['pnl_pct']:+.2f}% "
        f"(giris {best['entry_price']:.6g} -> cikis {best['exit_price']:.6g}, {REASON_LABELS.get(best['reason'], best['reason'])})\n"
        f"<b>En kotu islem</b>: {worst['pnl_pct']:+.2f}% "
        f"(giris {worst['entry_price']:.6g} -> cikis {worst['exit_price']:.6g}, {REASON_LABELS.get(worst['reason'], worst['reason'])})"
    )

    # -- ortalama islem suresi --
    durations = [t["closed_at"] - t["opened_at"] for t in all_trades
                 if t.get("closed_at") and t.get("opened_at")]
    if durations:
        avg_duration = sum(durations) / len(durations)
        lines.append(f"\nOrtalama islem suresi: {_format_duration(avg_duration)}")

    # -- son N islem listesi --
    recent = sorted(all_trades, key=lambda t: t.get("closed_at", 0), reverse=True)[:last_n]
    if recent:
        lines.append(f"\n<b>Son {len(recent)} Islem</b>")
        for t in recent:
            when = time.strftime("%d.%m %H:%M", time.localtime(t.get("closed_at", 0)))
            reason_label = REASON_LABELS.get(t["reason"], t["reason"])
            lines.append(
                f"{when}  {t['side'].upper()}  {t['entry_price']:.6g} -> {t['exit_price']:.6g}  "
                f"{t['pnl_pct']:+.2f}% ({t['pnl_usdt']:+.2f} USDT)  [{reason_label}]"
            )

    return "\n".join(lines)


def _period_label(hours: float) -> str:
    if hours == 12:
        return "12 Saat"
    if hours == 24:
        return "24 Saat"
    if hours == 24 * 7:
        return "1 Hafta"
    return f"{hours:.0f} Saat"


def handle_command(command: str, state, cfg: dict, exchange=None) -> str | None:
    cmd = command.split()[0].lower()

    if cmd in ("/rapor", "/report"):
        return build_per_coin_report(state)

    if cmd in ("/pozisyonlar", "/positions", "/pozisyon"):
        return build_open_positions_report(state, exchange, cfg)

    if cmd in ("/coinrapor", "/coinreport"):
        return build_coin_summary_report(state, cfg)

    if cmd.startswith("/rapor") and cmd != "/rapor":
        suffix = cmd[len("/rapor"):]
        symbol = match_symbol(suffix, cfg["symbols"])
        if symbol is None:
            available = ", ".join(s.replace("USDT", "") for s in cfg["symbols"])
            return f"⚠️ '{suffix.upper()}' icin takip edilen bir coin bulunamadi.\nTakip edilenler: {available}"
        return build_coin_detail_report(state, exchange, cfg, symbol)

    return None
