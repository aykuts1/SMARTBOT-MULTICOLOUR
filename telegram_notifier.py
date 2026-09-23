# -*- coding: utf-8 -*-
"""
telegram_notifier.py
---------------------
Telegram'a mesaj gonderen fonksiyonlar ve konusma sirasinda onaylanan
tum bildirim sablonlari.

KOKLU GUNCELLEME (Gold/Silver): Islem acilis/kapanis/red bildirimleri
artik hangi TURDE (Gold/Silver) oldugunu basliginda ve/veya ayri bir
"Tur" satirinda gosteriyor. Gold'un TP hedefi Silver cizgisi, Silver'in
TP hedefi Gold cizgisidir - bildirimdeki "TP hedefi" etiketi buna gore
dinamik.
"""

import time
from datetime import datetime

import requests

import config


def _now_str() -> str:
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def _tur_etiket(trade_type: str) -> str:
    return "GOLD" if trade_type == "gold" else "SILVER"


def _hedef_cizgi_adi(trade_type: str) -> str:
    """Gold islemin TP hedefi Silver cizgisi, Silver islemin TP hedefi
    Gold cizgisidir (birbirinin tersi)."""
    return "Silver çizgisi" if trade_type == "gold" else "Gold çizgisi"


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
        "Mod: Hedge / Cross Margin — Gold + Silver\n"
        f"Toplam varlık: {equity:.2f} USDT\n"
        "Durum: Aktif, veri akışı başladı"
    )
    send_message(text)


# ============================================================
# 2) ISLEM GIRISI
# ============================================================
def notify_position_opened(symbol: str, side: str, trade_type: str, entry_price: float,
                            target_line_price: float, lose_exit_price: float, sl_price: float,
                            leverage: float, allocated_amount: float, volume: float):
    yon = "LONG" if side == "long" else "SHORT"
    tur = _tur_etiket(trade_type)
    emoji = "🔵" if side == "long" else "🔴"
    text = (
        f"{emoji} *İŞLEM AÇILDI — {yon} ({tur})*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Giriş fiyatı: {entry_price:.4f} USDT\n"
        f"TP hedefi ({_hedef_cizgi_adi(trade_type)}): {target_line_price:.4f} USDT\n"
        f"Stake: {allocated_amount:.2f} USDT (%{config.EQUITY_PERCENT_PER_TRADE*100:.0f})\n"
        f"Kaldıraç: {leverage:.0f}x\n"
        f"İşlem hacmi: {volume:.2f} USDT\n"
        f"Lose exit: {lose_exit_price:.4f} USDT\n"
        f"Güvenlik SL: {sl_price:.4f} USDT\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 3) ISLEM CIKISI  (sebep: "Take Profit" / "Trend Dönüşü" / "Lose Exit" / "Stop Loss")
# ============================================================
def notify_position_closed(symbol: str, side: str, trade_type: str, entry_price: float,
                            exit_price: float, reason: str, pnl: float,
                            price_change_percent: float, duration_seconds: float):
    yon = "LONG" if side == "long" else "SHORT"
    tur = _tur_etiket(trade_type)
    emoji = "🟢" if pnl >= 0 else "🔴"
    hours = int(duration_seconds // 3600)
    minutes = int((duration_seconds % 3600) // 60)
    text = (
        f"{emoji} *İŞLEM KAPANDI — {yon} ({tur})*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Giriş fiyatı: {entry_price:.4f} USDT\n"
        f"Çıkış fiyatı: {exit_price:.4f} USDT\n"
        f"Sebep: {reason}\n"
        f"Kâr/Zarar: {pnl:+.2f} USDT (%{price_change_percent:+.2f} fiyat değişimi)\n"
        f"Süre: {hours} saat {minutes} dk\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 4) SLOT DOLU (sadece toplam sistem slotu dolunca)
# ============================================================
def notify_slot_full(open_count: int, max_count: int, rejected_symbol: str,
                      rejected_side: str, rejected_type: str):
    """open_count/max_count artik REDDEDILEN YONE OZGU sayimdir (long
    sinyali reddedildiyse acik long sayisi/limiti, short icin de ayni) -
    long ve short icin ayri ayri limit oldugu icin (bkz. config.
    MAX_POSITIONS_PER_SIDE)."""
    yon = "Long" if rejected_side == "long" else "Short"
    tur = _tur_etiket(rejected_type)
    text = (
        "⚠️ *SLOT DOLU*\n"
        f"{yon} işlem sayısı: {open_count}/{max_count}\n"
        f"Yeni sinyal: {rejected_symbol.replace('USDT','')}/USDT — {yon} ({tur}) (reddedildi)\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 5) BAKIYE YETERSIZ (sinyal atlanir)
# ============================================================
def notify_insufficient_balance(symbol: str, side: str, trade_type: str,
                                 required_margin: float, available: float):
    yon = "Long" if side == "long" else "Short"
    tur = _tur_etiket(trade_type)
    text = (
        "⚠️ *BAKİYE YETERSİZ*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Yön: {yon}\n"
        f"Tür: {tur}\n"
        f"Gereken marj: {required_margin:.2f} USDT\n"
        f"Mevcut bakiye: {available:.2f} USDT\n"
        "Durum: Sinyal atlandı, işlem açılmadı\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 6) KALDIRAC LIMITI ASILDI
# ============================================================
def notify_leverage_capped(symbol: str, side: str, trade_type: str,
                            calculated_leverage: float, max_leverage: float):
    yon = "Long" if side == "long" else "Short"
    tur = _tur_etiket(trade_type)
    text = (
        "⚠️ *KALDIRAÇ LİMİTİ AŞILDI*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Yön: {yon}\n"
        f"Tür: {tur}\n"
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
def notify_position_found_on_restart(symbol: str, side: str, trade_type: str, entry_price: float,
                                      sl_price: float, lose_exit_price: float, leverage: float):
    yon = "Short" if side == "short" else "Long"
    tur = _tur_etiket(trade_type)
    text = (
        "🔄 *AÇIK POZİSYON BULUNDU — TAKİBE ALINDI*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Yön: {yon} ({tur})\n"
        f"Giriş fiyatı: {entry_price:.4f} USDT\n"
        f"Lose exit: {lose_exit_price:.4f} USDT\n"
        f"Güvenlik SL: {sl_price:.4f} USDT\n"
        f"Kaldıraç: {leverage:.0f}x\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)


# ============================================================
# 9) BOT CALISIRKEN - BORSADA BULUNAN, KAYITLI OLMAYAN POZISYON
# ============================================================
def notify_position_synced_from_exchange(symbol: str, side: str, trade_type: str, entry_price: float,
                                          sl_price: float, lose_exit_price: float, leverage: float,
                                          inferred: bool = False):
    """Restart'tan farkli olarak: bot ZATEN CALISIRKEN, dakikalik
    reconcile sirasinda borsada bulunan ama bot'un kendi kayitlarinda
    olmayan bir pozisyon icin gonderilir. inferred=True ise, turu
    (Gold/Silver) bot'un kendi kaydinda bulunamadigi icin trend yonuyle
    karsilastirilarak TAHMIN edildigini belirtir."""
    yon = "Short" if side == "short" else "Long"
    tur = _tur_etiket(trade_type)
    tur_notu = " (tahmin edildi)" if inferred else ""
    text = (
        "⚠️ *BORSADA BULUNAN POZİSYON KAYDA ALINDI*\n"
        f"Coin: {symbol.replace('USDT','')}/USDT\n"
        f"Yön: {yon} ({tur}{tur_notu})\n"
        f"Giriş fiyatı: {entry_price:.4f} USDT\n"
        f"Lose exit: {lose_exit_price:.4f} USDT\n"
        f"Güvenlik SL: {sl_price:.4f} USDT\n"
        f"Kaldıraç: {leverage:.0f}x\n"
        "Not: Bu pozisyon botun kendi kayıtlarında yoktu - elle açılmış "
        "olabilir ya da bot bir aksama sonucu kaçırmış olabilir, kontrol etmen iyi olur.\n"
        f"Saat: {_now_str()}"
    )
    send_message(text)
