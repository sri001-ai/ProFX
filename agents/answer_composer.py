"""Grounds the final answer strictly in retrieved chunks; never invents
pricing/specs, and falls back gracefully when the KB has no match."""
from langchain_core.messages import HumanMessage, SystemMessage

import config
from agents.persona import PERSONA_INSTRUCTIONS

_SYSTEM_PROMPT = f"""{PERSONA_INSTRUCTIONS}

Base your answer only on what you know below — never invent prices, specs, or availability. Naturally mention the brand/product name, the way a knowledgeable staff member would. If what you know doesn't cover the question, say so warmly and offer to help find the right product or connect them with the team — don't reveal that this is retrieved data.

Keep answers concise and conversational."""

NO_CONTEXT_ANSWER = (
    "I don't have that particular detail on hand just yet — could you tell me a bit more about the "
    "product or brand you're interested in? Or I'd be happy to connect you with our team who can help "
    "right away!"
)


def make_answer_composer_node(llm):
    def node(state):
        docs = state.get("retrieved_docs") or []
        if not docs:
            return {"answer": NO_CONTEXT_ANSWER}

        knowledge = "\n\n---\n\n".join(
            f"[{d.get('product_name') or d.get('title') or d.get('url')} "
            f"({d.get('brand') or 'PRO FX'})]\n{d.get('text', '')[:1200]}"
            for d in docs
        )

        # Prior turns for follow-up context; the current turn is re-sent below
        # bundled with retrieved context, so it's excluded here to avoid
        # showing the model the bare question twice.
        history = (state.get("messages") or [])[:-1][-(config.CONVERSATION_HISTORY_TURNS * 2):]

        messages = [SystemMessage(content=_SYSTEM_PROMPT), *history]
        messages.append(
            HumanMessage(content=f"What you know about this:\n{knowledge}\n\nCustomer's question: {state['user_input']}")
        )

        resp = llm.invoke(messages)
        return {"answer": resp.content}

    return node
