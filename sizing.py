# -*- coding: utf-8 -*-
"""
sizing.py
-------------------
Islem acilirken kullanilacak stake, hacim, kaldirac, sabit lose exit ve
guvenlik SL seviyelerini hesaplar.

Adimlar:
    1) TP mesafesi: |giris - ana cizgi|  (acilis anindaki degerler)
    2) Sabit lose exit: girisin TP mesafesi x FIXED_LOSE_EXIT_TP_MULT (1.5)
       kadar TERS yonu. Acilista sabitlenir, sonra degismez.
    3) Guvenlik SL (borsada gercek emir): girisin, sabit lose exit
       MESAFESININ SAFETY_SL_MULT (2) kati kadar TERS yonu. Sabit.
    4) Stake: toplam varliga gore STAKE_TABLE'dan secilir (sinir degerler
       UST bareme girer).
    5) Kaldirac (risk cizgisi = Silver loss (long) / Gold loss (short),
       ACILIS ANINDAKI degeri):
         yuzde    = |giris - risk cizgisi| / giris x 100
         hacim    = stake / yuzde x 100
         kaldirac = hacim / stake
       (Amac: fiyat risk cizgisine gelirse kayip yaklasik stake kadar olsun.)
    6) Coin'in izin verdigi max kaldirac asilirsa max kaldirac kullanilir.
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class PositionSizeResult:
    entry_price: float
    tp_price: float                    # acilis anindaki ana cizgi (TP)
    tp_distance: float                 # |giris - TP|
    risk_line_price: float             # acilis anindaki Silver loss / Gold loss
    risk_distance: float               # |giris - risk cizgisi| (kaldirac formulunde)
    risk_percent: float                # risk_distance / giris x 100
    sl_price: float                    # guvenlik SL (sabit)
    lose_exit_price: float             # sabit lose exit
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
    tp_price: float,           # acilis anindaki ana cizgi
    risk_line_price: float,    # acilis anindaki Silver loss (long) / Gold loss (short)
    total_equity: float,
    max_leverage_for_coin: float,
) -> Optional[PositionSizeResult]:

    if not entry_price or entry_price <= 0:
        return None

    # 1) Mesafeler (yon kontrolu dahil: TP girisin karsi tarafinda, risk
    #    cizgisi girisin ters tarafinda olmali; degilse islem acilmaz)
    if side == "long":
        tp_distance = tp_price - entry_price
        risk_distance = entry_price - risk_line_price
    else:
        tp_distance = entry_price - tp_price
        risk_distance = risk_line_price - entry_price

    if tp_distance <= 0 or risk_distance <= 0:
        return None

    # 2) Sabit lose exit ve guvenlik SL (acilista sabit)
    lose_exit_distance = tp_distance * config.FIXED_LOSE_EXIT_TP_MULT
    sl_distance = lose_exit_distance * config.SAFETY_SL_MULT
    if side == "long":
        lose_exit_price = entry_price - lose_exit_distance
        sl_price = entry_price - sl_distance
    else:
        lose_exit_price = entry_price + lose_exit_distance
        sl_price = entry_price + sl_distance

    # Long'da seviyeler sifirin altina dusemez (cok genis mesafe durumu)
    if lose_exit_price <= 0 or sl_price <= 0:
        return None

    # 3) Kaldirac formulune giren yuzde
    risk_percent = (risk_distance / entry_price) * 100
    if risk_percent <= 0:
        return None

    # 4) Stake: varlik tablosundan
    allocated_amount = stake_for_equity(total_equity)

    # 5) Stake / yuzde x 100 = hacim ; hacim / stake = kaldirac
    target_volume = (allocated_amount / risk_percent) * 100
    calculated_leverage = target_volume / allocated_amount

    # 6) Coin'in izin verdigi max kaldiraci asarsa, max kaldirac kullanilir.
    #    Borsa 1x'in altini kabul etmez.
    leverage_was_capped = calculated_leverage > max_leverage_for_coin
    applied_leverage = max(1.0, min(calculated_leverage, max_leverage_for_coin))
    position_volume = allocated_amount * applied_leverage

    qty = position_volume / entry_price

    return PositionSizeResult(
        entry_price=entry_price,
        tp_price=tp_price,
        tp_distance=tp_distance,
        risk_line_price=risk_line_price,
        risk_distance=risk_distance,
        risk_percent=risk_percent,
        sl_price=sl_price,
        lose_exit_price=lose_exit_price,
        allocated_amount=allocated_amount,
        calculated_leverage=calculated_leverage,
        applied_leverage=applied_leverage,
        leverage_was_capped=leverage_was_capped,
        position_volume=position_volume,
        qty=qty,
    )
