#!/bin/bash
# Start Kryptos core trading agent plus runtime support services.
# Run this from the repo root: ./scripts/start_all_agents.sh
# Ensure your Python virtualenv is activated first.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="$(which python3)"
CONFIG="config.yaml"
DB="paper_trading.db"
LOG_DIR="$(python3 - <<'PY'
import yaml, os
cfg = yaml.safe_load(open('config.yaml'))
print(cfg.get('storage', {}).get('log_dir', '/logs'))
PY)"

mkdir -p "$LOG_DIR"

echo "Starting Kryptos trading agent in PAPER mode..."
python3 kryptos.py start --paper

# Optional auxiliary runtimes
echo "Starting DataCollector..."
nohup "$PYTHON" -m src.runtime.data_collector --config "$CONFIG" --db "$DB" > "$LOG_DIR/data_collector.log" 2>&1 &

echo "Starting ResearchAnalyst..."
nohup "$PYTHON" -m src.runtime.research_analyst --config "$CONFIG" --db "$DB" > "$LOG_DIR/research_analyst.log" 2>&1 &

echo "Starting AuditAgent..."
nohup "$PYTHON" -m src.runtime.audit_agent --config "$CONFIG" --db "$DB" > "$LOG_DIR/audit_agent.log" 2>&1 &

# Fulfillment service is optional; useful if you want the HTTP fill API.
echo "Starting FulfillmentService..."
nohup "$PYTHON" -m src.runtime.fulfillment_service --config "$CONFIG" --mode paper > "$LOG_DIR/fulfillment_service.log" 2>&1 &

# MCP tool server is optional but useful for internal tool queries.
echo "Starting MCP server..."
nohup "$PYTHON" -m src.mcp.server --config "$CONFIG" > "$LOG_DIR/mcp_server.log" 2>&1 &

printf "\nStarted core agent + auxiliary services.\n"
printf "Check log files in %s for each service.\n" "$LOG_DIR"
printf "Use data/kryptos.pid to confirm the trading agent PID, and run `python kryptos.py status` for core status.\n"
