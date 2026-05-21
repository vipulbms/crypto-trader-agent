#!/usr/bin/env python3
"""
manage_agents.py — Unified control for all Kryptos agents.

Start, stop, restart, and monitor:
  1. Trading agent (main.py)
  2. Data collector (src/runtime/data_collector.py)
  3. Research analyst (src/runtime/research_analyst.py)
  4. Audit agent (src/runtime/audit_agent.py)
  5. Fulfillment service (src/runtime/fulfillment_service.py)
  6. MCP server (src/mcp/server.py)

Usage:
  python3 scripts/manage_agents.py start [--mode {paper,live}] [--agents {agent1,agent2,...}]
  python3 scripts/manage_agents.py stop [--agents {agent1,agent2,...}]
  python3 scripts/manage_agents.py restart [--mode {paper,live}] [--agents {agent1,agent2,...}]
  python3 scripts/manage_agents.py status [--agents {agent1,agent2,...}]
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Setup paths
_BASE_DIR = Path(__file__).parent.parent
_DATA_DIR = _BASE_DIR / "data"
_PIDS_FILE = _DATA_DIR / "agents.json"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Agent definitions
AGENTS = {
    "trading": {
        "name": "Trading Agent",
        "script": "main.py",
        "requires_mode": True,
        "pid_key": "trading_agent_pid",
    },
    "collector": {
        "name": "Data Collector",
        "script": "src/runtime/data_collector.py",
        "requires_mode": False,
        "pid_key": "data_collector_pid",
    },
    "analyst": {
        "name": "Research Analyst",
        "script": "src/runtime/research_analyst.py",
        "requires_mode": False,
        "pid_key": "research_analyst_pid",
    },
    "auditor": {
        "name": "Audit Agent",
        "script": "src/runtime/audit_agent.py",
        "requires_mode": False,
        "pid_key": "audit_agent_pid",
    },
    "fulfillment": {
        "name": "Fulfillment Service",
        "script": "src/runtime/fulfillment_service.py",
        "requires_mode": False,
        "pid_key": "fulfillment_service_pid",
    },
    "mcp": {
        "name": "MCP Server",
        "script": "src/mcp/server.py",
        "requires_mode": False,
        "pid_key": "mcp_server_pid",
    },
}


def _ensure_data_dir():
    """Ensure data directory exists."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def _read_pids() -> Dict:
    """Read all agent PIDs from file."""
    _ensure_data_dir()
    if not _PIDS_FILE.exists():
        return {}
    try:
        with open(_PIDS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read PID file: {e}")
        return {}


def _write_pids(pids: Dict):
    """Write all agent PIDs to file."""
    _ensure_data_dir()
    try:
        with open(_PIDS_FILE, "w") as f:
            json.dump(pids, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Failed to write PID file: {e}")


def _is_running(pid: int) -> bool:
    """Check if process with given PID is running."""
    try:
        os.kill(pid, 0)  # signal 0 = check only
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def start_agent(agent_key: str, mode: str = "paper", config_path: Optional[str] = None) -> bool:
    """Start a single agent. Returns True if successful."""
    if agent_key not in AGENTS:
        logger.error(f"Unknown agent: {agent_key}")
        return False

    agent = AGENTS[agent_key]
    script_path = _BASE_DIR / agent["script"]

    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return False

    # Check if already running
    pids = _read_pids()
    pid = pids.get(agent["pid_key"])
    if pid and _is_running(pid):
        logger.warning(f"{agent['name']} is already running (PID {pid})")
        return False

    # Build command
    python = sys.executable
    cmd = [python, str(script_path)]

    if agent["requires_mode"]:
        cmd.append(f"--{mode}")

    if config_path:
        cmd.extend(["--config", config_path])

    # Start process
    log_file = _BASE_DIR / "logs" / f"{agent_key}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(log_file, "a") as lf:
            proc = subprocess.Popen(
                cmd,
                cwd=str(_BASE_DIR),
                stdout=lf,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # detach from terminal
            )

        time.sleep(1)  # confirm didn't exit immediately
        if not _is_running(proc.pid):
            logger.error(f"{agent['name']} exited immediately. Check {log_file}")
            return False

        # Store PID
        pids[agent["pid_key"]] = proc.pid
        _write_pids(pids)

        logger.info(f"✓ {agent['name']} started (PID {proc.pid})")
        logger.info(f"  Log: {log_file}")
        return True

    except Exception as e:
        logger.error(f"Failed to start {agent['name']}: {e}")
        return False


def stop_agent(agent_key: str, force: bool = False) -> bool:
    """Stop a single agent. Returns True if successful."""
    if agent_key not in AGENTS:
        logger.error(f"Unknown agent: {agent_key}")
        return False

    agent = AGENTS[agent_key]
    pids = _read_pids()
    pid = pids.get(agent["pid_key"])

    if not pid:
        logger.warning(f"{agent['name']} is not running (no PID on file)")
        return False

    if not _is_running(pid):
        logger.warning(f"{agent['name']} PID {pid} is not running. Cleaning up.")
        pids.pop(agent["pid_key"], None)
        _write_pids(pids)
        return False

    try:
        # Try graceful shutdown first
        os.kill(pid, signal.SIGTERM)
        wait_time = 10 if not force else 3
        for _ in range(wait_time):
            time.sleep(1)
            if not _is_running(pid):
                logger.info(f"✓ {agent['name']} stopped gracefully (PID {pid})")
                pids.pop(agent["pid_key"], None)
                _write_pids(pids)
                return True

        # Force kill if needed
        if force or True:  # always try force after timeout
            os.kill(pid, signal.SIGKILL)
            time.sleep(1)
            logger.info(f"✓ {agent['name']} force-killed (PID {pid})")
            pids.pop(agent["pid_key"], None)
            _write_pids(pids)
            return True

    except Exception as e:
        logger.error(f"Failed to stop {agent['name']}: {e}")
        return False


def status_agent(agent_key: str) -> Dict:
    """Get status of a single agent."""
    if agent_key not in AGENTS:
        logger.error(f"Unknown agent: {agent_key}")
        return {}

    agent = AGENTS[agent_key]
    pids = _read_pids()
    pid = pids.get(agent["pid_key"])

    result = {
        "agent": agent_key,
        "name": agent["name"],
        "running": False,
        "pid": None,
        "log_file": str(_BASE_DIR / "logs" / f"{agent_key}.log"),
    }

    if pid and _is_running(pid):
        result["running"] = True
        result["pid"] = pid

    return result


def cmd_start(args):
    """Handle 'start' subcommand."""
    config_path = args.config if hasattr(args, "config") else None
    agents = args.agents.split(",") if args.agents else list(AGENTS.keys())

    started = []
    failed = []

    for agent_key in agents:
        if start_agent(agent_key, mode=args.mode, config_path=config_path):
            started.append(agent_key)
        else:
            failed.append(agent_key)

    logger.info(f"\nSummary: {len(started)} started, {len(failed)} failed")
    if failed:
        logger.error(f"Failed agents: {', '.join(failed)}")
        return 1
    return 0


def cmd_stop(args):
    """Handle 'stop' subcommand."""
    agents = args.agents.split(",") if args.agents else list(AGENTS.keys())
    force = args.force if hasattr(args, "force") else False

    stopped = []
    failed = []

    for agent_key in agents:
        if stop_agent(agent_key, force=force):
            stopped.append(agent_key)
        else:
            failed.append(agent_key)

    logger.info(f"\nSummary: {len(stopped)} stopped, {len(failed)} failed")
    if failed:
        logger.error(f"Failed agents: {', '.join(failed)}")
        return 1
    return 0


def cmd_restart(args):
    """Handle 'restart' subcommand."""
    agents = args.agents.split(",") if args.agents else list(AGENTS.keys())

    logger.info("Stopping agents...")
    for agent_key in agents:
        stop_agent(agent_key, force=True)

    time.sleep(2)  # brief pause before restart

    logger.info("Starting agents...")
    config_path = args.config if hasattr(args, "config") else None
    started = []
    failed = []

    for agent_key in agents:
        if start_agent(agent_key, mode=args.mode, config_path=config_path):
            started.append(agent_key)
        else:
            failed.append(agent_key)

    logger.info(f"\nSummary: {len(started)} restarted, {len(failed)} failed")
    if failed:
        logger.error(f"Failed agents: {', '.join(failed)}")
        return 1
    return 0


def cmd_status(args):
    """Handle 'status' subcommand."""
    agents = args.agents.split(",") if args.agents else list(AGENTS.keys())

    logger.info("\nAgent Status:")
    logger.info("─" * 80)

    running_count = 0
    for agent_key in agents:
        status = status_agent(agent_key)
        running = "🟢 RUNNING" if status["running"] else "🔴 STOPPED"
        pid_str = f"(PID {status['pid']})" if status["pid"] else ""
        logger.info(f"  {status['name']:30} {running:12} {pid_str}")
        if status["running"]:
            running_count += 1

    logger.info("─" * 80)
    logger.info(f"Total: {running_count}/{len(agents)} running\n")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Manage all Kryptos agents (trading, collector, analyst, auditor, fulfillment, mcp)",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # Start subcommand
    start_parser = subparsers.add_parser("start", help="Start agents")
    start_parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode for trading agent (default: paper)",
    )
    start_parser.add_argument(
        "--config",
        type=str,
        help="Path to config.yaml (optional)",
    )
    start_parser.add_argument(
        "--agents",
        type=str,
        help="Comma-separated list of agents to start (default: all). Options: "
        + ", ".join(AGENTS.keys()),
    )
    start_parser.set_defaults(func=cmd_start)

    # Stop subcommand
    stop_parser = subparsers.add_parser("stop", help="Stop agents")
    stop_parser.add_argument(
        "--agents",
        type=str,
        help="Comma-separated list of agents to stop (default: all). Options: "
        + ", ".join(AGENTS.keys()),
    )
    stop_parser.add_argument(
        "--force",
        action="store_true",
        help="Force-kill agents immediately (skip graceful shutdown)",
    )
    stop_parser.set_defaults(func=cmd_stop)

    # Restart subcommand
    restart_parser = subparsers.add_parser("restart", help="Restart agents (stop + start)")
    restart_parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode for trading agent (default: paper)",
    )
    restart_parser.add_argument(
        "--config",
        type=str,
        help="Path to config.yaml (optional)",
    )
    restart_parser.add_argument(
        "--agents",
        type=str,
        help="Comma-separated list of agents to restart (default: all). Options: "
        + ", ".join(AGENTS.keys()),
    )
    restart_parser.set_defaults(func=cmd_restart)

    # Status subcommand
    status_parser = subparsers.add_parser("status", help="Show agent status")
    status_parser.add_argument(
        "--agents",
        type=str,
        help="Comma-separated list of agents to check (default: all). Options: "
        + ", ".join(AGENTS.keys()),
    )
    status_parser.set_defaults(func=cmd_status)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
