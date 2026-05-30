# 🤖 Bybit 3-Thread Trading Bot

Bybit Futures üzerinde **16 coin**, **50x kaldıraç**, **hedge mode** ile çalışan otomatik strateji botu.

Üç paralel thread:
- 🔴 **KIRMIZI** — Ana strateji, Donchian yön değişimine göre işlem açar
- 🔵 **MAVİ** — Hedge, Kırmızı'nın tersi yönünde koruma açar
- 🟡 **SARI** — Trend pekiştirici, Kırmızı'nın aynı yönünde kârı maksimize eder

---

## 📋 İçindekiler
1. [Kurulum](#-kurulum)
2. [Genel Akış](#-genel-akış)
3. [🔴 Kırmızı Thread](#-kırmızı-thread-stratejisi)
4. [🔵 Mavi Thread](#-mavi-thread-stratejisi)
5. [🟡 Sarı Thread](#-sarı-thread-stratejisi)
6. [Slot Kuralları](#-slot-kuralları)
7. [Telegram Komutları](#-telegram-komutları)
8. [Raporlar](#-raporlar)

---

## 🚀 Kurulum

### Gerekli environment variables
```
BYBIT_API_KEY=...
BYBIT_API_SECRET=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### Kurulum komutları
```bash
pip install -r requirements.txt
python main.py
```

### Railway için
`Procfile` ve `runtime.txt` mevcut, doğrudan deploy edilebilir.

---

## 🔁 Genel Akış

1. **Bot başlar** → bakiye, mum verileri, EMA, Donchian çekilir
2. **Başlangıçta otomatik flag taraması** yapılır (15dk boundary beklemez)
3. **Scheduler döngüsü:**
   - Her **5 sn** → tüm coinlerin anlık fiyatı çekilir
   - **15 dk** mum kapanışında → mum verileri ve göstergeler güncellenir + flag taraması
   - Her **12 saatte bir** → stake güncellenir (bakiye %2)
   - Her tick → thread sağlık kontrolü (çöken thread otomatik yeniden başlar)
4. **Thread'ler bağımsız** çalışır, 5 sn aralıkla taramalarını yapar
5. **Telegram thread** → anlık bildirimler + zamanlı raporlar + komut işleme

---

## 🔴 KIRMIZI Thread Stratejisi

### Flag açılışı (15dk mum kapanışında)
- Donchian alt çizgisi önceki kapanışa göre **yukarı** çıktıysa → **Short Flag** açılır
- Donchian üst çizgisi önceki kapanışa göre **aşağı** indiyse → **Long Flag** açılır
- Flag aynı yönde tekrar tetiklenirse zaten açıkken bir şey yapmaz
- Flag asla otomatik silinmez — sadece işleme dönüşünce silinir

### İşlem açılışı — 2 Aşamalı

**Aşama A: Giriş Çizgisi Kaydı**
- Flag açıkken fiyat Donchian çizgisini cross eder
- O ANDAKI **Donchian çizgisinin DEĞERİ** "giriş çizgisi" olarak kaydedilir
- (Direnç seviyesi mantığı — ham fiyat değil, çizginin matematik değeri)
- EMA bakılmaz

**Aşama B: İşlem Açılışı**
- Kaydedilen giriş çizgisini fiyat **cross eder** + **EMA800 filtresi** geçer → işlem açılır
  - Short: fiyat < EMA800 → açılır
  - Long: fiyat > EMA800 → açılır
- İşlem açılınca **flag VE giriş çizgisi silinir**

### Seviyeler
- **LOSE** = Donchian değeri (max %2 ile sınırlı)
- **ENTRY** = giriş fiyatı
- **ST1-ST5** = entry ile WINRATE arası 6 eşit parça
- **WINRATE** = entry'ye göre 3x lose mesafesi

### Çıkış mantığı
| Seviye | Çıkış çizgisi |
|--------|--------------|
| ENTRY  | LOSE         |
| ST1    | LOSE         |
| ST2    | ENTRY        |
| ST3    | ST1          |
| ST4    | ST2          |
| ST5    | ST3          |

WINRATE cross → her seviyede direkt kâr ile kapanış.

### Bağımlılık
Kırmızı kapandığında bağlı **Mavi** ve **Sarı** da otomatik kapanır.

---

## 🔵 MAVİ Thread Stratejisi

### Yön
- Kırmızı Short → Mavi Long
- Kırmızı Long → Mavi Short

### Tablo
**Kırmızı giriş çizgisi ↔ Kırmızı LOSE** arası **5 EŞİT** parça.

5 bölge (Short Kırmızı için alttan üste):

```
Kırmızı LOSE      ←─── tablo üst sınırı
─────────────  ST4 (en üst zone)
─────────────  ST3
─────────────  ST2
─────────────  ST1
─────────────  FLAG
Kırmızı giriş     ←─── tablo alt sınırı (= "giriş çizgisi")
```

Her bölgenin "giriş çizgisi" = bölgenin **alt** sınırı (Kırmızı'ya yakın taraf).

### Flag mantığı
- Kırmızı giriş çizgisi cross → **flag açılır**
- Ters cross → **flag silinir**
- Tekrar cross → **yeniden açılır**

### İşlem açılışı
- Flag varken **ST1 giriş çizgisi** cross → işlem açılır, seviye = ST1
- EMA filtresi UYGULANMAZ

### Seviye geçişi
ST2/ST3/ST4 cross → seviye yükselir, **asla geri gitmez**.

### Çıkış (TRAIL YOK — sabit 2 eşik)
| Seviye   | Çıkış çizgisi          |
|----------|------------------------|
| ST1, ST2 | Kırmızı giriş çizgisi  |
| ST3, ST4 | ST1 giriş çizgisi      |

### WINRATE çıkışı
Fiyat Kırmızı LOSE'u cross → Kırmızı kapanır → Mavi otomatik **kâr** ile kapanır.

### Yeniden giriş
Kırmızı yaşadığı sürece **sınırsız** yeniden giriş hakkı.

### Tablo kurulurken fiyat zaten yukarıda/aşağıdaysa
- FLAG bölgesindeyse → sadece flag açık
- ST1-ST4 bölgelerindeyse → **flag + işlem otomatik açılır**, seviye = o bölge

---

## 🟡 SARI Thread Stratejisi

### Yön
- Kırmızı Short → Sarı Short
- Kırmızı Long → Sarı Long

### Tablo
**Kırmızı giriş çizgisi ↔ Kırmızı WINRATE** arası **6 EŞİT** parça.

6 bölge (Short Kırmızı için üstten alta):

```
Kırmızı giriş     ←─── tablo üst sınırı (= "giriş çizgisi")
─────────────  FLAG
─────────────  ST1
─────────────  ST2
─────────────  ST3
─────────────  ST4
─────────────  ST5
Kırmızı WINRATE   ←─── tablo alt sınırı
```

Her bölgenin "giriş çizgisi" = bölgenin **üst** sınırı (Kırmızı'ya yakın taraf).

### Flag mantığı (POZİSYON BAZLI — Mavi/Kırmızı'dan farklı)
- Her tarama → fiyat FLAG bölgesindeyse flag açık, değilse kapalı
- Yukarı çıkış (Kırmızı giriş üstü) → flag silinir
- Aşağı çıkış (ST1 bölgesine) → işlem açma akışı tetiklenir

### İşlem açılışı
- **ST1 giriş çizgisi** cross → işlem açılır
- **Chandelier sistemi devreye girer**

### 🕯 Chandelier sistemi
- **Mesafe** = Kırmızı giriş ↔ Kırmızı LOSE mesafesinin **YARISI**
- **En iyi fiyat** = işlem ömrü boyunca görülen en düşük (Short) / en yüksek (Long) fiyat
- **Chandelier çizgisi** = en iyi fiyat ± mesafe
- Fiyat chandelier çizgisini **ters cross** → Sarı çıkış

### Seviye değişimi
- Her bölgeye geçişte Telegram bildirimi
- **İKİ YÖNLÜ** değişir (Mavi/Kırmızı'dan farklı — sadece telemetri)
- Çıkışı etkilemez

### WINRATE çıkışı
Fiyat Kırmızı WINRATE'i cross → Kırmızı kapanır → Sarı otomatik **kâr** ile kapanır.

### 🔄 ÖZEL Yeniden giriş
1. Chandelier çıkışı sonrası "en iyi fiyat" konumuna **yeni giriş çizgisi** çizilir
2. **Flag aranmaz** (klasik akışın dışında)
3. Fiyat **kâr yönüne** dönüp bu çizgiyi cross ederse → yeniden işlem açılır
4. Yeni chandelier **aynı mesafe** ile sıfırdan başlar
5. Yeni seviye = fiyatın bulunduğu bölge
6. Kırmızı yaşadığı sürece **sınırsız** tekrar

### Tablo kurulurken fiyat zaten yukarıda/aşağıdaysa
- FLAG bölgesindeyse → sadece flag açık
- ST1+ bölgesindeyse → **otomatik işlem açılır**

---

## 🎯 Slot Kuralları
- **16 coin**, her coine en fazla **1 Kırmızı** (yön farketmez)
- Her Kırmızı'ya **1 Mavi + 1 Sarı**
- Sistem max = 48 eşzamanlı işlem
- Global limit yok
- **External pozisyon mantığı YOK** — bot başlangıçta Bybit'teki mevcut pozisyonları ignore eder

---

## 📱 Telegram Komutları
| Komut | Açıklama |
|-------|----------|
| `/start` | Trading başlat |
| `/stop` | Trading durdur |
| `/status` | Anlık durum |
| `/report` | Hourly raporu zorla gönder |
| `/pause SEMBOL` | Coin'i duraklat |
| `/resume SEMBOL` | Coin'i devam ettir |
| `/help` | Komut listesi |

---

## 📊 Raporlar

### 📈 Saatlik (her saat başı)
- Anlık durum (bakiye, stake, açık işlemler, açık flagler)
- Son 1 saatte kapanan işlem özeti

### 📊 12 Saatlik Z Raporu (00:00 ve 12:00 UTC)
- Saatlik içeriği +
- Detaylı performans (winrate, profit factor)
- Thread bazında kırılım (Kırmızı/Mavi/Sarı)
- Çıkış tipi analizi (WINRATE / LOSE / CHANDELIER / BAĞIMLI)
- Yön bazında kırılım (Long/Short)
- En kârlı / zararlı 3 coin

### 📑 24 Saatlik X Raporu (sadece 00:00 UTC)
- Genel performans + streaks (en uzun kazanma/kaybetme serisi)
- Saatlik dağılım (en aktif/kârlı/zararlı saat)
- Thread detayı
- Tüm coinler için detay (en iyi/kötü işlem)
- Çıkış tipi tam analizi
- Flag istatistikleri (açılan/dönüşen/silinen) + konversiyon oranı
- Chandelier özel analizi
- 24 saatteki uyarılar

---

## ⚙️ Bildirimler (modern tasarım)
| Bildirim | Ne zaman |
|----------|----------|
| 🚀 Bot başladı | Bot ilk açıldığında |
| 🛑 Bot durdu | Shutdown anında |
| 🟢/🔴 İşlem açıldı | Her trade açılışında |
| ✅/❌ İşlem kapandı | Her trade kapanışında |
| 📍 Seviye değişti | Her seviye değişiminde |
| 🔵/🟡 Tablo hazır | Mavi/Sarı tablo kurulduğunda |
| ⚠️ Yetersiz bakiye | Stake yetersiz olduğunda |
| ⛔️ Slot dolu | Slot çakışmasında |
| 🆘 Hata | API/sistem hatalarında |
| 💱 Stake güncellendi | 12 saatte bir |
| 🚨 Kritik | Thread çöktüğünde, shutdown'da açık işlem varsa |

**❌ Flag bildirimleri ATILMIYOR** — sadece raporlarda görünür.

---

## 🛡 Güvenlik & Dayanıklılık
- ✅ Hard SL (config'den, tickSize'a güvenli yuvarlama)
- ✅ Pozisyon doğrulama (Bybit'te gerçekten açıldı mı? 1.5sn bekle, kontrol et)
- ✅ Gerçek dolum fiyatı kullanılır (PnL doğru hesap)
- ✅ Rate limit koruması (100ms minimum gap)
- ✅ Thread auto-recovery (çöken thread otomatik restart)
- ✅ Scheduler crash koruması (loop ölmez)
- ✅ Atomik fiyat okuma (race condition yok)
- ✅ Shutdown'da açık işlem uyarısı
- ✅ SIGTERM güvenli kapatma (flag-set)
