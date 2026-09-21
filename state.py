# -*- coding: utf-8 -*-
"""
state.py
--------
Botun "hafizasi": su an acik olan pozisyonlar ve kapanan islemlerin
gecmisi. Bot yeniden baslatildiginda, acik pozisyonlar borsadan okunup
burada yeniden kurulur (sifirdan hesaplama yapilmaz).
"""

import json
import os
import time
from dataclasses import dataclass, asdict, field
from typing import Optional

import config


@dataclass
class Position:
    symbol: str
    side: str                # "long" / "short"
    position_idx: int        # 1 = long, 2 = short (hedge modu)
    entry_price: float
    lose_exit_price: float
    lose_exit_percent: float
    sl_price: float
    leverage: float
    allocated_amount: float
    qty: float
    open_time: float = field(default_factory=time.time)


class BotState:
    def __init__(self):
        self.positions: dict[str, Position] = {}  # key: "SYMBOL_side"
        self.trade_history: list[dict] = []
        self._load_trade_history()

    # ------------------------------------------------------------
    def _key(self, symbol: str, side: str) -> str:
        return f"{symbol}_{side}"

    def add_position(self, pos: Position):
        self.positions[self._key(pos.symbol, pos.side)] = pos

    def remove_position(self, symbol: str, side: str) -> Optional[Position]:
        return self.positions.pop(self._key(symbol, side), None)

    def get_position(self, symbol: str, side: str) -> Optional[Position]:
        return self.positions.get(self._key(symbol, side))

    def has_position(self, symbol: str, side: str) -> bool:
        return self._key(symbol, side) in self.positions

    def coin_has_any_position(self, symbol: str) -> bool:
        return self.has_position(symbol, "long") or self.has_position(symbol, "short")

    def total_open_count(self) -> int:
        return len(self.positions)

    def all_positions(self):
        return list(self.positions.values())

    # ------------------------------------------------------------
    # ISLEM GECMISI (raporlar icin)
    # ------------------------------------------------------------
    def record_closed_trade(self, trade: dict):
        trade["closed_at"] = time.time()
        self.trade_history.append(trade)
        self._save_trade_history()

    def trades_since(self, seconds_ago: float) -> list:
        cutoff = time.time() - seconds_ago
        return [t for t in self.trade_history if t["closed_at"] >= cutoff]

    def _save_trade_history(self):
        try:
            with open(config.TRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.trade_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[state] Islem gecmisi kaydedilemedi: {e}")

    def _load_trade_history(self):
        if os.path.exists(config.TRADE_HISTORY_FILE):
            try:
                with open(config.TRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.trade_history = json.load(f)
            except Exception as e:
                print(f"[state] Islem gecmisi okunamadi: {e}")
                self.trade_history = []


def reconstruct_lose_exit(entry_price: float, sl_price: float, side: str) -> tuple:
    """
    Yeniden baslatmada: borsadan okunan giris fiyati ve SL fiyatindan,
    lose exit seviyesini geri hesaplar.

    SL = lose_exit +/- (giris_fiyati * %1)  ->  lose_exit = SL -/+ (giris_fiyati * %1)
    """
    sl_extra = entry_price * config.SL_EXTRA_PERCENT
    if side == "long":
        lose_exit_price = sl_price + sl_extra
    else:
        lose_exit_price = sl_price - sl_extra

    lose_exit_distance = abs(entry_price - lose_exit_price)
    lose_exit_percent = (lose_exit_distance / entry_price) * 100
    return lose_exit_price, lose_exit_percent
