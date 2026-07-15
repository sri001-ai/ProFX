"""Structured slot-filling lead capture — no CRM integration exists yet, so
completed leads are logged locally to data/leads.jsonl (scope decision;
swap _save_lead() for a real CRM call when one is available)."""
import json
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

import config

REQUIRED_SLOTS = ["name", "city", "contact"]
LEADS_FILE = config.DATA_DIR / "leads.jsonl"

_EXTRACT_PROMPT = """Extract any of these fields the customer mentions in their message: name, city, contact (a phone number or email), interest (the product/brand/category they're interested in). Respond with ONLY a JSON object containing just the fields you actually found, e.g. {"city": "Bengaluru"}. If none found, respond with {}."""

_SLOT_PROMPTS = {
    "name": "Sure, I can help set that up. Could I get your name?",
    "city": "Thanks! Which city are you in, so we can connect you with the right team?",
    "contact": "And what's the best phone number or email to reach you on?",
}


def _save_lead(session_id: str, slots: dict):
    LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {"session_id": session_id, "captured_at": datetime.now(timezone.utc).isoformat(), **slots}
    with open(LEADS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def make_lead_capture_node(llm):
    def node(state):
        slots = dict(state.get("lead_slots") or {})

        try:
            resp = llm.invoke([SystemMessage(content=_EXTRACT_PROMPT), HumanMessage(content=state["user_input"])])
            extracted = json.loads(resp.content)
            for k, v in extracted.items():
                if v:
                    slots[k] = v
        except Exception:
            pass

        missing = [s for s in REQUIRED_SLOTS if not slots.get(s)]
        if missing:
            slots["complete"] = False
            answer = _SLOT_PROMPTS[missing[0]]
        else:
            slots["complete"] = True
            _save_lead(state.get("session_id", ""), slots)
            interest_note = f" in {slots['interest']}" if slots.get("interest") else ""
            answer = (
                f"Thanks {slots.get('name')}! We've noted your interest{interest_note} and someone from our "
                f"{slots.get('city')} team will reach out to you shortly."
            )

        return {"lead_slots": slots, "answer": answer}

    return node
