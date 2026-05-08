"""
Telegram bildirim islemleri
"""

import requests
from datetime import datetime
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def send_message(message):
    """Telegram'a mesaj gonderir."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Token veya Chat ID tanimli degil!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"[Telegram] Mesaj gonderme hatasi: {e}")
        return False


def notify_bot_started(balance, stake):
    """Bot baslatildi bildirimi."""
    msg = (
        f"🤖 <b>SCALP BOT BAŞLATILDI</b>\n\n"
        f"💰 Bakiye: <b>{balance:.2f} USDT</b>\n"
        f"📊 Stake: <b>{stake:.2f} USDT</b>\n"
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return send_message(msg)


def notify_position_opened(symbol, side, entry_price, sl_price, qty):
    """Pozisyon acildi bildirimi."""
    side_emoji = "🟢" if side == "LONG" else "🔴"
    msg = (
        f"{side_emoji} <b>POZİSYON AÇILDI</b>\n\n"
        f"📍 Coin: <b>{symbol}</b>\n"
        f"📈 Yön: <b>{side}</b>\n"
        f"💵 Giriş: <b>{entry_price}</b>\n"
        f"🛑 SL: <b>{sl_price}</b>\n"
        f"📊 Miktar: <b>{qty}</b>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send_message(msg)


def notify_breakeven_and_ce_tightened(symbol, entry_price):
    """Breakeven aktif + CE sikilasti bildirimi."""
    msg = (
        f"🎯 <b>BREAKEVEN + CE SIKILAŞTI</b>\n\n"
        f"📍 Coin: <b>{symbol}</b>\n"
        f"💵 SL → Giriş fiyatına çekildi: <b>{entry_price}</b>\n"
        f"🔒 CE → 0.5 ATR'ye sıkılaştı\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send_message(msg)


def notify_position_closed(symbol, side, entry_price, exit_price, pnl_usdt, pnl_percent, reason):
    """Pozisyon kapandi bildirimi."""
    emoji = "✅" if pnl_usdt >= 0 else "❌"
    msg = (
        f"{emoji} <b>POZİSYON KAPATILDI</b>\n\n"
        f"📍 Coin: <b>{symbol}</b>\n"
        f"📈 Yön: <b>{side}</b>\n"
        f"💵 Giriş: <b>{entry_price}</b>\n"
        f"💵 Çıkış: <b>{exit_price}</b>\n"
        f"💰 P/L: <b>{pnl_usdt:+.2f} USDT ({pnl_percent:+.2f}%)</b>\n"
        f"📌 Sebep: <b>{reason}</b>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send_message(msg)


def notify_scan_summary(scanned_count, signals_found, errors):
    """Tarama ozeti (sinyal yoksa)."""
    msg = (
        f"🔍 <b>TARAMA TAMAMLANDI</b>\n\n"
        f"📊 Taranan coin: <b>{scanned_count}</b>\n"
        f"🎯 Bulunan sinyal: <b>{signals_found}</b>\n"
        f"⚠️ Hata: <b>{errors}</b>\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send_message(msg)


def notify_error(error_message):
    """Hata bildirimi."""
    msg = (
        f"⚠️ <b>HATA</b>\n\n"
        f"{error_message}\n"
        f"⏰ {datetime.now().strftime('%H:%M:%S')}"
    )
    return send_message(msg)
