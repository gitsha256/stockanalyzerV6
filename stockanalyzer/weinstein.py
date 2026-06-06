import pandas as pd
from typing import Union

def calculate_weinstein_stage(df_p: pd.DataFrame, sma_col: str, rsi_col: str) -> str:
    """Determines the Weinstein Stage (1-4) based on price, SMA, and RSI."""
    if len(df_p) < 35: 
        return "Insufficient Data"
        
    curr, prev = df_p.iloc[-1], df_p.iloc[-4]
    c, s, sp, r = curr['close'], curr[sma_col], prev[sma_col], curr[rsi_col]
    if pd.isna(s) or pd.isna(sp) or pd.isna(r): return "Insufficient Data"
    slope = (s - sp) / sp * 100
    if c > s and slope > 0 and r >= 50: return "Stage 2 (Uptrend)"
    if c < s and slope < 0 and r < 50: return "Stage 4 (Downtrend)"
    if abs(c - s) / s <= 0.03 and abs(slope) < 0.5 and 40 <= r <= 60: return "Stage 1 (Base)"
    if c <= s * 1.03 and slope < 0 and 45 <= r <= 65: return "Stage 3 (Top)"
    return "Stage 1 (Base)"