# T3 + Merkez Çizgisi Bot

Bybit Futures üzerinde çalışan, Tilson T3 ve "Merkez çizgisi" (ALMA)
göstergelerine dayalı hedge-mod trading botu.

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
gibi çalıştığından emin ol.

## 2) Çalıştırma

```bash
python main.py
```

Bot çalışırken durdurmak için terminalde Ctrl+C, ya da Telegram'dan
`/dur` komutu (bot pasif olur, açık pozisyonlar kapatılmaz).

## 3) Dosyalar

| Dosya | Ne işe yarar |
|---|---|
| `config.py` | Tüm ayarlar (coin listesi, gösterge ayarları, yüzdeler) |
| `indicators.py` | Tilson T3, Merkez çizgisi (ALMA), ATR hesaplamaları |
| `sizing.py` | Kaldıraç / işlem hacmi formülü |
| `bybit_client.py` | Bybit API ile konuşan fonksiyonlar |
| `state.py` | Açık pozisyonların ve işlem geçmişinin hafızası |
| `strategy.py` | Giriş/çıkış sinyali mantığı |
| `telegram_notifier.py` | Bildirim mesajları |
| `telegram_bot.py` | Telegram komutları ve periyodik raporlar |
| `main.py` | Botu başlatan ana dosya |

## 4) Konuşurken netleşmeyen / varsayılan bırakılan ayarlar

Bunları istediğin zaman `config.py` içinden tek satırdan değiştirebilirsin:

- **Merkez çizgisi (ALMA) offset / sigma:** orijinal Pine kodundaki
  varsayılanlar kullanıldı — offset `0.85`, sigma `6`. Sadece length
  (`7`) senin belirttiğin değer.
- **ATR periyodu:** konuşulmadı, piyasada standart olan **14** kullanıldı.
- **Mum (kline) zaman dilimi:** **1 saat** olarak ayarlandı (senin son
  talimatın). Gösterge hesapları bu zaman dilimindeki mumlardan yapılır;
  fiyatın banda "değmesi" ise ayrı olarak her saniye anlık fiyatla
  kontrol edilir.
- **"Fiyat merkez çizgisine değdi" tespiti:** iki ardışık saniyelik
  fiyat ölçümü arasında merkez çizgisinin değerinden geçilip
  geçilmediğine bakılarak tespit edilir (ani sıçramalarda da yakalar).

## 5) ÖNEMLİ - canlıya geçmeden önce

- Bybit'in API detayları (parametre adları, davranışları) zamanla
  değişebilir. Bu kod yazılırken güncel Bybit V5 dokümantasyonu
  kontrol edildi, ama gerçek para ile çalıştırmadan önce **mutlaka
  testnet'te test et.**
- `bybit_client.py` içindeki `open_market_position`, `close_market_position`,
  `set_stop_loss`, `set_leverage` fonksiyonları gerçek emir gönderir.
  İlk testlerini küçük miktarlarla yap.
- Bot çöker veya sunucu kapanırsa, gerçek SL emri borsada (Bybit'te)
  durduğu için pozisyonların korumasız kalmaz — ama TP ve "lose exit"
  kapatmaları botun kendisi tarafından yapıldığı için, bot kapalıyken
  bu kapatmalar çalışmaz. Botu kesintisiz bir sunucuda (VPS) çalıştırman
  önerilir.
