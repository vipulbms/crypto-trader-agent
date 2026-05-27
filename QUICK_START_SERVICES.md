# Kryptos Services — Quick Start Guide

## TL;DR

```bash
# Start everything
./scripts/manage_services.sh start

# Check status
./scripts/manage_services.sh status

# Restart everything
./scripts/manage_services.sh restart

# View logs
./scripts/manage_services.sh logs all 50

# Auto-heal with monitoring (run in background)
./scripts/healthcheck.sh --auto-restart --telegram &
```

---

## Common Commands

| Task | Command |
|------|---------|
| **Start all services** | `./scripts/manage_services.sh start` |
| **Stop all services** | `./scripts/manage_services.sh stop` |
| **Restart everything** | `./scripts/manage_services.sh restart` |
| **Check status** | `./scripts/manage_services.sh status` |
| **View all logs** | `./scripts/manage_services.sh logs all 50` |
| **View audit log** | `./scripts/manage_services.sh logs audit_agent 100` |
| **Check for errors** | `./scripts/manage_services.sh verify` |
| **Auto-heal (background)** | `./scripts/healthcheck.sh --auto-restart --telegram` |

---

## What Gets Started?

✅ **Core Agent** — Main trading loop  
✅ **AuditAgent** — Cycle and trade logging  
✅ **DataCollector** — Market data feeds  
✅ **ResearchAnalyst** — Market analysis  
✅ **FulfillmentService** — Order execution  
✅ **MCP Server** — HTTP tool API  

---

## Logs Location

All logs go to: `logs/`

| Service | Log File |
|---------|----------|
| Core Agent | `logs/core_agent.log` |
| Audit Agent | `logs/audit_agent.log` |
| Data Collector | `logs/data_collector.log` |
| Research Analyst | `logs/research_analyst.log` |
| Fulfillment Service | `logs/fulfillment_service.log` |
| MCP Server | `logs/mcp_server.log` |
| Health Checks | `logs/healthcheck.log` |

---

## Setup for Production

### Option A: Simple (Check manually)
```bash
# Start services
./scripts/manage_services.sh start

# Check periodically
./scripts/manage_services.sh status
./scripts/manage_services.sh verify
```

### Option B: Monitored (Auto-restart on failure)
```bash
# Run health check in background with auto-restart
./scripts/healthcheck.sh --auto-restart --telegram &

# Or via cron for scheduled monitoring (every 5 min)
# crontab -e
# */5 * * * * cd /path/to/repo && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/healthcheck.log 2>&1
```

### Option C: Scheduled Restart (Daily clean restart)
```bash
# Daily restart at 2:00 AM
# crontab -e
# 0 2 * * * cd /path/to/repo && ./scripts/manage_services.sh restart >> logs/cron-restart.log 2>&1
```

---

## Troubleshooting

### Services won't start?
```bash
# Check what's happening
./scripts/manage_services.sh verify

# View startup logs
./scripts/manage_services.sh logs all 100

# Check for port conflicts
lsof -i :8092
```

### Core agent not running?
```bash
# Check PID file
cat data/kryptos.pid

# Check core agent log
tail -50 logs/core_agent.log

# Try manual restart
./scripts/manage_services.sh stop
sleep 5
./scripts/manage_services.sh start
```

### Seeing errors in logs?
```bash
# Find all errors in all logs
grep -i "error\|exception\|failed" logs/*.log | tail -20

# Focus on a specific service
./scripts/manage_services.sh logs audit_agent 200 | grep -i "error"
```

---

## Health Monitoring (Background)

Run automatic health checks with auto-restart:

```bash
# Start monitoring in background
nohup ./scripts/healthcheck.sh --auto-restart --telegram > logs/monitor.log 2>&1 &

# Check the health check log
tail -50 logs/healthcheck.log

# If services fail, they'll auto-restart (up to 3 attempts)
# You'll get Telegram alerts if configured
```

---

## Cron Setup (5-Minute Health Checks)

```bash
crontab -e

# Add this line (replace /path/to/repo with actual path):
*/5 * * * * cd /path/to/repo && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/healthcheck.log 2>&1
```

Verify:
```bash
crontab -l
tail logs/healthcheck.log
```

---

## Performance Notes

- **Startup time:** ~5-10 seconds for all services
- **Memory:** ~300-500MB for all services combined
- **Health check:** ~2 seconds per run
- **Log rotation:** Configure in `config.yaml` storage section

---

## Questions?

See full documentation: `docs/SERVICE_MANAGEMENT.md`

Or check service logs for error details:
```bash
./scripts/manage_services.sh logs [service_name] 100
```
