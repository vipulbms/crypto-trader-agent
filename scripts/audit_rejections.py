#!/usr/bin/env python3
"""
Diagnostic script to audit why trades were not executed in backtesting.
It analyzes rejections across all 3 layers of the trading pipeline:
1. Signal Generator (Technical Indicators)
2. Agent/LLM (AI Logic)
3. Risk Manager (Capital & Time bounds)
"""

import sqlite3
import argparse
from collections import Counter

def query_db(db_path, query, params=()):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(query, params)
        res = cur.fetchall()
        conn.close()
        return res
    except sqlite3.Error as e:
        print(f"Database error reading {db_path}: {e}")
        return []

def main():
    parser = argparse.ArgumentParser(description="Analyze backtest rejections pipeline")
    parser.add_argument("--db", default="data/backtest_audit.db", help="Path to audit DB")
    args = parser.parse_args()

    db_path = args.db

    print("======================================================")
    print(" KRYPTOS BACKTEST REJECTION AUDIT")
    print("======================================================\n")

    # Layer 1: Signals
    print("--- [LAYER 1] Indicator Signal Blockers (signals.py) ---")
    reasons = query_db(db_path, "SELECT signal_reasons FROM audit_signals WHERE signal_direction = 'HOLD'")
    blockers = Counter()
    for row in reasons:
        reason_str = row[0]
        if "BLOCKED" in reason_str:
            # Extract basic block reason category for counting
            if "RSI" in reason_str and ">= 70" in reason_str:
                blockers["RSI Overbought (>= 70)"] += 1
            elif "Volume" in reason_str and "dropped below" in reason_str:
                blockers["Volume Dropped (Dead Zone)"] += 1
            elif "ATR-based TP" in reason_str and "floor" in reason_str:
                blockers["ATR Profit Floor too low"] += 1
            else:
                blockers["Other Indicator Block"] += 1

    total_holds = len(reasons)
    print(f"Total HOLD Signals Generated: {total_holds}")
    for k, v in blockers.most_common():
        print(f"  -> {k}: {v} times")
    print("")

    # Layer 2: LLM Decisions
    print("--- [LAYER 2] Agent/LLM Decisions (trading_agent.py) ---")
    llm_actions = query_db(db_path, "SELECT tool_called, COUNT(*) FROM audit_llm_decisions GROUP BY tool_called")
    print("Agent Output Summary:")
    for action, count in llm_actions:
        print(f"  -> {action}: {count}")
    
    print("\nTop 5 reasons the LLM decided to HOLD:")
    llm_holds = query_db(db_path, "SELECT hold_reason, COUNT(*) FROM audit_llm_decisions WHERE tool_called = 'hold' GROUP BY hold_reason ORDER BY COUNT(*) DESC LIMIT 5")
    if not llm_holds:
        print("  (No hold reasons logged or table empty)")
    for reason, count in llm_holds:
        clean_reason = reason.replace('\n', ' ') if reason else "No reason provided"
        print(f"  -> [{count}] {clean_reason[:80]}...")
    print("")

    # Layer 3: Risk Manager
    print("--- [LAYER 3] Risk Manager Guardrails (risk_manager.py) ---")
    risk_checks = query_db(db_path, "SELECT approved, rejection_reason, COUNT(*) FROM audit_risk_checks GROUP BY approved, rejection_reason")
    app_count = sum(c for a, r, c in risk_checks if a == 1)
    rej_count = sum(c for a, r, c in risk_checks if a == 0)
    print(f"Total Risk Manager Evaluations: {app_count + rej_count}")
    print(f"  -> Approved Buys: {app_count}")
    print(f"  -> Rejected Buys/Sells: {rej_count}")
    print("\nRejection Breakdown:")
    for a, reason, count in sorted(risk_checks, key=lambda x: x[2], reverse=True):
        if a == 0:
            print(f"  -> [{count}] {reason}")
    print("\n======================================================")

if __name__ == "__main__":
    main()
