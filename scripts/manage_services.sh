#!/bin/bash
# Comprehensive Kryptos service management: stop, start, verify, and error checking.
# Usage: ./scripts/manage_services.sh [start|stop|restart|status|logs]
# Run from repo root. Python virtualenv must be activated.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="$(which python3)"
CONFIG="config.yaml"
DB="paper_trading.db"
PID_FILE="data/kryptos.pid"
SERVICE_TIMEOUT=30  # seconds to wait for graceful shutdown

# Extract log_dir from config.yaml
LOG_DIR="$(python3 - <<'PY'
import yaml, os
cfg = yaml.safe_load(open('config.yaml'))
print(cfg.get('storage', {}).get('log_dir', 'logs'))
PY)"

mkdir -p "$LOG_DIR" "data"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logger function
log_info() {
    echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') — $*"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $(date '+%Y-%m-%d %H:%M:%S') — $*"
}

log_warning() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') — $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') — $*"
}

# Stop all services gracefully
stop_services() {
    log_info "Stopping all Kryptos services..."

    local stopped_count=0

    # Stop core trading agent via kryptos.py
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            log_info "Stopping core agent (PID: $pid)..."
            kill "$pid" 2>/dev/null || true

            # Wait for graceful shutdown
            local elapsed=0
            while kill -0 "$pid" 2>/dev/null && [ $elapsed -lt $SERVICE_TIMEOUT ]; do
                sleep 1
                ((elapsed++))
            done

            # Force kill if still running
            if kill -0 "$pid" 2>/dev/null; then
                log_warning "Core agent did not exit gracefully, force killing..."
                kill -9 "$pid" 2>/dev/null || true
            fi
            rm -f "$PID_FILE"
            log_success "Core agent stopped"
            ((stopped_count++))
        fi
    fi

    # Stop auxiliary services by pattern
    local services=("data_collector" "research_analyst" "audit_agent" "fulfillment_service" "mcp_server")

    for service in "${services[@]}"; do
        local pids=$(pgrep -f "src.runtime.$service|src.mcp.server" || true)
        if [ -n "$pids" ]; then
            log_info "Stopping $service..."
            echo "$pids" | xargs kill 2>/dev/null || true

            # Wait for graceful shutdown
            local elapsed=0
            while pgrep -f "src.runtime.$service|src.mcp.server" > /dev/null 2>&1 && [ $elapsed -lt $SERVICE_TIMEOUT ]; do
                sleep 1
                ((elapsed++))
            done

            # Force kill if still running
            if pgrep -f "src.runtime.$service|src.mcp.server" > /dev/null 2>&1; then
                log_warning "$service did not exit gracefully, force killing..."
                pgrep -f "src.runtime.$service|src.mcp.server" | xargs kill -9 2>/dev/null || true
            fi

            log_success "$service stopped"
            ((stopped_count++))
        fi
    done

    if [ $stopped_count -eq 0 ]; then
        log_warning "No services were running"
    else
        log_success "Stopped $stopped_count service(s)"
    fi

    sleep 2  # Brief pause before restart
}

# Start all services
start_services() {
    log_info "Starting Kryptos trading agent and support services..."

    # Verify config exists
    if [ ! -f "$CONFIG" ]; then
        log_error "Config file not found: $CONFIG"
        return 1
    fi

    # Clear old log files to avoid confusion
    for log in "$LOG_DIR"/*.log; do
        if [ -f "$log" ]; then
            > "$log"  # Truncate
        fi
    done

    # Start core agent (kryptos.py manages this, records PID)
    log_info "Starting core agent (paper mode)..."
    if ! "$PYTHON" kryptos.py start --paper > "$LOG_DIR/core_agent.log" 2>&1; then
        log_error "Failed to start core agent"
        return 1
    fi
    log_success "Core agent started"

    sleep 3  # Let core agent initialize before auxiliaries

    # Start DataCollector
    log_info "Starting DataCollector..."
    nohup "$PYTHON" -m src.runtime.data_collector --config "$CONFIG" --db "$DB" > "$LOG_DIR/data_collector.log" 2>&1 &
    log_success "DataCollector started"

    # Start ResearchAnalyst
    log_info "Starting ResearchAnalyst..."
    nohup "$PYTHON" -m src.runtime.research_analyst --config "$CONFIG" --db "$DB" > "$LOG_DIR/research_analyst.log" 2>&1 &
    log_success "ResearchAnalyst started"

    # Start AuditAgent
    log_info "Starting AuditAgent..."
    nohup "$PYTHON" -m src.runtime.audit_agent --config "$CONFIG" --db "$DB" > "$LOG_DIR/audit_agent.log" 2>&1 &
    log_success "AuditAgent started"

    # Start FulfillmentService
    log_info "Starting FulfillmentService..."
    nohup "$PYTHON" -m src.runtime.fulfillment_service --config "$CONFIG" --mode paper > "$LOG_DIR/fulfillment_service.log" 2>&1 &
    log_success "FulfillmentService started"

    # Start MCP server
    log_info "Starting MCP server..."
    nohup "$PYTHON" -m src.mcp.server --config "$CONFIG" > "$LOG_DIR/mcp_server.log" 2>&1 &
    log_success "MCP server started"

    sleep 5  # Give services time to start
}

# Verify all services are running and healthy
verify_services() {
    log_info "Verifying services..."

    local all_healthy=true

    # Check core agent
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            log_success "Core agent is running (PID: $pid)"
        else
            log_error "Core agent process (PID: $pid) is not running"
            all_healthy=false
        fi
    else
        log_error "Core agent PID file not found"
        all_healthy=false
    fi

    # Check auxiliary services
    local services=(
        "data_collector:DataCollector"
        "research_analyst:ResearchAnalyst"
        "audit_agent:AuditAgent"
        "fulfillment_service:FulfillmentService"
        "mcp_server:MCP server"
    )

    for service_pair in "${services[@]}"; do
        IFS=':' read -r pattern name <<< "$service_pair"
        if pgrep -f "src.runtime.$pattern|src.mcp.server" > /dev/null 2>&1; then
            local count=$(pgrep -f "src.runtime.$pattern|src.mcp.server" | wc -l)
            log_success "$name is running ($count process(es))"
        else
            log_warning "$name is not running"
            all_healthy=false
        fi
    done

    echo ""
    return $([ "$all_healthy" = true ] && echo 0 || echo 1)
}

# Check logs for errors
check_logs() {
    log_info "Checking logs for errors..."

    local error_count=0

    for log_file in "$LOG_DIR"/*.log; do
        if [ ! -f "$log_file" ]; then
            continue
        fi

        local log_name=$(basename "$log_file")
        local errors=$(grep -i "error\|exception\|traceback\|failed" "$log_file" 2>/dev/null | tail -5)

        if [ -n "$errors" ]; then
            log_error "Found errors in $log_name:"
            echo "$errors" | sed 's/^/  /'
            ((error_count++))
        else
            log_success "$log_name: no errors detected"
        fi
    done

    if [ $error_count -gt 0 ]; then
        log_warning "Found errors in $error_count log file(s)"
        return 1
    else
        log_success "All logs are clean"
        return 0
    fi
}

# Display service status
show_status() {
    log_info "Service Status Report"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Core agent
    echo -e "\n${BLUE}Core Agent:${NC}"
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "  Status: ${GREEN}Running${NC} (PID: $pid)"
            ps -p "$pid" -o %cpu=,%mem= | read cpu mem
            echo "  CPU: $cpu% | Memory: $mem%"
        else
            echo "  Status: ${RED}Stopped${NC}"
        fi
    else
        echo "  Status: ${RED}Stopped${NC} (no PID file)"
    fi

    # Auxiliary services
    echo -e "\n${BLUE}Auxiliary Services:${NC}"
    local services=(
        "data_collector:DataCollector"
        "research_analyst:ResearchAnalyst"
        "audit_agent:AuditAgent"
        "fulfillment_service:FulfillmentService"
        "mcp_server:MCP Server"
    )

    for service_pair in "${services[@]}"; do
        IFS=':' read -r pattern name <<< "$service_pair"
        if pgrep -f "src.runtime.$pattern|src.mcp.server" > /dev/null 2>&1; then
            local count=$(pgrep -f "src.runtime.$pattern|src.mcp.server" | wc -l)
            echo "  $name: ${GREEN}Running${NC} ($count process(es))"
        else
            echo "  $name: ${YELLOW}Stopped${NC}"
        fi
    done

    # Log directory
    echo -e "\n${BLUE}Logs:${NC}"
    echo "  Directory: $LOG_DIR"
    local log_count=$(ls -1 "$LOG_DIR"/*.log 2>/dev/null | wc -l)
    echo "  Files: $log_count"

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# Show recent logs
show_logs() {
    local service="${1:-all}"
    local lines="${2:-20}"

    if [ "$service" = "all" ]; then
        echo -e "${BLUE}=== Core Agent Log ===${NC}"
        tail -n "$lines" "$LOG_DIR/core_agent.log" 2>/dev/null || echo "No log found"

        echo -e "\n${BLUE}=== Audit Agent Log ===${NC}"
        tail -n "$lines" "$LOG_DIR/audit_agent.log" 2>/dev/null || echo "No log found"

        echo -e "\n${BLUE}=== DataCollector Log ===${NC}"
        tail -n "$lines" "$LOG_DIR/data_collector.log" 2>/dev/null || echo "No log found"
    else
        local log_file="$LOG_DIR/${service}.log"
        if [ -f "$log_file" ]; then
            tail -n "$lines" "$log_file"
        else
            log_error "Log file not found: $log_file"
        fi
    fi
}

# Main command dispatcher
case "${1:-status}" in
    start)
        start_services
        sleep 3
        verify_services
        if check_logs; then
            log_success "All services started successfully"
            exit 0
        else
            log_warning "Services started but errors detected in logs"
            exit 1
        fi
        ;;
    stop)
        stop_services
        log_success "All services stopped"
        exit 0
        ;;
    restart)
        stop_services
        sleep 2
        start_services
        sleep 3
        verify_services
        if check_logs; then
            log_success "All services restarted successfully"
            exit 0
        else
            log_warning "Services restarted but errors detected in logs"
            exit 1
        fi
        ;;
    status)
        show_status
        exit 0
        ;;
    logs)
        show_logs "${2:-all}" "${3:-20}"
        exit 0
        ;;
    verify)
        verify_services
        check_logs
        exit $?
        ;;
    *)
        cat << 'EOF'
Kryptos Service Manager

Usage: ./scripts/manage_services.sh <command> [options]

Commands:
  start              Start all services and verify
  stop               Stop all services gracefully
  restart            Stop and start all services
  status             Show status of all services
  verify             Verify services are running and check logs
  logs [service]     Tail logs (service: all|core_agent|audit_agent|data_collector|etc.)

Examples:
  ./scripts/manage_services.sh start
  ./scripts/manage_services.sh restart
  ./scripts/manage_services.sh logs audit_agent 50
  ./scripts/manage_services.sh status

EOF
        exit 0
        ;;
esac
