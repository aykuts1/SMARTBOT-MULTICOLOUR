# -*- coding: utf-8 -*-
"""
config.py
---------
Botun tum ayarlari burada. Bir seyi degistirmek istersen (coin listesi,
gosterge ayarlari, yuzdeler vb.) hep bu dosyaya bak.

API anahtarlari ve Telegram bilgileri .env dosyasindan okunur (guvenlik
icin kod icine yazilmaz). .env.example dosyasini kopyalayip .env yap ve
kendi bilgilerini gir.
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
# COIN LISTESI
# ============================================================
# Bybit'teki USDT perpetual sembol adlariyla (ARBUSDT gibi)
COINS = ["ARBUSDT", "INJUSDT", "NEARUSDT", "APTUSDT", "ENAUSDT"]

# ============================================================
# MUM (KLINE) AYARLARI
# ============================================================
# Zaman dilimi: 1 saatlik mum (senin belirttigin gibi).
# Bybit kline interval degerleri dakika cinsindendir -> 1 saat = "60"
# Farkli bir zaman dilimi istersen sadece burayi degistir.
# Bybit kline interval degerleri: "1","3","5","15","30","60","120","240", vb (dakika)
KLINE_INTERVAL = "60"

# Gosterge hesaplamasi icin hafizada tutulacak mum sayisi
# (T3, 6 katmanli EMA oldugu icin gecmise biraz daha fazla veri lazim)
KLINE_LOOKBACK = 300

# ============================================================
# TILSON T3 AYARLARI
# ============================================================
T3_VOLUME_FACTOR = 0.1   # "b" / factor
T3_PERIOD = 3            # EMA periyodu
T3_BAND_ATR_MULT = 0.1   # T3 ustune/altina cekilen bandin ATR carpani

# ============================================================
# MERKEZ CIZGISI (eskiden ALMA) AYARLARI
# ============================================================
MERKEZ_LENGTH = 7
MERKEZ_OFFSET = 0.85   # ALMA orijinal varsayilani (ayri belirtilmedi)
MERKEZ_SIGMA = 6        # ALMA orijinal varsayilani (ayri belirtilmedi)
MERKEZ_BAND_ATR_MULT = 0.8  # Merkez ustune/altina cekilen bandin ATR carpani

# ============================================================
# ATR AYARI
# ============================================================
# Konusulmadi -> piyasada standart olan 14 periyot kullaniliyor.
ATR_PERIOD = 14

# ============================================================
# POZISYON BUYUKLUGU / KALDIRAC FORMULU AYARLARI
# ============================================================
LOSE_EXIT_DISTANCE_MULT = 2.0     # giris-merkez bant mesafesinin kac kati lose exit olsun
EQUITY_PERCENT_PER_TRADE = 0.08   # toplam varligin yuzde kaci bir islem icin ayrilsin (%8)
SL_EXTRA_PERCENT = 0.01           # SL, lose exit'in giris fiyatina gore yuzde kaci daha uzaginda olsun (%1)

# ============================================================
# ISLEM / RISK AYARLARI
# ============================================================
MAX_TOTAL_POSITIONS = 10   # toplam ac aik pozisyon limiti (tum coinler toplami)
MARGIN_MODE = "REGULAR_MARGIN"  # Cross margin (Bybit V5 hesap capinda ayar)
ORDER_TYPE = "Market"

# ============================================================
# DONGU / POLLING AYARI
# ============================================================
POLL_INTERVAL_SECONDS = 1  # her saniye veri cekilir

# ============================================================
# RAPOR ZAMANLAMASI
# ============================================================
# Ilk rapor 00:00'da, sonrasi periyodik.
REPORT_SCHEDULE = {
    "Z": 12 * 3600,   # 12 saatte bir - yuzeysel
    "X": 24 * 3600,   # 24 saatte bir - detayli
    "Q": 7 * 24 * 3600,  # haftalik - cok detayli
}

# ============================================================
# DOSYA YOLLARI (yeniden baslatma / gecmis kayitlari icin)
# ============================================================
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TRADE_HISTORY_FILE = os.path.join(STATE_DIR, "trade_history.json")
LOG_FILE = os.path.join(STATE_DIR, "bot.log")

os.makedirs(STATE_DIR, exist_ok=True)
