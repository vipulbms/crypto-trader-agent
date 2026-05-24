"""
CycleContext — central data contract for one trading cycle.

Story: S12.1.2 | Sprint: S1 | Epic: E12 — Persona Framework

Every cycle, main.py constructs a CycleContext and passes it through the
entire agent stack. All agents (AIE, ROM, RiskManager, TradingAgent) read
persona thresholds from CycleContext.persona_config rather than directly
from the raw global config dict. This ensures a single persona switch in
config.yaml propagates atomically to all callers each cycle.

Design decision (ADR-009): CycleContext lives in src/core/ inside the
Kryptos repo — it is a domain object, not a shared library. It encodes the
per-cycle snapshot of the world as seen by the Orchestrator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CycleContext:
    """
    Immutable snapshot of the state fed into one agent decision cycle.

    Fields
    ------
    cycle_id : str
        Unique identifier for this cycle (UUID4 or timestamp-based).
    persona : str
        Active persona name: ``conservative`` | ``medium`` | ``high``.
    persona_config : dict
        Full parameter map for the active persona loaded from
        ``config["personas"][persona]``. Agents should read thresholds
        from this dict rather than from the raw global config.
    playbook : str
        Active Orchestrator playbook e.g. ``"accumulate"`` | ``"hold"`` |
        ``"de-risk"``. Empty string when Orchestrator is not yet wired (S1).
    open_positions : list[dict]
        Snapshot of currently open positions at cycle start.
        Each element is the dict returned by broker.get_open_positions().
    unfilled_clusters : list[str]
        Correlation cluster names that already contain open positions.
        Used by RiskManager.validate_buy() to enforce cluster caps.
    btc_dominance_trend : str
        ``"rising"`` | ``"falling"`` | ``"flat"`` — macro regime signal.
        Empty string when dominance data is unavailable.
    prompt_tokens : int
        Estimated token count of the LLM prompt built this cycle.
        Populated after build_cycle_prompt(); 0 before that point.
    """

    cycle_id: str
    persona: str
    persona_config: Dict[str, Any]

    # Populated by Orchestrator (Sprint S5); defaults allow S1 usage without
    # Orchestrator being present.
    playbook: str = ""

    # Broker snapshot — populated in main.py before each cycle
    open_positions: List[Dict[str, Any]] = field(default_factory=list)
    unfilled_clusters: List[str] = field(default_factory=list)

    # Macro context — copied from loop_state each cycle
    btc_dominance_trend: str = ""

    # Observability
    prompt_tokens: int = 0

    # ── convenience helpers ──────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value from persona_config with an optional fallback.

        Example::

            min_score = ctx.get("buy_min_score", 5)
        """
        return self.persona_config.get(key, default)

    @property
    def buy_min_score(self) -> int:
        return int(self.persona_config.get("buy_min_score", 5))

    @property
    def max_open_positions(self) -> int:
        return int(self.persona_config.get("max_open_positions", 10))

    @property
    def max_position_pct(self) -> float:
        return float(self.persona_config.get("max_position_pct", 30))

    @property
    def min_profit_floor_pct(self) -> float:
        return float(self.persona_config.get("min_profit_floor_pct", 1.0))

    @property
    def reallocation_enabled(self) -> bool:
        return bool(self.persona_config.get("reallocation_enabled", False))

    @property
    def llm_temperature(self) -> float:
        return float(self.persona_config.get("llm_temperature", 0))

    @property
    def llm_max_tokens(self) -> int:
        return int(self.persona_config.get("llm_max_tokens", 1024))

    @property
    def llm_system_role(self) -> str:
        return str(self.persona_config.get("llm_system_role", "standard"))

    # ── factory ─────────────────────────────────────────────────────────────

    @classmethod
    def from_config(
        cls,
        config: dict,
        cycle_id: str,
        open_positions: Optional[List[Dict[str, Any]]] = None,
        unfilled_clusters: Optional[List[str]] = None,
        btc_dominance_trend: str = "",
    ) -> "CycleContext":
        """
        Construct a CycleContext from the raw config dict.

        Reads ``config["agent"]["persona"]`` to select the active profile,
        then copies ``config["personas"][persona]`` into ``persona_config``.

        Raises
        ------
        KeyError
            If ``agent.persona`` points to a profile that does not exist.
            (validate_config() should have caught this at startup.)
        """
        persona = config["agent"]["persona"]
        persona_config = dict(config["personas"][persona])
        return cls(
            cycle_id=cycle_id,
            persona=persona,
            persona_config=persona_config,
            open_positions=open_positions or [],
            unfilled_clusters=unfilled_clusters or [],
            btc_dominance_trend=btc_dominance_trend,
        )


def get_active_persona_from_db(db_path: str) -> Optional[str]:
    """
    S26: Read the active persona from the agent_state table.
    Used by main.py to detect API-level persona overrides (S18.1.3).

    Returns the persona name if set, None if absent or on DB error.
    """
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        c = conn.cursor()
        c.execute(
            "SELECT value FROM agent_state WHERE key = 'active_persona_override' LIMIT 1"
        )
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None
