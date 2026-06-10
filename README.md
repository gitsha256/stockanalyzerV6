# NSE Stock Analyzer V6

A comprehensive, institutional-grade technical analysis suite for the National Stock Exchange (NSE). V6 introduces a **modular package architecture**, **high-performance Symbol-State Pattern Cache**, **unified Market Universe selection**, and an **integrated workflow orchestrator** to streamline data-to-alpha generation.

## 📋 Requirements

```
pip install -r requirements.txt
```

- Python 3.12+
- `pandas`, `numpy`, `nselib`, `pandas-ta`, `scipy`, `plotly`, `streamlit`, `yfinance`, `requests`, `openpyxl`, `tqdm`

---

## 🚀 Quick Start Guide (Setup & Workflow)

Follow this step-by-step guide to go from a fresh clone to your first trade picks.

### 1. Environment Setup

Open your terminal (PowerShell or CMD) and run:

```bash
# Move into the project directory
cd stockanalyzerV6

# Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows

# Install all required libraries
pip install -r requirements.txt
```

### 2. The Data Core Flow (`main.py`)

Start the core engine to build your database and generate snapshots.

1. **Select Market Universe**: Choose between **Nifty 500** or the **Broader Market** (All symbols).
2. **Run Fetch (Mode 1)**: Initial download of historical data for your chosen range. Generates `raw_data.csv`.
3. **Update (Mode 2)**: Daily maintenance. Appends the latest trading session to your existing database.
4. **Adjust (Mode 3)**: Mathematically adjusts historical prices for stock splits and bonuses. Reads `raw_data.csv` and generates the essential `data.csv`.
5. **Analyze (Mode 4)**: Computes all technical indicators, stages, and zones. Generates the `snapshot.csv` signal file. **Pro-tip:** Press **Enter** at the date prompt to automatically use the latest available data; the script will confirm the date it finds before starting.

> **Daily Workflow in Practice:**
> ```
> Mode 2 → appends 1 new candle to raw_data.csv
> Mode 4 → reads data.csv → runs analysis → writes snapshot.csv
> ```
> Run Mode 3 (Adjust) only when a corporate action (split/bonus) is detected — not daily.

### 3. Automated Reporting & Organization (`analyzer.py`)

Instead of running individual scripts after analysis, use the workflow orchestrator to process your latest snapshot in one command:

```bash
python analyzer.py
```

This automatically triggers the full post-analysis pipeline in sequence:

1. **Excel Formatting** — Color-coded heatmaps of the entire market via `formatter.py`
2. **Sectoral RRG** — Multi-factor institutional rotation analysis via `sectoralanalysis.py`
3. **Stock Screening** — Top 10 Intraday and Swing picks via `screen_stocks.py`
4. **SMA Confluence** — Stocks with tightening moving averages via `sma_filter.py`

---

## 🚀 Project Components

| Script | Description |
| :--- | :--- |
| `main.py` | **The V6 Core Engine.** Replaces legacy analyzers. Centralizes market universe selection, data management (Fetch/Update/Adjust), and technical snapshot generation. |
| `analyzer.py` | **Master Analyzer Suite.** Processes snapshots and organizes results into date-based folders (e.g., `DD-MM-YYYY` or `DD-MM-YYYY_all` for broader market). |
| `analyzer.py` | **The Orchestrator.** Automates the full post-analysis pipeline by calling the analyzer and other reporting tools in sequence. |
| `sectoralanalysis.py` | **The Master Strategy Bridge.** A proprietary Manual RRG engine that synthesizes sector indices, calculates multi-factor Rotational Scores, and enforces sector-specific trade filters. |
| `formatter.py` | **The Visualization Engine.** Converts snapshots to professional multi-sheet Excel reports with automated heat-mapping. |
| `screen_stocks.py` | **The Ranking Engine.** Applies multi-weighted scoring algorithms to produce top-tier Intraday and Weekly Swing candidates. |
| `sma_filter.py` | Utility to find stocks where multiple SMAs (20, 50, 100, 200) are converging (volatility confluence). |
| `montecarlo.py` | **Risk Management.** Fetches live Nifty/VIX data to provide position sizing and Monte Carlo price simulations for professional options trading. |

> Before running `montecarlo.py`, ensure your virtual environment is active:
> ```bash
> python -m venv venv
> .\venv\Scripts\Activate.ps1
> ```

---

## 📦 The `stockanalyzer` Package

V6 modularizes all core logic into a dedicated internal package for better maintainability and testability. Each module has a single responsibility:

| Module | Responsibility |
| :--- | :--- |
| `data.py` | NSE bhavcopy fetching via `nselib`, data standardization, and the price adjustment engine (detecting and applying stock splits from `raw_data.csv`). |
| `analysis.py` | The computational heart. Orchestrates the per-symbol analysis loop, resamples data for weekly indicators, and calculates Long-Term and Medium-Term price zones. |
| `pattern_cache.py` | **New in V6.** High-performance symbol-state JSON cache. Hashes the last 30 rows of OHLCV data per symbol; bypasses the CPU-heavy pattern recognition engine on cache hits. Results in **~10× faster** re-runs. |
| `indicators.py` | Centralized library for all technical indicators (RSI, ADX, Bollinger Bands, Supertrend, CMF, Stochastic, etc.) using `pandas-ta`. |
| `patterns.py` | Advanced pivot-based structural pattern recognition engine (Cup & Handle, Triangles, Channels, Broadening Formations, etc.). |
| `weinstein.py` | Logic for determining Weinstein Stage (1–4) and Weekly Stage based on price/SMA30 relationship. |
| `config.py` | Global settings, file paths, and tunable constants. |
| `utils.py` | Logging setup, input helpers, and shared utilities. |

---

## ⚡ Symbol-State Pattern Cache (`pattern_cache.py`)

Chart pattern recognition is the most CPU-intensive step in Mode 4. V6 introduces an intelligent caching layer that eliminates redundant computation.

### How It Works

1. **State Hashing** — For each symbol, the last 30 rows of `(open, high, low, close, volume)` are serialized and hashed into a 12-character MD5 fingerprint.
2. **Cache Hit** — If `.pattern_cache/{SYMBOL}_{hash12}.json` exists, pattern columns (`mpat`, `pcon`, `psta`, `pend`, `ppnt`, `xpat`, `patt`) are loaded instantly from disk. Pattern engine is skipped entirely.
3. **Cache Miss** — When price data changes (new daily candle appended, or a Mode 3 split adjustment backfilling historical prices), the hash changes automatically. The engine recomputes and saves the new result.
4. **Auto-Cleanup** — On every cache miss, orphaned files from previous data states for that symbol are deleted. The cache folder stays at ~1 file per symbol (~1500 files max) and never accumulates unboundedly.

### Why State-Hash (Not Date-Key)

The cache key is based on **what data produced the result**, not **what date the run was**. This matters because:

- A new daily candle → different hash → automatic miss → recomputed ✅
- A Mode 3 split adjustment backfilling historical prices → different hash → automatic miss → recomputed ✅
- Re-running Mode 4 on the same day (testing/tweaking) → same hash → instant cache hit ✅
- Running a date range for backtesting → all historical symbol states → full cache hits ✅

No manual cache invalidation is ever needed.

### Cache Output During Analysis

```
[CACHE] 1423 symbols cached | 287 KB
...
[CACHE] Hit: 1423 | Miss: 77 | Ratio: 94.9%
```

---

## 🔄 Sector Rotation & RRG Analysis (`sectoralanalysis.py`)

V6 places `sectoralanalysis.py` at the heart of the workflow. It acts as the "Bridge" between raw market data and actionable trades. Unlike standard scanners, it uses a **Manual RRG (Relative Rotation Graph) Engine** to identify where institutional money is flowing.

### Key Features

- **Index Synthesis**: Automatically builds equal-weighted sector indices directly from your local historical data (`data.csv`).
- **Manual RRG Calculation**: Calculates **RS-Ratio** (trend) and **RS-Momentum** (velocity) against the Nifty 50 benchmark without needing external data feeds.
- **Rotational Scoring**: An institutional-grade multi-factor score (0–100) based on:
  - **RSI Breadth**: % of stocks in the sector with RSI ≥ 50.
  - **EMA Breadth**: % of stocks trading above their 50-day SMA.
  - **Delivery Conviction**: Average delivery percentage across the sector.
  - **Heading Score**: Rewards sectors accelerating North-East toward the "Leading" quadrant.
- **Automatic Filtering**: Only permits swing candidates from "Leading" or "Improving" sectors, ensuring you are always trading with the wind at your back.

---

## 📈 V6 Structural Analysis Features

The analyzer performs deep structural scans on every symbol:

- **Weinstein Stages**: Automatically classifies stocks into Stage 1 (Base), Stage 2 (Uptrend), Stage 3 (Top), or Stage 4 (Downtrend) on both daily and weekly timeframes.
- **Dual-Zone Analysis**: Two distinct structural positioning layers to evaluate risk-to-reward:
  - **Long-Term Zone (`zone`)**: Calculated using `order=252` anchors (52-week extremes).
  - **Medium-Term Zone (`MT_Zone`)**: Calculated using `order=60` anchors — the stock's position within the most recent ~3-month swing structure.
  - Both use adaptive percentile logic (Discount / Equilibrium / Premium) normalized across different stock volatilities.
- **Pattern Engine**: Detects complex structures including Cup and Handle, Rounding Bottoms, Wedges, Channels, Broadening Formations, and Triangles using multi-timeframe pivot analysis.

---

## 📊 Abbreviation Dictionary

The analysis outputs (e.g., `04-06-26snapshot_all.csv`) use the following column headers:

### Core Data

| Column | Full Name | Description |
| :--- | :--- | :--- |
| `symb` | Symbol | NSE stock ticker |
| `clos` | Close | Adjusted closing price |
| `open` | Open | Market opening price |
| `high` / `low` | High / Low | Daily high and low prices |
| `chan` | Change % | Daily % change from open to close |
| `volu` | Volume | Total traded volume |
| `DlPer` | Delivery % | Delivery percentage — genuine accumulation indicator |
| `date` | Date | Trading date of the record |
| `sect` | Sector | Industry sector |
| `ascr` / `arnk` | Activity Score / Rank | Liquidity in ₹ (Price × Volume / 10M) and its market rank |

### Technical Indicators

| Column | Description |
| :--- | :--- |
| `rsi` / `wrsi` | Daily and Weekly RSI (Momentum) |
| `adx` | Average Directional Index (Trend Strength) |
| `obv` | On-Balance Volume (Cumulative volume flow) |
| `s020` / `s050` / `s100` / `s200` | Simple Moving Averages (20, 50, 100, 200 days) |
| `g200` / `g050` / `g020` | Boolean — is price above the 200/50/20 SMA? |
| `ws30` | Weekly 30-period SMA (Weinstein's primary indicator) |
| `vola` | Annualized Volatility (21-day standard deviation) |
| `bbup` / `bbdn` | Boolean — price breaking above upper / below lower Bollinger Band |
| `bbbw` | Bollinger Bandwidth (Volatility measurement) |
| `bbsq` | Bollinger Squeeze — true if volatility is at a 300-day relative low |
| `CMF_20` | 20-day Chaikin Money Flow (volume-weighted accumulation/distribution) |
| `SUPERT_7_3.0` / `SUPERTd_7_3.0` | Supertrend value and direction (+1 up / -1 down) |
| `STOCHk_14_3_3` / `STOCHd_14_3_3` | Stochastic %K and %D |
| `EMA_21` | 21-day Exponential Moving Average |
| `SQZ_ON` / `SQZ_OFF` / `SQZ_NO` | Squeeze Momentum state flags (compression / breakout / neutral) |
| `WILLR_14` | Williams %R momentum oscillator |
| `EFI_13` | Elder Force Index (volume-based momentum) |
| `RSI_2` | 2-period RSI (short-term pullback detection) |

### Trend & Stage Analysis

| Column | Description |
| :--- | :--- |
| `stge` | Weinstein Stage (Stage 1: Base, Stage 2: Uptrend, Stage 3: Top, Stage 4: Downtrend) |
| `stge_w` | Weekly Weinstein Stage — alignment of `stge` + `stge_w` = strongest signal |
| `tren` | Trend Direction (Uptrend / Sideways / Downtrend) |
| `tstr` | Trend Strength (Strong / Moderate / Weak) |
| `zone` | Long-term Price Location (Premium / Near Premium / Equilibrium / Near Discount / Discount) |
| `MT_Zone` | Medium-term Price Location within the recent 60-day swing range |
| `vrnk` / `rrnk` | Volume Rank and Relative Volume Rank |
| `delt` | % distance currently below the 52-week high |
| `h52h` / `l52l` | 52-Week High and Low prices |
| `shgh` / `slw` | Most recent Swing High and Swing Low |
| `eqb` | Equilibrium price (midpoint between Swing High and Swing Low) |

### Volume & Activity

| Column | Description |
| :--- | :--- |
| `rvol` | Relative Volume (current volume vs. 20-day average) |
| `vspk` | Volume Spike — true if volume > 2× average |
| `vtrd` | Volume Trend (Increasing / Decreasing) |
| `ascr` | Activity Score (Price × Volume / 10M) — measures ₹ liquidity |
| `arnk` | Activity Rank across all processed symbols |

### Chart Patterns

| Column | Description |
| :--- | :--- |
| `mpat` | Main pattern detected (e.g., Cup and Handle, Double Bottom) |
| `pcon` | Pattern Confidence score (0–99) |
| `patt` | All detected patterns with confidence scores |
| `xpat` | Secondary / background patterns |
| `ppnt` | Pivot points (Date@Price) defining the pattern structure |
| `psta` / `pend` | Pattern start and end dates |

---

## 🛠️ Usage Workflow

### 📡 Operating the Core Engine (`main.py`)

`main.py` is your database manager and snapshot generator. Follow the menus in order:

1. **Menu 1 — Fetch**: Initial setup or downloading historical blocks.
   - Input a start/end date or a "years back" value (e.g., `3.0`) to build `raw_data.csv`.
2. **Menu 2 — Update**: Your daily maintenance tool.
   - Checks the last date in your CSV and fetches only the missing data up to today.
3. **Menu 3 — Adjust**: Run when a corporate action is detected.
   - Scans `raw_data.csv` for price gaps caused by splits or bonuses. Mathematically adjusts historical prices and generates `data.csv`. Without this, SMAs and RSI will be inaccurate.
4. **Menu 4 — Analyze**: The signal generator.
   - Enter a date range (or press Enter for the latest).
   - Choose whether to run CPU-intensive Pattern Recognition.
   - Outputs `snapshot.csv` (or `snapshot_all.csv`).

### 📊 Snapshot Sample Preview

| Date | Symbol | Close | Stage | MT_Zone | RSI | Trend | Pattern |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-06-04 | HDFCBANK | 754.20 | Stage 4 | Discount | 43.79 | Sideways | Broadening Formation |
| 2026-06-04 | RELIANCE | 1303.70 | Stage 4 | Discount | 35.78 | Sideways | Cup and Handle |
| 2026-06-04 | TEJASNET | 601.95 | Stage 1/3 | Premium | 77.95 | Uptrend | Double Bottom |

### 📄 Full CSV Column Order

```
date,symb,clos,stge,wrsi,ws30,volu,DlPer,rvol,vspk,ascr,arnk,chan,g200,zone,MT_Zone,
rsi,delt,bbup,vtrd,bbbw,bbsq,g050,g020,adx,CMF_20,SUPERT_7_3.0,SUPERTd_7_3.0,
STOCHk_14_3_3,STOCHd_14_3_3,EMA_21,SQZ_ON,SQZ_OFF,SQZ_NO,WILLR_14,EFI_13,RSI_2,
open,bbdn,shgh,slw,high,low,eqb,s020,s050,s100,s200,h52h,l52l,vrnk,rrnk,tren,tstr,
vola,mpat,pcon,psta,pend,ppnt,xpat,patt,obv,sect
```

### 🔍 Screening and Filtering

Once snapshots are generated, use the secondary tools directly or run `analyzer.py` to trigger all at once.

**Run Screener** (Top 10 Intraday + Swing picks):
```bash
python screen_stocks.py 04-06-26snapshot_all.csv
```

**Analyze Sectors** (institutional rotation filter):
```bash
python sectoralanalysis.py 04-06-26snapshot_all.csv
```

**SMA Filter** (tightening SMA setups):
```bash
python sma_filter.py
```

**Run All At Once**:
```bash
python analyzer.py
```

---

### 📋 `screen_stocks.py` Logic

Reads your snapshot CSV and produces two ranked lists: **Intraday candidates** and **Weekly Swing candidates**.

Filename pattern: `DD-MM-YYsnapshot.csv` (date auto-parsed for display)
Run: `python screen_stocks.py [path/to/snapshot.csv]`

| Mode | Primary Hard Filters | Key Scoring Weights |
| :--- | :--- | :--- |
| **Intraday** | Stage 2, RSI 45–72, ADX > 18, RVol > 0.8, ascr ≥ 20 | RVol (×25), logAscr (×5), BBBW Contraction (15), EMA21 Proximity Bonus |
| **Swing** | Stage 2, wRSI 50–75, Delivery > 35%, ADX > 18, Uptrend | Strong Trend (15), BB Squeeze (10), RSI2 Pullback Bonus, Tiered Delivery Scoring |

Both modes include scoring from new indicators: **Supertrend direction**, **CMF** (money flow), **Squeeze ON**, **Stochastic setup**, **WILLR pullback**, and **EFI** (buying force).

Dual-timeframe confluence — symbols appearing in **both** lists — are flagged as highest-conviction picks.

---

### 🟢 Excel Formatting (`formatter.py`)

Turns raw CSV data into a visually intuitive heat-map of market signals.

**Usage:**
```bash
# Manual — specify file
python formatter.py path/to/your_snapshot.csv

# Automatic — auto-detects latest *snapshot.csv in directory
python formatter.py
```

**Key Features:**
- **Booleans**: Highlights `bbup`, `vspk`, `g200`, `bbsq`, etc. automatically.
- **Trend Alignment**: Color codes `tren` (Direction) and `tstr` (Strength).
- **Range Analysis**: Validates `rsi`, `wrsi`, and Stochastics against ideal entry/exit zones.
- **Contrarian Highlighting**: Flags `zone` (Discount/Premium) and `delt` (52W distance) for mean-reversion or breakout setups.

**Multi-Sheet Architecture:**
- **Main Analysis** — Primary dashboard with frozen headers and auto-adjusted column widths.
- **Chart Patterns** — Separates verbose pattern data (`psta`, `pend`, `ppnt`) to keep the main view clean.
- **Legend** — Embedded guide explaining every color rule and condition.

**Visual Standards:**

| Color | Meaning |
| :--- | :--- |
| Light Green `#C6EFCE` | Bullish / Signal Active |
| Light Red `#FFC7CE` | Bearish / Signal Inactive |
| Dark Green `#375623` + White Text | Extreme bullish condition |
| Dark Red `#9C0006` + White Text | Extreme bearish condition |
| Blue `#0070C0` + White Text | Overbought / Strongest momentum |
| Yellow `#FFEB84` | Neutral / Transitional |

---

## 📁 Repository Structure

```
stockanalyzerV6/
│
├── main.py                  # V6 Core Engine — data management + snapshot generation
├── analyzer.py              # Orchestrator — runs full post-analysis pipeline
├── formatter.py             # Visualization — Excel heatmap reports
├── screen_stocks.py         # Screener — Intraday + Swing ranking engine
├── sectoralanalysis.py      # RRG — Sector rotation + institutional filtering
├── sma_filter.py            # SMA confluence detector
├── montecarlo.py            # Risk management + Nifty/VIX simulations
│
├── stockanalyzer/           # Internal package
│   ├── __init__.py
│   ├── config.py            # Global settings and file paths
│   ├── utils.py             # Logging, input helpers
│   ├── data.py              # NSE data fetching, standardization, split adjustment
│   ├── analysis.py          # Main analysis orchestration loop
│   ├── indicators.py        # All technical indicators (pandas-ta)
│   ├── patterns.py          # Structural pattern recognition engine
│   ├── weinstein.py         # Weinstein Stage classification
│   └── pattern_cache.py     # Symbol-state hash cache for pattern results
│
├── tests/                   # Unit tests
├── symbols.csv              # Nifty 500 symbol list with sectors
├── symbolsall.csv           # Broader market symbol list
├── requirements.txt
└── .gitignore               # Includes .pattern_cache/
```

---

## 📋 Notes

- **`.pattern_cache/`** is listed in `.gitignore` and is never committed to the repository. It is generated locally on first Mode 4 run with patterns enabled.
- `raw_data.csv` and `data.csv` are also excluded from version control. Generate them locally via Mode 1 → Mode 3.
- The `Updater` folder is in development/testing phase — do not use in production.

---

*Disclaimer: This tool is for educational and analytical purposes only. Trading involves significant risk.*
