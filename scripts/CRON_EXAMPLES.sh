#!/bin/bash
# Example Cron Jobs for Kryptos Service Management
#
# This file contains example cron configurations for automated service management.
# Copy these lines into your crontab (crontab -e) to set up automated monitoring.
#
# IMPORTANT: Replace /path/to/crypto-trader-agent with your actual repo path!

# ============================================================================
# OPTION 1: Basic Health Check Every 5 Minutes (Recommended for Production)
# ============================================================================
# Runs health check every 5 minutes, logs to file
*/5 * * * * cd /path/to/crypto-trader-agent && ./scripts/healthcheck.sh >> logs/cron-healthcheck.log 2>&1

# ============================================================================
# OPTION 2: Health Check with Auto-Restart (For Fault Tolerance)
# ============================================================================
# Runs health check every 5 minutes with automatic restart on failure
*/5 * * * * cd /path/to/crypto-trader-agent && ./scripts/healthcheck.sh --auto-restart >> logs/cron-healthcheck.log 2>&1

# ============================================================================
# OPTION 3: Health Check with Telegram Alerts (For Critical Monitoring)
# ============================================================================
# Runs health check every 5 minutes with Telegram notifications
# Requires: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in config.yaml
*/5 * * * * cd /path/to/crypto-trader-agent && ./scripts/healthcheck.sh --telegram >> logs/cron-healthcheck.log 2>&1

# ============================================================================
# OPTION 4: Full Monitoring with Auto-Restart and Telegram (Production)
# ============================================================================
# Most comprehensive: auto-restart + Telegram alerts + detailed logging
*/5 * * * * cd /path/to/crypto-trader-agent && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/cron-healthcheck.log 2>&1

# ============================================================================
# OPTIONAL: Daily Service Restart (Clean Restart at Midnight)
# ============================================================================
# Restart all services daily at 2:00 AM (helps prevent memory leaks)
0 2 * * * cd /path/to/crypto-trader-agent && ./scripts/manage_services.sh restart >> logs/cron-restart.log 2>&1

# ============================================================================
# OPTIONAL: Daily Status Report (Email-friendly)
# ============================================================================
# Log status report every day at 9:00 AM and 6:00 PM
0 9,18 * * * cd /path/to/crypto-trader-agent && ./scripts/manage_services.sh status >> logs/cron-status.log 2>&1

# ============================================================================
# OPTIONAL: Weekly Log Rotation / Cleanup
# ============================================================================
# Compress and archive old logs weekly (Sundays at 3:00 AM)
# This keeps the logs directory clean and prevents disk space issues
0 3 * * 0 cd /path/to/crypto-trader-agent && gzip -v logs/*.log.1 2>/dev/null; find logs -name "*.log.*.gz" -mtime +30 -delete

# ============================================================================
# SETUP INSTRUCTIONS
# ============================================================================
#
# 1. Edit your crontab:
#    crontab -e
#
# 2. Add one or more of the examples above, replacing:
#    /path/to/crypto-trader-agent  →  Your actual repo path (use $(pwd) to find it)
#
# 3. Save and exit. Cron will automatically schedule the jobs.
#
# 4. Verify installation:
#    crontab -l
#
# ============================================================================
# MONITORING THE CRON JOBS
# ============================================================================
#
# View health check logs:
#    tail -50 logs/cron-healthcheck.log
#    tail -f logs/cron-healthcheck.log  (live tail)
#
# View restart logs:
#    tail -50 logs/cron-restart.log
#
# View status logs:
#    tail -50 logs/cron-status.log
#
# Check system cron logs (macOS):
#    log stream --predicate 'process == "cron"' --level debug
#
# Check system cron logs (Linux):
#    grep CRON /var/log/syslog | tail -20
#    journalctl -u cron --since today
#
# ============================================================================
# RECOMMENDED PRODUCTION SETUP
# ============================================================================
#
# For production with auto-recovery and notifications:
#
#   */5 * * * * cd /path/to/crypto-trader-agent && ./scripts/healthcheck.sh --auto-restart --telegram >> logs/cron-healthcheck.log 2>&1
#   0 2 * * * cd /path/to/crypto-trader-agent && ./scripts/manage_services.sh restart >> logs/cron-restart.log 2>&1
#   0 9,18 * * * cd /path/to/crypto-trader-agent && ./scripts/manage_services.sh status >> logs/cron-status.log 2>&1
#
# This gives you:
#   - Automatic restart on failure with Telegram alerts (every 5 min)
#   - Clean restart each night (memory leak prevention)
#   - Status snapshots twice daily
#
# ============================================================================
# TROUBLESHOOTING CRON ISSUES
# ============================================================================
#
# If cron jobs aren't running:
#
# 1. Verify cron service is running:
#    macOS:  sudo launchctl list | grep cron
#    Linux:  systemctl status cron
#
# 2. Check file permissions:
#    ls -la scripts/manage_services.sh
#    ls -la scripts/healthcheck.sh
#    # Both should have 'x' in permissions
#
# 3. Test the script manually:
#    cd /path/to/crypto-trader-agent
#    ./scripts/healthcheck.sh
#    # If it works manually, the issue is with cron's environment
#
# 4. Check cron logs:
#    macOS: system_profiler SPSoftwareDataType | grep 'System Version'
#           log stream --predicate 'process == "cron"' --level debug
#    Linux: journalctl -u cron --since today
#
# 5. Common issues:
#    - PATH not set: Use full paths to scripts ($(cd... pwd) pattern)
#    - Python not found: Activate virtualenv in cron job
#      Example: */5 * * * * source /path/venv/bin/activate && cd /path && ./scripts/healthcheck.sh
#
#    - Database locked: Increase SERVICE_TIMEOUT in manage_services.sh
#    - Permission denied: Check file ownership (chown) and permissions (chmod +x)
#
# ============================================================================
