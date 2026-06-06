import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from nselib import capital_market
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import List, Tuple, Set, Optional
from .config import CONFIG

logger = logging.getLogger("stockanalyzer")

def load_symbols(filepath: str) -> Tuple[List[str], pd.DataFrame, Set[datetime.date]]:
    """Loads symbols, sectors, and holidays from the CSV file."""
    try:
        df = pd.read_csv(filepath)
        df.columns = df.columns.str.strip().str.upper()
        if 'SYMBOL' not in df.columns:
            logger.error(f"'SYMBOL' column missing in {filepath}")
            return [], pd.DataFrame(), set()
            
        df['SYMBOL'] = df['SYMBOL'].astype(str).str.upper().str.strip() \
            .str.replace('.NS', '', regex=False) \
            .str.replace('-EQ', '', regex=False)
            
        symbols = df['SYMBOL'].dropna().unique().tolist()
        sector_df = df[['SYMBOL', 'SECTOR']].drop_duplicates().rename(columns={'SYMBOL': 'symbols'}) if 'SECTOR' in df.columns else pd.DataFrame()
        
        holidays = set()
        if 'HOLIDAYS' in df.columns:
            holiday_list = df['HOLIDAYS'].dropna().astype(str).str.strip().str.split(';').explode().str.strip()
            for date_str in holiday_list:
                try:
                    holiday_date = pd.to_datetime(date_str, format='%d-%m-%Y', errors='coerce')
                    if pd.notna(holiday_date):
                        holidays.add(holiday_date.date())
                except Exception as e:
                    logger.warning(f"Invalid holiday date format '{date_str}': {e}")
        
        return symbols, sector_df, holidays
    except Exception as e:
        logger.error(f"Error loading symbols: {e}")
        return [], pd.DataFrame(), set()

def get_nse_holiday_dates(symbols_file: str) -> Set[datetime.date]:
    _, _, holidays = load_symbols(symbols_file)
    return holidays

def standardize_data(df: pd.DataFrame, filepath: str = '', logger: logging.Logger = logger) -> pd.DataFrame:
    """Standardizes columns and formats for technical analysis."""
    if df.empty:
        if logger: logger.warning(f"No data in {filepath or 'DataFrame'}")
        return df
    try:
        df.columns = df.columns.str.strip().str.lower()
        if not all(col in df.columns for col in CONFIG['REQUIRED_COLUMNS']):
            logger.error(f"Missing required columns in {filepath or 'DataFrame'}")
            return pd.DataFrame()
            
        df['datetime'] = pd.to_datetime(df['datetime'], errors='coerce')
        df['symbols'] = df['symbols'].astype(str).str.upper().str.strip() \
            .str.replace('.NS', '', regex=False) \
            .str.replace('-EQ', '', regex=False)
            
        df = df.dropna(subset=['datetime', 'symbols']) \
               .sort_values(['symbols', 'datetime']) \
               .drop_duplicates(['symbols', 'datetime'], keep='last')
        if logger:
            logger.info(f"Standardized {len(df)} records from {filepath or 'DataFrame'}")
        return df
    except Exception as e:
        logger.error(f"Error standardizing data: {e}")
        return pd.DataFrame()

def fetch_and_format(trade_date: str, symbol_filter: Optional[List[str]] = None, logger: logging.Logger = logger) -> Optional[pd.DataFrame]:
    """Fetches NSE bhavcopy for a specific date and formats for analysis."""
    try:
        spot_data = capital_market.bhav_copy_with_delivery(trade_date=trade_date)
        ohlcv_columns = ['SYMBOL', 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY', 'DELIV_PER']
        available_cols = [col for col in ohlcv_columns if col in spot_data.columns]
        
        if not all(col in spot_data.columns for col in ['SYMBOL', 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY']):
            return None
            
        spot_ohlcv = spot_data[available_cols].copy()
        numeric_columns = [col for col in ['OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY', 'DELIV_PER'] if col in spot_ohlcv.columns]
        for col in numeric_columns:
            spot_ohlcv[col] = pd.to_numeric(spot_ohlcv[col], errors='coerce')

        spot_ohlcv.rename(columns={
            'SYMBOL': 'symbols', 'OPEN_PRICE': 'open', 'HIGH_PRICE': 'high',
            'LOW_PRICE': 'low', 'CLOSE_PRICE': 'close', 'TTL_TRD_QNTY': 'volume', 'DELIV_PER': 'delivery_perc'
        }, inplace=True)

        spot_ohlcv['symbols'] = spot_ohlcv['symbols'].str.upper().str.strip()
        spot_ohlcv['datetime'] = pd.to_datetime(trade_date, format='%d-%m-%Y')
        spot_ohlcv = spot_ohlcv.dropna(subset=['open', 'high', 'low', 'close', 'volume'])

        if symbol_filter is not None:
            spot_ohlcv = spot_ohlcv[spot_ohlcv['symbols'].isin(symbol_filter)]

        if logger: logger.info(f"Fetched {spot_ohlcv.shape[0]} records for {trade_date}")
        return spot_ohlcv
    except Exception as e:
        logger.warning(f"Failed to fetch data for {trade_date}: {e}")
        return None

def fetch_data(symbols: List[str], from_date: datetime, to_date: datetime, logger: logging.Logger = logger) -> pd.DataFrame:
    """Batch fetches data across a date range using threading."""
    all_data = []
    date_list = []
    current_date = from_date
    nse_holidays = get_nse_holiday_dates(CONFIG['SYMBOLS_FILE'])

    while current_date <= to_date:
        if current_date.weekday() < 5 and current_date.date() not in nse_holidays:
            date_list.append(current_date.strftime('%d-%m-%Y'))
        current_date += timedelta(days=1)

    if not date_list:
        return pd.DataFrame()

    with ThreadPoolExecutor(max_workers=CONFIG['MAX_WORKERS']) as executor:
        futures = {executor.submit(fetch_and_format, d, symbols, logger): d for d in date_list}
        for future in tqdm(as_completed(futures), total=len(futures), desc="Fetching data"):
            result = future.result()
            if result is not None and not result.empty:
                all_data.append(result)

    if not all_data:
        return pd.DataFrame()

    combined_df = pd.concat(all_data, ignore_index=True)
    return standardize_data(combined_df, logger=logger)

def detect_splits(symbol_data: pd.DataFrame, logger: logging.Logger = logger) -> pd.DataFrame:
    """Detects stock splits based on percentage price drops."""
    try:
        if len(symbol_data) < 2:
            symbol = symbol_data['symbols'].iloc[0] if not symbol_data.empty else 'unknown'
            logger.warning(f"Skipping split detection for {symbol}: insufficient data")
            return pd.DataFrame()

        symbol_data = symbol_data.sort_values('datetime').reset_index(drop=True)
        price_diffs = symbol_data['close'].pct_change()
        splits = []

        for idx in price_diffs[price_diffs <= -0.3].index:
            if idx == 0: continue
            prev, curr = symbol_data['close'].iloc[idx - 1], symbol_data['close'].iloc[idx]
            ratio = prev / curr
            if 1.5 <= ratio <= 12:
                splits.append({
                    'symbols': symbol_data['symbols'].iloc[0],
                    'SPLIT_DATE': symbol_data['datetime'].iloc[idx],
                    'SPLIT_RATIO': round(ratio, 2),
                })
        return pd.DataFrame(splits)
    except Exception as e:
        logger.error(f"Split detection error: {e}")
        return pd.DataFrame()

def adjust_prices(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Applies split adjustments to historical OHLC data."""
    if df.empty: return df, pd.DataFrame()
    try:
        splits = pd.concat([detect_splits(df[df['symbols'] == s]) for s in df['symbols'].unique()], ignore_index=True)
        adjusted = df.copy()
        if not splits.empty:
            for _, split in splits.iterrows():
                mask = (adjusted['symbols'] == split['symbols']) & (adjusted['datetime'] < split['SPLIT_DATE'])
                adjusted.loc[mask, ['open', 'high', 'low', 'close']] /= split['SPLIT_RATIO']
        return adjusted, splits
    except Exception as e:
        logger.error(f"Adjustment error: {e}")
        return df, pd.DataFrame()