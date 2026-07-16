"""Chitchat node — greetings, thanks, small talk, and vague meta questions.

Answered directly without touching the knowledge base, so a message like
"Hey there" can't get grounded in whatever product chunk happens to be
nearest in vector space and wander off into an unrelated answer.
"""
from langchain_core.messages import HumanMessage, SystemMessage

from agents.persona import PERSONA_INSTRUCTIONS

_SYSTEM_PROMPT = f"""{PERSONA_INSTRUCTIONS}

The customer just sent a greeting or general/small-talk message with no specific product question. Reply warmly and briefly, and invite them to ask about products, brands, pricing, installation, or to request a demo. Do not mention or invent any specific product or spec."""


def make_chitchat_node(llm):
    def node(state):
        history = (state.get("messages") or [])[:-1][-4:]
        messages = [SystemMessage(content=_SYSTEM_PROMPT), *history, HumanMessage(content=state["user_input"])]
        resp = llm.invoke(messages)
        return {"answer": resp.content}

    return node
