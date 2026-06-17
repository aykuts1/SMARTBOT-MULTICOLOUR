import math
import time
import json
import os
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timedelta
from logger_setup import get_logger

log = get_logger("utils")


def load_config(path="config.json"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_config_mtime(path="config.json"):
    return os.path.getmtime(path)


def format_usdt(value):
    if abs(value) >= 1:
        return f"{value:,.2f}"
    else:
        return f"{value:.6f}"


def format_pnl(pnl_usdt, pnl_pct):
    sign_usdt = "+" if pnl_usdt >= 0 else "-"
    sign_pct = "+" if pnl_pct >= 0 else "-"
    icon = "✅" if pnl_usdt >= 0 else "❌"
    return f"{sign_usdt}{format_usdt(abs(pnl_usdt))} USDT  |  {sign_pct}%{abs(pnl_pct):.2f}  {icon}"


def format_duration(seconds):
    if seconds < 0:
        seconds = 0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}s {minutes:02d}dk"


def now_str():
    return datetime.now().strftime("%H:%M | %d.%m.%Y")


def now_ts():
    return int(time.time() * 1000)


def tick_round(value, tick_size, direction="nearest"):
    if tick_size <= 0:
        return value
    if direction == "down":
        return math.floor(value / tick_size) * tick_size
    elif direction == "up":
        return math.ceil(value / tick_size) * tick_size
    else:
        return round(value / tick_size) * tick_size


def qty_round_down(qty, step_size):
    if step_size <= 0:
        return qty
    d_qty = Decimal(str(qty))
    d_step = Decimal(str(step_size))
    steps = (d_qty / d_step).to_integral_value(rounding=ROUND_DOWN)
    return float(steps * d_step)


def sl_round(entry_price, sl_price, tick_size, side):
    if side == "short":
        return tick_round(sl_price, tick_size, "up")
    else:
        return tick_round(sl_price, tick_size, "down")


def calc_sl_price(entry_price, sl_pct, side):
    if side == "short":
        return entry_price * (1 + sl_pct)
    else:
        return entry_price * (1 - sl_pct)


def calc_position_size(balance, margin_pct, leverage, price):
    margin = balance * margin_pct
    notional = margin * leverage
    qty = notional / price
    return qty, margin, notional


def calc_pnl(entry_price, exit_price, qty, side):
    if side == "short":
        pnl = (entry_price - exit_price) * qty
    else:
        pnl = (exit_price - entry_price) * qty
    pnl_pct = (pnl / (entry_price * qty)) * 100 if entry_price * qty > 0 else 0
    return pnl, pnl_pct


def generate_order_link_id(ecosystem, side, symbol):
    ts = int(time.time())
    return f"{ecosystem}_{side}_{symbol}_{ts}"


def parse_order_link_id(order_link_id):
    try:
        parts = order_link_id.split("_")
        if len(parts) >= 4:
            return {
                "ecosystem": parts[0],
                "side": parts[1],
                "symbol": parts[2],
                "timestamp": parts[3]
            }
    except Exception:
        pass
    return None


def is_our_order(order_link_id):
    valid_prefixes = [
        "KIRMIZI", "KIRMIZI1", "KIRMIZI2",
        "MAVI", "MAVI1", "MAVI2",
        "BEYAZ", "MOR",
        "SARI", "TURUNCU",
        "SIYAH", "GRI",
        "GOLD", "SILVER"
    ]
    if not order_link_id:
        return False
    prefix = order_link_id.split("_")[0] if "_" in order_link_id else ""
    return prefix in valid_prefixes


def ecosystem_emoji(name):
    emojis = {
        "kirmizi": "🔴", "kirmizi1": "🔴", "kirmizi2": "🔴",
        "mavi": "🔵", "mavi1": "🔵", "mavi2": "🔵",
        "beyaz": "⬜", "mor": "🟣",
        "sari": "🟡", "turuncu": "🟠",
        "siyah": "⬛", "gri": "🔘",
        "gold": "🥇", "silver": "🥈"
    }
    return emojis.get(name.lower(), "⚪")


def ecosystem_display_name(name):
    names = {
        "kirmizi": "Kırmızı", "kirmizi1": "Kırmızı 1", "kirmizi2": "Kırmızı 2",
        "mavi": "Mavi", "mavi1": "Mavi 1", "mavi2": "Mavi 2",
        "beyaz": "Beyaz", "mor": "Mor",
        "sari": "Sarı", "turuncu": "Turuncu",
        "siyah": "Siyah", "gri": "Gri",
        "gold": "Gold", "silver": "Silver"
    }
    return names.get(name.lower(), name)


def side_emoji(side):
    return "📈" if side == "long" else "📉"


def side_display(side):
    return "LONG" if side == "long" else "SHORT"
