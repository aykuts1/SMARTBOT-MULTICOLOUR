# -*- coding: utf-8 -*-
"""
config.py
---------
Botun tum ayarlari burada. Bir seyi degistirmek istersen (coin listesi,
gosterge ayarlari, yuzdeler vb.) hep bu dosyaya bak.

API anahtarlari ve Telegram bilgileri .env dosyasindan okunur (guvenlik
icin kod icine yazilmaz). .env.example dosyasini kopyalayip .env yap ve
kendi bilgilerini gir.

NOT (koklu guncelleme): Bu dosyadaki eski Tilson T3 / Merkez (ALMA)
gosterge ayarlari tamamen kaldirildi. Strateji artik Supertrend +
Entry/Exit cizgileri uzerine kurulu. Eski botun sabit yuzdeli "lose
exit" ayarlari da kaldirildi - yerine yeni, Entry-Exit mesafesine
oranli bir lose exit geldi (asagida LOSE_EXIT_DISTANCE_MULT).
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
    "TIAUSDT", "TAOUSDT", "TRUMPUSDT", "ADAUSDT", "WLDUSDT", "ENAUSDT",
    "INJUSDT", "APTUSDT", "NEARUSDT", "ARBUSDT", "HYPEUSDT", "ATOMUSDT",
]

# ============================================================
# MUM (KLINE) AYARLARI
# ============================================================
# 1 saatlik mum. Bybit kline interval degerleri dakika cinsinden -> "60"
KLINE_INTERVAL = "60"

# Gosterge hesaplamasi icin hafizada tutulacak mum sayisi
KLINE_LOOKBACK = 300

# ============================================================
# SUPERTREND AYARLARI (yeni strateji temeli)
# ============================================================
SUPERTREND_ATR_PERIOD = 10      # ATR Period
SUPERTREND_MULTIPLIER = 2.0     # ATR Multiplier

# Supertrend'in ana cizgisinden (up/dn), fiyata dogru kaydirilmis iki cizgi.
# Ikisi de ayni ATR'yi (yukaridaki Supertrend ATR'si) kullanir.
ENTRY_LINE_ATR_MULT = 1.2       # "Entry cizgisi" - giris tetigi
EXIT_LINE_ATR_MULT = 2.4        # "Exit cizgisi" - TP tetigi (dinamik)

# ============================================================
# POZISYON BUYUKLUGU / KALDIRAC FORMULU AYARLARI
# ============================================================
EQUITY_PERCENT_PER_TRADE = 0.08   # toplam varligin yuzde kaci bir islem icin ayrilsin (%8, stake)
SL_DISTANCE_MULT = 2.0            # borsadaki gercek SL, giris-exit cizgisi mesafesinin kac kati uzakta olsun
LOSE_EXIT_DISTANCE_MULT = 1.5     # lose exit, giris-exit cizgisi mesafesinin kac kati uzakta olsun (TP'nin
                                   # tersi yonde, TP'den DAHA UZAKTA - RR 1:1.5, TP mesafesi 100 ise lose exit 150)

# ============================================================
# ISLEM / RISK AYARLARI
# ============================================================
# Her coin'de ayni anda en fazla 1 acik islem olabilir (long VEYA short,
# ikisi birden degil). Bu kural kodda state.py'nin pozisyonlari sembol
# bazinda (tek anahtar) tutmasiyla saglanir.
MAX_TOTAL_POSITIONS = 10   # tum coinler toplaminda acik pozisyon limiti
MARGIN_MODE = "REGULAR_MARGIN"  # Cross margin (Bybit V5 hesap capinda ayar)
ORDER_TYPE = "Market"

# ============================================================
# DONGU / POLLING AYARI
# ============================================================
POLL_INTERVAL_SECONDS = 1  # her saniye veri cekilir (giris/TP kontrolu icin)

# Toplam varlik anlik goruntusu (equity snapshot) ne siklikta kaydedilsin.
# Raporlardaki "X saat once varlik neydi", gun ici en yuksek/dusuk ve
# drawdown hesaplari bu gecmise dayanir.
EQUITY_SNAPSHOT_INTERVAL_SECONDS = 60
EQUITY_HISTORY_RETENTION_DAYS = 35  # haftalik rapor + pay icin makul bir pencere

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
EQUITY_HISTORY_FILE = os.path.join(STATE_DIR, "equity_history.json")
SYSTEM_EVENTS_FILE = os.path.join(STATE_DIR, "system_events.json")
LOG_FILE = os.path.join(STATE_DIR, "bot.log")

os.makedirs(STATE_DIR, exist_ok=True)
