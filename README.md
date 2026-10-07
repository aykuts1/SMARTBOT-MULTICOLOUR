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
- Gold loss = ana + 2 ATR, Silver loss = ana − 2 ATR

**Giriş:** Fiyat Silver'a değerse **long**, Gold'a değerse **short**.

**Çıkış (hangisi önce olursa):**
| Çıkış | Long | Short |
|---|---|---|
| Kâr Alma | fiyat ana çizgiye gelince | fiyat ana çizgiye gelince |
| Hareketli Zarar | Silver loss'a gelince | Gold loss'a gelince |
| Lose Exit (sabit) | giriş − (TP mesafesi × 1,5) | giriş + (TP mesafesi × 1,5) |
| Stop Loss (borsada gerçek emir) | giriş − (lose exit mesafesi × 2) | giriş + (lose exit mesafesi × 2) |

TP mesafesi = açılış anında |giriş − ana çizgi|. Lose Exit ve Stop Loss açılışta
sabitlenir. Ana çizgi, Hareketli Zarar ve Kâr Alma canlıdır (çizgiyle birlikte kayar).

**Kaldıraç:** Açılış anındaki Silver loss (long) / Gold loss (short) mesafesine
göre: fiyat o çizgiye gelirse kayıp yaklaşık stake kadar olsun. Coin max
kaldıracı aşılırsa max kullanılır. Hacim 5 USDT altındaysa işlem atlanır.

**Kurallar**
- 40 coin taranır, her coinde aynı anda en fazla **1** işlem, toplamda en fazla **20** açık işlem (long + short birlikte).
- Aynı mumda birden fazla işlem açılıp kapanabilir.
- **Zararla kapanan coin** (Hareketli Zarar / Lose Exit / Stop Loss), o mum bitene
  kadar yeni işlem açmaz. Kârla (Kâr Alma) kapanan coin beklemez.
- Stake tablosu eskisi gibi (toplam varlığa göre, sınır değerler üst bareme girer).

## 3) `config.py` içindeki önemli ayarlar
- `COINS`: 40 coin. Bot açılırken Bybit'in canlı listesiyle karşılaştırır, bulunamayanları çıkarır ve Telegram'dan haber verir.
- `QT_INTRABAR_STEP`: `True` = gösterge canlı mumda Pine'daki gibi davranır (varsayılan). `False` = ana çizgi sadece mum kapanınca kayar, mum içinde çizgiler sabit kalır.
- `FIXED_LOSE_EXIT_TP_MULT = 1.5`, `SAFETY_SL_MULT = 2.0`, `MAX_OPEN_POSITIONS = 20`.
- `KLINE_LOOKBACK = 1000`: ana çizgi geçmişe bağlı olduğu için en fazla mum çekilir.

## 4) Dosyalar
`config.py`, `indicators.py` (Q-Trend), `sizing.py`, `bybit_client.py`, `state.py`,
`strategy.py`, `telegram_notifier.py`, `telegram_bot.py`, `main.py`.

## 5) Canlıya geçmeden önce
- Ana çizgi grafikteki Q-Trend ile birkaç coinde karşılaştırılmalı (TradingView'ın
  geçmişi daha uzun olduğu için küçük farklar çıkabilir).
- Düşük varlıkta BTC/ETH gibi büyük lotlu coinler minimum lot yüzünden atlanabilir
  ("MİNİMUM LOT ÇOK BÜYÜK" bildirimi).
- Bot kapalıyken sadece borsadaki Stop Loss emri korur; Kâr Alma, Hareketli Zarar
  ve Lose Exit botun kendisi tarafından yapılır. Botu kesintisiz bir sunucuda çalıştır.
