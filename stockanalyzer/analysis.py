import pandas as pd
import numpy as np
import pandas_ta as ta
import os
from scipy.signal import argrelextrema
from tqdm import tqdm
import logging
from typing import Optional, Tuple
from datetime import datetime
from .indicators import add_indicators
from .patterns import detect_price_patterns
from .weinstein import calculate_true_weekly_stage, calculate_true_daily_stage

logger = logging.getLogger("stockanalyzer")

def analyze_symbol(symbol: str, full_df: pd.DataFrame, benchmark_daily_close: pd.Series, benchmark_weekly_close: pd.Series, enable_patterns: bool = True) -> Tuple[Optional[pd.DataFrame], bool]:
    """Performs full technical analysis on a single symbol."""
    is_hit = False
    data = full_df[full_df['symbols'] == symbol].sort_values('datetime')
    if data.empty:
        return None, False
    if len(data) < 20:
        return None, False
    
    try:
        data = data.copy()
        data['Change'] = (data['close'] - data['open']) / data['open'] * 100
        data = add_indicators(data)
        
        # Squeeze & Bollinger Band Logic
        data['BB_BANDWIDTH'] = (data['BB_UPPER'] - data['BB_LOWER']) / data['BB_MIDDLE']
        data['BB_SQUEEZE'] = data['BB_BANDWIDTH'].rolling(301, min_periods=1).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100 <= 5, raw=True).astype(bool)
        data['BB_BREAKOUT_UP'] = (data['close'] > data['BB_UPPER']) & (data['close'].shift(1) <= data['BB_UPPER'].shift(1))
        data['BB_BREAKOUT_DOWN'] = (data['close'] < data['BB_LOWER']) & (data['close'].shift(1) >= data['BB_LOWER'].shift(1))
        
        # High/Low & Swings
        data['52W_High'] = data['high'].rolling(252, min_periods=1).max()
        data['52W_Low'] = data['low'].rolling(252, min_periods=1).min()
        
        # Long-term swings (order=252)
        data['SWING_HIGH'] = 0
        data['SWING_LOW'] = 0
        h_idx = argrelextrema(data['close'].values, np.greater_equal, order=252)[0]
        l_idx = argrelextrema(data['close'].values, np.less_equal, order=252)[0]
        data.iloc[h_idx, data.columns.get_loc('SWING_HIGH')] = 1
        data.iloc[l_idx, data.columns.get_loc('SWING_LOW')] = 1

        # Medium-term swings (order=60 anchors)
        data['MT_SWING_HIGH'] = 0
        data['MT_SWING_LOW'] = 0
        mt_h_idx = argrelextrema(data['close'].values, np.greater_equal, order=60)[0]
        mt_l_idx = argrelextrema(data['close'].values, np.less_equal, order=60)[0]
        data.iloc[mt_h_idx, data.columns.get_loc('MT_SWING_HIGH')] = 1
        data.iloc[mt_l_idx, data.columns.get_loc('MT_SWING_LOW')] = 1

        # Volume and Activity Metrics
        data['AVG_VOLUME_20'] = data['volume'].rolling(window=20, min_periods=1).mean()
        data['RELATIVE_VOLUME'] = data['volume'] / data['AVG_VOLUME_20']
        data['VOLUME_SPIKE'] = data['RELATIVE_VOLUME'] > 2
        data['ACTIVITY_SCORE'] = data['close'] * data['volume'] / 1e7

        # Weinstein Stage Analysis
        swing_stage = calculate_true_daily_stage(data, benchmark_daily_close)
        
        # Weinstein True Weekly Stage (New Logic)
        weekly_stage = calculate_true_weekly_stage(data, benchmark_weekly_close)

        # Weekly RSI and SMA30 for display
        weekly_df = data.resample('W-FRI', on='datetime').agg({'close': 'last'}).dropna()
        if len(weekly_df) > 14:
            w_rsi_series = ta.rsi(weekly_df['close'], length=14)
            w_rsi = w_rsi_series.iloc[-1] if w_rsi_series is not None and not w_rsi_series.empty else np.nan
        else:
            w_rsi = np.nan
            
        w_sma30 = weekly_df['close'].rolling(30).mean().iloc[-1] if len(weekly_df) >= 30 else np.nan

        latest = data.iloc[-1]
        close = latest['close']
        
        # Adaptive Zone Logic
        swing_high = data[data['SWING_HIGH'] == 1]['close'].iloc[-1] if not data[data['SWING_HIGH'] == 1].empty else np.nan
        swing_low = data[data['SWING_LOW'] == 1]['close'].iloc[-1] if not data[data['SWING_LOW'] == 1].empty else np.nan
        if pd.isna(swing_high) or pd.isna(swing_low) or swing_high == swing_low:
            zone, midpoint = "NO DATA", np.nan
        else:
            midpoint = (swing_high + swing_low) / 2
            rel_pos = (close - swing_low) / (swing_high - swing_low)
            if 0.45 <= rel_pos <= 0.55: zone = "Equilibrium"
            elif rel_pos <= 0.25: zone = "Discount"
            elif rel_pos >= 0.75: zone = "Premium"
            elif rel_pos < 0.50: zone = "Near Discount"
            else: zone = "Near Premium"

        # Medium-term Zone Logic
        mt_sh = data[data['MT_SWING_HIGH'] == 1]['close'].iloc[-1] if not data[data['MT_SWING_HIGH'] == 1].empty else np.nan
        mt_sl = data[data['MT_SWING_LOW'] == 1]['close'].iloc[-1] if not data[data['MT_SWING_LOW'] == 1].empty else np.nan
        if pd.isna(mt_sh) or pd.isna(mt_sl) or mt_sh == mt_sl:
            mt_zone = "NO DATA"
        else:
            mt_rel = (close - mt_sl) / (mt_sh - mt_sl)
            if 0.45 <= mt_rel <= 0.55: mt_zone = "Equilibrium"
            elif mt_rel <= 0.25: mt_zone = "Discount"
            elif mt_rel >= 0.75: mt_zone = "Premium"
            elif mt_rel < 0.50: mt_zone = "Near Discount"
            else: mt_zone = "Near Premium"
        
        # Trend Context
        above_200 = close > latest['SMA_200'] if pd.notna(latest['SMA_200']) else False
        above_50 = close > latest['SMA_50'] if pd.notna(latest['SMA_50']) else False
        above_20 = close > latest['SMA_20'] if pd.notna(latest['SMA_20']) else False
        
        per = round((latest['52W_High'] - close) / latest['52W_High'] * 100, 2) if pd.notna(latest['52W_High']) else np.nan
        vol_trend = "Increasing" if latest['volume'] > data['volume'].rolling(window=10).mean().iloc[-1] else "Decreasing"
        trend = ("Uptrend" if latest['ADX'] > 25 and (latest['SMA_50'] - data['SMA_50'].iloc[-5]) / 5 > 0 else
                 "Downtrend" if latest['ADX'] > 25 else "Sideways")
        t_strength = "Strong" if latest['ADX'] > 25 else "Moderate" if latest['ADX'] > 15 else "Weak"
        volatility = data['close'].pct_change().rolling(window=21).std().iloc[-1] * np.sqrt(252) * 100 if len(data) >= 21 else np.nan

        if enable_patterns:
            from .pattern_cache import compute_symbol_state_hash, get_cached_pattern, save_pattern_cache
            
            # Calculate state hash for the current symbol data
            hash12 = compute_symbol_state_hash(data)
            cached = get_cached_pattern(symbol, hash12)
            
            if cached is not None:
                # Restore from cache
                main_pattern = cached.get("mpat") or "No Clear Pattern"
                p_conf = cached.get("pcon") if cached.get("pcon") is not None else np.nan
                p_start = cached.get("psta") or ""
                p_end = cached.get("pend") or ""
                p_points = cached.get("ppnt") or ""
                misc_patterns = cached.get("xpat") or ""
                pattern = cached.get("patt") or "No Clear Pattern"
                is_hit = True
            else:
                # Compute and save to cache
                pattern_info = detect_price_patterns(data)
                pattern = pattern_info.get('all_patterns', 'No Clear Pattern')
                main_pattern = pattern_info.get('main_pattern', 'No Clear Pattern')
                misc_patterns = pattern_info.get('misc_patterns', '')
                p_conf = pattern_info.get('main_confidence', 0)
                p_points = pattern_info.get('pattern_points', '')
                p_start = pattern_info.get('pattern_start', '')
                p_end = pattern_info.get('pattern_end', '')
                
                save_pattern_cache(symbol, hash12, {
                    "mpat": main_pattern,
                    "pcon": p_conf,
                    "psta": p_start,
                    "pend": p_end,
                    "ppnt": p_points,
                    "xpat": misc_patterns,
                    "patt": pattern
                })
                is_hit = False
        else:
            pattern = main_pattern = misc_patterns = 'Disabled'
            p_conf = 0; p_points = p_start = p_end = ''

        row = {
            'datetime': latest['datetime'], 'symbols': symbol, 'close': round(close, 2), 'volume': latest['volume'],
            'Dl Per': round(latest['delivery_perc'], 2) if 'delivery_perc' in latest else np.nan,
            'CHANGE': round(latest['Change'], 2), 'SMA_200': round(latest['SMA_200'], 2),
            'ZONE': zone, 'MT_ZONE': mt_zone, 'RSI': round(latest['RSI'], 2), 'delta': per,
            '>200': above_200, '>50': above_50, '>20': above_20,
            'OBV': round(latest['OBV'], 2), 'VOLUME_TREND': vol_trend, 'ADX': round(latest['ADX'], 2),
            'CMF_20': round(latest['CMF_20'], 2) if 'CMF_20' in latest else np.nan,
            'SUPERT_7_3.0': round(latest['SUPERT_7_3.0'], 2) if 'SUPERT_7_3.0' in latest else np.nan,
            'SUPERTd_7_3.0': round(latest['SUPERTd_7_3.0'], 2) if 'SUPERTd_7_3.0' in latest else np.nan,
            'STOCHk_14_3_3': round(latest['STOCHk_14_3_3'], 2) if 'STOCHk_14_3_3' in latest else np.nan,
            'STOCHd_14_3_3': round(latest['STOCHd_14_3_3'], 2) if 'STOCHd_14_3_3' in latest else np.nan,
            'EMA_21': round(latest['EMA_21'], 2) if 'EMA_21' in latest else np.nan,
            'SQZ_ON': latest['SQZ_ON'] if 'SQZ_ON' in latest else np.nan,
            'SQZ_OFF': latest['SQZ_OFF'] if 'SQZ_OFF' in latest else np.nan,
            'SQZ_NO': latest['SQZ_NO'] if 'SQZ_NO' in latest else np.nan,
            'WILLR_14': round(latest['WILLR_14'], 2) if 'WILLR_14' in latest else np.nan,
            'EFI_13': round(latest['EFI_13'], 2) if 'EFI_13' in latest else np.nan,
            'RSI_2': round(latest['RSI_2'], 2) if 'RSI_2' in latest else np.nan,
            'open': round(latest['open'], 2), 'TREND': trend, 'TREND_STRENGTH': t_strength,
            'BB_BREAKOUT_UP': latest['BB_BREAKOUT_UP'], 'BB_BREAKOUT_DOWN': latest['BB_BREAKOUT_DOWN'],
            'BB_BANDWIDTH': round(latest['BB_BANDWIDTH'], 4), 'BB_SQUEEZE': latest['BB_SQUEEZE'],
            'VOLATILITY_%': round(volatility, 2), 'S_HIGH': round(swing_high, 2),
            'S_LOW': round(swing_low, 2), 'high': round(latest['high'], 2), 'low': round(latest['low'], 2),
            'EQB': round(midpoint, 2),
            'W_RSI': round(w_rsi, 2), 'W_SMA30': round(w_sma30, 2), 
            'STAGE': swing_stage, 'STAGE_W': weekly_stage,
            'RELATIVE_VOLUME': round(latest['RELATIVE_VOLUME'], 2), 'VOLUME_SPIKE': latest['VOLUME_SPIKE'],
            'ACTIVITY_SCORE': round(latest['ACTIVITY_SCORE'], 2), 'SMA20': round(latest['SMA_20'], 2),
            'SMA50': round(latest['SMA_50'], 2), 'SMA100': round(latest['SMA_100'], 2),
            '52HIGH': round(latest['52W_High'], 2), '52LOW': round(latest['52W_Low'], 2),
            'PATTERN': pattern, 'MAIN_PATTERN': main_pattern, 'MISC_PATTERNS': misc_patterns,
            'PATTERN_CONFIDENCE': p_conf, 'PATTERN_POINTS': p_points,
            'PATTERN_START': p_start, 'PATTERN_END': p_end
        }
        return pd.DataFrame([row]), is_hit
    except Exception as e:
        logger.debug(f"Error analyzing {symbol}: {e}")
        return None, False

def perform_technical_analysis(df: pd.DataFrame, sector_df: pd.DataFrame, enable_patterns: bool = True) -> pd.DataFrame:
    """Orchestrates analysis, applies rankings, and handles sector mapping."""
    # Step A: Build Benchmark ONCE
    from .benchmark import build_benchmark_from_constituents
    
    logger.info("Building synthetic equal-weighted benchmark...")
    bench_df = build_benchmark_from_constituents(df, min_history_days=60)
    benchmark_close = bench_df["close"] # Daily Series
    
    # Sanity check contributors
    thin = bench_df[bench_df["n_stocks"] < 450]
    if not thin.empty:
        logger.warning(f"[BENCHMARK] {len(thin)} dates have fewer than 450 stock contributors")

    # Resample benchmark to weekly once
    benchmark_weekly_close = bench_df["close"].resample("W-FRI").last().dropna()

    # Filter valid symbols
    all_syms = df['symbols'].unique()
    valid_symbols = [s for s in all_syms if len(df[df['symbols'] == s]) >= 20]
    
    cache_hits = 0
    cache_misses = 0
    
    results = []
    for s in tqdm(valid_symbols, desc="Analyzing Symbols"):
        res, is_hit = analyze_symbol(s, df, benchmark_close, benchmark_weekly_close, enable_patterns)
        if res is not None:
            results.append(res)
            if enable_patterns:
                if is_hit: cache_hits += 1
                else: cache_misses += 1
        
    if not results:
        return pd.DataFrame()
        
    if enable_patterns and (cache_hits + cache_misses > 0):
        ratio = (cache_hits / (cache_hits + cache_misses)) * 100
        print(f"[CACHE] Hit: {cache_hits} | Miss: {cache_misses} | Ratio: {ratio:.1f}%")
        
    analysis_df = pd.concat(results, ignore_index=True)
    
    # Calculate Rankings (Matches oldanalyzer.py logic)
    analysis_df['VOLUME_RANK'] = analysis_df['volume'].rank(ascending=False, method='min')
    analysis_df['ACTIVITY_RANK'] = analysis_df['ACTIVITY_SCORE'].rank(ascending=False, method='min')
    analysis_df['RELATIVE_VOLUME_RANK'] = analysis_df['RELATIVE_VOLUME'].rank(ascending=False, method='min')
    analysis_df = analysis_df.sort_values(['ACTIVITY_SCORE', 'RELATIVE_VOLUME'], ascending=[False, False])
    
    # Sector Mapping
    try:
        analysis_df['symbols'] = analysis_df['symbols'].astype(str)
        if not sector_df.empty:
            sector_df['symbols'] = sector_df['symbols'].astype(str)
            analysis_df = analysis_df.merge(sector_df[['symbols', 'SECTOR']], on='symbols', how='left')
        
        if 'SECTOR' not in analysis_df.columns:
            analysis_df['SECTOR'] = 'Unknown'
        analysis_df['SECTOR'] = analysis_df['SECTOR'].fillna('Unknown')
    except Exception as e:
        logger.error(f"Error merging sector data: {e}")

    # Comprehensive Column Remapping
    col_map = {
        'datetime': 'date', 'symbols': 'symb', 'close': 'clos', 'volume': 'volu',
        'Dl Per': 'DlPer', 'RELATIVE_VOLUME': 'rvol', 'VOLUME_SPIKE': 'vspk', 'ACTIVITY_SCORE': 'ascr',
        'ACTIVITY_RANK': 'arnk', 'CHANGE': 'chan', '>200': 'g200', 'ZONE': 'zone', 'MT_ZONE': 'MT_Zone',
        'STAGE_W': 'stge_w', 'RSI': 'rsi', 'delta': 'delt', 'OBV': 'obv', 'BB_BREAKOUT_UP': 'bbup',
        'VOLUME_TREND': 'vtrd', 'BB_BANDWIDTH': 'bbbw', '>50': 'g050', '>20': 'g020', 'ADX': 'adx',
        'open': 'open', 'BB_BREAKOUT_DOWN': 'bbdn', 'BB_SQUEEZE': 'bbsq', 'S_HIGH': 'shgh', 'S_LOW': 'slw',
        'high': 'high', 'low': 'low', 'EQB': 'eqb', 'SMA20': 's020', 'SMA50': 's050', 'SMA100': 's100',
        'SMA_200': 's200', '52HIGH': 'h52h', '52LOW': 'l52l', 'VOLUME_RANK': 'vrnk', 'RELATIVE_VOLUME_RANK': 'rrnk',
        'TREND': 'tren', 'TREND_STRENGTH': 'tstr', 'VOLATILITY_%': 'vola', 
        'W_RSI': 'wrsi', 'W_SMA30': 'ws30', 'STAGE': 'stge',
        'PATTERN': 'patt', 'MAIN_PATTERN': 'mpat', 'MISC_PATTERNS': 'xpat', 'PATTERN_CONFIDENCE': 'pcon',
        'PATTERN_POINTS': 'ppnt', 'PATTERN_START': 'psta', 'PATTERN_END': 'pend', 'SECTOR': 'sect'
    }
    analysis_df.rename(columns={k: v for k, v in col_map.items() if k in analysis_df.columns}, inplace=True)

    # institutional Column Ordering
    desired_order = [
        'date','symb','clos','stge','stge_w','wrsi','ws30','volu','DlPer','rvol','vspk','ascr','arnk','chan','g200','zone','MT_Zone','rsi','delt','bbup','vtrd','bbbw','bbsq',
        'g050','g020','adx','CMF_20','SUPERT_7_3.0','SUPERTd_7_3.0','STOCHk_14_3_3','STOCHd_14_3_3','EMA_21','SQZ_ON','SQZ_OFF','SQZ_NO','WILLR_14','EFI_13','RSI_2','open','bbdn','shgh','slw','high','low','eqb','s020','s050','s100','s200','h52h','l52l','vrnk','rrnk',
        'tren','tstr','vola','mpat','pcon','psta','pend','ppnt','xpat','patt','obv','sect'
    ]
    
    final_cols = [c for c in desired_order if c in analysis_df.columns]
    extra_cols = [c for c in analysis_df.columns if c not in final_cols]
    
    return analysis_df[final_cols + extra_cols]