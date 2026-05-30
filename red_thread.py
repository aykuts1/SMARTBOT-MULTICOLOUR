"""
🔴 KIRMIZI THREAD

Yeni Açılış Mantığı (madde 4-5, 38):
- Flag taraması: 15dk mum kapanışında Donchian yön değişimi ile.
- İşlem açılışı 2 aşamalı:
  A) Fiyat Donchian çizgisini cross ederse → giriş çizgisi olarak DONCHIAN ÇİZGİSİNİN
     DEĞERİ kaydedilir (ham fiyat değil — direnç seviyesi mantığı). EMA bakılmaz.
  B) Fiyat kaydedilen giriş çizgisini cross ederse + EMA filtresi tamam → işlem açılır.
- İşlem açıldığında flag VE giriş çizgisi silinir.

Hızlı tarama: 5 sn (madde 1).

Seviye ve çıkışlar: aynen kaldı (trail mantığı korundu).
"""
import threading
import time
import logging

from utils import crossed_up, crossed_down, now_ts

log = logging.getLogger("RedThread")


class RedThread(threading.Thread):

    LEVEL_ORDER = ["ENTRY", "ST1", "ST2", "ST3", "ST4", "ST5"]
    # current_level → çıkış için karşılaştırılacak çizgi adı
    EXIT_LINE_FOR_LEVEL = {
        "ENTRY": "LOSE",
        "ST1": "LOSE",
        "ST2": "ENTRY",
        "ST3": "ST1",
        "ST4": "ST2",
        "ST5": "ST3",
    }

    def __init__(self, config, data_manager, trade_manager,
                 blue_thread_ref=None, yellow_thread_ref=None):
        super().__init__(name="RedThread", daemon=True)
        self.cfg = config
        self.dm = data_manager
        self.tm = trade_manager
        self.blue = blue_thread_ref
        self.yellow = yellow_thread_ref

        self._stop = threading.Event()

        # symbol -> {"long_flag": bool, "short_flag": bool,
        #            "long_entry_line": float|None, "short_entry_line": float|None}
        self.state = {s: {
            "long_flag": False,
            "short_flag": False,
            "long_entry_line": None,
            "short_entry_line": None,
        } for s in config.symbols}

        # En son flag check edilen mum timestamp
        self.last_flag_check_ts = {s: None for s in config.symbols}

    def set_thread_refs(self, blue, yellow):
        self.blue = blue
        self.yellow = yellow

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    # OKUMA HELPERS (raporlar için)
    # ------------------------------------------------------------------
    def get_open_flags(self):
        """Raporlar için açık Kırmızı flag'leri döndür."""
        result = []
        for symbol, st in self.state.items():
            if st["long_flag"]:
                result.append({"symbol": symbol, "thread": "RED", "side": "LONG",
                               "entry_line": st["long_entry_line"]})
            if st["short_flag"]:
                result.append({"symbol": symbol, "thread": "RED", "side": "SHORT",
                               "entry_line": st["short_entry_line"]})
        return result

    # ------------------------------------------------------------------
    # FLAG TARAMA — 15dk mum kapanışında
    # ------------------------------------------------------------------
    def scan_flags(self):
        for symbol in self.cfg.symbols:
            if self.dm.is_paused(symbol):
                continue
            if self._stop.is_set():
                return
            self._scan_flag_one(symbol)

    def _scan_flag_one(self, symbol):
        snap = self.dm.get_snapshot(symbol)
        if not snap:
            return
        upper_hist = snap["donchian_upper_history"]
        lower_hist = snap["donchian_lower_history"]
        if len(upper_hist) < 2 or upper_hist[-1] is None or upper_hist[-2] is None:
            return
        if lower_hist[-1] is None or lower_hist[-2] is None:
            return

        cur_upper = upper_hist[-1]
        prev_upper = upper_hist[-2]
        cur_lower = lower_hist[-1]
        prev_lower = lower_hist[-2]

        last_close_ts = snap["last_candle_close_ts"]
        if self.last_flag_check_ts.get(symbol) == last_close_ts:
            return
        self.last_flag_check_ts[symbol] = last_close_ts

        st = self.state[symbol]

        # Donchian alt çizgi önceki seviyeden yukarı çıktı → Short Flag
        if cur_lower > prev_lower:
            if not st["short_flag"]:
                st["short_flag"] = True
                # Yeni flag → giriş çizgisi sıfırlanır
                st["short_entry_line"] = None
                self.tm.log_flag_event(symbol, "RED", "SHORT", "OPENED")

        # Donchian üst çizgi önceki seviyeden aşağı indi → Long Flag
        if cur_upper < prev_upper:
            if not st["long_flag"]:
                st["long_flag"] = True
                st["long_entry_line"] = None
                self.tm.log_flag_event(symbol, "RED", "LONG", "OPENED")

    # ------------------------------------------------------------------
    # AÇILIŞ — 2 AŞAMALI YENİ MANTIK (madde 4-5)
    # ------------------------------------------------------------------
    def scan_open_signals(self):
        for symbol in self.cfg.symbols:
            if self.dm.is_paused(symbol):
                continue
            if self._stop.is_set():
                return
            self._scan_open_one(symbol)

    def _scan_open_one(self, symbol):
        prev, curr = self.dm.get_price_pair(symbol)
        if prev is None or curr is None:
            return

        d_upper, d_lower = self.dm.get_donchian_current(symbol)
        ema_val = self.dm.get_ema(symbol)
        if d_upper is None or d_lower is None or ema_val is None:
            return

        st = self.state[symbol]

        # ----- SHORT açılış akışı -----
        if st["short_flag"]:
            # Aşama A: giriş çizgisi kaydı
            # Donchian alt çizgisini aşağı cross → bu çizginin değeri giriş çizgisi
            if st["short_entry_line"] is None:
                if crossed_down(prev, curr, d_lower):
                    # Direnç seviyesi mantığı: Donchian'ın O ANDAKI değeri kaydedilir
                    st["short_entry_line"] = d_lower
                    log.info(f"[{symbol}] SHORT giriş çizgisi kaydedildi: {d_lower}")
            else:
                # Aşama B: kaydedilmiş giriş çizgisini aşağı cross + EMA altında
                entry_line = st["short_entry_line"]
                # Daha düşük seviyede yeni bir Donchian değişimi olursa üzerine yazma
                # mantığı yeni flag ile gelir (eskisi temizlenir).
                # Burada üzerine yazma sadece eski çizginin ÜSTÜNDE oluşacak yeni
                # değme ile olur — yani fiyat yukarı dönüp tekrar Donchian alt çizgiyi
                # aşağı cross ederse ve YENİ değer eskisinden farklıysa güncellenir.
                # (Donchian zaten 15dk'da bir değişir, fiyat hareketiyle değişmez.)

                # Cross + EMA kontrolü
                if crossed_down(prev, curr, entry_line):
                    if curr < ema_val:
                        self._open_red(symbol, "SHORT", curr, d_upper, d_lower)
                    # EMA filtresine takıldı → işlem açılmaz, giriş çizgisi kalır

        # ----- LONG açılış akışı (simetrik) -----
        if st["long_flag"]:
            if st["long_entry_line"] is None:
                if crossed_up(prev, curr, d_upper):
                    st["long_entry_line"] = d_upper
                    log.info(f"[{symbol}] LONG giriş çizgisi kaydedildi: {d_upper}")
            else:
                entry_line = st["long_entry_line"]
                if crossed_up(prev, curr, entry_line):
                    if curr > ema_val:
                        self._open_red(symbol, "LONG", curr, d_upper, d_lower)

    def _calc_red_levels(self, side, entry_price, d_upper, d_lower):
        """
        Kırmızı seviyelerini hesapla.
        LOSE = Donchian (max %2 sınırlı), WINRATE = entry'den 3x lose mesafesi.
        ST1..ST5 = entry ile winrate arası 6 eşit parça.
        """
        max_lose_pct = self.cfg.max_lose_pct / 100.0

        if side == "SHORT":
            raw_lose = d_upper
            max_lose = entry_price * (1.0 + max_lose_pct)
            lose = min(raw_lose, max_lose)
            lose_dist = lose - entry_price
            if lose_dist <= 0:
                lose = max_lose
                lose_dist = lose - entry_price
            winrate = entry_price - self.cfg.risk_reward * lose_dist
            step = (entry_price - winrate) / 6.0
            levels = {
                "LOSE": lose,
                "ENTRY": entry_price,
                "ST1": entry_price - step * 1,
                "ST2": entry_price - step * 2,
                "ST3": entry_price - step * 3,
                "ST4": entry_price - step * 4,
                "ST5": entry_price - step * 5,
                "WINRATE": winrate,
            }
        else:  # LONG
            raw_lose = d_lower
            max_lose = entry_price * (1.0 - max_lose_pct)
            lose = max(raw_lose, max_lose)
            lose_dist = entry_price - lose
            if lose_dist <= 0:
                lose = max_lose
                lose_dist = entry_price - lose
            winrate = entry_price + self.cfg.risk_reward * lose_dist
            step = (winrate - entry_price) / 6.0
            levels = {
                "LOSE": lose,
                "ENTRY": entry_price,
                "ST1": entry_price + step * 1,
                "ST2": entry_price + step * 2,
                "ST3": entry_price + step * 3,
                "ST4": entry_price + step * 4,
                "ST5": entry_price + step * 5,
                "WINRATE": winrate,
            }
        return levels

    def _open_red(self, symbol, side, entry_price, d_upper, d_lower):
        levels = self._calc_red_levels(side, entry_price, d_upper, d_lower)

        if side == "SHORT" and levels["LOSE"] <= entry_price:
            return
        if side == "LONG" and levels["LOSE"] >= entry_price:
            return

        trade = self.tm.open_trade(
            symbol=symbol, side=side, thread="RED",
            entry_price=entry_price,
            lose_line=levels["LOSE"],
            winrate_line=levels["WINRATE"],
            level_lines=levels,
            current_level="ENTRY",
        )
        if not trade:
            # İşlem açılamadı (slot dolu / qty yetersiz / order hatası vs)
            # Flag ve giriş çizgisi temizleme YAPMIYORUZ — bir sonraki fırsat
            # için bekleyebilirler. Sadece slot dolu durumunda log kaldı.
            return

        # İşlem açıldı: flag + giriş çizgisi silinir
        st = self.state[symbol]
        if side == "SHORT":
            if st["short_flag"]:
                st["short_flag"] = False
                self.tm.log_flag_event(symbol, "RED", "SHORT", "CONVERTED")
            st["short_entry_line"] = None
        else:
            if st["long_flag"]:
                st["long_flag"] = False
                self.tm.log_flag_event(symbol, "RED", "LONG", "CONVERTED")
            st["long_entry_line"] = None

        # Mavi ve Sarı tablolarını kur
        try:
            if self.blue:
                self.blue.create_table_for_red(trade)
        except Exception as e:
            log.error(f"Mavi tablo oluşturma hatası: {e}")
        try:
            if self.yellow:
                self.yellow.create_table_for_red(trade)
        except Exception as e:
            log.error(f"Sarı tablo oluşturma hatası: {e}")

    # ------------------------------------------------------------------
    # SEVİYE GEÇİŞİ + ÇIKIŞ
    # ------------------------------------------------------------------
    def scan_levels_and_exits(self):
        trades = self.tm.slots.get_open_by_thread("RED")
        for t in trades:
            if self._stop.is_set():
                return
            self._tick_red(t)

    def _tick_red(self, trade):
        prev, curr = self.dm.get_price_pair(trade.symbol)
        if prev is None or curr is None:
            return

        levels = trade.level_lines

        # 1) WINRATE çıkışı (her seviyede)
        if trade.side == "SHORT":
            if crossed_down(prev, curr, levels["WINRATE"]):
                self.tm.close_red_and_dependents(
                    trade, f"KIRMIZI {trade.current_level} WINRATE EXIT", curr)
                return
        else:
            if crossed_up(prev, curr, levels["WINRATE"]):
                self.tm.close_red_and_dependents(
                    trade, f"KIRMIZI {trade.current_level} WINRATE EXIT", curr)
                return

        # 2) Seviye geçişi
        new_level = self._maybe_advance_level(trade, prev, curr)
        if new_level:
            trade.current_level = new_level
            trade.highest_level = new_level
            self.tm.tg.notify_level_change(trade, new_level)

        # 3) Mevcut seviyeden çıkış kontrolü
        cur_lvl = trade.current_level
        exit_line_name = self.EXIT_LINE_FOR_LEVEL.get(cur_lvl)
        if exit_line_name is None:
            return
        exit_line = levels.get(exit_line_name)
        if exit_line is None:
            return

        if trade.side == "SHORT":
            if crossed_up(prev, curr, exit_line):
                self.tm.close_red_and_dependents(
                    trade, f"KIRMIZI {cur_lvl} {exit_line_name} EXIT", curr)
        else:
            if crossed_down(prev, curr, exit_line):
                self.tm.close_red_and_dependents(
                    trade, f"KIRMIZI {cur_lvl} {exit_line_name} EXIT", curr)

    def _maybe_advance_level(self, trade, prev, curr):
        cur_lvl = trade.current_level
        try:
            idx = self.LEVEL_ORDER.index(cur_lvl)
        except ValueError:
            return None
        if idx + 1 >= len(self.LEVEL_ORDER):
            return None
        next_lvl = self.LEVEL_ORDER[idx + 1]
        next_line = trade.level_lines.get(next_lvl)
        if next_line is None:
            return None
        if trade.side == "SHORT":
            if crossed_down(prev, curr, next_line):
                return next_lvl
        else:
            if crossed_up(prev, curr, next_line):
                return next_lvl
        return None

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------
    def run(self):
        log.info("Kırmızı thread başladı.")
        scan_interval = self.cfg.thread_scan_interval_sec
        while not self._stop.is_set():
            try:
                self.scan_open_signals()
                self.scan_levels_and_exits()
            except Exception as e:
                log.exception(f"RedThread döngü hatası: {e}")
            # Stop event'ı bekle (interruptible sleep)
            self._stop.wait(scan_interval)
        log.info("Kırmızı thread durdu.")
