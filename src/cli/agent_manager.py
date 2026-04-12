"""
agent_manager.py — Start, stop, and monitor the Kryptos trading agent process.

Uses a PID file at data/kryptos.pid to track the running process.
The agent itself is launched by running main.py in a subprocess.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

from src.utils.tz import SGT, now_sgt

logger = logging.getLogger(__name__)

_BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DATA_DIR    = os.path.join(_BASE_DIR, "data")
_PID_FILE    = os.path.join(_DATA_DIR, "kryptos.pid")
_MAIN_SCRIPT = os.path.join(_BASE_DIR, "main.py")
_LOG_FILE    = "/logs/agent.log"  # overridden by init_from_config()


def init_from_config(config: dict) -> None:
    """Resolve log paths from config.storage.log_dir. Call once at CLI startup."""
    global _LOG_FILE
    log_dir  = config.get("storage", {}).get("log_dir", "/logs")
    os.makedirs(log_dir, exist_ok=True)
    _LOG_FILE = os.path.join(log_dir, "agent.log")


def _ensure_data_dir() -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)


# ──────────────────────────────────────────────────────────────
# PID helpers
# ──────────────────────────────────────────────────────────────

def _write_pid(pid: int, mode: str) -> None:
    _ensure_data_dir()
    with open(_PID_FILE, "w") as f:
        json.dump({
            "pid": pid,
            "mode": mode,
            "started_at": now_sgt().isoformat(),
        }, f)


def _read_pid() -> Optional[dict]:
    if not os.path.exists(_PID_FILE):
        return None
    try:
        with open(_PID_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _clear_pid() -> None:
    if os.path.exists(_PID_FILE):
        os.remove(_PID_FILE)


def _is_running(pid: int) -> bool:
    """Check if a process with the given PID is alive."""
    try:
        os.kill(pid, 0)   # signal 0 = check only, no actual signal sent
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def start(mode: str = "paper") -> dict:
    """
    Launch the agent as a detached background subprocess.
    Returns {'ok': bool, 'message': str, 'pid': int|None}.
    """
    existing = _read_pid()
    if existing and _is_running(existing["pid"]):
        return {
            "ok": False,
            "message": (
                f"Agent is already running in {existing['mode'].upper()} mode "
                f"(PID {existing['pid']}, started {existing['started_at']})."
            ),
            "pid": existing["pid"],
        }

    if not os.path.exists(_MAIN_SCRIPT):
        return {"ok": False, "message": f"main.py not found at {_MAIN_SCRIPT}", "pid": None}

    python = sys.executable
    flag   = "--paper" if mode == "paper" else "--live"

    log_out = open(_LOG_FILE, "a")
    proc = subprocess.Popen(
        [python, _MAIN_SCRIPT, flag],
        cwd=_BASE_DIR,
        stdout=log_out,
        stderr=log_out,
        start_new_session=True,   # detach from this terminal
    )

    time.sleep(1)  # brief pause — confirm process didn't exit immediately
    if not _is_running(proc.pid):
        return {
            "ok": False,
            "message": f"Agent process exited immediately. Check {_LOG_FILE} for errors.",
            "pid": None,
        }

    _write_pid(proc.pid, mode)
    return {
        "ok": True,
        "message": f"Agent started in {mode.upper()} mode (PID {proc.pid}).",
        "pid": proc.pid,
        "log_file": _LOG_FILE,
    }


def stop() -> dict:
    """
    Gracefully stop the running agent (SIGTERM, then SIGKILL after 10 s).
    Returns {'ok': bool, 'message': str}.
    """
    info = _read_pid()
    if not info:
        return {"ok": False, "message": "No running agent found (no PID file)."}

    pid = info["pid"]
    if not _is_running(pid):
        _clear_pid()
        return {"ok": False, "message": f"Agent PID {pid} is not running. Cleaned up stale PID file."}

    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            time.sleep(1)
            if not _is_running(pid):
                _clear_pid()
                return {"ok": True, "message": f"Agent (PID {pid}) stopped gracefully."}

        # Force kill if SIGTERM didn't work
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
        _clear_pid()
        return {"ok": True, "message": f"Agent (PID {pid}) force-killed after SIGTERM timeout."}

    except Exception as exc:
        return {"ok": False, "message": f"Failed to stop agent: {exc}"}


def status(config: Optional[dict] = None) -> dict:
    """
    Return a status dict describing the agent's current state.

    config is optional — if provided, the last audit cycle is included.
    """
    info   = _read_pid()
    result = {
        "running": False,
        "pid": None,
        "mode": None,
        "started_at": None,
        "uptime_human": None,
        "last_cycle": None,
        "log_file": _LOG_FILE,
    }

    if info:
        result["pid"]        = info.get("pid")
        result["mode"]       = info.get("mode")
        result["started_at"] = info.get("started_at")
        result["running"]    = _is_running(info["pid"])

        if result["running"] and info.get("started_at"):
            try:
                started = datetime.fromisoformat(info["started_at"]).astimezone(SGT)
                uptime  = now_sgt() - started
                total_s = int(uptime.total_seconds())
                h = total_s // 3600
                m = (total_s % 3600) // 60
                result["uptime_human"] = f"{h}h {m}m"
            except Exception:
                pass

        if not result["running"]:
            _clear_pid()

    # Pull last cycle from audit DB if possible
    if config:
        try:
            from src.storage.database import get_connection
            mode = info["mode"] if info else "paper"
            ac   = get_connection(config["storage"]["audit_db"])
            row  = ac.execute(
                "SELECT * FROM audit_cycles WHERE mode=? ORDER BY cycle_at DESC LIMIT 1",
                (mode,),
            ).fetchone()
            if row:
                result["last_cycle"] = dict(row)
            ac.close()
        except Exception:
            pass

    return result


def get_next_schedule(config: Optional[dict] = None) -> dict:
    """
    Estimate the next decision cycle time based on the last known cycle
    and the configured interval.
    """
    interval_min = 15
    if config:
        interval_min = config.get("trading", {}).get("cycle_interval_minutes", 15)

    last_cycle_at = None
    if config:
        try:
            from src.storage.database import get_connection
            info = _read_pid()
            mode = info["mode"] if info else "paper"
            ac   = get_connection(config["storage"]["audit_db"])
            row  = ac.execute(
                "SELECT cycle_at FROM audit_cycles WHERE mode=? ORDER BY cycle_at DESC LIMIT 1",
                (mode,),
            ).fetchone()
            if row:
                last_cycle_at = row["cycle_at"]
            ac.close()
        except Exception:
            pass

    now = now_sgt()

    if last_cycle_at:
        try:
            last = datetime.fromisoformat(last_cycle_at).astimezone(SGT)
            nxt  = last + timedelta(minutes=interval_min)
            if nxt < now:
                nxt = now  # overdue — should happen immediately
            wait_secs = max(0, int((nxt - now).total_seconds()))
            wait_min  = wait_secs // 60
            wait_sec  = wait_secs % 60
            return {
                "last_cycle_at": last_cycle_at,
                "next_cycle_at": nxt.isoformat(),
                "interval_minutes": interval_min,
                "wait_human": f"{wait_min}m {wait_sec}s" if wait_min > 0 else f"{wait_sec}s",
                "is_overdue": nxt < now,
            }
        except Exception:
            pass

    return {
        "last_cycle_at": None,
        "next_cycle_at": None,
        "interval_minutes": interval_min,
        "wait_human": "unknown (no cycles run yet)",
        "is_overdue": False,
    }


def tail_log(lines: int = 30) -> list:
    """Return the last N lines of agent.log."""
    if not os.path.exists(_LOG_FILE):
        return ["No log file found. Agent has not been run yet."]
    try:
        with open(_LOG_FILE, "r") as f:
            all_lines = f.readlines()
        return [l.rstrip() for l in all_lines[-lines:]]
    except Exception as exc:
        return [f"Error reading log: {exc}"]
