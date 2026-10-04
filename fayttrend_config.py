# -*- coding: utf-8 -*-
"""
fayttrend_config.py
-------------------
FAYTTREND botunun tum ayarlari burada.

API anahtarlari ve Telegram bilgileri .env dosyasindan okunur (guvenlik
icin kod icine yazilmaz). .env.example dosyasini kopyalayip .env yap ve
kendi bilgilerini gir.

STRATEJI: Faytterro Bands (alt bant / ust bant). Fiyat alt banda degerse
long, ust banda degerse short. Karsi yondeki pozisyon kapatilir.
"""

import os
from dotenv import load_dotenv

load_dotenv()  # .env dosyasini okur ve ortam degiskenlerine yukler

# ============================================================
# BYBIT API BILGILERI (ortam degiskenlerinden / .env'den okunur)
# ============================================================
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_TESTNET = os.getenv("BYBIT_TESTNET", "false").lower() == "true"

# ============================================================
# TELEGRAM BILGILERI
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================================
# COIN LISTESI (12 coin)
# ============================================================
COINS = [
    "TIAUSDT", "TAOUSDT", "ADAUSDT", "ENAUSDT",
    "INJUSDT", "APTUSDT", "NEARUSDT", "ARBUSDT", "HYPEUSDT", "ATOMUSDT",
    "TRUMPUSDT", "WLDUSDT",
]

# ============================================================
# MUM (KLINE) AYARLARI
# ============================================================
KLINE_INTERVAL = "60"       # 1 saatlik mum (dakika cinsinden)
KLINE_LOOKBACK = 300

# ============================================================
# FAYTTERRO BANDS AYARLARI
# ============================================================
# Kaynak fiyat: hlc3 = (yuksek + dusuk + kapanis) / 3  (indicators.py'de sabit)
BANDS_LENGTH = 5            # Pine'daki "lenght" ayari (orijinal kodda 50, burada 5)
BANDS_STDDEV_MULT = 2.0     # Pine'daki "StdDev" ayari

# ============================================================
# LOSE EXIT / GUVENLIK SL
# ============================================================
# Islem acilirken KARSI BANDA olan mesafe (D) olculur:
#   long  -> D = ust bant - giris fiyati
#   short -> D = giris fiyati - alt bant
# Lose exit  : girisin D x LOSE_EXIT_DISTANCE_MULT kadar TERS yonunde (sabit)
# Guvenlik SL: girisin D x SL_DISTANCE_MULT kadar TERS yonunde (sabit,
#              borsaya gercek emir olarak konur)
LOSE_EXIT_DISTANCE_MULT = 1.0
SL_DISTANCE_MULT = 2.0

# ============================================================
# STAKE TABLOSU (toplam varliga gore sabit tutar, USDT)
# ============================================================
# Her satir: (varligin alt siniri, stake). Sinir degerler UST bareme
# girer: ornegin varlik tam 25 ise 25-50 satirinin stake'i (0.50) uygulanir.
STAKE_TABLE = [
    (0, 0.25),
    (25, 0.50),
    (50, 1.0),
    (75, 1.50),
    (100, 2.0),
    (150, 3.0),
    (200, 4.0),
    (300, 6.0),
    (400, 8.0),
    (500, 10.0),
    (600, 12.0),
    (800, 16.0),
    (1000, 20.0),
    (1300, 25.0),
    (1700, 35.0),
    (2000, 40.0),
    (2500, 50.0),
]

# ============================================================
# ISLEM / RISK AYARLARI
# ============================================================
# Bir coin'de ayni anda en fazla 1 LONG + 1 SHORT olabilir (borsanin
# hedge modu kapasitesiyle birebir - bkz. state.py'nin pozisyon
# anahtarlamasi: "SYMBOL_side").
# Toplamda ise LONG ve SHORT icin AYRI AYRI limit var: en fazla 12 long
# VE en fazla 12 short ayni anda acik olabilir.
MAX_POSITIONS_PER_SIDE = 12

# Bybit'in USDT perpetual islemler icin platform genelindeki minimum
# emir DEGERI (notional, qty*fiyat cinsinden). Hesaplanan islem hacmi
# bunun altinda kalirsa islem acilmadan once atlanir.
MIN_ORDER_VALUE_USDT = 5.0
MARGIN_MODE = "REGULAR_MARGIN"
ORDER_TYPE = "Market"

# ============================================================
# DONGU / POLLING AYARI
# ============================================================
POLL_INTERVAL_SECONDS = 1

EQUITY_SNAPSHOT_INTERVAL_SECONDS = 60
EQUITY_HISTORY_RETENTION_DAYS = 35

# Bot, kendi acik pozisyon kayitlarini borsayla bu araliklarla (saniye)
# IKI YONLU karsilastirir.
RECONCILE_INTERVAL_SECONDS = 60

# ============================================================
# RAPOR ZAMANLAMASI
# ============================================================
REPORT_SCHEDULE = {
    "Z": 12 * 3600,
    "X": 24 * 3600,
    "Q": 7 * 24 * 3600,
}

# ============================================================
# DOSYA YOLLARI (yeniden baslatma / gecmis kayitlari icin)
# ============================================================
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TRADE_HISTORY_FILE = os.path.join(STATE_DIR, "trade_history.json")
EQUITY_HISTORY_FILE = os.path.join(STATE_DIR, "equity_history.json")
SYSTEM_EVENTS_FILE = os.path.join(STATE_DIR, "system_events.json")
LOG_FILE = os.path.join(STATE_DIR, "bot.log")

os.makedirs(STATE_DIR, exist_ok=True)
