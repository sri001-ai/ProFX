"""Shared LangGraph state schema for the PRO FX chat graph."""
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class GraphState(TypedDict, total=False):
    session_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    user_input: str

    guard_blocked: bool
    guard_reason: Optional[str]
    pii_redacted: bool

    intent: Optional[str]
    retrieved_docs: list[dict]
    lead_slots: dict
    answer: Optional[str]
