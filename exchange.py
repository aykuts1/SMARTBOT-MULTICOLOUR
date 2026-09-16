"""
exchange.py
-----------
Bybit V5 (Unified Trading Account, linear/USDT perpetual) API'siyle tum
iletisim burada toplanir. MAINNET sabit -- testnet parametresi yok/kapali.

Gerekli ortam degiskenleri (Railway'de zaten tanimli):
  BYBIT_API_KEY
  BYBIT_API_SECRET

NOT: Bu dosya canli borsa baglantisi gerektirdigi icin bu ortamda (sandbox)
calistirilarak test EDILEMEDI. pybit'in resmi V5 metod/parametre isimleri
kullanildi. Ilk canli calistirmada -- ozellikle set_margin_mode /
switch_position_mode cagrilarinda -- hesap turune (Unified/Classic) gore
kucuk farklar cikabilir; bu yuzden bu cagrilar try/except ile sarilip
hata Telegram'a ve loglara dusecek sekilde yazildi, bot bu yuzden CRASH
OLMAYACAK ama sen ilk calistirmada Telegram loglarini/Railway loglarini
mutlaka izlemelisin.
"""

import os
import time
import logging

from pybit.unified_trading import HTTP

logger = logging.getLogger("exchange")

CATEGORY = "linear"
KLINE_INTERVAL_1H = "60"


class Exchange:
    def __init__(self):
        api_key = os.environ["BYBIT_API_KEY"]
        api_secret = os.environ["BYBIT_API_SECRET"]
        self.client = HTTP(api_key=api_key, api_secret=api_secret, testnet=False)

        self._instrument_cache: dict[str, dict] = {}
        self._leverage_set: set[str] = set()
        self._margin_mode_set = False

    # -- kurulum -----------------------------------------------------------
    def ensure_account_margin_mode(self) -> None:
        """Hesap capinda CROSS (REGULAR_MARGIN) moda gecirir. Sadece bir kez calisir."""
        if self._margin_mode_set:
            return
        try:
            self.client.set_margin_mode(setMarginMode="REGULAR_MARGIN")
        except Exception as e:
            logger.warning("set_margin_mode basarisiz (muhtemelen zaten REGULAR_MARGIN): %s", e)
        self._margin_mode_set = True

    def ensure_leverage_and_margin_mode(self, symbol: str, leverage: int) -> None:
        if symbol in self._leverage_set:
            return
        self.ensure_account_margin_mode()
        try:
            self.client.switch_position_mode(category=CATEGORY, symbol=symbol, mode=0)  # one-way
        except Exception as e:
            logger.info("switch_position_mode (%s): %s", symbol, e)
        try:
            self.client.set_leverage(category=CATEGORY, symbol=symbol,
                                      buyLeverage=str(leverage), sellLeverage=str(leverage))
        except Exception as e:
            logger.info("set_leverage (%s): %s", symbol, e)
        self._leverage_set.add(symbol)

    def get_instrument_info(self, symbol: str) -> dict:
        if symbol in self._instrument_cache:
            return self._instrument_cache[symbol]
        resp = self.client.get_instruments_info(category=CATEGORY, symbol=symbol)
        item = resp["result"]["list"][0]
        lot = item["lotSizeFilter"]
        info = {
            "qty_step": float(lot["qtyStep"]),
            "min_qty": float(lot["minOrderQty"]),
        }
        self._instrument_cache[symbol] = info
        return info

    # -- piyasa verisi -------------------------------------------------------
    def get_klines(self, symbol: str, limit: int = 300):
        """Ascending (eskiden yeniye) siralanmis OHLC DataFrame doner (start = mum acilis zamani, ms)."""
        import pandas as pd
        resp = self.client.get_kline(category=CATEGORY, symbol=symbol,
                                      interval=KLINE_INTERVAL_1H, limit=limit)
        rows = resp["result"]["list"]
        rows = list(reversed(rows))  # Bybit yeni->eski verir, biz eski->yeni istiyoruz
        df = pd.DataFrame(rows, columns=["start", "open", "high", "low", "close", "volume", "turnover"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        df["start"] = df["start"].astype("int64")
        return df[["start", "open", "high", "low", "close"]]

    def get_all_tickers(self) -> dict:
        """Tum linear semboller icin TEK cagriyla anlik fiyat -- 3 sn dongusu icin."""
        resp = self.client.get_tickers(category=CATEGORY)
        result = {}
        for item in resp["result"]["list"]:
            result[item["symbol"]] = float(item["lastPrice"])
        return result

    def get_last_price(self, symbol: str) -> float:
        resp = self.client.get_tickers(category=CATEGORY, symbol=symbol)
        return float(resp["result"]["list"][0]["lastPrice"])

    # -- hesap ---------------------------------------------------------------
    def get_available_balance(self) -> float:
        resp = self.client.get_wallet_balance(accountType="UNIFIED", coin="USDT")
        coin_info = resp["result"]["list"][0]["coin"][0]
        return float(coin_info.get("availableToWithdraw") or coin_info.get("walletBalance") or 0.0)

    def get_open_positions(self) -> list[dict]:
        resp = self.client.get_positions(category=CATEGORY, settleCoin="USDT")
        positions = []
        for p in resp["result"]["list"]:
            size = float(p["size"])
            if size == 0:
                continue
            positions.append({
                "symbol": p["symbol"],
                "side": "long" if p["side"] == "Buy" else "short",
                "qty": size,
                "entry_price": float(p["avgPrice"]),
            })
        return positions

    # -- emirler --------------------------------------------------------------
    def place_market_order(self, symbol: str, order_side: str, qty: float,
                            reduce_only: bool = False, stop_loss_price: float | None = None) -> dict:
        kwargs = dict(
            category=CATEGORY, symbol=symbol, side=order_side,
            orderType="Market", qty=str(qty), reduceOnly=reduce_only,
        )
        if stop_loss_price is not None and not reduce_only:
            # Guvenlik agi: bot cokse/offline kalsa bile borsa tarafinda gercek
            # bir stop-loss emri dursun diye (Loss Exit seviyesi). Hareketli TP
            # borsa emriyle konamaz -- o her zaman bot canliyken yonetilir.
            kwargs["stopLoss"] = str(round(stop_loss_price, 6))

        for attempt in range(3):
            try:
                resp = self.client.place_order(**kwargs)
                break
            except Exception as e:
                logger.warning("place_order deneme %d basarisiz (%s): %s", attempt + 1, symbol, e)
                time.sleep(1.5)
        else:
            raise RuntimeError(f"place_order 3 denemede de basarisiz: {symbol}")

        order_id = resp["result"]["orderId"]
        avg_price = self._resolve_avg_fill_price(symbol, order_id)
        return {"order_id": order_id, "avg_price": avg_price}

    def _resolve_avg_fill_price(self, symbol: str, order_id: str, retries: int = 5) -> float:
        """Market emri aninda dolar ama ortalama doluş fiyati icin kisa bir bekleme/sorgu gerekir."""
        for _ in range(retries):
            try:
                resp = self.client.get_order_history(category=CATEGORY, symbol=symbol, orderId=order_id)
                items = resp["result"]["list"]
                if items and float(items[0].get("avgPrice", 0) or 0) > 0:
                    return float(items[0]["avgPrice"])
            except Exception as e:
                logger.info("avg fill fiyati sorgusu basarisiz: %s", e)
            time.sleep(0.5)
        # son care: son fiyati kullan
        return self.get_last_price(symbol)
