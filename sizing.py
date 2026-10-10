# -*- coding: utf-8 -*-
"""
sizing.py
-------------------
Islem acilirken kullanilacak stake, hacim ve kaldiraci hesaplar.

Adimlar:
    1) TP mesafesi: |giris - ana cizgi|  (acilis anindaki degerler)
    2) Stake: futures cuzdan bakiyesinin %STAKE_PERCENT'i (varsayilan %1).
       Bakiye, acik islemlerdeki gecici kar/zarari icermez (bkz. config.py).
    3) Kaldirac (TP mesafesine gore - ACILIS ANINDAKI deger):
         yuzde    = |giris - TP| / giris x 100
         hacim    = stake / yuzde x 100
         kaldirac = hacim / stake
       (Amac: fiyat TP'ye (ana cizgiye) gelirse kar yaklasik stake kadar
       olsun.)
    4) Coin'in izin verdigi max kaldirac asilirsa max kaldirac kullanilir.

Stop Loss burada hesaplanmaz: seviyesi, pozisyon acildiktan sonra Bybit'in
verdigi likit fiyatina gore strategy.py'de belirlenir.
"""

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class PositionSizeResult:
    entry_price: float
    tp_price: float                    # acilis anindaki ana cizgi (TP)
    tp_distance: float                 # |giris - TP| (kaldirac formulunde de kullanilir)
    tp_percent: float                  # tp_distance / giris x 100
    allocated_amount: float            # stake (bakiyenin %1'i)
    calculated_leverage: float         # formulden cikan ham kaldirac
    applied_leverage: float            # coin limiti uygulandiktan sonraki kaldirac
    leverage_was_capped: bool
    position_volume: float             # uygulanan kaldiracla gercek islem hacmi
    qty: float                         # coin adedi (hacim / giris fiyati)


def stake_for_balance(wallet_balance: float) -> float:
    """Futures cuzdan bakiyesine gore stake tutarini dondurur
    (bakiyenin %STAKE_PERCENT'i)."""
    if not wallet_balance or wallet_balance <= 0:
        return 0.0
    return wallet_balance * config.STAKE_PERCENT / 100.0


def calculate_position(
    side: str,                 # "long" veya "short"
    entry_price: float,
    tp_price: float,           # acilis anindaki ana cizgi
    wallet_balance: float,     # futures cuzdan bakiyesi (gecici kar/zarar haric)
    max_leverage_for_coin: float,
) -> Optional[PositionSizeResult]:

    if not entry_price or entry_price <= 0:
        return None

    # 1) TP mesafesi (yon kontrolu dahil: TP girisin karsi tarafinda
    #    olmali; degilse islem acilmaz)
    if side == "long":
        tp_distance = tp_price - entry_price
    elif side == "short":
        tp_distance = entry_price - tp_price
    else:
        return None

    if tp_distance <= 0:
        return None

    # 2) Kaldirac formulune giren yuzde (TP mesafesine gore)
    tp_percent = (tp_distance / entry_price) * 100
    if tp_percent <= 0:
        return None

    # 3) Stake: bakiyenin yuzdesi
    allocated_amount = stake_for_balance(wallet_balance)
    if allocated_amount <= 0:
        return None

    # 4) Stake / yuzde x 100 = hacim ; hacim / stake = kaldirac
    target_volume = (allocated_amount / tp_percent) * 100
    calculated_leverage = target_volume / allocated_amount

    # 5) Coin'in izin verdigi max kaldiraci asarsa, max kaldirac kullanilir.
    #    Borsa 1x'in altini kabul etmez.
    leverage_was_capped = calculated_leverage > max_leverage_for_coin
    applied_leverage = max(1.0, min(calculated_leverage, max_leverage_for_coin))
    position_volume = allocated_amount * applied_leverage

    qty = position_volume / entry_price

    return PositionSizeResult(
        entry_price=entry_price,
        tp_price=tp_price,
        tp_distance=tp_distance,
        tp_percent=tp_percent,
        allocated_amount=allocated_amount,
        calculated_leverage=calculated_leverage,
        applied_leverage=applied_leverage,
        leverage_was_capped=leverage_was_capped,
        position_volume=position_volume,
        qty=qty,
    )
