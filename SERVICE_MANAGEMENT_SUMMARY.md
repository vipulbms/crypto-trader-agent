# Service Management Scripts — Complete Summary

## What Was Created

Three new tools have been added to manage Kryptos services:

### 1. **manage_services.sh** — Lifecycle Management
**Location:** `scripts/manage_services.sh`

Complete service orchestration with error checking. Handles starting, stopping, restarting, and verifying all 6 services.

**Key Features:**
- Graceful shutdown (30-second timeout before force kill)
- Process verification after startup
- Log error scanning (detects ERROR, EXCEPTION, TRACEBACK, FAILED)
- Color-coded status output
- Service activity monitoring

**Quick Usage:**
```bash
./scripts/manage_services.sh start      # Start all + verify
./scripts/manage_services.sh restart    # Stop/start/verify
./scripts/manage_services.sh status     # Show current state
./scripts/manage_services.sh verify     # Check health
./scripts/manage_services.sh logs audit_agent 50
```

---

### 2. **healthcheck.sh** — Continuous Monitoring
**Location:** `scripts/healthcheck.sh`

Automatic health monitoring with optional auto-restart for production resilience.

**Key Features:**
- Monitors all 6 services are running
- Detects log inactivity (indicates stalled services)
- Scans for critical errors (CRITICAL, FATAL, database lock)
- Auto-restart capability (with cooldown + attempt limits)
- Telegram alerts (optional)
- Health check audit log

**Quick Usage:**
```bash
./scripts/healthcheck.sh                              # Report only
./scripts/healthcheck.sh --auto-restart               # Auto-heal
./scripts/healthcheck.sh --auto-restart --telegram    # With alerts
```

**For Background Monitoring:**
```bash
# Run every 5 minutes via cron
*/5 * * * * cd /path/to/repo && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/healthcheck.log 2>&1
```

---

### 3. **Documentation**

#### SERVICE_MANAGEMENT.md
Complete reference guide covering:
- All command options
- Workflows (startup, daily restart, troubleshooting)
- Environment setup
- Systemd integration (optional)
- Advanced configuration

#### QUICK_START_SERVICES.md
Handy one-page reference with:
- Common commands table
- What gets started
- Log file locations
- Troubleshooting quick fixes
- Production setup options

#### CRON_EXAMPLES.sh
Pre-made cron configurations for:
- Basic health checks (every 5 min)
- Auto-restart on failure
- Telegram notifications
- Daily service restarts
- Weekly log rotation

---

## Services Managed

| Service | Entry Point | Status File |
|---------|------------|------------|
| **Core Agent** | `kryptos.py start --paper` | `data/kryptos.pid` |
| **AuditAgent** | `src.runtime.audit_agent` | Process list |
| **DataCollector** | `src.runtime.data_collector` | Process list |
| **ResearchAnalyst** | `src.runtime.research_analyst` | Process list |
| **FulfillmentService** | `src.runtime.fulfillment_service` | Process list |
| **MCP Server** | `src.mcp.server` | Process list |

All logs go to `logs/` directory (configurable in `config.yaml`).

---

## Usage Examples

### Basic Startup
```bash
# Start all services
./scripts/manage_services.sh start

# Expected output:
# [INFO] Starting Kryptos trading agent and support services...
# [OK] Core agent started
# [OK] DataCollector started
# [OK] ResearchAnalyst started
# [OK] AuditAgent started
# [OK] FulfillmentService started
# [OK] MCP server started
# [OK] All services started successfully
```

### Check Status
```bash
./scripts/manage_services.sh status

# Shows: Core agent PID, all auxiliary service status, log file count
```

### Verify and Fix Issues
```bash
./scripts/manage_services.sh verify

# Shows: Process status, log activity, any errors found
# Exit code 0 = healthy, 1 = problems detected
```

### View Logs
```bash
# View last 50 lines of audit agent log
./scripts/manage_services.sh logs audit_agent 50

# View all logs (last 20 lines each)
./scripts/manage_services.sh logs all 20

# Check for errors
./scripts/manage_services.sh logs all 100 | grep -i error
```

### Auto-Healing (Production)
```bash
# Run health check with auto-restart and Telegram alerts
./scripts/healthcheck.sh --auto-restart --telegram

# Or run in background
nohup ./scripts/healthcheck.sh --auto-restart --telegram > logs/monitor.log 2>&1 &

# Or via cron (automatic)
crontab -e
# Add: */5 * * * * cd /path/to/repo && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/healthcheck.log 2>&1
```

---

## Exit Codes

**manage_services.sh:**
- `0` = Success (services running, no errors)
- `1` = Services running but errors detected in logs

**healthcheck.sh:**
- Outputs status to stdout: `HEALTHY`, `RESTARTED`, `UNHEALTHY`, `RESTART_FAILED`
- Also logs to `logs/healthcheck.log` with timestamps

---

## Error Detection

The scripts automatically detect and report:

| Error Type | Detection | Action |
|-----------|-----------|--------|
| **Missing process** | pgrep fails | Service marked as stopped |
| **Log inactivity** | No recent log updates | Service marked as stalled (healthcheck) |
| **Critical errors** | "CRITICAL" in logs | Logged and reported |
| **Fatal errors** | "FATAL" in logs | Logged and reported |
| **Database lock** | "SQLiteDatabase is locked" | Logged and reported |
| **Parse errors** | Exception/Traceback in logs | Logged and reported |

Example error output:
```
[ERROR] Found errors in audit_agent.log:
  2026-05-19 10:32:15,123 ERROR: Failed to insert cycle record
  Traceback (most recent call last):
    File "audit_logger.py", line 45, in log_cycle
      raise DatabaseError("Connection timeout")
```

---

## Production Configuration

### Minimum (Manual checks)
```bash
# Once per day, manually check
./scripts/manage_services.sh status
./scripts/manage_services.sh verify
```

### Recommended (Automatic monitoring)
```bash
# Cron job: health check every 5 minutes with auto-restart
*/5 * * * * cd /path/to/repo && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/healthcheck.log 2>&1

# Cron job: daily clean restart
0 2 * * * cd /path/to/repo && ./scripts/manage_services.sh restart >> logs/cron-restart.log 2>&1
```

### Advanced (Full resilience)
```bash
# 5-minute health checks with auto-restart
*/5 * * * * cd /path/to/repo && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/healthcheck.log 2>&1

# Daily 2 AM restart (clean slate)
0 2 * * * cd /path/to/repo && ./scripts/manage_services.sh restart >> logs/cron-restart.log 2>&1

# Status snapshot at 9 AM and 6 PM
0 9,18 * * * cd /path/to/repo && ./scripts/manage_services.sh status >> logs/status.log 2>&1

# Weekly log compression (Sundays 3 AM)
0 3 * * 0 cd /path/to/repo && gzip logs/*.log 2>/dev/null; true
```

---

## Log Files

### Service Logs
- `logs/core_agent.log` — Main trading loop
- `logs/audit_agent.log` — Cycle and trade logging
- `logs/data_collector.log` — Market data collection
- `logs/research_analyst.log` — Market analysis
- `logs/fulfillment_service.log` — Order execution
- `logs/mcp_server.log` — HTTP API

### Management Logs
- `logs/healthcheck.log` — Health check audit trail
- `logs/cron-healthcheck.log` — Cron job health checks
- `logs/cron-restart.log` — Cron job restarts
- `logs/cron-status.log` — Cron job status snapshots

### View Recent Activity
```bash
tail -100 logs/audit_agent.log          # Recent cycles
tail -100 logs/healthcheck.log          # Recent health checks
grep ERROR logs/*.log | tail -20        # All recent errors
```

---

## Troubleshooting

### Services won't start
```bash
# 1. Check what's wrong
./scripts/manage_services.sh verify

# 2. View startup output
./scripts/manage_services.sh logs core_agent 100

# 3. Look for specific errors
grep -i error logs/core_agent.log

# 4. Check Python environment
python3 --version
python3 -c "import yaml" && echo "YAML OK"

# 5. Manual restart
./scripts/manage_services.sh stop
sleep 5
./scripts/manage_services.sh start
```

### Services run but produce errors
```bash
# 1. Scan all logs
./scripts/manage_services.sh verify

# 2. View detailed logs
./scripts/manage_services.sh logs all 200

# 3. Check specific service
./scripts/manage_services.sh logs audit_agent 500 | grep -A5 ERROR
```

### Auto-restart isn't working
```bash
# 1. Check health check log
tail -100 logs/healthcheck.log

# 2. Verify cron job
crontab -l

# 3. Test manually
./scripts/healthcheck.sh --auto-restart

# 4. Check system logs
# macOS: log stream --predicate 'process == "cron"' --level debug
# Linux: journalctl -u cron --since today
```

---

## Key Features Summary

✅ **Automated service management** — Start, stop, restart all services  
✅ **Health monitoring** — Detect stuck/failed services  
✅ **Error detection** — Scan logs for problems  
✅ **Auto-recovery** — Restart failed services (with limits)  
✅ **Activity detection** — Know when services are stalled  
✅ **Telegram alerts** — Get notified of failures  
✅ **Graceful shutdown** — Services exit cleanly  
✅ **Color output** — Easy-to-read status reports  
✅ **Exit codes** — Integration with scripts/cron  
✅ **Production ready** — Handles edge cases and timeouts  

---

## Getting Started Now

### 1. Test the Scripts
```bash
# Check current status
./scripts/manage_services.sh status

# Try a restart
./scripts/manage_services.sh restart

# Check logs
./scripts/manage_services.sh logs all 20
```

### 2. Set Up Monitoring (Optional)
```bash
# For auto-healing, add to crontab:
crontab -e

# Add this line (replace /path):
*/5 * * * * cd /path/to/crypto-trader-agent && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/healthcheck.log 2>&1
```

### 3. Reference Documentation
- **Quick commands:** See `QUICK_START_SERVICES.md`
- **Full guide:** See `docs/SERVICE_MANAGEMENT.md`
- **Cron setup:** See `scripts/CRON_EXAMPLES.sh`

---

## Questions or Issues?

1. **Check logs:** `./scripts/manage_services.sh logs all 100`
2. **Read docs:** `docs/SERVICE_MANAGEMENT.md`
3. **Test manually:** `./scripts/healthcheck.sh`
4. **Check cron:** `crontab -l` and `logs/healthcheck.log`

All scripts are bash-only (no external dependencies beyond Python and standard Unix tools).
