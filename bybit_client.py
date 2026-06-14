import os
import math
from pybit.unified_trading import HTTP


class BybitClient:
    def __init__(self):
        self.client = HTTP(
            testnet=False,
            api_key=os.environ["BYBIT_API_KEY"],
            api_secret=os.environ["BYBIT_API_SECRET"],
        )

    # ------------------------------------------------------------------ #
    #  Piyasa verisi                                                       #
    # ------------------------------------------------------------------ #

    def get_qty_step(self, symbol: str) -> float:
        resp = self.client.get_instruments_info(category="linear", symbol=symbol)
        lot = resp["result"]["list"][0]["lotSizeFilter"]
        return float(lot["qtyStep"])

    @staticmethod
    def round_qty(raw: float, step: float) -> float:
        precision = len(str(step).rstrip("0").split(".")[-1]) if "." in str(step) else 0
        return round(math.floor(raw / step) * step, precision)

    def get_klines(self, symbol: str, interval: str, limit: int = 200) -> list:
        resp = self.client.get_kline(
            category="linear",
            symbol=symbol,
            interval=interval,
            limit=limit,
        )
        return resp["result"]["list"]

    def get_ticker(self, symbol: str) -> dict:
        resp = self.client.get_tickers(category="linear", symbol=symbol)
        return resp["result"]["list"][0]

    def get_balance(self) -> float:
        resp = self.client.get_wallet_balance(accountType="UNIFIED")
        coins = resp["result"]["list"][0]["coin"]
        for c in coins:
            if c["coin"] == "USDT":
                return float(c["walletBalance"])
        return 0.0

    # ------------------------------------------------------------------ #
    #  Kaldıraç & margin                                                   #
    # ------------------------------------------------------------------ #

    def set_leverage(self, symbol: str, leverage: int):
        try:
            self.client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
        except Exception:
            pass  # Zaten ayarlıysa hata gelir, geçilebilir

    def set_cross_margin(self, symbol: str):
        try:
            self.client.switch_margin_mode(
                category="linear",
                symbol=symbol,
                tradeMode=0,  # 0 = Cross
                buyLeverage="1",
                sellLeverage="1",
            )
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Emir gönderme                                                       #
    # ------------------------------------------------------------------ #

    def place_market_order(
        self,
        symbol: str,
        side: str,      # "Buy" veya "Sell"
        qty: float,
        sl_price: float,
        reduce_only: bool = False,
    ) -> dict:
        params = dict(
            category="linear",
            symbol=symbol,
            side=side,
            orderType="Market",
            qty=str(qty),
            timeInForce="GTC",
            reduceOnly=reduce_only,
            stopLoss=str(round(sl_price, 8)),
            slTriggerBy="MarkPrice",
            positionIdx=1 if side == "Buy" else 2,
        )
        resp = self.client.place_order(**params)
        return resp["result"]

    def place_market_close(self, symbol: str, side: str, qty: float) -> dict:
        close_side = "Buy" if side == "Sell" else "Sell"
        resp = self.client.place_order(
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=str(qty),
            timeInForce="GTC",
            reduceOnly=True,
            positionIdx=2 if close_side == "Buy" else 1,
        )
        return resp["result"]

    def cancel_sl(self, symbol: str):
        try:
            self.client.cancel_all_orders(category="linear", symbol=symbol, orderFilter="StopOrder")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Pozisyon sorgulama                                                  #
    # ------------------------------------------------------------------ #

    def get_position(self, symbol: str) -> dict | None:
        resp = self.client.get_positions(category="linear", symbol=symbol)
        positions = resp["result"]["list"]
        for p in positions:
            if float(p["size"]) > 0:
                return p
        return None
