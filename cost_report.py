#!/usr/bin/env python3
"""
Summarizes data/llm_calls.jsonl for cost monitoring.

Examples:
    python cost_report.py                # full summary since the log began
    python cost_report.py --since 2026-07-15
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime

from agents.cost_logger import LOG_FILE


def main():
    parser = argparse.ArgumentParser(description="Summarize LLM call cost/token log")
    parser.add_argument("--since", help="Only include calls at/after this ISO date, e.g. 2026-07-15")
    args = parser.parse_args()

    if not LOG_FILE.exists():
        print(f"No log yet at {LOG_FILE} — nothing has been sent to an LLM.")
        return

    since = datetime.fromisoformat(args.since) if args.since else None

    total_cost = 0.0
    total_calls = 0
    total_errors = 0
    by_model = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0})
    by_node = defaultdict(lambda: {"calls": 0, "cost": 0.0})

    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            record = json.loads(line)
            ts = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
            if since and ts.replace(tzinfo=None) < since:
                continue

            total_calls += 1
            if record["status"] == "error":
                total_errors += 1
                continue

            cost = record.get("estimated_cost_usd") or 0.0
            total_cost += cost
            by_model[record["model"]]["calls"] += 1
            by_model[record["model"]]["input_tokens"] += record["input_tokens"]
            by_model[record["model"]]["output_tokens"] += record["output_tokens"]
            by_model[record["model"]]["cost"] += cost
            by_node[record["node"]]["calls"] += 1
            by_node[record["node"]]["cost"] += cost

    print(f"Total calls: {total_calls}  (errors/fallbacks triggered: {total_errors})")
    print(f"Estimated total cost: ${total_cost:.4f}\n")

    print("By model:")
    for model, stats in sorted(by_model.items(), key=lambda kv: -kv[1]["cost"]):
        print(
            f"  {model:30s} calls={stats['calls']:<5} "
            f"in={stats['input_tokens']:<8} out={stats['output_tokens']:<8} "
            f"cost=${stats['cost']:.4f}"
        )

    print("\nBy node:")
    for node, stats in sorted(by_node.items(), key=lambda kv: -kv[1]["cost"]):
        print(f"  {node:20s} calls={stats['calls']:<5} cost=${stats['cost']:.4f}")


if __name__ == "__main__":
    main()
