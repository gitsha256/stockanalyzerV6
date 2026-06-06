import numpy as np
import datetime
import yfinance as yf

# ============== MANUAL INPUT ==============
def fetch_live_market_data():
    try:
        print("Attempting to fetch live data...")
        nifty = yf.Ticker("^NSEI")
        vix = yf.Ticker("^INDIAVIX")
        
        def get_last_price(ticker_obj):
            # Try fast_info first
            price = ticker_obj.fast_info.get('last_price')
            if price is None or np.isnan(price) or price <= 0:
                # Fallback to last close if market is closed or API returns None
                hist = ticker_obj.history(period='5d')
                price = hist['Close'].iloc[-1] if not hist.empty else None
            return price

        return round(get_last_price(nifty), 2), round(get_last_price(vix), 2)
    except Exception as e:
        return None, None

live_nifty, live_vix = fetch_live_market_data()

s0_input = input(f"Enter current Nifty price [{live_nifty or 'Required'}]: ").strip()
S0 = float(s0_input) if s0_input else (live_nifty if live_nifty else 0.0)

vix_input = input(f"Enter India VIX [{live_vix or 'Required'}]: ").strip()
india_vix = float(vix_input) if vix_input else (live_vix if live_vix else 0.0)

# ============== SETTINGS ==============
risk_free      = 0.068   # update monthly
days_to_expiry = int(input("Days to expiry (1 or 2)   : "))
capital        = 100000
risk_per_trade = 0.030
LOT_SIZE       = 65

print(f"\nNifty: {S0:.0f} | VIX: {india_vix}% | Days: {days_to_expiry}")

# ============== SANITY CHECKS ==============
if not (10000 <= S0 <= 35000):
    print("[WARNING] Nifty price looks suspicious. Verify.")
if not (10 <= india_vix <= 60):
    print("[WARNING] VIX looks unusual. Verify.")

# ===================== 1-MIN SCALPING SIZING =====================
minutes_per_year   = 252 * 375
sigma_1min         = (india_vix / 100) / np.sqrt(minutes_per_year)
expected_1min_move = S0 * sigma_1min
stop_distance      = 2 * expected_1min_move
max_risk           = capital * risk_per_trade
cost_per_lot       = stop_distance * LOT_SIZE

print(f"\n--- 1-Min Scalping ---")
print(f"Expected move (±1σ) : ±{expected_1min_move:.1f} pts")
print(f"2σ Stop Distance    : {stop_distance:.1f} pts")
print(f"Risk per lot (₹)    : ₹{cost_per_lot:.0f}")

if cost_per_lot == 0:
    print("[ERROR] Stop distance is zero. Check inputs.")
else:
    lot_qty = max(int(max_risk / cost_per_lot), 0)
    print(f"Max lots for {risk_per_trade*100}% risk : {lot_qty} lot(s)")
    if lot_qty == 0:
        min_capital = cost_per_lot / risk_per_trade
        print(f"[INFO] Need ₹{min_capital:,.0f} capital to trade 1 lot safely.")

# ===================== INTRADAY MONTE CARLO =====================
now = datetime.datetime.now()
target_time = now.replace(hour=15, minute=0, second=0, microsecond=0)

if now.time() < datetime.time(9, 15):
    mins_remaining = 345 # 9:15 to 15:00
elif now >= target_time:
    mins_remaining = 0
else:
    mins_remaining = int((target_time - now).total_seconds() / 60)

n_sim = 10000
dt_intra = 1 / (252 * 375)
sigma = india_vix / 100

if mins_remaining > 0:
    Z_intra = np.random.normal(0, 1, (n_sim, mins_remaining))
    log_ret_intra = (risk_free - 0.5 * sigma**2) * dt_intra + sigma * np.sqrt(dt_intra) * Z_intra
    paths_intra = S0 * np.exp(np.cumsum(log_ret_intra, axis=1))
    final_intra = paths_intra[:, -1]

    intra_var_5 = np.percentile(final_intra, 5)
    intra_var_95 = np.percentile(final_intra, 95)
    print(f"\n--- Intraday Monte Carlo ({mins_remaining} mins left until 15:00) ---")
    print(f"Prob Bullish (Intraday): {(final_intra > S0).mean()*100:.1f}%")
    print(f"Expected Range (90%)   : {intra_var_5:.0f} to {intra_var_95:.0f}")
else:
    print(f"\n--- Intraday Monte Carlo ---")
    print("Trading window (until 15:00) has closed.")

# ===================== WEEKLY MONTE CARLO =====================
dt    = 1 / 252
sigma = india_vix / 100

np.random.seed(42)
Z           = np.random.normal(0, 1, (n_sim := 10000, days_to_expiry))
log_returns = (risk_free - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z
paths       = S0 * np.exp(np.cumsum(log_returns, axis=1))

final_prices = paths[:, -1]
prob_up      = (final_prices > S0).mean() * 100
prob_down    = 100 - prob_up
var_5        = np.percentile(final_prices, 5)
var_95       = np.percentile(final_prices, 95)
median       = np.median(final_prices)
mean         = final_prices.mean()
std_dev      = final_prices.std()

print(f"\n--- Weekly Monte Carlo ({days_to_expiry} days, {n_sim:,} simulations) ---")
print(f"Probability ends HIGHER : {prob_up:.1f}%")
print(f"Probability ends LOWER  : {prob_down:.1f}%")
print(f"Median expected level   : {median:.0f}")
print(f"Mean expected level     : {mean:.0f}")
print(f"Std Dev of outcomes     : ±{std_dev:.0f} pts")
print(f"5%  worst-case (VaR)    : {var_5:.0f}  (down {S0-var_5:.0f} pts)")
print(f"95% best-case           : {var_95:.0f} (up   {var_95-S0:.0f} pts)")

# ===================== REWARD:RISK SUMMARY =====================
upside   = var_95 - S0
downside = S0 - var_5
rr_ratio = upside / downside if downside != 0 else 0

print(f"\n--- Trade Setup Summary ---")
print(f"Upside (95th pct)   : +{upside:.0f} pts")
print(f"Downside (5th pct)  : -{downside:.0f} pts")
print(f"Reward:Risk Ratio   : {rr_ratio:.2f}")

if rr_ratio >= 1.5:
    print("Bias : ✅ BULLISH setup  (R:R favourable)")
elif rr_ratio <= 0.67:
    print("Bias : 🔴 BEARISH setup  (R:R favours downside)")
else:
    print("Bias : ⚪ NEUTRAL / no clear edge")

# ===================== CAPITAL GUIDE =====================
min_cap_1lot = cost_per_lot / risk_per_trade
print(f"\n--- Capital Guide ---")
print(f"Min capital for 1 lot : ₹{min_cap_1lot:,.0f}")