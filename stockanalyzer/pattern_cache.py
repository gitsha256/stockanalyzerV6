import json
import hashlib
import pathlib
import logging
import numpy as np
import pandas as pd
from typing import Optional, Dict, Any

logger = logging.getLogger("stockanalyzer")
CACHE_DIR = pathlib.Path(".pattern_cache")

def compute_symbol_state_hash(df: pd.DataFrame, rows: int = 30) -> str:
    """
    Generates a unique hash based on the last N rows of price/volume data.
    Used to detect if the symbol's data state has changed.
    """
    cols = ['open', 'high', 'low', 'close', 'volume']
    # Ensure we only hash columns that affect technical structure
    subset = df.tail(rows)[cols]
    # Serialize to CSV string for consistent hashing
    csv_str = subset.to_csv(index=False)
    return hashlib.md5(csv_str.encode('utf-8')).hexdigest()[:12]

def get_cached_pattern(symbol: str, hash12: str) -> Optional[Dict[str, Any]]:
    """
    Attempts to retrieve a cached pattern result for a symbol and state hash.
    """
    cache_file = CACHE_DIR / f"{symbol}_{hash12}.json"
    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Corrupt cache file detected for {symbol}: {e}. Deleting.")
        try:
            cache_file.unlink(missing_ok=True)
        except Exception:
            pass
        return None

def save_pattern_cache(symbol: str, hash12: str, result: Dict[str, Any]):
    """
    Saves a pattern result to cache and cleans up previous states for the symbol.
    """
    if not CACHE_DIR.exists():
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Cleanup orphans: delete any other hash versions for this symbol
    for old_cache in CACHE_DIR.glob(f"{symbol}_*.json"):
        try:
            old_cache.unlink()
        except Exception:
            pass

    cache_file = CACHE_DIR / f"{symbol}_{hash12}.json"
    try:
        with open(cache_file, 'w') as f:
            json.dump(result, f)
    except Exception as e:
        logger.error(f"Failed to write cache for {symbol}: {e}")

def cache_stats() -> Dict[str, Any]:
    """
    Calculates current utilization of the pattern cache.
    """
    if not CACHE_DIR.exists():
        return {"total_files": 0, "total_size_kb": 0.0, "symbols_cached": 0}

    files = list(CACHE_DIR.glob("*.json"))
    total_size = sum(f.stat().st_size for f in files) / 1024.0
    unique_symbols = {f.name.split('_')[0] for f in files}
    
    return {
        "total_files": len(files),
        "total_size_kb": total_size,
        "symbols_cached": len(unique_symbols)
    }