from logger_setup import get_logger

log = get_logger("trade_table")


def create_white_table(entry_price, atr, config, side="short"):
    le_atr = config.get("lose_exit_atr", 1.0)
    wr_atr = config.get("winrate_atr", 2.5)
    hedge_atr = config.get("mor_hedge_giris_atr", 0.5)

    if side == "short":
        lose_exit = entry_price + le_atr * atr
        winrate = entry_price - wr_atr * atr
        hedge_entry = entry_price + hedge_atr * atr
        zones = {}
        for i in range(1, 5):
            zones[f"zone{i + 1}_entry"] = entry_price - (i * 0.5) * atr
    else:
        lose_exit = entry_price - le_atr * atr
        winrate = entry_price + wr_atr * atr
        hedge_entry = entry_price - hedge_atr * atr
        zones = {}
        for i in range(1, 5):
            zones[f"zone{i + 1}_entry"] = entry_price + (i * 0.5) * atr

    table = {
        "side": side,
        "entry": entry_price,
        "lose_exit": lose_exit,
        "winrate": winrate,
        "hedge_entry": hedge_entry,
        "chandelier_distance": config.get("chandelier_atr_carpani", 1) * atr,
        "atr": atr
    }
    table.update(zones)
    return table


def create_yellow_table(entry_price, bb_middle, config, side="short"):
    if side == "short":
        lose_exit = bb_middle
        distance = lose_exit - entry_price
    else:
        lose_exit = bb_middle
        distance = entry_price - lose_exit

    multiplier = config.get("winrate_mesafe_carpani", 2.5)

    if side == "short":
        winrate = entry_price - (distance * multiplier)
    else:
        winrate = entry_price + (distance * multiplier)

    ls_step = distance / 4.0
    zone_total = abs(entry_price - winrate) if side == "short" else abs(winrate - entry_price)
    zone_step = zone_total / 5.0

    hedge_entry = (entry_price + lose_exit) / 2

    if side == "short":
        ls_zones = {
            "ls_zone4_entry": lose_exit - 1 * ls_step,
            "ls_zone3_entry": lose_exit - 2 * ls_step,
            "ls_zone2_entry": lose_exit - 3 * ls_step,
        }
        alt_zones = {
            "zone2_entry": entry_price - 1 * zone_step,
            "zone3_entry": entry_price - 2 * zone_step,
            "zone4_entry": entry_price - 3 * zone_step,
            "zone5_entry": entry_price - 4 * zone_step,
        }
    else:
        ls_zones = {
            "ls_zone4_entry": lose_exit + 1 * ls_step,
            "ls_zone3_entry": lose_exit + 2 * ls_step,
            "ls_zone2_entry": lose_exit + 3 * ls_step,
        }
        alt_zones = {
            "zone2_entry": entry_price + 1 * zone_step,
            "zone3_entry": entry_price + 2 * zone_step,
            "zone4_entry": entry_price + 3 * zone_step,
            "zone5_entry": entry_price + 4 * zone_step,
        }

    chandelier_dist = distance * config.get("chandelier_mesafe_carpani", 1)

    table = {
        "side": side,
        "entry": entry_price,
        "lose_exit": lose_exit,
        "winrate": winrate,
        "hedge_entry": hedge_entry,
        "distance": distance,
        "chandelier_distance": chandelier_dist,
    }
    table.update(ls_zones)
    table.update(alt_zones)
    return table


def create_red_table(entry_price, lose_exit_price, side, config):
    if side == "short":
        distance = lose_exit_price - entry_price
        winrate = entry_price - distance * config.get("winrate_mesafe_carpani", 2.5)
    else:
        distance = entry_price - lose_exit_price
        winrate = entry_price + distance * config.get("winrate_mesafe_carpani", 2.5)

    return {
        "side": side,
        "entry": entry_price,
        "lose_exit": lose_exit_price,
        "winrate": winrate,
        "distance": distance,
        "chandelier_distance": distance,
    }


def create_gold_table(entry_price, side, config):
    le_pct = config.get("lose_exit_yuzde", 0.02)
    wr_pct = config.get("winrate_yuzde", 0.05)

    if side == "short":
        lose_exit = entry_price * (1 + le_pct)
        winrate = entry_price * (1 - wr_pct)
    else:
        lose_exit = entry_price * (1 - le_pct)
        winrate = entry_price * (1 + wr_pct)

    distance = entry_price * le_pct
    hedge_entry = (entry_price + lose_exit) / 2

    return {
        "side": side,
        "entry": entry_price,
        "lose_exit": lose_exit,
        "winrate": winrate,
        "hedge_entry": hedge_entry,
        "distance": distance,
        "chandelier_distance": distance,
    }


def create_black_table(entry_price, dc_upper, config, side="short"):
    max_le_pct = config.get("max_lose_exit_yuzdesi", 0.02)

    if side == "short":
        natural_le = dc_upper
        max_le = entry_price * (1 + max_le_pct)
        lose_exit = min(natural_le, max_le)
        distance = lose_exit - entry_price
    else:
        natural_le = dc_upper
        max_le = entry_price * (1 - max_le_pct)
        lose_exit = max(natural_le, max_le)
        distance = entry_price - lose_exit

    multiplier = config.get("winrate_mesafe_carpani", 2.5)

    if side == "short":
        winrate = entry_price - (distance * multiplier)
    else:
        winrate = entry_price + (distance * multiplier)

    ls_step = distance / 4.0
    zone_total = abs(entry_price - winrate) if side == "short" else abs(winrate - entry_price)
    zone_step = zone_total / 5.0

    hedge_entry = (entry_price + lose_exit) / 2

    if side == "short":
        ls_zones = {
            "ls_zone4_entry": lose_exit - 1 * ls_step,
            "ls_zone3_entry": lose_exit - 2 * ls_step,
            "ls_zone2_entry": lose_exit - 3 * ls_step,
        }
        alt_zones = {
            "zone2_entry": entry_price - 1 * zone_step,
            "zone3_entry": entry_price - 2 * zone_step,
            "zone4_entry": entry_price - 3 * zone_step,
            "zone5_entry": entry_price - 4 * zone_step,
        }
    else:
        ls_zones = {
            "ls_zone4_entry": lose_exit + 1 * ls_step,
            "ls_zone3_entry": lose_exit + 2 * ls_step,
            "ls_zone2_entry": lose_exit + 3 * ls_step,
        }
        alt_zones = {
            "zone2_entry": entry_price + 1 * zone_step,
            "zone3_entry": entry_price + 2 * zone_step,
            "zone4_entry": entry_price + 3 * zone_step,
            "zone5_entry": entry_price + 4 * zone_step,
        }

    chandelier_dist = distance * config.get("chandelier_mesafe_carpani", 1)

    table = {
        "side": side,
        "entry": entry_price,
        "lose_exit": lose_exit,
        "winrate": winrate,
        "hedge_entry": hedge_entry,
        "distance": distance,
        "chandelier_distance": chandelier_dist,
    }
    table.update(ls_zones)
    table.update(alt_zones)
    return table
