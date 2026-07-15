"""Intent router: classifies each turn into retrieval / lead_capture /
escalation, per the taxonomy in agents/README.md."""
import json

from langchain_core.messages import HumanMessage, SystemMessage

_SYSTEM_PROMPT = """You are the intent router for the PRO FX customer-support chatbot (PRO FX sells and installs premium audio-video and home-automation systems in India). Classify the customer's message into exactly one of:

- "retrieval": product info, specs, brand questions, installation/warranty FAQs, or any general question answerable from our product knowledge base.
- "lead_capture": the customer wants a price quote, wants to book a demo, wants a callback, or is providing contact/city/budget details to get one.
- "escalation": the customer explicitly asks to speak to a human, an agent, or our support/sales team.

If unsure, choose "retrieval". Respond with ONLY a JSON object, no other text: {"intent": "retrieval" | "lead_capture" | "escalation"}"""

_VALID_INTENTS = {"retrieval", "lead_capture", "escalation"}


def make_router_node(llm):
    def node(state):
        # Mid-flow lead capture keeps going without re-classifying every turn.
        lead_slots = state.get("lead_slots") or {}
        if lead_slots and not lead_slots.get("complete"):
            return {"intent": "lead_capture"}

        intent = "retrieval"
        try:
            resp = llm.invoke([SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=state["user_input"])])
            data = json.loads(resp.content)
            candidate = data.get("intent", "retrieval")
            if candidate in _VALID_INTENTS:
                intent = candidate
        except Exception:
            pass

        return {"intent": intent}

    return node
