# -*- coding: utf-8 -*-
"""
state.py
--------
Botun "hafizasi": su an acik olan pozisyonlar, kapanan islemlerin
gecmisi, varlik (equity) gecmisi ve sistem olaylari (bakiye yetersiz /
slot dolu / kaldirac limiti asildi). Bot yeniden baslatildiginda, acik
pozisyonlar borsadan okunup burada yeniden kurulur.

KOKLU GUNCELLEME:
- Her coin'de artik en fazla 1 acik islem olabilecegi icin pozisyonlar
  artik "SYMBOL_side" degil, dogrudan "SYMBOL" anahtariyla tutuluyor.
- Eski "lose exit" alanlari (lose_exit_price, lose_exit_percent) ve
  bunlari yeniden baslatmada geri hesaplayan reconstruct_lose_exit()
  tamamen kaldirildi - yeni SL sabit ve dogrudan borsadan okunuyor.
- Detayli raporlar icin equity_history (varlik gecmisi) ve
  system_events (bakiye yetersiz / slot dolu / kaldirac limiti) takibi
  eklendi.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import config


@dataclass
class Position:
    symbol: str
    side: str                # "long" / "short"
    position_idx: int        # 1 = long, 2 = short (hedge modu)
    entry_price: float
    sl_price: float            # guvenlik SL - acilista sabitlenir, sonra degismez
    lose_exit_price: float     # lose exit - acilista sabitlenir, sonra degismez (RR 1:1.5)
    leverage: float
    allocated_amount: float
    qty: float
    exit_line_at_entry: Optional[float] = None      # acilis anindaki Exit cizgisi (bilgi amacli)
    entry_exit_percent: Optional[float] = None       # sizing icin kullanilan yuzde (bilgi amacli)
    leverage_was_capped: bool = False
    open_time: float = field(default_factory=time.time)


class BotState:
    def __init__(self):
        self.positions: dict[str, Position] = {}  # key: symbol (coin basina tek pozisyon)
        self.trade_history: list[dict] = []
        self.equity_history: list[dict] = []       # [{"t": ts, "equity": float}, ...]
        self.system_events: list[dict] = []        # [{"t": ts, "type": .., "symbol": .., "side": ..}, ...]
        self._load_trade_history()
        self._load_equity_history()
        self._load_system_events()

    # ------------------------------------------------------------
    # POZISYONLAR (coin basina tek anahtar)
    # ------------------------------------------------------------
    def add_position(self, pos: Position):
        self.positions[pos.symbol] = pos

    def remove_position(self, symbol: str) -> Optional[Position]:
        return self.positions.pop(symbol, None)

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

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

    def trades_for_symbol(self, symbol: str) -> list:
        return [t for t in self.trade_history if t.get("symbol") == symbol]

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

    # ------------------------------------------------------------
    # VARLIK (EQUITY) GECMISI
    # ------------------------------------------------------------
    def record_equity_snapshot(self, equity: float):
        self.equity_history.append({"t": time.time(), "equity": equity})
        self._prune_equity_history()
        self._save_equity_history()

    def _prune_equity_history(self):
        cutoff = time.time() - config.EQUITY_HISTORY_RETENTION_DAYS * 24 * 3600
        self.equity_history = [e for e in self.equity_history if e["t"] >= cutoff]

    def equity_since(self, seconds_ago: float) -> list:
        cutoff = time.time() - seconds_ago
        return [e for e in self.equity_history if e["t"] >= cutoff]

    def equity_before(self, seconds_ago: float) -> Optional[float]:
        """seconds_ago kadar once (veya ona en yakin, oncesindeki) kayitli
        varlik degerini dondurur. Yoksa None."""
        target = time.time() - seconds_ago
        candidates = [e for e in self.equity_history if e["t"] <= target]
        if not candidates:
            return None
        return candidates[-1]["equity"]

    def equity_high_low_since(self, seconds_ago: float):
        points = self.equity_since(seconds_ago)
        if not points:
            return None, None
        values = [e["equity"] for e in points]
        return max(values), min(values)

    def max_drawdown_since(self, seconds_ago: float) -> float:
        """Yuzde cinsinden en buyuk dusus (tepe noktadan)."""
        points = self.equity_since(seconds_ago)
        if not points:
            return 0.0
        peak = points[0]["equity"]
        max_dd = 0.0
        for e in points:
            peak = max(peak, e["equity"])
            if peak > 0:
                dd = (e["equity"] - peak) / peak * 100
                max_dd = min(max_dd, dd)
        return max_dd

    def _save_equity_history(self):
        try:
            with open(config.EQUITY_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(self.equity_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[state] Varlik gecmisi kaydedilemedi: {e}")

    def _load_equity_history(self):
        if os.path.exists(config.EQUITY_HISTORY_FILE):
            try:
                with open(config.EQUITY_HISTORY_FILE, "r", encoding="utf-8") as f:
                    self.equity_history = json.load(f)
            except Exception as e:
                print(f"[state] Varlik gecmisi okunamadi: {e}")
                self.equity_history = []

    # ------------------------------------------------------------
    # SISTEM OLAYLARI (bakiye yetersiz / slot dolu / kaldirac limiti)
    # ------------------------------------------------------------
    def record_system_event(self, event_type: str, symbol: str = "", side: str = ""):
        self.system_events.append({
            "t": time.time(), "type": event_type, "symbol": symbol, "side": side,
        })
        self._prune_system_events()
        self._save_system_events()

    def _prune_system_events(self):
        cutoff = time.time() - config.EQUITY_HISTORY_RETENTION_DAYS * 24 * 3600
        self.system_events = [e for e in self.system_events if e["t"] >= cutoff]

    def system_events_since(self, seconds_ago: float, event_type: Optional[str] = None) -> list:
        cutoff = time.time() - seconds_ago
        events = [e for e in self.system_events if e["t"] >= cutoff]
        if event_type:
            events = [e for e in events if e["type"] == event_type]
        return events

    def _save_system_events(self):
        try:
            with open(config.SYSTEM_EVENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.system_events, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[state] Sistem olaylari kaydedilemedi: {e}")

    def _load_system_events(self):
        if os.path.exists(config.SYSTEM_EVENTS_FILE):
            try:
                with open(config.SYSTEM_EVENTS_FILE, "r", encoding="utf-8") as f:
                    self.system_events = json.load(f)
            except Exception as e:
                print(f"[state] Sistem olaylari okunamadi: {e}")
                self.system_events = []


def reconstruct_lose_exit(entry_price: float, sl_price: float, side: str) -> float:
    """Yeniden baslatmada: lose exit borsada saklanan bir deger degildir
    (sadece guvenlik SL borsada gercek bir emir olarak durur), bu yuzden
    restart sonrasi acik bir pozisyon bulundugunda lose exit seviyesi
    guvenlik SL'den GERI HESAPLANIR.

    Ikisi de ayni oranli formulden turedigi icin bu hesap tam isabetlidir:
        SL mesafesi        = D * SL_DISTANCE_MULT
        lose exit mesafesi = D * LOSE_EXIT_DISTANCE_MULT
    yani:
        lose exit mesafesi = SL mesafesi * (LOSE_EXIT_DISTANCE_MULT / SL_DISTANCE_MULT)
    """
    if not sl_price:
        return 0.0
    sl_distance = abs(entry_price - sl_price)
    ratio = config.LOSE_EXIT_DISTANCE_MULT / config.SL_DISTANCE_MULT
    lose_exit_distance = sl_distance * ratio
    if side == "long":
        return entry_price - lose_exit_distance
    return entry_price + lose_exit_distance
