# -*- coding: utf-8 -*-
"""
sizing.py
---------
Islem acilirken kullanilacak stake, hacim, kaldirac ve guvenlik SL /
lose exit seviyelerini hesaplar. Hem GOLD hem SILVER islemler AYNI
formulu kullanir - tek fark lose exit carpani (Gold: 1.5, Silver: 1.0),
bu yuzden fonksiyon disaridan parametre olarak aliyor.

KOKLU GUNCELLEME: Kaldirac/hacim formulundeki "yuzde" artik GIRIS-TP
MESAFESINDEN degil, GIRIS-LOSE EXIT MESAFESINDEN hesaplaniyor. Lose
exit ve guvenlik SL seviyelerinin KENDI hesabi degismedi (hala TP
mesafesine oranli) - sadece kaldiraç formuluna giren yuzde degisti.

Sonuc: Gold'da (lose exit carpani 1.5, TP mesafesinden daha genis
oldugu icin) kaldirac ONCEKINE GORE DUSER - ayni stake ile daha az
hacim/kaldirac, risk mesafesine gore daha muhafazakar bir boyutlandirma.
Silver'da ise lose exit mesafesi zaten TP mesafesiyle AYNIYDI (RR 1:1),
bu yuzden Silver'in kaldiracinda HICBIR DEGISIKLIK olmuyor.

Adimlar (yeni haliyle):
    1) Giris ile TP hedefi arasi mesafe olculur (SL ve lose exit
       seviyeleri hala buradan turetilir - degismedi)
    2) Lose exit mesafesi = TP mesafesi x lose_exit_mult (Gold: 1.5,
       Silver: 1.0)
    3) Kaldirac formulune giren yuzde = lose exit mesafesi / giris
       fiyati x 100
    4) Stake / bu yuzde = ... x 100 = hacim -> hacim / stake = kaldirac

Ikisi de (lose exit, guvenlik SL) ACILISTA bir kez hesaplanir ve SABIT
kalir.
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class PositionSizeResult:
    entry_price: float
    target_line_price: float           # acilis anindaki TP hedef cizgisi degeri
    entry_target_distance: float       # giris-TP mesafesi (fiyat cinsinden) - SL/lose exit buradan turetilir
    entry_target_percent: float        # giris-TP mesafesinin yuzdesi (bilgi amacli - artik kaldiracta kullanilmiyor)
    entry_lose_exit_percent: float     # giris-lose exit mesafesinin yuzdesi - KALDIRAÇ FORMULUNDE KULLANILAN budur
    sl_price: float                    # entry +/- SL_DISTANCE_MULT x TP mesafesi (sabit)
    lose_exit_price: float             # entry +/- lose_exit_mult x TP mesafesi (sabit)
    allocated_amount: float            # stake (varligin %3'u)
    calculated_leverage: float         # formulden cikan ham kaldirac
    applied_leverage: float            # coin limiti uygulandiktan sonraki kaldirac
    leverage_was_capped: bool
    position_volume: float             # uygulanan kaldiracla gercek islem hacmi
    qty: float                         # coin adedi (hacim / giris fiyati)


def calculate_position(
    side: str,                 # "long" veya "short"
    entry_price: float,
    target_line_price: float,  # o anki TP hedef cizgisinin degeri
    total_equity: float,
    max_leverage_for_coin: float,
    lose_exit_mult: float,     # config.LOSE_EXIT_DISTANCE_MULT_GOLD veya _SILVER
) -> Optional[PositionSizeResult]:

    # 1) Giris ile TP hedefi arasi mesafe (SL ve lose exit hala buradan turer)
    entry_target_distance = abs(entry_price - target_line_price)
    entry_target_percent = (entry_target_distance / entry_price) * 100 if entry_price else 0.0

    if entry_target_percent <= 0:
        return None  # gecersiz durum (mesafe sifir/negatif) - islem acilmamali

    # 2) Guvenlik SL: giris fiyatina gore, TP mesafesinin SL_DISTANCE_MULT kati uzakta (sabit)
    sl_distance = entry_target_distance * config.SL_DISTANCE_MULT
    if side == "long":
        sl_price = entry_price - sl_distance
    else:
        sl_price = entry_price + sl_distance

    # 3) Lose exit: guvenlik SL ile AYNI yonde ama (Gold'da) daha yakin -
    #    TP mesafesinin lose_exit_mult kati uzakta (sabit).
    lose_exit_distance = entry_target_distance * lose_exit_mult
    if side == "long":
        lose_exit_price = entry_price - lose_exit_distance
    else:
        lose_exit_price = entry_price + lose_exit_distance

    # 4) KALDIRAÇ FORMULUNE GIREN YUZDE: artik giris-lose exit mesafesinden
    entry_lose_exit_percent = (lose_exit_distance / entry_price) * 100 if entry_price else 0.0
    if entry_lose_exit_percent <= 0:
        return None

    # 5) Stake: toplam varligin %3'u
    allocated_amount = total_equity * config.EQUITY_PERCENT_PER_TRADE

    # 6) Stake / (lose exit yuzdesi)
    step1 = allocated_amount / entry_lose_exit_percent

    # 7) Sonuc x 100 = hedeflenen islem hacmi
    target_volume = step1 * 100

    # 8) Hacim / stake = gereken kaldirac
    calculated_leverage = target_volume / allocated_amount

    # 9) Coin'in izin verdigi max kaldiraci asarsa, max kaldirac kullanilir.
    leverage_was_capped = calculated_leverage > max_leverage_for_coin
    applied_leverage = min(calculated_leverage, max_leverage_for_coin)
    position_volume = allocated_amount * applied_leverage

    qty = position_volume / entry_price

    return PositionSizeResult(
        entry_price=entry_price,
        target_line_price=target_line_price,
        entry_target_distance=entry_target_distance,
        entry_target_percent=entry_target_percent,
        entry_lose_exit_percent=entry_lose_exit_percent,
        sl_price=sl_price,
        lose_exit_price=lose_exit_price,
        allocated_amount=allocated_amount,
        calculated_leverage=calculated_leverage,
        applied_leverage=applied_leverage,
        leverage_was_capped=leverage_was_capped,
        position_volume=position_volume,
        qty=qty,
    )
