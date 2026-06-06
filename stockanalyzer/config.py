import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG = {
    'SYMBOLS_FILE': str(BASE_DIR / 'symbols.csv'),
    'RAW_DATA_FILE': str(BASE_DIR / 'raw_data.csv'),
    'ADJUSTED_DATA_FILE': str(BASE_DIR / 'data.csv'),
    'SPLITS_LOG_FILE': str(BASE_DIR / 'detected_splits.csv'),
    'ANALYSIS_OUTPUT_FILE': str(BASE_DIR / 'snapshot.csv'),
    'MAX_WORKERS': 6,
    'DEFAULT_LOOKBACK_DAYS': 756,
    'FETCH_INTERVAL': 'D',
    'REQUIRED_COLUMNS': ['datetime', 'open', 'high', 'low', 'close', 'volume', 'symbols'],
    'PATTERN_MAX_AGE_DAYS': 252,
    'PATTERN_MIN_BARS_IN_WINDOW': 70,
    'PATTERN_WEEKLY_PIVOT_ORDER': 2,
    'PATTERN_WEEKLY_MIN_GAP': 2,
    'PATTERN_WEEKLY_MIN_DOUBLE_SPAN': 3,
    'PATTERN_WEEKLY_MIN_TRIPLE_SPAN': 5,
    'PATTERN_WEEKLY_MIN_HS_SPAN': 4,
    'PATTERN_DAILY_PIVOT_ORDER_MIN': 10,
    'PATTERN_DAILY_PIVOT_ORDER_MAX': 14,
}

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

def get_pattern_base_confidence(pattern_name: str) -> int:
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