"""Qdrant vector retrieval + optional cross-encoder reranking."""
import re

from langchain_core.messages import HumanMessage, SystemMessage

import config
from ingestion.embedder import get_embedder
from ingestion.qdrant_store import get_client, search

_reranker = None
_embedder = None
_client = None

# Follow-ups like "what is the weight of this?" carry no product name of
# their own — embedding them as-is retrieves whatever's nearest in vector
# space, which is often a *different* product. Only bother rewriting when a
# referential pronoun is actually present and there's prior conversation to
# resolve it against, so plain standalone questions skip the extra LLM call.
_PRONOUN_RE = re.compile(r"\b(this|that|these|those|it|its|they|them|the same)\b", re.IGNORECASE)

_CONDENSE_PROMPT = """Rewrite the customer's follow-up question into a standalone question by filling in the product/brand/topic it refers to, using the conversation so far. Keep it short — just the rewritten question, nothing else, no preamble.

If the follow-up is already standalone (names its own subject), return it unchanged."""


def _cached_embedder():
    global _embedder
    if _embedder is None:
        _embedder = get_embedder()
    return _embedder


def _cached_client():
    global _client
    if _client is None:
        _client = get_client()
    return _client


def _get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(config.RERANKER_MODEL)
    return _reranker


def _condense_query(user_input: str, history: list, llm) -> str:
    if not history or not _PRONOUN_RE.search(user_input):
        return user_input

    transcript = "\n".join(
        f"{'Customer' if isinstance(m, HumanMessage) else 'Assistant'}: {m.content}" for m in history[-6:]
    )
    try:
        resp = llm.invoke([
            SystemMessage(content=_CONDENSE_PROMPT),
            HumanMessage(content=f"Conversation so far:\n{transcript}\n\nFollow-up question: {user_input}"),
        ])
        rewritten = resp.content.strip()
        return rewritten or user_input
    except Exception:
        return user_input


def retrieve(query: str, top_k: int | None = None) -> list[dict]:
    top_k = top_k or config.RETRIEVAL_TOP_K
    vector = _cached_embedder().embed_query(query)
    return search(_cached_client(), vector, top_k)


def rerank(query: str, docs: list[dict], top_n: int | None = None) -> list[dict]:
    top_n = top_n or config.RERANK_TOP_K
    if not docs:
        return []
    if not config.ENABLE_RERANKER:
        return docs[:top_n]
    model = _get_reranker()
    pairs = [(query, d.get("text", "")) for d in docs]
    scores = model.predict(pairs)
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [d for d, _ in ranked[:top_n]]


def make_retrieval_node(llm):
    def node(state):
        # messages already include the current turn (input_guard appends it
        # first) — exclude it so "history" here really means prior turns.
        history = (state.get("messages") or [])[:-1]
        query = _condense_query(state["user_input"], history, llm)
        docs = retrieve(query)
        docs = rerank(query, docs)
        return {"retrieved_docs": docs}

    return node
