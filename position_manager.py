"""
position_manager.py
--------------------
- SlotManager: 16 toplam slot / coin basina 1 pozisyon kuralini yonetir (saf mantik, test edilebilir).
- calc_position_size: guncel bakiyenin %5'i uzerinden, borsanin qty_step'ine
  yuvarlanmis pozisyon buyuklugunu hesaplar (saf mantik, test edilebilir).
  Yuvarlama Decimal ile yapilir -- ham float bolme/carpma (ornegin
  178.60000000000002 gibi) borsanin "Qty invalid" ile reddettigi kirli
  ondalik degerler uretebiliyor, Decimal bunu onler.
- open_position / close_position: yukaridaki mantigi gercek borsa (exchange.py)
  ve kalici durum (state.py) ile birlestirir. Bu kisim canli API baglantisi
  gerektirdigi icin sadece gercek ortamda dogrulanabilir.

NOT: Pozisyon acilirken borsaya konan guvenlik stop-loss emri (broker_stop_loss_pct,
varsayilan %6) ile botun kendi surekli (3 sn) kontrol ettigi Loss Exit
(loss_exit_pct, varsayilan %5.75) ARTIK AYRI iki parametre -- ikisi de
config.json'dan okunuyor ama farkli amaclara hizmet ediyor:
  - loss_exit_pct         -> botun kendisi calisirken, market emriyle kapatir
  - broker_stop_loss_pct  -> bot cokerse/offline kalirsa diye borsanin
                              kendi tuttugu guvenlik agi
"""

import time
from decimal import Decimal, ROUND_DOWN

import indicators as ind
import signals as sig


class SlotManager:
    """16 toplam / coin basina 1 pozisyon kurali. Saf bellek ici mantik."""

    def __init__(self, max_total: int = 16):
        self.max_total = max_total
        self.open_symbols = set()

    def can_open(self, symbol: str) -> bool:
        if symbol in self.open_symbols:
            return False
        if len(self.open_symbols) >= self.max_total:
            return False
        return True

    def register_open(self, symbol: str) -> None:
        self.open_symbols.add(symbol)

    def register_close(self, symbol: str) -> None:
        self.open_symbols.discard(symbol)

    def is_full(self) -> bool:
        return len(self.open_symbols) >= self.max_total

    def count(self) -> int:
        return len(self.open_symbols)


def calc_position_size(balance: float, pct: float, price: float,
                        qty_step: float, leverage: int = 20) -> dict:
    """
    balance: GUNCEL toplam hesap bakiyesi (her islemde canli cekilir, sabit degil)
    pct: pozisyon buyuklugu yuzdesi (5.0 -> %5)
    price: giris anindaki piyasa fiyati (qty hesaplamak icin)
    qty_step: borsanin bu sembol icin izin verdigi minimum miktar adimi
    leverage: kaldirac (varsayilan 20x)

    qty, qty_step'in tam kati olacak sekilde ASAGI yuvarlanir. Bu islem
    Decimal ile yapilir -- ham float aritmetigi (raw_qty / qty_step * qty_step)
    bazen 178.6 yerine 178.60000000000002 gibi kirli bir sonuc uretebiliyor,
    bu da borsa tarafinda "Qty invalid" hatasina yol aciyordu.
    """
    margin_usdt = balance * (pct / 100.0)
    notional_usdt = margin_usdt * leverage
    raw_qty = notional_usdt / price

    qty_step_dec = Decimal(str(qty_step))
    raw_qty_dec = Decimal(str(raw_qty))
    steps = (raw_qty_dec / qty_step_dec).to_integral_value(rounding=ROUND_DOWN)
    qty = float(steps * qty_step_dec)

    return {
        "margin_usdt": margin_usdt,
        "notional_usdt": notional_usdt,
        "qty": qty,
    }


# ---------------------------------------------------------------------------
# Canli islem orkestrasyon (exchange + state gerektirir)
# ---------------------------------------------------------------------------
def open_position(exchange, state, cfg, symbol: str, side: str,
                   indicator_row, notify_fn=None) -> dict | None:
    """
    Yeni pozisyon acar: bakiye cek -> boyut hesapla -> market emir gonder ->
    ilk TP bant seviyesini kaydet -> state.json'a yaz -> Telegram bildirimi.
    Basarisiz olursa None doner (ornegin bakiye yetersizse).
    """
    balance = exchange.get_available_balance()

    instr = exchange.get_instrument_info(symbol)
    qty_step = instr["qty_step"]
    min_qty = instr["min_qty"]

    price = exchange.get_last_price(symbol)
    sized = calc_position_size(balance, cfg["position_size_pct"], price, qty_step, cfg["leverage"])

    if sized["qty"] < min_qty:
        if notify_fn:
            notify_fn("insufficient_balance", symbol=symbol, balance=balance, required=sized["margin_usdt"])
        return None

    exchange.ensure_leverage_and_margin_mode(symbol, cfg["leverage"])

    order_side = "Sell" if side == "short" else "Buy"
    order = exchange.place_market_order(
        symbol=symbol, order_side=order_side, qty=sized["qty"],
        # borsaya konan guvenlik agi stop-loss'u -- botun kendi Loss Exit'inden
        # (loss_exit_pct) AYRI bir parametre (broker_stop_loss_pct)
        stop_loss_price=_compute_loss_exit_price(price, side, cfg["broker_stop_loss_pct"]),
    )

    entry_price = order.get("avg_price", price)
    tp_band_price = ind.nearest_band(indicator_row, cfg, side, entry_price)

    position = {
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "qty": sized["qty"],
        "margin_usdt": sized["margin_usdt"],
        "opened_at": time.time(),
        "tp_band_price": tp_band_price,
    }
    state.add_position(position)

    if notify_fn:
        notify_fn("position_opened", notional_usdt=sized["notional_usdt"], **position)

    return position


def close_position(exchange, state, symbol: str, reason: str,
                    exit_price: float, notify_fn=None) -> dict | None:
    position = state.get_position(symbol)
    if position is None:
        return None

    order_side = "Buy" if position["side"] == "short" else "Sell"
    exchange.place_market_order(symbol=symbol, order_side=order_side,
                                 qty=position["qty"], reduce_only=True)

    pnl_pct = _pnl_pct(position["side"], position["entry_price"], exit_price)
    pnl_usdt = (position.get("margin_usdt") or 0.0) * (pnl_pct / 100.0) * _leverage_from_position(position)

    result = {**position, "exit_price": exit_price, "reason": reason,
              "pnl_pct": pnl_pct, "pnl_usdt": pnl_usdt, "closed_at": time.time()}

    state.remove_position(symbol)
    state.log_closed_trade(result)

    if notify_fn:
        notify_fn("position_closed", **result)

    return result


def update_tp_band(state, symbol: str, indicator_row, cfg) -> None:
    """Her yeni mum kapanisinda hareketli TP hedefini gunceller."""
    position = state.get_position(symbol)
    if position is None:
        return
    new_band = ind.nearest_band(indicator_row, cfg, position["side"], position["entry_price"])
    state.update_position_field(symbol, "tp_band_price", new_band)


def _compute_loss_exit_price(entry_price: float, side: str, loss_pct: float) -> float:
    if side == "short":
        return entry_price * (1 + loss_pct / 100.0)
    return entry_price * (1 - loss_pct / 100.0)


def _pnl_pct(side: str, entry_price: float, exit_price: float) -> float:
    if side == "short":
        return (entry_price - exit_price) / entry_price * 100.0
    return (exit_price - entry_price) / entry_price * 100.0


def _leverage_from_position(position: dict) -> float:
    # margin_usdt * leverage = notional -- qty*entry_price = notional oldugundan geri cikarilir
    # margin_usdt bilinmiyorsa (beklenmedik/eski bir kayit) 1.0 kaldirac varsayilir --
    # asil duzeltme main.py -> sync_with_exchange icinde yetim pozisyonlar icin
    # margin_usdt'nin dogru tahmin edilerek kaydedilmesi (bkz. asagida).
    notional = position["qty"] * position["entry_price"]
    margin = position.get("margin_usdt")
    if not margin:
        return 1.0
    return notional / margin
