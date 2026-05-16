"""
Bybit v5 API wrapper using pybit unified_trading.
Wraps account, market, and order endpoints needed by the bot.
"""
import time
from typing import List, Dict, Optional, Tuple
from pybit.unified_trading import HTTP

import config


class BybitClient:
    def __init__(self):
        self.session = HTTP(
            testnet=config.BYBIT_TESTNET,
            api_key=config.BYBIT_API_KEY,
            api_secret=config.BYBIT_API_SECRET,
            recv_window=10000,
        )
        # Symbol metadata cache: {symbol: {"qty_step": float, "min_qty": float, "tick_size": float}}
        self._instruments: Dict[str, Dict[str, float]] = {}

    # =====================================================
    # WALLET / BALANCE
    # =====================================================
    def get_total_balance_usdt(self) -> float:
        """
        Total wallet balance in USDT (including converted value of other coins).
        For Unified account, this is the total equity.
        """
        resp = self.session.get_wallet_balance(accountType=config.ACCOUNT_TYPE)
        if resp.get("retCode") != 0:
            raise RuntimeError(f"get_wallet_balance failed: {resp}")
        accounts = resp["result"]["list"]
        if not accounts:
            return 0.0
        # totalEquity in USDT for Unified account
        total = accounts[0].get("totalEquity", "0")
        try:
            return float(total)
        except (ValueError, TypeError):
            return 0.0

    # =====================================================
    # MARKET DATA
    # =====================================================
    def get_klines(self, symbol: str, interval: str = "5", limit: int = 300) -> List[Dict]:
        """
        Returns list of klines OLDEST FIRST. Each kline is a dict with keys:
        start, open, high, low, close, volume, turnover.
        Bybit returns newest first; we reverse.
        """
        resp = self.session.get_kline(
            category=config.CATEGORY,
            symbol=symbol,
            interval=interval,
            limit=limit,
        )
        if resp.get("retCode") != 0:
            raise RuntimeError(f"get_kline failed for {symbol}: {resp}")
        raw = resp["result"]["list"]
        # raw entries: [start, open, high, low, close, volume, turnover]
        klines = []
        for r in reversed(raw):
            klines.append({
                "start": int(r[0]),
                "open": float(r[1]),
                "high": float(r[2]),
                "low": float(r[3]),
                "close": float(r[4]),
                "volume": float(r[5]),
                "turnover": float(r[6]),
            })
        return klines

    def get_last_price(self, symbol: str) -> float:
        """Latest mark/last price."""
        resp = self.session.get_tickers(category=config.CATEGORY, symbol=symbol)
        if resp.get("retCode") != 0:
            raise RuntimeError(f"get_tickers failed for {symbol}: {resp}")
        items = resp["result"]["list"]
        if not items:
            raise RuntimeError(f"No ticker for {symbol}")
        return float(items[0]["lastPrice"])

    # =====================================================
    # INSTRUMENT INFO (qty step, min qty, tick size)
    # =====================================================
    def get_instrument_info(self, symbol: str) -> Dict[str, float]:
        """
        Fetch and cache symbol trading rules.
        Returns dict with qty_step, min_qty, tick_size.
        """
        if symbol in self._instruments:
            return self._instruments[symbol]
        resp = self.session.get_instruments_info(category=config.CATEGORY, symbol=symbol)
        if resp.get("retCode") != 0:
            raise RuntimeError(f"get_instruments_info failed for {symbol}: {resp}")
        items = resp["result"]["list"]
        if not items:
            raise RuntimeError(f"No instrument info for {symbol}")
        info = items[0]
        lot = info["lotSizeFilter"]
        price = info["priceFilter"]
        meta = {
            "qty_step": float(lot["qtyStep"]),
            "min_qty": float(lot["minOrderQty"]),
            "tick_size": float(price["tickSize"]),
        }
        self._instruments[symbol] = meta
        return meta

    @staticmethod
    def round_step(value: float, step: float) -> float:
        """Floor value to nearest step."""
        if step <= 0:
            return value
        return (int(value / step)) * step

    @staticmethod
    def format_qty(qty: float, step: float) -> str:
        """Format quantity as string respecting step decimals."""
        s = f"{step:.10f}".rstrip("0")
        if "." in s:
            decimals = len(s.split(".")[1])
        else:
            decimals = 0
        return f"{qty:.{decimals}f}"

    @staticmethod
    def format_price(price: float, tick: float) -> str:
        """Format price as string respecting tick decimals."""
        s = f"{tick:.10f}".rstrip("0")
        if "." in s:
            decimals = len(s.split(".")[1])
        else:
            decimals = 0
        return f"{price:.{decimals}f}"

    # =====================================================
    # LEVERAGE / MARGIN MODE
    # =====================================================
    def set_leverage(self, symbol: str, leverage: int) -> None:
        """
        Set leverage for both long and short.
        Silently ignore 'leverage not modified' errors (retCode 110043).
        """
        try:
            resp = self.session.set_leverage(
                category=config.CATEGORY,
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            if resp.get("retCode") not in (0, 110043):
                # 110043 = leverage not modified
                raise RuntimeError(f"set_leverage failed: {resp}")
        except Exception as e:
            msg = str(e)
            if "110043" in msg or "not modified" in msg.lower():
                return
            raise

    def set_isolated_margin(self, symbol: str, leverage: int) -> None:
        """
        Switch symbol to isolated margin mode.
        Silently ignore if already in isolated mode.
        """
        try:
            resp = self.session.switch_margin_mode(
                category=config.CATEGORY,
                symbol=symbol,
                tradeMode=1,  # 0 = cross, 1 = isolated
                buyLeverage=str(leverage),
                sellLeverage=str(leverage),
            )
            if resp.get("retCode") not in (0, 110026):
                # 110026 = mode not modified
                raise RuntimeError(f"switch_margin_mode failed: {resp}")
        except Exception as e:
            msg = str(e)
            if "110026" in msg or "not modified" in msg.lower():
                return
            # Don't crash on margin mode issues - log and continue
            print(f"[WARN] set_isolated_margin {symbol}: {e}")

    # =====================================================
    # ORDERS
    # =====================================================
    def place_market_order(
        self,
        symbol: str,
        side: str,             # "Buy" or "Sell"
        qty: float,
        stop_loss_price: Optional[float] = None,
        reduce_only: bool = False,
    ) -> Dict:
        """
        Place a market order. If stop_loss_price given, attach SL.
        Returns API response.
        """
        info = self.get_instrument_info(symbol)
        qty_str = self.format_qty(qty, info["qty_step"])

        params = {
            "category": config.CATEGORY,
            "symbol": symbol,
            "side": side,
            "orderType": "Market",
            "qty": qty_str,
            "positionIdx": 0,   # one-way mode
            "reduceOnly": reduce_only,
        }
        if stop_loss_price is not None and not reduce_only:
            sl_str = self.format_price(stop_loss_price, info["tick_size"])
            params["stopLoss"] = sl_str
            params["slTriggerBy"] = "LastPrice"
            params["tpslMode"] = "Full"

        resp = self.session.place_order(**params)
        if resp.get("retCode") != 0:
            raise RuntimeError(f"place_order failed for {symbol}: {resp}")
        return resp

    def update_stop_loss(self, symbol: str, sl_price: float) -> None:
        """
        Update existing position's stop loss.
        """
        info = self.get_instrument_info(symbol)
        sl_str = self.format_price(sl_price, info["tick_size"])
        resp = self.session.set_trading_stop(
            category=config.CATEGORY,
            symbol=symbol,
            stopLoss=sl_str,
            slTriggerBy="LastPrice",
            tpslMode="Full",
            positionIdx=0,
        )
        if resp.get("retCode") != 0:
            raise RuntimeError(f"set_trading_stop failed for {symbol}: {resp}")

    def close_position(self, symbol: str, side: str, qty: float) -> Dict:
        """
        Close an open position by sending opposite market order with reduceOnly.
        `side` here is the original position side ("Buy" or "Sell").
        """
        opposite = "Sell" if side == "Buy" else "Buy"
        return self.place_market_order(symbol, opposite, qty, reduce_only=True)

    # =====================================================
    # POSITIONS
    # =====================================================
    def get_position(self, symbol: str) -> Optional[Dict]:
        """
        Get current position for symbol. Returns None if no open position.
        """
        resp = self.session.get_positions(category=config.CATEGORY, symbol=symbol)
        if resp.get("retCode") != 0:
            raise RuntimeError(f"get_positions failed for {symbol}: {resp}")
        items = resp["result"]["list"]
        for p in items:
            size = float(p.get("size", "0") or 0)
            if size > 0:
                return p
        return None

    def get_open_positions(self) -> List[Dict]:
        """Get all open positions across the account."""
        resp = self.session.get_positions(category=config.CATEGORY, settleCoin="USDT")
        if resp.get("retCode") != 0:
            raise RuntimeError(f"get_positions (all) failed: {resp}")
        items = resp["result"]["list"]
        return [p for p in items if float(p.get("size", "0") or 0) > 0]
