# -*- coding: utf-8 -*-
"""
fayttrend_sizing.py
-------------------
Islem acilirken kullanilacak stake, hacim, kaldirac, lose exit ve
guvenlik SL seviyelerini hesaplar.

Adimlar:
    1) Giris aninda KARSI BANDA olan mesafe (D) olculur:
         long  -> ust bant - giris
         short -> giris - alt bant
    2) Lose exit : girisin D x LOSE_EXIT_DISTANCE_MULT kadar ters yonu (sabit)
       Guvenlik SL: girisin D x SL_DISTANCE_MULT kadar ters yonu (sabit)
    3) Stake: toplam varliga gore STAKE_TABLE'dan secilir (sinir degerler
       UST bareme girer).
    4) Kaldirac formulu:
         yuzde  = lose exit mesafesi / giris x 100
         hacim  = stake / yuzde x 100
         kaldirac = hacim / stake
       (Amac: fiyat lose exit'e gelirse kayip yaklasik stake kadar olsun.)
    5) Coin'in izin verdigi max kaldirac asilirsa max kaldirac kullanilir.
"""

from dataclasses import dataclass
from typing import Optional

import fayttrend_config as config


@dataclass
class PositionSizeResult:
    entry_price: float
    band_distance: float               # D: giris ile karsi bant arasi mesafe (fiyat cinsinden)
    opposite_band_price: float         # acilis anindaki karsi bant degeri (bilgi amacli)
    lose_exit_percent: float           # giris-lose exit mesafesinin yuzdesi (kaldirac formulunde kullanilan)
    sl_price: float                    # guvenlik SL (sabit)
    lose_exit_price: float             # lose exit (sabit)
    allocated_amount: float            # stake (tablodan)
    calculated_leverage: float         # formulden cikan ham kaldirac
    applied_leverage: float            # coin limiti uygulandiktan sonraki kaldirac
    leverage_was_capped: bool
    position_volume: float             # uygulanan kaldiracla gercek islem hacmi
    qty: float                         # coin adedi (hacim / giris fiyati)


def stake_for_equity(total_equity: float) -> float:
    """Toplam varliga gore stake tutarini dondurur. Sinir degerler UST
    bareme girer: tam 25 -> 0.50, tam 100 -> 2, tam 2500 -> 50."""
    stake = config.STAKE_TABLE[0][1]
    for lower_bound, amount in config.STAKE_TABLE:
        if total_equity >= lower_bound:
            stake = amount
        else:
            break
    return stake


def calculate_position(
    side: str,                 # "long" veya "short"
    entry_price: float,
    band_distance: float,      # D: karsi banda olan mesafe
    opposite_band_price: float,
    total_equity: float,
    max_leverage_for_coin: float,
) -> Optional[PositionSizeResult]:

    if not entry_price or band_distance <= 0:
        return None  # gecersiz durum - islem acilmamali

    # 1) Lose exit ve guvenlik SL (giris fiyatina gore, ters yonde, sabit)
    lose_exit_distance = band_distance * config.LOSE_EXIT_DISTANCE_MULT
    sl_distance = band_distance * config.SL_DISTANCE_MULT
    if side == "long":
        lose_exit_price = entry_price - lose_exit_distance
        sl_price = entry_price - sl_distance
    else:
        lose_exit_price = entry_price + lose_exit_distance
        sl_price = entry_price + sl_distance

    # Long'da seviyeler sifirin altina dusemez (cok genis bant durumu)
    if lose_exit_price <= 0 or sl_price <= 0:
        return None

    # 2) Kaldirac formulune giren yuzde
    lose_exit_percent = (lose_exit_distance / entry_price) * 100
    if lose_exit_percent <= 0:
        return None

    # 3) Stake: varlik tablosundan
    allocated_amount = stake_for_equity(total_equity)

    # 4) Stake / yuzde x 100 = hacim ; hacim / stake = kaldirac
    target_volume = (allocated_amount / lose_exit_percent) * 100
    calculated_leverage = target_volume / allocated_amount

    # 5) Coin'in izin verdigi max kaldiraci asarsa, max kaldirac kullanilir.
    leverage_was_capped = calculated_leverage > max_leverage_for_coin
    applied_leverage = min(calculated_leverage, max_leverage_for_coin)
    position_volume = allocated_amount * applied_leverage

    qty = position_volume / entry_price

    return PositionSizeResult(
        entry_price=entry_price,
        band_distance=band_distance,
        opposite_band_price=opposite_band_price,
        lose_exit_percent=lose_exit_percent,
        sl_price=sl_price,
        lose_exit_price=lose_exit_price,
        allocated_amount=allocated_amount,
        calculated_leverage=calculated_leverage,
        applied_leverage=applied_leverage,
        leverage_was_capped=leverage_was_capped,
        position_volume=position_volume,
        qty=qty,
    )
