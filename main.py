"""
Main bot loop.

Schedules:
  - Entry scan: every 5-min candle close (a few seconds after to ensure fresh data)
  - Exit scan: every 60 seconds (manages CE, stage transitions, external SL detection)
  - Daily summary: at UTC midnight
"""
import time
import traceback
from datetime import datetime, timezone
from typing import List

import config
import strategy
import telegram_bot as tg
from bybit_client import BybitClient
from position_manager import PositionManager, Position


# ============================================================
# GLOBALS
# ============================================================
STAKE_USDT = 0.0
DAILY_STATS = {"date": None, "pnl": 0.0, "trades": 0, "wins": 0}


# ============================================================
# HELPERS
# ============================================================
def now_ts() -> float:
    return time.time()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_sl_price(side: str, entry_price: float, sl_pct: float) -> float:
    """Compute SL price given entry side and percentage."""
    if side == "Buy":
        return entry_price * (1 - sl_pct)
    else:
        return entry_price * (1 + sl_pct)


def compute_stage2_sl(side: str, entry_price: float, profit_pct: float) -> float:
    """SL moves to +profit_pct on entry price."""
    if side == "Buy":
        return entry_price * (1 + profit_pct)
    else:
        return entry_price * (1 - profit_pct)


def get_closed_pnl(client: BybitClient, symbol: str) -> tuple:
    """
    Fetch most recent closed PnL for a symbol.
    Returns (exit_price, pnl_usdt) or (None, 0).
    """
    try:
        resp = client.session.get_closed_pnl(
            category=config.CATEGORY,
            symbol=symbol,
            limit=1,
        )
        if resp.get("retCode") == 0:
            items = resp["result"]["list"]
            if items:
                last = items[0]
                exit_price = float(last.get("avgExitPrice", 0) or 0)
                pnl = float(last.get("closedPnl", 0) or 0)
                return exit_price, pnl
    except Exception as e:
        print(f"[WARN] get_closed_pnl {symbol}: {e}")
    return None, 0.0


def record_trade(pnl: float) -> None:
    """Update daily stats."""
    today = utc_now().date()
    if DAILY_STATS["date"] != today:
        DAILY_STATS["date"] = today
        DAILY_STATS["pnl"] = 0.0
        DAILY_STATS["trades"] = 0
        DAILY_STATS["wins"] = 0
    DAILY_STATS["pnl"] += pnl
    DAILY_STATS["trades"] += 1
    if pnl > 0:
        DAILY_STATS["wins"] += 1


# ============================================================
# POSITION OPENING
# ============================================================
def open_position(client: BybitClient, pm: PositionManager, signal: strategy.Signal) -> None:
    """Place market order with attached %1 SL and record the position."""
    symbol = signal.symbol
    side = signal.side
    entry_ref = signal.entry_price

    try:
        # Ensure isolated + leverage set
        client.set_isolated_margin(symbol, config.LEVERAGE)
        client.set_leverage(symbol, config.LEVERAGE)

        info = client.get_instrument_info(symbol)

        # Notional value = stake * leverage; qty = notional / price
        notional = STAKE_USDT * config.LEVERAGE
        raw_qty = notional / entry_ref
        qty = client.round_step(raw_qty, info["qty_step"])
        if qty < info["min_qty"]:
            print(f"[SKIP] {symbol} qty {qty} below min {info['min_qty']}")
            return

        sl_price = compute_sl_price(side, entry_ref, config.INITIAL_SL_PERCENT)

        # Place market order with attached SL
        client.place_market_order(
            symbol=symbol,
            side=side,
            qty=qty,
            stop_loss_price=sl_price,
        )

        # Brief pause to let order fill, then read actual position
        time.sleep(1.5)
        pos = client.get_position(symbol)
        if pos is None:
            tg.send_error("İşlem açıldı ama pozisyon bulunamadı", f"{symbol} {side}")
            return

        actual_entry = float(pos.get("avgPrice", entry_ref) or entry_ref)
        actual_qty = float(pos.get("size", qty) or qty)

        # Recompute SL based on actual entry and update on exchange
        actual_sl = compute_sl_price(side, actual_entry, config.INITIAL_SL_PERCENT)
        try:
            client.update_stop_loss(symbol, actual_sl)
        except Exception:
            # If recomputed SL fails to update, the initial one (from order) is already there
            pass

        position = Position(
            symbol=symbol,
            side=side,
            entry_price=actual_entry,
            qty=actual_qty,
            stake_usdt=STAKE_USDT,
            leverage=config.LEVERAGE,
            atr_at_entry=signal.atr,
            open_time=now_ts(),
            stage=0,
            ce_level=None,
            current_sl=actual_sl,
            extreme_price=actual_entry,
        )
        pm.open(position)

        tg.send_entry(
            symbol=symbol,
            side=side,
            price=actual_entry,
            qty=actual_qty,
            stake=STAKE_USDT,
            leverage=config.LEVERAGE,
            sl_price=actual_sl,
            atr_value=signal.atr,
        )
        print(f"[OPEN] {symbol} {side} @ {actual_entry} qty={actual_qty} sl={actual_sl}")

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERR] open_position {symbol}: {e}\n{tb}")
        tg.send_error(f"İşlem açılamadı: {symbol} {side}", str(e))


# ============================================================
# POSITION CLOSING
# ============================================================
def close_position(client: BybitClient, pm: PositionManager, symbol: str, reason: str) -> None:
    """Close a tracked position with market reduceOnly order."""
    pos = pm.get(symbol)
    if pos is None:
        return

    try:
        # Verify position still open on exchange
        ex_pos = client.get_position(symbol)
        if ex_pos is None:
            # Already closed externally - just record
            exit_price, pnl = get_closed_pnl(client, symbol)
            if exit_price is None:
                exit_price = pos.entry_price
            pnl_pct = (pnl / pos.stake_usdt * 100) if pos.stake_usdt else 0
            tg.send_exit(
                symbol=symbol,
                side=pos.side,
                entry_price=pos.entry_price,
                exit_price=exit_price,
                pnl_usdt=pnl,
                pnl_pct=pnl_pct,
                reason=reason,
            )
            record_trade(pnl)
            pm.close(symbol)
            return

        # Send opposite market order
        actual_qty = float(ex_pos.get("size", pos.qty))
        client.close_position(symbol, pos.side, actual_qty)
        time.sleep(1.2)

        # Fetch closed pnl
        exit_price, pnl = get_closed_pnl(client, symbol)
        if exit_price is None:
            exit_price = client.get_last_price(symbol)
        pnl_pct = (pnl / pos.stake_usdt * 100) if pos.stake_usdt else 0

        tg.send_exit(
            symbol=symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            pnl_usdt=pnl,
            pnl_pct=pnl_pct,
            reason=reason,
        )
        record_trade(pnl)
        pm.close(symbol)
        print(f"[CLOSE] {symbol} reason={reason} pnl={pnl:.2f}")

    except Exception as e:
        tb = traceback.format_exc()
        print(f"[ERR] close_position {symbol}: {e}\n{tb}")
        tg.send_error(f"İşlem kapatılamadı: {symbol}", str(e))


# ============================================================
# ENTRY SCAN (every 5min candle close)
# ============================================================
def entry_scan(client: BybitClient, pm: PositionManager) -> None:
    print(f"[SCAN] entry scan @ {utc_now().isoformat()}")
    signals_found: List[str] = []
    scanned = 0

    for symbol in config.SYMBOLS:
        try:
            klines = client.get_klines(symbol, config.TIMEFRAME, config.KLINE_LIMIT)
            scanned += 1
            if len(klines) < config.EMA_HIGH_PERIOD + config.CHANNEL_AVG_PERIOD:
                continue

            # First: if we have an open position on this symbol, check reverse signal
            if pm.has(symbol):
                pos = pm.get(symbol)
                last_candle_start = klines[-1]["start"]
                # Only check once per candle
                if pos.last_reverse_check_candle != last_candle_start:
                    pos.last_reverse_check_candle = last_candle_start
                    if strategy.check_reverse_signal(pos.side, klines):
                        close_position(client, pm, symbol, "Ters Sinyal (EMA7 kanalı ters yönde kesti)")
                        # After close, fall through to check if a new entry signal exists
                        # (in the opposite direction)

            # Don't open new position if symbol already has one
            if pm.has(symbol):
                continue

            # Don't open new position if max slots full
            if pm.count() >= config.MAX_POSITIONS:
                continue

            signal = strategy.evaluate_entry(symbol, klines)
            if signal is not None:
                signals_found.append(f"{symbol}({'L' if signal.side == 'Buy' else 'S'})")
                open_position(client, pm, signal)
                # Small delay between order placements
                time.sleep(0.3)

        except Exception as e:
            print(f"[ERR] entry_scan {symbol}: {e}")
            # Don't spam telegram - log only
            continue

    tg.send_scan_summary(scanned, signals_found, pm.count(), config.MAX_POSITIONS)


# ============================================================
# EXIT SCAN (every 60s)
# ============================================================
def exit_scan(client: BybitClient, pm: PositionManager) -> None:
    if pm.count() == 0:
        return

    for symbol, pos in list(pm.all().items()):
        try:
            # Verify position still open on exchange
            ex_pos = client.get_position(symbol)
            if ex_pos is None:
                # External close (SL hit on exchange)
                exit_price, pnl = get_closed_pnl(client, symbol)
                if exit_price is None:
                    exit_price = pos.current_sl
                pnl_pct = (pnl / pos.stake_usdt * 100) if pos.stake_usdt else 0
                reason = "Stop Loss (Borsa)"
                tg.send_exit(
                    symbol=symbol,
                    side=pos.side,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    pnl_usdt=pnl,
                    pnl_pct=pnl_pct,
                    reason=reason,
                )
                record_trade(pnl)
                pm.close(symbol)
                print(f"[EXIT-SL] {symbol} pnl={pnl:.2f}")
                continue

            # Get current price
            price = client.get_last_price(symbol)
            pos.update_extreme(price)

            # Stage 0 → 1: at +1 ATR profit
            if pos.stage == 0:
                if pos.profit_in_atr(price) >= config.STAGE1_TRIGGER_ATR:
                    pos.stage = 1
                    pos.ce_level = pos.compute_ce(config.STAGE1_CE_TRAIL_ATR)
                    tg.send_stage1(
                        symbol=symbol,
                        side=pos.side,
                        price=price,
                        ce_level=pos.ce_level,
                        atr_value=pos.atr_at_entry,
                    )
                    print(f"[STAGE1] {symbol} ce={pos.ce_level}")

            # Stage 1 → 2: at +1.2% profit
            if pos.stage == 1:
                if pos.profit_pct(price) >= config.STAGE2_TRIGGER_PCT:
                    pos.stage = 2
                    new_sl = compute_stage2_sl(pos.side, pos.entry_price, config.STAGE2_SL_PCT)
                    try:
                        client.update_stop_loss(symbol, new_sl)
                        pos.current_sl = new_sl
                        tg.send_stage2(
                            symbol=symbol,
                            side=pos.side,
                            price=price,
                            new_sl=new_sl,
                            profit_pct=pos.profit_pct(price),
                        )
                        print(f"[STAGE2] {symbol} sl={new_sl}")
                    except Exception as e:
                        print(f"[ERR] update SL {symbol}: {e}")
                        tg.send_error(f"SL güncellenemedi: {symbol}", str(e))

            # CE recompute (Stage 1 or 2): trail 1 ATR behind extreme
            if pos.stage >= 1:
                pos.ce_level = pos.compute_ce(config.STAGE1_CE_TRAIL_ATR)
                if pos.ce_hit(price):
                    close_position(client, pm, symbol, "Chandelier Exit (CE)")

        except Exception as e:
            print(f"[ERR] exit_scan {symbol}: {e}")
            continue


# ============================================================
# DAILY SUMMARY
# ============================================================
def maybe_send_daily_summary(last_sent_date) -> object:
    today = utc_now().date()
    if last_sent_date == today:
        return last_sent_date
    # Send summary for previous day at first UTC tick of new day
    if DAILY_STATS["date"] is not None and DAILY_STATS["date"] != today and DAILY_STATS["trades"] > 0:
        tg.send_daily_summary(
            total_pnl=DAILY_STATS["pnl"],
            trade_count=DAILY_STATS["trades"],
            win_count=DAILY_STATS["wins"],
        )
        # Reset
        DAILY_STATS["date"] = today
        DAILY_STATS["pnl"] = 0.0
        DAILY_STATS["trades"] = 0
        DAILY_STATS["wins"] = 0
    return today


# ============================================================
# STARTUP
# ============================================================
def startup(client: BybitClient) -> None:
    """Validate config, fetch balance, compute stake, send start tg."""
    global STAKE_USDT
    config.validate_config()
    balance = client.get_total_balance_usdt()
    if balance <= 0:
        raise RuntimeError(f"Total balance is zero or negative: {balance}")
    STAKE_USDT = balance * config.STAKE_PERCENT
    tg.send_bot_start(
        balance=balance,
        stake=STAKE_USDT,
        leverage=config.LEVERAGE,
        symbols=config.SYMBOLS,
    )
    print(f"[START] balance={balance:.2f} stake={STAKE_USDT:.2f}")


# ============================================================
# MAIN LOOP
# ============================================================
def main():
    client = BybitClient()
    pm = PositionManager()

    try:
        startup(client)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"[FATAL] startup: {e}\n{tb}")
        try:
            tg.send_error("Bot başlatılamadı", str(e))
        except Exception:
            pass
        return

    last_entry_scan_slot = -1
    last_exit_scan = 0.0
    last_daily_summary_date = utc_now().date()

    # Initialize daily stats for today
    DAILY_STATS["date"] = utc_now().date()

    print("[LOOP] entering main loop")

    while True:
        try:
            now = now_ts()

            # ----- Entry scan: once per 5min candle, ~5s after close -----
            slot = int(now // 300)
            seconds_into_slot = now - (slot * 300)
            if slot > last_entry_scan_slot and seconds_into_slot >= 5:
                entry_scan(client, pm)
                last_entry_scan_slot = slot

            # ----- Exit scan: every 60s -----
            if now - last_exit_scan >= config.EXIT_SCAN_INTERVAL:
                exit_scan(client, pm)
                last_exit_scan = now

            # ----- Daily summary at UTC midnight -----
            last_daily_summary_date = maybe_send_daily_summary(last_daily_summary_date)

            time.sleep(2)

        except KeyboardInterrupt:
            print("[STOP] keyboard interrupt")
            break
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[ERR] main loop: {e}\n{tb}")
            try:
                tg.send_error("Ana döngü hatası", str(e))
            except Exception:
                pass
            time.sleep(10)


if __name__ == "__main__":
    main()
