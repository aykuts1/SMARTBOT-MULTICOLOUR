import os
from dotenv import load_dotenv

load_dotenv()

# ============ BYBIT API ============
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")
BYBIT_TESTNET = False  # Mainnet

# ============ TELEGRAM ============
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ============ COIN LISTESI ============
SYMBOLS = [
    # Majörler
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT",
    "ADAUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT",
    # Orta katman
    "SUIUSDT", "APTUSDT", "NEARUSDT", "INJUSDT", "TONUSDT",
    "1000PEPEUSDT", "TRXUSDT", "DOTUSDT", "MATICUSDT", "ATOMUSDT"
]

# ============ STRATEJI PARAMETRELERI ============
TIMEFRAME = "15"          # 15 dakikalık mum
SCAN_INTERVAL = 900       # Giriş tarama: 15 dk (saniye)
EXIT_CHECK_INTERVAL = 60  # Çıkış tarama: 60 saniye

# ============ BOLLINGER BANDS ============
BB_PERIOD = 20
BB_STD = 2

# ============ RSI ============
RSI_PERIOD = 14
RSI_LONG_THRESHOLD = 35   # RSI < 35 -> LONG
RSI_SHORT_THRESHOLD = 65  # RSI > 65 -> SHORT

# ============ ADX ============
ADX_PERIOD = 14
ADX_THRESHOLD = 25        # ADX < 25 -> Yatay piyasa

# ============ ATR ============
ATR_PERIOD = 14

# ============ POZISYON YONETIMI ============
LEVERAGE = 10
STAKE_PERCENT = 0.20      # Bakiyenin %20'si
MAX_POSITIONS = 4         # Max es zamanli pozisyon

# ============ RISK YONETIMI ============
INITIAL_SL_PERCENT = 0.01      # %1 baslangic SL
BREAKEVEN_TRIGGER = 0.01       # %1 karda breakeven
CE_INITIAL_MULTIPLIER = 2.0    # 2 ATR baslangic
CE_TIGHT_MULTIPLIER = 0.5      # 0.5 ATR sikilasmis
