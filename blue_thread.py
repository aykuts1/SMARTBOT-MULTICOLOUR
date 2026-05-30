"""
🔵 MAVİ THREAD (Yeni Yapı — madde 14-23)

Hedge mantığı:
- Kırmızı Short açıldığında → Mavi Long tablo
- Kırmızı Long açıldığında → Mavi Short tablo

Tablo (madde 14):
- Kırmızı giriş çizgisi ↔ Kırmızı LOSE arası 5 EŞİT parça
- 5 bölge (alttan üste, Short Kırmızı için): FLAG, ST1, ST2, ST3, ST4
- 6 çizgi: Kırmızı giriş → ST1 → ST2 → ST3 → ST4 → Kırmızı LOSE
- Her bölgenin "giriş çizgisi" = bölgenin alt sınırı

Flag açılışı (madde 15):
- Kırmızı giriş çizgisini cross → flag açılır

Flag silme + yeniden açılma (madde 16):
- Ters cross → flag silinir
- Tekrar cross → flag yeniden açılır

İşlem açılışı (madde 17):
- ST1 giriş çizgisi cross → işlem açılır, seviye=ST1

Yeniden giriş (madde 18):
- Kırmızı yaşadığı sürece sınırsız

Seviye ilerlemesi (madde 19):
- ST2/ST3/ST4 cross → seviye yükselir, geri gitmez

Çıkış (madde 20, TRAIL YOK):
- Seviye ST1/ST2 → çıkış çizgisi = Kırmızı giriş çizgisi
- Seviye ST3/ST4 → çıkış çizgisi = ST1 giriş çizgisi

WINRATE çıkışı (madde 21):
- Fiyat Kırmızı LOSE'u cross → Kırmızı kapanır → Mavi otomatik kâr ile kapanır

Mavi'nin sonu (madde 22):
- Kırmızı kapanınca tablo silinir

Tablo kurulurken fiyat zaten yukarıda/aşağıda ise (madde 23):
- FLAG bölgesinde → sadece flag açık
- ST1-ST4 bölgelerinde → flag+işlem doğrudan açılır, seviye = bölge
"""
import threading
import time
import logging

from utils import crossed_up, crossed_down

log = logging.getLogger("BlueThread")


class BlueTable:
    """Bir Kırmızı işleme bağlı Mavi tablo."""
    __slots__ = ("red_trade_id", "red_side", "symbol", "side",
                 "levels", "lose_line", "entry_line",
                 "flag_open", "current_level", "active_trade")

    def __init__(self, red_trade, levels):
        self.red_trade_id = red_trade.id
        self.red_side = red_trade.side
        self.symbol = red_trade.symbol
        # Mavi yön Kırmızı'nın tersi
        self.side = "LONG" if red_trade.side == "SHORT" else "SHORT"
        self.levels = dict(levels)  # ST1..ST4 giriş çizgileri
        self.lose_line = red_trade.lose_line  # Kırmızı LOSE
        self.entry_line = red_trade.level_lines["ENTRY"]  # Kırmızı giriş çizgisi
        self.flag_open = False
        self.current_level = None  # işlem açık değilken None
        self.active_trade = None


class BlueThread(threading.Thread):

    LEVEL_ORDER = ["ST1", "ST2", "ST3", "ST4"]

    def __init__(self, config, data_manager, trade_manager):
        super().__init__(name="BlueThread", daemon=True)
        self.cfg = config
        self.dm = data_manager
        self.tm = trade_manager
        self._stop = threading.Event()
        # red_trade_id -> BlueTable
        self.tables = {}
        self.tables_lock = threading.Lock()

    def stop(self):
        self._stop.set()

    # ------------------------------------------------------------------
    # OKUMA HELPERS (raporlar için)
    # ------------------------------------------------------------------
    def get_open_flags(self):
        result = []
        with self.tables_lock:
            for tbl in self.tables.values():
                if tbl.flag_open and tbl.active_trade is None:
                    result.append({"symbol": tbl.symbol, "thread": "BLUE",
                                   "side": tbl.side})
        return result

    # ------------------------------------------------------------------
    # TABLO OLUŞTURMA
    # ------------------------------------------------------------------
    def create_table_for_red(self, red_trade):
        """
        Kırmızı işlem açıldığında çağrılır.
        Tablo: Kırmızı giriş ↔ Kırmızı LOSE arası 5 eşit parça.
        """
        entry = red_trade.level_lines["ENTRY"]
        lose = red_trade.lose_line
        # 5 eşit parça → step = (lose - entry) / 5
        # ST1..ST4 = entry + (1..4) * step
        step = (lose - entry) / 5.0
        levels = {
            "ST1": entry + step * 1,
            "ST2": entry + step * 2,
            "ST3": entry + step * 3,
            "ST4": entry + step * 4,
        }
        # Sınır çizgileri (raporlama için): entry_line ve lose_line zaten table'da

        table = BlueTable(red_trade, levels)
        with self.tables_lock:
            self.tables[red_trade.id] = table

        # Telegram bildirim
        all_lines = {
            "Kırmızı Giriş": entry,
            **levels,
            "Kırmızı LOSE": lose,
        }
        self.tm.tg.notify_thread_ready(red_trade, "BLUE", table.side, all_lines)

        # Madde 23: Fiyat zaten yukarıda/aşağıda mı kontrolü
        self._check_initial_position(table)

        return table

    def _check_initial_position(self, tbl):
        """Madde 23: tablo kurulurken fiyat hangi bölgede?"""
        curr = self.dm.get_last_price(tbl.symbol)
        if curr is None:
            return

        # Mavi Long (Kırmızı Short) için: tablo entry ↑ lose şeklinde, yukarı uzanır
        # Mavi Short (Kırmızı Long) için: tablo entry ↓ lose şeklinde, aşağı uzanır
        # Bölge tespiti yön bilinçli

        zone = self._find_zone(tbl, curr)
        if zone is None:
            return  # FLAG bölgesinin dışında (Kırmızı kâr yönünde veya LOSE ötesinde)

        if zone == "FLAG":
            tbl.flag_open = True
            self.tm.log_flag_event(tbl.symbol, "BLUE", tbl.side, "OPENED")
        elif zone in ("ST1", "ST2", "ST3", "ST4"):
            # Otomatik açılış
            tbl.flag_open = True
            opened = self._open_blue(tbl, curr, initial_level=zone)
            if opened:
                self.tm.log_flag_event(tbl.symbol, "BLUE", tbl.side, "CONVERTED")

    def _find_zone(self, tbl, price):
        """
        Fiyat hangi bölgede? Mavi tablosuna göre yön bilinçli kontrol.
        Dönüş: "FLAG", "ST1", "ST2", "ST3", "ST4" veya None (tablo dışı).
        """
        entry = tbl.entry_line
        lose = tbl.lose_line
        levels = tbl.levels

        if tbl.side == "LONG":
            # Kırmızı Short, Mavi Long → tablo yukarı uzanır
            # FLAG bölgesi: entry ile ST1 arasında
            # ST1: ST1 ile ST2 arası
            # ...
            # ST4: ST4 ile lose arası
            if price < entry or price > lose:
                return None
            if price < levels["ST1"]:
                return "FLAG"
            if price < levels["ST2"]:
                return "ST1"
            if price < levels["ST3"]:
                return "ST2"
            if price < levels["ST4"]:
                return "ST3"
            return "ST4"
        else:
            # Kırmızı Long, Mavi Short → tablo aşağı uzanır
            if price > entry or price < lose:
                return None
            if price > levels["ST1"]:
                return "FLAG"
            if price > levels["ST2"]:
                return "ST1"
            if price > levels["ST3"]:
                return "ST2"
            if price > levels["ST4"]:
                return "ST3"
            return "ST4"

    def remove_table_for_red(self, red_trade_id):
        """Kırmızı kapanınca çağrılır."""
        with self.tables_lock:
            tbl = self.tables.pop(red_trade_id, None)
        if not tbl:
            return
        if tbl.flag_open and tbl.active_trade is None:
            self.tm.log_flag_event(tbl.symbol, "BLUE", tbl.side, "DELETED")

    # ------------------------------------------------------------------
    # SCAN
    # ------------------------------------------------------------------
    def scan(self):
        # Kırmızı'sı kapanmış tabloları temizle
        with self.tables_lock:
            ids_to_remove = []
            for red_id, tbl in self.tables.items():
                red = self.tm.slots.get_red_for(tbl.symbol, tbl.red_side)
                if red is None or red.id != red_id or red.closed:
                    ids_to_remove.append(red_id)
            for rid in ids_to_remove:
                self.tables.pop(rid, None)

        with self.tables_lock:
            tbls = list(self.tables.values())

        for tbl in tbls:
            if self._stop.is_set():
                return
            self._tick_table(tbl)

    def _tick_table(self, tbl):
        prev, curr = self.dm.get_price_pair(tbl.symbol)
        if prev is None or curr is None:
            return

        side = tbl.side  # Mavi yönü
        entry = tbl.entry_line
        lose = tbl.lose_line
        levels = tbl.levels

        # 0) Kırmızı LOSE cross → işlem varsa Mavi WINRATE çıkışı
        # (Kırmızı thread'i de paralel olarak Kırmızı'yı kapatır, close_red_and_dependents
        #  bizi de kapatır. Burada race var ama close_trade idempotent.)
        # Yine de Mavi'nin kendi tarafından LOSE crossunu izlemesine GEREK YOK —
        # Kırmızı zaten close_red_and_dependents ile Mavi'yi kapatır.
        # Bu yüzden bu kısmı izlemiyoruz, race azaltıyoruz.

        if tbl.active_trade and tbl.active_trade.closed:
            tbl.active_trade = None
            tbl.current_level = None
            tbl.flag_open = False

        # 1) FLAG AÇMA / SİLME (sadece işlem yokken)
        if tbl.active_trade is None:
            if side == "LONG":
                # Yukarı cross → flag açılır
                if not tbl.flag_open:
                    if crossed_up(prev, curr, entry):
                        tbl.flag_open = True
                        self.tm.log_flag_event(tbl.symbol, "BLUE", side, "OPENED")
                else:
                    # Aşağı cross → flag silinir (ters cross)
                    if crossed_down(prev, curr, entry):
                        tbl.flag_open = False
                        self.tm.log_flag_event(tbl.symbol, "BLUE", side, "DELETED")
                        return
            else:  # SHORT
                if not tbl.flag_open:
                    if crossed_down(prev, curr, entry):
                        tbl.flag_open = True
                        self.tm.log_flag_event(tbl.symbol, "BLUE", side, "OPENED")
                else:
                    if crossed_up(prev, curr, entry):
                        tbl.flag_open = False
                        self.tm.log_flag_event(tbl.symbol, "BLUE", side, "DELETED")
                        return

        # 2) İŞLEM AÇMA — flag varken ST1 cross
        if tbl.flag_open and tbl.active_trade is None:
            st1 = levels["ST1"]
            opened = False
            if side == "LONG":
                if crossed_up(prev, curr, st1):
                    opened = self._open_blue(tbl, curr, initial_level="ST1")
            else:
                if crossed_down(prev, curr, st1):
                    opened = self._open_blue(tbl, curr, initial_level="ST1")
            if opened:
                self.tm.log_flag_event(tbl.symbol, "BLUE", side, "CONVERTED")
                return

        # 3) SEVİYE GEÇİŞİ (işlem açıkken)
        if tbl.active_trade and not tbl.active_trade.closed:
            new_lvl = self._maybe_advance(tbl, prev, curr)
            if new_lvl:
                tbl.current_level = new_lvl
                tbl.active_trade.current_level = new_lvl
                tbl.active_trade.highest_level = new_lvl
                self.tm.tg.notify_level_change(tbl.active_trade, new_lvl)

        # 4) ÇIKIŞ — yeni sabit eşik mantığı (madde 20)
        if tbl.active_trade and not tbl.active_trade.closed:
            cur_lvl = tbl.current_level
            # ST1/ST2 → Kırmızı giriş çizgisi
            # ST3/ST4 → ST1 giriş çizgisi
            if cur_lvl in ("ST1", "ST2"):
                exit_line = entry
                exit_line_name = "KIRMIZI_GIRIS"
            elif cur_lvl in ("ST3", "ST4"):
                exit_line = levels["ST1"]
                exit_line_name = "ST1"
            else:
                return

            if side == "LONG":
                # Mavi Long çıkışı: aşağı cross
                if crossed_down(prev, curr, exit_line):
                    self.tm.close_trade(
                        tbl.active_trade,
                        f"MAVİ {cur_lvl} {exit_line_name} EXIT", curr)
                    tbl.active_trade = None
                    tbl.current_level = None
                    tbl.flag_open = False
            else:  # SHORT
                if crossed_up(prev, curr, exit_line):
                    self.tm.close_trade(
                        tbl.active_trade,
                        f"MAVİ {cur_lvl} {exit_line_name} EXIT", curr)
                    tbl.active_trade = None
                    tbl.current_level = None
                    tbl.flag_open = False

    def _maybe_advance(self, tbl, prev, curr):
        cur_lvl = tbl.current_level
        if cur_lvl not in self.LEVEL_ORDER:
            return None
        idx = self.LEVEL_ORDER.index(cur_lvl)
        if idx + 1 >= len(self.LEVEL_ORDER):
            return None
        next_lvl = self.LEVEL_ORDER[idx + 1]
        next_line = tbl.levels.get(next_lvl)
        if next_line is None:
            return None
        if tbl.side == "LONG":
            if crossed_up(prev, curr, next_line):
                return next_lvl
        else:
            if crossed_down(prev, curr, next_line):
                return next_lvl
        return None

    def _open_blue(self, tbl, entry_price, initial_level="ST1"):
        # Parent Kırmızı'yı O(1) bul
        red_trade = self.tm.slots.get_red_for(tbl.symbol, tbl.red_side)
        if not red_trade or red_trade.id != tbl.red_trade_id or red_trade.closed:
            return False

        # Tablodaki tüm seviye çizgilerini level_lines olarak gönder (raporlamada lazım)
        level_lines = {
            "ENTRY": tbl.entry_line,
            **tbl.levels,
            "LOSE": tbl.lose_line,
        }

        trade = self.tm.open_trade(
            symbol=tbl.symbol, side=tbl.side, thread="BLUE",
            entry_price=entry_price,
            lose_line=tbl.lose_line,
            winrate_line=tbl.lose_line,  # Mavi için "WINRATE" Kırmızı LOSE
            level_lines=level_lines,
            current_level=initial_level,
            parent_red_trade=red_trade,
        )
        if trade:
            tbl.active_trade = trade
            tbl.current_level = initial_level
            tbl.flag_open = False
            return True
        return False

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------
    def run(self):
        log.info("Mavi thread başladı.")
        scan_interval = self.cfg.thread_scan_interval_sec
        while not self._stop.is_set():
            try:
                self.scan()
            except Exception as e:
                log.exception(f"BlueThread döngü hatası: {e}")
            self._stop.wait(scan_interval)
        log.info("Mavi thread durdu.")
