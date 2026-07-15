"""Builds and compiles the PRO FX chat graph:

    input_guard --(blocked)--> output_guard --> END
        |(ok)
        v
     router --> retrieval --> answer_composer --\
        |--> lead_capture -------------------------> output_guard --> END
        |--> escalation  --------------------------/
"""
import sqlite3

from langchain_ollama import ChatOllama
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

import config
from agents.answer_composer import make_answer_composer_node
from agents.escalation import escalation_node
from agents.guardrails.input_guard import make_input_guard_node
from agents.guardrails.output_guard import output_guard_node
from agents.lead_capture import make_lead_capture_node
from agents.retrieval import make_retrieval_node
from agents.router import make_router_node
from agents.state import GraphState


def _route_after_input_guard(state: GraphState) -> str:
    return "blocked" if state.get("guard_blocked") else "ok"


def _route_after_router(state: GraphState) -> str:
    return state.get("intent", "retrieval")


def build_graph(checkpointer=None):
    # reasoning=False: qwen3's "thinking" mode is both ~10x slower and, in
    # testing, less reliable at these short classification/extraction tasks
    # than plain instruction-following.
    chat_llm = ChatOllama(
        model=config.OLLAMA_LLM_MODEL, base_url=config.OLLAMA_BASE_URL, temperature=0.3, reasoning=False
    )
    json_llm = ChatOllama(
        model=config.OLLAMA_LLM_MODEL,
        base_url=config.OLLAMA_BASE_URL,
        temperature=0,
        format="json",
        reasoning=False,
    )

    graph = StateGraph(GraphState)
    graph.add_node("input_guard", make_input_guard_node(json_llm))
    graph.add_node("router", make_router_node(json_llm))
    graph.add_node("retrieval", make_retrieval_node(chat_llm))
    graph.add_node("lead_capture", make_lead_capture_node(json_llm))
    graph.add_node("escalation", escalation_node)
    graph.add_node("answer_composer", make_answer_composer_node(chat_llm))
    graph.add_node("output_guard", output_guard_node)

    graph.set_entry_point("input_guard")
    graph.add_conditional_edges(
        "input_guard", _route_after_input_guard, {"blocked": "output_guard", "ok": "router"}
    )
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {"retrieval": "retrieval", "lead_capture": "lead_capture", "escalation": "escalation"},
    )
    graph.add_edge("retrieval", "answer_composer")
    graph.add_edge("answer_composer", "output_guard")
    graph.add_edge("lead_capture", "output_guard")
    graph.add_edge("escalation", "output_guard")
    graph.add_edge("output_guard", END)

    return graph.compile(checkpointer=checkpointer)


def get_checkpointer() -> SqliteSaver:
    conn = sqlite3.connect(str(config.CHAT_STATE_DB), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def make_thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
