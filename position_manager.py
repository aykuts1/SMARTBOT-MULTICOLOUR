"""
Pozisyon yonetimi
- Acik pozisyonlari takip et
- CE (Chandelier Exit) hesapla
- Breakeven kontrolu
- Cikis sinyali kontrolu
"""

from config import (
    BREAKEVEN_TRIGGER, CE_INITIAL_MULTIPLIER, CE_TIGHT_MULTIPLIER
)


class Position:
    """Tek bir pozisyonu temsil eder."""

    def __init__(self, symbol, side, qty, entry_price, sl_price):
        self.symbol = symbol
        self.side = side  # "LONG" veya "SHORT"
        self.qty = qty
        self.entry_price = entry_price
        self.sl_price = sl_price  # Borsa SL fiyati

        # CE takibi icin
        self.highest_price = entry_price  # LONG icin
        self.lowest_price = entry_price   # SHORT icin
        self.ce_price = None              # Hesaplanmis CE
        self.ce_initialized = False

        # Asama bayraklari
        self.breakeven_done = False  # Borsa SL girise cekildi mi
        self.ce_tightened = False    # CE 0.5 ATR'ye sikilasti mi

    def calculate_pnl_percent(self, current_price):
        """Su anki kar/zarar yuzdesini doner."""
        if self.side == "LONG":
            return ((current_price - self.entry_price) / self.entry_price) * 100
        else:  # SHORT
            return ((self.entry_price - current_price) / self.entry_price) * 100

    def update_extremes(self, current_price):
        """En yuksek/dusuk fiyati gunceller."""
        if current_price > self.highest_price:
            self.highest_price = current_price
        if current_price < self.lowest_price:
            self.lowest_price = current_price

    def calculate_ce(self, atr):
        """
        Chandelier Exit hesaplar.
        Kar < %1 ise: 2 ATR
        Kar >= %1 ise: 0.5 ATR
        """
        # Hangi multiplier kullanilacak
        if self.ce_tightened:
            multiplier = CE_TIGHT_MULTIPLIER
        else:
            multiplier = CE_INITIAL_MULTIPLIER

        if self.side == "LONG":
            new_ce = self.highest_price - (multiplier * atr)
            # CE sadece yukari hareket eder
            if self.ce_price is None or new_ce > self.ce_price:
                self.ce_price = new_ce
        else:  # SHORT
            new_ce = self.lowest_price + (multiplier * atr)
            # CE sadece asagi hareket eder
            if self.ce_price is None or new_ce < self.ce_price:
                self.ce_price = new_ce

        self.ce_initialized = True
        return self.ce_price

    def is_ce_triggered(self, current_price):
        """CE tetiklendi mi kontrol eder."""
        if not self.ce_initialized or self.ce_price is None:
            return False

        if self.side == "LONG":
            return current_price < self.ce_price
        else:  # SHORT
            return current_price > self.ce_price

    def should_breakeven(self, current_price):
        """Breakeven yapilmasi gerekiyor mu kontrol eder."""
        if self.breakeven_done:
            return False
        pnl = self.calculate_pnl_percent(current_price)
        return pnl >= (BREAKEVEN_TRIGGER * 100)


class PositionManager:
    """Tum acik pozisyonlari yonetir."""

    def __init__(self):
        self.positions = {}  # symbol -> Position

    def add_position(self, symbol, side, qty, entry_price, sl_price):
        """Yeni pozisyon ekler."""
        position = Position(symbol, side, qty, entry_price, sl_price)
        self.positions[symbol] = position
        return position

    def remove_position(self, symbol):
        """Pozisyonu siler."""
        if symbol in self.positions:
            del self.positions[symbol]

    def get_position(self, symbol):
        """Belirli sembol icin pozisyonu doner."""
        return self.positions.get(symbol)

    def has_position(self, symbol):
        """Bu sembolde acik pozisyon var mi."""
        return symbol in self.positions

    def get_all_positions(self):
        """Tum acik pozisyonlari liste olarak doner."""
        return list(self.positions.values())

    def count(self):
        """Acik pozisyon sayisi."""
        return len(self.positions)
