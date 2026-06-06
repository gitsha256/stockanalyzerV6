import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from nselib import capital_market
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from scipy.signal import argrelextrema
import pandas_ta as ta
import logging

# Configuration
CONFIG = {
    'SYMBOLS_FILE': 'symbols.csv',
    'RAW_DATA_FILE': 'raw_data.csv',
    'ADJUSTED_DATA_FILE': 'data.csv',
    'SPLITS_LOG_FILE': 'detected_splits.csv',
    'ANALYSIS_OUTPUT_FILE': 'snapshot.csv',
    'MAX_WORKERS': 6,
    'DEFAULT_LOOKBACK_DAYS': 756,  # 3 years to support weekly SMA/long-term patterns
    'FETCH_INTERVAL': 'D',
    'REQUIRED_COLUMNS': ['datetime', 'open', 'high', 'low', 'close', 'volume', 'symbols'],
    # Chart patterns: expanded to last 4 calendar months for better structural clarity.
    'PATTERN_MAX_AGE_DAYS': 252,  # Look back 1 year for major structures
    'PATTERN_MIN_BARS_IN_WINDOW': 70,
    # Weekly pivot spacing (bars) — avoids triple bottom from 3 lows in one week.
    'PATTERN_WEEKLY_PIVOT_ORDER': 2,
    'PATTERN_WEEKLY_MIN_GAP': 2,
    'PATTERN_WEEKLY_MIN_DOUBLE_SPAN': 3,
    'PATTERN_WEEKLY_MIN_TRIPLE_SPAN': 5,
    'PATTERN_WEEKLY_MIN_HS_SPAN': 4,
    # Daily pivots for flags only (smoother swings).
    'PATTERN_DAILY_PIVOT_ORDER_MIN': 8,
    'PATTERN_DAILY_PIVOT_ORDER_MAX': 14,
}

# Setup logging
def setup_logging(verbose=True):
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.FileHandler('workflow.log'), logging.StreamHandler()]
    )
    return logging.getLogger(__name__)

# Modified load_symbols to handle holidays column
def load_symbols(filepath, logger):
    try:
        df = pd.read_csv(filepath)
        df.columns = df.columns.str.strip().str.upper()
        if 'SYMBOL' not in df.columns:
            logger.error(f"'SYMBOL' column missing in {filepath}")
            return [], pd.DataFrame(), set()
        df['SYMBOL'] = df['SYMBOL'].astype(str).str.upper().str.strip().str.replace('.NS', '', regex=False).str.replace('-EQ', '', regex=False)
        symbols = df['SYMBOL'].dropna().unique().tolist()
        sector_df = df[['SYMBOL', 'SECTOR']].drop_duplicates().rename(columns={'SYMBOL': 'symbols'}) if 'SECTOR' in df.columns else pd.DataFrame()
        
        # Extract holidays
        holidays = set()
        if 'HOLIDAYS' in df.columns:
            holiday_list = df['HOLIDAYS'].dropna().astype(str).str.strip().str.split(';').explode().str.strip()
            for date_str in holiday_list:
                try:
                    holiday_date = pd.to_datetime(date_str, format='%d-%m-%Y', errors='coerce')
                    if pd.notna(holiday_date):
                        holidays.add(holiday_date.date())
                except Exception as e:
                    logger.warning(f"Invalid holiday date format '{date_str}' in {filepath}: {e}")
        else:
            logger.warning(f"No 'HOLIDAYS' column found in {filepath}. Assuming no holidays.")
        
        logger.info(f"Loaded {len(symbols)} symbols and {len(holidays)} holiday dates")
        return symbols, sector_df, holidays
    except Exception as e:
        logger.error(f"Error loading {filepath}: {e}")
        return [], pd.DataFrame(), set()

# Modified get_nse_holiday_dates to use holidays from symbols.csv
def get_nse_holiday_dates(symbols_file, logger):
    _, _, holidays = load_symbols(symbols_file, logger)
    logger.info(f"Holidays loaded from {symbols_file}: {sorted(holidays)}")
    return holidays

def standardize_data(df, filepath='', logger=None):
    if df.empty:
        if logger: logger.warning(f"No data in {filepath or 'DataFrame'}")
        return df
    try:
        df.columns = df.columns.str.strip().str.lower()
        if not all(col in df.columns for col in CONFIG['REQUIRED_COLUMNS']):
            if logger: logger.error(f"Missing required columns in {filepath or 'DataFrame'}: {CONFIG['REQUIRED_COLUMNS']}")
            return pd.DataFrame()
        df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
        df['symbols'] = df['symbols'].astype(str).str.upper().str.strip().str.replace('.NS', '', regex=False).str.replace('-EQ', '', regex=False)
        df = df.dropna(subset=['datetime', 'symbols']).sort_values(['symbols', 'datetime']).drop_duplicates(['symbols', 'datetime'], keep='last')
        if logger:
            logger.info(f"Standardized {len(df)} records from {filepath or 'DataFrame'}")
        return df
    except Exception as e:
        if logger: logger.error(f"Error standardizing data from {filepath}: {e}")
        return pd.DataFrame()


def add_indicators(df):
    if df is None or df.empty:
        print("Warning: add_indicators received empty DataFrame")
        return df

    original_columns = list(df.columns)

    try:
        df.ta.rsi(length=14, append=True)
        if 'RSI' not in df.columns and 'RSI_14' in df.columns:
            df.rename(columns={'RSI_14': 'RSI'}, inplace=True)
    except Exception as e:
        print(f"Warning: RSI failed: {e}")

    try:
        for length in [20, 30, 50, 100, 200]:
            df.ta.sma(length=length, append=True)
    except Exception as e:
        print(f"Warning: SMA failed: {e}")

    try:
        df.ta.adx(length=14, append=True)
        if 'ADX' not in df.columns and 'ADX_14' in df.columns:
            df.rename(columns={'ADX_14': 'ADX'}, inplace=True)
    except Exception as e:
        print(f"Warning: ADX failed: {e}")

    try:
        df.ta.obv(append=True)
    except Exception as e:
        print(f"Warning: OBV failed: {e}")

    try:
        df.ta.bbands(length=20, std=2, append=True)
        rename_map = {}
        for col in df.columns:
            if col.startswith('BBU_20_2.0'):
                rename_map[col] = 'BB_UPPER'
            elif col.startswith('BBM_20_2.0'):
                rename_map[col] = 'BB_MIDDLE'
            elif col.startswith('BBL_20_2.0'):
                rename_map[col] = 'BB_LOWER'
        if rename_map:
            df.rename(columns=rename_map, inplace=True)
    except Exception as e:
        print(f"Warning: Bollinger Bands failed: {e}")

    try:
        df.ta.cmf(length=20, append=True)
    except Exception as e:
        print(f"Warning: CMF failed: {e}")

    try:
        df.ta.supertrend(length=7, multiplier=3.0, high='high', low='low', close='close', append=True)
    except Exception as e:
        print(f"Warning: Supertrend failed: {e}")

    try:
        df.ta.stoch(k=14, d=3, smooth_k=3, append=True)
    except Exception as e:
        print(f"Warning: Stochastic failed: {e}")

    try:
        df.ta.ema(length=21, append=True)
    except Exception as e:
        print(f"Warning: EMA 21 failed: {e}")

    try:
        df.ta.squeeze(length=20, kc_length=20, append=True)
    except Exception as e:
        print(f"Warning: Squeeze failed: {e}")

    try:
        df.ta.willr(length=14, append=True)
    except Exception as e:
        print(f"Warning: Williams %R failed: {e}")

    try:
        df.ta.efi(length=13, append=True)
    except Exception as e:
        print(f"Warning: Elder Force Index failed: {e}")

    try:
        df.ta.rsi(length=2, append=True)
    except Exception as e:
        print(f"Warning: RSI 2 failed: {e}")

    optional_indicator_columns = [
        'RSI', 'ADX', 'OBV', 'BB_UPPER', 'BB_MIDDLE', 'BB_LOWER',
        'SMA_20', 'SMA_50', 'SMA_100', 'SMA_200', 'CMF_20',
        'SUPERT_7_3.0', 'SUPERTd_7_3.0', 'STOCHk_14_3_3', 'STOCHd_14_3_3',
        'EMA_21', 'SQZ_ON', 'SQZ_OFF', 'SQZ_NO', 'WILLR_14', 'EFI_13', 'RSI_2'
    ]
    for col in optional_indicator_columns:
        if col not in df.columns:
            df[col] = np.nan

    return df


def fetch_and_format(trade_date, symbol_filter=None, logger=None):
    try:
        spot_data = capital_market.bhav_copy_with_delivery(trade_date=trade_date)
        logger.info(f"Raw data for {trade_date}: {spot_data.shape} rows, columns: {spot_data.columns.tolist()}")
        ohlcv_columns = [
            'SYMBOL', 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY', 'DELIV_PER'
        ]
        available_cols = [col for col in ohlcv_columns if col in spot_data.columns]
        if not all(col in spot_data.columns for col in ['SYMBOL', 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY']):
            if logger: logger.warning(f"Missing expected columns in bhav copy for {trade_date}: {available_cols}")
            return None
        spot_ohlcv = spot_data[available_cols].copy()

        numeric_columns = [col for col in ['OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY', 'DELIV_PER'] if col in spot_ohlcv.columns]
        for col in numeric_columns:
            spot_ohlcv[col] = pd.to_numeric(spot_ohlcv[col], errors='coerce')

        spot_ohlcv.rename(columns={
            'SYMBOL': 'symbols',
            'OPEN_PRICE': 'open',
            'HIGH_PRICE': 'high',
            'LOW_PRICE': 'low',
            'CLOSE_PRICE': 'close',
            'TTL_TRD_QNTY': 'volume',
            'DELIV_PER': 'delivery_perc'
        }, inplace=True)

        spot_ohlcv['symbols'] = spot_ohlcv['symbols'].str.upper().str.strip()
        spot_ohlcv['datetime'] = pd.to_datetime(trade_date, format='%d-%m-%Y')
        spot_ohlcv = spot_ohlcv.dropna(subset=['open', 'high', 'low', 'close', 'volume'])

        if symbol_filter is not None:
            spot_ohlcv = spot_ohlcv[spot_ohlcv['symbols'].isin(symbol_filter)]

        cols = spot_ohlcv.columns.tolist()
        if 'delivery_perc' in cols:
            cols.remove('delivery_perc')
            close_idx = cols.index('close')
            cols = cols[:close_idx+1] + ['delivery_perc'] + cols[close_idx+1:]
            spot_ohlcv = spot_ohlcv[cols]

        logger.info(f"Fetched {spot_ohlcv.shape[0]} records for {trade_date} after processing")
        return spot_ohlcv
    except Exception as e:
        if logger: logger.warning(f"Failed to fetch data for {trade_date}: {e}")
        return None

def fetch_data(symbols, from_date, to_date, logger):
    all_data = []
    date_list = []
    current_date = from_date

    nse_holidays = get_nse_holiday_dates(CONFIG['SYMBOLS_FILE'], logger)
    logger.info(f"Holidays: {sorted(nse_holidays)}")

    try:
        while current_date <= to_date:
            if current_date.weekday() < 5 and current_date.date() not in nse_holidays:
                date_list.append(current_date.strftime('%d-%m-%Y'))
            current_date += timedelta(days=1)

        logger.info(f"Fetching data for {len(date_list)} dates (weekdays & non-holidays): {date_list}")
        if not date_list:
            logger.warning("No valid trading dates to fetch")
            return pd.DataFrame()

        with ThreadPoolExecutor(max_workers=CONFIG['MAX_WORKERS']) as executor:
            futures = {executor.submit(fetch_and_format, d, symbols, logger): d for d in date_list}
            for future in tqdm(as_completed(futures), total=len(futures), desc="Fetching data"):
                trade_date = futures[future]
                result = future.result()
                if result is not None and not result.empty:
                    all_data.append(result)
                else:
                    logger.warning(f"No valid data fetched for {trade_date}")

        if not all_data:
            logger.error("No data fetched")
            return pd.DataFrame()

        combined_df = pd.concat(all_data, ignore_index=True)
        combined_df = standardize_data(combined_df, logger=logger)
        
        for symbol in symbols:
            symbol_data = combined_df[combined_df['symbols'] == symbol]
            if len(symbol_data) == 0:
                logger.warning(f"Symbol {symbol} has no data after standardization")
        
        return combined_df
    
    except Exception as e:
        logger.error(f"Error in fetch_data: {e}")
        return pd.DataFrame()

def detect_splits(symbol_data, logger):
    try:
        if len(symbol_data) < 2:
            symbol = symbol_data['symbols'].iloc[0] if not symbol_data.empty else 'unknown'
            logger.warning(f"Skipping split detection for {symbol}: insufficient data ({len(symbol_data)} rows)")
            return pd.DataFrame()

        symbol_data = symbol_data.sort_values('datetime').reset_index(drop=True)
        price_diffs = symbol_data['close'].pct_change()
        splits = []

        for idx in price_diffs[price_diffs <= -0.3].index:
            if idx == 0:
                continue
            prev, curr = symbol_data['close'].iloc[idx - 1], symbol_data['close'].iloc[idx]
            if pd.isna(prev) or pd.isna(curr):
                continue
            ratio = prev / curr
            if 1.5 <= ratio <= 12:
                splits.append({
                    'symbols': symbol_data['symbols'].iloc[0],
                    'SPLIT_DATE': symbol_data['datetime'].iloc[idx],
                    'SPLIT_RATIO': round(ratio, 2),
                    'PREV_CLOSE': prev,
                    'CURR_CLOSE': curr
                })

        return pd.DataFrame(splits)
    
    except Exception as e:
        logger.error(f"Error detecting splits for {symbol_data['symbols'].iloc[0] if not symbol_data.empty else 'unknown'}: {e}")
        return pd.DataFrame()

def adjust_prices(df, logger):
    if df is None or df.empty:
        logger.warning("Input DataFrame is empty or None. Skipping adjustment.")
        return df, pd.DataFrame()

    try:
        splits = pd.concat(
            [detect_splits(df[df['symbols'] == s], logger) for s in df['symbols'].unique()],
            ignore_index=True
        )
        adjusted = df.copy()
        if not splits.empty:
            for _, split in splits.iterrows():
                mask = (adjusted['symbols'] == split['symbols']) & (adjusted['datetime'] < split['SPLIT_DATE'])
                adjusted.loc[mask, ['open', 'high', 'low', 'close']] /= split['SPLIT_RATIO']
            logger.info('Adjusted splits')
            print(f"Adjusted {len(adjusted)} records with {len(splits)} splits detected")
        return adjusted, splits
        
        
    except Exception as e:
        logger.error(f"Error during split adjustment: {e}")
        return df, pd.DataFrame()

def _pivot_points(data, order=5, lookback=120):
    recent = data.tail(lookback).reset_index(drop=True)
    prices = recent['close'].values.astype(float)
    if len(prices) < 2 * order + 1:
        return recent, [], []
    
    # Standard extrema (confirmed)
    high_idx = argrelextrema(prices, np.greater_equal, order=order)[0]
    low_idx = argrelextrema(prices, np.less_equal, order=order)[0]
    
    # Strict Confirmation: Filter out pivots that occurred within the last 'order' bars.
    # This prevents 'developing' prices from being flagged as completed pivots.
    high_idx = [i for i in high_idx if i < len(prices) - order]
    low_idx = [i for i in low_idx if i < len(prices) - order]
    
    highs = [(int(i), float(prices[i])) for i in high_idx]
    lows = [(int(i), float(prices[i])) for i in low_idx]
    return recent, highs, lows

def _resample_to_weekly(daily_df):
    """Aggregate daily OHLCV to weekly (Fri) for higher-timeframe pattern structure."""
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()
    d = daily_df.sort_values('datetime').copy()
    d['datetime'] = pd.to_datetime(d['datetime'])
    d = d.set_index('datetime')
    agg = {}
    for col, how in [('open', 'first'), ('high', 'max'), ('low', 'min'), ('close', 'last'), ('volume', 'sum')]:
        if col in d.columns:
            agg[col] = how
    if not agg:
        return pd.DataFrame()
    w = d.resample('W-FRI').agg(agg).dropna(subset=['close'])
    return w.reset_index()

def _pivot_indices_spaced(idxs, min_gap, min_span):
    if len(idxs) < 2:
        return False
    for a in range(len(idxs) - 1):
        if idxs[a + 1] - idxs[a] < min_gap:
            return False
    return idxs[-1] - idxs[0] >= min_span

def _chain_spaced(idxs, min_gap):
    if len(idxs) < 2:
        return True
    for a in range(len(idxs) - 1):
        if idxs[a + 1] - idxs[a] < min_gap:
            return False
    return True

def _line_slope(points):
    if len(points) < 2:
        return 0.0
    y = np.array([p for _, p in points], dtype=float)
    x = np.arange(len(y), dtype=float)
    return float(np.polyfit(x, y, 1)[0])

def _is_flat(values, tolerance_ratio=0.02):
    if len(values) < 2:
        return False
    avg = np.mean(values)
    if avg == 0:
        return False
    # Strict 2% max spread — removed 1.5x multiplier that caused Triple Top false positives
    return (max(values) - min(values)) / abs(avg) <= tolerance_ratio

def _detect_head_shoulders(highs, lows, tolerance=0.03, min_gap=10, min_span=25):
    if len(highs) < 3 or len(lows) < 1:
        return None
    h_sorted = sorted(highs, key=lambda x: x[0])
    for i in range(len(h_sorted) - 2):
        (li, lp), (hi, hp), (ri, rp) = h_sorted[i], h_sorted[i + 1], h_sorted[i + 2]
        if not (li < hi < ri):
            continue
        if not _pivot_indices_spaced([li, hi, ri], min_gap, min_span):
            continue

        # Temporal Symmetry: Tightened 0.5 → 0.30 — lopsided patterns were passing before
        left_dist = hi - li
        right_dist = ri - hi
        if abs(left_dist - right_dist) / max(left_dist, right_dist) > 0.30:
            continue

        shoulder_ref = (lp + rp) / 2
        if shoulder_ref == 0: continue

        # Price Symmetry
        shoulders_close = abs(lp - rp) / shoulder_ref <= tolerance
        if not shoulders_close: continue

        # Head Prominence: Raised to 6% — weak heads were being accepted at 5%
        head_prominent = (hp - lp) / hp >= 0.06 and (hp - rp) / hp >= 0.06
        if not head_prominent: continue

        # Ensure troughs exist on both sides of the head to form a proper neckline
        trough_left = [v for idx, v in lows if li < idx < hi]
        trough_right = [v for idx, v in lows if hi < idx < ri]

        if trough_left and trough_right:
            return "Head and Shoulders", [li, hi, ri]
    return None

def _detect_inverse_head_shoulders(highs, lows, tolerance=0.03, min_gap=10, min_span=25):
    if len(lows) < 3 or len(highs) < 1:
        return None
    l_sorted = sorted(lows, key=lambda x: x[0])
    for i in range(len(l_sorted) - 2):
        (li, lp), (hi, hp), (ri, rp) = l_sorted[i], l_sorted[i + 1], l_sorted[i + 2]
        if not (li < hi < ri):
            continue
        if not _pivot_indices_spaced([li, hi, ri], min_gap, min_span):
            continue

        # Temporal Symmetry: Tightened 0.5 → 0.30
        left_dist = hi - li
        right_dist = ri - hi
        if abs(left_dist - right_dist) / max(left_dist, right_dist) > 0.30:
            continue

        shoulder_ref = (lp + rp) / 2
        if shoulder_ref == 0: continue

        # Price Symmetry
        shoulders_close = abs(lp - rp) / shoulder_ref <= tolerance
        if not shoulders_close: continue

        # Head Prominence: Raised to 6%
        head_prominent = (lp - hp) / lp >= 0.06 and (rp - hp) / rp >= 0.06
        if not head_prominent: continue

        # Ensure peaks exist on both sides of the head
        peak_left = [v for idx, v in highs if li < idx < hi]
        peak_right = [v for idx, v in highs if hi < idx < ri]

        if peak_left and peak_right:
            return "Inverse Head and Shoulders", [li, hi, ri]
    return None

def _detect_double_top_bottom(highs, lows, last_close, tolerance=0.02, min_gap=12, min_span=20):
    if len(highs) >= 2:
        (i1, p1), (i2, p2) = sorted(highs, key=lambda x: x[0])[-2:]
        if i2 > i1 and p1 > 0 and p2 > 0 and (i2 - i1) >= min_gap and (i2 - i1) >= min_span:
            if abs(p1 - p2) / ((p1 + p2) / 2) <= tolerance:
                troughs_between = [v for idx, v in lows if i1 < idx < i2]
                # Confirmation: Price must have dropped at least 2% below the second peak
                if troughs_between and min(troughs_between) < min(p1, p2) * (1 - 0.03) and last_close < p2 * 0.98:
                    return "Double Top", [i1, i2]
    if len(lows) >= 2:
        (i1, p1), (i2, p2) = sorted(lows, key=lambda x: x[0])[-2:]
        if i2 > i1 and p1 > 0 and p2 > 0 and (i2 - i1) >= min_gap and (i2 - i1) >= min_span:
            if abs(p1 - p2) / ((p1 + p2) / 2) <= tolerance:
                peaks_between = [v for idx, v in highs if i1 < idx < i2]
                # Confirmation: Price must have bounced at least 2% above the second trough
                if peaks_between and max(peaks_between) > max(p1, p2) * (1 + 0.03) and last_close > p2 * 1.02:
                    return "Double Bottom", [i1, i2]
    return None

def _detect_triple_top_bottom(highs, lows, tolerance=0.025, min_gap=10, min_span=25):
    if len(highs) >= 3:
        last_highs = sorted(highs, key=lambda x: x[0])[-3:]
        i1, i2, i3 = last_highs[0][0], last_highs[1][0], last_highs[2][0]
        if _pivot_indices_spaced([i1, i2, i3], min_gap, min_span):
            prices = [p for _, p in last_highs]
            if _is_flat(prices, tolerance):
                return "Triple Top", [i1, i2, i3]
    if len(lows) >= 3:
        last_lows = sorted(lows, key=lambda x: x[0])[-3:]
        i1, i2, i3 = last_lows[0][0], last_lows[1][0], last_lows[2][0]
        if not _pivot_indices_spaced([i1, i2, i3], min_gap, min_span):
            return None
        prices = [p for _, p in last_lows]
        if _is_flat(prices, tolerance):
            return "Triple Bottom", [i1, i2, i3]
    return None

def _detect_triangle(highs, lows, min_gap=4):
    if len(highs) < 3 or len(lows) < 3:
        return None
    highs_recent = sorted(highs, key=lambda x: x[0])[-4:]
    lows_recent = sorted(lows, key=lambda x: x[0])[-4:]
    hi_idx = [x[0] for x in highs_recent]
    lo_idx = [x[0] for x in lows_recent]
    if not _chain_spaced(hi_idx, min_gap) or not _chain_spaced(lo_idx, min_gap):
        return None

    hs = np.array([v for _, v in highs_recent], dtype=float)
    ls = np.array([v for _, v in lows_recent], dtype=float)
    hi_x = np.arange(len(hs), dtype=float)
    lo_x = np.arange(len(ls), dtype=float)
    high_slope = np.polyfit(hi_x, hs, 1)[0]
    low_slope = np.polyfit(lo_x, ls, 1)[0]

    flat_thr = max(np.nanmean(hs), np.nanmean(ls)) * 0.0005
    if high_slope < -flat_thr and low_slope > flat_thr:
        return "Symmetrical Triangle", [hi_idx[-2], hi_idx[-1], lo_idx[-2], lo_idx[-1]]
    if abs(high_slope) <= flat_thr and low_slope > flat_thr:
        return "Ascending Triangle", [hi_idx[-2], hi_idx[-1], lo_idx[-2], lo_idx[-1]]
    if high_slope < -flat_thr and abs(low_slope) <= flat_thr:
        return "Descending Triangle", [hi_idx[-2], hi_idx[-1], lo_idx[-2], lo_idx[-1]]
    return None

def _detect_channel(recent, highs, lows, min_gap=2, min_span=12):
    """Detect Ascending/Descending channels requiring clear structural duration (default 12 weeks)."""
    if recent is None or recent.empty or len(highs) < 3 or len(lows) < 3:
        return None
    h_sorted = sorted(highs, key=lambda x: x[0])[-4:]
    l_sorted = sorted(lows, key=lambda x: x[0])[-4:]
    
    # Start Proximity: Lines must start nearly 10-15 days (3 weekly bars) apart
    if abs(h_sorted[0][0] - l_sorted[0][0]) > 3:
        return None

    # Duration check (avoiding small consolidations)
    start_idx = min(h_sorted[0][0], l_sorted[0][0])
    end_idx = max(h_sorted[-1][0], l_sorted[-1][0])
    if (end_idx - start_idx) < min_span:
        return None

    if not _chain_spaced([x[0] for x in h_sorted], min_gap) or not _chain_spaced([x[0] for x in l_sorted], min_gap):
        return None

    # Boundary Violation Check: No "huge distant price" closes above/below line
    c = recent['close'].values.astype(float)
    hx, hy = zip(*h_sorted)
    lx, ly = zip(*l_sorted)
    hm, hc = np.polyfit(hx, hy, 1)
    lm, lc = np.polyfit(lx, ly, 1)
    
    # Vectorized boundary violation check
    idx_arr = np.arange(start_idx, len(c))
    upper_bounds = (hm * idx_arr + hc) * 1.05
    lower_bounds = (lm * idx_arr + lc) * 0.95
    violations = np.sum((c[start_idx:] > upper_bounds) | (c[start_idx:] < lower_bounds))

    if violations > (len(c) - start_idx) * 0.15: # Allow 15% of bars to deviate
        return None

    hs = _line_slope(h_sorted)
    ls = _line_slope(l_sorted)
    mag = max(np.mean([p for _, p in h_sorted]), np.mean([p for _, p in l_sorted])) * 0.0004
    
    # Parallel check: Same direction and similar slope magnitude
    same_dir = (hs > 0 and ls > 0) or (hs < 0 and ls < 0)
    similar_mag = abs(hs - ls) <= max(abs(hs), abs(ls)) * 0.3 # Stricter parallel requirement

    if same_dir and similar_mag:
        # Return all pivot points to show clear touches and zig-zag behavior
        points = [x[0] for x in h_sorted] + [x[0] for x in l_sorted]
        if hs > mag: return "Ascending Channel", points
        if hs < -mag: return "Descending Channel", points
    return None

def _detect_wedge(recent, highs, lows, min_gap=2, min_span=12):
    """Detect Rising/Falling wedges requiring clear structural duration (default 12 weeks)."""
    if recent is None or recent.empty or len(highs) < 3 or len(lows) < 3:
        return None
    h_sorted = sorted(highs, key=lambda x: x[0])[-4:]
    l_sorted = sorted(lows, key=lambda x: x[0])[-4:]

    # Start Proximity: Lines must start nearly 10-15 days (3 weekly bars) apart
    if abs(h_sorted[0][0] - l_sorted[0][0]) > 3:
        return None

    # Duration check
    start_idx = min(h_sorted[0][0], l_sorted[0][0])
    end_idx = max(h_sorted[-1][0], l_sorted[-1][0])
    if (end_idx - start_idx) < min_span:
        return None

    if not _chain_spaced([x[0] for x in h_sorted], min_gap) or not _chain_spaced([x[0] for x in l_sorted], min_gap):
        return None

    # Boundary Violation Check
    c = recent['close'].values.astype(float)
    hx, hy = zip(*h_sorted)
    lx, ly = zip(*l_sorted)
    hm, hc = np.polyfit(hx, hy, 1)
    lm, lc = np.polyfit(lx, ly, 1)
    
    # Vectorized boundary violation check
    idx_arr = np.arange(start_idx, len(c))
    upper_bounds = (hm * idx_arr + hc) * 1.05
    lower_bounds = (lm * idx_arr + lc) * 0.95
    violations = np.sum((c[start_idx:] > upper_bounds) | (c[start_idx:] < lower_bounds))

    if violations > (len(c) - start_idx) * 0.15:
        return None

    hs = _line_slope(h_sorted)
    ls = _line_slope(l_sorted)
    h_vals = [p for _, p in h_sorted]
    l_vals = [p for _, p in l_sorted]
    width_start = h_vals[0] - l_vals[0]
    width_end   = h_vals[-1] - l_vals[-1]

    # Tightened: 0.75 → 0.60 — need meaningful convergence, not just slight taper
    converging = width_end < width_start * 0.60 if width_start > 0 else False

    # Return all pivot points defining the upper and lower boundaries
    points = [x[0] for x in h_sorted] + [x[0] for x in l_sorted]

    if converging and hs < 0 and ls < 0:
        # Falling Wedge: both lines down, lower line must fall faster (more negative)
        if ls < hs:
            return "Falling Wedge", points

    if converging and hs > 0 and ls > 0:
        # Rising Wedge: both lines up, upper line must rise slower (less positive)
        if hs < ls:
            return "Rising Wedge", points

    return None

def _detect_rectangle(highs, lows, min_gap=2):
    if len(highs) < 3 or len(lows) < 3:
        return None
    h_sorted = sorted(highs, key=lambda x: x[0])[-4:]
    l_sorted = sorted(lows, key=lambda x: x[0])[-4:]
    if not _chain_spaced([x[0] for x in h_sorted], min_gap) or not _chain_spaced([x[0] for x in l_sorted], min_gap):
        return None
    h_vals = [p for _, p in h_sorted]
    l_vals = [p for _, p in l_sorted]
    if _is_flat(h_vals, 0.02) and _is_flat(l_vals, 0.02):
        return "Rectangle Pattern", [h_sorted[-1][0], l_sorted[-1][0]]
    return None

def _detect_flag_pennant(recent, highs, lows, tri_result=None):
    if len(recent) < 30:
        return None
    close = recent['close'].values.astype(float)
    if close[0] == 0:
        return None
    pole_ret = (close[15] - close[0]) / close[0]
    pullback = close[29] - close[15]
    small_consolidation = abs(pullback) <= abs(close[15] - close[10]) * 1.2
    tri = tri_result[0] if tri_result else None
    if pole_ret >= 0.06 and small_consolidation:
        if tri in {"Symmetrical Triangle", "Ascending Triangle", "Descending Triangle"}:
            return "Pennant Pattern", [0, 15, 29]
        return "Flag Pattern (Bull Flag)", [0, 15, 29]
    if pole_ret <= -0.06 and small_consolidation:
        if tri in {"Symmetrical Triangle", "Ascending Triangle", "Descending Triangle"}:
            return "Pennant Pattern", [0, 15, 29]
        return "Flag Pattern (Bear Flag)", [0, 15, 29]
    return None

def _detect_cup_handle(recent, prefix=""):
    lookback = len(recent)
    if lookback < 60:
        return None
    c = recent['close'].values.astype(float)
    
    split1 = int(lookback * 0.45)
    split2 = int(lookback * 0.8)
    
    left_zone = c[:split1]
    right_zone = c[split1:split2]
    handle_zone = c[split2:]
    
    if len(handle_zone) < 5:
        return None
        
    left_peak_idx = np.argmax(left_zone)
    left_peak = left_zone[left_peak_idx]
    
    right_peak_idx = split1 + np.argmax(right_zone)
    right_peak = right_zone[np.argmax(right_zone)]
    
    # Cup Segment Roundness Enhancement (parabolic fit like Rounding Bottom)
    cup_data = c[left_peak_idx : right_peak_idx + 1]
    if len(cup_data) < 20:
        return None
        
    y_cup = cup_data
    x_cup = np.linspace(-1, 1, len(y_cup))
    a_cup, b_cup, _ = np.polyfit(x_cup, y_cup, 2)
    std_cup = np.std(y_cup)
    
    if std_cup == 0:
        return None

    # Symmetry check: Ensure the cup isn't too skewed
    # Curvature check: Ensure a smooth U-shape depth significant vs volatility
    is_u_shape = a_cup > 0
    is_symmetric = abs(b_cup) < std_cup * 0.25
    is_curvy = abs(a_cup) > std_cup * 1.5

    if not (is_u_shape and is_symmetric and is_curvy):
        return None

    cup_bottom_idx = left_peak_idx + np.argmin(cup_data)
    cup_bottom = c[cup_bottom_idx]
    handle_low_idx = split2 + np.argmin(handle_zone)
    
    if left_peak <= 0:
        return None
        
    depth_ok = (left_peak - cup_bottom) / left_peak >= 0.08
    rim_similarity = abs(left_peak - right_peak) / left_peak <= 0.06
    handle_pullback_ok = (right_peak - c[handle_low_idx]) / right_peak <= 0.15 if right_peak > 0 else False
    
    if depth_ok and rim_similarity and handle_pullback_ok:
        return f"{prefix}Cup and Handle", [left_peak_idx, cup_bottom_idx, right_peak_idx, handle_low_idx]
    return None

def _detect_rounding(recent, prefix=""):
    size = len(recent)
    if size < 35: 
        return None
    c = recent['close'].values.astype(float)
    y = c
    x = np.linspace(-1, 1, len(y))
    a, b, _ = np.polyfit(x, y, 2)
    std_y = np.std(y)
    if std_y == 0:
        return None

    # Symmetry check: Ensures the pattern isn't too skewed to one side (linear component 'b' is small)
    # Curvature check: Ensures 'enough roundness' (quadratic component 'a' is significant vs volatility)
    is_symmetric = abs(b) < std_y * 0.25
    is_curvy = abs(a) > std_y * 1.5  # Requires the parabolic 'depth' to be at least 1.5x standard deviation

    if a > 0 and is_symmetric and is_curvy:
        return f"{prefix}Rounding Bottom", [0, int(size*0.25), int(size*0.5), int(size*0.75), size-1]
    if a < 0 and is_symmetric and is_curvy:
        return f"{prefix}Rounding Top", [0, int(size*0.25), int(size*0.5), int(size*0.75), size-1]
    return None

def _detect_diamond(highs, lows, min_gap=1):
    if len(highs) < 6 or len(lows) < 6:
        return None
    h = sorted(highs, key=lambda x: x[0])[-6:]
    l = sorted(lows, key=lambda x: x[0])[-6:]
    if not _chain_spaced([x[0] for x in h], min_gap) or not _chain_spaced([x[0] for x in l], min_gap):
        return None
    h_vals = [p for _, p in h]
    l_vals = [p for _, p in l]
    half = 3
    w1 = (max(h_vals[:half]) - min(l_vals[:half]))
    w2 = (max(h_vals[half:]) - min(l_vals[half:]))
    expanding_then_contracting = w1 < (max(h_vals) - min(l_vals)) and w2 < (max(h_vals) - min(l_vals))
    if not expanding_then_contracting:
        return None
    if h_vals[-1] < h_vals[0]:
        return "Diamond Top", [h[0][0], h[2][0], h[-1][0], l[0][0], l[2][0], l[-1][0]]
    if l_vals[-1] > l_vals[0]:
        return "Diamond Bottom", [h[0][0], h[2][0], h[-1][0], l[0][0], l[2][0], l[-1][0]]
    return None

def _detect_broadening(highs, lows, min_gap=2):
    if len(highs) < 4 or len(lows) < 4:
        return None
    h_sorted = sorted(highs, key=lambda x: x[0])[-4:]
    l_sorted = sorted(lows, key=lambda x: x[0])[-4:]
    if not _chain_spaced([x[0] for x in h_sorted], min_gap) or not _chain_spaced([x[0] for x in l_sorted], min_gap):
        return None
    h_vals = [p for _, p in h_sorted]
    l_vals = [p for _, p in l_sorted]
    width_start = h_vals[0] - l_vals[0]
    width_end = h_vals[-1] - l_vals[-1]
    if width_start > 0 and width_end / width_start >= 1.2:
        return "Broadening Formation", [h_sorted[0][0], h_sorted[-1][0], l_sorted[0][0], l_sorted[-1][0]]
    return None

def _pattern_base_confidence(pattern_name):
    confidence_map = {
        "Head and Shoulders": 84,
        "Inverse Head and Shoulders": 84,
        "Double Top": 78,
        "Double Bottom": 78,
        "Triple Top": 82,
        "Triple Bottom": 82,
        "Ascending Triangle": 80,
        "Descending Triangle": 80,
        "Symmetrical Triangle": 74,
        "Flag Pattern (Bull Flag)": 76,
        "Flag Pattern (Bear Flag)": 76,
        "Pennant Pattern": 73,
        "Falling Wedge": 77,
        "Rising Wedge": 77,
        "Cup and Handle": 79,
        "Rectangle Pattern": 70,
        "Rounding Bottom": 71,
        "Rounding Top": 71,
        "Diamond Top": 72,
        "Diamond Bottom": 72,
        "Broadening Formation": 68,
        "Ascending Channel": 69,
        "Descending Channel": 69,
    }
    return confidence_map.get(pattern_name, 65)

PATTERN_SENTIMENT = {
    "Head and Shoulders": "Bearish",
    "Inverse Head and Shoulders": "Bullish",
    "Double Top": "Bearish",
    "Double Bottom": "Bullish",
    "Triple Top": "Bearish",
    "Triple Bottom": "Bullish",
    "Ascending Triangle": "Bullish",
    "Descending Triangle": "Bearish",
    "Symmetrical Triangle": "Neutral",
    "Flag Pattern (Bull Flag)": "Bullish",
    "Flag Pattern (Bear Flag)": "Bearish",
    "Pennant Pattern": "Neutral",
    "Falling Wedge": "Bullish",
    "Rising Wedge": "Bearish",
    "Cup and Handle": "Bullish",
    "Rectangle Pattern": "Neutral",
    "Rounding Bottom": "Bullish",
    "Rounding Top": "Bearish",
    "Diamond Top": "Bearish",
    "Diamond Bottom": "Bullish",
    "Broadening Formation": "Neutral",
    "Ascending Channel": "Bullish",
    "Descending Channel": "Bearish",
}

def _fmt_anchor(recent, idx, label):
    if idx is None or idx < 0 or idx >= len(recent):
        return None
    dt = pd.to_datetime(recent.iloc[idx]['datetime']).strftime('%d-%m-%Y')
    px = round(float(recent.iloc[idx]['close']), 2)
    return f"{label}:{dt}@{px}"

def _build_pattern_trace(main_pattern, recent, points_idx):
    points = []
    
    labels = []
    if "Head and Shoulders" in main_pattern: labels = ["LS", "H", "RS"]
    elif "Double" in main_pattern: labels = ["P1", "P2"]
    elif "Triple" in main_pattern: labels = ["P1", "P2", "P3"]
    elif "Cup and Handle" in main_pattern: labels = ["RimL", "Btm", "RimR", "Hdl"]
    elif "Rounding" in main_pattern: labels = ["Start", "Q1", "Mid", "Q3", "End"]
    elif "Diamond" in main_pattern: labels = ["H1", "H2", "H3", "L1", "L2", "L3"]
    elif "Channel" in main_pattern or "Wedge" in main_pattern:
        mid = len(points_idx) // 2
        labels = [f"UL{i+1}" for i in range(mid)] + [f"LL{i+1}" for i in range(len(points_idx) - mid)]
    elif "Triangle" in main_pattern or "Broadening" in main_pattern:
        labels = ["H1", "H2", "L1", "L2"]
    elif "Flag" in main_pattern or "Pennant" in main_pattern: labels = ["PoleS", "PoleE", "Consol"]
    else:
        labels = [f"Pt{i+1}" for i in range(len(points_idx))]

    for i, idx in enumerate(points_idx):
        lbl = labels[i] if i < len(labels) else f"Pt{i+1}"
        p = _fmt_anchor(recent, idx, lbl)
        if p: points.append(p)

    if not points_idx:
        return "", "", ""

    start_idx = max(0, min(points_idx))
    end_idx = min(len(recent) - 1, max(points_idx))
    start_date = pd.to_datetime(recent.iloc[start_idx]['datetime']).strftime('%d-%m-%Y')
    end_date = pd.to_datetime(recent.iloc[end_idx]['datetime']).strftime('%d-%m-%Y')
    return " ; ".join(points), start_date, end_date

def detect_price_patterns(data, max_age_days=None):
    """
    Detect major chart patterns. Only the last max_age_days of daily data is used (no older fallback).
    Structural reversals use weekly-resampled pivots so swings are not micro noise on daily bars.
    Short patterns (cup, flag) stay on daily with stricter pivot order.
    """
    if max_age_days is None:
        max_age_days = CONFIG.get('PATTERN_MAX_AGE_DAYS', 124)

    empty = {
        "main_pattern": "Insufficient Data",
        "main_confidence": 0,
        "misc_patterns": "",
        "all_patterns": "Insufficient Data",
        "pattern_points": "",
        "pattern_start": "",
        "pattern_end": "",
    }

    if data is None or data.empty:
        return empty

    analysis_date = pd.to_datetime(data['datetime'].max())
    cutoff_date = analysis_date - pd.Timedelta(days=max_age_days)
    window = data[pd.to_datetime(data['datetime']) >= cutoff_date].copy()
    min_bars = CONFIG.get('PATTERN_MIN_BARS_IN_WINDOW', 70)
    if len(window) < min_bars:
        return empty

    w_gap = CONFIG.get('PATTERN_WEEKLY_MIN_GAP', 2)
    w_double = CONFIG.get('PATTERN_WEEKLY_MIN_DOUBLE_SPAN', 3)
    w_triple = CONFIG.get('PATTERN_WEEKLY_MIN_TRIPLE_SPAN', 5)
    w_hs = CONFIG.get('PATTERN_WEEKLY_MIN_HS_SPAN', 4)
    w_order = CONFIG.get('PATTERN_WEEKLY_PIVOT_ORDER', 2)

    # Significantly increased daily order for higher accuracy.
    # A pivot must now be the max/min of a 21-day window (10 left, 10 right).
    o_min = 10 
    o_max = 15
    daily_order = max(o_min, min(o_max, max(5, len(window) // 6)))

    recent_d, hd, ld = _pivot_points(window, order=daily_order, lookback=len(window))

    weekly = _resample_to_weekly(window)
    recent_w, hw, lw = None, [], []
    if len(weekly) >= 6:
        recent_w, hw, lw = _pivot_points(weekly, order=w_order, lookback=len(weekly))

    patterns_found = [] 
    weekly_structure_names = {
        "Head and Shoulders", "Inverse Head and Shoulders", "Double Top", "Double Bottom",
        "Triple Top", "Triple Bottom", "Symmetrical Triangle", "Ascending Triangle", "Descending Triangle",
        "Falling Wedge", "Rising Wedge", "Rectangle Pattern", "Ascending Channel", "Descending Channel",
        "Diamond Top", "Diamond Bottom", "Broadening Formation",
    }

    # Weekly (higher effective timeframe) — major structure
    if recent_w is not None and len(recent_w) > 0 and (len(hw) >= 2 or len(lw) >= 2):
        for patt_res in [
            _detect_head_shoulders(hw, lw, tolerance=0.03, min_gap=w_gap, min_span=w_hs),
            _detect_inverse_head_shoulders(hw, lw, tolerance=0.03, min_gap=w_gap, min_span=w_hs),
            _detect_double_top_bottom(hw, lw, float(window['close'].iloc[-1]), tolerance=0.022, min_gap=w_gap, min_span=w_double),
            _detect_triple_top_bottom(hw, lw, tolerance=0.022, min_gap=w_gap, min_span=w_triple),
            _detect_diamond(hw, lw, min_gap=1),
            _detect_wedge(recent_w, hw, lw, min_gap=w_gap, min_span=12),
            _detect_rectangle(hw, lw, min_gap=w_gap),
            _detect_broadening(hw, lw, min_gap=w_gap),
            _detect_channel(recent_w, hw, lw, min_gap=w_gap, min_span=12),
        ]:
            if patt_res: patterns_found.append((patt_res[0], patt_res[1], recent_w))
        
        if tri_res := _detect_triangle(hw, lw, min_gap=w_gap):
            patterns_found.append((tri_res[0], tri_res[1], recent_w))

    # Long-term (Bigger Patterns) — Check last 1 year if available
    full_year_win = data.tail(252).copy().reset_index(drop=True)
    if len(full_year_win) >= 150:
        if r_res := _detect_rounding(full_year_win, prefix="Long-term "):
            patterns_found.append((r_res[0], r_res[1], full_year_win))
        if c_res := _detect_cup_handle(full_year_win, prefix="Long-term "):
            patterns_found.append((c_res[0], c_res[1], full_year_win))

    # Daily — structural shapes like Cups and Rounding Bottoms require precise windows to fit mathematically.
    # We iterate through multiple lookbacks to catch patterns of varying speeds (e.g. OLAELEC's ~60 day base).
    for lb in [40, 50, 60, 75, 90, 110]:
        if len(window) >= lb:
            slice_df = window.tail(lb).reset_index(drop=True)
            if r_res := _detect_rounding(slice_df):
                patterns_found.append((r_res[0], r_res[1], slice_df))
            if c_res := _detect_cup_handle(slice_df):
                patterns_found.append((c_res[0], c_res[1], slice_df))

    # Flags / pennants: daily pivots with wide order + triangle check on same pivots
    if len(window) >= 30 and len(hd) >= 2 and len(ld) >= 2:
        tri_d_res = _detect_triangle(hd, ld, min_gap=2)
        if fp_res := _detect_flag_pennant(window.reset_index(drop=True), hd, ld, tri_result=tri_d_res):
            patterns_found.append((fp_res[0], fp_res[1], window.reset_index(drop=True)))

    if not patterns_found:
        return {
            "main_pattern": "No Clear Pattern",
            "main_confidence": 0,
            "misc_patterns": "",
            "all_patterns": "No Clear Pattern",
            "pattern_points": "",
            "pattern_start": "",
            "pattern_end": "",
        }

    scored_patterns = []
    for name, points, ctx_df in patterns_found:
        base = _pattern_base_confidence(name.replace("Long-term ", ""))
        scored_patterns.append({"name": name, "points": points, "df": ctx_df, "score": base})
    
    scored_patterns.sort(key=lambda x: x['score'], reverse=True)
    unique_scored = []
    seen = set()
    for p in scored_patterns:
        if p['name'] not in seen:
            unique_scored.append(p)
            seen.add(p['name'])

    latest = window.iloc[-1]
    rel_vol = (latest['volume'] / window['volume'].rolling(window=20, min_periods=1).mean().iloc[-1]
               if len(window) >= 5 and window['volume'].rolling(window=20, min_periods=1).mean().iloc[-1] > 0 else 1.0)
    vol_boost = 4 if rel_vol >= 1.5 else 0
    breakout_boost = 3 if ('BB_BREAKOUT_UP' in latest and bool(latest['BB_BREAKOUT_UP'])) or ('BB_BREAKOUT_DOWN' in latest and bool(latest['BB_BREAKOUT_DOWN'])) else 0

    # Calculate Long-term Trend Context (200 SMA)
    trend = "Neutral"
    if len(data) >= 200:
        sma200 = data['close'].rolling(window=200).mean()
        curr_sma = sma200.iloc[-1]
        prev_sma = sma200.iloc[-20] # 1 month ago
        curr_price = data['close'].iloc[-1]
        if curr_price > curr_sma and curr_sma > prev_sma:
            trend = "Uptrend"
        elif curr_price < curr_sma and curr_sma < prev_sma:
            trend = "Downtrend"

    for p in unique_scored:
        base_name = p['name'].replace("Long-term ", "")
        sentiment = PATTERN_SENTIMENT.get(base_name, "Neutral")
        trend_adj = 0
        if trend == "Uptrend":
            trend_adj = 8 if sentiment == "Bearish" else 4 if sentiment == "Bullish" else 0
        elif trend == "Downtrend":
            trend_adj = 8 if sentiment == "Bullish" else -12 if sentiment == "Bearish" else 0
        
        p['final_score'] = int(max(1, min(99, round(p['score'] + vol_boost + breakout_boost + trend_adj))))

    unique_scored.sort(key=lambda x: x['final_score'], reverse=True)

    main = unique_scored[0]
    points_text, start_date, end_date = _build_pattern_trace(main['name'], main['df'], main['points'])
    
    misc = [f"{p['name']}({p['final_score']})" for p in unique_scored[1:]]
    all_patterns = " | ".join([f"{p['name']}({p['final_score']})" for p in unique_scored])
    
    return {
        "main_pattern": main['name'],
        "main_confidence": main['final_score'],
        "misc_patterns": " | ".join(misc),
        "all_patterns": all_patterns,
        "pattern_points": points_text,
        "pattern_start": start_date,
        "pattern_end": end_date,
    }

def detect_price_pattern(data):
    # Backward-compatible helper.
    return detect_price_patterns(data).get("all_patterns", "No Clear Pattern")

def analyze_symbol(symbol, logger, enable_chart_patterns=True):
    global df
    data = df[df['symbols'] == symbol].sort_values('datetime')
    if data.empty:
        logger.warning(f"No data for symbol {symbol}")
        return None
    if len(data) < 20:
        logger.warning(f"Skipping analysis for {symbol}: insufficient data ({len(data)} rows)")
        return None
    try:
        data['Change'] = (data['close'] - data['open']) / data['open'] * 100
        data = add_indicators(data)
        data['BB_BANDWIDTH'] = (data['BB_UPPER'] - data['BB_LOWER']) / data['BB_MIDDLE']
        data['BB_SQUEEZE'] = data['BB_BANDWIDTH'].rolling(window=301, min_periods=1).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100 <= 5, raw=True).astype(bool)
        data['BB_BREAKOUT_UP'] = (data['close'] > data['BB_UPPER']) & (data['close'].shift(1) <= data['BB_UPPER'].shift(1))
        data['BB_BREAKOUT_DOWN'] = (data['close'] < data['BB_LOWER']) & (data['close'].shift(1) >= data['BB_LOWER'].shift(1))
        data['52W_High'] = data['high'].rolling(window=252, min_periods=1).max()
        data['52W_Low'] = data['low'].rolling(window=252, min_periods=1).min()
        data['SWING_HIGH'] = 0
        data['SWING_LOW'] = 0
        high_idx = argrelextrema(data['close'].values, np.greater_equal, order=252)[0]
        low_idx = argrelextrema(data['close'].values, np.less_equal, order=252)[0]
        data.iloc[high_idx, data.columns.get_loc('SWING_HIGH')] = 1
        data.iloc[low_idx, data.columns.get_loc('SWING_LOW')] = 1

        # Medium-term swings (order=60 anchors)
        data['MT_SWING_HIGH'] = 0
        data['MT_SWING_LOW'] = 0
        mt_high_idx = argrelextrema(data['close'].values, np.greater_equal, order=60)[0]
        mt_low_idx = argrelextrema(data['close'].values, np.less_equal, order=60)[0]
        data.iloc[mt_high_idx, data.columns.get_loc('MT_SWING_HIGH')] = 1
        data.iloc[mt_low_idx, data.columns.get_loc('MT_SWING_LOW')] = 1

        data['AVG_VOLUME_20'] = data['volume'].rolling(window=20, min_periods=1).mean()
        data['RELATIVE_VOLUME'] = data['volume'] / data['AVG_VOLUME_20']
        data['VOLUME_SPIKE'] = data['RELATIVE_VOLUME'] > 2
        data['ACTIVITY_SCORE'] = data['close'] * data['volume'] / 1e7

        # --- WEEKLY ANALYSIS AND WEINSTEIN STAGE ---
        weekly_df = data.resample('W-FRI', on='datetime').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
        }).dropna()
        
        try:
            weekly_df.ta.rsi(length=14, append=True)
            w_rsi = weekly_df['RSI_14'].iloc[-1] if len(weekly_df) >= 14 else np.nan
        except Exception:
            w_rsi = np.nan
        
        w_sma30_s = weekly_df['close'].rolling(window=30).mean()
        w_sma30 = w_sma30_s.iloc[-1] if len(weekly_df) >= 30 else np.nan

        def calculate_weinstein_stage(df_p, sma_col, rsi_col):
            if len(df_p) < 35: return "Insufficient Data"
            curr, prev = df_p.iloc[-1], df_p.iloc[-4]
            c, s, sp, r = curr['close'], curr[sma_col], prev[sma_col], curr[rsi_col]
            if pd.isna(s) or pd.isna(sp) or pd.isna(r): return "Insufficient Data"
            slope = (s - sp) / sp * 100
            if c > s and slope > 0 and r >= 50: return "Stage 2 (Uptrend)"
            if c < s and slope < 0 and r < 50: return "Stage 4 (Downtrend)"
            if abs(c - s) / s <= 0.03 and abs(slope) < 0.5 and 40 <= r <= 60: return "Stage 1 (Base)"
            if c <= s * 1.03 and slope < 0 and 45 <= r <= 65: return "Stage 3 (Top)"
            return "Stage 1 (Base)"

        # Daily Weinstein Stage (stge)
        data['SMA_30'] = data['close'].rolling(window=30).mean()
        swing_stage = calculate_weinstein_stage(data, 'SMA_30', 'RSI')

        # Weekly Weinstein Stage (stge_w)
        try:
            w_df_stage = weekly_df.copy()
            w_df_stage['SMA_30'] = w_sma30_s
            if data['datetime'].max().weekday() != 4: # Drop incomplete week if not Friday
                w_df_stage = w_df_stage.iloc[:-1]
            weekly_stage = calculate_weinstein_stage(w_df_stage, 'SMA_30', 'RSI_14')
        except:
            weekly_stage = "Insufficient Data"

        latest = data.iloc[-1]
        close = latest['close']
        swing_high = data[data['SWING_HIGH'] == 1]['close'].iloc[-1] if not data[data['SWING_HIGH'] == 1].empty else np.nan
        swing_low = data[data['SWING_LOW'] == 1]['close'].iloc[-1] if not data[data['SWING_LOW'] == 1].empty else np.nan

        # Better Zone Logic: Percentile-based (adapts to stock volatility)
        if pd.isna(swing_high) or pd.isna(swing_low) or swing_high == swing_low:
            zone = "NO DATA"
            midpoint = np.nan
        else:
            midpoint = (swing_high + swing_low) / 2
            rel_pos = (close - swing_low) / (swing_high - swing_low)
            if 0.45 <= rel_pos <= 0.55: zone = "Equilibrium"
            elif rel_pos <= 0.25:      zone = "Discount"
            elif rel_pos >= 0.75:      zone = "Premium"
            elif rel_pos < 0.50:       zone = "Near Discount"
            else:                      zone = "Near Premium"
        
        # Medium-term Zone Logic (order=60 anchors)
        mt_swing_high = data[data['MT_SWING_HIGH'] == 1]['close'].iloc[-1] if not data[data['MT_SWING_HIGH'] == 1].empty else np.nan
        mt_swing_low = data[data['MT_SWING_LOW'] == 1]['close'].iloc[-1] if not data[data['MT_SWING_LOW'] == 1].empty else np.nan

        if pd.isna(mt_swing_high) or pd.isna(mt_swing_low) or mt_swing_high == mt_swing_low:
            mt_zone = "NO DATA"
        else:
            mt_rel_pos = (close - mt_swing_low) / (mt_swing_high - mt_swing_low)
            if 0.45 <= mt_rel_pos <= 0.55: mt_zone = "Equilibrium"
            elif mt_rel_pos <= 0.25:      mt_zone = "Discount"
            elif mt_rel_pos >= 0.75:      mt_zone = "Premium"
            elif mt_rel_pos < 0.50:       mt_zone = "Near Discount"
            else:                      mt_zone = "Near Premium"
        
        above_sma_200 = close > latest['SMA_200'] if pd.notna(latest['SMA_200']) else False
        above_sma_50 = close > latest['SMA_50'] if pd.notna(latest['SMA_50']) else False
        above_sma_20 = close > latest['SMA_20'] if pd.notna(latest['SMA_20']) else False

        bb_position = ((close - latest['BB_LOWER']) / (latest['BB_UPPER'] - latest['BB_LOWER'])
                       if pd.notna(latest['BB_UPPER']) and pd.notna(latest['BB_LOWER']) else 0.5)
        per = round((latest['52W_High'] - close) / latest['52W_High'] * 100, 2) if pd.notna(latest['52W_High']) else np.nan
        vol_trend = "Increasing" if latest['volume'] > data['volume'].rolling(window=10).mean().iloc[-1] else "Decreasing"
        trend = ("Uptrend" if latest['ADX'] > 25 and (latest['SMA_50'] - data['SMA_50'].iloc[-5]) / 5 > 0 else
                 "Downtrend" if latest['ADX'] > 25 else "Sideways")
        trend_strength = "Strong" if latest['ADX'] > 25 else "Moderate" if latest['ADX'] > 15 else "Weak"
        volatility = data['close'].pct_change().rolling(window=21).std().iloc[-1] * np.sqrt(252) * 100 if len(data) >= 21 else np.nan
        if enable_chart_patterns:
            pattern_info = detect_price_patterns(data)
            pattern = pattern_info.get('all_patterns', 'No Clear Pattern')
            main_pattern = pattern_info.get('main_pattern', 'No Clear Pattern')
        else:
            pattern_info = {}
            pattern = 'Disabled'
            main_pattern = 'Disabled'

        misc_patterns = pattern_info.get('misc_patterns', '')
        pattern_conf = pattern_info.get('main_confidence', 0)
        pattern_points = pattern_info.get('pattern_points', '')
        pattern_start = pattern_info.get('pattern_start', '')
        pattern_end = pattern_info.get('pattern_end', '')

        row = {
            'datetime': latest['datetime'], 'symbols': symbol, 'close': round(close, 2), 'volume': latest['volume'],
            'Dl Per': round(latest['delivery_perc'], 2) if 'delivery_perc' in latest else np.nan,
            'CHANGE': round(latest['Change'], 2), 'SMA_200': round(latest['SMA_200'], 2),
            'ZONE': zone, 'MT_ZONE': mt_zone, 'RSI': round(latest['RSI'], 2), 'delta': per,
            '>200': above_sma_200, '>50': above_sma_50, '>20': above_sma_20,
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
            'open': round(latest['open'], 2), 'TREND': trend, 'TREND_STRENGTH': trend_strength,
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
            'PATTERN_CONFIDENCE': pattern_conf, 'PATTERN_POINTS': pattern_points,
            'PATTERN_START': pattern_start, 'PATTERN_END': pattern_end
        }
        return pd.DataFrame([row])
    
    except Exception as e:
        if logger:
            logger.debug(f"Error analyzing symbol {symbol}: {e}")
        return None

def perform_technical_analysis(df_input, sector_df, logger, enable_chart_patterns=True):
    global df
    df = df_input
    if df.empty:
        logger.warning("No data for analysis")
        return pd.DataFrame()
    
    try:
        all_symbols = df['symbols'].unique()
        valid_symbols = [s for s in all_symbols if len(df[df['symbols'] == s]) >= 20]
        logger.info(f"Found {len(valid_symbols)} symbols with sufficient data (>= 20 rows) out of {len(all_symbols)} loaded symbols")
        print(f"Analyzing {len(valid_symbols)} symbols out of {len(all_symbols)} loaded symbols.")
        
        invalid_symbols = [s for s in all_symbols if len(df[df['symbols'] == s]) < 20]
        for symbol in invalid_symbols:
            logger.warning(f"Symbol {symbol} has insufficient data: {len(df[df['symbols'] == symbol])} rows")
        
        results = []
        analysis_errors = []
        for symbol in tqdm(valid_symbols, desc="Analyzing data"):
            result = analyze_symbol(symbol, logger, enable_chart_patterns=enable_chart_patterns)
            if result is not None:
                results.append(result)
            else:
                analysis_errors.append(symbol)

        if analysis_errors:
            summary = ', '.join(analysis_errors[:20]) + ('...' if len(analysis_errors) > 20 else '')
            logger.warning(f"Completed analysis with {len(analysis_errors)} symbols skipped due to insufficient data or indicator issues: {summary}")
            print(f"Completed analysis with {len(analysis_errors)} symbols skipped due to insufficient data or indicator issues: {summary}")

        if not results:
            logger.warning("No analysis results generated")
            return pd.DataFrame()
        
        analysis_df = pd.concat(results, ignore_index=True)
        
        analysis_df['VOLUME_RANK'] = analysis_df['volume'].rank(ascending=False, method='min')
        analysis_df['ACTIVITY_RANK'] = analysis_df['ACTIVITY_SCORE'].rank(ascending=False, method='min')
        analysis_df['RELATIVE_VOLUME_RANK'] = analysis_df['RELATIVE_VOLUME'].rank(ascending=False, method='min')
        analysis_df = analysis_df.sort_values(['ACTIVITY_SCORE', 'RELATIVE_VOLUME'], ascending=[False, False])
        
        # Ensure SECTOR column exists before mapping to 'sect'
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
        
        col_map = {
            'datetime': 'date', 'symbols': 'symb', 'close': 'clos', 'volume': 'volu',
            'Dl Per': 'DlPer', 'RELATIVE_VOLUME': 'rvol', 'VOLUME_SPIKE': 'vspk', 'ACTIVITY_SCORE': 'ascr',
            'ACTIVITY_RANK': 'arnk', 'CHANGE': 'chan', '>200': 'g200', 'ZONE': 'zone', 
            'STAGE_W': 'stge_w', 'RSI': 'rsi',
            'delta': 'delt', 'OBV': 'obv', 'BB_BREAKOUT_UP': 'bbup', 'VOLUME_TREND': 'vtrd',
            'BB_BANDWIDTH': 'bbbw', '>50': 'g050', '>20': 'g020', 'ADX': 'adx',
            'open': 'open', 'BB_BREAKOUT_DOWN': 'bbdn', 'BB_SQUEEZE': 'bbsq', 'S_HIGH': 'shgh', 'S_LOW': 'slw',
            'high': 'high', 'low': 'low', 'EQB': 'eqb', 'SMA20': 's020', 'SMA50': 's050', 'SMA100': 's100',
            'SMA_200': 's200', '52HIGH': 'h52h', '52LOW': 'l52l', 'VOLUME_RANK': 'vrnk', 'RELATIVE_VOLUME_RANK': 'rrnk',
            'TREND': 'tren', 'TREND_STRENGTH': 'tstr', 'VOLATILITY_%': 'vola', 
            'W_RSI': 'wrsi', 'W_SMA30': 'ws30', 'STAGE': 'stge',
            'PATTERN': 'patt', 'MAIN_PATTERN': 'mpat', 'MISC_PATTERNS': 'xpat', 'PATTERN_CONFIDENCE': 'pcon',
            'PATTERN_POINTS': 'ppnt', 'PATTERN_START': 'psta', 'PATTERN_END': 'pend',
            'SECTOR': 'sect'
        }
        analysis_df.rename(columns={k: v for k, v in col_map.items() if k in analysis_df.columns}, inplace=True)
        
        desired_order = [
            'date','symb','clos','stge','stge_w','wrsi','ws30','volu','DlPer','rvol','vspk','ascr','arnk','chan','g200','zone','rsi','delt','bbup','vtrd','bbbw','bbsq',
            'g050','g020','adx','CMF_20','SUPERT_7_3.0','SUPERTd_7_3.0','STOCHk_14_3_3','STOCHd_14_3_3','EMA_21','SQZ_ON','SQZ_OFF','SQZ_NO','WILLR_14','EFI_13','RSI_2','open','bbdn','shgh','slw','high','low','eqb','s020','s050','s100','s200','h52h','l52l','vrnk','rrnk',
            'tren','tstr','vola','mpat','pcon','psta','pend','ppnt','xpat','patt','obv','sect'
        ]
        final_cols = [c for c in desired_order if c in analysis_df.columns]
        extra_cols = [c for c in analysis_df.columns if c not in final_cols]
        analysis_df = analysis_df[final_cols + extra_cols]
        
        logger.info(f"Generated analysis for {len(analysis_df)} symbols")
        return analysis_df
    
    except Exception as e:
        logger.error(f"Error in perform_technical_analysis: {e}")
        return pd.DataFrame()

def get_input(prompt):
    val = input(prompt)
    if val.strip().lower() == 'q':
        print("Operation cancelled by user.")
        exit(0)
    return val

def main():
    logger = setup_logging(verbose=True)
    try:
        symbols, sector_df, _ = load_symbols(CONFIG['SYMBOLS_FILE'], logger)
        if not symbols:
            logger.error("No symbols loaded")
            return

        print("Choose the operation mode:")
        print("1. Fetch")
        print("2. Update")
        print("3. Adjust")
        print("4. Analyze")

        choice = get_input("Enter your choice (1-4 or Q to quit): ").strip()

        raw_data = pd.DataFrame()
        if choice == '1':  # Fetch
            print("Choose date range mode:")
            print("1. Custom start and end dates")
            print("2. End date and years back")
            date_choice = input("Enter choice (1 or 2): ").strip()
            
            if date_choice == '1':
                start_date = input("Start date (DD-MM-YYYY): ").strip()
                end_date = input("End date (DD-MM-YYYY): ").strip()
                try:
                    start_date = datetime.strptime(start_date, '%d-%m-%Y')
                    end_date = datetime.strptime(end_date, '%d-%m-%Y')
                    if start_date > end_date:
                        logger.error("Start date cannot be after end date")
                        return
                    raw_data = fetch_data(symbols, start_date, end_date, logger)
                except ValueError as e:
                    logger.error(f"Invalid date format: {e}")
                    return
            
            elif date_choice == '2':
                end_date = input("End date (DD-MM-YYYY): ").strip()
                years_back = input("Years back (e.g., 1.5): ").strip()
                try:
                    end_date = datetime.strptime(end_date, '%d-%m-%Y')
                    years_back = float(years_back)
                    days_back = int(years_back * 365)
                    start_date = end_date - timedelta(days=days_back)
                    raw_data = fetch_data(symbols, start_date, end_date, logger)
                except ValueError as e:
                    logger.error(f"Invalid input for date or years: {e}")
                    return
            else:
                logger.error("Invalid date choice")
                return

        elif choice == '2':  # Update
            if not os.path.exists(CONFIG['RAW_DATA_FILE']):
                logger.error(f"No {CONFIG['RAW_DATA_FILE']} found")
                return
            try:
                existing = standardize_data(pd.read_csv(CONFIG['RAW_DATA_FILE']), CONFIG['RAW_DATA_FILE'], logger)
                if existing.empty:
                    logger.error(f"No valid data in {CONFIG['RAW_DATA_FILE']}")
                    return
                tasks = []
                to_date = datetime.now()
                logger.info(f"Checking for updates up to {to_date.strftime('%d-%m-%Y')}")
                min_from_date = to_date
                for symbol in symbols:
                    last_date = existing[existing['symbols'] == symbol]['datetime'].max()
                    from_date = last_date + timedelta(days=1) if pd.notna(last_date) else to_date - timedelta(days=CONFIG['DEFAULT_LOOKBACK_DAYS'])
                    if from_date.date() <= to_date.date():
                        tasks.append(symbol)
                        if from_date < min_from_date:
                            min_from_date = from_date
                        logger.info(f"Symbol {symbol} needs update from {from_date.strftime('%d-%m-%Y')}")
                if tasks:
                    logger.info(f"Fetching new data for {len(tasks)} symbols")
                    new_data = fetch_data(tasks, min_from_date, to_date, logger)
                    if not new_data.empty:
                        new_data = new_data.dropna(subset=['open', 'high', 'low', 'close', 'volume'])
                        if new_data.empty:
                            logger.warning("No new data with valid OHLCV values after filtering")
                            return
                        raw_data = pd.concat([existing, new_data]).drop_duplicates(['symbols', 'datetime'], keep='last')
                        logger.info(f"Combined {len(raw_data)} records after update")
                    else:
                        logger.warning("No new data fetched")
                        return
                else:
                    logger.info("No new data to fetch")
                    return
            except Exception as e:
                logger.error(f"Error updating data: {e}")
                return

        elif choice == '3':  # Adjust
            if not os.path.exists(CONFIG['RAW_DATA_FILE']):
                logger.error(f"No {CONFIG['RAW_DATA_FILE']} found")
                return
            try:
                raw_data = standardize_data(pd.read_csv(CONFIG['RAW_DATA_FILE']), CONFIG['RAW_DATA_FILE'], logger)
                if raw_data.empty:
                    logger.error(f"No valid data in {CONFIG['RAW_DATA_FILE']}")
                    return
            except Exception as e:
                logger.error(f"Error reading raw data: {e}")
                return

        elif choice == '4':  # Analyze
            if not os.path.exists(CONFIG['ADJUSTED_DATA_FILE']):
                logger.error(f"No {CONFIG['ADJUSTED_DATA_FILE']} found")
                return
            try:
                adjusted_data = standardize_data(pd.read_csv(CONFIG['ADJUSTED_DATA_FILE']), CONFIG['ADJUSTED_DATA_FILE'], logger)
                if adjusted_data.empty:
                    logger.error(f"No valid data in {CONFIG['ADJUSTED_DATA_FILE']}")
                    return

                date_input = get_input("press Enter to analyze latest data or date/dates (DD-MM-YYYY to DD-MM-YYYY) ").strip()
                if date_input and 'to' in date_input:
                    try:
                        start_str, end_str = [d.strip() for d in date_input.split('to')]
                        start_date = datetime.strptime(start_str, '%d-%m-%Y')
                        end_date = datetime.strptime(end_str, '%d-%m-%Y')
                        chart_choice = get_input("Enable Chart Pattern analysis? (y/N): ").strip().lower()
                        enable_chart_patterns = chart_choice in ['y', 'yes']
                        all_dates = pd.date_range(start_date, end_date, freq='D')
                        for d in all_dates:
                            mask = adjusted_data['datetime'] <= d
                            data_till_date = adjusted_data[mask]
                            # Skip if no data for this date
                            if data_till_date.empty or not (data_till_date['datetime'] == d).any():
                                logger.info(f"Skipping {d.strftime('%d-%m-%Y')}: no data for this date")
                                continue
                            analysis_df = perform_technical_analysis(data_till_date, sector_df, logger, enable_chart_patterns=enable_chart_patterns)
                            if not analysis_df.empty:
                                date_str = d.strftime('%d-%m-%y')
                                outfile = f"{date_str}snapshot.csv"
                                analysis_df.to_csv(outfile, index=False)
                                print(f'Analysis for {d.strftime("%d-%m-%Y")} complete. Check the {outfile} file for results.')
                                logger.info(f"Saved analysis to {outfile}")
                    except Exception as e:
                        logger.error(f"Invalid date range format: {e}")
                        return
                else:
                    # Single date or blank: original logic
                    if date_input:
                        try:
                            specific_date = datetime.strptime(date_input, '%d-%m-%Y')
                            mask = adjusted_data['datetime'] <= specific_date
                            adjusted_data = adjusted_data[mask]
                        except Exception as e:
                            logger.error(f"Invalid date format: {e}")
                            return

                    if adjusted_data.empty:
                        logger.error("No data found for the specified date(s).")
                        return

                    chart_choice = get_input("Enable Chart Pattern analysis? (y/N): ").strip().lower()
                    enable_chart_patterns = chart_choice in ['y', 'yes']
                    analysis_df = perform_technical_analysis(adjusted_data, sector_df, logger, enable_chart_patterns=enable_chart_patterns)
                    if not analysis_df.empty:
                        latest_date = pd.to_datetime(analysis_df['date']).max()
                        date_str = latest_date.strftime('%d-%m-%y')
                        outfile = f"{date_str}snapshot.csv"
                        analysis_df.to_csv(outfile, index=False)
                        print(f'Analysis complete. Check the {outfile} file for results.')
                        logger.info(f"Saved analysis to {outfile}")
                return
            except Exception as e:
                logger.error(f"Error during analysis: {e}")
                return

        else:
            logger.error("Invalid choice")
            return

        if choice in ['1', '2', '3'] and not raw_data.empty:
            raw_data.to_csv(CONFIG['RAW_DATA_FILE'], index=False)
            logger.info(f"Saved raw data to {CONFIG['RAW_DATA_FILE']}")
            adjusted_data, splits = adjust_prices(raw_data, logger)
            if not adjusted_data.empty:
                adjusted_data.to_csv(CONFIG['ADJUSTED_DATA_FILE'], index=False)
                splits.to_csv(CONFIG['SPLITS_LOG_FILE'], index=False)
                logger.info(f"Saved adjusted data to {CONFIG['ADJUSTED_DATA_FILE']} and splits to {CONFIG['SPLITS_LOG_FILE']}")

    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")

if __name__ == "__main__":
    logger = setup_logging(verbose=False)
    main()