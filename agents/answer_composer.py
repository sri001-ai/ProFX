"""Grounds the final answer strictly in retrieved chunks; never invents
pricing/specs, and falls back gracefully when the KB has no match."""
from langchain_core.messages import HumanMessage, SystemMessage

_SYSTEM_PROMPT = """You are the PRO FX assistant, a customer-support chatbot for PRO FX, a premium audio-video and home-automation dealer in India.

Answer ONLY using the provided context chunks. Naturally cite the brand/product name in your answer. If the context doesn't contain enough information to answer confidently, say so plainly and suggest the customer ask about a specific product, or offer to connect them with the team — never invent prices, specs, or availability.

Keep answers concise and conversational."""

NO_CONTEXT_ANSWER = (
    "I don't have specific information on that in our catalog right now. Could you tell me the "
    "product or brand you're interested in, or would you like me to connect you with our team?"
)


def make_answer_composer_node(llm):
    def node(state):
        docs = state.get("retrieved_docs") or []
        if not docs:
            return {"answer": NO_CONTEXT_ANSWER}

        context = "\n\n---\n\n".join(
            f"[Source: {d.get('product_name') or d.get('title') or d.get('url')} "
            f"({d.get('brand') or 'PRO FX'})]\n{d.get('text', '')[:1200]}"
            for d in docs
        )

        # Prior turns for follow-up context; the current turn is re-sent below
        # bundled with retrieved context, so it's excluded here to avoid
        # showing the model the bare question twice.
        history = (state.get("messages") or [])[:-1][-6:]

        messages = [SystemMessage(content=_SYSTEM_PROMPT), *history]
        messages.append(HumanMessage(content=f"Context:\n{context}\n\nQuestion: {state['user_input']}"))

        resp = llm.invoke(messages)
        return {"answer": resp.content}

    return node
