# -*- coding: utf-8 -*-
"""
sizing.py
---------
Islem acilirken kullanilacak lose exit seviyesi, SL seviyesi, kaldirac
ve islem hacmini hesaplar. Bu dosyadaki adimlar, konusma sirasinda
birebir anlatilan ornekle ayni sirayla ilerler:

    100 dolar giris, lose exit 95 dolar (%5)
    Toplam varlik 100 dolar -> isleme ayrilan: 8 dolar (%8)
    8 / 5 = 1.6
    1.6 x 100 = 160  -> islem hacmi
    160 / 8 = 20     -> kaldirac
"""

from dataclasses import dataclass

import config


@dataclass
class PositionSizeResult:
    entry_price: float
    lose_exit_price: float
    lose_exit_distance: float          # fiyat cinsinden mesafe
    lose_exit_percent: float           # giris fiyatina gore yuzde
    sl_price: float                    # lose_exit'in %1 otesinde (guvenlik agi)
    allocated_amount: float            # isleme ayrilan miktar (varligin %8'i)
    calculated_leverage: float         # formulden cikan ham kaldirac
    applied_leverage: float            # coin limiti uygulandiktan sonraki kaldirac
    leverage_was_capped: bool
    position_volume: float             # uygulanan kaldiracla gercek islem hacmi
    qty: float                         # coin adedi (hacim / giris fiyati)


def calculate_position(
    side: str,                 # "long" veya "short"
    entry_price: float,
    merkez_band_price: float,  # long icin merkez_ust_bant, short icin merkez_alt_bant
    total_equity: float,
    max_leverage_for_coin: float,
) -> PositionSizeResult:

    # 1) Giris ile merkez bandi arasi mesafe
    distance_to_band = abs(entry_price - merkez_band_price)

    # 2) Bu mesafenin 2 kati = lose exit mesafesi
    lose_exit_distance = distance_to_band * config.LOSE_EXIT_DISTANCE_MULT

    if side == "long":
        lose_exit_price = entry_price - lose_exit_distance
    else:
        lose_exit_price = entry_price + lose_exit_distance

    # 3) Bu mesafenin girise gore yuzdesi
    lose_exit_percent = (lose_exit_distance / entry_price) * 100

    # 4) SL: lose exit'in, giris fiyatina gore %1 daha uzaginda (guvenlik agi)
    sl_extra = entry_price * config.SL_EXTRA_PERCENT
    if side == "long":
        sl_price = lose_exit_price - sl_extra
    else:
        sl_price = lose_exit_price + sl_extra

    # 5) Toplam varligin %8'i isleme ayrilir
    allocated_amount = total_equity * config.EQUITY_PERCENT_PER_TRADE

    # 6) Ayrilan miktar / yuzde
    step1 = allocated_amount / lose_exit_percent

    # 7) Sonuc x 100 = hedeflenen islem hacmi
    target_volume = step1 * 100

    # 8) Hacim / ayrilan miktar = gereken kaldirac
    calculated_leverage = target_volume / allocated_amount

    # 9) Coin'in izin verdigi max kaldiraci asarsa, max kaldirac kullanilir.
    #    Bu durumda ayrilan miktar (risk edilen marj) ayni kalir, ama
    #    kaldirac dustugu icin gercek islem hacmi de kucuk kalir.
    leverage_was_capped = calculated_leverage > max_leverage_for_coin
    applied_leverage = min(calculated_leverage, max_leverage_for_coin)
    position_volume = allocated_amount * applied_leverage

    qty = position_volume / entry_price

    return PositionSizeResult(
        entry_price=entry_price,
        lose_exit_price=lose_exit_price,
        lose_exit_distance=lose_exit_distance,
        lose_exit_percent=lose_exit_percent,
        sl_price=sl_price,
        allocated_amount=allocated_amount,
        calculated_leverage=calculated_leverage,
        applied_leverage=applied_leverage,
        leverage_was_capped=leverage_was_capped,
        position_volume=position_volume,
        qty=qty,
    )
