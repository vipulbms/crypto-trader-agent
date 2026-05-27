#!/bin/bash
# Kryptos service health check — monitor service health and auto-restart on failure.
# Run periodically via cron: */5 * * * * /path/to/healthcheck.sh
# Or run standalone: ./scripts/healthcheck.sh [--auto-restart] [--telegram]

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

CONFIG="config.yaml"
DB="paper_trading.db"
PID_FILE="data/kryptos.pid"
HEALTHCHECK_LOG="logs/healthcheck.log"
MAX_RESTART_ATTEMPTS=3
RESTART_COOLDOWN=300  # seconds (5 minutes)

# Extract settings from config
LOG_DIR="$(python3 - <<'PY'
import yaml
try:
    cfg = yaml.safe_load(open('config.yaml'))
    print(cfg.get('storage', {}).get('log_dir', 'logs'))
except:
    print('logs')
PY)"

mkdir -p "$LOG_DIR"

# Parse command-line arguments
AUTO_RESTART=false
SEND_TELEGRAM=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --auto-restart)
            AUTO_RESTART=true
            shift
            ;;
        --telegram)
            SEND_TELEGRAM=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Helper functions
log_check() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$HEALTHCHECK_LOG"
}

send_telegram_alert() {
    if [ "$SEND_TELEGRAM" = false ]; then
        return
    fi

    local message="$1"
    local bot_token=$(python3 - <<'PY'
import yaml
try:
    cfg = yaml.safe_load(open('config.yaml'))
    print(cfg.get('notifications', {}).get('telegram_bot_token', ''))
except:
    print('')
PY)
    local chat_id=$(python3 - <<'PY'
import yaml
try:
    cfg = yaml.safe_load(open('config.yaml'))
    print(cfg.get('notifications', {}).get('telegram_chat_id', ''))
except:
    print('')
PY)

    if [ -n "$bot_token" ] && [ -n "$chat_id" ]; then
        curl -s -X POST "https://api.telegram.org/bot${bot_token}/sendMessage" \
            -d "chat_id=${chat_id}" \
            -d "text=⚠️ Healthcheck: ${message}" \
            -d "parse_mode=HTML" > /dev/null 2>&1 || true
    fi
}

# Check if service is running
is_running() {
    local pattern=$1
    pgrep -f "$pattern" > /dev/null 2>&1
}

# Get service PID
get_pid() {
    local pattern=$1
    pgrep -f "$pattern" | head -1
}

# Check last modification time of log file (indicates activity)
log_has_recent_activity() {
    local log_file=$1
    local minutes=${2:-10}  # default 10 minutes

    if [ ! -f "$log_file" ]; then
        return 1
    fi

    local mtime=$(stat -f %m "$log_file" 2>/dev/null || stat -c %Y "$log_file" 2>/dev/null || echo 0)
    local now=$(date +%s)
    local age=$((now - mtime))
    local threshold=$((minutes * 60))

    [ $age -lt $threshold ]
}

# Perform health checks
perform_checks() {
    local all_healthy=true
    local failed_services=()

    # Check core agent
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            log_check "✓ Core agent (PID: $pid) is running"
        else
            log_check "✗ Core agent process (PID: $pid) is not running"
            failed_services+=("core_agent")
            all_healthy=false
        fi
    else
        log_check "✗ Core agent PID file not found"
        failed_services+=("core_agent")
        all_healthy=false
    fi

    # Check if core agent is producing logs (indicating it's actively working)
    if ! log_has_recent_activity "$LOG_DIR/audit_agent.log" 15; then
        log_check "⚠ Audit agent log inactive for >15 minutes"
        failed_services+=("audit_agent_inactive")
        all_healthy=false
    else
        log_check "✓ Audit agent producing logs (active)"
    fi

    # Check auxiliary services
    local services=(
        "src.runtime.data_collector:data_collector"
        "src.runtime.research_analyst:research_analyst"
        "src.runtime.audit_agent:audit_agent"
        "src.runtime.fulfillment_service:fulfillment_service"
        "src.mcp.server:mcp_server"
    )

    for service_pair in "${services[@]}"; do
        IFS=':' read -r pattern name <<< "$service_pair"
        if is_running "$pattern"; then
            log_check "✓ $name is running"
        else
            log_check "✗ $name is not running"
            failed_services+=("$name")
            all_healthy=false
        fi
    done

    # Check for critical errors in logs
    local error_keywords=("CRITICAL" "FATAL" "SQLiteDatabase is locked")
    for log_file in "$LOG_DIR"/*.log; do
        if [ -f "$log_file" ]; then
            for keyword in "${error_keywords[@]}"; do
                if tail -100 "$log_file" | grep -q "$keyword"; then
                    local log_name=$(basename "$log_file")
                    log_check "⚠ Critical error in $log_name: $keyword"
                    failed_services+=("$log_name")
                    all_healthy=false
                fi
            done
        fi
    done

    # Return results
    if [ "$all_healthy" = true ]; then
        return 0
    else
        # Print failed services for potential restart
        printf '%s\n' "${failed_services[@]}"
        return 1
    fi
}

# Attempt to restart services
restart_services() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Check restart cooldown
    if [ -f "$HEALTHCHECK_LOG" ]; then
        local last_restart=$(grep -o "RESTART_ATTEMPT" "$HEALTHCHECK_LOG" | tail -1)
        if [ -n "$last_restart" ]; then
            local last_restart_epoch=$(grep "RESTART_ATTEMPT" "$HEALTHCHECK_LOG" | tail -1 | cut -d']' -f1 | cut -d'[' -f2)
            local now=$(date +%s)
            local elapsed=$((now - $(date -d "$last_restart_epoch" +%s 2>/dev/null || echo 0)))

            if [ $elapsed -lt $RESTART_COOLDOWN ]; then
                log_check "⏱ Skipping restart (cooldown active: ${elapsed}s < ${RESTART_COOLDOWN}s)"
                return 1
            fi
        fi
    fi

    # Check restart attempt count
    local restart_count=$(grep -c "RESTART_ATTEMPT" "$HEALTHCHECK_LOG" || echo 0)
    if [ $restart_count -ge $MAX_RESTART_ATTEMPTS ]; then
        local alert="Too many restart attempts ($restart_count/$MAX_RESTART_ATTEMPTS). Manual intervention required."
        log_check "❌ $alert"
        send_telegram_alert "$alert"
        return 1
    fi

    log_check "🔄 RESTART_ATTEMPT #$((restart_count + 1))/$MAX_RESTART_ATTEMPTS at $timestamp"
    send_telegram_alert "Attempting service restart (attempt $((restart_count + 1)))"

    # Execute restart
    if bash "$ROOT_DIR/scripts/manage_services.sh" restart >> "$HEALTHCHECK_LOG" 2>&1; then
        log_check "✓ Restart completed successfully"
        send_telegram_alert "Services restarted successfully"
        return 0
    else
        log_check "✗ Restart command failed"
        send_telegram_alert "Service restart failed"
        return 1
    fi
}

# Main health check flow
main() {
    log_check "═══════════════════════════════════════════════════════════"
    log_check "Health check started at $(date '+%Y-%m-%d %H:%M:%S')"

    if perform_checks > /tmp/failed_services.txt 2>&1; then
        log_check "✓ All services healthy"
        echo "HEALTHY"
    else
        local failed=$(cat /tmp/failed_services.txt)
        log_check "✗ Health check failed for: $failed"

        if [ "$AUTO_RESTART" = true ]; then
            if restart_services; then
                echo "RESTARTED"
            else
                echo "RESTART_FAILED"
            fi
        else
            echo "UNHEALTHY"
        fi
    fi

    log_check "Health check completed"
}

main
