"""Intent router: classifies each turn into chitchat / retrieval /
lead_capture / escalation, per the taxonomy in agents/README.md — and, for
retrieval turns, rewrites the message into a standalone query in the same
call (folding query condensation into the router avoids a second LLM call
per turn while fixing follow-ups that don't use pronouns, e.g. "give me a
few more options")."""
import json

from langchain_core.messages import HumanMessage, SystemMessage

import config

_SYSTEM_PROMPT = """You are the intent router for the PRO FX customer-support chatbot (PRO FX sells and installs premium audio-video and home-automation systems in India). Given the conversation so far and the customer's latest message, do two things:

1. Classify intent into exactly one of:
   - "chitchat": greetings, thanks, small talk, or vague/meta messages with no product or business content (e.g. "hey", "thanks", "who are you").
   - "retrieval": product info, specs, brand questions, installation/warranty FAQs, showroom hours/location, or any question answerable from our knowledge base — including short follow-ups like "any other options" or "what about the price" that continue a product discussion.
   - "lead_capture": the customer wants a price quote, wants to book a demo, wants a callback, or is actively providing contact/city/budget details toward one.
   - "escalation": the customer explicitly asks to speak to a human, an agent, or our support/sales team.

2. If intent is "retrieval", rewrite the latest message into a standalone query that names the product/brand/topic being discussed, filling in anything implied by the conversation (e.g. after discussing "JBL speakers over 200W", rewrite "give me a few more options" into "more JBL speaker options with output over 200W"). If the message already names its own subject, or intent isn't "retrieval", just repeat the latest message unchanged.

Respond with ONLY a JSON object, no other text: {"intent": "chitchat" | "retrieval" | "lead_capture" | "escalation", "standalone_query": "<rewritten or original message>"}"""

_VALID_INTENTS = {"chitchat", "retrieval", "lead_capture", "escalation"}


def make_router_node(llm):
    def node(state):
        user_input = state["user_input"]

        lead_slots = state.get("lead_slots") or {}
        lead_in_progress = bool(lead_slots) and not lead_slots.get("complete")

        history = (state.get("messages") or [])[:-1][-(config.CONVERSATION_HISTORY_TURNS * 2):]
        transcript = (
            "\n".join(f"{'Customer' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}" for m in history)
            or "(no prior conversation)"
        )

        latest_message = f"Latest message: {user_input}"
        if lead_in_progress:
            # Every turn is still re-classified — never blindly assume the
            # customer is continuing to provide their details, or a decline
            # like "no thanks, just researching" gets stuck re-asking for a
            # name forever instead of being heard.
            missing = [s for s in ("name", "city", "contact") if not lead_slots.get(s)]
            latest_message += (
                f"\n\n(Note: the customer already started a quote/demo request and we're still missing "
                f"{', '.join(missing)}. If their latest message continues providing that info, classify as "
                f'"lead_capture". If they decline, say they\'re just browsing, or ask about something else '
                f"entirely, classify based on what they actually said — we'll drop the incomplete request.)"
            )

        intent = "retrieval"
        standalone_query = user_input
        try:
            resp = llm.invoke([
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(content=f"Conversation so far:\n{transcript}\n\n{latest_message}"),
            ])
            data = json.loads(resp.content)
            candidate = data.get("intent", "retrieval")
            if candidate in _VALID_INTENTS:
                intent = candidate
            standalone_query = data.get("standalone_query") or user_input
        except Exception:
            pass

        result = {"intent": intent, "standalone_query": standalone_query}
        if lead_in_progress and intent != "lead_capture":
            result["lead_slots"] = {}  # abandon the incomplete request, don't let it linger
        return result

    return node
