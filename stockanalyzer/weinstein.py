import pandas as pd
import numpy as np
import logging
from .benchmark import calculate_relative_strength, get_rs_slope

logger = logging.getLogger("stockanalyzer")

def calculate_true_weekly_stage(
    df_daily: pd.DataFrame,
    benchmark_weekly_close: pd.Series,
    sma30w_slope_bars: int = 10,
    rs_window: int = 52,
    min_weeks: int = 40,
) -> str:
    """
    Implements True Weinstein Stage Analysis using Weekly data and 
    Relative Strength vs synthetic benchmark.
    """
    try:
        # Step 1: Resample to Weekly
        weekly = df_daily.resample("W-FRI", on='datetime').agg({
            "open": "first", "high": "max",
            "low": "min", "close": "last", "volume": "sum"
        }).dropna(subset=["close"])

        # Step 2: History Check
        if len(weekly) < min_weeks:
            return "Insufficient Data"

        # Step 3: 30-week SMA
        weekly["sma30w"] = weekly["close"].rolling(30).mean()

        # Step 4: SMA Slope
        # slope = ((curr - prev) / prev) * 100
        sma_prev = weekly["sma30w"].shift(sma30w_slope_bars)
        weekly["slope"] = ((weekly["sma30w"] - sma_prev) / sma_prev) * 100

        # Step 5: Relative Strength Logic
        # Align benchmark to stock's weekly index
        b_aligned = benchmark_weekly_close.reindex(weekly.index).ffill()
        
        if b_aligned.dropna().empty or len(b_aligned.dropna()) < rs_window:
             return "Insufficient Data"

        weekly["rs"] = calculate_relative_strength(weekly["close"], b_aligned, window=rs_window)
        weekly["rs_slope"] = get_rs_slope(weekly["rs"], window=sma30w_slope_bars)

        # Step 6: Extract Latest State
        curr = weekly.iloc[-1]
        if pd.isna(curr["sma30w"]) or pd.isna(curr["rs"]):
            return "Insufficient Data"

        c = curr["close"]
        sma = curr["sma30w"]
        slope = curr["slope"]
        rs = curr["rs"]
        rs_slope = curr["rs_slope"]
        dist = ((c - sma) / sma) * 100

        # Step 7: Classification Rules

        # Stage 2 (Uptrend)
        if c > sma and slope > 0.3 and rs >= 1.0:
            return "Stage 2 (Uptrend)"

        # Stage 4 (Downtrend)
        if c < sma and slope < -0.3 and rs <= 1.0:
            return "Stage 4 (Downtrend)"

        # Stage 3 (Top)
        # Recent high check prevents labelling Stage 4 base as a Top
        recent_high = weekly["close"].tail(sma30w_slope_bars).max()
        recent_sma_avg = weekly["sma30w"].tail(sma30w_slope_bars).mean()
        
        if (abs(slope) < 0.5 and 
            dist <= 3.0 and 
            rs_slope < 0 and 
            recent_high > (recent_sma_avg * 1.02)):
            return "Stage 3 (Top)"

        # Stage 1 (Base)
        if (abs(slope) < 0.8 and 
            abs(dist) <= 8.0 and 
            rs_slope >= -0.05):
            return "Stage 1 (Base)"

        # Fallback (Directional)
        if c > sma and slope >= 0:
            return "Stage 2 (Uptrend)"
        elif c < sma and slope <= 0:
            return "Stage 4 (Downtrend)"
        elif c > sma and slope < 0:
            return "Stage 3 (Top)"
        else:
            return "Stage 1 (Base)"

    except Exception as e:
        logger.warning(f"Weinstein Weekly error: {e}")
        return "Insufficient Data"

def calculate_true_daily_stage(
    df_daily: pd.DataFrame,
    benchmark_daily_close: pd.Series,
    sma_period: int = 150,
    slope_bars: int = 50,
    rs_window: int = 150,
    min_days: int = 160,
) -> str:
    """
    Implements True Weinstein Stage Analysis for the Daily timeframe.
    Uses 150-day SMA as a proxy for the 30-week institutional trend.
    """
    try:
        # History check: Need enough for SMA + slope
        if len(df_daily) < min_days or benchmark_daily_close.empty:
            return "Insufficient Data"

        # 1. Institutional SMA (Proxy for 30-week)
        work_df = df_daily.copy()
        work_df["sma_inst"] = work_df["close"].rolling(sma_period).mean()
        
        # 2. Institutional Slope
        sma_prev = work_df["sma_inst"].shift(slope_bars)
        work_df["slope"] = ((work_df["sma_inst"] - sma_prev) / sma_prev) * 100

        # 3. Daily Relative Strength vs Daily Benchmark
        # Fix index mismatch: Align using the datetime column values
        b_aligned = benchmark_daily_close.reindex(work_df['datetime']).ffill()
        # Re-map the aligned values back to the integer index for calculations
        b_aligned.index = work_df.index
        
        if b_aligned.dropna().empty or len(b_aligned.dropna()) < rs_window:
            return "Insufficient Data"

        # Calculate RS Ratio using consistent window
        stock_ret = work_df["close"] / work_df["close"].shift(rs_window)
        bench_ret = b_aligned / b_aligned.shift(rs_window)
        work_df["rs"] = (stock_ret / bench_ret).fillna(0)
        work_df["rs_slope"] = work_df["rs"].diff(slope_bars).fillna(0)

        # 4. Extract Latest
        curr = work_df.iloc[-1]
        if pd.isna(curr["sma_inst"]) or pd.isna(curr["rs"]):
            return "Insufficient Data"

        c, sma, slope, rs, rs_slope = curr["close"], curr["sma_inst"], curr["slope"], curr["rs"], curr["rs_slope"]
        dist = ((c - sma) / sma) * 100

        # 5. Classification Rules
        if c > sma and slope > 0.3 and rs >= 1.0:
            return "Stage 2 (Uptrend)"

        if c < sma and slope < -0.3 and rs <= 1.0:
            return "Stage 4 (Downtrend)"

        recent_high = work_df["close"].tail(slope_bars).max()
        recent_sma_avg = work_df["sma_inst"].tail(slope_bars).mean()
        
        if abs(slope) < 0.5 and dist <= 3.0 and rs_slope < 0 and recent_high > (recent_sma_avg * 1.02):
            return "Stage 3 (Top)"

        if abs(slope) < 0.8 and abs(dist) <= 8.0 and rs_slope >= -0.05:
            return "Stage 1 (Base)"

        # Fallback
        if c > sma and slope >= 0: return "Stage 2 (Uptrend)"
        elif c < sma and slope <= 0: return "Stage 4 (Downtrend)"
        elif c > sma and slope < 0: return "Stage 3 (Top)"
        else: return "Stage 1 (Base)"

    except Exception as e:
        logger.warning(f"Weinstein Daily error: {e}")
        return "Insufficient Data"