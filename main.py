import pandas as pd
import os
from datetime import datetime, timedelta
from stockanalyzer.config import CONFIG
from stockanalyzer.utils import setup_logging, get_input
from stockanalyzer.data import load_symbols, fetch_data, standardize_data, adjust_prices
from stockanalyzer.analysis import perform_technical_analysis

def main():
    logger = setup_logging(verbose=True)
    try:
        print("\nSelect Market Universe:")
        print("1. Nifty 500 (Default)")
        print("2. Broader Market")
        universe_choice = get_input("Choice (1,2 or Enter): ").strip()
        
        suffix = ""
        if universe_choice == '2':
            suffix = "_all"
            CONFIG['SYMBOLS_FILE'] = CONFIG['SYMBOLS_FILE'].replace('symbols.csv', 'symbolsall.csv')
            CONFIG['RAW_DATA_FILE'] = CONFIG['RAW_DATA_FILE'].replace('.csv', '_all.csv')
            CONFIG['ADJUSTED_DATA_FILE'] = CONFIG['ADJUSTED_DATA_FILE'].replace('.csv', '_all.csv')

        symbols, sector_df, _ = load_symbols(CONFIG['SYMBOLS_FILE'])
        if not symbols:
            logger.error("No symbols loaded")
            return

        print("\nChoose Operation Mode:\n1. Fetch\n2. Update\n3. Adjust\n4. Analyze (Default)")
        choice = get_input("Choice (1-4, default 4 or Q to quit): ").strip() or '4'

        raw_data = pd.DataFrame()
        if choice == '1':
            print("\nFetch Mode:")
            print("1. Custom Dates ")
            print("2. Years Back ")
            date_choice = input("Enter choice (1,2): ").strip()
            if date_choice == '1':
                start = datetime.strptime(input("Start (DD-MM-YYYY): "), '%d-%m-%Y')
                end = datetime.strptime(input("End (DD-MM-YYYY): "), '%d-%m-%Y')
                raw_data = fetch_data(symbols, start, end, logger)
            elif date_choice == '2':
                end = datetime.strptime(input("End (DD-MM-YYYY): "), '%d-%m-%Y')
                days_back = int(float(input("Years back: ")) * 365)
                raw_data = fetch_data(symbols, end - timedelta(days=days_back), end, logger)

        elif choice == '2':
            if not os.path.exists(CONFIG['RAW_DATA_FILE']):
                print(f"[ERROR] {CONFIG['RAW_DATA_FILE']} not found. Run Option 1 first.")
                return
            
            existing = standardize_data(pd.read_csv(CONFIG['RAW_DATA_FILE']), logger=logger)
            to_date = datetime.now()
            tasks = []
            min_from = to_date
            for s in symbols:
                last = existing[existing['symbols'] == s]['datetime'].max()
                f = last + timedelta(1) if pd.notna(last) else to_date - timedelta(CONFIG['DEFAULT_LOOKBACK_DAYS'])
                if f.date() <= to_date.date():
                    tasks.append(s); min_from = min(min_from, f)
            if tasks:
                new = fetch_data(tasks, min_from, to_date, logger)
                if not new.empty:
                    raw_data = pd.concat([existing, new]).drop_duplicates(['symbols', 'datetime'], keep='last')

        elif choice == '3':
            if not os.path.exists(CONFIG['RAW_DATA_FILE']):
                print(f"[ERROR] {CONFIG['RAW_DATA_FILE']} not found. Run Option 1 or 2 first.")
                return
            raw_data = standardize_data(pd.read_csv(CONFIG['RAW_DATA_FILE']), logger=logger)

        elif choice == '4':
            if not os.path.exists(CONFIG['ADJUSTED_DATA_FILE']):
                print(f"[ERROR] Adjusted data file missing: {CONFIG['ADJUSTED_DATA_FILE']}")
                print(">>> Please run Option 3 (Adjust) first to generate this file.")
                return
            
            from stockanalyzer.pattern_cache import cache_stats
            stats = cache_stats()
            print(f"[CACHE] {stats['symbols_cached']} symbols cached | {stats['total_size_kb']:.0f} KB")

            adj = standardize_data(pd.read_csv(CONFIG['ADJUSTED_DATA_FILE']), logger=logger)
            date_input = get_input("Enter date range (DD-MM-YYYY to DD-MM-YYYY) or Enter for latest: ").strip()
            chart_choice = get_input("Enable Chart Pattern analysis? Default is Y (Y/n): ").strip().lower()
            enable = chart_choice in ['y', 'yes', '']

            if 'to' in date_input:
                start_str, end_str = [d.strip() for d in date_input.split('to')]
                for d in pd.date_range(datetime.strptime(start_str, '%d-%m-%Y'), datetime.strptime(end_str, '%d-%m-%Y')):
                    mask = adj['datetime'] <= d
                    if not adj[mask].empty and (adj['datetime'] == d).any():
                        analysis_df = perform_technical_analysis(adj[mask], sector_df, enable)
                        if not analysis_df.empty:
                            outfile = f"{d.strftime('%d-%m-%y')}snapshot{suffix}.csv"
                            analysis_df.to_csv(outfile, index=False)
                            print(f"[SUCCESS] Saved {outfile}")
            else:
                if not date_input:
                    latest_dt = adj['datetime'].max()
                    print(f"[INFO] Loading latest available date: {latest_dt.strftime('%d-%m-%Y')}")
                else:
                    adj = adj[adj['datetime'] <= datetime.strptime(date_input, '%d-%m-%Y')]
                
                analysis_df = perform_technical_analysis(adj, sector_df, enable)
                if not analysis_df.empty:
                    outfile = f"{pd.to_datetime(analysis_df['date']).max().strftime('%d-%m-%y')}snapshot{suffix}.csv"
                    analysis_df.to_csv(outfile, index=False)
                    print(f"[SUCCESS] Analysis complete. Saved to {outfile}")
                else:
                    print("[WARN] No analysis results. Ensure your data has at least 20 days of history per symbol.")
            return

        if choice in ['1', '2', '3'] and not raw_data.empty:
            raw_data.to_csv(CONFIG['RAW_DATA_FILE'], index=False)
            print(f"[INFO] Saved raw data. Processing split adjustments...")
            adj, splits = adjust_prices(raw_data)
            adj.to_csv(CONFIG['ADJUSTED_DATA_FILE'], index=False)
            splits.to_csv(CONFIG['SPLITS_LOG_FILE'], index=False)
            print(f"[SUCCESS] Adjusted data saved to {CONFIG['ADJUSTED_DATA_FILE']}")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()