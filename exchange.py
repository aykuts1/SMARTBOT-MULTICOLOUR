"""
Bybit API islemleri
- Bakiye okuma
- Mum verisi cekme
- Pozisyon acma/kapama
- Stop Loss yonetimi
"""

import time
from pybit.unified_trading import HTTP
from config import (
    BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET, LEVERAGE
)


class BybitExchange:
    def __init__(self):
        self.client = HTTP(
            testnet=BYBIT_TESTNET,
            api_key=BYBIT_API_KEY,
            api_secret=BYBIT_API_SECRET
        )

    # ============ BAKIYE ============
    def get_balance(self, retries=5):
        """USDT bakiyesini doner. Hata olursa retries kadar dener."""
        for attempt in range(retries):
            try:
                result = self.client.get_wallet_balance(
                    accountType="UNIFIED",
                    coin="USDT"
                )
                if result["retCode"] == 0:
                    coins = result["result"]["list"][0]["coin"]
                    for c in coins:
                        if c["coin"] == "USDT":
                            balance = float(c["walletBalance"])
                            return balance
                time.sleep(2)
            except Exception as e:
                print(f"[get_balance] Deneme {attempt+1} hata: {e}")
                time.sleep(2)
        return 0.0

    # ============ MUM VERISI ============
    def get_klines(self, symbol, interval="15", limit=200):
        """Mum verisini doner. Rate limit icin sleep eklenmis."""
        try:
            time.sleep(1)  # Rate limit korumasi
            result = self.client.get_kline(
                category="linear",
                symbol=symbol,
                interval=interval,
                limit=limit
            )
            if result["retCode"] == 0:
                klines = result["result"]["list"]
                # Bybit veriyi tersten doner (yeniden eskiye), duzeltiyoruz
                klines.reverse()
                return klines
            return None
        except Exception as e:
            print(f"[get_klines] {symbol} hata: {e}")
            return None

    # ============ ANLIK FIYAT ============
    def get_current_price(self, symbol):
        """Anlik fiyati doner."""
        try:
            result = self.client.get_tickers(
                category="linear",
                symbol=symbol
            )
            if result["retCode"] == 0:
                return float(result["result"]["list"][0]["lastPrice"])
            return None
        except Exception as e:
            print(f"[get_current_price] {symbol} hata: {e}")
            return None

    # ============ KALDIRACI AYARLA ============
    def set_leverage(self, symbol, leverage=LEVERAGE):
        """Kaldiraci ayarlar."""
        try:
            self.client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
            return True
        except Exception as e:
            # Kaldirac zaten ayarliysa hata vermeden gec
            if "leverage not modified" in str(e).lower():
                return True
            print(f"[set_leverage] {symbol} hata: {e}")
            return False

    # ============ SEMBOL BILGISI ============
    def get_symbol_info(self, symbol):
        """Sembol icin min islem boyutu, ondalik basamak vs. doner."""
        try:
            result = self.client.get_instruments_info(
                category="linear",
                symbol=symbol
            )
            if result["retCode"] == 0:
                info = result["result"]["list"][0]
                return {
                    "min_qty": float(info["lotSizeFilter"]["minOrderQty"]),
                    "qty_step": float(info["lotSizeFilter"]["qtyStep"]),
                    "tick_size": float(info["priceFilter"]["tickSize"])
                }
            return None
        except Exception as e:
            print(f"[get_symbol_info] {symbol} hata: {e}")
            return None

    # ============ MIKTAR YUVARLA ============
    def round_qty(self, qty, qty_step):
        """Miktari step'e gore yuvarla."""
        import math
        return math.floor(qty / qty_step) * qty_step

    def round_price(self, price, tick_size):
        """Fiyati tick'e gore yuvarla."""
        import math
        return round(math.floor(price / tick_size) * tick_size, 8)

    # ============ POZISYON AC ============
    def open_position(self, symbol, side, qty, sl_price=None):
        """
        Market emir ile pozisyon acar.
        side: "Buy" (LONG) veya "Sell" (SHORT)
        sl_price: Borsa SL fiyati
        """
        try:
            params = {
                "category": "linear",
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": str(qty),
                "positionIdx": 0  # One-way mode
            }
            if sl_price:
                params["stopLoss"] = str(sl_price)

            result = self.client.place_order(**params)
            if result["retCode"] == 0:
                return result["result"]
            else:
                print(f"[open_position] {symbol} hata: {result['retMsg']}")
                return None
        except Exception as e:
            print(f"[open_position] {symbol} hata: {e}")
            return None

    # ============ POZISYON KAPAT ============
    def close_position(self, symbol, side, qty):
        """
        Market emir ile pozisyon kapatir.
        side: Acik pozisyonun TERSI olmali (LONG icin "Sell", SHORT icin "Buy")
        """
        try:
            result = self.client.place_order(
                category="linear",
                symbol=symbol,
                side=side,
                orderType="Market",
                qty=str(qty),
                reduceOnly=True,
                positionIdx=0
            )
            if result["retCode"] == 0:
                return result["result"]
            else:
                print(f"[close_position] {symbol} hata: {result['retMsg']}")
                return None
        except Exception as e:
            print(f"[close_position] {symbol} hata: {e}")
            return None

    # ============ STOP LOSS GUNCELLE ============
    def update_stop_loss(self, symbol, sl_price):
        """Acik pozisyonun stop loss fiyatini gunceller."""
        try:
            result = self.client.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss=str(sl_price),
                positionIdx=0
            )
            if result["retCode"] == 0:
                return True
            else:
                print(f"[update_stop_loss] {symbol} hata: {result['retMsg']}")
                return False
        except Exception as e:
            print(f"[update_stop_loss] {symbol} hata: {e}")
            return False

    # ============ STOP LOSS IPTAL ============
    def cancel_stop_loss(self, symbol):
        """Acik pozisyonun stop loss emrini iptal eder (0 yaparak)."""
        try:
            result = self.client.set_trading_stop(
                category="linear",
                symbol=symbol,
                stopLoss="0",
                positionIdx=0
            )
            return result["retCode"] == 0
        except Exception as e:
            print(f"[cancel_stop_loss] {symbol} hata: {e}")
            return False

    # ============ ACIK POZISYONLARI GETIR ============
    def get_open_positions(self):
        """Tum acik pozisyonlari doner."""
        try:
            result = self.client.get_positions(
                category="linear",
                settleCoin="USDT"
            )
            if result["retCode"] == 0:
                positions = result["result"]["list"]
                # Sadece miktari 0'dan buyuk olanlari al
                return [p for p in positions if float(p["size"]) > 0]
            return []
        except Exception as e:
            print(f"[get_open_positions] hata: {e}")
            return []
