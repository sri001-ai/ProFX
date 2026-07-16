"""Output guardrail node: redacts only high-risk ID-like PII (credit card,
Aadhaar, PAN) from generated answers. Deliberately narrower than the input
guard — this is a dealer bot that legitimately shares business phone/email
contact info, so those are not redacted here."""
from datetime import datetime

from langchain_core.messages import AIMessage

import config
from agents.guardrails import pii


def output_guard_node(state):
    answer = state.get("answer") or ""
    if config.ENABLE_OUTPUT_GUARDRAILS and answer:
        redacted, matches = pii.redact(answer, pii.HIGH_RISK_TYPES)
        if matches:
            answer = redacted
    timestamp = datetime.now().isoformat()
    return {"answer": answer, "messages": [AIMessage(content=answer, additional_kwargs={"timestamp": timestamp})]}
