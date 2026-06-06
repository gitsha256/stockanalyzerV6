import pandas as pd
import numpy as np
import logging
from typing import List

logger = logging.getLogger("stockanalyzer")

def build_benchmark_from_constituents(
    df: pd.DataFrame,
    min_history_days: int = 60,
) -> pd.DataFrame:
    """
    Builds a synthetic equal-weighted benchmark from constituent stock data.
    Each symbol is normalized to 1.0 at its start to ensure equal weighting.
    """
    required = {"datetime", "symbols", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"Benchmark build requires columns: {required}")

    # local copy and formatting
    work_df = df.copy()
    work_df['datetime'] = pd.to_datetime(work_df['datetime'])
    work_df = work_df[work_df['close'] > 0]

    # Filter symbols with insufficient history
    counts = work_df.groupby("symbols")["datetime"].count()
    valid_syms = counts[counts >= min_history_days].index
    work_df = work_df[work_df["symbols"].isin(valid_syms)]

    # Normalize each symbol to 1.0 at its first available close
    work_df = work_df.sort_values(["symbols", "datetime"])
    work_df["norm_close"] = work_df.groupby("symbols")["close"].transform(lambda x: x / x.iloc[0])

    # Calculate equal-weighted mean per day
    benchmark = (
        work_df.groupby("datetime")["norm_close"]
        .agg(close="mean", n_stocks="count")
        .sort_index()
    )

    return benchmark

def calculate_relative_strength(
    weekly_close: pd.Series,
    benchmark_weekly_close: pd.Series,
    window: int = 52,
) -> pd.Series:
    """
    Calculates Relative Strength ratio comparing stock 52-week returns 
    vs benchmark 52-week returns.
    """
    stock_return = weekly_close / weekly_close.shift(window)
    bench_return = benchmark_weekly_close / benchmark_weekly_close.shift(window)
    
    # Values > 1.0 = Outperforming, < 1.0 = Underperforming
    rs = stock_return / bench_return
    return rs

def get_rs_slope(rs_series: pd.Series, window: int = 10) -> pd.Series:
    """Calculates the change in RS over a specific window."""
    return rs_series.diff(window)