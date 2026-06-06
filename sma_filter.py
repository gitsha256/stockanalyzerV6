import pandas as pd
import glob
import os
import sys
import re
from datetime import datetime, timedelta

# Resolve the snapshot CSV path
# 1. Ask for snapshot type
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

# 2. Ask for data target
print("\nOptions: press Enter to latest data, enter a specific date (DD-MM-YYYY),")
print("a range (DD-MM-YYYY to DD-MM-YYYY), or a custom filename.")
user_input = input("Target: ").strip()

targets = []

if not user_input:
    all_files = glob.glob(pattern)
    if choice != '2':
        all_files = [f for f in all_files if not f.endswith("_all.csv")]
    
    files = [f for f in all_files if re.match(r"^\d{2}-\d{2}-\d{2,4}", os.path.basename(f))]

    if not files:
        print(f"No files matching {pattern} found in current directory.")
        sys.exit(1)

    # Sort by the date embedded in the filename (DD-MM-YY)
    def get_file_date(fname):
        name = os.path.basename(fname)
        try:
            return datetime.strptime(name[:8], "%d-%m-%y")
        except ValueError:
            try:
                return datetime.strptime(name[:10], "%d-%m-%Y")
            except ValueError:
                return datetime.fromtimestamp(0)

    files.sort(key=get_file_date)
    targets.append(files[-1])

elif "to" in user_input:
    # Handle range
    try:
        start_str, end_str = [d.strip() for d in user_input.split('to')]
        start_dt = datetime.strptime(start_str, '%d-%m-%Y')
        end_dt = datetime.strptime(end_str, '%d-%m-%Y')
        
        curr = start_dt
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
    # Try as single date
    try:
        dt = datetime.strptime(user_input, '%d-%m-%Y')
        fname = f"{dt.strftime('%d-%m-%y')}snapshot{suffix_flag}.csv"
        if os.path.exists(fname):
            targets.append(fname)
        else:
            print(f"File {fname} not found.")
            sys.exit(1)
    except ValueError:
        print(f"Invalid input format or file not found: {user_input}")
        sys.exit(1)

if not targets:
    print("No valid snapshot files identified to process.")
    sys.exit(1)

threshold_input = input("Enter the percent threshold (e.g., 5 for 5%) [default 5]: ").strip()
threshold = (float(threshold_input) if threshold_input else 5.0) / 100

for latest_file in targets:
    print(f"\n[INFO] Processing {latest_file}...")
    df = pd.read_csv(latest_file)

    # Drop rows with missing SMA or symbol values
    sma_cols = ['s020', 's050', 's100', 's200', 'symb']
    df_clean = df.dropna(subset=sma_cols).copy()

    def all_near(row):
        sma200 = row['s200']
        if sma200 == 0:
            return False
        return (
            abs(row['s020'] - sma200) / sma200 <= threshold and
            abs(row['s050'] - sma200) / sma200 <= threshold and
            abs(row['s100'] - sma200) / sma200 <= threshold
        )

    matching = df_clean[df_clean.apply(all_near, axis=1)]

    # Save unique symbols to file
    base_name = os.path.splitext(os.path.basename(latest_file))[0]
    out_file = f"confluence_{base_name.replace('snapshot', '')}.csv"
    matching[['symb']].drop_duplicates().to_csv(out_file, index=False)
    
    print(f"Rows after dropna: {len(df_clean)}")
    print(f"Rows matching SMA confluence: {len(matching)}")
    print(f"Symbols saved to: {out_file}")
    print(matching[['symb']].drop_duplicates().to_string(index=False))