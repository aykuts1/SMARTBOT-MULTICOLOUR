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
from decimal import Decimal, ROUND_DOWN

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
        # Mum (kline) onbellegi: 300 mumluk tam gecmis mum araligi basina
        # (ornegin 1 saatlik mumda saatte) bir yenilenir, aradaki her
        # cagrida sadece anlik fiyatla son mum guncellenir.
        self._candle_cache = {}
        self._candle_cache_bucket = {}

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
        """Son N mumu eskiden yeniye siralanmis olarak dondurur.
        Her cagrida borsaya gider (tam yenileme). Ana dongude bunun
        yerine get_klines_cached() kullanilir - bu fonksiyon sadece
        onun tam yenileme yapmasi gerektiginde ve baslangicta cagrilir."""
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

    def get_klines_cached(self, symbol: str) -> pd.DataFrame:
        """get_klines ile ayni seklide (son N mum, eskiden yeniye) bir
        dataframe dondurur, ama her saniye borsaya gitmez:

          - Mum araligi degistiginde (KLINE_INTERVAL'e gore yeni "mum
            dilimi"ne girildiginde - ornegin 1 saatlik mumda her saat
            basi) 300 mumluk tam gecmis yeniden cekilir.
          - Aradaki her cagrida (saniyede bir) sadece anlik fiyat cekilir;
            bu fiyat, henuz kapanmamis son mumun close/high/low
            degerlerini gunceller (ATR hesabi high/low'a da ihtiyac
            duydugu icin ikisi de anlik olarak genisletilir).

        Boylece saniyelik hassasiyet aynen korunurken, agir "300 mum
        indir" istegi saniyede degil mum araligi basina bir kez yapilmis
        olur. Cache mantigi buradadir cunku bu dosya, Bybit'ten cekilen
        verinin kendisiyle ilgilenen tek yerdir (max_leverage_cache /
        qty_step_cache ile ayni desen)."""
        bucket = self._current_kline_bucket()

        if symbol not in self._candle_cache or self._candle_cache_bucket.get(symbol) != bucket:
            self._candle_cache[symbol] = self.get_klines(symbol)
            self._candle_cache_bucket[symbol] = bucket
        else:
            last_price = self.get_last_price(symbol)
            self._update_cached_last_candle(symbol, last_price)

        return self._candle_cache[symbol]

    def _current_kline_bucket(self) -> int:
        """Suanki 'mum dilimi' numarasi. KLINE_INTERVAL (dakika) degerine
        gore hesaplanir - yeni bir mum acildiginda bu sayi degisir, boylece
        get_klines_cached() tam yenileme yapmasi gerektigini anlar."""
        interval_seconds = int(config.KLINE_INTERVAL) * 60
        return int(time.time() // interval_seconds)

    def _update_cached_last_candle(self, symbol: str, last_price: float):
        """Onbellekteki son (henuz kapanmamis) mumun kapanisini anlik
        fiyatla gunceller; en yuksek/en dusuk degerleri de gerceklestigi
        gibi genisletir."""
        df = self._candle_cache[symbol]
        last_idx = df.index[-1]
        df.loc[last_idx, "close"] = last_price
        if last_price > df.loc[last_idx, "high"]:
            df.loc[last_idx, "high"] = last_price
        if last_price < df.loc[last_idx, "low"]:
            df.loc[last_idx, "low"] = last_price

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
        """Miktari borsanin izin verdigi adim (qtyStep) buyuklugune
        yuvarlar. Decimal kullanilir - float ile dogrudan carpip bolmek
        (ornegin int(qty/step)*step) 94.30000000000001 gibi 'kirli'
        ondalikli sonuclar uretebiliyordu, bu da Bybit'ten 'Qty invalid'
        (ErrCode 10001) hatasi aldiriyordu (adim buyuklugunden fazla
        ondalik basamak icerdigi icin)."""
        step = self.get_qty_step(symbol)
        if step <= 0:
            return qty
        rounded = self._round_to_step(qty, step)
        return float(rounded)

    def _round_to_step(self, value: float, step: float) -> Decimal:
        step_dec = Decimal(str(step))
        value_dec = Decimal(str(value))
        steps = (value_dec / step_dec).to_integral_value(rounding=ROUND_DOWN)
        rounded = steps * step_dec
        if rounded < step_dec:
            rounded = step_dec
        return rounded

    def _format_qty(self, symbol: str, qty: float) -> str:
        """Emri Bybit'e gonderirken kullanilacak TEMIZ miktar string'i.
        round_qty ile ayni Decimal mantigini kullanir ve sabit noktali
        (bilimsel gosterim olmayan) bir string dondurur - boylece uzun
        ondalikli float string'leri (ve bunlarin yol actigi 'Qty invalid'
        hatasi) borsaya asla gitmez. round_qty zaten cagrilmis bir deger
        icin bile guvenlidir (tekrar yuvarlamak zararsizdir)."""
        step = self.get_qty_step(symbol)
        if step <= 0:
            return format(Decimal(str(qty)), "f")
        rounded = self._round_to_step(qty, step)
        return format(rounded, "f")

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
            qty=self._format_qty(symbol, qty),
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
            qty=self._format_qty(symbol, qty),
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
