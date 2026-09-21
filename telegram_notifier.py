# -*- coding: utf-8 -*-
"""
telegram_notifier.py
---------------------
Telegram'a mesaj gonderen fonksiyonlar ve konusma sirasinda onaylanan
tum bildirim sablonlari.
"""

import time
from datetime import datetime

import requests

import config


def _now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def send_message(text: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[telegram] Token/Chat ID ayarli degil, mesaj gonderilmedi:\n", text)
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": config.TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception as e:
        print(f"[telegram] Mesaj gonderilemedi: {e}")


# ============================================================
# 1) BOT BASLATILDI
# ============================================================
def notify_bot_started(equity: float):
    text = (
        "🟢 *BOT BAŞLATILDI*\n"
        f"Tarih: {_now_str()}\n"
        f"Takip edilen coinler: {', '.join(c.replace('USDT','') for c in config.COINS)}\n"
        "Mod: Hedge / Cross Margin\n"
        f"Toplam varlık: {equity:.2f} USDT\n"
        "Durum: Aktif, veri akışı başladı"
    )
    send_message(text)


# ============================================================
# 2) ISLEM GIRISI
# ============================================================
def notify_position_opened(symbol: str, side: str, entry_price: float, merkez_value: float,
                            merkez_band_value: float, lose_exit_price: float, lose_exit_percent: float,
                            sl_price: float, leverage: float, allocated_amount: float,
                            volume: float):
    yon = "LONG" if side == "long" else "SHORT"
    emoji = "🔵" if side == "long" else "🔴"
    merkez_band_label = "Merkez üst bant" if side == "long" else "Merkez alt bant"
    text = (
        f"{emoji} *İŞLEM AÇILDI — {yon}*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Giriş fiyatı: {entry_price:.4f} USDT\n"
        f"Merkez çizgi: {merkez_value:.4f} | {merkez_band_label}: {merkez_band_value:.4f}\n"
        f"Lose exit: {lose_exit_price:.4f} USDT (%{lose_exit_percent:.2f})\n"
        f"SL: {sl_price:.4f} USDT\n"
        f"Kaldıraç: {leverage:.0f}x\n"
        f"Ayrılan miktar: {allocated_amount:.2f} USDT\n"
        f"İşlem hacmi: {volume:.2f} USDT\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 3) ISLEM CIKISI  (sebep: "Take Profit" / "Lose Exit" / "Stop Loss")
# ============================================================
def notify_position_closed(symbol: str, side: str, entry_price: float, exit_price: float,
                            reason: str, pnl: float, pnl_percent: float, duration_seconds: float):
    yon = "LONG" if side == "long" else "SHORT"
    emoji = "🟢" if pnl >= 0 else "🔴"
    hours = int(duration_seconds // 3600)
    minutes = int((duration_seconds % 3600) // 60)
    text = (
        f"{emoji} *İŞLEM KAPANDI — {yon}*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Giriş fiyatı: {entry_price:.4f} USDT\n"
        f"Çıkış fiyatı: {exit_price:.4f} USDT\n"
        f"Sebep: {reason}\n"
        f"Kâr/Zarar: {pnl:+.2f} USDT (%{pnl_percent:+.2f})\n"
        f"Süre: {hours} saat {minutes} dk\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 4) SLOT DOLU (sadece toplam sistem slotu 10/10 dolunca)
# ============================================================
def notify_slot_full(open_count: int, max_count: int, rejected_symbol: str, rejected_side: str):
    yon = "Long" if rejected_side == "long" else "Short"
    text = (
        "⚠️ *SLOT DOLU*\n"
        f"Açık işlem sayısı: {open_count}/{max_count}\n"
        f"Yeni sinyal: {rejected_symbol.replace('USDT','')}/USDT — {yon} (reddedildi)\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 5) BAKIYE YETERSIZ (sinyal atlanir)
# ============================================================
def notify_insufficient_balance(symbol: str, side: str, required_margin: float, available: float):
    yon = "Long" if side == "long" else "Short"
    text = (
        "⚠️ *BAKİYE YETERSİZ*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Yön: {yon}\n"
        f"Gereken marj: {required_margin:.2f} USDT\n"
        f"Mevcut bakiye: {available:.2f} USDT\n"
        "Durum: Sinyal atlandı, işlem açılmadı\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 6) KALDIRAC LIMITI ASILDI
# ============================================================
def notify_leverage_capped(symbol: str, side: str, calculated_leverage: float, max_leverage: float):
    yon = "Long" if side == "long" else "Short"
    text = (
        "⚠️ *KALDIRAÇ LİMİTİ AŞILDI*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Yön: {yon}\n"
        f"Hesaplanan kaldıraç: {calculated_leverage:.0f}x\n"
        f"Coin'in izin verdiği max kaldıraç: {max_leverage:.0f}x\n"
        f"Uygulanan kaldıraç: {max_leverage:.0f}x\n"
        "Durum: İşlem, düşürülmüş kaldıraçla açıldı\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 7) BAGLANTI KOPTU / YENIDEN KURULDU
# ============================================================
def notify_connection_lost(last_success_str: str):
    text = (
        "🔴 *BAĞLANTI KOPTU*\n"
        "Sebep: Bybit API'den yanıt alınamıyor\n"
        f"Son başarılı veri: {last_success_str}\n"
        "Durum: Bot veri akışını kaybetti, yeniden bağlanmaya çalışıyor\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


def notify_connection_restored(downtime_seconds: float):
    text = (
        "🟢 *BAĞLANTI YENİDEN KURULDU*\n"
        f"Kopma süresi: {downtime_seconds:.0f} saniye\n"
        "Durum: Veri akışı normale döndü, bot takibe devam ediyor\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 8) YENIDEN BASLATILDI - ACIK POZISYON BULUNDU
# ============================================================
def notify_position_found_on_restart(symbol: str, side: str, entry_price: float,
                                      lose_exit_price: float, lose_exit_percent: float,
                                      sl_price: float, leverage: float):
    yon = "Short" if side == "short" else "Long"
    text = (
        "🔄 *AÇIK POZİSYON BULUNDU — TAKİBE ALINDI*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Yön: {yon}\n"
        f"Giriş fiyatı: {entry_price:.4f} USDT\n"
        f"Lose exit: {lose_exit_price:.4f} USDT (%{lose_exit_percent:.2f})\n"
        f"SL: {sl_price:.4f} USDT\n"
        f"Kaldıraç: {leverage:.0f}x\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)
