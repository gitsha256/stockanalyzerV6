import pandas as pd
import numpy as np
import pandas_ta as ta
import logging

logger = logging.getLogger("stockanalyzer")

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Applies a comprehensive set of technical indicators to the dataframe."""
    if df is None or df.empty:
        return df

    try:
        # RSI
        df.ta.rsi(length=14, append=True)
        if 'RSI_14' in df.columns: df.rename(columns={'RSI_14': 'RSI'}, inplace=True)
        df.ta.rsi(length=2, append=True)

        # Moving Averages
        for length in [20, 30, 50, 100, 200]:
            df.ta.sma(length=length, append=True)
        df.ta.ema(length=21, append=True)

        # Trend & Momentum
        df.ta.adx(length=14, append=True)
        if 'ADX_14' in df.columns: df.rename(columns={'ADX_14': 'ADX'}, inplace=True)
        df.ta.supertrend(length=7, multiplier=3.0, append=True)
        df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
        df.ta.willr(length=14, append=True)
        df.ta.squeeze(length=20, kc_length=20, append=True)

        # Volume Indicators
        df.ta.obv(append=True)
        df.ta.cmf(length=20, append=True)
        df.ta.efi(length=13, append=True)

        # Bollinger Bands
        df.ta.bbands(length=20, std=2, append=True)
        rename_map = {
            'BBU_20_2.0': 'BB_UPPER',
            'BBM_20_2.0': 'BB_MIDDLE',
            'BBL_20_2.0': 'BB_LOWER'
        }
        for old, new in rename_map.items():
            found = [c for c in df.columns if c.startswith(old)]
            if found: df.rename(columns={found[0]: new}, inplace=True)

    except Exception as e:
        logger.warning(f"Error calculating some indicators: {e}")

    # Ensure column consistency
    expected = [
        'RSI', 'ADX', 'OBV', 'BB_UPPER', 'BB_MIDDLE', 'BB_LOWER',
        'SMA_20', 'SMA_50', 'SMA_100', 'SMA_200', 'CMF_20',
        'SUPERT_7_3.0', 'SUPERTd_7_3.0', 'STOCHk_14_3_3', 'STOCHd_14_3_3',
        'EMA_21', 'SQZ_ON', 'SQZ_OFF', 'SQZ_NO', 'WILLR_14', 'EFI_13', 'RSI_2'
    ]
    for col in expected:
        if col not in df.columns:
            df[col] = np.nan

    return df