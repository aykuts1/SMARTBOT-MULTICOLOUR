# -*- coding: utf-8 -*-
"""
config.py
-------------------
FAYTTREND botunun tum ayarlari burada. (Q-Trend surumu)

API anahtarlari ve Telegram bilgileri .env dosyasindan okunur (guvenlik
icin kod icine yazilmaz). .env.example dosyasini kopyalayip .env yap ve
kendi bilgilerini gir.

STRATEJI: Q-Trend (ana cizgi + Gold/Silver).
  - Fiyat Silver'a degerse LONG, Gold'a degerse SHORT.
  - Kar Alma: ana cizgi (canli, her saniye kontrol edilir).
  - Stop Loss: pozisyon acilinca borsaya GERCEK bir SL emri konur. Seviyesi,
    giris ile Bybit'in verdigi LIKIT fiyati arasindaki yolun %80'indedir
    (likitten onceki guvenlik cizgisi). Likit fiyati degistikce (capraz
    marj) bot, her dakika stop'u yeni seviyeye tasir.
  - Stake: futures cuzdan bakiyesinin %1'i (acik islemlerdeki gecici
    kar/zarar sayilmaz, sadece kapanan islemler bakiyeyi degistirir).
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
# COIN LISTESI (50 coin taranir)
# ============================================================
# Bot acilirken bu isimleri Bybit'in canli listesiyle karsilastirir;
# Bybit'te bulunmayan / islem gormeyen sembolleri listeden cikarir ve
# Telegram'dan haber verir (bkz. main.py).
COINS = [
    # ilk 12
    "TIAUSDT", "TAOUSDT", "ADAUSDT", "ENAUSDT",
    "INJUSDT", "APTUSDT", "NEARUSDT", "ARBUSDT", "HYPEUSDT", "ATOMUSDT",
    "TRUMPUSDT", "WLDUSDT",
    # hacmi yuksek 17
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "BNBUSDT",
    "SUIUSDT", "LINKUSDT", "AVAXUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT",
    "AAVEUSDT", "ONDOUSDT", "OPUSDT", "FARTCOINUSDT", "TRXUSDT",
    # ek 9
    "TONUSDT", "HBARUSDT", "UNIUSDT", "FILUSDT", "ETCUSDT",
    "WIFUSDT", "PENGUUSDT", "SEIUSDT", "RENDERUSDT",
    # ek 2
    "XLMUSDT", "POLUSDT",
    # kullanicinin ekledigi 5
    "CHZUSDT", "1000PEPEUSDT", "SHIB1000USDT", "ZECUSDT", "AKEUSDT",
    # ek 5
    "ICPUSDT", "FETUSDT", "STXUSDT", "LDOUSDT", "JUPUSDT",
]

# ============================================================
# MUM (KLINE) AYARLARI
# ============================================================
KLINE_INTERVAL = "60"       # 1 saatlik mum (dakika cinsinden)
# Q-Trend'in ana cizgisi gecmise bagimli (merdiven gibi) ilerler. Grafikteki
# degere olabildigince yaklasmak icin Bybit'in izin verdigi en fazla mum
# (1000) cekilir.
KLINE_LOOKBACK = 1000
KLINE_FETCH_WORKERS = 8     # saat basinda 50 coinin mumunu paralel cekmek icin

# ============================================================
# Q-TREND AYARLARI (Pine kodundaki varsayilanlarla ayni)
# ============================================================
QT_TREND_PERIOD = 200       # "Trend period"
QT_ATR_PERIOD = 14          # "ATR Period"
QT_ATR_MULT = 1.0           # "ATR Multiplier" (ana cizginin basamak buyuklugu)

GOLD_MULT = 1.0             # Gold cizgisi   = ana cizgi + GOLD_MULT   x ATR
SILVER_MULT = 1.0           # Silver cizgisi = ana cizgi - SILVER_MULT x ATR
GOLD_LOSS_MULT = 2.0        # Gold loss      = ana cizgi + GOLD_LOSS_MULT   x ATR (sadece bilgi/rapor amacli)
SILVER_LOSS_MULT = 2.0      # Silver loss    = ana cizgi - SILVER_LOSS_MULT x ATR (sadece bilgi/rapor amacli)

# True : Pine gostergesi canli mumda nasil davraniyorsa aynen oyle (ana cizgi
#        mum icinde, anlik fiyata gore bir basamak oynayabilir; "repaint").
# False: Ana cizgi sadece mum KAPANINCA kayar; mum icinde cizgiler sabit kalir.
QT_INTRABAR_STEP = True

# ============================================================
# CIKIS / RISK AYARLARI
# ============================================================
# Stake: futures (UNIFIED) cuzdan bakiyesinin yuzde kaci her islemde
# kullanilsin. Bakiye = totalWalletBalance: acik islemlerdeki gecici kar/zarar
# DAHIL DEGIL, ana (Funding) cuzdan DAHIL DEGIL.
STAKE_PERCENT = 1.0

# Stop Loss yerlesimi: giris fiyati ile Bybit'in verdigi likit fiyati arasi
# mesafenin bu orani kadar ilerisine konur (0.8 = yolun %80'i, yani likitten
# onceki mesafenin %20'si guvenlik payi olarak kalir).
STOP_PLACEMENT_FRACTION = 0.8

# Stop'un tetiklenme fiyati turu. Bybit likidasyonu MarkPrice'a gore yaptigi
# icin ayni fiyat turu kullanilir.
STOP_TRIGGER_BY = "MarkPrice"

# Pozisyon acildiktan sonra Bybit'ten likit fiyatini okumak icin deneme
# sayisi ve denemeler arasi bekleme (saniye).
LIQ_FETCH_RETRIES = 5
LIQ_FETCH_WAIT_SECONDS = 0.6

# ============================================================
# ISLEM / LIMIT AYARLARI
# ============================================================
# Her coinde ayni anda sadece 1 islem. Toplamda (long + short birlikte)
# en fazla bu kadar acik islem.
MAX_OPEN_POSITIONS = 15
# Eski raporlarla (telegram_bot.py) uyum icin takma ad - ayni degeri tasir.
MAX_POSITIONS_PER_SIDE = MAX_OPEN_POSITIONS

# Bybit'in USDT perpetual islemler icin minimum emir DEGERI (notional).
MIN_ORDER_VALUE_USDT = 5.0
# Borsanin minimum lot adimi yuzunden gercek hacim hedeflenen hacmin bu
# kadar katindan fazla cikacaksa (ornegin dusuk varlikta BTC/ETH) islem
# acilmaz - aksi halde risk planin cok ustune cikar.
MAX_LOT_OVERSHOOT = 2.0

MARGIN_MODE = "REGULAR_MARGIN"
ORDER_TYPE = "Market"

# ============================================================
# DONGU / POLLING AYARI
# ============================================================
POLL_INTERVAL_SECONDS = 1

EQUITY_SNAPSHOT_INTERVAL_SECONDS = 60
EQUITY_HISTORY_RETENTION_DAYS = 35

# Bot, kendi acik pozisyon kayitlarini borsayla bu araliklarla (saniye)
# IKI YONLU karsilastirir. Ayni turda acik pozisyonlarin Stop Loss seviyesi
# de (likit fiyati degistigi icin) yeniden hesaplanip guncellenir.
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
OPEN_POSITIONS_FILE = os.path.join(STATE_DIR, "open_positions.json")
LOG_FILE = os.path.join(STATE_DIR, "bot.log")

os.makedirs(STATE_DIR, exist_ok=True)
