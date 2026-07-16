"""Builds and compiles the PRO FX chat graph:

    input_guard --(blocked)--> output_guard --> END
        |(ok)
        v
     router --> retrieval --> answer_composer --\
        |--> chitchat    --------------------------> output_guard --> END
        |--> escalation  --------------------------/
        |--> lead_capture_guard
                |--(continue)-----> lead_capture ---/
                |--(retrieval/chitchat/escalation)--> (that node) --/
"""
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

import config
from agents.answer_composer import make_answer_composer_node
from agents.chitchat import make_chitchat_node
from agents.cost_logger import CostLoggingHandler
from agents.escalation import escalation_node
from agents.guardrails.input_guard import make_input_guard_node
from agents.guardrails.output_guard import output_guard_node
from agents.lead_capture import make_lead_capture_node
from agents.lead_capture_guard import make_lead_capture_guard_node
from agents.llm import build_chat_llm
from agents.retrieval import retrieval_node
from agents.router import make_router_node
from agents.state import GraphState


def _route_after_input_guard(state: GraphState) -> str:
    return "blocked" if state.get("guard_blocked") else "ok"


def _route_after_router(state: GraphState) -> str:
    return state.get("intent", "retrieval")


def _route_after_lead_capture_guard(state: GraphState) -> str:
    decision = state.get("lead_capture_decision", "continue")
    return decision if decision != "continue" else "lead_capture"


def build_graph(checkpointer=None):
    # chat_llm: free-form answers (answer_composer, chitchat).
    # json_llm: classification/extraction nodes that parse a JSON response —
    # temperature 0 for consistency; JSON-ness is enforced via prompt
    # instructions (see each node) rather than a provider-specific JSON
    # mode, since that'd need different handling per provider in the
    # fallback chain for little practical benefit — frontier models are
    # reliable at "respond with ONLY a JSON object" without it.
    chat_llm = build_chat_llm(temperature=0.3)
    json_llm = build_chat_llm(temperature=0)

    # Every LLM call gets logged to data/llm_calls.jsonl (model actually
    # used, tokens, estimated cost) — see cost_report.py for a summary.
    # Binding a per-node "node" tag onto its own copy of the llm here means
    # no node's own code needs to change to get this for free.
    cost_logger = CostLoggingHandler()

    def _tagged(llm, node_name: str):
        return llm.with_config(callbacks=[cost_logger], metadata={"node": node_name}, run_name=node_name)

    graph = StateGraph(GraphState)
    graph.add_node("input_guard", make_input_guard_node(_tagged(json_llm, "input_guard")))
    graph.add_node("router", make_router_node(_tagged(json_llm, "router")))
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("lead_capture_guard", make_lead_capture_guard_node(_tagged(json_llm, "lead_capture_guard")))
    graph.add_node("lead_capture", make_lead_capture_node(_tagged(json_llm, "lead_capture")))
    graph.add_node("escalation", escalation_node)
    graph.add_node("chitchat", make_chitchat_node(_tagged(chat_llm, "chitchat")))
    graph.add_node("answer_composer", make_answer_composer_node(_tagged(chat_llm, "answer_composer")))
    graph.add_node("output_guard", output_guard_node)

    graph.set_entry_point("input_guard")
    graph.add_conditional_edges(
        "input_guard", _route_after_input_guard, {"blocked": "output_guard", "ok": "router"}
    )
    graph.add_conditional_edges(
        "router",
        _route_after_router,
        {
            "retrieval": "retrieval",
            "lead_capture": "lead_capture_guard",
            "escalation": "escalation",
            "chitchat": "chitchat",
        },
    )
    # lead_capture_guard double-checks the router's call against the exact
    # question just asked (see lead_capture_guard.py for why this needs to
    # be a separate, narrowly-scoped step rather than folded into router).
    graph.add_conditional_edges(
        "lead_capture_guard",
        _route_after_lead_capture_guard,
        {
            "lead_capture": "lead_capture",
            "retrieval": "retrieval",
            "chitchat": "chitchat",
            "escalation": "escalation",
        },
    )
    graph.add_edge("retrieval", "answer_composer")
    graph.add_edge("answer_composer", "output_guard")
    graph.add_edge("lead_capture", "output_guard")
    graph.add_edge("escalation", "output_guard")
    graph.add_edge("chitchat", "output_guard")
    graph.add_edge("output_guard", END)

    return graph.compile(checkpointer=checkpointer)


def get_checkpointer() -> SqliteSaver:
    conn = sqlite3.connect(str(config.CHAT_STATE_DB), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver


def make_thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}
