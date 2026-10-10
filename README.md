# FAYTTREND (Q-Trend sürümü)

Bybit Futures üzerinde çalışan, **Q-Trend** göstergesinin ana çizgisi ve
Gold/Silver çizgileri üzerinden işlem açan bot. Faytterro Bands tamamen
kaldırıldı. BUY/SELL ve STRONG sinyalleri **kullanılmaz**.

## 1) Kurulum ve çalıştırma

```bash
pip install -r requirements.txt
cp .env.example .env     # API anahtarlarını ve Telegram bilgilerini gir
python main.py
```

**Önce mutlaka `BYBIT_TESTNET=true` ile dene.**
Eski bot ile aynı klasörde çalıştırma: eski `data/` klasörü yeni raporlara
karışır. Temiz başlamak için `data/` klasörünü sil.

## 2) Strateji

**Çizgiler** (1 saatlik mum, ATR 14, trend periyodu 200, çarpan 1.0):
- Ana çizgi (merdiven gibi ilerler), Gold = ana + 1 ATR, Silver = ana − 1 ATR
- Gold loss / Silver loss çizgileri sadece bilgi/rapor amaçlı hesaplanır, çıkışta kullanılmaz.

**Giriş:** Fiyat Silver'a değerse **long**, Gold'a değerse **short**.

**Çıkış (hangisi önce olursa):**
| Çıkış | Nasıl çalışır |
|---|---|
| Kâr Alma | Fiyat ana çizgiye gelince bot pozisyonu kapatır. CANLI, her saniye kontrol edilir. |
| Stop Loss | Borsada **gerçek bir emir**. Giriş ile Bybit'in verdiği **likit fiyatı** arasındaki yolun **%80'ine** konur (likitten önceki güvenlik payı %20). |

**Stop Loss nasıl çalışır**
- Pozisyon açılınca bot Bybit'ten pozisyonun likit fiyatını okur ve stop'u
  `giriş + (likit − giriş) × 0.8` seviyesine koyar (long'da aşağıda, short'ta yukarıda).
- Çapraz marj kullanıldığı için likit fiyatı sürekli değişir (hesap bakiyesi ve
  diğer açık işlemlere bağlı). Bot **her dakika** (`RECONCILE_INTERVAL_SECONDS`)
  her pozisyonun likit fiyatını yeniden okur ve stop'u yeni seviyeye taşır.
  Seviye değişmediyse borsaya istek atılmaz.
- Stop, `MarkPrice` ile tetiklenir (Bybit likidasyonu da MarkPrice'a göre yapar).
- Bot kapalıyken borsadaki stop emri yerinde kalır, ama likit fiyatı kayarsa
  güncellenemez; ayrıca Kâr Alma da çalışmaz.
- **Bybit likit fiyatını boş döndürürse** (ya da stop emri reddedilirse) stop
  konamaz: pozisyon açık kalır ve Telegram'dan "STOP LOSS KONULAMADI" uyarısı gelir.
  Aynı uyarı pozisyon başına bir kez gönderilir, bot her dakika yeniden dener.
- Borsa stop'u tetiklediğinde kapanış sebebi "Stop Loss" olarak kaydedilir;
  fiyat stop'a yakın değilse "Dış Kapanış" (elle kapatma) yazılır.

**Stake:** Futures (UNIFIED) cüzdan bakiyesinin **%1'i** (`STAKE_PERCENT`).
Kullanılan bakiye `totalWalletBalance`'tır: açık işlemlerdeki geçici kâr/zarar
**dahil değildir** (sadece kapanan işlemler bakiyeyi değiştirir), ana (Funding)
cüzdan da dahil değildir. Raporlardaki "toplam varlık" ise geçici kâr/zararı da
içeren toplam varlıktır.

**Kaldıraç:** Açılış anındaki TP mesafesine (giriş − ana çizgi) göre hesaplanır:
fiyat TP'ye (ana çizgiye) gelirse kâr yaklaşık stake kadar olsun. Coin max
kaldıracı aşılırsa max kullanılır. Hacim 5 USDT altındaysa işlem atlanır.

**Kurallar**
- 50 coin taranır, her coinde aynı anda en fazla **1** işlem, toplamda en fazla **15** açık işlem (long + short birlikte).
- Aynı mumda birden fazla işlem açılıp kapanabilir (mum başına işlem sınırı ve zarar sonrası bekleme yok).

## 3) Açık pozisyonların diske kaydı

Açık her pozisyon `data/open_positions.json` dosyasına da yazılır (açılış zamanı,
açılış anındaki TP bilgisi gibi borsadan geri okunamayan bilgiler yeniden
başlatmada korunsun diye). Stop seviyesi ve likit fiyatı ise borsadan okunur.
Dosyada kaydı olmayan ama borsada bulunan pozisyonlar kayda alınır, stop'ları
ayarlanır ve Telegram'dan bildirilir.

## 4) `config.py` içindeki önemli ayarlar
- `COINS`: 50 coin. Bot açılırken Bybit'in canlı listesiyle karşılaştırır, bulunamayanları çıkarır ve Telegram'dan haber verir.
- `STAKE_PERCENT = 1.0`, `MAX_OPEN_POSITIONS = 15`.
- `STOP_PLACEMENT_FRACTION = 0.8`: stop'un giriş→likit yolundaki yeri.
- `STOP_TRIGGER_BY = "MarkPrice"`.
- `LIQ_FETCH_RETRIES`, `LIQ_FETCH_WAIT_SECONDS`: pozisyon açıldıktan sonra Bybit'in likit fiyatını vermesini beklemek için deneme sayısı ve bekleme.
- `QT_INTRABAR_STEP`: `True` = gösterge canlı mumda Pine'daki gibi davranır (varsayılan). `False` = ana çizgi sadece mum kapanınca kayar.
- `KLINE_LOOKBACK = 1000`: ana çizgi geçmişe bağlı olduğu için en fazla mum çekilir.

## 5) Dosyalar
`config.py`, `indicators.py` (Q-Trend), `sizing.py`, `bybit_client.py`, `state.py`,
`strategy.py`, `telegram_notifier.py`, `telegram_bot.py`, `main.py`.

## 6) Canlıya geçmeden önce
- Ana çizgi grafikteki Q-Trend ile birkaç coinde karşılaştırılmalı (TradingView'ın
  geçmişi daha uzun olduğu için küçük farklar çıkabilir).
- Düşük varlıkta BTC/ETH gibi büyük lotlu coinler minimum lot yüzünden atlanabilir
  ("MİNİMUM LOT ÇOK BÜYÜK" bildirimi).
- **Stop Loss testnet'te mutlaka denenmeli.** Bybit'in çapraz marjda `liqPrice`
  alanını nasıl döndürdüğü (bazı durumlarda boş olabilir) ve stop emrinin kabul
  edilip edilmediği canlıda kontrol edilmeli.
- Çapraz marjda zarar sadece stake ile sınırlı değildir: pozisyonun arkasında
  futures hesabındaki tüm bakiye durur. Stop likidasyondan önce çalışacak şekilde
  konur, ama fiyat çok hızlı hareket ederse (boşluk) stop'a rağmen likit olabilir.
- Botu kesintisiz, güvenilir bir sunucuda çalıştır: bot kapalıyken stop seviyeleri
  güncellenmez ve Kâr Alma çalışmaz.
