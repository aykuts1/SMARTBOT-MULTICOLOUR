from logger_setup import get_logger

log = get_logger("trade_table")


def create_red_table(entry_price, ema48, atr, side="short"):
    if side == "short":
        lose_exit = ema48
        alt1 = ema48 - 1 * atr
        alt2 = ema48 - 2 * atr
        alt3 = ema48 - 3 * atr
        alt4 = ema48 - 4 * atr
        alt5 = ema48 - 5 * atr
        alt6 = ema48 - 6 * atr
        alt7 = ema48 - 7 * atr
        hedge_entry = entry_price + 0.5 * atr
        winrate = alt7
        return {
            "side": side,
            "entry": entry_price,
            "lose_exit": lose_exit,
            "winrate": winrate,
            "hedge_entry": hedge_entry,
            "ls_zone2_entry": alt1,
            "ls_zone1_entry": entry_price + 0.5 * atr,
            "zone2_entry": alt3,
            "zone3_entry": alt4,
            "zone4_entry": alt5,
            "zone5_entry": alt6,
            "chandelier_distance": 2 * atr,
            "atr": atr
        }
    else:
        lose_exit = ema48
        ust1 = ema48 + 1 * atr
        ust2 = ema48 + 2 * atr
        ust3 = ema48 + 3 * atr
        ust4 = ema48 + 4 * atr
        ust5 = ema48 + 5 * atr
        ust6 = ema48 + 6 * atr
        ust7 = ema48 + 7 * atr
        hedge_entry = entry_price - 0.5 * atr
        winrate = ust7
        return {
            "side": side,
            "entry": entry_price,
            "lose_exit": lose_exit,
            "winrate": winrate,
            "hedge_entry": hedge_entry,
            "ls_zone2_entry": ust1,
            "ls_zone1_entry": entry_price - 0.5 * atr,
            "zone2_entry": ust3,
            "zone3_entry": ust4,
            "zone4_entry": ust5,
            "zone5_entry": ust6,
            "chandelier_distance": 2 * atr,
            "atr": atr
        }


def create_red_sub_table(entry_price, atr, le_atr, wr_atr, side="short"):
    if side == "short":
        return {
            "side": side,
            "entry": entry_price,
            "lose_exit": entry_price + le_atr * atr,
            "winrate": entry_price - wr_atr * atr,
            "hedge_entry": entry_price + 0.5 * atr,
            "chandelier_distance": 2 * atr,
            "atr": atr
        }
    else:
        return {
            "side": side,
            "entry": entry_price,
            "lose_exit": entry_price - le_atr * atr,
            "winrate": entry_price + wr_atr * atr,
            "hedge_entry": entry_price - 0.5 * atr,
            "chandelier_distance": 2 * atr,
            "atr": atr
        }


def create_white_table(entry_price, atr, config, side="short"):
    le_atr = config.get("lose_exit_atr", 1.0)
    wr_atr = config.get("winrate_atr", 2.5)
    hedge_atr = config.get("mor_hedge_giris_atr", 0.25)

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
        hedge_entry = ls_zones["ls_zone2_entry"]
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
        hedge_entry = ls_zones["ls_zone2_entry"]

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
        hedge_entry = ls_zones["ls_zone2_entry"]
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
        hedge_entry = ls_zones["ls_zone2_entry"]

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
