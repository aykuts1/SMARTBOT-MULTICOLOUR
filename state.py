# -*- coding: utf-8 -*-
"""
state.py
--------
Botun "hafizasi": su an acik olan pozisyonlar, kapanan islemlerin
gecmisi, varlik (equity) gecmisi ve sistem olaylari (bakiye yetersiz /
slot dolu / kaldirac limiti asildi). Bot yeniden baslatildiginda, acik
pozisyonlar borsadan okunup burada yeniden kurulur.

KOKLU GUNCELLEME (Gold/Silver):
- Bir coin'de artik AYNI ANDA hem 1 long hem 1 short acik olabilir
  (Gold ve Silver hep ters yonde actigi icin bu dogal bir durum, borsanin
  hedge modu kapasitesiyle birebir ortusuyor). Bu yuzden pozisyonlar
  artik "SYMBOL" degil, "SYMBOL_side" anahtariyla tutuluyor.
- Her Position artik bir "trade_type" ("gold"/"silver") tasiyor. Borsa
  bu bilgiyi saklamadigi icin (sadece long/short + fiyat/SL bilgisi
  verir), bot bunu kendi diskine KUCUK bir kayit olarak da tutuyor
  (position_types) - restart sonrasi acik bir pozisyonun Gold mu Silver
  mi oldugunu buradan hatirliyor. Eger bu kayitta yoksa (ornegin elle
  acilmis bir pozisyon), o anki trend yonuyle karsilastirilarak tahmin
  ediliyor (bkz. strategy._infer_trade_type).
- reconstruct_lose_exit artik lose_exit_mult parametresi aliyor, cunku
  bu carpan artik Gold ve Silver icin farkli (1.5 / 1.0).
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
    side: str                  # "long" / "short"
    position_idx: int          # 1 = long, 2 = short (hedge modu)
    trade_type: str            # "gold" veya "silver"
    entry_price: float
    sl_price: float             # guvenlik SL - acilista sabitlenir, sonra degismez
    lose_exit_price: float      # lose exit - acilista sabitlenir, sonra degismez
    leverage: float
    allocated_amount: float
    qty: float
    target_line_at_entry: Optional[float] = None    # acilis anindaki TP hedef cizgisi (bilgi amacli)
    entry_target_percent: Optional[float] = None      # giris-TP mesafesinin yuzdesi (bilgi amacli)
    entry_lose_exit_percent: Optional[float] = None    # giris-lose exit mesafesinin yuzdesi (kaldiracta KULLANILAN)
    leverage_was_capped: bool = False
    open_time: float = field(default_factory=time.time)


class BotState:
    def __init__(self):
        self.positions: dict[str, Position] = {}   # key: "SYMBOL_side"
        self.position_types: dict[str, str] = {}    # key: "SYMBOL_side" -> "gold"/"silver"
        self.trade_history: list[dict] = []
        self.equity_history: list[dict] = []
        self.system_events: list[dict] = []
        self._load_trade_history()
        self._load_equity_history()
        self._load_system_events()
        self._load_position_types()

    # ------------------------------------------------------------
    # POZISYONLAR (coin + yon anahtari: coin basina 1 long + 1 short)
    # ------------------------------------------------------------
    def _key(self, symbol: str, side: str) -> str:
        return f"{symbol}_{side}"

    def add_position(self, pos: Position):
        key = self._key(pos.symbol, pos.side)
        self.positions[key] = pos
        # Tur bilgisini de restart-kurtarma dosyasina yaz.
        self.position_types[key] = pos.trade_type
        self._save_position_types()

    def remove_position(self, symbol: str, side: str) -> Optional[Position]:
        key = self._key(symbol, side)
        self.position_types.pop(key, None)
        self._save_position_types()
        return self.positions.pop(key, None)

    def get_position(self, symbol: str, side: str) -> Optional[Position]:
        return self.positions.get(self._key(symbol, side))

    def has_position(self, symbol: str, side: str) -> bool:
        return self._key(symbol, side) in self.positions

    def total_open_count(self) -> int:
        return len(self.positions)

    def open_count_for_side(self, side: str) -> int:
        return sum(1 for p in self.positions.values() if p.side == side)

    def all_positions(self):
        return list(self.positions.values())

    def get_remembered_type(self, symbol: str, side: str) -> Optional[str]:
        return self.position_types.get(self._key(symbol, side))

    def _save_position_types(self):
        try:
            with open(config.POSITION_TYPES_FILE, "w", encoding="utf-8") as f:
                json.dump(self.position_types, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[state] Pozisyon turu kaydi yazilamadi: {e}")

    def _load_position_types(self):
        if os.path.exists(config.POSITION_TYPES_FILE):
            try:
                with open(config.POSITION_TYPES_FILE, "r", encoding="utf-8") as f:
                    self.position_types = json.load(f)
            except Exception as e:
                print(f"[state] Pozisyon turu kaydi okunamadi: {e}")
                self.position_types = {}

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

    def trades_for_symbol(self, symbol: str, trade_type: Optional[str] = None) -> list:
        trades = [t for t in self.trade_history if t.get("symbol") == symbol]
        if trade_type:
            trades = [t for t in trades if t.get("trade_type") == trade_type]
        return trades

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


def reconstruct_lose_exit(entry_price: float, sl_price: float, side: str, lose_exit_mult: float) -> float:
    """Yeniden baslatmada: lose exit borsada saklanan bir deger degildir
    (sadece guvenlik SL borsada gercek bir emir olarak durur), bu yuzden
    restart sonrasi acik bir pozisyon bulundugunda lose exit seviyesi
    guvenlik SL'den GERI HESAPLANIR.

    Ikisi de ayni oranli formulden turedigi icin bu hesap tam isabetlidir:
        SL mesafesi        = D * SL_DISTANCE_MULT
        lose exit mesafesi = D * lose_exit_mult   (Gold: 1.5, Silver: 1.0)
    yani:
        lose exit mesafesi = SL mesafesi * (lose_exit_mult / SL_DISTANCE_MULT)

    lose_exit_mult, pozisyonun turune (Gold/Silver) gore CAGIRAN TARAFTAN
    (strategy.py) verilir - bu yuzden dogru turun once bilinmesi/tahmin
    edilmesi gerekir.
    """
    if not sl_price:
        return 0.0
    sl_distance = abs(entry_price - sl_price)
    ratio = lose_exit_mult / config.SL_DISTANCE_MULT
    lose_exit_distance = sl_distance * ratio
    if side == "long":
        return entry_price - lose_exit_distance
    return entry_price + lose_exit_distance
