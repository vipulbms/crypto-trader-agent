---
name: Kryptos project context
description: Architecture, pairs, critical conventions, GitHub repo, skills for the Kryptos crypto trading agent
type: project
---

# Kryptos Project Context

**GitHub repo:** https://github.com/vipulbms/crypto-trader-agent
**Entry points:** `python main.py --paper` (background loop), `python kryptos.py` (CLI)
**DB files:** `paper_trading.db`, `audit.db` (never commit these)
**LLM:** Ollama `qwen2.5:14b`, fallback `llama3.1:8b`, timeout 900s

## 15 Trading Pairs

BTC/USD (8%), ETH/USD (12%), BNB/USD (12%), SOL/USD (16%), XRP/USD (12%), TRX/USD (12%), DOGE/USD (20%), ADA/USD (12%), LTC/USD (8%), RAILS/USD (20%), AVAX/USD (12%), SUI/USD (20%), HYPE/USD (20%), UNI/USD (12%), INJ/USD (20%). All use 5% SL.

## Critical Conventions

- **`get_balance()`** must return `total_usd = cash + sum(usd_value of open positions)` — never cash-only. This has regressed twice.
- **`usd_value` in DB** = entry cost only. Actual cash deducted = entry cost + entry fee.
- **`caution_factor` is code-enforced:** After `build_ai_context()`, `main.py` scales `portfolio["max_per_trade"]` by `caution_factor` (0.5 bearish, 0.7 volatile) before the LLM cycle. Not just advisory.
- **Dynamic TP is order-level:** `TradingTools.propose_buy()` uses `ai_context["dynamic_tp_values"][pair]` (ATR/BB-adjusted), falling back to static config. `set_dynamic_tp_values()` called by `trading_agent.run_cycle()` before LLM decision.
- **Single LLM call per cycle** covers all 15 pairs. LLM ranks BUY candidates, picks top ≤3.
- **SL/TP checks run before LLM cycle** — highest priority in the loop.
- **Early-sell guardrails:** LLM cannot call `propose_sell` unless P&L > +2%.
- **Cycle interval:** 30 minutes.
- **Never trust LLM pair names** — always resolve against known signal pairs.
- **`set_cycle_id()`** must be called immediately after `audit.log_cycle()` in `main.py`.

## Skills

- `/commit` — stages safe files, writes session notes, updates CLAUDE.md + docs, pushes to GitHub
- `/add-pair` — onboards a new pair (only `config.yaml` needs editing now — config-driven architecture)

## Architecture Notes

- All 7 AI features (regime, sentiment, patterns, exit_timing, position_sizing, dynamic_tp, post_trade) are in `src/analysis/features.py`
- `build_ai_context()` returns both text blocks (for LLM prompt) and structured data (`regime_data`, `dynamic_tp_values`) for code-level enforcement
- Tests live in `tests/` — run with `.venv/bin/python -m pytest tests/`
