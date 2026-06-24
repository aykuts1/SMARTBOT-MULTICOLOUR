# SMARTBOT — Teknik Dokümantasyon

Bu belge botun nasıl çalıştığını, hangi kararları neden verdiğini ve her bileşenin tam olarak ne yaptığını açıklar.

---

## İçindekiler

1. [Genel Yapı](#1-genel-yapı)
2. [Başlangıç Süreci](#2-başlangıç-süreci)
3. [Göstergeler](#3-göstergeler)
4. [Kırmızı Thread](#4-kırmızı-thread)
5. [Mavi Thread](#5-mavi-thread)
6. [Veri Çekme](#6-veri-çekme)
7. [İşlem Açma Mekanizması](#7-i̇şlem-açma-mekanizması)
8. [İşlem Kapama Mekanizması](#8-i̇şlem-kapama-mekanizması)
9. [Slot Limitleri](#9-slot-limitleri)
10. [Emniyet Kemeri — Exchange SL](#10-emniyet-kemeri--exchange-sl)
11. [SL Guard Loop](#11-sl-guard-loop)
12. [Pozisyon Senkronizasyonu](#12-pozisyon-senkronizasyonu)
13. [Config İzleme](#13-config-i̇zleme)
14. [Sağlık Kontrolü](#14-sağlık-kontrolü)
15. [Periyodik Raporlar](#15-periyodik-raporlar)
16. [Telegram Komutları](#16-telegram-komutları)
17. [İşlem Geçmişi](#17-i̇şlem-geçmişi)
18. [Bybit API Katmanı](#18-bybit-api-katmanı)
19. [Dosya Yapısı](#19-dosya-yapısı)
20. [Parametreler](#20-parametreler)
21. [Deploy — Railway](#21-deploy--railway)

---

## 1. Genel Yapı

Bot iki bağımsız stratejiden oluşur: **Kırmızı Thread** ve **Mavi Thread**. Her iki thread de aynı fiyat verisini ve aynı gösterge hesaplamalarını kullanır, ancak birbirinden tamamen bağımsız kararlar alır ve açtığı işlemleri yalnızca kendisi takip eder.

Bot Python ile yazılmıştır. GitHub üzerinden Railway'e deploy edilir ve gerçek Bybit Futures piyasasında çalışır (testnet değil). Tüm API anahtarları Railway ortam değişkenlerinden okunur.

Bot başladığında tek bir ana process çalıştırır. Bu process içinde birden fazla thread paralel olarak çalışır:

- **price_poller thread**: 5 saniyede bir fiyat çeker, 30 dakikalık mum kapanışlarını tespit eder
- **scan_loop thread**: Her 5 saniyede bir tüm coinler için on_tick çağırır
- **report_loop thread**: Saatlik/6 saatlik/12 saatlik/24 saatlik raporları gönderir
- **health_loop thread**: Fiyat verisinin kesilip kesilmediğini kontrol eder
- **config_watch thread**: config.json dosyasının değişip değişmediğini izler
- **sl_guard thread**: Pozisyonların kayıplarını izler, emniyet kapanışı yapar
- **telegram polling thread**: Telegram komutlarını dinler

Tüm bu thread'ler daemon olarak çalışır, yani ana process kapandığında otomatik olarak kapanırlar.

---

## 2. Başlangıç Süreci

Bot `main.py` dosyasındaki `BotManager.run()` fonksiyonu ile başlar. Başlangıç adımları sırasıyla şu şekilde işler:

**Adım 1 — Bybit Bağlantı Testi**
Bybit API'sine `get_server_time` çağrısı yapılır. Yanıt gelmezse veya hata dönerse bot başlamaz.

**Adım 2 — Coin Listesi ve Instrument Bilgisi**
config.json'daki `coin_listesi` okunur. Her coin için Bybit'ten instrument bilgisi çekilir: tick size (fiyat adımı), minimum miktar ve miktar adımı. Bu bilgiler emir gönderirken kullanılır. Her coin arasında 0.1 saniye beklenir (rate limit koruması).

**Adım 3 — Hesap Ayarları**
Her coin için üç şey yapılır:
- **Hedge mode** aktif edilir (mode=3). Bu sayede aynı coinde hem long hem short pozisyon aynı anda açılabilir.
- **Cross margin** modu ayarlanır (tradeMode=0). Pozisyonlar cüzdanın tamamını teminat olarak kullanır, isolated değil.
- **Kaldıraç** ayarlanır. config.json'daki `kaldirac` değeri (varsayılan 50x) hem Buy hem Sell tarafı için set edilir. Her adım arasında 0.15 saniye beklenir.

**Adım 4 — Bakiye Okuma**
Bybit UNIFIED hesabındaki USDT bakiyesi okunur. Hem toplam bakiye hem de kullanılabilir bakiye alınır. Bakiye alınamazsa bot başlamaz.

**Adım 5 — Başlangıç Mumlarını Çekme ve Gösterge Hesaplama**
Her coin için son 200 adet 30 dakikalık mum verisi Bybit'ten çekilir. Mumlar `data_pool`'a kaydedilir. Ardından her coin için göstergeler hesaplanır ve `data_pool`'a kaydedilir. Her coin arasında 0.2 saniye beklenir.

**Adım 6 — Mevcut Pozisyon Kontrolü**
Bybit'teki açık pozisyonlar kontrol edilir. Her pozisyon, `order_link_id` alanına bakılarak botun kendi işlemi mi yoksa dışarıdan açılmış mı olduğu anlaşılır. Botun kendi işlemleri `KIRMIZI_` veya `MAVI_` ile başlar. Yabancı pozisyonlara bot dokunmaz, yalnızca Telegram'a bildirim gönderir.

**Adım 7 — Price Poller Başlatma**
Fiyat çekme döngüsü başlar. Hem 5 saniyelik periyodik fiyat güncellemesi hem de mum kapanışı tespiti aktif olur.

**Adım 8 — Bot Durumu**
`running = True` yapılır, başlangıç zamanı kaydedilir, günlük istatistiklere başlangıç bakiyesi yazılır.

**Adım 9 — Telegram Bot Başlatma**
Telegram komutları dinlenmeye başlanır. Önce `deleteWebhook` çağrısı yapılır (Railway'de webhook kalıntısı olabilir), ardından polling başlar.

**Adım 10 — Başlangıç Bildirimi**
Telegram'a bot başladı mesajı gönderilir: bakiye, marjin oranı, kaldıraç, ekosistem durumları, açık pozisyon sayısı.

**Adım 11 — Arka Plan Thread'leri**
scan_loop, report_loop, health_loop, config_watch ve sl_guard thread'leri başlatılır.

**Adım 12 — Ana Döngü**
Bot bir `threading.Event` üzerinde bekler. `Ctrl+C` veya `SIGTERM` sinyali alındığında döngüden çıkar ve kapatma işlemi başlar.

---

## 3. Göstergeler

Her mum kapanışında tüm coinler için göstergeler yeniden hesaplanır. Hesaplama `indicators.py` dosyasındaki `compute_all_indicators` fonksiyonu tarafından yapılır. Sonuçlar `data_pool`'a kaydedilir ve hem Kırmızı hem de Mavi Thread bu verilere erişir.

### EMA 21 ve EMA 50

Klasik Üstel Hareketli Ortalama (EMA) formülü kullanılır:

```
EMA[i] = (Kapanış[i] - EMA[i-1]) × çarpan + EMA[i-1]
çarpan = 2 / (periyot + 1)
```

İlk değer, ilk `periyot` sayıda mumun aritmetik ortalamasıdır. EMA 21 için çarpan 2/22 ≈ 0.0909, EMA 50 için 2/51 ≈ 0.0392.

### Merkez Çizgi

Her mumda:

```
Merkez Çizgi = (EMA 21 + EMA 50) / 2
```

### Merkez Çizgi Rengi

EMA 21'in Merkez Çizgiye göre konumu renge dönüştürülür:

- EMA 21 > Merkez Çizgi ise renk **"green"** (LONG yön)
- EMA 21 ≤ Merkez Çizgi ise renk **"red"** (SHORT yön)

Bu karşılaştırma her mum için ayrı ayrı yapılır, böylece geçmişe dönük renk dizisi elde edilir. Renk değişimi ise bir önceki mum ile mevcut mumun renklerinin farklı olmasıyla tespit edilir.

### ATR 14

14 periyotluk Average True Range hesaplanır. True Range şu şekilde hesaplanır:

```
TR[0] = Yüksek[0] - Düşük[0]
TR[i] = max(Yüksek[i] - Düşük[i],  |Yüksek[i] - Kapanış[i-1]|,  |Düşük[i] - Kapanış[i-1]|)
```

ATR, TR değerlerinin Wilder smoothing yöntemiyle ortalamasıdır:

```
ATR[14] = ortalama(TR[0..13])
ATR[i]  = (ATR[i-1] × 13 + TR[i]) / 14
```

### Diş Çizgiler

```
Üst Diş = Merkez Çizgi + 1 × ATR 14
Alt Diş  = Merkez Çizgi - 1 × ATR 14
```

### Winrate Çizgileri

```
Üst Winrate = Merkez Çizgi + 6 × ATR 14
Alt Winrate  = Merkez Çizgi - 6 × ATR 14
```

Çarpanlar config.json'daki `indicators` bölümünden okunur ve değiştirilebilir.

---

## 4. Kırmızı Thread

Kırmızı Thread, 30 dakikalık mum kapanışlarını takip eder. Giriş ve çıkış mantığının büyük kısmı mum kapanışında çalışır, ancak chandelier ve stop loss kontrolü anlık fiyatla yapılır.

### Giriş Mantığı

Mum kapandığında `on_candle_close` çağrılır. Göstergelerden `center_color` dizisi alınır ve son iki değer karşılaştırılır:

- `colors[-2]` (önceki mum) yeşil, `colors[-1]` (yeni kapanan mum) kırmızı → **SHORT açılır**
- `colors[-2]` kırmızı, `colors[-1]` yeşil → **LONG açılır**
- İki renk aynıysa ya da herhangi biri boşsa hiçbir şey yapılmaz

Renk değişimi tespit edildiğinde önce o coindeki mevcut Kırmızı işlem varsa kapatılır (çıkış sebebi `renk_degisimi`), ardından yeni yönde işlem açılır.

### Slot Kontrolü

İşlem açılmadan önce iki kural kontrol edilir:

1. Toplamda açık Kırmızı işlem sayısı `max_islem` (varsayılan 10) değerine ulaşmışsa yeni işlem açılmaz, Telegram'a slot dolu bildirimi gönderilir.
2. Aynı coinde zaten bir Kırmızı işlem varsa (yeni açılana kadar kapanmadıysa) ikinci işlem açılmaz.

### Çıkış Koşulları — Stop Loss

Anlık fiyatla her 5 saniyede bir kontrol edilir. Kâr/Zarar yüzdesi şu formülle hesaplanır:

```
Short için: pnl_pct = (giriş_fiyatı - anlık_fiyat) / giriş_fiyatı
Long için:  pnl_pct = (anlık_fiyat - giriş_fiyatı) / giriş_fiyatı
```

`pnl_pct ≤ -0.02` (yani %2 zarar) olursa işlem anında kapatılır (sebep: `stop_loss`).

### Çıkış Koşulları — Take Profit

`pnl_pct ≥ 0.10` (yani %10 kâr) olursa işlem kapatılır (sebep: `take_profit`).

### Çıkış Koşulları — Chandelier Trailing Stop

Bu mekanizma üç aşamada çalışır:

**Aşama 1 — Chandelier Aktif Hale Gelir (%5 kâr)**
`pnl_pct ≥ 0.05` olduğunda chandelier aktif hale gelir. O anki fiyat `extreme_price` olarak kaydedilir. Trailing mesafesi `chandelier_trail_pct = 0.02` (%2) olarak ayarlanır.

**Aşama 2 — Extreme Fiyat Güncellenir**
Her 5 saniyelik tick'te:
- Short işlemde: Fiyat `extreme_price`'dan daha aşağıya giderse `extreme_price` güncellenir (fiyat daha da düştü, bu iyiye işaret).
- Long işlemde: Fiyat `extreme_price`'dan daha yukarıya giderse `extreme_price` güncellenir.

**Aşama 3 — %7 Kârda Chandelier Sıkışır**
`pnl_pct ≥ 0.07` olduğunda trailing mesafesi `chandelier_trail_pct = 0.01` (%1) olarak güncellenir. Bu, kârı koruma altına alır.

**Chandelier Tetiklenme**
```
Short: eğer anlık_fiyat ≥ extreme_price × (1 + chandelier_trail_pct) → Çıkış
Long:  eğer anlık_fiyat ≤ extreme_price × (1 - chandelier_trail_pct) → Çıkış
```

Chandelier tetiklenirse işlem kapatılır (sebep: `chandelier`).

Chandelier aktif olduğunda Telegram'a bildirim gönderilir: hangi coinde, hangi yönde, giriş fiyatı, o anki fiyat ve chandelier seviyesi.

### Renk Değişimi ile Çıkış ve Yeni Giriş

Mum kapanışında renk değişimi olduğunda:
1. Mevcut işlem kapatılır (sebep: `renk_degisimi`)
2. Slot uygunsa yeni yönde hemen işlem açılır

Bu iki işlem birbiri ardına yapılır, aralarında bekleme yoktur.

### Eş Zamanlılık Güvenliği

Kırmızı Thread'deki tüm işlem listesi değişiklikleri `threading.Lock()` ile koruma altındadır. `on_candle_close` ve `on_tick` farklı thread'lerde çalışır. Her iki fonksiyon da bir işlemi kapatmadan önce önce listeden çıkarır (lock alarak), sonra API çağrısını yapar. Böylece aynı işlemin iki kez kapatılması önlenir.

---

## 5. Mavi Thread

Mavi Thread, Kırmızı Thread'den tamamen bağımsız çalışır. Kendi işlemlerini yalnızca kendisi takip eder ve kapatır. İki aşamalı bir giriş mantığı vardır: önce flag, sonra onay.

### Flag Sistemi

Flag, "fiyatın merkez çizgiyi geçtiğini" hatırlatan bir işaret biridir. Her coin için en fazla bir flag açık olabilir; yeni flag açılırsa eski flag silinir.

**Flag Açılma Koşulu (Tick bazlı)**
Her 5 saniyede bir, her coin için anlık fiyat ile Merkez Çizgi'nin son değeri karşılaştırılır. Bir önceki 5 saniyeden bu yana fiyatın Merkez Çizgiye göre konumu değiştiyse:

- Fiyat, Merkez Çizginin üstünden altına geçtiyse → **Mavi Short Flag** açılır
- Fiyat, Merkez Çizginin altından üstüne geçtiyse → **Mavi Long Flag** açılır

Bu cross tespiti, `_prev_above` sözlüğüne kaydedilen bir önceki tick'teki konum ile mevcut tick'teki konumun karşılaştırılmasıyla yapılır.

**Flag Silinme Koşulları**
- Ters yönde yeni flag açılırsa eski flag otomatik silinir.
- Giriş koşulları sağlanıp işlem açılırsa flag silinir.

### Giriş Mantığı

Mum kapandığında `on_candle_close` çağrılır. O coin için açık bir flag varsa üç koşul birden kontrol edilir:

**Mavi Short Girişi:**
1. O coinde Mavi Short Flag açık olmalı
2. Merkez Çizgi rengi `"red"` olmalı
3. Kapanan mumun kapanış fiyatı **Alt Diş Bandın altında** olmalı (`close < lower_tooth[-1]`)

**Mavi Long Girişi:**
1. O coinde Mavi Long Flag açık olmalı
2. Merkez Çizgi rengi `"green"` olmalı
3. Kapanan mumun kapanış fiyatı **Üst Diş Bandın üstünde** olmalı (`close > upper_tooth[-1]`)

Üç koşul da sağlanırsa işlem açılır ve flag silinir. Koşullardan herhangi biri sağlanmadıysa flag açık kalmaya devam eder.

### Çıkış Koşulları — Diş Bant

Anlık fiyatla her 5 saniyede bir kontrol edilir:

- **Short işlem**: Fiyat Üst Diş Banda ulaşır veya geçerse işlem kapatılır (sebep: `ust_dis_bant`). Bu genellikle zararda bir çıkıştır.
- **Long işlem**: Fiyat Alt Diş Banda ulaşır veya altına düşerse işlem kapatılır (sebep: `alt_dis_bant`). Bu genellikle zararda bir çıkıştır.

### Çıkış Koşulları — Winrate Çizgisi

- **Short işlem**: Fiyat Alt Winrate Çizgisine ulaşır veya altına düşerse işlem kapatılır (sebep: `alt_winrate`). Bu kârlı bir çıkıştır (Merkez Çizgi'nin çok altı).
- **Long işlem**: Fiyat Üst Winrate Çizgisine ulaşır veya üstüne çıkarsa işlem kapatılır (sebep: `ust_winrate`). Bu kârlı bir çıkıştır.

### Çıkış Koşulları — %5 Kâr

`pnl_pct ≥ 0.05` (yani %5 kâr) olursa işlem kapatılır (sebep: `kar_al`).

### Slot Kontrolü

Kırmızı Thread ile aynı mantık: toplamda 10 Mavi işlem limiti ve aynı coinde 1 Mavi işlem limiti.

### Telegram Bildirimi

İşlem açılırken `send_trade_opened` çağrısıyla Lose Exit (Üst/Alt Diş) ve Winrate seviyeleri de bildirilir. Bu seviyeler işlem açıldığı anki gösterge değerlerine göre hesaplanır.

---

## 6. Veri Çekme

`price_poller.py` dosyasındaki `PricePoller` sınıfı iki tür veri çekme işlemi yapar.

### 5 Saniyelik Periyodik Fiyat Güncelleme

`_loop` metodu `_stop_event.wait(5)` ile 5 saniyede bir döner. Her döngüde `_update_prices` çağrılır.

`_update_prices` metodu Bybit'in `get_tickers(category="linear")` endpoint'ini çağırır. Bu endpoint tüm USDT linear kontratların anlık fiyatlarını tek seferde döner. Bot listedeki tüm coinleri bu sonuçtan filtreler ve `data_pool.update_price(symbol, price)` ile kaydeder. Bu işlem tek bir API çağrısıyla tüm coinlerin fiyatını günceller.

### Mum Kapanışı Sonrası Veri Çekme

Aynı 5 saniyelik döngü içinde `_check_candle_close` de çağrılır.

`_current_boundary` metodu, mevcut Unix zamanını 30 dakikalık dilimlere göre hizalar. Yeni bir dilim başladıysa (yani `current > last_boundary`) mum kapanışı gerçekleşmiştir.

Mum kapanışı tespit edildiğinde ayrı bir thread başlatılır: 5 saniye bekler (mumun borsada kesinleşmesi için) ve ardından `_fetch_and_trigger` çalışır. Bu metod her coin için Bybit'ten son 3 mumu çeker ve `candles[-2]`'yi yani kapanan mumu alır. `on_candle_close(symbol, closed_candle)` çağrılır.

Her coin arasında 0.15 saniye beklenir (rate limit koruması).

### Veri Havuzu (DataPool)

Hem fiyatlar hem de mumlar `data_pool.py`'daki `DataPool` sınıfında tutulur. Tüm okuma ve yazma işlemleri `threading.Lock()` ile korumalıdır.

- Mum listesi en fazla 300 mum tutar, bu dolduğunda en eski 50 mum atılır ve 250 mum kalır.
- Göstergeler de ayrı bir sözlükte tutulur: `_indicators[symbol]`.
- Anlık fiyatlar `_prices[symbol]` sözlüğünde tutulur.

---

## 7. İşlem Açma Mekanizması

Her iki thread de işlem açmak istediğinde `trade_executor.py`'daki `TradeExecutor.open_trade` fonksiyonunu çağırır.

**Adım 1 — Bakiye Okuma**
Her işlem açılışında güncel bakiye Bybit'ten okunur (1 saniyelik cache mevcuttur, aynı saniye içinde birden fazla çağrı yapılırsa cache döner).

**Adım 2 — Pozisyon Büyüklüğü Hesaplama**

```
Marjin = Toplam Bakiye × marjin_orani   (varsayılan %5)
Notional = Marjin × kaldıraç           (varsayılan 50x)
Miktar = Notional / Giriş Fiyatı
```

Miktar, coin'in `qty_step` değerine göre aşağıya yuvarlanır (ROUND_DOWN). Örneğin `qty_step = 0.001` ise 0.1234567 → 0.123 olur.

**Adım 3 — Bakiye Yeterliliği**
Hesaplanan marjin, kullanılabilir bakiyeyi aşıyorsa işlem açılmaz, Telegram'a yetersiz bakiye bildirimi gönderilir.

**Adım 4 — Minimum Miktar Kontrolü**
Hesaplanan miktar, coin'in minimum sipariş miktarından (`min_qty`) küçükse işlem açılmaz, Telegram'a bildirim gönderilir.

**Adım 5 — Stop Loss Fiyatı Hesaplama**
Exchange'e gönderilecek güvenlik SL fiyatı hesaplanır:

```
Short için SL: giriş_fiyatı × (1 + stop_loss_orani)   → varsayılan %5 yukarı
Long için SL:  giriş_fiyatı × (1 - stop_loss_orani)   → varsayılan %5 aşağı
```

Bu fiyat tick_size'a göre güvenli yönde yuvarlanır: Short için yukarıya (ROUND_UP), Long için aşağıya (ROUND_DOWN). Böylece SL her zaman biraz daha geniş tutulur, erken tetiklenmez.

**Adım 6 — Order Link ID Üretimi**
Her işlem için benzersiz bir `order_link_id` üretilir:

```
KIRMIZI_SHORT_BTCUSDT_1750000000
MAVI_LONG_ETHUSDT_1750000001
```

Bu kimlik bota ait işlemleri tanımlamak için kullanılır.

**Adım 7 — Emir Gönderme**
Bybit'e Market emri gönderilir (IOC — Immediate or Cancel). Emir parametreleri:
- `orderType: Market`
- `timeInForce: IOC`
- `positionIdx: 1` (Long) veya `2` (Short) — hedge mode için gereklidir
- `orderLinkId: <üretilen id>`

**Adım 8 — Yeniden Deneme**
Emir başarısız olursa `islem_acma_deneme` kadar (varsayılan 3) yeniden denenir. Denemeler arası `islem_acma_bekleme_sn` (varsayılan 2 saniye) beklenir. Tüm denemeler başarısız olursa Telegram'a hata bildirimi gönderilir.

**Önemli Not:** `place_order` içinde SL parametresi **gönderilmez**. SL emri doğrudan exchange'e değil, bot içi emniyet mekanizmasıyla ayrıca yönetilir. Asıl SL, exchange'e `set_trading_stop` ile gönderilir.

---

## 8. İşlem Kapama Mekanizması

`TradeExecutor.close_trade` hem Trade objesi hem de dict kabul eder. Kapatma işlemi sonuç alana kadar süresiz tekrar eder (sonsuz döngü), çünkü açık bir pozisyonu kapatamamak kritik bir sorun olur.

**Kapatma Adımları:**
1. `close_position` çağrılır: ters yönde reduce-only market emri gönderilir.
2. Başarılı olursa PnL hesaplanır, komisyon hesaplanır, `trade_history.record` ile diske kaydedilir, sonuç döndürülür.
3. Başarısız olursa ilk hatada Telegram'a bildirim gönderilir. Sonraki hatalarda yalnızca `kapatma_hatasi_bildirim_aralik_sn` (varsayılan 300 saniye) geçtikten sonra yeni bildirim gönderilir.
4. Bybit error code 110017 ("pozisyon zaten kapalı") durumu başarılı sayılır, state temizlenir.

**Asenkron Kapatma:**
`close_trade_async` metodu kapatmayı ayrı bir thread'de başlatır. Aynı key'e (symbol_ecosystem_side) ait bir thread zaten çalışıyorsa yeni thread başlatılmaz.

---

## 9. Slot Limitleri

Her iki thread için ayrı limit vardır.

**Coin bazlı limit:** Aynı coinde Kırmızı 1, Mavi 1 işlem açılabilir. Kırmızı Thread için: renk değişiminde mevcut işlem kapatılıp yeni yönde açılır, bu sayede limit aşılmaz.

**Toplam limit:** Kırmızı için 10, Mavi için 10. Limit dolduğunda yeni sinyal gelirse işlem atlanır, Telegram'a bildirim gönderilir.

Limitler config.json'dan okunur (`kirmizi.max_islem` ve `mavi.max_islem`) ve çalışırken config güncellenirse yeni değer anında etkin olur.

---

## 10. Emniyet Kemeri — Exchange SL

Her işlem açıldığında borsaya %5 Stop Loss emri gönderilmesi planlanmıştır. Bu, botun çökmesi veya bağlantı kopması durumunda pozisyonun borsanın kendi mekanizmasıyla kapanmasını sağlar.

`config.json`'da `global.stop_loss_orani = 0.05` olarak ayarlanmıştır. `trade_executor.py`, bu değeri okuyarak giriş fiyatına göre SL fiyatını hesaplar.

**Önemli:** `bybit_client.place_order` içinde SL parametresi gönderilmiyor. SL ayrıca `bybit_client.set_position_sl` fonksiyonuyla set edilebilir. Mevcut kodda emir gönderildikten sonra ayrı bir SL set çağrısı yapılmamaktadır. Bu nedenle exchange SL'i ayrıca yönetmek gerekiyorsa `trade_executor.open_trade` içine `set_position_sl` çağrısı eklenmelidir.

---

## 11. SL Guard Loop

`main.py`'daki `_sl_guard_loop` her 5 saniyede bir çalışır. Bybit'ten tüm açık pozisyonları çeker ve her biri için şu kontrolü yapar:

```
loss_pct = -unrealised_pnl / (entry_price × size)
```

Eğer `loss_pct ≥ stop_loss_orani` (varsayılan %5) ise pozisyon kapatılır.

Bu kapatma gerçekleştiğinde:
- Bot'un ekosistem listelerinden o işlem kaldırılır
- `trade_history.record` ile diske kaydedilir (sebep: `SL Emniyet Kemeri`)
- Telegram'a `send_sl_guard_close` bildirimi gönderilir

SL guard, exchange SL'in ikinci katmandaki yazılım güvencesidir.

---

## 12. Pozisyon Senkronizasyonu

`_health_loop` her 5 dakikada bir `_sync_positions` fonksiyonunu çağırır.

Bu fonksiyon Bybit'teki gerçek pozisyonları ile botun takip ettiği işlemleri karşılaştırır. Bot takibinde olup Bybit'te olmayan bir işlem "dış kapanış" olarak tespit edilir. Bu durum SL tetiklemesi, manuel kapatma veya likidite ile olabilir.

Dış kapanış tespit edildiğinde:
- İşlem ekosistem listesinden kaldırılır
- Telegram'a `send_external_close` bildirimi gönderilir

Bu senkronizasyon, botun gerçeklikten kopmamasını sağlar.

---

## 13. Config İzleme

`_config_watch_loop` her 5 saniyede bir `config.json` dosyasının son değiştirilme zamanını (`os.path.getmtime`) kontrol eder.

Değişiklik tespit edilirse yeni config okunur ve `_apply_config` çağrılır. Bu fonksiyon:
- `trade_executor` için yeni config yükler
- Kırmızı ve Mavi Thread için `reload_config` çağırır

Config değişikliği açık işlemleri etkilemez, yalnızca yeni sinyal değerlendirmelerinde yeni parametreler kullanılır.

---

## 14. Sağlık Kontrolü

`_health_loop` her 30 saniyede bir çalışır ve `price_poller.seconds_since_last_price` değerini kontrol eder.

- Son fiyat güncellemesi 60 saniyeden eskiyse bağlantı kopuk sayılır, Telegram'a `send_connection_lost` gönderilir.
- Bağlantı geri geldiğinde Telegram'a `send_connection_restored` ve kesinti süresi gönderilir.

---

## 15. Periyodik Raporlar

Dört rapor türü vardır: 1 saatlik, 6 saatlik, 12 saatlik, 24 saatlik. Her biri config.json'dan açılıp kapatılabilir.

Her rapor şunları gösterir:
- Güncel bakiye ve dönem PnL'i
- Açılan, kapanan, atlanan işlem sayıları
- Kırmızı ve Mavi thread bazlı PnL özeti
- Kazanan/kaybeden işlem sayıları

12 ve 24 saatlik raporlarda ek olarak çıkış sebeplerinin dağılımı da gösterilir: stop_loss, take_profit, chandelier, renk_degisimi, ust_dis_bant, alt_dis_bant, alt_winrate, ust_winrate, kar_al.

Her dönem raporu gönderildikten sonra o dönemin istatistikleri sıfırlanır. Günlük istatistikler 24 saatlik rapor gönderildiğinde sıfırlanır.

---

## 16. Telegram Komutları

Tüm komutlar `telegram_bot.py`'da tanımlanmıştır. Polling yöntemiyle çalışır: 1 saniye timeout ile `getUpdates` endpoint'i sürekli çağrılır.

### Bilgi Komutları

`/durum` — Botun çalışma durumu, bakiye, günlük PnL, her iki thread'in aktif/pasif durumu ve açık işlem sayıları. Ayrıca son fiyat güncellemesinin kaç saniye önce geldiği gösterilir.

`/anlik` — Günlük PnL, açık pozisyon sayısı, bugün açılan/kapanan/atlanan işlem sayıları, thread bazlı PnL.

`/bakiye` — Toplam bakiye, kullanılan marjin, serbest bakiye, işlem başına marjin (%5).

`/pnl` — Günlük PnL detayı, thread bazlı PnL, winrate yüzdesi ve toplam komisyon.

`/islemler` — Thread bazlı gruplandırılmış açık işlemler. Her işlem için giriş fiyatı, anlık fiyat, PnL ve süre gösterilir.

`/pozisyonlar` — Tüm açık pozisyonların sıralı listesi.

`/borsada` — Borsada açık olup bot takibinde olmayan pozisyonlar. Eski bot işlemleri ve tamamen yabancı pozisyonlar ayrı gösterilir.

`/rapor` — 1s/6s/12s/24s dönemleri için thread bazlı kapanan işlem sayısı, kazanma/kayıp oranı ve PnL.

`/flagler` — Mavi Thread'deki açık flagler. Her flag için coin, yön (SHORT/LONG) ve ne kadar önce açıldığı gösterilir.

`/log` — Son 10 önemli olay (bot başlatma, durdurma, config güncelleme, bağlantı kopma/gelme vb.).

`/son100` — Son 100 kapanan işlemin detayı: coin, yön, ekosistem, giriş/çıkış fiyatı, PnL, çıkış sebebi, tarih. Ayrıca kapanış sebepleri özetlenir.

### Kontrol Komutları

`/durdur` — Onay ister. Onaylanırsa bot yeni işlem açmayı durdurur, açık işlemler Bybit'te kalmaya devam eder.

`/durdur_onayla` — Durdurma onayı.

`/baslat` — Durdurulmuş botu yeniden başlatır.

`/kapat_hepsi` — Onay ister. Onaylanırsa tüm açık pozisyonlar market emriyle kapatılır.

`/kapat_hepsi_onayla` — Toplu kapama onayı.

`/panic` — Onay ister. Onaylanırsa hem tüm pozisyonlar kapatılır hem de bot durdurulur.

`/panic_onayla` — Panic onayı.

`/iptal` — Bekleyen bir onayı iptal eder.

### Ekosistem Komutları

`/ekosistem_durdur kirmizi` — Kırmızı Thread'i durdurur. Açık işlemler takip edilmeye devam eder, yeni işlem açılmaz.

`/ekosistem_durdur mavi` — Mavi Thread'i durdurur.

`/ekosistem_baslat kirmizi` — Kırmızı Thread'i yeniden başlatır.

`/ekosistem_baslat mavi` — Mavi Thread'i yeniden başlatır.

`/yardim` — Tüm komutların listesi.

---

## 17. İşlem Geçmişi

Her kapanan işlem `trade_history.py` üzerinden `trade_history.json` dosyasına yazılır. Dosya JSON formatındadır. En fazla 500 kayıt tutulur, bu dolduğunda en eski kayıtlar silinir.

Her kayıt şu alanları içerir: zaman (Unix timestamp), coin, yön, ekosistem, giriş fiyatı, çıkış fiyatı, miktar, PnL ve çıkış sebebi.

Dosyaya erişim `threading.Lock()` ile korumalıdır. Birden fazla thread aynı anda yazmaya çalışsa da kilitleme sayesinde bozulma olmaz.

---

## 18. Bybit API Katmanı

`bybit_client.py` içindeki `BybitClient` sınıfı tüm Bybit API iletişimini kapsar. `pybit` kütüphanesinin `unified_trading.HTTP` sınıfını kullanır.

**Bakiye Caching:** Bakiye sorgusu saniyede birden fazla yapılabilir (çünkü her işlem açılışında okunur). Rate limit koruması için 1 saniyelik cache uygulanmıştır. Aynı saniye içinde gelen çağrılar cache'den döner.

**Hedge Mode:** `setup_account` içinde her coin için `switch_position_mode(mode=3)` çağrılır. Hedge mode, aynı coinde hem long hem short pozisyonun aynı anda açık olabilmesini sağlar. `positionIdx=1` long, `positionIdx=2` short pozisyon içindir.

**Emir Gönderme:** Tüm emirler market tipidir (anlık gerçekleşir), IOC (Immediate or Cancel) time-in-force ile gönderilir. Bu sayede kısmi dolum sorunu yaşanmaz.

**Hata 110017:** Bybit, zaten kapalı bir pozisyonu kapatmaya çalışıldığında 110017 kodu döner. Bu durum başarılı sayılır ve state temizlenir, çünkü pozisyon zaten kapalıdır.

---

## 19. Dosya Yapısı

```
SMARTBOT-MULTICOLOUR/
├── main.py              → Bot yönetimi, başlatma, arka plan thread'leri
├── ecosystem_red.py     → Kırmızı Thread (renk değişimi + chandelier)
├── ecosystem_blue.py    → Mavi Thread (flag sistemi + diş bant)
├── indicators.py        → EMA, ATR, Merkez Çizgi, Diş Bant, Winrate hesaplama
├── price_poller.py      → 5sn tick + mum kapanışı sonrası veri çekme
├── data_pool.py         → Fiyat ve gösterge veri havuzu
├── bybit_client.py      → Bybit REST API istemcisi
├── trade_executor.py    → İşlem açma ve kapama
├── telegram_bot.py      → Telegram komutları ve bildirimler
├── trade_history.py     → Kapanan işlem kaydı (trade_history.json)
├── utils.py             → Yardımcı fonksiyonlar (hesaplamalar, format, id)
├── logger_setup.py      → Log sistemi
├── config.json          → Tüm parametreler
├── deploy.bat           → Railway deploy scripti
└── trade_history.json   → Kapanan işlem veritabanı (otomatik oluşur)
```

---

## 20. Parametreler

Tüm parametreler `config.json` dosyasında tutulur. Bot çalışırken değiştirilebilir, değişiklik 5 saniye içinde otomatik uygulanır.

### global

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `kaldirac` | 50 | Kaldıraç katsayısı |
| `marjin_orani` | 0.05 | İşlem başına bakiyenin yüzde kaçı kullanılır |
| `stop_loss_orani` | 0.05 | Emniyet kemeri SL yüzdesi (exchange'e gönderilir) |
| `baslangic_mum_sayisi` | 200 | Başlangıçta çekilecek mum sayısı |
| `timeframe` | "30" | Mum periyodu (dakika) |
| `coin_listesi` | 20 coin | İşlem yapılacak coinler |
| `islem_acma_deneme` | 3 | Başarısız emir sonrası tekrar sayısı |
| `islem_acma_bekleme_sn` | 2 | Tekrarlar arası bekleme (saniye) |
| `islem_kapatma_bekleme_sn` | 2 | Kapama retry arası bekleme (saniye) |
| `kapatma_hatasi_bildirim_aralik_sn` | 300 | Kapama hatası Telegram bildirimleri arası minimum süre |

### kirmizi

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `aktif` | true | Thread aktif mi |
| `max_islem` | 10 | Toplam maksimum açık işlem sayısı |
| `sl_yuzde` | 0.02 | Stop Loss yüzdesi (%2) |
| `tp_yuzde` | 0.10 | Take Profit yüzdesi (%10) |
| `chandelier_baslangic` | 0.05 | Chandelier'ın aktif olduğu kâr yüzdesi (%5) |
| `chandelier_trail_1` | 0.02 | İlk trailing mesafesi (%2) |
| `chandelier_sikistir` | 0.07 | Chandelier'ın sıkıştığı kâr yüzdesi (%7) |
| `chandelier_trail_2` | 0.01 | Sıkışmış trailing mesafesi (%1) |

### mavi

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `aktif` | true | Thread aktif mi |
| `max_islem` | 10 | Toplam maksimum açık işlem sayısı |
| `tp_yuzde` | 0.05 | Take Profit yüzdesi (%5) |

### indicators

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `ema21_periyot` | 21 | EMA 21 periyodu |
| `ema50_periyot` | 50 | EMA 50 periyodu |
| `atr_periyot` | 14 | ATR periyodu |
| `dis_carpan` | 1.0 | Diş bant ATR çarpanı |
| `winrate_carpan` | 6.0 | Winrate çizgisi ATR çarpanı |

---

## 21. Deploy — Railway

Bot GitHub üzerinden Railway'e deploy edilir. `deploy.bat` scripti bu işlemi otomatikleştirir.

### deploy.bat Nasıl Çalışır

1. `git status` ile commit edilecek değişiklik var mı kontrol eder.
2. Değişiklik varsa commit mesajı istenir (boş bırakılırsa "update" kullanılır).
3. `git add .` ile tüm değişiklikler eklenir.
4. `git commit` yapılır.
5. `git push origin main` ile Railway'e gönderilir.
6. Push başarısız olursa 5 saniye bekleyip 3 kez yeniden dener.
7. Her adımın sonucu ekranda gösterilir.

### Railway Ortam Değişkenleri

Bu değişkenler Railway dashboard'dan ayarlanmalıdır, `config.json`'a yazılmaz:

| Değişken | Açıklama |
|---|---|
| `BYBIT_API_KEY` | Bybit API anahtarı |
| `BYBIT_API_SECRET` | Bybit API gizli anahtarı |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `TELEGRAM_CHAT_ID` | Mesajların gönderileceği chat ID |
| `BYBIT_TESTNET` | "true" veya "false" (varsayılan false = gerçek piyasa) |
