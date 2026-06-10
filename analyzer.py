import os
import sys
import glob
import pandas as pd
from datetime import datetime, timedelta
import re

# Import existing modules
import formatter
import sectoralanalysis
import screen_stocks

def resolve_targets():
    """Replicates the interactive prompt logic to identify files for processing."""
    print("Choose snapshot source:")
    print("1. snapshot.csv")
    print("2. snapshot_all.csv")
    choice = input("Enter choice [default 1]: ").strip()

    if choice == '2':
        suffix_flag = "_all"
        pattern = "*snapshot_all.csv"
    else:
        suffix_flag = ""
        pattern = "*snapshot.csv"

    print("\nOptions: press Enter to latest data, enter a specific date (DD-MM-YYYY),")
    print("a range (DD-MM-YYYY to DD-MM-YYYY), or a custom filename.")
    user_input = input("Target: ").strip()

    targets = []

    if not user_input:
        all_files = glob.glob(pattern)
        if choice != '2':
            all_files = [f for f in all_files if not f.endswith("_all.csv")]
        
        # Only include files that follow the dated pattern (DD-MM-YY or DD-MM-YYYY)
        # This ignores generic files like 'snapshot.csv'
        files = [f for f in all_files if re.match(r"^\d{2}-\d{2}-\d{2,4}", os.path.basename(f))]

        if not files:
            print(f"No files matching {pattern} found.")
            sys.exit(1)

        def get_file_date(fname):
            name = os.path.basename(fname)
            try:
                # Try parsing as DD-MM-YY (8 chars)
                return datetime.strptime(name[:8], "%d-%m-%y")
            except ValueError:
                try:
                    # Try parsing as DD-MM-YYYY (10 chars)
                    return datetime.strptime(name[:10], "%d-%m-%Y")
                except ValueError:
                    return datetime.fromtimestamp(0) # Push invalid names to bottom

        files.sort(key=get_file_date)
        targets.append(files[-1])

    elif "to" in user_input:
        try:
            start_str, end_str = [d.strip() for d in user_input.split('to')]
            curr = datetime.strptime(start_str, '%d-%m-%Y')
            end_dt = datetime.strptime(end_str, '%d-%m-%Y')
            while curr <= end_dt:
                fname = f"{curr.strftime('%d-%m-%y')}snapshot{suffix_flag}.csv"
                if os.path.exists(fname):
                    targets.append(fname)
                curr += timedelta(days=1)
        except Exception as e:
            print(f"Error parsing date range: {e}")
            sys.exit(1)

    elif os.path.exists(user_input):
        targets.append(user_input)

    else:
        try:
            dt = datetime.strptime(user_input, '%d-%m-%Y')
            fname = f"{dt.strftime('%d-%m-%y')}snapshot{suffix_flag}.csv"
            if os.path.exists(fname):
                targets.append(fname)
            else:
                print(f"File {fname} not found.")
                sys.exit(1)
        except ValueError:
            print(f"Invalid input: {user_input}")
            sys.exit(1)

    return targets, suffix_flag

def run_sma_confluence(file_path, threshold_pct, output_dir="."):
    """Integrated SMA filter logic."""
    df = pd.read_csv(file_path)
    df.columns = df.columns.str.strip()
    sma_cols = ['s020', 's050', 's100', 's200', 'symb']
    df_clean = df.dropna(subset=sma_cols).copy()
    threshold = threshold_pct / 100

    def is_confluence(row):
        s200 = row['s200']
        if s200 == 0: return False
        return (abs(row['s020'] - s200) / s200 <= threshold and
                abs(row['s050'] - s200) / s200 <= threshold and
                abs(row['s100'] - s200) / s200 <= threshold)

    matching = df_clean[df_clean.apply(is_confluence, axis=1)]
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    out_file = os.path.join(output_dir, f"confluence_{base_name.replace('snapshot', '')}.csv")
    matching[['symb']].drop_duplicates().to_csv(out_file, index=False)
    print(f"   [SMA] {len(matching)} symbols saved to {out_file}")

def main():
    print("="*60)
    print("🚀 NSE MASTER ANALYZER SUITE")
    print("="*60)

    targets, suffix = resolve_targets()
    
    threshold_input = input("\nEnter SMA threshold % [default 2]: ").strip()
    sma_threshold = float(threshold_input if threshold_input else 2.0)

    if not targets:
        print("No valid files identified.")
        return

    for csv_path in targets:
        print(f"\n{'─'*60}")
        print(f"📂 PROCESSING: {csv_path}")
        print(f"{'─'*60}")

        # Extract date for folder naming (DD-MM-YYYY)
        fname_base = os.path.basename(csv_path)
        try:
            # Try parsing as DD-MM-YY (e.g. 09-06-26)
            dt_obj = datetime.strptime(fname_base[:8], "%d-%m-%y")
        except ValueError:
            try:
                # Try parsing as DD-MM-YYYY (e.g. 09-06-2026)
                dt_obj = datetime.strptime(fname_base[:10], "%d-%m-%Y")
            except ValueError:
                dt_obj = datetime.now()
        
        folder_name = dt_obj.strftime("%d-%m-%Y") + suffix
        os.makedirs(folder_name, exist_ok=True)

        # 1. Excel Formatter
        print("\n1/4. Generating Formatted Excel...")
        formatter.colorize_snapshot(csv_path)
        # Move the generated xlsx into the date folder
        original_xlsx = csv_path.replace('.csv', '.xlsx')
        if os.path.exists(original_xlsx):
            os.replace(original_xlsx, os.path.join(folder_name, os.path.basename(original_xlsx)))

        # 2. Sectoral Analysis
        print("\n2/4. Running Sectoral RRG & Filtering...")
        try:
            snap = sectoralanalysis.load_snapshot(csv_path)
            sectors = sectoralanalysis.get_sector_rankings(snap, csv_path)
            candidates, steps = sectoralanalysis.build_candidates(snap, sectors)
            report_name = f"sector_report_{os.path.splitext(os.path.basename(csv_path))[0]}.xlsx"
            report_path = os.path.join(folder_name, report_name)
            with pd.ExcelWriter(report_path, engine='openpyxl') as writer:
                candidates.to_excel(writer, sheet_name="Swing Candidates", index=False)
                sectors.to_excel(writer, sheet_name="Sector RRG Snapshot", index=False)
            sectoralanalysis.apply_corporate_styling(report_path)
            print(f"   [Sector] Report saved: {report_path}")
        except Exception as e:
            print(f"   [ERROR] Sectoral Analysis failed: {e}")

        # 3. Stock Screener (Intraday & Swing Picks)
        print("\n3/4. Running Stock Screener...")
        df = screen_stocks.load_csv(csv_path)
        intraday, pool_i = screen_stocks.screen_intraday(df, screen_stocks.INTRADAY_CFG)
        swing, pool_s = screen_stocks.screen_swing(df, screen_stocks.SWING_CFG)
        
        snap_date = screen_stocks.parse_date_from_filename(csv_path)
        screener_out = os.path.join(folder_name, f"picks_{snap_date.replace(' ', '_')}{suffix}.xlsx")
        screen_stocks.apply_professional_formatting(screener_out, pd.concat([intraday.assign(screener_type="Intraday"), swing.assign(screener_type="Swing")], ignore_index=True))
        print(f"   [Screener] Picks saved: {screener_out}")

        # 4. SMA Filter
        print("\n4/4. Running SMA Confluence Filter...")
        run_sma_confluence(csv_path, sma_threshold, folder_name)

    print(f"\n\n✅ COMPLETED: All {len(targets)} snapshot(s) analyzed.")

if __name__ == "__main__":
    main()