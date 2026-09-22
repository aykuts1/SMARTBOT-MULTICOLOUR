# -*- coding: utf-8 -*-
"""
sizing.py
---------
Islem acilirken kullanilacak stake, hacim, kaldirac ve guvenlik SL
seviyesini hesaplar. Bu dosyadaki adimlar, konusma sirasinda birebir
anlatilan ornekle ayni sirayla ilerler:

    Entry-Exit cizgisi mesafesi -> girise gore yuzde: ornek %5
    Stake = toplam varligin %8'i: ornek 8 dolar
    8 / 5 = 1.6
    1.6 x 100 = 160  -> islem hacmi
    160 / 8 = 20     -> kaldirac

Guvenlik SL: giris fiyati ile Exit cizgisi arasindaki mesafenin 2 kati,
borsaya gercek stop-loss emri olarak koyulur. Bu seviye ACILISTA bir kez
hesaplanir ve SABIT kalir - Exit cizgisi sonradan hareket etse bile SL
guncellenmez.

Lose exit: yine ACILISTA bir kez hesaplanan, SABIT kalan bir seviye -
TP'nin (Exit cizgisi mesafesinin) TERS yonunde, ama TP'den DAHA UZAKTA:
mesafesi Entry-Exit mesafesinin 1.5 kati (RR 1:1.5 - TP mesafesi 100 ise
lose exit mesafesi 150). Guvenlik SL'den (2 kati) DAHA YAKINDIR, yani
normal kosullarda pozisyon once lose exit'te kapanir; borsadaki gercek
SL sadece bot/baglanti koparsa diye bir guvenlik agi olarak kalir.

KOKLU GUNCELLEME: Eski (T3/Merkez donemindeki) sabit yuzdeli "lose exit"
hesabi tamamen kaldirildi. Yerine gelen yeni lose exit, Entry-Exit
cizgisi mesafesine ORANLI (RR 1:1.5) ve acilista sabitlenen bir seviye -
detay asagida.
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class PositionSizeResult:
    entry_price: float
    exit_line_price: float             # acilis anindaki Exit cizgisi degeri
    entry_exit_distance: float         # fiyat cinsinden mesafe
    entry_exit_percent: float          # girise gore yuzde
    sl_price: float                    # entry +/- 2x mesafe (sabit) - guvenlik agi
    lose_exit_price: float             # entry +/- 1.5x mesafe (sabit) - RR 1:1.5
    allocated_amount: float            # stake (varligin %8'i)
    calculated_leverage: float         # formulden cikan ham kaldirac
    applied_leverage: float            # coin limiti uygulandiktan sonraki kaldirac
    leverage_was_capped: bool
    position_volume: float             # uygulanan kaldiracla gercek islem hacmi
    qty: float                         # coin adedi (hacim / giris fiyati)


def calculate_position(
    side: str,                 # "long" veya "short"
    entry_price: float,
    exit_line_price: float,    # o anki Exit cizgisi degeri
    total_equity: float,
    max_leverage_for_coin: float,
) -> Optional[PositionSizeResult]:

    # 1) Giris ile Exit cizgisi arasi mesafe
    entry_exit_distance = abs(entry_price - exit_line_price)
    entry_exit_percent = (entry_exit_distance / entry_price) * 100 if entry_price else 0.0

    if entry_exit_percent <= 0:
        # Gecersiz durum (mesafe sifir/negatif) - islem acilmamali
        return None

    # 2) Guvenlik SL: giris fiyatina gore, Exit mesafesinin 2 kati uzakta (sabit)
    sl_distance = entry_exit_distance * config.SL_DISTANCE_MULT
    if side == "long":
        sl_price = entry_price - sl_distance
    else:
        sl_price = entry_price + sl_distance

    # 2b) Lose exit: guvenlik SL ile AYNI yonde ama daha yakin - Exit
    #     mesafesinin 1.5 kati uzakta (sabit). RR 1:1.5.
    lose_exit_distance = entry_exit_distance * config.LOSE_EXIT_DISTANCE_MULT
    if side == "long":
        lose_exit_price = entry_price - lose_exit_distance
    else:
        lose_exit_price = entry_price + lose_exit_distance

    # 3) Stake: toplam varligin %8'i
    allocated_amount = total_equity * config.EQUITY_PERCENT_PER_TRADE

    # 4) Stake / yuzde
    step1 = allocated_amount / entry_exit_percent

    # 5) Sonuc x 100 = hedeflenen islem hacmi
    target_volume = step1 * 100

    # 6) Hacim / stake = gereken kaldirac
    calculated_leverage = target_volume / allocated_amount

    # 7) Coin'in izin verdigi max kaldiraci asarsa, max kaldirac kullanilir.
    #    Bu durumda stake ayni kalir, ama kaldirac dustugu icin gercek
    #    islem hacmi de kucuk kalir.
    leverage_was_capped = calculated_leverage > max_leverage_for_coin
    applied_leverage = min(calculated_leverage, max_leverage_for_coin)
    position_volume = allocated_amount * applied_leverage

    qty = position_volume / entry_price

    return PositionSizeResult(
        entry_price=entry_price,
        exit_line_price=exit_line_price,
        entry_exit_distance=entry_exit_distance,
        entry_exit_percent=entry_exit_percent,
        sl_price=sl_price,
        lose_exit_price=lose_exit_price,
        allocated_amount=allocated_amount,
        calculated_leverage=calculated_leverage,
        applied_leverage=applied_leverage,
        leverage_was_capped=leverage_was_capped,
        position_volume=position_volume,
        qty=qty,
    )
