
import urllib.request
import json
import time
import pandas as pd
import numpy as np

# Try importing ta library
try:
    import ta
    HAS_TA = True
except ImportError:
    HAS_TA = False
    print("WARNING: ta library not found, will compute indicators manually")

PAIRS = {
    'BTC/USD':  'XBTUSD',
    'ETH/USD':  'ETHUSD',
    'BNB/USD':  'BNBUSD',
    'SOL/USD':  'SOLUSD',
    'XRP/USD':  'XRPUSD',
    'TRX/USD':  'TRXUSD',
    'DOGE/USD': 'XDGUSD',
    'ADA/USD':  'ADAUSD',
    'LTC/USD':  'LTCUSD',
    'AVAX/USD': 'AVAXUSD',
    'SUI/USD':  'SUIUSD',
    'HYPE/USD': 'HYPEUSD',
    'UNI/USD':  'UNIUSD',
    'INJ/USD':  'INJUSD',
}

def fetch_ohlcv(kraken_pair, interval=60):
    url = f"https://api.kraken.com/0/public/OHLC?pair={kraken_pair}&interval={interval}&since=0"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        if data.get('error'):
            print(f"  API error for {kraken_pair}: {data['error']}")
            return None
        result = data.get('result', {})
        # Find the actual key (not 'last')
        key = [k for k in result.keys() if k != 'last']
        if not key:
            return None
        candles = result[key[0]]
        df = pd.DataFrame(candles, columns=['time','open','high','low','close','vwap','volume','count'])
        for col in ['open','high','low','close','vwap','volume']:
            df[col] = pd.to_numeric(df[col])
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.sort_values('time').reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  Exception fetching {kraken_pair}: {e}")
        return None

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period-1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period-1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def compute_atr(df, period=14):
    high = df['high']
    low = df['low']
    close = df['close']
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(com=period-1, min_periods=period).mean()
    return atr

def compute_bollinger(series, period=20, std=2):
    mid = series.rolling(period).mean()
    s = series.rolling(period).std()
    upper = mid + std * s
    lower = mid - std * s
    return upper, mid, lower

def compute_macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, min_periods=fast).mean()
    ema_slow = series.ewm(span=slow, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def analyze(pair_name, kraken_pair):
    print(f"\nFetching {pair_name} ({kraken_pair})...")
    df = fetch_ohlcv(kraken_pair)
    if df is None:
        return None
    
    # Use last 720 candles
    df = df.tail(720).reset_index(drop=True)
    n = len(df)
    print(f"  Got {n} candles, range: {df['time'].iloc[0]} to {df['time'].iloc[-1]}")
    
    close = df['close']
    
    # RSI
    if HAS_TA:
        rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
    else:
        rsi = compute_rsi(close, 14)
    
    rsi_valid = rsi.dropna()
    rsi_pct = {
        '<30': (rsi_valid < 30).mean() * 100,
        '<35': (rsi_valid < 35).mean() * 100,
        '<40': (rsi_valid < 40).mean() * 100,
        '<45': (rsi_valid < 45).mean() * 100,
        '>55': (rsi_valid > 55).mean() * 100,
        '>60': (rsi_valid > 60).mean() * 100,
        '>65': (rsi_valid > 65).mean() * 100,
        '>70': (rsi_valid > 70).mean() * 100,
    }
    
    # ATR as % of price
    atr = compute_atr(df, 14)
    atr_valid = atr.dropna()
    close_aligned = close[atr_valid.index]
    atr_pct = (atr_valid / close_aligned * 100).mean()
    
    # Bollinger Bands
    if HAS_TA:
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_lower = bb.bollinger_lband()
        bb_mid = bb.bollinger_mavg()
    else:
        _, bb_mid, bb_lower = compute_bollinger(close, 20, 2)
    
    bb_valid_mask = bb_lower.notna()
    bb_lower_v = bb_lower[bb_valid_mask]
    bb_mid_v = bb_mid[bb_valid_mask]
    close_bb = close[bb_valid_mask]
    
    # "touches" lower band: price <= lower band
    bb_lower_touch = (close_bb <= bb_lower_v).mean() * 100
    # price below middle band
    bb_below_mid = (close_bb <= bb_mid_v).mean() * 100
    
    # MACD histogram
    _, _, macd_hist = compute_macd(close)
    macd_valid = macd_hist.dropna()
    macd_pos = (macd_valid > 0).mean() * 100
    macd_neg = (macd_valid <= 0).mean() * 100
    
    return {
        'pair': pair_name,
        'n_candles': n,
        'rsi_pct': rsi_pct,
        'atr_pct': atr_pct,
        'bb_lower_touch_pct': bb_lower_touch,
        'bb_below_mid_pct': bb_below_mid,
        'macd_pos_pct': macd_pos,
        'macd_neg_pct': macd_neg,
        'rsi_mean': rsi_valid.mean(),
        'rsi_median': rsi_valid.median(),
    }

results = {}
for pair_name, kraken_pair in PAIRS.items():
    result = analyze(pair_name, kraken_pair)
    if result:
        results[pair_name] = result
    time.sleep(0.5)  # be polite to API

print("\n\n" + "="*100)
print("ANALYSIS RESULTS - LAST 720 HOURLY CANDLES (30 DAYS)")
print("="*100)

# RSI percentile table
print("\n--- RSI(14) DISTRIBUTION (% of time) ---")
header = f"{'Pair':<12} | {'<30':>6} | {'<35':>6} | {'<40':>6} | {'<45':>6} | {'>55':>6} | {'>60':>6} | {'>65':>6} | {'>70':>6} | {'Mean':>6} | {'Median':>6}"
print(header)
print("-" * len(header))
for pair, r in results.items():
    rp = r['rsi_pct']
    print(f"{pair:<12} | {rp['<30']:>5.1f}% | {rp['<35']:>5.1f}% | {rp['<40']:>5.1f}% | {rp['<45']:>5.1f}% | "
          f"{rp['>55']:>5.1f}% | {rp['>60']:>5.1f}% | {rp['>65']:>5.1f}% | {rp['>70']:>5.1f}% | "
          f"{r['rsi_mean']:>5.1f}  | {r['rsi_median']:>5.1f}")

print("\n--- ATR% OF PRICE & BOLLINGER BAND TOUCH FREQUENCY ---")
header2 = f"{'Pair':<12} | {'ATR%':>7} | {'BB Lower Touch':>14} | {'BB Below Mid':>12}"
print(header2)
print("-" * len(header2))
for pair, r in results.items():
    print(f"{pair:<12} | {r['atr_pct']:>6.3f}% | {r['bb_lower_touch_pct']:>13.1f}% | {r['bb_below_mid_pct']:>11.1f}%")

print("\n--- MACD(12,26,9) HISTOGRAM DISTRIBUTION ---")
header3 = f"{'Pair':<12} | {'MACD Hist > 0':>13} | {'MACD Hist <= 0':>14}"
print(header3)
print("-" * len(header3))
for pair, r in results.items():
    print(f"{pair:<12} | {r['macd_pos_pct']:>12.1f}% | {r['macd_neg_pct']:>13.1f}%")

print("\n--- RECOMMENDED RSI THRESHOLDS & SIGNAL SCORING ASSESSMENT ---")
print(f"{'Pair':<12} | {'Oversold Rec':>12} | {'Overbought Rec':>14} | {'BB Lower Touch':>14} | {'MACD Pos%':>9} | {'BUY Score>=4 Realistic?':>23}")
print("-" * 100)

for pair, r in results.items():
    rp = r['rsi_pct']
    # Choose oversold threshold so ~5-10% of candles qualify (meaningful but not too rare)
    # Check levels: <30, <35, <40
    if rp['<30'] >= 5:
        oversold = 30
    elif rp['<35'] >= 5:
        oversold = 35
    elif rp['<40'] >= 5:
        oversold = 40
    else:
        oversold = 45
    
    # Choose overbought threshold so ~10-20% qualify
    if rp['>70'] >= 10:
        overbought = 70
    elif rp['>65'] >= 10:
        overbought = 65
    elif rp['>60'] >= 10:
        overbought = 60
    else:
        overbought = 55
    
    # BUY score: RSI<oversold (+3) + BB lower touch (+3) + MACD hist>0 (+2) >= 4
    # For score >= 4: need at least RSI<thresh (+3) + MACD>0 (+2) = 5, or
    # BB lower touch (+3) + MACD>0 (+2) = 5
    # Probability of RSI<oversold AND MACD>0 (assuming independence):
    rsi_prob = rp[f'<{oversold}'] / 100
    bb_prob = r['bb_lower_touch_pct'] / 100
    macd_prob = r['macd_pos_pct'] / 100
    
    # P(score >= 4):
    # RSI alone = 3 pts, need +1 more: BB or MACD
    # BB alone = 3 pts, need +1 more: RSI or MACD
    # MACD alone = 2 pts, need +2 more: RSI or BB
    # Combinations (assuming rough independence):
    p_rsi_macd = rsi_prob * macd_prob  # 5 pts
    p_bb_macd = bb_prob * macd_prob    # 5 pts
    p_rsi_bb = rsi_prob * bb_prob      # 6 pts
    p_all = rsi_prob * bb_prob * macd_prob  # 8 pts
    # P(score>=4) ~ P(RSI+MACD) + P(BB+MACD) + P(RSI+BB) - overlaps
    p_score4 = p_rsi_macd + p_bb_macd + p_rsi_bb - 2*p_all
    
    realistic = "YES" if p_score4 >= 0.01 else ("MARGINAL" if p_score4 >= 0.005 else "RARELY")
    
    print(f"{pair:<12} | {oversold:>12} | {overbought:>14} | {r['bb_lower_touch_pct']:>13.1f}% | "
          f"{r['macd_pos_pct']:>8.1f}% | {realistic:>23} (~{p_score4*100:.1f}% of candles)")

print("\n--- SIGNAL SCORING SYSTEM ASSESSMENT ---")
print("""
The current scoring logic: RSI < threshold = +3pts, BB lower touch = +3pts, MACD hist > 0 = +2pts
BUY signal requires score >= 4.

Key observations:
- Score >= 4 can be triggered by: RSI+MACD (5pts), BB+MACD (5pts), RSI+BB (6pts), or all three (8pts)
- BB lower band touches happen ~2-5% of the time (by statistical definition of 2-sigma bands)
- RSI oversold (<35) happens ~5-15% of the time depending on pair volatility
- MACD positive happens ~40-60% of the time (near coin-flip)

The scoring thresholds are ASYMMETRIC: 
- RSI oversold (+3) is a rare but strong signal
- BB lower touch (+3) is also rare (~2-5%)
- MACD positive (+2) is frequent but weak alone (only 2pts, needs another signal)
- Combined rare events make BUY signals infrequent but meaningful
""")
