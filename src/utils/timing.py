"""
Timing decorator — logs execution time for every instrumented method.

Log format:
  [TIMING] cycle=<id> class=<ClassName> method=<name> <key=val ...> took=<N>ms

Usage:
  @timed("pair", "usd_amount")      # logs named args by position or keyword
  def propose_buy(self, pair, usd_amount): ...

  @timed()                          # logs method name and time only
  def some_method(self): ...
"""

import asyncio
import functools
import inspect
import logging
import time
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger("timing")

# Holds the current cycle ID — set by run_cycle in main.py
current_cycle_id: ContextVar[int] = ContextVar("current_cycle_id", default=0)


def set_cycle_id(cycle_id: int) -> None:
    current_cycle_id.set(cycle_id)


def _extract_params(func, args, kwargs, param_names: tuple) -> dict:
    """Extract named parameters from a function call by inspecting the signature."""
    if not param_names:
        return {}
    try:
        sig = inspect.signature(func)
        bound = sig.bind(*args, **kwargs)
        bound.apply_defaults()
        return {k: bound.arguments[k] for k in param_names if k in bound.arguments}
    except Exception:
        return {}


def _class_name(args) -> str:
    """Return class name if first arg is self/cls, else empty string."""
    if args and hasattr(args[0], "__class__"):
        cls = args[0].__class__
        if cls.__name__ not in ("function", "module"):
            return cls.__name__
    return ""


def _build_log(class_name: str, method_name: str, params: dict, elapsed_ms: int) -> str:
    cycle = current_cycle_id.get()
    parts = [f"cycle={cycle}", f"class={class_name or 'module'}", f"method={method_name}"]
    for k, v in params.items():
        # Truncate long values (e.g. dicts/lists)
        sv = str(v)
        parts.append(f"{k}={sv[:40]}" if len(sv) > 40 else f"{k}={sv}")
    parts.append(f"took={elapsed_ms}ms")
    return "[TIMING] " + " ".join(parts)


def timed(*param_names: str):
    """
    Decorator factory. Pass the parameter names you want logged.
    Works on both sync and async methods/functions.
    """
    def decorator(func):
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                params = _extract_params(func, args, kwargs, param_names)
                cls = _class_name(args)
                start = time.perf_counter()
                try:
                    return await func(*args, **kwargs)
                finally:
                    elapsed = int((time.perf_counter() - start) * 1000)
                    logger.info(_build_log(cls, func.__name__, params, elapsed))
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                params = _extract_params(func, args, kwargs, param_names)
                cls = _class_name(args)
                start = time.perf_counter()
                try:
                    return func(*args, **kwargs)
                finally:
                    elapsed = int((time.perf_counter() - start) * 1000)
                    logger.info(_build_log(cls, func.__name__, params, elapsed))
            return sync_wrapper
    return decorator
