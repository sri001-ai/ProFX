"""Double-checks the router's "lead_capture" call against the specific
question that was just asked, before committing to it.

Why this exists: the general router juggles four categories at once and,
in testing, kept misreading replies like "yes im based out of bangalore" as
someone providing lead-capture slot info — when it was actually just
answering the assistant's own prior question about finding a showroom
address. A narrowly-scoped agent whose only job is "given exactly what the
assistant just asked, is the customer still engaged in a quote/demo
request, or did they answer something else?" is far more reliable than
asking the same broad classifier to catch its own edge cases.
"""
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

_SYSTEM_PROMPT = """You are checking whether a customer is genuinely continuing a price-quote/demo/callback request, or actually asking about something else (like an address, hours, specs, or declining).

You'll be given the assistant's last message and the customer's reply. Decide which ONE of these best describes the reply:
- "continue": the customer is still engaged in providing their name/city/contact/interest toward the quote/demo/callback that was asked about.
- "retrieval": the customer is actually asking a product or business question (e.g. an address, hours, specs) — not continuing the lead request, even if their reply mentions a city or sounds affirmative.
- "chitchat": the customer is declining, saying they're just browsing, or making small talk.
- "escalation": the customer wants to talk to a human directly instead.

A reply that merely mentions a city or says "yes" is NOT enough on its own to mean "continue" — check what the assistant's message actually asked for.

If the decision is "retrieval", also rewrite the customer's reply into a standalone question using the assistant's last message for context (e.g. assistant asked "want help finding your nearest showroom?", customer replied "yes im based out of bangalore" -> standalone question "Where is the Bangalore showroom located?"). For any other decision, just repeat the reply unchanged.

Respond with ONLY a JSON object, no other text: {"decision": "continue" | "retrieval" | "chitchat" | "escalation", "standalone_query": "<rewritten or original reply>"}"""

_VALID_DECISIONS = {"continue", "retrieval", "chitchat", "escalation"}


def _last_assistant_message(messages: list) -> str:
    for m in reversed(messages[:-1]):
        if isinstance(m, AIMessage):
            return m.content
    return "(this is the start of the conversation)"


def make_lead_capture_guard_node(llm):
    def node(state):
        prior_ai = _last_assistant_message(state.get("messages") or [])
        user_input = state["user_input"]

        decision = "continue"
        standalone_query = user_input
        try:
            resp = llm.invoke([
                SystemMessage(content=_SYSTEM_PROMPT),
                HumanMessage(
                    content=f'Assistant\'s last message: "{prior_ai}"\nCustomer\'s reply: "{user_input}"'
                ),
            ])
            data = json.loads(resp.content)
            candidate = data.get("decision", "continue")
            if candidate in _VALID_DECISIONS:
                decision = candidate
            standalone_query = data.get("standalone_query") or user_input
        except Exception:
            pass

        result = {"lead_capture_decision": decision}
        if decision != "continue":
            result["intent"] = decision
            result["standalone_query"] = standalone_query
            result["lead_slots"] = {}  # abandon — don't let it linger for later turns
        return result

    return node
