# Agent Management

Kryptos runs multiple agents in parallel:

1. **Trading Agent** — LLM-driven decision cycle for all pairs
2. **Data Collector** — Continuous WebSocket + REST price feed aggregation
3. **Research Analyst** — RAA universe proposal evaluation
4. **Audit Agent** — Outcome tracking, HITL lock, pump detection
5. **Fulfillment Service** — Order execution and SL/TP monitoring
6. **MCP Server** — HTTP interface for external tool calls

## Managing Agents

Use `scripts/manage_agents.py` for unified control:

### Start all agents (paper mode, default)
```bash
python3 scripts/manage_agents.py start
```

### Start all agents in live mode
```bash
python3 scripts/manage_agents.py start --mode live
```

### Start specific agents
```bash
python3 scripts/manage_agents.py start --agents trading,collector,mcp
```

### Stop all agents gracefully (10s timeout, then SIGKILL)
```bash
python3 scripts/manage_agents.py stop
```

### Force-kill agents immediately
```bash
python3 scripts/manage_agents.py stop --force
```

### Restart all agents (useful after config changes)
```bash
python3 scripts/manage_agents.py restart
```

### Check agent status
```bash
python3 scripts/manage_agents.py status
```

Output example:
```
Agent Status:
────────────────────────────────────────────────────────────────────────────────
  Trading Agent                  🟢 RUNNING   (PID 12345)
  Data Collector                 🟢 RUNNING   (PID 12346)
  Research Analyst               🔴 STOPPED   
  Audit Agent                    🟢 RUNNING   (PID 12347)
  Fulfillment Service            🟢 RUNNING   (PID 12348)
  MCP Server                     🟢 RUNNING   (PID 12349)
────────────────────────────────────────────────────────────────────────────────
Total: 5/6 running
```

## Agent Details

### Trading Agent
- **Script**: `main.py`
- **Mode**: paper (virtual) or live (real Kraken)
- **Modes**: `--mode paper` or `--mode live`
- **Log**: `logs/trading.log`

### Data Collector
- **Script**: `src/runtime/data_collector.py`
- **Purpose**: Streams OHLCV candles and order book snapshots from Kraken WS v2
- **Log**: `logs/collector.log`
- **HTTP Endpoint**: http://127.0.0.1:9100/health

### Research Analyst
- **Script**: `src/runtime/research_analyst.py`
- **Purpose**: LLM-powered universe expansion decisions
- **Log**: `logs/analyst.log`

### Audit Agent
- **Script**: `src/runtime/audit_agent.py`
- **Purpose**: Post-trade outcome tracking and HITL lock management
- **Log**: `logs/auditor.log`

### Fulfillment Service
- **Script**: `src/runtime/fulfillment_service.py`
- **Purpose**: Real-time SL/TP monitoring and partial TP execution
- **Log**: `logs/fulfillment.log`

### MCP Server
- **Script**: `src/mcp/server.py`
- **Purpose**: HTTP interface for Claude Code and external tools
- **Endpoint**: http://127.0.0.1:8092
- **Log**: `logs/mcp.log`

## Agent State & Persistence

- **PID tracking**: `data/agents.json`
- **Each agent logs to**: `logs/{agent_key}.log` (rotated at 100 MB × 5 files)
- **Graceful shutdown**: SIGTERM with 10s wait, then SIGKILL
- **Restart safety**: Old PIDs cleaned from `agents.json` if process no longer running

## Common Patterns

### Daily restart (maintenance)
```bash
python3 scripts/manage_agents.py restart --mode paper
```

### Selective restart (after updating research_analyst)
```bash
python3 scripts/manage_agents.py stop --agents analyst
sleep 2
python3 scripts/manage_agents.py start --agents analyst
```

### Emergency stop
```bash
python3 scripts/manage_agents.py stop --force
```

### Monitor in real time
```bash
while true; do
  clear
  python3 scripts/manage_agents.py status
  sleep 5
done
```

## Troubleshooting

### Agent exits immediately
Check the log: `tail -f logs/{agent}.log`

### Stale PID file after crash
`scripts/manage_agents.py` auto-cleans stale PIDs on status check.

### Port already in use (MCP)
```bash
lsof -i :8092  # find process using port 8092
kill -9 <PID>
```

### Data Collector HTTP endpoint failing
```bash
curl http://127.0.0.1:9100/health
```

## Architecture Notes

- All agents run in separate processes (detached sessions)
- Agents communicate via SQLite (`paper_trading.db`, `audit.db`)
- Config is read once at startup; restart required for config changes
- Logs use rotating file handlers (100 MB × 5 files per agent)
