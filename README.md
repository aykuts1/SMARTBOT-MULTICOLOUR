# FAYTTREND (Q-Trend sürümü)

Bybit Futures üzerinde çalışan, **Q-Trend** göstergesinin ana çizgisi (rengine göre
yön) ve Gold/Silver çizgileri üzerinden işlem açıp kapatan bot. Faytterro Bands tamamen
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

**Çizgiler** (1 saatlik mum, ATR 14, trend periyodu 200):
- Ana (orta) çizgi merdiven gibi ilerler; adım büyüklüğü **2 ATR**.
- Gold = ana + **2 ATR**, Silver = ana − **2 ATR**.
- Çizgi rengi: **yeşil** = yükseliş (Pine'daki `ls == "B"`), **kırmızı** = düşüş.

**Giriş:** Fiyat **ana çizgiye** değince işlem açılır. Çizgi **yeşilse LONG**,
**kırmızıysa SHORT**. (Silver/Gold'a değince giriş artık yok.)
Çizgi fiyatla birlikte basamak atlarken oluşan sahte "değme" sayılmaz; çizgi
önceki saniyede de aynı yerdeyse ve fiyat onu geçtiyse giriş olur.

**Çıkış (hangisi önce olursa):**
| Çıkış | Nasıl çalışır |
|---|---|
| Kâr Alma (dinamik) | **Long:** fiyat **Gold** çizgisine ulaşınca. **Short:** fiyat **Silver** çizgisine ulaşınca. Hedef çizgi hareket ettikçe hedef de kayar; CANLI, her saniye kontrol edilir. |
| Lose Exit | **Long:** işlem açıldığı andaki **Silver** değeri sabit tutulur; 1 saatlik mum bu seviyenin **altında kapanırsa** işlem zararla kapatılır. **Short:** tam ters (açılıştaki **Gold**; mum **üstünde** kapanırsa). Açılış mumunun kapanışı da kontrol edilir. |
| Stop Loss | Borsada **gerçek bir emir**. Giriş ile Bybit'in verdiği **likit fiyatı** arasındaki yolun **%80'ine** konur. |

**Stop Loss nasıl çalışır**
- Pozisyon açılınca bot Bybit'ten pozisyonun likit fiyatını okur ve stop'u
  `giriş + (likit − giriş) × 0.8` seviyesine koyar (long'da aşağıda, short'ta yukarıda).
- Çapraz marj kullanıldığı için likit fiyatı sürekli değişir (hesap bakiyesi ve
  diğer açık işlemlere bağlı). Bot **her dakika** (`RECONCILE_INTERVAL_SECONDS`)
  her pozisyonun likit fiyatını yeniden okur ve stop'u yeni seviyeye taşır.
  Seviye değişmediyse borsaya istek atılmaz.
- Stop, `MarkPrice` ile tetiklenir (Bybit likidasyonu da MarkPrice'a göre yapar).
- Bot kapalıyken borsadaki stop emri yerinde kalır, ama likit fiyatı kayarsa
  güncellenemez; ayrıca Kâr Alma ve Lose Exit de çalışmaz.
- **Bybit likit fiyatını boş döndürürse** (ya da stop emri reddedilirse) stop
  konamaz: pozisyon açık kalır ve Telegram'dan "STOP LOSS KONULAMADI" uyarısı gelir.
  Aynı uyarı pozisyon başına bir kez gönderilir, bot her dakika yeniden dener.
- Borsa stop'u tetiklediğinde kapanış sebebi "Stop Loss" olarak kaydedilir;
  fiyat stop'a yakın değilse "Dış Kapanış" (elle kapatma) yazılır.
- Kapanış sebepleri: Kâr Alma, Lose Exit, Stop Loss, Dış Kapanış.

**Stake:** Futures (UNIFIED) cüzdan bakiyesinin **%1'i** (`STAKE_PERCENT`).
Kullanılan bakiye `totalWalletBalance`'tır: açık işlemlerdeki geçici kâr/zarar
**dahil değildir** (sadece kapanan işlemler bakiyeyi değiştirir), ana (Funding)
cüzdan da dahil değildir. Raporlardaki "toplam varlık" ise geçici kâr/zararı da
içeren toplam varlıktır.

**Kaldıraç:** Açılış anındaki TP mesafesine (giriş ↔ Gold/Silver) göre hesaplanır:
fiyat TP'ye gelirse kâr yaklaşık stake kadar olsun. Açıldıktan sonra kaldıraç
sabittir (TP çizgisi kaysa da değişmez). Coin max kaldıracı aşılırsa max
kullanılır. Hacim 5 USDT altındaysa işlem atlanır.

**Kurallar**
- 20 coin taranır, her coinde aynı anda en fazla **1** işlem, toplamda en fazla **15** açık işlem (long + short birlikte).
- Aynı mumda birden fazla işlem açılıp kapanabilir (mum başına işlem sınırı ve zarar sonrası bekleme yok).

## 3) Açık pozisyonların diske kaydı

Açık her pozisyon `data/open_positions.json` dosyasına da yazılır (açılış zamanı,
Lose Exit seviyesi, açılış anındaki TP bilgisi gibi borsadan geri okunamayan bilgiler yeniden
başlatmada korunsun diye). Stop seviyesi ve likit fiyatı ise borsadan okunur.
Dosyada kaydı olmayan ama borsada bulunan pozisyonlar kayda alınır, stop'ları
ayarlanır ve Telegram'dan bildirilir. Bu pozisyonların gerçek açılış anı bilinmediği
için Lose Exit seviyesi **tahmini** olarak kayıt anındaki Silver (long) / Gold (short)
çizgisinden alınır ve bildirimde "TAHMİNİ" yazar.

## 4) `config.py` içindeki önemli ayarlar
- `COINS`: 20 coin (BTC, ETH, SOL, XRP, SUI, ARB, NEAR, ADA, AAVE, AVAX, APT, TRUMP, ENA, TIA, TAO, HYPE, ATOM, WLD, INJ, CHZ). Bot açılırken Bybit'in canlı listesiyle karşılaştırır, bulunamayanları çıkarır ve Telegram'dan haber verir.
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
- Ana çizgi ve çizgi rengi grafikteki Q-Trend (2 ATR ayarıyla) ile birkaç coinde karşılaştırılmalı (TradingView'ın
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
