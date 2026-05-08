# Scalp Bot - Bybit

Bollinger Bands + RSI + ADX scalping stratejisi ile çalışan otomatik trading botu.

## Strateji Özeti

- **Borsa:** Bybit (Unified Trading)
- **Mum:** 15 dakika
- **Filtreler (sırasıyla):**
  1. **Bollinger Bands** - Bant geri dönüşü (tetikleyici)
  2. **RSI** - Aşırı alım/satım teyidi (< 35 long, > 65 short)
  3. **ADX** - Yatay piyasa kontrolü (< 25)
- **Pozisyon:**
  - 10x kaldıraç
  - Stake = Bakiyenin %20'si
  - Max 4 eş zamanlı pozisyon
  - Aynı coinde max 1 pozisyon
- **Risk Yönetimi:**
  - Borsa SL: %1
  - Kâr %1'e ulaşınca → SL giriş fiyatına çekilir + CE 0.5 ATR'ye sıkılaşır
  - Chandelier Exit: Başlangıçta 2 ATR, sıkılaştığında 0.5 ATR

## Dosya Yapısı

```
scalp-bot/
├── main.py              # Ana bot döngüsü
├── config.py            # Ayarlar
├── exchange.py          # Bybit API
├── indicators.py        # BB, RSI, ADX, ATR
├── filters.py           # Sinyal filtreleri
├── position_manager.py  # Pozisyon takibi
├── telegram_bot.py      # Telegram bildirimleri
├── requirements.txt     # Python kütüphaneleri
├── .env.example         # Örnek env dosyası
├── Procfile             # Railway için
└── runtime.txt          # Python versiyonu
```

## Kurulum

### 1. Bybit API Key Oluştur

1. Bybit hesabına gir → API Management
2. Yeni API key oluştur
3. **İzinler:** Read-Write, Unified Trading
4. Key ve Secret'i kaydet

### 2. Telegram Bot Oluştur

1. Telegram'da `@BotFather`'a yaz
2. `/newbot` komutu ile yeni bot oluştur
3. Token'ı kaydet
4. Botu kendi sohbetine ekle, mesaj at
5. `https://api.telegram.org/bot<TOKEN>/getUpdates` adresinden chat_id'yi al

### 3. .env Dosyasını Düzenle

`.env.example` dosyasını `.env` olarak kopyala ve değerleri doldur:

```
BYBIT_API_KEY=your_api_key
BYBIT_API_SECRET=your_api_secret
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 4. Lokal Test

```bash
pip install -r requirements.txt
python main.py
```

### 5. Railway'e Deploy

1. GitHub'a yeni bir repo aç ve dosyaları yükle
2. Railway'de `New Project` → `Deploy from GitHub repo`
3. Environment Variables kısmına `.env` değerlerini ekle
4. Deploy başlatılır

## RSI Botu ile Geçiş

Aynı Bybit hesabında iki bot çalıştırmak yerine, sırayla kullan:

- Scalp botu çalışacak → RSI botunu Railway'de **Suspend**, scalp botu **Resume**
- RSI botu çalışacak → Scalp botunu **Suspend**, RSI botu **Resume**

⚠️ **Aynı anda ikisini birden çalıştırma!** Pozisyon çakışması olur.

## Coin Listesi

20 coin tanımlı (config.py içinde). Düzenlemek için `SYMBOLS` listesini güncelle.

## Bildirimler

- ✅ Bot başladı
- 🟢/🔴 Pozisyon açıldı
- 🎯 Breakeven + CE sıkılaştı
- ✅/❌ Pozisyon kapatıldı
- 🔍 Tarama özeti (sinyal yoksa)
- ⚠️ Hata
