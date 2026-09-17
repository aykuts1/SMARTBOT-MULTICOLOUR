"""
telegram_notify.py
-------------------
Telegram Bot API ile dogrudan HTTP istegi (requests) -- ekstra kutuphane
bagimliligi olmasin diye python-telegram-bot yerine sade sendMessage/
getUpdates cagrilari kullanilir.

Gerekli ortam degiskenleri:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
"""

import os
import logging

import requests

logger = logging.getLogger("telegram")

BASE_URL = "https://api.telegram.org/bot{token}"


class Telegram:
    def __init__(self):
        self.token = os.environ["TELEGRAM_BOT_TOKEN"]
        self.chat_id = os.environ["TELEGRAM_CHAT_ID"]
        self.base = BASE_URL.format(token=self.token)
        self._last_update_id = 0

    def send_message(self, text: str) -> None:
        try:
            requests.post(f"{self.base}/sendMessage",
                           data={"chat_id": self.chat_id, "text": text,
                                 "parse_mode": "HTML"}, timeout=10)
        except Exception as e:
            logger.warning("Telegram mesaji gonderilemedi: %s", e)

    def get_new_commands(self) -> list[str]:
        """Son kontrolden beri gelen /komutlari dondurur (basit long-polling)."""
        try:
            resp = requests.get(f"{self.base}/getUpdates",
                                 params={"offset": self._last_update_id + 1, "timeout": 0},
                                 timeout=10).json()
        except Exception as e:
            logger.warning("Telegram getUpdates basarisiz: %s", e)
            return []

        commands = []
        for update in resp.get("result", []):
            self._last_update_id = max(self._last_update_id, update["update_id"])
            msg = update.get("message", {})
            if str(msg.get("chat", {}).get("id")) != str(self.chat_id):
                continue
            text = msg.get("text", "")
            if text.startswith("/"):
                commands.append(text.strip())
        return commands

    # -- hazir bildirim sablonlari ------------------------------------------
    def notify(self, event: str, **kw) -> None:
        text = _format(event, **kw)
        if text:
            self.send_message(text)


def _format(event: str, **kw) -> str:
    if event == "bot_started":
        balance = kw.get("balance")
        balance_str = f"{balance:.2f} USDT" if balance is not None else "okunamadi (API baglantisini kontrol et)"
        return (f"🤖 <b>Bot Baslatildi</b>\n"
                f"Takip edilen coin: {kw['symbol_count']}\n"
                f"Bakiye: {balance_str}\n"
                f"Kaldirac: {kw['leverage']}x\n"
                f"Pozisyon buyuklugu: bakiyenin %{kw['position_size_pct']:.1f}'i\n"
                f"Max pozisyon: {kw['max_positions']}\n"
                f"Loss Exit: %{kw['loss_exit_pct']:.1f}\n"
                f"Kar esigi (renk-flip/TP): %{kw['profit_threshold_pct']:.2f}")

    if event == "position_opened":
        margin = kw["margin_usdt"]
        notional = kw["notional_usdt"]
        leverage_display = f"{notional / margin:.0f}x" if margin else "-"
        return (f"🟢 <b>Pozisyon Acildi</b>\n"
                f"Coin: {kw['symbol']}\n"
                f"Yon: {kw['side'].upper()}\n"
                f"Giris: {kw['entry_price']:.6g}\n"
                f"Miktar: {kw['qty']:.6g}\n"
                f"Marj: {margin:.2f} USDT\n"
                f"Hacim: {notional:.2f} USDT ({leverage_display})")

    if event == "position_closed":
        sign = "🟩" if kw["pnl_pct"] >= 0 else "🟥"
        reason_map = {"loss_exit": "Loss Exit", "take_profit": "ALMA TP",
                      "trend_flip": "Trend Degisimi", "color_flip_profit": "Renk Donusu / Kar",
                      "candle_close_loss": "Mum Kapanis Zarar",
                      "reverse_signal": "Ters Sinyal / Yon Degisimi"}
        return (f"{sign} <b>Pozisyon Kapandi</b>\n"
                f"Coin: {kw['symbol']}\n"
                f"Yon: {kw['side'].upper()}\n"
                f"Neden: {reason_map.get(kw['reason'], kw['reason'])}\n"
                f"Giris: {kw['entry_price']:.6g}  Cikis: {kw['exit_price']:.6g}\n"
                f"P&L: {kw['pnl_pct']:.2f}%")

    if event == "slot_full":
        return f"⚠️ Slot dolu ({kw['count']}/{kw['max_total']}) -- {kw['symbol']} icin sinyal atlandi."

    if event == "insufficient_balance":
        return (f"⚠️ Yetersiz bakiye: {kw['symbol']} icin islem acilamadi.\n"
                f"Bakiye: {kw['balance']:.2f} USDT, gereken marj: {kw['required']:.2f} USDT")

    return ""
