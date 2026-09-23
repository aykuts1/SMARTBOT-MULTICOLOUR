# -*- coding: utf-8 -*-
"""
config.py
---------
Botun tum ayarlari burada.

API anahtarlari ve Telegram bilgileri .env dosyasindan okunur (guvenlik
icin kod icine yazilmaz). .env.example dosyasini kopyalayip .env yap ve
kendi bilgilerini gir.

KOKLU GUNCELLEME (Gold/Silver): Cizgiler yeniden adlandirildi ve artik
IKI ayri islem turu var - eskiden tek olan strateji artik "Gold islem"
oldu, yanina "Silver islem" eklendi. Detay asagida.
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
KLINE_INTERVAL = "60"       # 1 saatlik mum (dakika cinsinden)
KLINE_LOOKBACK = 300

# ============================================================
# SUPERTREND AYARLARI
# ============================================================
SUPERTREND_ATR_PERIOD = 10
SUPERTREND_MULTIPLIER = 2.0

# Supertrend'in ana cizgisinden (up/dn), fiyata dogru kaydirilmis iki
# cizgi. Ikisi de ayni ATR'yi (Supertrend ATR'si) kullanir.
GOLD_LINE_ATR_MULT = 1.2     # "Gold cizgi" (eski adiyla Entry cizgisi)
SILVER_LINE_ATR_MULT = 2.4   # "Silver cizgi" (eski adiyla Exit cizgisi)

# ============================================================
# IKI ISLEM TURU: GOLD ve SILVER
# ============================================================
# GOLD ISLEM: fiyat Gold cizgisine degince, Supertrend YONUNDE acilir.
#   TP hedefi: Silver cizgisi (dinamik). Trend donusu cikisi VAR.
# SILVER ISLEM: fiyat Silver cizgisine degince, Supertrend'in TERSI
#   yonunde acilir. TP hedefi: Gold cizgisi (dinamik). Trend donusu
#   cikisi YOK (pratikte gerekmiyor - trend donecek kadar fiyat gitmeden
#   once zaten Silver kendi TP'sine degip kapanmis oluyor).
#
# Ikisi de AYNI buyukluk/kaldirac formulunu kullanir: giris ile hedef
# cizgi arasi mesafe -> yuzde -> stake/yuzde*100 = hacim -> hacim/stake
# = kaldirac. Stake ve guvenlik SL carpani ikisinde de ORTAK; sadece
# lose exit mesafesi turlere gore farkli (asagida).
EQUITY_PERCENT_PER_TRADE = 0.03   # stake: toplam varligin %3'u (her iki tur icin de)
SL_DISTANCE_MULT = 2.0            # guvenlik SL, giris-hedef mesafesinin kac kati uzakta (ORTAK)

LOSE_EXIT_DISTANCE_MULT_GOLD = 1.5    # Gold lose exit: RR 1:1.5 (TP mesafesinin 1.5 kati)
LOSE_EXIT_DISTANCE_MULT_SILVER = 1.0  # Silver lose exit: RR 1:1 (TP mesafesiyle ayni)

# ============================================================
# ISLEM / RISK AYARLARI
# ============================================================
# Bir coin'de ayni anda en fazla 1 LONG + 1 SHORT olabilir (borsanin
# hedge modu kapasitesiyle birebir - bkz. state.py'nin pozisyon
# anahtarlamasi: "SYMBOL_side"). Bu long/short slotu Gold ya da Silver
# tarafindan doldurulabilir, tur onemli degil.
# Bir coin'de ayni anda en fazla 1 LONG + 1 SHORT olabilir (borsanin
# hedge modu kapasitesiyle birebir - bkz. state.py'nin pozisyon
# anahtarlamasi: "SYMBOL_side"). Bu long/short slotu Gold ya da Silver
# tarafindan doldurulabilir, tur onemli degil.
#
# Toplamda ise LONG ve SHORT icin AYRI AYRI limit var: en fazla 12 long
# VE en fazla 12 short ayni anda acik olabilir (birlesik degil, ayri
# sayaçlar) - yani teorik olarak en fazla 12+12=24 acik islem olabilir.
MAX_POSITIONS_PER_SIDE = 12

# Bybit'in USDT perpetual islemler icin platform genelindeki minimum
# emir DEGERI (notional, qty*fiyat cinsinden - qty adedi degil). Canli
# ortamda gozlemlenen hata mesajinin ("Order does not meet minimum
# order value 5USDT") kendisinden alinmistir. Hesaplanan islem hacmi
# bunun altinda kalirsa (dusuk stake/kaldirac ya da ucuz bir coin
# yuzunden olabilir), islem acilmadan once atlanir - aksi halde borsa
# emri reddeder ve sinyal her saniye ayni basarisiz emri tekrar dener.
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
# Hangi acik pozisyonun Gold hangisinin Silver oldugunu hatirlamak icin
# (borsa bu bilgiyi saklamiyor - restart sonrasi buradan okunur).
POSITION_TYPES_FILE = os.path.join(STATE_DIR, "position_types.json")
LOG_FILE = os.path.join(STATE_DIR, "bot.log")

os.makedirs(STATE_DIR, exist_ok=True)
