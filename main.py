"""
Scalp Bot - Ana Dongu
Bollinger Bands + RSI + ADX stratejisi
"""

import time
import traceback
from datetime import datetime, timezone

from config import (
    SYMBOLS, TIMEFRAME, SCAN_INTERVAL, EXIT_CHECK_INTERVAL,
    BB_PERIOD, BB_STD, RSI_PERIOD, ADX_PERIOD, ATR_PERIOD,
    LEVERAGE, STAKE_PERCENT, MAX_POSITIONS,
    INITIAL_SL_PERCENT
)
from exchange import BybitExchange
from indicators import calculate_all_indicators
from filters import check_all_filters
from position_manager import PositionManager
import telegram_bot as tg


# Global durumlar
exchange = BybitExchange()
position_mgr = PositionManager()
current_stake = 0.0
last_scan_time = 0
last_exit_check_time = 0


# ============ STAKE GUNCELLE ============
def update_stake():
    """Bakiyeyi okur ve stake'i gunceller."""
    global current_stake
    balance = exchange.get_balance()
    if balance > 0:
        current_stake = balance * STAKE_PERCENT
        print(f"[Stake] Bakiye: {balance:.2f} USDT | Stake: {current_stake:.2f} USDT")
        return balance, current_stake
    return 0.0, 0.0


# ============ POZISYON AC ============
def open_position(symbol, signal):
    """
    Pozisyon acar.
    signal: "LONG" veya "SHORT"
    """
    try:
        # Sembol bilgisi
        info = exchange.get_symbol_info(symbol)
        if not info:
            print(f"[{symbol}] Sembol bilgisi alinamadi")
            return False

        # Anlik fiyat
        current_price = exchange.get_current_price(symbol)
        if not current_price:
            print(f"[{symbol}] Anlik fiyat alinamadi")
            return False

        # Kaldiraci ayarla
        exchange.set_leverage(symbol, LEVERAGE)

        # Miktar hesapla (stake * kaldirac / fiyat)
        notional = current_stake * LEVERAGE
        qty = notional / current_price
        qty = exchange.round_qty(qty, info["qty_step"])

        if qty < info["min_qty"]:
            print(f"[{symbol}] Miktar cok kucuk: {qty} < {info['min_qty']}")
            return False

        # SL fiyati hesapla
        if signal == "LONG":
            side = "Buy"
            sl_price = current_price * (1 - INITIAL_SL_PERCENT)
        else:  # SHORT
            side = "Sell"
            sl_price = current_price * (1 + INITIAL_SL_PERCENT)

        sl_price = exchange.round_price(sl_price, info["tick_size"])

        # Pozisyon ac
        result = exchange.open_position(symbol, side, qty, sl_price)
        if not result:
            print(f"[{symbol}] Pozisyon acilamadi")
            return False

        # Ucret/kayma sebebiyle gercek giris fiyati farkli olabilir
        # Borsadan acik pozisyonu cekelim
        time.sleep(2)
        positions = exchange.get_open_positions()
        actual_entry = current_price
        actual_qty = qty
        for p in positions:
            if p["symbol"] == symbol:
                actual_entry = float(p["avgPrice"])
                actual_qty = float(p["size"])
                break

        # Position manager'a ekle
        position_mgr.add_position(symbol, signal, actual_qty, actual_entry, sl_price)

        # Telegram bildir
        tg.notify_position_opened(symbol, signal, actual_entry, sl_price, actual_qty)

        print(f"[{symbol}] ✅ {signal} aciliyor: Giris={actual_entry}, SL={sl_price}, Qty={actual_qty}")
        return True

    except Exception as e:
        print(f"[{symbol}] open_position hata: {e}")
        traceback.print_exc()
        return False


# ============ POZISYON KAPAT ============
def close_position(position, reason="CE"):
    """Pozisyonu kapatir."""
    try:
        symbol = position.symbol

        # Borsadaki SL emrini iptal et (CE ile kapatildiginda gerekli)
        exchange.cancel_stop_loss(symbol)
        time.sleep(0.5)

        # Kapatma yonu (acik pozisyonun TERSI)
        if position.side == "LONG":
            close_side = "Sell"
        else:
            close_side = "Buy"

        # Market emir ile kapat
        result = exchange.close_position(symbol, close_side, position.qty)
        if not result:
            print(f"[{symbol}] Pozisyon kapatilamadi")
            return False

        # Cikis fiyati
        time.sleep(1)
        exit_price = exchange.get_current_price(symbol) or position.entry_price

        # PnL hesapla
        pnl_percent = position.calculate_pnl_percent(exit_price)
        # USDT bazinda PnL: (qty * giris) * (pnl_percent/100) * (1 yonune gore)
        # Daha basit: qty * (exit - entry) (LONG) veya qty * (entry - exit) (SHORT)
        if position.side == "LONG":
            pnl_usdt = position.qty * (exit_price - position.entry_price)
        else:
            pnl_usdt = position.qty * (position.entry_price - exit_price)

        # Telegram bildir
        tg.notify_position_closed(
            symbol, position.side, position.entry_price,
            exit_price, pnl_usdt, pnl_percent, reason
        )

        # Position manager'dan sil
        position_mgr.remove_position(symbol)

        # Stake'i guncelle
        update_stake()

        print(f"[{symbol}] ✅ Kapatildi: {reason} | PnL: {pnl_usdt:+.2f} USDT ({pnl_percent:+.2f}%)")
        return True

    except Exception as e:
        print(f"[{position.symbol}] close_position hata: {e}")
        traceback.print_exc()
        return False


# ============ GIRIS TARAMASI ============
def scan_for_entries():
    """Tum coinleri tarar, sinyal varsa pozisyon acar."""
    print(f"\n{'='*60}")
    print(f"🔍 GIRIS TARAMASI - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    scanned = 0
    signals_found = 0
    errors = 0
    new_positions = 0

    for symbol in SYMBOLS:
        try:
            # Max pozisyon kontrolu
            if position_mgr.count() >= MAX_POSITIONS:
                print(f"[{symbol}] Max pozisyon doldu, atlaniyor")
                break

            # Bu coinde acik pozisyon varsa atla
            if position_mgr.has_position(symbol):
                print(f"[{symbol}] Acik pozisyon var, atlaniyor")
                continue

            # Mum verisi cek
            klines = exchange.get_klines(symbol, TIMEFRAME, limit=100)
            if not klines or len(klines) < 50:
                print(f"[{symbol}] Yetersiz mum verisi")
                errors += 1
                continue

            # Gostergeleri hesapla
            df = calculate_all_indicators(
                klines,
                bb_period=BB_PERIOD, bb_std=BB_STD,
                rsi_period=RSI_PERIOD, adx_period=ADX_PERIOD,
                atr_period=ATR_PERIOD
            )

            # Filtreleri uygula
            signal, details = check_all_filters(df)
            scanned += 1

            # Loglama
            bb_str = details["bb_signal"] or "-"
            rsi_str = f"{details['rsi_value']}" if details["rsi_value"] else "-"
            adx_str = f"{details['adx_value']}" if details["adx_value"] else "-"
            print(f"[{symbol}] BB:{bb_str} | RSI:{rsi_str} | ADX:{adx_str} | Sinyal:{signal or '-'}")

            # Sinyal varsa pozisyon ac
            if signal:
                signals_found += 1
                if open_position(symbol, signal):
                    new_positions += 1

        except Exception as e:
            print(f"[{symbol}] Tarama hatasi: {e}")
            errors += 1

    # Tarama ozeti (yeni pozisyon acilmadiysa)
    if new_positions == 0:
        tg.notify_scan_summary(scanned, signals_found, errors)

    print(f"\n📊 Tarama bitti: {scanned} coin tarandi, {signals_found} sinyal, "
          f"{new_positions} pozisyon acildi, {errors} hata\n")


# ============ CIKIS TARAMASI ============
def check_exits():
    """Acik pozisyonlari kontrol eder, CE ve breakeven uygular."""
    if position_mgr.count() == 0:
        return

    print(f"\n🔄 CIKIS KONTROLU - {datetime.now().strftime('%H:%M:%S')} - "
          f"Acik pozisyon: {position_mgr.count()}")

    for position in position_mgr.get_all_positions()[:]:  # Liste kopyasi (silme icin)
        try:
            symbol = position.symbol

            # Anlik fiyat
            current_price = exchange.get_current_price(symbol)
            if not current_price:
                continue

            # En yuksek/dusuk fiyati guncelle
            position.update_extremes(current_price)

            # PnL hesapla
            pnl_percent = position.calculate_pnl_percent(current_price)

            # ATR icin mum verisi cek (CE hesabi icin)
            klines = exchange.get_klines(symbol, TIMEFRAME, limit=50)
            if not klines:
                continue
            df = calculate_all_indicators(
                klines,
                bb_period=BB_PERIOD, bb_std=BB_STD,
                rsi_period=RSI_PERIOD, adx_period=ADX_PERIOD,
                atr_period=ATR_PERIOD
            )
            atr = df.iloc[-1]["atr"]
            if not atr or atr != atr:  # NaN kontrolu
                continue

            # Breakeven + CE sikilasma kontrolu
            if position.should_breakeven(current_price):
                # Borsa SL'i girise cek
                if exchange.update_stop_loss(symbol, position.entry_price):
                    position.sl_price = position.entry_price
                    position.breakeven_done = True
                    position.ce_tightened = True  # CE de 0.5 ATR'ye sikilasir
                    tg.notify_breakeven_and_ce_tightened(symbol, position.entry_price)
                    print(f"[{symbol}] 🎯 Breakeven + CE sikilasti")

            # CE'yi guncelle
            position.calculate_ce(atr)

            print(f"[{symbol}] {position.side} | Fiyat:{current_price} | "
                  f"PnL:{pnl_percent:+.2f}% | CE:{position.ce_price:.6f}")

            # CE tetiklendi mi?
            if position.is_ce_triggered(current_price):
                print(f"[{symbol}] 🚨 CE tetiklendi!")
                close_position(position, reason="CE")
                continue

            # Borsa SL ile kapanmis mi kontrol et (pozisyon yok artik)
            open_positions = exchange.get_open_positions()
            symbols_open = [p["symbol"] for p in open_positions]
            if symbol not in symbols_open:
                # Borsada pozisyon yok demek ki SL tetiklendi
                print(f"[{symbol}] 🛑 Borsa SL tetiklenmis, position manager'dan siliniyor")
                exit_price = position.sl_price
                if position.side == "LONG":
                    pnl_usdt = position.qty * (exit_price - position.entry_price)
                else:
                    pnl_usdt = position.qty * (position.entry_price - exit_price)
                pnl_pct = position.calculate_pnl_percent(exit_price)
                tg.notify_position_closed(
                    symbol, position.side, position.entry_price,
                    exit_price, pnl_usdt, pnl_pct, "Borsa SL"
                )
                position_mgr.remove_position(symbol)
                update_stake()

        except Exception as e:
            print(f"[{position.symbol}] Cikis kontrolu hatasi: {e}")
            traceback.print_exc()


# ============ 15DK MUM KAPANIS ZAMANI MI ============
def is_candle_close_time():
    """15dk mumun yeni kapandigi an mi kontrol eder."""
    now = datetime.now(timezone.utc)
    minute = now.minute
    second = now.second
    # 0, 15, 30, 45. dakikalarda mum kapanir, 5 sn icinde tarayalim
    return (minute % 15 == 0) and (second < 30)


# ============ ANA DONGU ============
def main():
    """Bot ana dongu."""
    global last_scan_time, last_exit_check_time

    print("=" * 60)
    print("🚀 SCALP BOT BASLATILIYOR")
    print("=" * 60)

    # Baslangic bakiye/stake
    balance, stake = update_stake()
    if balance == 0:
        print("❌ Bakiye okunamadi! Bot durduruluyor.")
        tg.notify_error("Baslangic bakiye okunamadi! Bot durduruldu.")
        return

    # Borsadaki acik pozisyonlari yukle (bot yeniden baslatildiysa)
    try:
        open_positions = exchange.get_open_positions()
        for p in open_positions:
            symbol = p["symbol"]
            if symbol in SYMBOLS:
                side_raw = p["side"]
                side = "LONG" if side_raw == "Buy" else "SHORT"
                qty = float(p["size"])
                entry = float(p["avgPrice"])
                sl = float(p.get("stopLoss", "0")) or entry * (
                    0.99 if side == "LONG" else 1.01
                )
                position_mgr.add_position(symbol, side, qty, entry, sl)
                print(f"[Yukleme] {symbol} {side} pozisyonu yuklendi: Giris={entry}, Qty={qty}")
    except Exception as e:
        print(f"[Yukleme] Hata: {e}")

    # Bot basladi bildirimi
    tg.notify_bot_started(balance, stake)

    # Ilk taramayi hemen yap
    last_scan_time = 0
    last_exit_check_time = time.time()

    print("\n✅ Bot calisiyor, dongu baslatildi...\n")

    # Ana dongu
    while True:
        try:
            now = time.time()

            # Cikis kontrolu (her 60 saniyede)
            if now - last_exit_check_time >= EXIT_CHECK_INTERVAL:
                check_exits()
                last_exit_check_time = now

            # Giris taramasi (15dk mum kapanisinda)
            if is_candle_close_time() and (now - last_scan_time >= SCAN_INTERVAL - 60):
                scan_for_entries()
                last_scan_time = now

            time.sleep(5)

        except KeyboardInterrupt:
            print("\n⛔ Bot manuel durduruldu")
            tg.notify_error("Bot manuel olarak durduruldu (KeyboardInterrupt)")
            break
        except Exception as e:
            print(f"❌ Ana dongu hatasi: {e}")
            traceback.print_exc()
            tg.notify_error(f"Ana dongu hatasi: {str(e)[:200]}")
            time.sleep(30)


if __name__ == "__main__":
    main()
