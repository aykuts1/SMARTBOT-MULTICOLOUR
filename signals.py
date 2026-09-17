"""
signals.py
----------
Giris ve cikis kurallarinin degerlendirilmesi. Tum fonksiyonlar saf (pure) --
disaridan veri alir, karar dondurur, yan etkisi yoktur. Bu sayede gercek
borsa baglantisi olmadan test edilebilirler.

MUM KAPANISINDA degerlendirilenler: giris sinyali, trend-flip cikisi,
T3 renk-flip kar kontrolu, mum kapanis bazli zarar kontrolu.
SUREKLI (3 saniyede bir) degerlendirilenler: TP bandi ve Loss Exit --
bunlar main.py / risk.py tarafinda anlik fiyatla cagrilir.
"""


def check_entry_signal(row) -> str | None:
    """
    row: indicators.compute_all() ciktisinin bir satiri (Series) -- en azindan
    't3_color', 'trend', 'slope' alanlarini icermeli.
    Donus: 'short', 'long' veya None (sinyal yok).
    """
    if row["t3_color"] == "red" and row["trend"] == "short" and row["slope"] == "short":
        return "short"
    if row["t3_color"] == "green" and row["trend"] == "long" and row["slope"] == "long":
        return "long"
    return None


def check_trend_flip_exit(position_side: str, current_trend: str) -> bool:
    """Sadece mum kapanisinda cagrilir. Pozisyonun tersi yone trend donduyse True."""
    if position_side == "short":
        return current_trend == "long"
    if position_side == "long":
        return current_trend == "short"
    return False


def check_color_flip_exit(position_side: str, t3_color: str,
                           entry_price: float, current_price: float,
                           threshold_pct: float) -> bool:
    """
    Sadece mum kapanisinda cagrilir. t3_color = o mumun kapanisindaki Tilson T3
    rengi ('green' / 'red' / 'neutral').
    SHORT pozisyon: T3 KIRMIZI kaldigi surece bu kural hic degerlendirilmez
      (fonksiyon False doner, "devam et" anlaminda). T3 YESILE donduğu anda
      kar >= threshold_pct ise True (kapat), degilse False (acik kalsin).
    LONG pozisyon: ayna mantik, tetikleyici renk KIRMIZI.
    Kar yuzdesi KALDIRACSIZ fiyat hareketi uzerinden hesaplanir.
    """
    if position_side == "short":
        if t3_color != "green":
            return False
        profit_pct = (entry_price - current_price) / entry_price * 100.0
        return profit_pct >= threshold_pct

    if position_side == "long":
        if t3_color != "red":
            return False
        profit_pct = (current_price - entry_price) / entry_price * 100.0
        return profit_pct >= threshold_pct

    return False


def check_candle_close_loss_exit(position_side: str, entry_price: float,
                                  candle_close_price: float, loss_pct: float) -> bool:
    """
    Sadece mum kapanisinda cagrilir. Sürekli (3 sn) calisan check_loss_exit'ten
    FARKLI bir kural: mumun icinde (fitilde) olusan gecici zararlara degil,
    SADECE o mumun KAPANIS fiyatina bakar. O kapanis fiyatina gore pozisyon
    loss_pct (%4) kadar veya daha fazla zarardaysa True doner (kapat).
    """
    if position_side == "short":
        loss_pct_actual = (candle_close_price - entry_price) / entry_price * 100.0
    elif position_side == "long":
        loss_pct_actual = (entry_price - candle_close_price) / entry_price * 100.0
    else:
        return False
    return loss_pct_actual >= loss_pct


def check_loss_exit(position_side: str, entry_price: float,
                     current_price: float, loss_pct: float) -> bool:
    """
    Surekli (3 sn) kontrol edilir. Girisden itibaren ters yonde loss_pct
    (%5.75) kadar fiyat hareketi olduysa True.
    """
    if position_side == "short":
        adverse_pct = (current_price - entry_price) / entry_price * 100.0
    elif position_side == "long":
        adverse_pct = (entry_price - current_price) / entry_price * 100.0
    else:
        return False
    return adverse_pct >= loss_pct


def check_tp_exit(position_side: str, current_price: float, band_price: float,
                   entry_price: float, min_profit_pct: float) -> bool:
    """
    Surekli (3 sn) kontrol edilir. band_price o anki (guncel mum kapanisindan
    hesaplanmis) ALMA bandi seviyesidir -- HAREKETLI hedef, her yeni mum
    kapanisinda caller tarafindan guncellenir.

    ONEMLI: Banda carpilmis olmasi TEK BASINA yetmez -- bandin KENDI SEVIYESI
    entry_price'a gore en az min_profit_pct (%0.10) kar temsil etmiyorsa
    (bant entry'ye fazla yaklasmis ya da entry'nin gerisine gecmisse) bu kural
    devreye girmez, islem acik kalir. O an sadece Loss Exit / trend-flip /
    renk-flip / mum-kapanis-zarar kurallari gecerlidir.
    """
    if position_side == "short":
        band_touched = current_price <= band_price
        band_profit_pct = (entry_price - band_price) / entry_price * 100.0
    elif position_side == "long":
        band_touched = current_price >= band_price
        band_profit_pct = (band_price - entry_price) / entry_price * 100.0
    else:
        return False

    return band_touched and band_profit_pct >= min_profit_pct


def evaluate_close_position_exits(position: dict, row, current_price: float,
                                   loss_pct: float, profit_threshold_pct: float,
                                   candle_close_loss_pct: float) -> str | None:
    """
    Acik bir pozisyon icin cikis kurallarinin tumunu sirayla kontrol eder.
    row: en son kapanan mumun indikator satiri (trend/slope/t3_color + guncel band seviyeleri icerir)
    Donus: cikis nedeni string'i veya None.

    Oncelik sirasi: once en kritik (stop-loss), sonra TP bandi, sonra trend-flip,
    sonra mum-kapanis-zarar, en son T3 renk-flip-kar.
    """
    side = position["side"]
    entry_price = position["entry_price"]

    if check_loss_exit(side, entry_price, current_price, loss_pct):
        return "loss_exit"

    if check_tp_exit(side, current_price, position["tp_band_price"], entry_price, profit_threshold_pct):
        return "take_profit"

    if check_trend_flip_exit(side, row["trend"]):
        return "trend_flip"

    if check_candle_close_loss_exit(side, entry_price, row["close"], candle_close_loss_pct):
        return "candle_close_loss"

    if check_color_flip_exit(side, row["t3_color"], entry_price, current_price, profit_threshold_pct):
        return "color_flip_profit"

    return None
