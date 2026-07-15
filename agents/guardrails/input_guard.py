"""Input guardrail node: blocks jailbreak attempts, redacts PII before it
ever reaches retrieval, the LLM prompt, or the persisted chat history."""
from langchain_core.messages import HumanMessage

import config
from agents.guardrails import jailbreak, pii

REFUSAL_MESSAGE = (
    "I can't help with that request. Let's get back to your PRO FX questions — "
    "products, pricing, installation, or booking a demo."
)


def make_input_guard_node(llm):
    def node(state):
        user_input = state["user_input"]
        result = {"guard_blocked": False, "guard_reason": None, "pii_redacted": False}

        if config.ENABLE_INPUT_GUARDRAILS:
            verdict = jailbreak.classify(user_input, llm)
            if verdict["jailbreak"]:
                result["guard_blocked"] = True
                result["guard_reason"] = f"jailbreak: {verdict['reason']}"
                result["answer"] = REFUSAL_MESSAGE
                result["messages"] = [HumanMessage(content=user_input)]
                return result

            # Mid-flow lead capture explicitly asks the user for their
            # phone/email as the "contact" slot — redacting it there would
            # make the captured lead useless. Still redact everything else
            # (nobody should be handing over a card/Aadhaar/PAN number here).
            lead_slots = state.get("lead_slots") or {}
            in_lead_capture = bool(lead_slots) and not lead_slots.get("complete")
            redact_types = (pii.ALL_TYPES - {"email", "phone"}) if in_lead_capture else pii.ALL_TYPES

            redacted, matches = pii.redact(user_input, redact_types)
            if matches:
                result["pii_redacted"] = True
                user_input = redacted

        result["user_input"] = user_input
        result["messages"] = [HumanMessage(content=user_input)]
        return result

    return node
