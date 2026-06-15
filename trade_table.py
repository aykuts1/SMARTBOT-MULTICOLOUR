from dataclasses import dataclass


@dataclass
class RedTable:
    """
    Kırmızı/Yeşil işlem açıldığı anda sabitlenir.
    Tüm çizgi değerleri işlem anındaki bantlardan alınır, güncellenmez.
    """
    symbol: str
    direction: str          # "short" | "long"
    entry_price: float      # Giriş fiyatı (Alt2 veya Üst2 değeri)
    lose_exit: float        # İşlem anındaki EMA48 (sabit)

    # Bant seviyeleri (işlem anında sabitlenir)
    lose_1: float           # Alt1 (short) / Üst1 (long)
    level_1: float          # Alt3 / Üst3
    level_2: float          # Alt4 / Üst4
    level_3: float          # Alt5 / Üst5
    level_4: float          # Alt6 / Üst6
    winrate: float          # Alt7 / Üst7

    # Zone sınırları
    zone1_low: float        # entry_price
    zone1_high: float       # level_1
    zone2_low: float        # level_1
    zone2_high: float       # level_2
    zone3_low: float        # level_2
    zone3_high: float       # level_3
    zone4_low: float        # level_3
    zone4_high: float       # level_4
    zone5_low: float        # level_4
    zone5_high: float       # winrate

    qty: float = 0.0        # İşlem miktarı
    order_id: str = ""      # Bybit order ID

    # CE takip değeri (her 5 saniyede güncellenir)
    ce_value: float = 0.0

    @classmethod
    def from_bands(cls, symbol: str, direction: str, bands: dict, qty: float, order_id: str = "") -> "RedTable":
        u = bands["upper"]
        l = bands["lower"]
        ema = bands["ema"]

        if direction == "short":
            return cls(
                symbol=symbol,
                direction=direction,
                entry_price=l[1],   # Alt2
                lose_exit=ema,
                lose_1=l[0],        # Alt1
                level_1=l[2],       # Alt3
                level_2=l[3],       # Alt4
                level_3=l[4],       # Alt5
                level_4=l[5],       # Alt6
                winrate=l[6],       # Alt7
                zone1_low=l[1],     zone1_high=l[2],
                zone2_low=l[2],     zone2_high=l[3],
                zone3_low=l[3],     zone3_high=l[4],
                zone4_low=l[4],     zone4_high=l[5],
                zone5_low=l[5],     zone5_high=l[6],
                qty=qty,
                order_id=order_id,
            )
        else:  # long
            return cls(
                symbol=symbol,
                direction=direction,
                entry_price=u[1],   # Üst2
                lose_exit=ema,
                lose_1=u[0],        # Üst1
                level_1=u[2],       # Üst3
                level_2=u[3],       # Üst4
                level_3=u[4],       # Üst5
                level_4=u[5],       # Üst6
                winrate=u[6],       # Üst7
                zone1_low=u[1],     zone1_high=u[2],
                zone2_low=u[2],     zone2_high=u[3],
                zone3_low=u[3],     zone3_high=u[4],
                zone4_low=u[4],     zone4_high=u[5],
                zone5_low=u[5],     zone5_high=u[6],
                qty=qty,
                order_id=order_id,
            )


@dataclass
class BlueTable:
    """
    Mavi hedge tablosu. Kırmızı işlem açılınca oluşur.
    Giriş ↔ Lose Exit arasını 4 eşit zone'a böler.
    """
    symbol: str
    direction: str          # "long" (kırmızı long için) | "short" (kırmızı short için)
    parent_direction: str   # bağlı olduğu ana işlemin yönü

    zone1_low: float
    zone1_high: float
    zone2_low: float
    zone2_high: float
    zone3_low: float
    zone3_high: float
    zone4_low: float
    zone4_high: float       # Lose Exit'e yakın

    qty: float = 0.0
    order_id: str = ""
    flag: bool = False      # Zone1'e girildi mi
    is_open: bool = False

    @classmethod
    def from_red_table(cls, red: "RedTable") -> "BlueTable":
        entry = red.entry_price
        lose = red.lose_exit
        step = abs(lose - entry) / 4

        if red.direction == "short":
            # Fiyat yukarı çıkar (short zarar), zone1 = entry'ye yakın
            z1_l = entry
            z1_h = entry + step
            z2_l = z1_h
            z2_h = z1_h + step
            z3_l = z2_h
            z3_h = z2_h + step
            z4_l = z3_h
            z4_h = lose
            hedge_dir = "long"
        else:
            # Fiyat aşağı düşer (long zarar), zone1 = entry'ye yakın
            z1_h = entry
            z1_l = entry - step
            z2_h = z1_l
            z2_l = z1_l - step
            z3_h = z2_l
            z3_l = z2_l - step
            z4_h = z3_l
            z4_l = lose
            hedge_dir = "short"

        return cls(
            symbol=red.symbol,
            direction=hedge_dir,
            parent_direction=red.direction,
            zone1_low=z1_l,   zone1_high=z1_h,
            zone2_low=z2_l,   zone2_high=z2_h,
            zone3_low=z3_l,   zone3_high=z3_h,
            zone4_low=z4_l,   zone4_high=z4_h,
        )


@dataclass
class YellowTable:
    """
    Sarı 1 / Sarı 2 işlem tablosu. RedTable ile aynı yapıda, farklı giriş seviyesi.
    """
    symbol: str
    direction: str
    label: str              # "yellow1" | "yellow2"
    entry_price: float
    lose_exit: float
    lose_1: float
    level_1: float
    level_2: float
    level_3: float
    level_4: float
    winrate: float
    zone1_low: float;  zone1_high: float
    zone2_low: float;  zone2_high: float
    zone3_low: float;  zone3_high: float
    zone4_low: float;  zone4_high: float
    zone5_low: float;  zone5_high: float
    qty: float = 0.0
    order_id: str = ""
    ce_value: float = 0.0

    @classmethod
    def from_bands(cls, symbol: str, direction: str, label: str, bands: dict, entry_band_idx: int, qty: float) -> "YellowTable":
        """
        entry_band_idx: Sarı 1 → Alt4/Üst4 (index 3), Sarı 2 → Alt6/Üst6 (index 5)
        """
        u = bands["upper"]
        l = bands["lower"]
        ema = bands["ema"]

        if direction == "short":
            ep = l[entry_band_idx]
            return cls(
                symbol=symbol, direction=direction, label=label,
                entry_price=ep, lose_exit=ema,
                lose_1=l[0], level_1=l[2], level_2=l[3],
                level_3=l[4], level_4=l[5], winrate=l[6],
                zone1_low=l[1],  zone1_high=l[2],
                zone2_low=l[2],  zone2_high=l[3],
                zone3_low=l[3],  zone3_high=l[4],
                zone4_low=l[4],  zone4_high=l[5],
                zone5_low=l[5],  zone5_high=l[6],
                qty=qty,
            )
        else:
            ep = u[entry_band_idx]
            return cls(
                symbol=symbol, direction=direction, label=label,
                entry_price=ep, lose_exit=ema,
                lose_1=u[0], level_1=u[2], level_2=u[3],
                level_3=u[4], level_4=u[5], winrate=u[6],
                zone1_low=u[1],  zone1_high=u[2],
                zone2_low=u[2],  zone2_high=u[3],
                zone3_low=u[3],  zone3_high=u[4],
                zone4_low=u[4],  zone4_high=u[5],
                zone5_low=u[5],  zone5_high=u[6],
                qty=qty,
            )


@dataclass
class WhiteTable:
    """
    Beyaz işlem tablosu. Giriş fiyatı + ATR48 çarpanlarıyla sabitlenir.
    """
    symbol: str
    direction: str
    entry_price: float
    atr: float

    lose_exit: float
    lose_zone2_low: float;  lose_zone2_high: float
    lose_zone1_low: float;  lose_zone1_high: float
    zone1_low: float;  zone1_high: float
    zone2_low: float;  zone2_high: float
    zone3_low: float;  zone3_high: float
    zone4_low: float;  zone4_high: float
    zone5_low: float;  zone5_high: float
    winrate: float

    qty: float = 0.0
    order_id: str = ""

    @classmethod
    def from_entry(cls, symbol: str, direction: str, entry_price: float, atr: float, qty: float) -> "WhiteTable":
        a = atr
        if direction == "short":
            return cls(
                symbol=symbol, direction=direction, entry_price=entry_price, atr=atr,
                lose_exit=round(entry_price + 1.0 * a, 8),
                lose_zone2_low=round(entry_price + 0.5 * a, 8),
                lose_zone2_high=round(entry_price + 1.0 * a, 8),
                lose_zone1_low=entry_price,
                lose_zone1_high=round(entry_price + 0.5 * a, 8),
                zone1_low=round(entry_price - 0.5 * a, 8),   zone1_high=entry_price,
                zone2_low=round(entry_price - 1.0 * a, 8),   zone2_high=round(entry_price - 0.5 * a, 8),
                zone3_low=round(entry_price - 1.5 * a, 8),   zone3_high=round(entry_price - 1.0 * a, 8),
                zone4_low=round(entry_price - 2.0 * a, 8),   zone4_high=round(entry_price - 1.5 * a, 8),
                zone5_low=round(entry_price - 2.5 * a, 8),   zone5_high=round(entry_price - 2.0 * a, 8),
                winrate=round(entry_price - 2.5 * a, 8),
                qty=qty,
            )
        else:  # long
            return cls(
                symbol=symbol, direction=direction, entry_price=entry_price, atr=atr,
                lose_exit=round(entry_price - 1.0 * a, 8),
                lose_zone2_low=round(entry_price - 1.0 * a, 8),
                lose_zone2_high=round(entry_price - 0.5 * a, 8),
                lose_zone1_low=round(entry_price - 0.5 * a, 8),
                lose_zone1_high=entry_price,
                zone1_low=entry_price,                         zone1_high=round(entry_price + 0.5 * a, 8),
                zone2_low=round(entry_price + 0.5 * a, 8),    zone2_high=round(entry_price + 1.0 * a, 8),
                zone3_low=round(entry_price + 1.0 * a, 8),    zone3_high=round(entry_price + 1.5 * a, 8),
                zone4_low=round(entry_price + 1.5 * a, 8),    zone4_high=round(entry_price + 2.0 * a, 8),
                zone5_low=round(entry_price + 2.0 * a, 8),    zone5_high=round(entry_price + 2.5 * a, 8),
                winrate=round(entry_price + 2.5 * a, 8),
                qty=qty,
            )


@dataclass
class OrangeTable:
    """
    Turuncu işlem tablosu. Her Turuncu thread açıldığında sabitlenir.
    entry_idx: 1=Alt2/Üst2, 2=Alt3/Üst3, 3=Alt4/Üst4, 4=Alt5/Üst5
    """
    symbol: str
    direction: str
    label: str           # "turuncu1" | "turuncu2" | "turuncu3" | "turuncu4"
    entry_price: float   # Giriş seviyesi
    lose_exit: float     # Bir üst bant (SHORT zarar çizgisi)
    winrate: float       # İki alt bant (SHORT kâr çizgisi)
    qty: float = 0.0
    order_id: str = ""

    @classmethod
    def from_bands(cls, symbol: str, direction: str, label: str,
                   bands: dict, entry_idx: int, qty: float) -> "OrangeTable":
        if direction == "short":
            l = bands["lower"]
            return cls(
                symbol=symbol, direction=direction, label=label,
                entry_price=l[entry_idx],
                lose_exit=l[entry_idx - 1],
                winrate=l[entry_idx + 2],
                qty=qty,
            )
        else:
            u = bands["upper"]
            return cls(
                symbol=symbol, direction=direction, label=label,
                entry_price=u[entry_idx],
                lose_exit=u[entry_idx - 1],
                winrate=u[entry_idx + 2],
                qty=qty,
            )


@dataclass
class TealTable:
    """
    Turkuaz hedge tablosu. Her Turuncu açılışında oluşur.
    Turuncu giriş ↔ Lose Exit arasını 4 eşit zone'a böler.
    """
    symbol: str
    direction: str
    parent_direction: str
    entry_price: float   # Turuncu'nun giriş fiyatı (zone alt/üst sınırı)

    zone1_low: float;  zone1_high: float
    zone2_low: float;  zone2_high: float
    zone3_low: float;  zone3_high: float
    zone4_low: float;  zone4_high: float

    qty: float = 0.0
    order_id: str = ""
    is_open: bool = False

    @classmethod
    def from_orange_table(cls, orange: "OrangeTable") -> "TealTable":
        entry = orange.entry_price
        lose  = orange.lose_exit
        step  = abs(lose - entry) / 4

        if orange.direction == "short":
            # Teal LONG, zone'lar yukarı gider (entry → lose_exit)
            z1_l = entry;      z1_h = entry + step
            z2_l = z1_h;       z2_h = z1_h + step
            z3_l = z2_h;       z3_h = z2_h + step
            z4_l = z3_h;       z4_h = lose
            hedge_dir = "long"
        else:
            # Teal SHORT, zone'lar aşağı gider (entry → lose_exit)
            z1_h = entry;      z1_l = entry - step
            z2_h = z1_l;       z2_l = z1_l - step
            z3_h = z2_l;       z3_l = z2_l - step
            z4_h = z3_l;       z4_l = lose
            hedge_dir = "short"

        return cls(
            symbol=orange.symbol,
            direction=hedge_dir,
            parent_direction=orange.direction,
            entry_price=entry,
            zone1_low=z1_l,  zone1_high=z1_h,
            zone2_low=z2_l,  zone2_high=z2_h,
            zone3_low=z3_l,  zone3_high=z3_h,
            zone4_low=z4_l,  zone4_high=z4_h,
        )


@dataclass
class PurpleTable:
    """
    Mor hedge tablosu. Beyaz işlem açılınca oluşur.
    Giriş ↔ Lose Exit arasını 4 eşit zone'a böler.
    """
    symbol: str
    direction: str
    parent_direction: str

    zone1_low: float;  zone1_high: float
    zone2_low: float;  zone2_high: float
    zone3_low: float;  zone3_high: float
    zone4_low: float;  zone4_high: float

    qty: float = 0.0
    order_id: str = ""
    flag: bool = False
    is_open: bool = False

    @classmethod
    def from_white_table(cls, white: "WhiteTable") -> "PurpleTable":
        entry = white.entry_price
        lose  = white.lose_exit
        step  = abs(lose - entry) / 4

        if white.direction == "short":
            z1_l = entry;          z1_h = entry + step
            z2_l = z1_h;           z2_h = z1_h + step
            z3_l = z2_h;           z3_h = z2_h + step
            z4_l = z3_h;           z4_h = lose
            hedge_dir = "long"
        else:
            z1_h = entry;          z1_l = entry - step
            z2_h = z1_l;           z2_l = z1_l - step
            z3_h = z2_l;           z3_l = z2_l - step
            z4_h = z3_l;           z4_l = lose
            hedge_dir = "short"

        return cls(
            symbol=white.symbol,
            direction=hedge_dir,
            parent_direction=white.direction,
            zone1_low=z1_l,  zone1_high=z1_h,
            zone2_low=z2_l,  zone2_high=z2_h,
            zone3_low=z3_l,  zone3_high=z3_h,
            zone4_low=z4_l,  zone4_high=z4_h,
        )
