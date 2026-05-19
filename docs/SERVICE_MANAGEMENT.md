# Kryptos Service Management Guide

This guide covers how to manage Kryptos services using the provided management and health check scripts.

## Overview

Kryptos consists of multiple services that need to be coordinated:

### Core Services
- **Core Agent** (`main.py` / `kryptos.py start`) — Main trading loop and decision engine
- **AuditAgent** (`src.runtime.audit_agent`) — Audit trail and cycle logging
- **DataCollector** (`src.runtime.data_collector`) — Real-time market data collection
- **ResearchAnalyst** (`src.runtime.research_analyst`) — Market analysis and research
- **FulfillmentService** (`src.runtime.fulfillment_service`) — Order execution interface
- **MCP Server** (`src.mcp.server`) — Tool introspection and HTTP API

## Scripts

### 1. manage_services.sh — Complete Service Lifecycle Management

**Location:** `scripts/manage_services.sh`

**Purpose:** Start, stop, restart, and verify all Kryptos services with error checking.

#### Usage

```bash
# Start all services and verify
./scripts/manage_services.sh start

# Stop all services gracefully
./scripts/manage_services.sh stop

# Stop and restart all services
./scripts/manage_services.sh restart

# Show status of all running services
./scripts/manage_services.sh status

# Check logs for errors
./scripts/manage_services.sh verify

# View logs
./scripts/manage_services.sh logs [service] [lines]
./scripts/manage_services.sh logs all 50
./scripts/manage_services.sh logs audit_agent 100
```

#### Commands

| Command | Description |
|---------|-------------|
| `start` | Start all services and verify they're healthy |
| `stop` | Stop all services gracefully with timeout |
| `restart` | Full stop/start cycle with verification |
| `status` | Display current service status without changes |
| `verify` | Check if services are running and scan logs for errors |
| `logs [service] [lines]` | Tail service logs (default: all services, 20 lines) |

#### Examples

```bash
# Check current status
./scripts/manage_services.sh status

# Restart with error checking
./scripts/manage_services.sh restart

# View last 50 lines of audit agent log
./scripts/manage_services.sh logs audit_agent 50

# View all logs (last 20 lines each)
./scripts/manage_services.sh logs all 20
```

#### Exit Codes

- `0` — Success (all services started/stopped successfully, no errors in logs)
- `1` — Services running but errors detected in logs or services failed to start

#### Features

✓ **Graceful shutdown** — Waits up to 30 seconds for processes to exit  
✓ **Force kill** — Force kills services that don't exit gracefully  
✓ **Log error detection** — Scans all log files for ERROR, EXCEPTION, TRACEBACK, FAILED  
✓ **Color-coded output** — Easy-to-read status reports  
✓ **Process verification** — Confirms services are running after start  
✓ **Timeout handling** — Respects service startup times  

### 2. healthcheck.sh — Continuous Service Monitoring

**Location:** `scripts/healthcheck.sh`

**Purpose:** Monitor service health and optionally auto-restart on failure.

#### Usage

```bash
# Run a health check (report only)
./scripts/healthcheck.sh

# Run health check with auto-restart on failure
./scripts/healthcheck.sh --auto-restart

# Run with Telegram alerts
./scripts/healthcheck.sh --telegram

# Run with both auto-restart and alerts
./scripts/healthcheck.sh --auto-restart --telegram
```

#### Features

✓ **Service process monitoring** — Confirms all services are running  
✓ **Activity detection** — Checks if services are actively producing logs  
✓ **Critical error detection** — Scans for CRITICAL, FATAL, database lock errors  
✓ **Auto-restart capability** — Restarts failed services automatically  
✓ **Restart throttling** — Prevents restart loops (5-minute cooldown between attempts)  
✓ **Restart limits** — Max 3 restart attempts before manual intervention  
✓ **Telegram alerts** — Notify via Telegram if services fail (optional)  
✓ **Health check log** — Records all checks in `logs/healthcheck.log`  

#### Continuous Monitoring Setup

To run health checks every 5 minutes via cron:

```bash
# Edit crontab
crontab -e

# Add this line to check every 5 minutes with auto-restart
*/5 * * * * cd /path/to/crypto-trader-agent && ./scripts/healthcheck.sh --auto-restart --telegram >> /tmp/healthcheck-cron.log 2>&1
```

#### Health Check Log

Health checks are logged to `logs/healthcheck.log` with timestamps:

```
[2026-05-19 14:32:15] Health check started at 2026-05-19 14:32:15
[2026-05-19 14:32:15] ✓ Core agent (PID: 12345) is running
[2026-05-19 14:32:15] ✓ Audit agent producing logs (active)
[2026-05-19 14:32:15] ✓ data_collector is running
[2026-05-19 14:32:15] ✓ All services healthy
[2026-05-19 14:32:15] Health check completed
```

#### Auto-Restart Behavior

When `--auto-restart` is enabled:

1. **First failure** — Immediately restart services
2. **Restart cooldown** — Wait 5 minutes before next restart attempt
3. **Attempt tracking** — Log shows attempt count (max 3)
4. **Manual intervention** — After 3 failures, requires manual restart
5. **Telegram alerts** — Notify on each restart attempt and result

## Common Workflows

### Initial Startup

```bash
# Activate Python virtualenv first
source venv/bin/activate

# Start all services
./scripts/manage_services.sh start

# Verify everything is running
./scripts/manage_services.sh status
```

### Daily Restart (Recommended)

```bash
# Gracefully restart all services daily
./scripts/manage_services.sh restart

# Check logs after restart
./scripts/manage_services.sh logs all 50
```

### Troubleshooting

```bash
# Get full status report
./scripts/manage_services.sh status

# Check for errors in all logs
./scripts/manage_services.sh verify

# View recent audit activity
./scripts/manage_services.sh logs audit_agent 100

# View core agent startup logs
./scripts/manage_services.sh logs core_agent 50

# If services won't restart, check individual service logs
cat logs/core_agent.log
cat logs/audit_agent.log
cat logs/data_collector.log
```

### Overnight Monitoring

```bash
# Set up cron job for health monitoring with auto-restart
crontab -e

# Add:
*/5 * * * * cd /path/to/crypto-trader-agent && ./scripts/healthcheck.sh --auto-restart --telegram

# View health check log periodically
tail -50 logs/healthcheck.log
```

## Service Locations and Logs

### Core Agent
- **Entry:** `python main.py --paper`
- **PID File:** `data/kryptos.pid`
- **Logs:** `logs/core_agent.log`

### Auxiliary Services
- **DataCollector** → `logs/data_collector.log`
- **AuditAgent** → `logs/audit_agent.log`
- **ResearchAnalyst** → `logs/research_analyst.log`
- **FulfillmentService** → `logs/fulfillment_service.log`
- **MCP Server** → `logs/mcp_server.log`

### Health Checks
- **Health Check Log** → `logs/healthcheck.log`

## Environment Requirements

- Python 3.11+ with virtualenv activated
- Bash 4.0+
- Standard Unix tools: `pgrep`, `kill`, `ps`, `grep`, `tail`
- `config.yaml` in repo root
- `data/` directory for PID files

## Troubleshooting

### Services Won't Start

1. **Check if ports are in use:**
   ```bash
   lsof -i :8092  # MCP server port
   ```

2. **Check Python environment:**
   ```bash
   python3 --version
   which python3
   python3 -m pip list | grep -i krypto
   ```

3. **Verify config:**
   ```bash
   python3 -c "import yaml; yaml.safe_load(open('config.yaml'))" && echo "Config OK"
   ```

4. **Check database:**
   ```bash
   sqlite3 data/paper_trading.db ".tables"
   ```

### Services Run But Produce Errors

1. **Check error logs:**
   ```bash
   ./scripts/manage_services.sh verify
   ```

2. **View service logs:**
   ```bash
   ./scripts/manage_services.sh logs [service_name] 100
   ```

3. **Look for specific errors:**
   ```bash
   grep -i "error\|exception" logs/*.log | tail -20
   ```

### Auto-Restart Not Working

1. **Check healthcheck log:**
   ```bash
   tail -50 logs/healthcheck.log
   ```

2. **Verify cron job:**
   ```bash
   crontab -l
   ```

3. **Test healthcheck manually:**
   ```bash
   ./scripts/healthcheck.sh --auto-restart --telegram
   ```

### Database Locked Error

This usually indicates concurrent access to the database.

1. **Check running processes:**
   ```bash
   ps aux | grep -i kryptos | grep -v grep
   ```

2. **Ensure only one core agent is running:**
   ```bash
   pgrep -f "main.py|kryptos.py start" | wc -l  # Should be 0 or 1
   ```

3. **Kill stuck processes if necessary:**
   ```bash
   ./scripts/manage_services.sh stop
   sleep 5
   ./scripts/manage_services.sh start
   ```

## Performance Tips

- **Run health checks every 5 minutes** for production monitoring
- **Restart services daily** to clear accumulated memory
- **Monitor logs** for patterns that precede failures
- **Set Telegram alerts** for immediate notification of failures
- **Keep logs rotation enabled** to prevent disk space issues

## Advanced Configuration

### Custom Service Timeout

Edit `manage_services.sh` and change:
```bash
SERVICE_TIMEOUT=30  # seconds to wait for graceful shutdown
```

### Custom Restart Cooldown

Edit `healthcheck.sh` and change:
```bash
RESTART_COOLDOWN=300  # seconds (5 minutes) between restart attempts
```

### Custom Log Directory

By default, services log to the directory specified in `config.yaml` under `storage.log_dir`. To override:

```bash
# Edit manage_services.sh or healthcheck.sh and set:
LOG_DIR="/custom/path/to/logs"
```

## Integration with Systemd (Optional)

For production environments, consider running services via systemd:

```bash
# Create systemd service file
sudo tee /etc/systemd/system/kryptos.service > /dev/null <<EOF
[Unit]
Description=Kryptos Trading Agent
After=network.target

[Service]
Type=forking
User=$USER
WorkingDirectory=/path/to/crypto-trader-agent
ExecStart=/path/to/crypto-trader-agent/scripts/manage_services.sh start
ExecStop=/path/to/crypto-trader-agent/scripts/manage_services.sh stop
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable kryptos
sudo systemctl start kryptos
sudo systemctl status kryptos
```

Then use systemd's built-in restart and health management instead of the healthcheck script.

## Questions / Issues?

If services fail to start or produce unexpected errors:

1. Run `./scripts/manage_services.sh verify` to get diagnostics
2. Check `logs/healthcheck.log` for auto-restart history
3. Review individual service logs in `logs/`
4. Check CLAUDE.md for known issues and gotchas
