# Gold/Silver Supertrend Bot

Bybit Futures üzerinde çalışan, **Supertrend** göstergesine ve ona bağlı
**Gold çizgi / Silver çizgi** ikilisine dayalı, **iki paralel işlem
türlü** (Gold + Silver) bir trading botu.

> **Not:** Bu, önceki "tek stratejili" Supertrend botunun köklü bir
> güncellemesidir. Eskiden tek olan strateji artik **Gold işlem** oldu,
> yanına simetrik bir **Silver işlem** eklendi.

## 1) Kurulum

```bash
pip install -r requirements.txt
```

`.env.example` dosyasını kopyala, adını `.env` yap, içine kendi Bybit
API anahtarlarını ve Telegram bot bilgilerini gir.

```bash
cp .env.example .env
```

**Önce mutlaka `BYBIT_TESTNET=true` ile dene.**

## 2) Çalıştırma

```bash
python main.py
```

Durdurmak için Ctrl+C, ya da Telegram'dan `/dur` (bot pasif olur, açık
pozisyonlar kapatılmaz, borsadaki güvenlik SL emirleri aktif kalır).

## 3) Strateji özeti

**Gösterge:** Supertrend (ATR Period: 10, Multiplier: 2). Buna bağlı iki
çizgi:
- **Gold çizgi** — Supertrend'in aktif çizgisinden 1.2 ATR uzakta
- **Silver çizgi** — Supertrend'in aktif çizgisinden 2.4 ATR uzakta

### Gold işlem
- **Giriş:** Fiyat (her saniye) Gold çizgisine değerse, o anki Supertrend
  **yönünde** açılır.
- **TP hedefi:** Silver çizgisi (dinamik) — pozisyonun **kendi yönüne**
  göre seçilir (genel Supertrend yönü mum kapanmadan geçici dönse bile),
  ve sadece gerçekten kâr/başabaş durumunda "Take Profit" sayılır.
- **Trend dönüşü:** Supertrend yön değiştirirse kapanır — **sadece mum
  kapanışında** kontrol edilir.
- **Lose exit:** Giriş-hedef mesafesinin **1,5 katı** (RR 1:1,5), sabit.
- **Güvenlik SL:** Mesafenin **2 katı**, sabit.

### Silver işlem
- **Giriş:** Fiyat (her saniye) Silver çizgisine değerse, o anki
  Supertrend'in **tersi** yönünde açılır.
- **TP hedefi:** Gold çizgisi (dinamik) — aynı şekilde pozisyonun kendi
  yönüne göre.
- **Trend dönüşü çıkışı yok** (pratikte gerekmiyor — fiyat trend
  dönüşüne yol açacak kadar gitmeden önce Silver zaten kendi TP'sine
  değip kapanmış oluyor).
- **Lose exit:** Giriş-hedef mesafesinin **1,0 katı** (RR 1:1, TP
  mesafesiyle aynı), sabit.
- **Güvenlik SL:** Mesafenin **2 katı**, sabit (Gold ile **aynı** çarpan).

### Ortak
- **Pozisyon büyüklüğü/kaldıraç formülü** ikisinde de aynı: giriş ile
  **lose exit** arası mesafe → yüzde → stake ÷ yüzde × 100 = hacim →
  hacim ÷ stake = kaldıraç. (Lose exit ve güvenlik SL'in **kendi
  seviyeleri** hâlâ giriş-TP mesafesinden türetiliyor — sadece kaldıraç
  formülüne giren yüzde artık TP mesafesi değil, lose exit mesafesi.
  Sonuç: Gold'da lose exit mesafesi TP'den geniş olduğu için kaldıraç
  öncekinden **düşük** çıkar; Silver'da lose exit mesafesi zaten TP'yle
  aynı olduğu için (RR 1:1) kaldıraçta **hiçbir değişiklik olmaz**.)
- **Stake:** Toplam varlığın **%3'ü** (her iki tür için).
- **Doğal el değişimi:** Bir Gold işlem Silver çizgisine değince kapanır
  — bu aynı anda yeni bir Silver girişinin şartını da sağlar (ve
  simetrik olarak tersi). Pratikte biri kapanınca genelde diğeri açılır.

**Coin listesi (12):** TIA, TAO, TRUMP, ADA, WLD, ENA, INJ, APT, NEAR,
ARB, HYPE, ATOM

**Pozisyon limitleri:** Bir coin'de aynı anda en fazla **1 long + 1
short** açık olabilir (Gold ve Silver hep ters yönde açtığı için bu,
borsanın hedge kapasitesiyle birebir örtüşüyor — kim hangi slotu
doldurmuş olursa olsun, tür önemli değil). Toplamda ise **long ve
short için ayrı ayrı** en fazla **12'şer** açık işlem olabilir
(birleşik değil — yani teorik olarak en fazla 12 long + 12 short = 24
açık işlem).

**Zaman dilimi:** 1 saatlik mum. Mum verisi saniyelik anlık fiyatla
güncellenir.

**Borsa ile kayıt senkronizasyonu:** Bot, açık pozisyon kayıtlarını her
~60 saniyede bir borsayla **iki yönlü** karşılaştırır (bkz. `strategy.
reconcile_with_exchange`):
- Bot'ta açık görünen ama borsada olmayan bir pozisyon varsa kayıttan
  silinir (Stop Loss olarak işlenir).
- Borsada açık olan ama bot'un bilmediği bir pozisyon varsa, gerekli
  hesaplamalar yapılarak kayda alınır ve ayrı bir bildirim gider.

**Gold/Silver tür takibi:** Borsa bir pozisyonun Gold mu Silver mu
olduğunu saklamaz (sadece long/short + fiyat/SL bilgisi verir). Bot bu
bilgiyi kendi diskine küçük bir kayıt (`data/position_types.json`)
olarak tutar — restart sonrası ya da senkronizasyon sırasında bir
pozisyon bulunduğunda önce bu kayda bakılır; kayıtta yoksa (örn. elle
açılmış bir pozisyon), o anki Supertrend yönüyle karşılaştırılarak
tahmin edilir (yön trendle aynıysa Gold, tersiyse Silver) ve bildirimde
"(tahmin edildi)" notu düşülür.

## 4) Dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `config.py` | Tüm ayarlar (coin listesi, Supertrend/Gold/Silver ayarları, yüzdeler) |
| `indicators.py` | Supertrend, ATR, Gold çizgi, Silver çizgi hesaplamaları |
| `sizing.py` | Stake / hacim / kaldıraç / güvenlik SL / lose exit formülü (Gold+Silver ortak) |
| `bybit_client.py` | Bybit API ile konuşan fonksiyonlar |
| `state.py` | Açık pozisyonlar (coin+yön), işlem geçmişi, varlık geçmişi, tür kaydı |
| `strategy.py` | Giriş/çıkış sinyal mantığı — botun beyni |
| `telegram_notifier.py` | Anlık bildirim mesajları |
| `telegram_bot.py` | Telegram komutları ve periyodik/detaylı raporlar |
| `main.py` | Botu başlatan ana dosya |

## 5) Telegram

**Bildirimler (otomatik):** bot başlatıldı, işlem açıldı (Gold/Silver
etiketli), işlem kapandı (sebep: Take Profit / Trend Dönüşü / Lose Exit
/ Stop Loss — kâr/zarar yüzdesi **ham fiyat değişim yüzdesi**), slot
dolu, bakiye yetersiz, kaldıraç limiti aşıldı, bağlantı koptu/kuruldu,
restart sonrası bulunan açık pozisyon, çalışırken borsada bulunan
kayıtsız pozisyon.

**Komutlar:**

| Komut | Ne yapar |
|---|---|
| `/Z` | Yüzeysel durum raporu (12 saatte bir otomatik de gider) |
| `/X` | Detaylı durum raporu (24 saatte bir otomatik de gider) |
| `/Q` | Çok detaylı haftalık rapor (haftada bir otomatik de gider) |
| `/pozisyonlar` | Açık pozisyonları listeler (tür etiketiyle) |
| `/coinrapor` | Tüm coinlerin özet durumu + Supertrend yönü |
| `/rapor{coinadi}` | Tek coin'in detaylı raporu (örn. `/raporARB`) — coin'de açık Gold ve/veya Silver varsa ikisi de gösterilir |
| `/coinperformans` | Her coin'in **tüm zamanlar** performansı, **Gold ve Silver ayrı ayrı** + coin toplamı |
| `/dur` | Botu acil durdurur |
| `/yardim` | Komut listesini gösterir |

## 6) Konuşurken netleşen / kilitlenen ayarlar

- Supertrend: ATR Period **10**, Multiplier **2**
- Gold çizgi: **1.2** ATR | Silver çizgi: **2.4** ATR
- Stake: toplam varlığın **%3**'ü (Gold + Silver ortak)
- Gold lose exit: mesafenin **1,5 katı** (RR 1:1,5)
- Silver lose exit: mesafenin **1,0 katı** (RR 1:1)
- Güvenlik SL: mesafenin **2 katı**, **Gold ve Silver'da ortak**
- Trend dönüşü kontrolü: **sadece mum kapanışında**, **sadece Gold'da**
- Coin başına maksimum **1 long + 1 short**; long ve short için **ayrı
  ayrı** maksimum **12'şer** (birleşik değil)
- Borsa ile kayıt senkronizasyonu: her **60 saniyede** bir, iki yönlü

## 7) ÖNEMLİ — canlıya geçmeden önce

- Bybit'in API detayları zamanla değişebilir — gerçek para ile
  çalıştırmadan önce **mutlaka testnet'te test et.**
- `bybit_client.py` içindeki emir fonksiyonları gerçek emir gönderir.
  İlk testlerini küçük miktarlarla yap.
- Bot çöker veya sunucu kapanırsa, gerçek SL emri borsada durduğu için
  pozisyon korumasız kalmaz — ama TP, lose exit ve trend-dönüşü
  kapatmaları botun kendisi tarafından yapıldığı için, bot kapalıyken
  bu kapatmalar çalışmaz. Botu kesintisiz bir sunucuda (VPS) çalıştırman
  önerilir.
- `data/position_types.json` dosyası, açık pozisyonların Gold/Silver
  bilgisini tutar — bu dosyayı elle silme; silinirse restart sonrası
  bot açık pozisyonların türünü trend yönüyle tahmin etmek zorunda kalır
  (genelde doğru tahmin eder, ama kesin bilgi kaybolmuş olur).
