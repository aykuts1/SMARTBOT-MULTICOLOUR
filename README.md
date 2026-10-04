# FAYTTREND

Bybit Futures üzerinde çalışan, **Faytterro Bands** göstergesine dayalı,
fiyat alt banda değince **long**, üst banda değince **short** açan ve
karşı yöndeki pozisyonu kapatan bir trading botu.

> **Not:** Bu, önceki Gold/Silver Supertrend botunun yerine geçen tamamen
> yeni bir stratejidir. Supertrend, Gold/Silver çizgileri, TP ve trend
> dönüşü çıkışı kaldırıldı.

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

**Gösterge:** Faytterro Bands (kaynak: hlc3, uzunluk **5**, StdDev **2.0**).
Fiyatın etrafında bir **alt bant** ve bir **üst bant** çizer. Bot, bandın
**şu anki muma denk gelen** değerine bakar (gösterge alarmının baktığı
nokta ile aynı).

> Gösterge son mumlarda sınırlı ölçüde yeniden çizer (repaint). Bantlar
> her saniye taze hesaplanır.

### Giriş / çıkış (stop-and-reverse)
- **Fiyat alt banda değerse:** açık short varsa kapatılır, long açılır
  (short yoksa doğrudan long açılır).
- **Fiyat üst banda değerse:** açık long varsa kapatılır, short açılır
  (long yoksa doğrudan short açılır).
- Aynı coinde aynı yönde zaten pozisyon açıksa yenisi açılmaz.

### Lose exit ve güvenlik SL
- İşlem açılırken **karşı banda olan mesafe (D)** ölçülür:
  long için `üst bant − giriş`, short için `giriş − alt bant`.
- **Lose exit:** girişin D kadar ters yönünde (long'da aşağıda, short'ta yukarıda).
  Açılışta sabitlenir, sonra değişmez. Botun kendisi kapatır.
- **Güvenlik SL:** girişin 2×D kadar ters yönünde. Borsaya gerçek emir olarak
  konur, bot kapalıyken de korur.

### Stake (toplam varlığa göre sabit tutar)

| Varlık (USDT) | Stake (USDT) |
|---|---|
| 0 - 25 | 0,25 |
| 25 - 50 | 0,50 |
| 50 - 75 | 1 |
| 75 - 100 | 1,50 |
| 100 - 150 | 2 |
| 150 - 200 | 3 |
| 200 - 300 | 4 |
| 300 - 400 | 6 |
| 400 - 500 | 8 |
| 500 - 600 | 10 |
| 600 - 800 | 12 |
| 800 - 1000 | 16 |
| 1000 - 1300 | 20 |
| 1300 - 1700 | 25 |
| 1700 - 2000 | 35 |
| 2000 - 2500 | 40 |
| 2500 ve üzeri | 50 |

**Sınır değerler üst bareme girer** (örn. tam 25 USDT → 0,50; tam 100 USDT → 2).

### Kaldıraç
Fiyat lose exit'e gelirse kayıp yaklaşık stake kadar olsun diye hesaplanır:
1. Giriş ile lose exit arası mesafe → yüzde
2. Stake ÷ yüzde × 100 = işlem hacmi
3. Hacim ÷ stake = kaldıraç

Coin'in izin verdiği maksimum kaldıraç aşılırsa maksimum kullanılır ve
bildirim gider. Hesaplanan hacim Bybit'in minimum emir değerinin (5 USDT)
altında kalırsa işlem atlanır ve "İşlem Hacmi Yetersiz" bildirimi gider.

**Coin listesi (12):** TIA, TAO, ADA, ENA, INJ, APT, NEAR, ARB, HYPE, ATOM,
TRUMP, WLD

**Pozisyon limitleri:** Bir coinde aynı anda en fazla **1 long + 1 short**.
Toplamda **long ve short için ayrı ayrı** en fazla **12'şer** açık işlem.

**Zaman dilimi:** 1 saatlik mum. Mum verisi saniyelik anlık fiyatla güncellenir.

**Borsa ile kayıt senkronizasyonu:** Bot, açık pozisyon kayıtlarını her
~60 saniyede bir borsayla **iki yönlü** karşılaştırır (bkz.
`strategy.reconcile_with_exchange`):
- Bot'ta açık görünen ama borsada olmayan pozisyon kayıttan silinir
  (Stop Loss olarak işlenir).
- Borsada açık olan ama bot'un bilmediği pozisyon, gerekli hesaplamalar
  yapılarak kayda alınır ve ayrı bir bildirim gider.

## 4) Dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `config.py` | Tüm ayarlar (coin listesi, bant ayarları, stake tablosu, limitler) |
| `indicators.py` | Faytterro Bands hesabı (alt/üst bant) |
| `sizing.py` | Stake / hacim / kaldıraç / güvenlik SL / lose exit formülü |
| `bybit_client.py` | Bybit API ile konuşan fonksiyonlar |
| `state.py` | Açık pozisyonlar (coin+yön), işlem geçmişi, varlık geçmişi |
| `strategy.py` | Giriş/çıkış sinyal mantığı — botun beyni |
| `telegram_notifier.py` | Anlık bildirim mesajları |
| `telegram_bot.py` | Telegram komutları ve periyodik/detaylı raporlar |
| `main.py` | Botu başlatan ana dosya |

## 5) Telegram

**Bildirimler (otomatik):** bot başlatıldı, işlem açıldı, işlem kapandı
(sebep: Bant Dönüşü / Lose Exit / Stop Loss), slot dolu, bakiye yetersiz,
kaldıraç limiti aşıldı, işlem hacmi yetersiz, bağlantı koptu/kuruldu,
restart sonrası bulunan açık pozisyon, çalışırken borsada bulunan
kayıtsız pozisyon.

**Komutlar:**

| Komut | Ne yapar |
|---|---|
| `/Z` | Yüzeysel durum raporu (12 saatte bir otomatik de gider) |
| `/X` | Detaylı durum raporu (24 saatte bir otomatik de gider) |
| `/Q` | Çok detaylı haftalık rapor (haftada bir otomatik de gider) |
| `/pozisyonlar` | Açık pozisyonları listeler |
| `/coinrapor` | Tüm coinlerin özet durumu + alt/üst bant değerleri |
| `/rapor{coinadi}` | Tek coin'in detaylı raporu (örn. `/raporARB`) |
| `/coinperformans` | Her coin'in **tüm zamanlar** performansı, **Long ve Short ayrı ayrı** + coin toplamı |
| `/dur` | Botu acil durdurur |
| `/yardim` | Komut listesini gösterir |

## 6) ÖNEMLİ — canlıya geçmeden önce

- Bybit'in API detayları zamanla değişebilir — gerçek para ile
  çalıştırmadan önce **mutlaka testnet'te test et.**
- `bybit_client.py` içindeki emir fonksiyonları gerçek emir
  gönderir. İlk testlerini küçük miktarlarla yap.
- Bot çöker veya sunucu kapanırsa, gerçek SL emri borsada durduğu için
  pozisyon korumasız kalmaz — ama lose exit ve bant dönüşü kapatmaları
  botun kendisi tarafından yapıldığı için, bot kapalıyken bu kapatmalar
  çalışmaz. Botu kesintisiz bir sunucuda (VPS) çalıştırman önerilir.
- Bot her başladığında, Telegram'da o ana kadar **bekleyen** komutları
  çalıştırmadan atlar — sadece bundan sonra gelenlere tepki verir. Eğer
  `/dur` gönderdiğin tam anda bot yeniden başlıyorsa, o komut atlanabilir;
  böyle bir durumda `/dur`'u tekrar göndermen yeterli.
- Stake'ler küçük olduğu için (özellikle düşük varlıkta) hesaplanan hacim
  5 USDT'nin altında kalabilir; bu durumda bot işlemi atlar ve bildirim gönderir.
- Eski bot (Gold/Silver) ile aynı klasörde çalıştırma: eski `data/`
  klasöründeki işlem geçmişi yeni raporlara karışır. Temiz başlamak için
  `data/` klasörünü sil ya da yeni bir klasörde çalıştır.
