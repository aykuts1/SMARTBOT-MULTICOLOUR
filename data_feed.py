import time
import threading
import logging
from bybit_client import BybitClient
from band_calculator import BandCalculator

logger = logging.getLogger(__name__)


class DataFeed:
    """
    Her 5 saniyede Bybit'ten veri çeker.
    Tüm thread'ler bu ortak nesneyi okur, kimse ayrıca API çağrısı yapmaz.

    data[symbol] = {
        "price":  float,
        "bands":  { "ema", "atr", "upper": [...], "lower": [...] },
        "ce":     { "ce_long", "ce_short" },
        "klines": [...],   # ham 30dk mumlar
    }
    """

    def __init__(self, config: dict, client: BybitClient):
        self.config = config
        self.client = client
        self.calculator = BandCalculator(
            ema_period=config["band"]["ema_period"],
            atr_period=config["band"]["atr_period"],
            band_levels=config["band"]["band_levels"],
        )
        self.ce_multiplier = config["chandelier_exit"]["atr_multiplier"]
        self.ce_period = config["chandelier_exit"]["atr_period"]
        self.interval = config["data_feed"]["interval_seconds"]
        self.timeframe = config["band"]["timeframe"]
        self.symbols = config["coins"]

        white_cfg = config.get("white_ecosystem", {})
        stoch_cfg = white_cfg.get("stochastic", {})
        macd_cfg  = white_cfg.get("macd", {})
        self.stoch_k_length = stoch_cfg.get("k_length", 50)
        self.stoch_k_smooth = stoch_cfg.get("k_smooth", 21)
        self.stoch_d_smooth = stoch_cfg.get("d_smooth", 8)
        self.macd_fast   = macd_cfg.get("fast", 50)
        self.macd_slow   = macd_cfg.get("slow", 21)
        self.macd_signal = macd_cfg.get("signal", 9)

        self.data: dict = {}
        self._last_candle_times: dict = {}  # symbol -> son görülen kapanmış mum zamanı
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ #
    #  Public API                                                          #
    # ------------------------------------------------------------------ #

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, name="DataFeed", daemon=True)
        self._thread.start()
        logger.info("DataFeed başlatıldı.")

    def stop(self):
        self._running = False

    def get(self, symbol: str) -> dict | None:
        with self._lock:
            return self.data.get(symbol)

    def get_price(self, symbol: str) -> float | None:
        d = self.get(symbol)
        return d["price"] if d else None

    def get_bands(self, symbol: str) -> dict | None:
        d = self.get(symbol)
        return d["bands"] if d else None

    def get_ce(self, symbol: str) -> dict | None:
        d = self.get(symbol)
        return d["ce"] if d else None

    def get_stoch(self, symbol: str) -> dict | None:
        d = self.get(symbol)
        return d["stoch"] if d else None

    def get_macd(self, symbol: str) -> dict | None:
        d = self.get(symbol)
        return d["macd"] if d else None

    # ------------------------------------------------------------------ #
    #  İç döngü                                                           #
    # ------------------------------------------------------------------ #

    def _loop(self):
        while self._running:
            start = time.time()
            for symbol in self.symbols:
                try:
                    self._refresh(symbol)
                except Exception as e:
                    logger.warning(f"DataFeed hata [{symbol}]: {e}")
            elapsed = time.time() - start
            sleep_time = max(0.0, self.interval - elapsed)
            time.sleep(sleep_time)

    def _refresh(self, symbol: str):
        klines = self.client.get_klines(symbol, self.timeframe, limit=200)

        # klines[0] = anlık açık mum, klines[1] = son kapanmış mum
        price             = float(klines[0][4])
        last_closed_time  = int(klines[1][0])   if len(klines) > 1 else 0
        last_closed_price = float(klines[1][4]) if len(klines) > 1 else price

        bands = self.calculator.calculate(klines)
        ce    = self.calculator.calculate_ce(klines, self.ce_multiplier, self.ce_period)

        # Stoch ve MACD sadece yeni mum kapandığında hesaplanır (30dk'da bir)
        if last_closed_time != self._last_candle_times.get(symbol):
            self._last_candle_times[symbol] = last_closed_time
            stoch = self.calculator.calculate_stochastic(
                klines, self.stoch_k_length, self.stoch_k_smooth, self.stoch_d_smooth
            )
            macd = self.calculator.calculate_macd(
                klines, self.macd_fast, self.macd_slow, self.macd_signal
            )
        else:
            existing = self.data.get(symbol, {})
            stoch = existing.get("stoch")
            macd  = existing.get("macd")

        with self._lock:
            self.data[symbol] = {
                "price": price,
                "bands": bands,
                "ce": ce,
                "klines": klines,
                "stoch": stoch,
                "macd": macd,
                "last_closed_candle_time": last_closed_time,
                "last_closed_price": last_closed_price,
            }
