# Trend + ALMA + Heikin Ashi Bot

Bybit Futures, 1 saatlik zaman dilimi, MAINNET. EMA21/50 trend+egim, ALMA9
tabanli hareketli kar-al bandi, Heikin Ashi renk tetikleyicili giris/cikis.

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

- `/rapor` -> coin bazli toplam kar/zarar dokumu
- `/pozisyonlar` -> su an acik olan pozisyonlar, anlik kar/zararlariyla

Otomatik gelenler: pozisyon acildi/kapandi, slot dolu, bakiye yetersiz,
12 saatlik / 24 saatlik / haftalik ozet.

## Testler

Ag baglantisi gerektirmeyen mantik testleri (indikatorler, sinyaller,
pozisyon boyutlandirma) icin:

```
pip install pytest
pytest test_bot.py -v
```

31 test de gecmeli. Bybit/Telegram baglantisi gerektiren kisimlar (exchange.py,
telegram_notify.py, main.py) bu ortamda ag erisimi olmadigi icin CANLI test
EDILEMEDI -- pybit'in resmi V5 metod/parametre isimleri kullanildi, ama ilk
gercek calistirmada asagidaki noktalara dikkat et.

## Ilk canli calistirmada mutlaka izle

- **Margin/pozisyon modu ayarlari**: `exchange.py` icindeki
  `ensure_leverage_and_margin_mode` fonksiyonu hesabini CROSS margin +
  one-way (hedge olmayan) moda gecirmeyi dener. Hesap turune (Unified/Classic)
  gore bu cagrilarin tam davranisi degisebilir. Hata olursa bot COKMEZ (try/except
  ile sarili, loglanir) ama Railway loglarini ilk saatlerde kontrol et.
- **Guvenlik agi stop-loss**: Pozisyon acilirken borsa tarafinda da Loss Exit
  (%5) seviyesinde GERCEK bir stop-loss emri konuyor -- bunun amaci bot
  cokerse/offline kalirsa pozisyonun tamamen korumasiz kalmamasi. Hareketli
  ALMA TP bandi borsa emriyle konamaz (sabit deger degil), o her zaman bot
  calisirken yonetilir -- yani **bot offline iken TP calismaz, sadece stop-loss
  calisir**. Istemiyorsan haber ver, kaldirabilirim.
- **Bakiye alani**: `get_available_balance` UNIFIED hesap turunu varsayiyor.
  Hesabin farkli bir tipteyse (ornegin Classic) bu kismi birlikte duzeltiriz.
- Yeni deploy sonrasi ilk 1-2 saat pozisyon acilis/kapanislarini Telegram'dan
  yakindan takip etmeni oneririm.
