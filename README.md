# Bybit EMA Channel Scalp Bot

Bybit USDT perpetual futures üzerinde 5 dakikalık zaman diliminde **EMA7 + EMA100 Yüksek/Düşük kanalı + kanal genişliği filtresi** ile çalışan otomatik scalp botu. Railway worker olarak çalışmak üzere tasarlanmıştır.

---

## Strateji Özeti

### Göstergeler
- **EMA100(High)** — son 100 mumun en yüksek fiyatlarının EMA'sı (dinamik direnç)
- **EMA100(Low)** — son 100 mumun en düşük fiyatlarının EMA'sı (dinamik destek)
- **EMA7(Close)** — son 7 kapanış fiyatının EMA'sı (tetikleyici)
- **ATR(14)** — 5 dakikalık ATR

### Giriş Sinyalleri
**Long:**
- 5 dakikalık mum kapanışında **EMA7 > EMA100(High)**
- **Kanal genişliği > son 100 mumun ortalama kanal genişliği**

**Short:**
- 5 dakikalık mum kapanışında **EMA7 < EMA100(Low)**
- Aynı kanal genişliği filtresi

### Pozisyon Yönetimi
- **%20** bakiye stake olarak ayrılır (bot başlangıcında kilitlenir, restart'a kadar sabit)
- **50x ISOLATED** kaldıraç
- Maksimum **5 eş zamanlı pozisyon**, aynı coinde **1 pozisyon**

### Çıkış Aşamaları
| Aşama | Tetikleyici | Aksiyon |
|---|---|---|
| Giriş | İşlem açılır | Borsaya **%1 SL** emri |
| Aşama 1 | **+1 ATR kâr** | CE devreye girer, **1 ATR geriden** takip |
| Aşama 2 | **+%1.2 kâr** | SL **+%1 kâra** taşınır, CE devam |

**Çıkış tetikleyicileri:**
1. CE seviyesi tetiklenirse → çıkış
2. EMA7 ters kanalı keserse → anında çıkış (strateji tersine döndü)
3. %1 SL tetiklenirse → çıkış (borsa tarafında)

### Tarama
- **Giriş taraması:** her 5 dakikalık mum kapanışında
- **Çıkış taraması:** her 60 saniyede bir

---

## Dosya Yapısı

```
.
├── config.py              # Environment variables ve strateji parametreleri
├── bybit_client.py        # Bybit v5 API wrapper
├── indicators.py          # EMA, ATR, kanal genişliği
├── strategy.py            # Giriş/ters sinyal mantığı
├── position_manager.py    # Açık pozisyon takibi (CE, aşamalar)
├── telegram_bot.py        # Telegram bildirimleri
├── main.py                # Ana döngü + scheduler
├── requirements.txt       # Python bağımlılıkları
├── Procfile               # Railway worker komutu
├── runtime.txt            # Python sürümü
└── README.md
```

---

## Environment Variables

Railway'de aşağıdaki değişkenleri ayarlamak gerekir:

| Değişken | Zorunlu | Açıklama |
| --- | --- | --- |
| `BYBIT_API_KEY` | ✅ | Bybit API anahtarı |
| `BYBIT_API_SECRET` | ✅ | Bybit API gizli anahtarı |
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram bot token (BotFather'dan) |
| `TELEGRAM_CHAT_ID` | ✅ | Telegram chat ID |
| `SYMBOLS` | ❌ | Virgülle ayrılmış sembol listesi (boşsa 40 coinlik varsayılan) |
| `BYBIT_TESTNET` | ❌ | `true` ise testnet (varsayılan: `false`) |

---

## Varsayılan Coin Listesi (40 coin)

BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, PEPEUSDT, SUIUSDT, WIFUSDT, AVAXUSDT, NEARUSDT, SHIBUSDT, APTUSDT, ADAUSDT, LINKUSDT, ORDIUSDT, FETUSDT, OPUSDT, ARBUSDT, FTMUSDT, TIAUSDT, BONKUSDT, FLOKIUSDT, WLDUSDT, LTCUSDT, BCHUSDT, DOTUSDT, TRXUSDT, INJUSDT, SEIUSDT, RENDERUSDT, ATOMUSDT, POLUSDT, STXUSDT, LDOUSDT, FILUSDT, GALAUSDT, GRTUSDT, UNIUSDT, ARKMUSDT, ETCUSDT

---

## Bybit API İzinleri

API key şu izinlere sahip olmalı:
- ✅ **Unified Trading**: Orders + Positions
- ❌ Withdraw (kapalı kalsın)

---

## Railway'de Kurulum

1. Bu repoyu GitHub'a push et
2. Railway → mevcut projeyi seç (veya yeni proje → "Deploy from GitHub repo")
3. Eski dosyalar otomatik olarak yenileriyle değişecek
4. Environment variables zaten ayarlıysa dokunmaya gerek yok
5. Deploy başlayacak; logları takip et

`Procfile` sayesinde Railway otomatik olarak `worker: python main.py` çalıştırır.

---

## Telegram Bildirimleri

Bot şu durumlarda Telegram mesajı gönderir:

- 🚀 **Bot başlangıcı** — bakiye, stake, kaldıraç, coin sayısı
- 📡 **Her 5dk tarama özeti** — taranan, sinyaller, aktif/boş slot
- 🟢/🔴 **İşlem açılışı** — coin, yön, fiyat, miktar, SL, ATR
- ⚙️ **Aşama 1** — CE aktifleşti, seviye
- 🔒 **Aşama 2** — SL kâra taşındı
- ✅/❌ **İşlem kapanışı** — giriş/çıkış, PnL, sebep
- 🚨 **Hata bildirimi** — API/bağlantı hataları
- 📈/📉 **Günlük özet** — UTC gün dönümünde toplam PnL, işlem sayısı, kazanma oranı

---

## Önemli Notlar

- **Bot Unified Trading hesabı kullanır.** Klasik hesap için `config.ACCOUNT_TYPE` değiştirilmeli.
- **One-way mode varsayılır** (positionIdx=0). Hedge mode için kod değiştirilmeli.
- **Stake bot başlangıcında sabitlenir.** Güncellemek için botu yeniden başlat.
- **CE seviyesi sadece bot hafızasında tutulur** (borsada değil). Bot restart olursa açık pozisyonların CE state'i kaybolur; borsadaki %1 (veya Aşama 2 sonrası %1 kâr) SL korunur.
- **Aşama 2 sonrası CE takip etmeye devam eder.** İki çıkış yolundan hangisi önce tetiklenirse o işler.

---

## Risk Uyarısı

Bu bot finansal tavsiye değildir. Kripto vadeli işlemler **yüksek risklidir**; sermayenizin tamamını kaybedebilirsiniz. 50x kaldıraçta %1 fiyat hareketi, kullanılan teminatın yarısını silebilir. Önce testnet'te ve düşük tutarlarla test edin. Yazılım hataları, ağ kesintileri ve borsa kesintileri nedeniyle beklenmedik kayıplar oluşabilir. Kullanım kendi sorumluluğunuzdadır.
