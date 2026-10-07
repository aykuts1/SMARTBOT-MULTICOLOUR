# -*- coding: utf-8 -*-
"""
bybit_client.py
------------------------
Bybit Futures (V5 API) ile konusan tum fonksiyonlar burada. Diger
dosyalar Bybit'e dogrudan istek atmaz, hep bu dosya uzerinden gecer.

ONEMLI NOT: Bybit'in API detaylari (parametre adlari, endpoint davranisi)
zamanla degisebilir. Canli paraya gecmeden ONCE mutlaka testnet
(BYBIT_TESTNET=true) ile denenmelidir.
"""

import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

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
        self._tick_size_cache = {}
        # Mum (kline) onbellegi: 1000 mumluk tam gecmis, mum araligi basina
        # (1 saatlik mumda saatte) bir kez yenilenir.
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

    def get_tradable_symbols(self) -> set:
        """Bybit'te su an islem goren (status=Trading) tum linear sembolleri
        dondurur. Coin listesini dogrulamak icin kullanilir."""
        symbols = set()
        cursor = None
        while True:
            kwargs = {"category": "linear", "limit": 1000}
            if cursor:
                kwargs["cursor"] = cursor
            resp = self.session.get_instruments_info(**kwargs)
            for item in resp["result"]["list"]:
                if item.get("status") == "Trading":
                    symbols.add(item["symbol"])
            cursor = resp["result"].get("nextPageCursor")
            if not cursor:
                break
        return symbols

    # ------------------------------------------------------------
    # PIYASA VERISI
    # ------------------------------------------------------------
    def get_klines(self, symbol: str) -> pd.DataFrame:
        """Son N mumu eskiden yeniye siralanmis olarak dondurur.
        Her cagrida borsaya gider (tam yenileme)."""
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

    def _current_kline_bucket(self) -> int:
        """Suanki 'mum dilimi' numarasi. KLINE_INTERVAL (dakika) degerine
        gore hesaplanir - yeni bir mum acildiginda bu sayi degisir."""
        interval_seconds = int(config.KLINE_INTERVAL) * 60
        return int(time.time() // interval_seconds)

    def current_bucket(self) -> int:
        """Disaridan kullanim icin (strategy.py): suanki mumun numarasi."""
        return self._current_kline_bucket()

    def _is_candle_of_bucket(self, df: pd.DataFrame, bucket: int) -> bool:
        """Cekilen verinin SON mumu gercekten 'bucket' numarali (suanki) mum
        mu? Saat basinda Bybit yeni mumu birkac yuz ms gec yayinlayabilir; o
        durumda son mum aslinda bir onceki mum olur ve 'kapanmis mum' hesabi
        kayardi. Bu kontrol onu engeller."""
        if df is None or len(df) == 0:
            return False
        try:
            start_ms = int(float(df.iloc[-1]["start_time"]))
        except Exception:
            return False
        interval_seconds = int(config.KLINE_INTERVAL) * 60
        return (start_ms // 1000) // interval_seconds == bucket

    def refresh_klines(self, symbols) -> list:
        """Mumu bu mum dilimi icin henuz yenilenmemis coinlerin mumunu PARALEL
        ceker. Basarisiz / henuz taze olmayan coinlerin listesini dondurur
        (bir sonraki dongude tekrar denenir)."""
        bucket = self._current_kline_bucket()
        stale = [s for s in symbols if self._candle_cache_bucket.get(s) != bucket]
        if not stale:
            return []

        def work(sym):
            try:
                df = self.get_klines(sym)
                if not self._is_candle_of_bucket(df, bucket):
                    return sym, None, "son mum henuz guncel degil"
                return sym, df, None
            except Exception as e:
                return sym, None, str(e)

        failed = []
        workers = max(1, min(config.KLINE_FETCH_WORKERS, len(stale)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for sym, df, err in ex.map(work, stale):
                if df is None:
                    failed.append(sym)
                    if err and "guncel degil" not in err:
                        print(f"[klines] {sym} mumu cekilemedi: {err}")
                else:
                    self._candle_cache[sym] = df
                    self._candle_cache_bucket[sym] = bucket
        return failed

    def get_cached_klines(self, symbol: str):
        """Bu mum dilimi icin taze onbellekteki mumlari dondurur; yoksa None.
        Son satir = henuz kapanmamis (canli) mum."""
        if self._candle_cache_bucket.get(symbol) == self._current_kline_bucket():
            return self._candle_cache.get(symbol)
        return None

    def get_klines_cached(self, symbol: str) -> pd.DataFrame:
        """Eski kodlarla (raporlar) uyum icin: son N mumu dondurur, son
        mumun close/high/low degerleri anlik fiyatla guncellenir."""
        df = self.get_cached_klines(symbol)
        if df is None:
            self.refresh_klines([symbol])
            df = self.get_cached_klines(symbol)
        if df is None:
            return self.get_klines(symbol)  # onbellege almadan, dogrudan
        self._update_cached_last_candle(symbol, self.get_last_price(symbol))
        return df

    def _update_cached_last_candle(self, symbol: str, last_price: float):
        """Onbellekteki son (henuz kapanmamis) mumun kapanisini anlik
        fiyatla gunceller; en yuksek/en dusuk degerleri de genisletir."""
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

    def get_all_last_prices(self) -> dict:
        """TUM linear sembollerin son fiyatini TEK istekle dondurur
        ({sembol: fiyat}). 40 coin icin saniyede 40 istek yerine 1 istek."""
        resp = self.session.get_tickers(category="linear")
        prices = {}
        for t in resp["result"]["list"]:
            lp = t.get("lastPrice")
            if lp:
                try:
                    prices[t["symbol"]] = float(lp)
                except ValueError:
                    continue
        return prices

    # ------------------------------------------------------------
    # HESAP BILGISI
    # ------------------------------------------------------------
    def get_total_equity(self) -> float:
        resp = self.session.get_wallet_balance(accountType="UNIFIED")
        return float(resp["result"]["list"][0]["totalEquity"])

    def _load_instrument_info(self, symbol: str):
        resp = self.session.get_instruments_info(category="linear", symbol=symbol)
        info = resp["result"]["list"][0]
        self._max_leverage_cache[symbol] = float(info["leverageFilter"]["maxLeverage"])
        self._qty_step_cache[symbol] = float(info["lotSizeFilter"]["qtyStep"])
        try:
            self._tick_size_cache[symbol] = float(info["priceFilter"]["tickSize"])
        except Exception:
            self._tick_size_cache[symbol] = 0.0

    def get_max_leverage(self, symbol: str) -> float:
        if symbol not in self._max_leverage_cache:
            self._load_instrument_info(symbol)
        return self._max_leverage_cache[symbol]

    def get_qty_step(self, symbol: str) -> float:
        if symbol not in self._qty_step_cache:
            self._load_instrument_info(symbol)
        return self._qty_step_cache.get(symbol, 0.001)

    def get_tick_size(self, symbol: str) -> float:
        if symbol not in self._tick_size_cache:
            self._load_instrument_info(symbol)
        return self._tick_size_cache.get(symbol, 0.0)

    def round_qty(self, symbol: str, qty: float) -> float:
        """Miktari borsanin izin verdigi adim (qtyStep) buyuklugune
        yuvarlar. Decimal kullanilir - float ile dogrudan carpip bolmek
        'Qty invalid' (ErrCode 10001) hatasina yol acabiliyordu."""
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
        """Emri Bybit'e gonderirken kullanilacak TEMIZ miktar string'i
        (sabit noktali, bilimsel gosterimsiz)."""
        step = self.get_qty_step(symbol)
        if step <= 0:
            return format(Decimal(str(qty)), "f")
        rounded = self._round_to_step(qty, step)
        return format(rounded, "f")

    def _format_price(self, symbol: str, price: float) -> str:
        """Fiyati borsanin fiyat adimina (tickSize) en yakin degere yuvarlar.
        (BTC/ETH gibi coinlerde adimin katı olmayan fiyatlar reddedilebilir.)"""
        tick = self.get_tick_size(symbol)
        if tick <= 0:
            return str(round(price, 6))
        tick_dec = Decimal(str(tick))
        steps = (Decimal(str(price)) / tick_dec).to_integral_value(rounding=ROUND_HALF_UP)
        rounded = steps * tick_dec
        if rounded <= 0:
            rounded = tick_dec
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
            stopLoss=self._format_price(symbol, sl_price),
            tpslMode="Full",
            slTriggerBy="LastPrice",
            positionIdx=position_idx,
        )
