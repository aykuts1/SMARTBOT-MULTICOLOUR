import os
import time
import threading
from pybit.unified_trading import WebSocket
from logger_setup import get_logger

log = get_logger("websocket")


class WebSocketClient:
    def __init__(self, on_tick, on_candle_close):
        self.api_key = os.environ.get("BYBIT_API_KEY", "")
        self.api_secret = os.environ.get("BYBIT_API_SECRET", "")
        self.testnet = os.environ.get("BYBIT_TESTNET", "false").lower() == "true"

        self.on_tick = on_tick
        self.on_candle_close = on_candle_close

        self.ws = None
        self.connected = False
        self.reconnect_delay = 1
        self.max_reconnect_delay = 60
        self.last_data_time = 0
        self.disconnect_time = None
        self._stop_event = threading.Event()
        self._symbols = []

    def start(self, symbols):
        self._symbols = symbols
        self._connect(symbols)

    def _connect(self, symbols):
        # Eski bağlantı varsa önce kapat
        if self.ws is not None:
            try:
                self.ws.exit()
            except Exception:
                pass
            self.ws = None

        try:
            self.ws = WebSocket(
                testnet=self.testnet,
                channel_type="linear"
            )

            for symbol in symbols:
                self.ws.ticker_stream(
                    symbol=symbol,
                    callback=self._handle_ticker
                )

            for symbol in symbols:
                self.ws.kline_stream(
                    interval=30,
                    symbol=symbol,
                    callback=self._handle_kline
                )

            self.connected = True
            self.reconnect_delay = 1
            self.last_data_time = time.time()

            if self.disconnect_time:
                duration = time.time() - self.disconnect_time
                self.disconnect_time = None
                log.info("Baglanti kuruldu (kesinti: %.0f sn)", duration)

            log.info("WebSocket baglandi (%d coin)", len(symbols))

        except Exception as e:
            log.error("WebSocket baglanti hatasi: %s", e)
            self.connected = False
            self._schedule_reconnect()

    def _handle_ticker(self, message):
        try:
            if "data" not in message:
                return

            data = message["data"]
            symbol = data.get("symbol", "")
            last_price = data.get("lastPrice", "")

            if symbol and last_price:
                price = float(last_price)
                self.last_data_time = time.time()

                if self.on_tick:
                    self.on_tick(symbol, price)

        except Exception as e:
            log.error("Ticker isleme hatasi: %s", e)

    def _handle_kline(self, message):
        try:
            if "data" not in message:
                return

            data_list = message["data"]
            for data in data_list:
                symbol = data.get("symbol", "")
                confirm = data.get("confirm", False)

                if confirm and symbol:
                    candle = {
                        "timestamp": int(data["start"]),
                        "open": float(data["open"]),
                        "high": float(data["high"]),
                        "low": float(data["low"]),
                        "close": float(data["close"]),
                        "volume": float(data["volume"])
                    }
                    self.last_data_time = time.time()

                    if self.on_candle_close:
                        self.on_candle_close(symbol, candle)

                    log.debug("%s mum kapandi: O=%.4f H=%.4f L=%.4f C=%.4f",
                              symbol, candle["open"], candle["high"],
                              candle["low"], candle["close"])

        except Exception as e:
            log.error("Kline isleme hatasi: %s", e)

    def _schedule_reconnect(self):
        if self._stop_event.is_set():
            return

        self.disconnect_time = self.disconnect_time or time.time()
        log.warning("Yeniden baglanma: %.0f sn sonra", self.reconnect_delay)

        def reconnect():
            if not self._stop_event.is_set():
                self._connect(self._symbols)

        timer = threading.Timer(self.reconnect_delay, reconnect)
        timer.daemon = True
        timer.start()

        self.reconnect_delay = min(
            self.reconnect_delay * 2,
            self.max_reconnect_delay
        )

    def check_health(self):
        if time.time() - self.last_data_time > 30:
            log.warning("WebSocket veri akisi kesilmis, yeniden baglaniliyor")
            self.connected = False
            self.disconnect_time = self.disconnect_time or time.time()
            try:
                if self.ws:
                    self.ws.exit()
            except Exception:
                pass
            self._connect(self._symbols)
            return False
        return True

    def stop(self):
        self._stop_event.set()
        try:
            if self.ws:
                self.ws.exit()
        except Exception:
            pass
        self.connected = False
        log.info("WebSocket durduruldu")

    @property
    def is_connected(self):
        return self.connected and (time.time() - self.last_data_time < 30)

    @property
    def seconds_since_last_data(self):
        return time.time() - self.last_data_time if self.last_data_time > 0 else -1
