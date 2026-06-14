import pandas as pd
import pandas_ta as ta


class BandCalculator:
    """
    30dk mumlardan EMA48 + ATR48 hesaplar.
    Merkezden her iki yöne band_levels adet çizgi üretir.
    """

    def __init__(self, ema_period: int = 48, atr_period: int = 48, band_levels: int = 7):
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.band_levels = band_levels

    def calculate(self, klines: list) -> dict | None:
        """
        klines: Bybit'ten gelen ham liste (en yeni başta)
        Döner: {
            "ema": float,
            "atr": float,
            "upper": [u1, u2, ..., u7],   # merkeze yakından uzağa
            "lower": [l1, l2, ..., l7],   # merkeze yakından uzağa
        }
        """
        df = self._to_dataframe(klines)
        if len(df) < max(self.ema_period, self.atr_period) + 1:
            return None

        ema_series = ta.ema(df["close"], length=self.ema_period)
        atr_series = ta.atr(df["high"], df["low"], df["close"], length=self.atr_period)

        ema = float(ema_series.iloc[-1])
        atr = float(atr_series.iloc[-1])

        if pd.isna(ema) or pd.isna(atr):
            return None

        upper = [round(ema + atr * i, 8) for i in range(1, self.band_levels + 1)]
        lower = [round(ema - atr * i, 8) for i in range(1, self.band_levels + 1)]

        return {
            "ema": round(ema, 8),
            "atr": round(atr, 8),
            "upper": upper,
            "lower": lower,
        }

    def calculate_ce(self, klines: list, atr_multiplier: int = 2, atr_period: int = 48) -> dict | None:
        """
        Chandelier Exit değerlerini hesaplar.
        Döner: {"ce_long": float, "ce_short": float}
        ce_long  → Long pozisyon için aşağı takip eden CE (close - mult*ATR)
        ce_short → Short pozisyon için yukarı takip eden CE (close + mult*ATR)
        """
        df = self._to_dataframe(klines)
        if len(df) < atr_period + 1:
            return None

        atr_series = ta.atr(df["high"], df["low"], df["close"], length=atr_period)
        atr = float(atr_series.iloc[-1])
        close = float(df["close"].iloc[-1])

        if pd.isna(atr):
            return None

        return {
            "ce_long": round(close - atr_multiplier * atr, 8),
            "ce_short": round(close + atr_multiplier * atr, 8),
        }

    def calculate_stochastic(self, klines: list, k_length: int = 50, k_smooth: int = 21, d_smooth: int = 8) -> dict | None:
        df = self._to_dataframe(klines)
        df_closed = df.iloc[:-1]
        if len(df_closed) < k_length + k_smooth + d_smooth:
            return None
        stoch = ta.stoch(df_closed["high"], df_closed["low"], df_closed["close"],
                         k=k_length, d=d_smooth, smooth_k=k_smooth)
        if stoch is None or stoch.empty:
            return None
        try:
            k_col = [c for c in stoch.columns if c.startswith("STOCHk")][0]
            d_col = [c for c in stoch.columns if c.startswith("STOCHd")][0]
        except IndexError:
            return None
        k_s = stoch[k_col].dropna()
        d_s = stoch[d_col].dropna()
        if len(k_s) < 2 or len(d_s) < 2:
            return None
        return {
            "k_prev": float(k_s.iloc[-2]),
            "k_curr": float(k_s.iloc[-1]),
            "d_prev": float(d_s.iloc[-2]),
            "d_curr": float(d_s.iloc[-1]),
        }

    def calculate_macd(self, klines: list, fast: int = 50, slow: int = 21, signal: int = 9) -> dict | None:
        df = self._to_dataframe(klines)
        df_closed = df.iloc[:-1]
        if len(df_closed) < max(fast, slow) + signal:
            return None
        macd_df = ta.macd(df_closed["close"], fast=fast, slow=slow, signal=signal)
        if macd_df is None or macd_df.empty:
            return None
        try:
            macd_col = [c for c in macd_df.columns if c.startswith("MACD_")][0]
            sig_col  = [c for c in macd_df.columns if c.startswith("MACDs_")][0]
        except IndexError:
            return None
        m_s = macd_df[macd_col].dropna()
        s_s = macd_df[sig_col].dropna()
        if len(m_s) < 2 or len(s_s) < 2:
            return None
        return {
            "macd_prev":   float(m_s.iloc[-2]),
            "macd_curr":   float(m_s.iloc[-1]),
            "signal_prev": float(s_s.iloc[-2]),
            "signal_curr": float(s_s.iloc[-1]),
        }

    @staticmethod
    def _to_dataframe(klines: list) -> pd.DataFrame:
        # Bybit: [startTime, open, high, low, close, volume, turnover]
        df = pd.DataFrame(klines, columns=["time", "open", "high", "low", "close", "volume", "turnover"])
        df = df.astype({"open": float, "high": float, "low": float, "close": float})
        df = df.iloc[::-1].reset_index(drop=True)  # Bybit en yeni başta gönderir, eski→yeni sırala
        return df
