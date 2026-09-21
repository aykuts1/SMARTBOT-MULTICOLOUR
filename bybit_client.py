# -*- coding: utf-8 -*-
"""
bybit_client.py
----------------
Bybit Futures (V5 API) ile konusan tum fonksiyonlar burada. Diger
dosyalar Bybit'e dogrudan istek atmaz, hep bu dosya uzerinden gecer.

ONEMLI NOT: Bybit'in API detaylari (parametre adlari, endpoint davranisi)
zamanla degisebilir. Bu kod yazilirken guncel Bybit V5 dokumantasyonu
kontrol edilmistir, ama canli paraya gecmeden ONCE mutlaka testnet
(BYBIT_TESTNET=true) ile denenmelidir.
"""

import time
import pandas as pd
from pybit.unified_trading import HTTP

import config


class BybitClient:
    def __init__(self):
        self.session = HTTP(
            testnet=config.BYBIT_TESTNET,
            api_key=config.BYBIT_API_KEY,
            api_secret=config.BYBIT_API_SECRET,
        )
        self._max_leverage_cache = {}
        self._qty_step_cache = {}

    # ------------------------------------------------------------
    # BASLANGIC AYARLARI (bot her acildiginda bir kere calistirilir)
    # ------------------------------------------------------------
    def setup_account(self):
        """Hedge modu ve cross margin ayarlarini garanti eder.
        Zaten ayarliysa hata verebilir - bu durumlar yok sayilir."""
        try:
            self.session.switch_position_mode(category="linear", coin="USDT", mode=3)
        except Exception as e:
            print(f"[setup] Hedge modu ayari atlandi (muhtemelen zaten ayarli): {e}")

        try:
            self.session.set_margin_mode(setMarginMode=config.MARGIN_MODE)
        except Exception as e:
            print(f"[setup] Margin modu ayari atlandi (muhtemelen zaten ayarli): {e}")

    # ------------------------------------------------------------
    # PIYASA VERISI
    # ------------------------------------------------------------
    def get_klines(self, symbol: str) -> pd.DataFrame:
        """Son N mumu eskiden yeniye siralanmis olarak dondurur."""
        resp = self.session.get_kline(
            category="linear",
            symbol=symbol,
            interval=config.KLINE_INTERVAL,
            limit=config.KLINE_LOOKBACK,
        )
        rows = resp["result"]["list"]  # Bybit yeniden eskiye verir
        rows = list(reversed(rows))  # eskiden yeniye cevir

        df = pd.DataFrame(rows, columns=[
            "start_time", "open", "high", "low", "close", "volume", "turnover"
        ])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        return df

    def get_last_price(self, symbol: str) -> float:
        resp = self.session.get_tickers(category="linear", symbol=symbol)
        return float(resp["result"]["list"][0]["lastPrice"])

    # ------------------------------------------------------------
    # HESAP BILGISI
    # ------------------------------------------------------------
    def get_total_equity(self) -> float:
        resp = self.session.get_wallet_balance(accountType="UNIFIED")
        return float(resp["result"]["list"][0]["totalEquity"])

    def get_max_leverage(self, symbol: str) -> float:
        if symbol in self._max_leverage_cache:
            return self._max_leverage_cache[symbol]
        resp = self.session.get_instruments_info(category="linear", symbol=symbol)
        info = resp["result"]["list"][0]
        max_lev = float(info["leverageFilter"]["maxLeverage"])
        qty_step = float(info["lotSizeFilter"]["qtyStep"])
        self._max_leverage_cache[symbol] = max_lev
        self._qty_step_cache[symbol] = qty_step
        return max_lev

    def get_qty_step(self, symbol: str) -> float:
        if symbol not in self._qty_step_cache:
            self.get_max_leverage(symbol)  # ikisini de cache'ler
        return self._qty_step_cache.get(symbol, 0.001)

    def round_qty(self, symbol: str, qty: float) -> float:
        """Miktari, coin'in izin verdigi adima (step) yuvarlar.
        Kayan nokta artiklarini (ornegin 146.20000000000002) da temizler,
        yoksa Bybit 'Qty invalid' diye emri reddediyor."""
        step = self.get_qty_step(symbol)
        if step <= 0:
            return qty
        steps = int(qty / step)
        rounded = steps * step
        decimals = self._decimals_for_step(step)
        rounded = round(rounded, decimals)
        return max(round(step, decimals), rounded)

    @staticmethod
    def _decimals_for_step(step: float) -> int:
        step_str = f"{step:.10f}".rstrip("0")
        if "." in step_str:
            return len(step_str.split(".")[1])
        return 0

    # ------------------------------------------------------------
    # KALDIRAC
    # ------------------------------------------------------------
    def set_leverage(self, symbol: str, leverage: float):
        lev_str = str(leverage)
        try:
            self.session.set_leverage(
                category="linear", symbol=symbol,
                buyLeverage=lev_str, sellLeverage=lev_str,
            )
        except Exception as e:
            # "leverage not modified" gibi hatalar zararsizdir
            print(f"[leverage] {symbol} kaldirac ayari notu: {e}")

    # ------------------------------------------------------------
    # POZISYONLAR
    # ------------------------------------------------------------
    def get_open_positions(self) -> list:
        """Tum coinlerdeki acik pozisyonlari dondurur (hem long hem short)."""
        resp = self.session.get_positions(category="linear", settleCoin="USDT")
        positions = []
        for p in resp["result"]["list"]:
            size = float(p.get("size", 0) or 0)
            if size > 0:
                positions.append(p)
        return positions

    # ------------------------------------------------------------
    # EMIRLER
    # ------------------------------------------------------------
    def open_market_position(self, symbol: str, side: str, qty: float, position_idx: int):
        """side: 'Buy' (long acmak) veya 'Sell' (short acmak)"""
        return self.session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType=config.ORDER_TYPE,
            qty=str(qty),
            positionIdx=position_idx,
        )

    def close_market_position(self, symbol: str, side: str, qty: float, position_idx: int):
        """Pozisyonu kapatmak icin ters yonde reduceOnly emir.
        side: kapatilacak pozisyon long ise 'Sell', short ise 'Buy' verilmeli."""
        return self.session.place_order(
            category="linear",
            symbol=symbol,
            side=side,
            orderType=config.ORDER_TYPE,
            qty=str(qty),
            positionIdx=position_idx,
            reduceOnly=True,
        )

    def set_stop_loss(self, symbol: str, sl_price: float, position_idx: int):
        """Pozisyona bagli gercek SL emri (guvenlik agi)."""
        return self.session.set_trading_stop(
            category="linear",
            symbol=symbol,
            stopLoss=str(round(sl_price, 6)),
            tpslMode="Full",
            slTriggerBy="LastPrice",
            positionIdx=position_idx,
        )
