"""
Position manager - in-memory tracking of open positions and exit state.

For each open position we track:
  - entry price, side, qty, leverage
  - atr at entry (for ATR-based trailing)
  - current stage (0, 1, 2)
  - current CE level (None until Stage 1 activates)
  - current SL price on the exchange
  - peak/trough price since entry (for CE)
  - last candle start (to detect reverse signal once per candle)
"""
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class Position:
    symbol: str
    side: str                # "Buy" (long) or "Sell" (short)
    entry_price: float
    qty: float
    stake_usdt: float        # USDT margin used
    leverage: int
    atr_at_entry: float
    open_time: float

    # Stage tracking
    stage: int = 0           # 0 = entry SL only, 1 = CE active, 2 = SL moved to profit
    ce_level: Optional[float] = None        # Current Chandelier Exit level (price)
    current_sl: float = 0.0                 # Current SL price on the exchange
    extreme_price: float = 0.0              # Highest high (long) or lowest low (short) since entry

    # Misc
    last_reverse_check_candle: int = 0      # candle.start timestamp of last reverse check

    def update_extreme(self, current_price: float) -> None:
        """Update peak/trough since entry."""
        if self.side == "Buy":
            if current_price > self.extreme_price:
                self.extreme_price = current_price
        else:
            if current_price < self.extreme_price:
                self.extreme_price = current_price

    def compute_ce(self, trail_atr_mult: float) -> float:
        """Compute Chandelier Exit level based on current extreme."""
        offset = self.atr_at_entry * trail_atr_mult
        if self.side == "Buy":
            return self.extreme_price - offset
        else:
            return self.extreme_price + offset

    def profit_pct(self, current_price: float) -> float:
        """Price-based profit percentage (not PnL %, just price move)."""
        if self.side == "Buy":
            return (current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - current_price) / self.entry_price

    def profit_in_atr(self, current_price: float) -> float:
        """Price-based profit measured in ATR units."""
        if self.atr_at_entry <= 0:
            return 0.0
        if self.side == "Buy":
            return (current_price - self.entry_price) / self.atr_at_entry
        else:
            return (self.entry_price - current_price) / self.atr_at_entry

    def ce_hit(self, current_price: float) -> bool:
        """Has the current price touched/crossed the CE level?"""
        if self.ce_level is None:
            return False
        if self.side == "Buy":
            return current_price <= self.ce_level
        else:
            return current_price >= self.ce_level


class PositionManager:
    def __init__(self):
        self._positions: Dict[str, Position] = {}

    def open(self, position: Position) -> None:
        self._positions[position.symbol] = position

    def close(self, symbol: str) -> Optional[Position]:
        return self._positions.pop(symbol, None)

    def get(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def all(self) -> Dict[str, Position]:
        return dict(self._positions)

    def count(self) -> int:
        return len(self._positions)

    def has(self, symbol: str) -> bool:
        return symbol in self._positions
