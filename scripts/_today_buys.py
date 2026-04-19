import sqlite3
from datetime import datetime, timezone, timedelta

SGT = timezone(timedelta(hours=8))
now_sgt = datetime.now(SGT)
today_sgt = now_sgt.strftime('%Y-%m-%d')

print(f"Today (SGT): {today_sgt}   Now (SGT): {now_sgt.strftime('%H:%M:%S')}\n")

conn = sqlite3.connect('data/paper_trading.db')
conn.row_factory = sqlite3.Row

# All open positions
rows = conn.execute(
    'SELECT pair, entry_price, usd_value, take_profit_pct, stop_loss_pct, opened_at FROM paper_positions ORDER BY opened_at'
).fetchall()

bought_today = []
other_open = []
for r in rows:
    dt = datetime.fromisoformat(r['opened_at'])
    dt_sgt = dt.astimezone(SGT)
    entry = dict(r)
    entry['_sgt'] = dt_sgt
    if dt_sgt.strftime('%Y-%m-%d') == today_sgt:
        bought_today.append(entry)
    else:
        other_open.append(entry)

print(f"=== Bought TODAY ({today_sgt} SGT) - {len(bought_today)} open position(s) ===")
if bought_today:
    for e in bought_today:
        t = e['_sgt']
        print(f"  {e['pair']:15s}  entry=${e['entry_price']:.4f}  cost=${e['usd_value']:.2f}  TP={e['take_profit_pct']}%  SL={e['stop_loss_pct']}%  @ {t.strftime('%H:%M')} SGT")
else:
    print("  (none)")

print(f"\n=== Older open positions ({len(other_open)}) ===")
for e in other_open:
    t = e['_sgt']
    print(f"  {e['pair']:15s}  entry=${e['entry_price']:.4f}  cost=${e['usd_value']:.2f}  TP={e['take_profit_pct']}%  opened {t.strftime('%Y-%m-%d %H:%M')} SGT")

# Closed trades opened today
rows2 = conn.execute(
    'SELECT pair, entry_price, usd_invested, opened_at, closed_at, pnl_pct, exit_reason FROM paper_trades ORDER BY opened_at DESC LIMIT 50'
).fetchall()

closed_today = []
for r in rows2:
    dt = datetime.fromisoformat(r['opened_at'])
    dt_sgt = dt.astimezone(SGT)
    if dt_sgt.strftime('%Y-%m-%d') == today_sgt:
        closed_today.append((r, dt_sgt))

print(f"\n=== Bought & closed today ({len(closed_today)}) ===")
if closed_today:
    for r, dt_sgt in closed_today:
        print(f"  {r['pair']:15s}  entry=${r['entry_price']:.4f}  cost=${r['usd_invested']:.2f}  pnl={r['pnl_pct']:.2f}%  reason={r['exit_reason']}  @ {dt_sgt.strftime('%H:%M')} SGT  closed={r['closed_at']}")
else:
    print("  (none)")

conn.close()
