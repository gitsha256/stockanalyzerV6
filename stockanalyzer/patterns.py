import pandas as pd
import numpy as np
from scipy.signal import argrelextrema
from typing import List, Tuple, Optional, Dict, Any
from .config import CONFIG, PATTERN_SENTIMENT, get_pattern_base_confidence


def _pivot_points(data: pd.DataFrame, order: int = 5, lookback: int = 120) -> Tuple[pd.DataFrame, list, list]:
    recent = data.tail(lookback).reset_index(drop=True)
    prices = recent['close'].values.astype(float)
    if len(prices) < 2 * order + 1:
        return recent, [], []

    high_idx = argrelextrema(prices, np.greater_equal, order=order)[0]
    low_idx = argrelextrema(prices, np.less_equal, order=order)[0]

    high_idx = [i for i in high_idx if i < len(prices) - order]
    low_idx = [i for i in low_idx if i < len(prices) - order]

    highs = [(int(i), float(prices[i])) for i in high_idx]
    lows = [(int(i), float(prices[i])) for i in low_idx]
    return recent, highs, lows


def _resample_to_weekly(daily_df: pd.DataFrame) -> pd.DataFrame:
    if daily_df is None or daily_df.empty:
        return pd.DataFrame()
    d = daily_df.sort_values('datetime').copy()
    d['datetime'] = pd.to_datetime(d['datetime'])
    d = d.set_index('datetime')
    agg = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
    w = d.resample('W-FRI').agg(agg).dropna(subset=['close'])
    return w.reset_index()


def _pivot_indices_spaced(idxs: list, min_gap: int, min_span: int) -> bool:
    if len(idxs) < 2:
        return False
    for a in range(len(idxs) - 1):
        if idxs[a + 1] - idxs[a] < min_gap:
            return False
    return idxs[-1] - idxs[0] >= min_span


def _chain_spaced(idxs: list, min_gap: int) -> bool:
    if len(idxs) < 2:
        return True
    for a in range(len(idxs) - 1):
        if idxs[a + 1] - idxs[a] < min_gap:
            return False
    return True


def _line_slope(points: list) -> float:
    if len(points) < 2:
        return 0.0
    y = np.array([p for _, p in points], dtype=float)
    x = np.arange(len(y), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def _is_flat(values: list, tolerance_ratio: float = 0.02) -> bool:
    if len(values) < 2:
        return False
    avg = np.mean(values)
    if avg == 0:
        return False
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
        if abs((hi - li) - (ri - hi)) / max(hi - li, ri - hi) > 0.30:
            continue

        shoulder_ref = (lp + rp) / 2
        if shoulder_ref == 0:
            continue
        if abs(lp - rp) / shoulder_ref > tolerance:
            continue
        if (hp - lp) / hp < 0.06 or (hp - rp) / hp < 0.06:
            continue

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
        if abs((hi - li) - (ri - hi)) / max(hi - li, ri - hi) > 0.30:
            continue

        shoulder_ref = (lp + rp) / 2
        if shoulder_ref == 0:
            continue
        if abs(lp - rp) / shoulder_ref > tolerance:
            continue
        if (lp - hp) / lp < 0.06 or (rp - hp) / rp < 0.06:
            continue

        peak_left = [v for idx, v in highs if li < idx < hi]
        peak_right = [v for idx, v in highs if hi < idx < ri]
        if peak_left and peak_right:
            return "Inverse Head and Shoulders", [li, hi, ri]
    return None


def _detect_double_top_bottom(highs, lows, last_close, tolerance=0.02, min_gap=12, min_span=20):
    if len(highs) >= 2:
        (i1, p1), (i2, p2) = sorted(highs, key=lambda x: x[0])[-2:]
        if (i2 - i1) >= min_gap and (i2 - i1) >= min_span and abs(p1 - p2) / ((p1 + p2) / 2) <= tolerance:
            troughs_between = [v for idx, v in lows if i1 < idx < i2]
            if troughs_between and min(troughs_between) < min(p1, p2) * 0.97 and last_close < p2 * 0.98:
                return "Double Top", [i1, i2]
    if len(lows) >= 2:
        (i1, p1), (i2, p2) = sorted(lows, key=lambda x: x[0])[-2:]
        if (i2 - i1) >= min_gap and (i2 - i1) >= min_span and abs(p1 - p2) / ((p1 + p2) / 2) <= tolerance:
            peaks_between = [v for idx, v in highs if i1 < idx < i2]
            if peaks_between and max(peaks_between) > max(p1, p2) * 1.03 and last_close > p2 * 1.02:
                return "Double Bottom", [i1, i2]
    return None


def _detect_triple_top_bottom(highs, lows, tolerance=0.025, min_gap=10, min_span=25):
    if len(highs) >= 3:
        last_highs = sorted(highs, key=lambda x: x[0])[-3:]
        idxs = [x[0] for x in last_highs]
        if _pivot_indices_spaced(idxs, min_gap, min_span) and _is_flat([x[1] for x in last_highs], tolerance):
            return "Triple Top", idxs
    if len(lows) >= 3:
        last_lows = sorted(lows, key=lambda x: x[0])[-3:]
        idxs = [x[0] for x in last_lows]
        if _pivot_indices_spaced(idxs, min_gap, min_span) and _is_flat([x[1] for x in last_lows], tolerance):
            return "Triple Bottom", idxs
    return None


def _detect_triangle(highs, lows, min_gap=4):
    if len(highs) < 3 or len(lows) < 3:
        return None
    h_recent = sorted(highs, key=lambda x: x[0])[-4:]
    l_recent = sorted(lows, key=lambda x: x[0])[-4:]
    hi_idx, lo_idx = [x[0] for x in h_recent], [x[0] for x in l_recent]
    if not _chain_spaced(hi_idx, min_gap) or not _chain_spaced(lo_idx, min_gap):
        return None

    hs, ls = np.array([x[1] for x in h_recent]), np.array([x[1] for x in l_recent])
    h_slope = np.polyfit(np.arange(len(hs)), hs, 1)[0]
    l_slope = np.polyfit(np.arange(len(ls)), ls, 1)[0]

    flat_thr = max(np.nanmean(hs), np.nanmean(ls)) * 0.0005
    pts = [hi_idx[-2], hi_idx[-1], lo_idx[-2], lo_idx[-1]]
    if h_slope < -flat_thr and l_slope > flat_thr:
        return "Symmetrical Triangle", pts
    if abs(h_slope) <= flat_thr and l_slope > flat_thr:
        return "Ascending Triangle", pts
    if h_slope < -flat_thr and abs(l_slope) <= flat_thr:
        return "Descending Triangle", pts
    return None


def _detect_channel(recent, highs, lows, min_gap=2, min_span=12):
    if recent is None or recent.empty or len(highs) < 3 or len(lows) < 3:
        return None
    h_sorted = sorted(highs, key=lambda x: x[0])[-4:]
    l_sorted = sorted(lows, key=lambda x: x[0])[-4:]
    if abs(h_sorted[0][0] - l_sorted[0][0]) > 3:
        return None
    start_idx, end_idx = min(h_sorted[0][0], l_sorted[0][0]), max(h_sorted[-1][0], l_sorted[-1][0])
    if (end_idx - start_idx) < min_span:
        return None

    c = recent['close'].values.astype(float)
    hx, hy = zip(*h_sorted)
    lx, ly = zip(*l_sorted)
    hm, hc = np.polyfit(hx, hy, 1)
    lm, lc = np.polyfit(lx, ly, 1)
    idx_arr = np.arange(start_idx, len(c))
    violations = np.sum((c[start_idx:] > (hm * idx_arr + hc) * 1.05) | (c[start_idx:] < (lm * idx_arr + lc) * 0.95))
    if violations > (len(c) - start_idx) * 0.15:
        return None

    hs, ls = _line_slope(h_sorted), _line_slope(l_sorted)
    if (hs > 0 and ls > 0) or (hs < 0 and ls < 0):
        if abs(hs - ls) <= max(abs(hs), abs(ls)) * 0.3:
            pts = [x[0] for x in h_sorted] + [x[0] for x in l_sorted]
            mag = max(np.mean(hy), np.mean(ly)) * 0.0004
            if hs > mag:
                return "Ascending Channel", pts
            if hs < -mag:
                return "Descending Channel", pts
    return None


def _detect_wedge(recent, highs, lows, min_gap=2, min_span=12):
    if recent is None or recent.empty or len(highs) < 3 or len(lows) < 3:
        return None
    h_sorted = sorted(highs, key=lambda x: x[0])[-4:]
    l_sorted = sorted(lows, key=lambda x: x[0])[-4:]
    if abs(h_sorted[0][0] - l_sorted[0][0]) > 3:
        return None
    start_idx, end_idx = min(h_sorted[0][0], l_sorted[0][0]), max(h_sorted[-1][0], l_sorted[-1][0])
    if (end_idx - start_idx) < min_span:
        return None

    hs, ls = _line_slope(h_sorted), _line_slope(l_sorted)
    h_vals, l_vals = [x[1] for x in h_sorted], [x[1] for x in l_sorted]
    if (h_vals[-1] - l_vals[-1]) < (h_vals[0] - l_vals[0]) * 0.60:
        pts = [x[0] for x in h_sorted] + [x[0] for x in l_sorted]
        if hs < 0 and ls < 0 and ls < hs:
            return "Falling Wedge", pts
        if hs > 0 and ls > 0 and hs < ls:
            return "Rising Wedge", pts
    return None


def _detect_rectangle(highs, lows, min_gap=2):
    if len(highs) < 3 or len(lows) < 3:
        return None
    h_sorted = sorted(highs, key=lambda x: x[0])[-4:]
    l_sorted = sorted(lows, key=lambda x: x[0])[-4:]
    if not _chain_spaced([x[0] for x in h_sorted], min_gap) or not _chain_spaced([x[0] for x in l_sorted], min_gap):
        return None
    if _is_flat([x[1] for x in h_sorted], 0.02) and _is_flat([x[1] for x in l_sorted], 0.02):
        return "Rectangle Pattern", [h_sorted[-1][0], l_sorted[-1][0]]
    return None


def _detect_flag_pennant(recent, highs, lows, tri_result=None):
    if len(recent) < 30:
        return None
    c = recent['close'].values.astype(float)
    if c[0] == 0:
        return None
    pole_ret = (c[15] - c[0]) / c[0]
    pullback = c[29] - c[15]
    small_consolidation = abs(pullback) <= abs(c[15] - c[10]) * 1.2
    tri = tri_result[0] if tri_result else None
    pts = [0, 15, 29]
    if pole_ret >= 0.06 and small_consolidation:
        return ("Pennant Pattern", pts) if tri else ("Flag Pattern (Bull Flag)", pts)
    if pole_ret <= -0.06 and small_consolidation:
        return ("Pennant Pattern", pts) if tri else ("Flag Pattern (Bear Flag)", pts)
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
    right_peak_idx = split1 + np.argmax(right_zone)
    right_peak = right_zone[np.argmax(right_zone)]

    cup_data = c[left_peak_idx:right_peak_idx + 1]
    if len(cup_data) < 20:
        return None

    y_cup = cup_data
    x_cup = np.linspace(-1, 1, len(y_cup))
    a_cup, b_cup, _ = np.polyfit(x_cup, y_cup, 2)
    std_cup = np.std(y_cup)

    if std_cup == 0:
        return None

    is_u_shape = a_cup > 0
    is_symmetric = abs(b_cup) < std_cup * 0.25
    is_curvy = abs(a_cup) > std_cup * 1.5

    if not (is_u_shape and is_symmetric and is_curvy):
        return None

    cup_bottom_idx = left_peak_idx + np.argmin(cup_data)
    cup_bottom = c[cup_bottom_idx]
    handle_low_idx = split2 + np.argmin(handle_zone)

    left_peak = c[left_peak_idx]
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

    is_symmetric = abs(b) < std_y * 0.25
    is_curvy = abs(a) > std_y * 1.5

    if a > 0 and is_symmetric and is_curvy:
        return f"{prefix}Rounding Bottom", [0, int(size * 0.25), int(size * 0.5), int(size * 0.75), size - 1]
    if a < 0 and is_symmetric and is_curvy:
        return f"{prefix}Rounding Top", [0, int(size * 0.25), int(size * 0.5), int(size * 0.75), size - 1]
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
    pts = [h[0][0], h[2][0], h[-1][0], l[0][0], l[2][0], l[-1][0]]
    if h_vals[-1] < h_vals[0]:
        return "Diamond Top", pts
    if l_vals[-1] > l_vals[0]:
        return "Diamond Bottom", pts
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


def _fmt_anchor(recent: pd.DataFrame, idx: int, label: str) -> Optional[str]:
    if idx is None or idx < 0 or idx >= len(recent):
        return None
    dt = pd.to_datetime(recent.iloc[idx]['datetime']).strftime('%d-%m-%Y')
    px = round(float(recent.iloc[idx]['close']), 2)
    return f"{label}:{dt}@{px}"


def _build_pattern_trace(main_pattern: str, recent: pd.DataFrame, points_idx: List[int]) -> Tuple[str, str, str]:
    if not points_idx:
        return "", "", ""

    labels = []
    if "Head and Shoulders" in main_pattern:
        labels = ["LS", "H", "RS"]
    elif "Double" in main_pattern:
        labels = ["P1", "P2"]
    elif "Triple" in main_pattern:
        labels = ["P1", "P2", "P3"]
    elif "Cup and Handle" in main_pattern:
        labels = ["RimL", "Btm", "RimR", "Hdl"]
    elif "Rounding" in main_pattern:
        labels = ["Start", "Q1", "Mid", "Q3", "End"]
    elif "Diamond" in main_pattern:
        labels = ["H1", "H2", "H3", "L1", "L2", "L3"]
    elif "Channel" in main_pattern or "Wedge" in main_pattern:
        mid = len(points_idx) // 2
        labels = [f"UL{i+1}" for i in range(mid)] + [f"LL{i+1}" for i in range(len(points_idx) - mid)]
    elif "Triangle" in main_pattern or "Broadening" in main_pattern:
        labels = ["H1", "H2", "L1", "L2"]
    elif "Flag" in main_pattern or "Pennant" in main_pattern:
        labels = ["PoleS", "PoleE", "Consol"]
    else:
        labels = [f"Pt{i+1}" for i in range(len(points_idx))]

    points = []
    for i, idx in enumerate(points_idx):
        label = labels[i] if i < len(labels) else f"Pt{i+1}"
        anchor = _fmt_anchor(recent, idx, label)
        if anchor:
            points.append(anchor)

    start_idx = max(0, min(points_idx))
    end_idx = min(len(recent) - 1, max(points_idx))
    start_date = pd.to_datetime(recent.iloc[start_idx]['datetime']).strftime('%d-%m-%Y')
    end_date = pd.to_datetime(recent.iloc[end_idx]['datetime']).strftime('%d-%m-%Y')
    return " ; ".join(points), start_date, end_date


def detect_price_patterns(data: pd.DataFrame, max_age_days: Optional[int] = None) -> Dict[str, Any]:
    """Master function to orchestrate chart pattern recognition."""
    if max_age_days is None:
        max_age_days = CONFIG.get('PATTERN_MAX_AGE_DAYS', 124)
    empty = {k: ("No Clear Pattern" if "pattern" in k else (0 if "confidence" in k else "")) for k in ["main_pattern", "main_confidence", "misc_patterns", "all_patterns", "pattern_points", "pattern_start", "pattern_end"]}
    if data is None or data.empty:
        return empty

    analysis_date = pd.to_datetime(data['datetime'].max())
    cutoff_date = analysis_date - pd.Timedelta(days=max_age_days)
    window = data[pd.to_datetime(data['datetime']) >= cutoff_date].copy()
    if len(window) < CONFIG.get('PATTERN_MIN_BARS_IN_WINDOW', 70):
        return empty

    w_gap = CONFIG.get('PATTERN_WEEKLY_MIN_GAP', 2)
    w_double = CONFIG.get('PATTERN_WEEKLY_MIN_DOUBLE_SPAN', 3)
    w_triple = CONFIG.get('PATTERN_WEEKLY_MIN_TRIPLE_SPAN', 5)
    w_hs = CONFIG.get('PATTERN_WEEKLY_MIN_HS_SPAN', 4)
    w_order = CONFIG.get('PATTERN_WEEKLY_PIVOT_ORDER', 2)
    daily_order = max(CONFIG.get('PATTERN_DAILY_PIVOT_ORDER_MIN', 10), min(CONFIG.get('PATTERN_DAILY_PIVOT_ORDER_MAX', 14), max(5, len(window) // 6)))

    recent_d, hd, ld = _pivot_points(window, order=daily_order, lookback=len(window))
    weekly = _resample_to_weekly(window)
    recent_w, hw, lw = (None, [], []) if len(weekly) < 6 else _pivot_points(weekly, order=w_order, lookback=len(weekly))

    patterns_found = []
    if recent_w is not None and len(recent_w) > 0 and (len(hw) >= 2 or len(lw) >= 2):
        for res in [
            _detect_head_shoulders(hw, lw, tolerance=0.03, min_gap=w_gap, min_span=w_hs),
            _detect_inverse_head_shoulders(hw, lw, tolerance=0.03, min_gap=w_gap, min_span=w_hs),
            _detect_double_top_bottom(hw, lw, float(window['close'].iloc[-1]), tolerance=0.022, min_gap=w_gap, min_span=w_double),
            _detect_triple_top_bottom(hw, lw, tolerance=0.022, min_gap=w_gap, min_span=w_triple),
            _detect_diamond(hw, lw, min_gap=1),
            _detect_wedge(recent_w, hw, lw, min_gap=w_gap, min_span=12),
            _detect_rectangle(hw, lw, min_gap=w_gap),
            _detect_broadening(hw, lw, min_gap=w_gap),
            _detect_channel(recent_w, hw, lw, min_gap=w_gap, min_span=12),
            _detect_triangle(hw, lw, min_gap=w_gap),
        ]:
            if res:
                patterns_found.append((res[0], res[1], recent_w))

    full_year = data.tail(252).copy().reset_index(drop=True)
    if len(full_year) >= 150:
        for res in [_detect_rounding(full_year, "Long-term "), _detect_cup_handle(full_year, "Long-term ")]:
            if res:
                patterns_found.append((res[0], res[1], full_year))

    for lb in [40, 50, 60, 75, 90, 110]:
        if len(window) >= lb:
            slice_df = window.tail(lb).reset_index(drop=True)
            for res in [_detect_rounding(slice_df), _detect_cup_handle(slice_df)]:
                if res:
                    patterns_found.append((res[0], res[1], slice_df))

    if len(window) >= 30 and len(hd) >= 2 and len(ld) >= 2:
        tri_d = _detect_triangle(hd, ld, min_gap=2)
        res = _detect_flag_pennant(window.reset_index(drop=True), hd, ld, tri_d)
        if res:
            patterns_found.append((res[0], res[1], window.reset_index(drop=True)))

    if not patterns_found:
        return empty

    scored = []
    for name, pts, df_ctx in patterns_found:
        base = get_pattern_base_confidence(name.replace("Long-term ", ""))
        scored.append({"name": name, "points": pts, "df": df_ctx, "score": base})

    unique = []
    seen = set()
    for s in sorted(scored, key=lambda x: x['score'], reverse=True):
        if s['name'] not in seen:
            unique.append(s)
            seen.add(s['name'])

    latest = window.iloc[-1]
    avg_v = window['volume'].tail(20).mean()
    vol_boost = 4 if avg_v > 0 and latest['volume'] / avg_v >= 1.5 else 0
    bo_boost = 3 if any(latest.get(k, False) for k in ['BB_BREAKOUT_UP', 'BB_BREAKOUT_DOWN']) else 0

    trend = "Neutral"
    if len(data) >= 200:
        sma = data['close'].rolling(200).mean()
        cur_s = sma.iloc[-1]
        prev_s = sma.iloc[-20]
        cur_p = data['close'].iloc[-1]
        trend = "Uptrend" if cur_p > cur_s > prev_s else "Downtrend" if cur_p < cur_s < prev_s else "Neutral"

    for u in unique:
        sent = PATTERN_SENTIMENT.get(u['name'].replace("Long-term ", ""), "Neutral")
        if trend == "Uptrend":
            t_adj = 8 if sent == "Bearish" else 4 if sent == "Bullish" else 0
        elif trend == "Downtrend":
            t_adj = 8 if sent == "Bullish" else -12 if sent == "Bearish" else 0
        else:
            t_adj = 0
        u['final_score'] = int(max(1, min(99, round(u['score'] + vol_boost + bo_boost + t_adj))))

    unique.sort(key=lambda x: x['final_score'], reverse=True)
    main = unique[0]
    pts_txt, p_start, p_end = _build_pattern_trace(main['name'], main['df'], main['points'])

    return {
        "main_pattern": main['name'],
        "main_confidence": main['final_score'],
        "misc_patterns": " | ".join([f"{p['name']}({p['final_score']})" for p in unique[1:]]),
        "all_patterns": " | ".join([f"{p['name']}({p['final_score']})" for p in unique]),
        "pattern_points": pts_txt,
        "pattern_start": p_start,
        "pattern_end": p_end,
    }


def detect_price_pattern(data: pd.DataFrame) -> str:
    return detect_price_patterns(data).get("all_patterns", "No Clear Pattern")