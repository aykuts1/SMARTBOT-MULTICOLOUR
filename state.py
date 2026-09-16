"""
state.py
--------
state.json icin kalici durum yonetimi. Her yazma islemi ATOMIK yapilir
(once gecici dosyaya yazilir, sonra os.replace ile degistirilir) -- bu
sayede bot yazma sirasinda cokerse dosya bozulmaz.

Bot her yeniden basladiginda (main.py) bu dosyadaki pozisyonlar Bybit'teki
gercek acik pozisyonlarla karsilastirilip senkronize edilir (bkz. main.py
-> reconcile_positions).
"""

import json
import os
import tempfile
import threading


class State:
    def __init__(self, path: str = "state.json"):
        self.path = path
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {"positions": {}, "trade_history": [],
                    "last_report_12h": None,
                    "last_report_24h": None, "last_report_weekly": None}
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
            data.setdefault("trade_history", [])
            return data

    def _save(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path)) or "."
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state_tmp_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, default=str)
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # -- pozisyonlar -----------------------------------------------------
    def add_position(self, position: dict) -> None:
        with self._lock:
            self._data["positions"][position["symbol"]] = position
            self._save()

    def remove_position(self, symbol: str) -> None:
        with self._lock:
            self._data["positions"].pop(symbol, None)
            self._save()

    def get_position(self, symbol: str) -> dict | None:
        return self._data["positions"].get(symbol)

    def all_positions(self) -> dict:
        return dict(self._data["positions"])

    def update_position_field(self, symbol: str, field: str, value) -> None:
        with self._lock:
            if symbol in self._data["positions"]:
                self._data["positions"][symbol][field] = value
                self._save()

    def replace_all_positions(self, positions: dict) -> None:
        """Reconciliation sirasinda tum pozisyon listesini borsayla esitlemek icin."""
        with self._lock:
            self._data["positions"] = positions
            self._save()

    # -- kapanan islem gecmisi (raporlar icin) ----------------------------
    def log_closed_trade(self, trade: dict) -> None:
        with self._lock:
            self._data["trade_history"].append(trade)
            # asiri buyumesin diye son 5000 islemle sinirla
            self._data["trade_history"] = self._data["trade_history"][-5000:]
            self._save()

    def get_trades_since(self, ts: float) -> list:
        return [t for t in self._data["trade_history"] if t.get("closed_at", 0) >= ts]

    def all_trades(self) -> list:
        return list(self._data["trade_history"])

    # -- rapor zaman damgalari -------------------------------------------
    def get_last_report_time(self, key: str):
        return self._data.get(f"last_report_{key}")

    def set_last_report_time(self, key: str, ts: float) -> None:
        with self._lock:
            self._data[f"last_report_{key}"] = ts
            self._save()
