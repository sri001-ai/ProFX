"""LangChain callback that logs every LLM call — node, model actually used,
input/output tokens, and an approximate USD cost — to data/llm_calls.jsonl.

This is a lower-friction alternative to the LangSmith dashboard for a
running cost total: `python cost_report.py` summarizes the log directly.
Especially useful with the Gemini->Claude->OpenAI fallback chain, since the
model that actually serves a given request can vary — this records which
one it actually was, and logs a failed attempt (0 cost) whenever a
provider errors out and the chain falls through to the next one.
"""
import json
import threading
from datetime import datetime, timezone

from langchain_core.callbacks import BaseCallbackHandler

import config

# Approximate list price in $ per 1M tokens (input, output). For rough
# cost-tracking only, not billing — update if provider pricing changes.
_PRICING_PER_MILLION = {
    "gemini-2.0-flash": (0.10, 0.40),
    "claude-sonnet-5": (3.00, 15.00),
    "gpt-4o": (2.50, 10.00),
}

LOG_FILE = config.DATA_DIR / "llm_calls.jsonl"
_lock = threading.Lock()


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    for key, (in_price, out_price) in _PRICING_PER_MILLION.items():
        if key in (model or ""):
            return round((input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price, 6)
    return None


def _write(record: dict):
    with _lock:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")


class CostLoggingHandler(BaseCallbackHandler):
    def __init__(self):
        super().__init__()
        self._run_context: dict[str, dict] = {}

    def on_chat_model_start(self, serialized, messages, *, run_id, metadata=None, **kwargs):
        self._run_context[str(run_id)] = {"node": (metadata or {}).get("node", "unknown")}

    def on_llm_end(self, response, *, run_id, **kwargs):
        context = self._run_context.pop(str(run_id), {})
        for generation_list in response.generations:
            for generation in generation_list:
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None) or {}
                resp_meta = getattr(message, "response_metadata", None) or {}
                model = resp_meta.get("model_name") or resp_meta.get("model") or "unknown"
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                _write({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "node": context.get("node", "unknown"),
                    "model": model,
                    "status": "ok",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": usage.get("total_tokens", input_tokens + output_tokens),
                    "estimated_cost_usd": _estimate_cost(model, input_tokens, output_tokens),
                })

    def on_llm_error(self, error, *, run_id, **kwargs):
        context = self._run_context.pop(str(run_id), {})
        _write({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node": context.get("node", "unknown"),
            "model": "unknown",
            "status": "error",
            "error": str(error)[:300],
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0,
        })
