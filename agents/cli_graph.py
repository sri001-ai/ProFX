"""Entry point for `langgraph dev` / LangGraph Studio.

The Studio dev server manages its own checkpointing for graphs it runs, so
no SqliteSaver is passed here — that's only needed by the Streamlit app's
own long-lived process (see graph.py's get_checkpointer()).
"""
from agents.graph import build_graph

graph = build_graph()
