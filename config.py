"""
config.py
---------
config.json'daki strateji parametrelerini okur. API anahtarlari / Telegram
bilgileri burada DEGIL -- onlar exchange.py ve telegram_notify.py icinde
dogrudan ortam degiskenlerinden (Railway env vars) okunur.
"""

import json
import os

_DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config(path: str = _DEFAULT_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    required = ["symbols", "ema_fast_length", "ema_slow_length", "atr_length",
                "alma_length", "alma_offset", "alma_sigma", "band_multipliers",
                "position_size_pct", "leverage", "loss_exit_pct",
                "profit_threshold_pct", "max_positions", "price_poll_seconds",
                "kline_history_limit"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"config.json icinde eksik alanlar: {missing}")

    return cfg
