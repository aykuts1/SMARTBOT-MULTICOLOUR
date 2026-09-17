# Trend + ALMA + Tilson T3 Bot

Bybit Futures, 1 saatlik zaman dilimi, MAINNET. EMA21/50 trend+egim, ALMA9
tabanli hareketli kar-al bandi, Tilson T3 (0.7 / 2) renk tetikleyicili
giris/cikis.

## v2 guncellemeleri (bu surumde neler degisti)

- **Heikin Ashi kaldirildi**, yerine **Tilson T3** (Factor 0.7, Period 2)
  eklendi. Giris sinyali ve renk-flip kar cikisi artik T3'un rengine
  (bir onceki muma gore yukari=yesil / asagi=kirmizi) bakiyor.
- **Yeni cikis kurali:** Mum kapanis fiyatina gore pozisyon %4'ten fazla
  zarardaysa, o mum kapanisinda pozisyon kapatilir (`candle_close_loss_pct`).
- **Loss Exit (bot icinde, surekli/3 sn kontrol) %5.75'e cikti**
  (`loss_exit_pct`).
- **Borsaya girerken konan guvenlik stop-loss emri artik ayri bir parametre**
  ve %6'ya cikti (`broker_stop_loss_pct`) -- botun kendi Loss Exit'inden
  (`loss_exit_pct`) BAGIMSIZ.
- **Iki yonlu senkronizasyon artik sadece bot basladiginda degil, HER TAM MUM
  KAPANISINDA da calisiyor:** state.json ile Bybit'teki gercek acik
  pozisyonlar karsilastirilir -- borsada olup kendi kayitlarinda olmayan
  pozisyonlar (yetim) devreye alinir, kendi kayitlarinda olup borsada
  olmayanlar (dis etkenle kapanmis -- manuel veya likidasyon) kayittan/slot
  listesinden dusurulur. Ikisinde de Telegram'a bilgi mesaji gider.
- **Duzeltilen hata:** yetim pozisyon (borsada var, botun kendi kaydinda
  yoktu) kapatilirken `margin_usdt` bilinmedigi icin kar/zarar hesaplamasi
  hata veriyordu; bu yuzden pozisyon borsada kapansa bile bot bunu fark
  edemiyor, tekrar tekrar kapatmaya calisiyordu. Artik yetim pozisyon takibe
  alinirken `margin_usdt`, config'deki kaldiraca gore (qty * giris fiyati /
  kaldirac) tahmin edilip kaydediliyor; ayrica `close_position` da bu alan
  herhangi bir sebeple bos gelirse cokmeyecek sekilde savunmaci hale
  getirildi.
- **Bakiye hesabi bilincli olarak degistirilmedi** -- pozisyon buyuklugu hala
  "kullanilabilir/cekilebilir bakiyenin %'si" uzerinden hesaplaniyor (toplam
  equity degil), sadece yuzde asagida v3'te degisti.

## v3 guncellemeleri

- **Coin listesi daraltildi (10 coin):** APTUSDT, CHZUSDT, ENAUSDT,
  TRUMPUSDT, ETHUSDT, SOLUSDT, BTCUSDT, WLDUSDT, TRXUSDT, SUIUSDT.
- **Pozisyon buyuklugu %5'ten %8'e cikti** (`position_size_pct`), kaldirac
  20x'te ayni kaldi.
- **Max acik pozisyon 16'dan 10'a dustu** (`max_positions`) -- coin listesi
  10'a indigi icin zaten her coinde 1 pozisyon kuraliyla ust sinir da 10 oldu.
- **Yeni Telegram komutlari:** `/coinrapor` (her coin icin ozet istatistik)
  ve `/rapor<coin>` (orn. `/raporbtc` -- tek coin icin detayli dokum).
  Detaylar yukaridaki "Telegram komutlari" bolumunde.
- `/pozisyonlar` raporundaki "acik pozisyon / max" sayisi artik sabit 16
  degil, config'deki `max_positions` degerini kullaniyor (bu sayede yukaridaki
  degisiklikle otomatik olarak dogru gosteriyor).

## Kurulum (Railway)

1. Bu dosyalarin hepsini GitHub reponuza yukleyin (tek klasor, alt klasor yok).
2. Railway'de asagidaki ortam degiskenlerinin tanimli oldugundan emin olun:
   - `BYBIT_API_KEY`, `BYBIT_API_SECRET` (senin belirttigin gibi zaten tanimli)
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (varsa diger botlarinla ayni
     Telegram bot/kanali kullanabilirsin, yoksa yeni bir BotFather botu
     olusturup token'ini buraya ekle)
3. Start command: `python main.py`
4. `requirements.txt` otomatik kurulacaktir.

## Telegram komutlari

- `/rapor` -> coin bazli toplam kar/zarar dokumu (kisa ozet)
- `/pozisyonlar` -> su an acik olan pozisyonlar, anlik kar/zararlariyla
- `/coinrapor` -> takip edilen HER coin icin: islem sayisi, kazanan/kaybeden
  sayisi, basari orani, ortalama kar/zarar % ve toplam PnL (USDT)
- `/rapor<coin>` (orn. `/raporbtc`, `/raporsol`) -> tek bir coin icin cok
  detayli rapor: genel istatistikler, en iyi/en kotu islem, ortalama islem
  suresi, varsa acik pozisyonun anlik durumu, son 10 islemin tek tek listesi

Otomatik gelenler: pozisyon acildi/kapandi, slot dolu, bakiye yetersiz,
yetim pozisyon bulundu, dis etkenle kapanma, 12 saatlik / 24 saatlik /
haftalik ozet.

## Testler

Ag baglantisi gerektirmeyen mantik testleri (indikatorler, sinyaller,
pozisyon boyutlandirma) icin:

```
pip install pytest
pytest test_bot.py -v
```

45 test de gecmeli. Bybit/Telegram baglantisi gerektiren kisimlar (exchange.py,
telegram_notify.py, main.py) bu ortamda ag erisimi olmadigi icin CANLI test
EDILEMEDI -- pybit'in resmi V5 metod/parametre isimleri kullanildi, ama ilk
gercek calistirmada asagidaki noktalara dikkat et.

## Ilk canli calistirmada mutlaka izle

- **Margin/pozisyon modu ayarlari**: `exchange.py` icindeki
  `ensure_leverage_and_margin_mode` fonksiyonu hesabini CROSS margin +
  one-way (hedge olmayan) moda gecirmeyi dener. Hesap turune (Unified/Classic)
  gore bu cagrilarin tam davranisi degisebilir. Hata olursa bot COKMEZ (try/except
  ile sarili, loglanir) ama Railway loglarini ilk saatlerde kontrol et.
- **Iki ayri stop-loss var, karistirma:** `loss_exit_pct` (%5.75) botun
  kendisi calisirken 3 saniyede bir kontrol ettigi ve tetiklenince kendisinin
  kapattigi seviye. `broker_stop_loss_pct` (%6) ise pozisyon acilirken
  Bybit'e AYRICA gonderilen gercek stop-loss emri -- bot cokerse/offline
  kalirsa diye son bir guvenlik agi. Hareketli ALMA TP bandi borsa emriyle
  konamaz (sabit deger degil), o her zaman bot calisirken yonetilir -- yani
  **bot offline iken TP calismaz, sadece broker_stop_loss_pct calisir**.
- **Bakiye alani**: `get_available_balance` UNIFIED hesap turunu varsayiyor.
  Hesabin farkli bir tipteyse (ornegin Classic) bu kismi birlikte duzeltiriz.
- Yeni deploy sonrasi ilk 1-2 saat pozisyon acilis/kapanislarini Telegram'dan
  yakindan takip etmeni oneririm. Ayrica ayni deploy'da acik olan pozisyonlar
  icin trend-flip/T3-renk-flip/mum-kapanis-zarar kontrolleri, redeploy
  sonrasi ILK mum kapanisinda degil, BIR SONRAKI tam mum kapanisinda
  baslar (yanlis/stale veriyle karar vermemek icin bilincli bir gecikme).
