# Supertrend Entry/Exit Bot

Bybit Futures üzerinde çalışan, **Supertrend** göstergesine ve ona bağlı
**Entry çizgisi / Exit çizgisi** ikilisine dayalı bir trading botu.

> **Not:** Bu, eski "T3 + Merkez Çizgisi" botunun köklü bir güncellemesidir.
> Eski gösterge (Tilson T3, Merkez/ALMA) ve eski "lose exit" mantığı
> tamamen kaldırıldı, yerine bu belgede anlatılan yeni strateji geldi.

## 1) Kurulum

```bash
pip install -r requirements.txt
```

`.env.example` dosyasını kopyala, adını `.env` yap, içine kendi Bybit
API anahtarlarını ve Telegram bot bilgilerini gir.

```bash
cp .env.example .env
```

**Önce mutlaka `BYBIT_TESTNET=true` ile dene.** Gerçek parayla
çalıştırmadan önce testnet'te birkaç gün izleyip her şeyin beklediğin
gibi çalıştığından emin ol — özellikle yeni giriş/çıkış mantığı ve yeni
pozisyon büyüklüğü formülü.

## 2) Çalıştırma

```bash
python main.py
```

Bot çalışırken durdurmak için terminalde Ctrl+C, ya da Telegram'dan
`/dur` komutu (bot pasif olur, açık pozisyonlar kapatılmaz, borsadaki
güvenlik SL emirleri aktif kalır).

## 3) Strateji özeti

**Gösterge:** Supertrend (ATR Period: 10, Multiplier: 2). Buna bağlı iki
çizgi, fiyata doğru kaydırılmış olarak hesaplanır:
- **Entry çizgisi** — Supertrend'in aktif çizgisinden 1.2 ATR uzakta
- **Exit çizgisi** — Supertrend'in aktif çizgisinden 2.4 ATR uzakta

**Yön:** Bot sadece Supertrend'in o anki yönünde işlem açar (trend
yükselişte ise sadece long, düşüşte ise sadece short).

**Giriş:** Fiyat her saniye çekilir. Anlık fiyat Entry çizgisini
geçtiği (iki ölçüm arasında kestiği) an, o anki Supertrend yönünde
işlem açılır.

**Pozisyon büyüklüğü / kaldıraç:**
1. Entry ile Exit çizgisi arası mesafe ölçülür, girişe göre yüzdeye
   çevrilir (örnek: %5)
2. Stake = toplam varlığın %8'i (örnek: 8 USDT)
3. Stake ÷ yüzde × 100 = işlem hacmi → 8 / 5 × 100 = 160 USDT
4. İşlem hacmi ÷ stake = kaldıraç → 160 / 8 = 20x
5. Coin'in izin verdiği maksimum kaldıracı aşarsa, kaldıraç orada
   sabitlenir (stake aynı kalır, hacim küçülür) ve Telegram'a ayrı bir
   bildirim gider.

**Çıkış — üç yol:**
1. **TP:** Fiyat (her saniye, anlık) Exit çizgisini geçerse pozisyon
   kapanır. Exit çizgisi dinamiktir, her mumda değişebilir.
2. **Trend dönüşü:** Supertrend yön değiştirirse pozisyon kapanır —
   ama bu **sadece mum kapanışında** kontrol edilir, saniyelik değil.
3. **Güvenlik SL:** Giriş fiyatı ile o anki Exit çizgisi arasındaki
   mesafenin **2 katı**, borsaya gerçek stop-loss emri olarak konur.
   Bu seviye açılışta bir kez hesaplanır ve **sabit kalır** — Exit
   çizgisi sonradan hareket etse bile SL güncellenmez. Sadece bot
   çökerse / bağlantı koparsa diye bir güvenlik ağıdır.

**Coin listesi (12):** TIA, TAO, TRUMP, ADA, WLD, ENA, INJ, APT, NEAR,
ARB, HYPE, ATOM

**Pozisyon limitleri:** Her coin'de aynı anda en fazla **1** açık işlem
(long ya da short, ikisi birden değil); toplamda en fazla **10** açık
işlem. Hedge modu borsa tarafında açık kalır ama bot mantığı coin
başına tek pozisyonla sınırlıdır.

**Zaman dilimi:** 1 saatlik mum. Mum verisi saniyelik anlık fiyatla
güncellenir (bkz. `bybit_client.py` — 300 mumluk tam yenileme sadece
her yeni mumda, aradaki her saniyede sadece son mumun close/high/low
değeri anlık fiyatla güncellenir).

## 4) Dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `config.py` | Tüm ayarlar (coin listesi, Supertrend/Entry/Exit ayarları, yüzdeler) |
| `indicators.py` | Supertrend, ATR, Entry çizgisi, Exit çizgisi hesaplamaları |
| `sizing.py` | Stake / hacim / kaldıraç / güvenlik SL formülü |
| `bybit_client.py` | Bybit API ile konuşan fonksiyonlar (değişmedi) |
| `state.py` | Açık pozisyonlar (coin başına tek), işlem geçmişi, varlık geçmişi, sistem olayları |
| `strategy.py` | Giriş/çıkış sinyal mantığı — botun beyni |
| `telegram_notifier.py` | Anlık bildirim mesajları |
| `telegram_bot.py` | Telegram komutları ve periyodik/detaylı raporlar |
| `main.py` | Botu başlatan ana dosya — saniyelik döngü + mum-kapanış tespiti |

## 5) Telegram

**Bildirimler (otomatik):** bot başlatıldı, işlem açıldı, işlem kapandı
(sebep: Take Profit / Trend Dönüşü / Stop Loss — kâr/zarar yüzdesi artık
kaldıraçlı getiri değil, **ham fiyat değişim yüzdesi**), slot dolu,
bakiye yetersiz, kaldıraç limiti aşıldı, bağlantı koptu/kuruldu, restart
sonrası bulunan açık pozisyon.

**Komutlar:**

| Komut | Ne yapar |
|---|---|
| `/Z` | Yüzeysel durum raporu (12 saatte bir otomatik de gider) |
| `/X` | Detaylı durum raporu (24 saatte bir otomatik de gider) |
| `/Q` | Çok detaylı haftalık rapor (haftada bir otomatik de gider) |
| `/pozisyonlar` | Açık pozisyonları listeler |
| `/coinrapor` | Tüm coinlerin özet durumu + Supertrend yönü |
| `/rapor{coinadi}` | Tek coin'in detaylı raporu (örn. `/raporARB`) |
| `/coinperformans` | Her coin'in **tüm zamanlar** toplam işlem/kâr/zarar/kazanma oranı özeti |
| `/dur` | Botu acil durdurur |
| `/yardim` | Komut listesini gösterir |

İlk periyodik rapor gece 00:00'da gönderilir, sonrası periyodiktir.

## 6) Konuşurken netleşen / kilitlenen ayarlar

- Supertrend: ATR Period **10**, Multiplier **2**
- Entry çizgisi: **1.2** ATR | Exit çizgisi: **2.4** ATR
- Stake: toplam varlığın **%8**'i
- Güvenlik SL: Entry-Exit mesafesinin **2 katı**, **sabit** (açılışta bir
  kez hesaplanır, sonra güncellenmez)
- Trend dönüşü kontrolü: **sadece mum kapanışında**
- Coin başına maksimum **1** açık işlem, toplamda maksimum **10**

## 7) ÖNEMLİ — canlıya geçmeden önce

- Bybit'in API detayları (parametre adları, davranışları) zamanla
  değişebilir. Bu kod yazılırken güncel Bybit V5 dokümantasyonu
  kontrol edildi, ama gerçek para ile çalıştırmadan önce **mutlaka
  testnet'te test et.**
- `bybit_client.py` içindeki `open_market_position`, `close_market_position`,
  `set_stop_loss`, `set_leverage` fonksiyonları gerçek emir gönderir.
  İlk testlerini küçük miktarlarla yap.
- Bot çöker veya sunucu kapanırsa, gerçek SL emri borsada (Bybit'te)
  durduğu için pozisyon korumasız kalmaz — ama TP ve trend-dönüşü
  kapatmaları botun kendisi tarafından yapıldığı için, bot kapalıyken
  bu kapatmalar çalışmaz. Botu kesintisiz bir sunucuda (VPS) çalıştırman
  önerilir.
- Bot ilk kez bu yeni sürümle başlatıldığında, eğer borsada eski
  bottan kalma (aynı coin'de hem long hem short gibi) bir pozisyon
  kalıntısı varsa, bot bunlardan sadece birini otomatik takibe alır ve
  diğerini konsola not düşer — böyle bir durumda borsadaki pozisyonları
  bota geçmeden önce elle gözden geçirmen iyi olur.
