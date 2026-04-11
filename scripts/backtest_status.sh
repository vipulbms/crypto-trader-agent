#!/usr/bin/env bash
# backtest_status.sh — print current backtest progress, P&L, and positions
#
# Usage:
#   ./scripts/backtest_status.sh                        # text summary only
#   ./scripts/backtest_status.sh --charts               # text + per-trade PNG charts
#   ./scripts/backtest_status.sh --charts --pair ETH/USD   # filter to one pair
#   ./scripts/backtest_status.sh --charts --out charts/backtest   # custom output dir
#   ./scripts/backtest_status.sh <audit.db> <paper.db>  # custom DB paths
#
# Closes #101

# ── Argument parsing ──────────────────────────────────────────────────────────
SHOW_CHARTS=0
CHART_PAIR=""
CHART_OUT="charts/backtest"
POSITIONAL=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --charts)     SHOW_CHARTS=1; shift ;;
    --pair)       CHART_PAIR="$2"; shift 2 ;;
    --out)        CHART_OUT="$2";  shift 2 ;;
    *)            POSITIONAL+=("$1"); shift ;;
  esac
done

AUDIT_DB="${POSITIONAL[0]:-data/backtest_audit.db}"
PAPER_DB="${POSITIONAL[1]:-data/backtest_paper.db}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

if [ ! -f "$AUDIT_DB" ]; then echo "Audit DB not found: $AUDIT_DB"; exit 1; fi
if [ ! -f "$PAPER_DB" ]; then echo "Paper DB not found: $PAPER_DB"; exit 1; fi

echo -e "\n${BOLD}${CYAN}━━━━━━━━━━━━━━━━━━━━━━  BACKTEST STATUS  ━━━━━━━━━━━━━━━━━━━━━━${RESET}"

# ── Cycles ────────────────────────────────────────────────────────────────────
echo -e "\n${BOLD}CYCLES${RESET}"
sqlite3 "$AUDIT_DB" "
SELECT
  COUNT(*)                          AS total_cycles,
  MIN(cycle_at)                     AS first_cycle,
  MAX(cycle_at)                     AS last_cycle
FROM audit_cycles;" | awk -F'|' '{
  printf "  Total   : %s\n  From    : %s\n  To      : %s\n", $1, $2, $3
}'

# ── Wallet ─────────────────────────────────────────────────────────────────────
CASH=$(sqlite3 "$PAPER_DB" "SELECT cash_usd FROM paper_wallet ORDER BY id DESC LIMIT 1;")

# ── Open positions ─────────────────────────────────────────────────────────────
echo -e "\n${BOLD}OPEN POSITIONS${RESET}"
OPEN_VALUE=$(sqlite3 "$PAPER_DB" "SELECT ROUND(SUM(usd_value),2) FROM paper_positions;")
sqlite3 "$PAPER_DB" "
SELECT pair, opened_at, ROUND(usd_value,2), entry_price, stop_loss_pct, take_profit_pct
FROM paper_positions
ORDER BY opened_at;" | awk -F'|' '
BEGIN { printf "  %-12s %-32s %10s %12s %6s %6s\n", "PAIR","OPENED AT","USD","ENTRY","SL%","TP%" }
      { printf "  %-12s %-32s %10s %12s %6s %6s\n", $1, $2, $3, $4, $5, $6 }'

OPEN_COUNT=$(sqlite3 "$PAPER_DB" "SELECT COUNT(*) FROM paper_positions;")

# ── Portfolio summary ──────────────────────────────────────────────────────────
TOTAL=$(echo "$CASH + $OPEN_VALUE" | bc 2>/dev/null || echo "n/a")
echo -e "\n${BOLD}PORTFOLIO${RESET}"
printf "  Cash          : \$%s\n" "$CASH"
printf "  Open positions: \$%s  (%s positions)\n" "$OPEN_VALUE" "$OPEN_COUNT"
printf "  Total value   : \$%s\n" "$TOTAL"

# ── Closed trades ──────────────────────────────────────────────────────────────
echo -e "\n${BOLD}CLOSED TRADES${RESET}"
TRADE_COUNT=$(sqlite3 "$PAPER_DB" "SELECT COUNT(*) FROM paper_trades;")

if [ "$TRADE_COUNT" -eq 0 ]; then
  echo "  No closed trades yet."
else
  sqlite3 "$PAPER_DB" "
  SELECT
    pair,
    opened_at,
    closed_at,
    ROUND(usd_invested,2),
    ROUND(entry_price,4),
    ROUND(exit_price,4),
    ROUND(pnl_usd,2),
    ROUND(pnl_pct,2),
    exit_reason
  FROM paper_trades
  ORDER BY closed_at;" | awk -F'|' '
  BEGIN { printf "  %-12s %-22s %-22s %8s %10s %10s %8s %7s  %s\n",
    "PAIR","OPENED","CLOSED","USD","ENTRY","EXIT","PNL$","PNL%","REASON" }
  {
    pnl = $7+0
    color = (pnl >= 0) ? "\033[0;32m" : "\033[0;31m"
    reset = "\033[0m"
    printf "  %-12s %-22s %-22s %8s %10s %10s %s%8s%s %6s%%  %s\n",
      $1,$2,$3,$4,$5,$6,color,$7,reset,$8,$9
  }'

  echo ""
  # P&L summary
  sqlite3 "$PAPER_DB" "
  SELECT
    COUNT(*)                                            AS trades,
    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END)      AS wins,
    SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END)      AS losses,
    ROUND(SUM(pnl_usd),2)                               AS total_pnl,
    ROUND(AVG(pnl_pct),2)                               AS avg_pnl_pct
  FROM paper_trades;" | awk -F'|' '{
    printf "  Trades: %s  |  Wins: %s  Losses: %s  |  Total P&L: $%s  |  Avg: %s%%\n",
      $1,$2,$3,$4,$5 }'

  echo -e "\n${BOLD}  EXIT REASON BREAKDOWN${RESET}"
  sqlite3 "$PAPER_DB" "
  SELECT exit_reason, COUNT(*) as cnt, ROUND(SUM(pnl_usd),2) as pnl
  FROM paper_trades GROUP BY exit_reason ORDER BY cnt DESC;" | awk -F'|' '{
    printf "    %-20s  %3s trades   \$%s\n", $1, $2, $3 }'

  echo -e "\n${BOLD}  PER-PAIR BREAKDOWN${RESET}"
  sqlite3 "$PAPER_DB" "
  SELECT pair, COUNT(*) as trades,
    SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(pnl_usd),2) as pnl,
    ROUND(AVG(pnl_pct),2) as avg_pct
  FROM paper_trades GROUP BY pair ORDER BY pnl DESC;" | awk -F'|' '{
    printf "    %-12s  %3s trades  %3s wins  \$%s  avg %s%%\n", $1,$2,$3,$4,$5 }'
fi

echo -e "\n${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RESET}\n"

# ── Per-trade charts (optional) ───────────────────────────────────────────────
if [ "$SHOW_CHARTS" -eq 1 ]; then
  echo -e "${BOLD}${CYAN}GENERATING CHARTS  →  $CHART_OUT/${RESET}"

  PAIR_ARG=""
  if [ -n "$CHART_PAIR" ]; then
    PAIR_ARG="pair_filter='$CHART_PAIR',"
  fi

  python3 - <<PYEOF
import sys, os
sys.path.insert(0, os.getcwd())
from src.reports.chart_generator import generate_charts
paths = generate_charts(
    db_path='$PAPER_DB',
    out_dir='$CHART_OUT',
    history_dir='history',
    $PAIR_ARG
)
if paths:
    print(f"\nCharts written ({len(paths)}):")
    for p in paths:
        print(f"  {p}")
else:
    print("No charts generated.")
PYEOF
fi
