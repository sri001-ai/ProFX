"""Qdrant vector retrieval + optional cross-encoder reranking.

Query condensation for ambiguous follow-ups ("give me a few more options")
happens once, in the router (see router.py's standalone_query) — folded
into the intent-classification call rather than a second LLM call here.
"""
import config
from ingestion.embedder import get_embedder
from ingestion.qdrant_store import get_client, search

_reranker = None
_embedder = None
_client = None


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


def retrieve(query: str, top_k: int | None = None) -> list[dict]:
    top_k = top_k or config.RETRIEVAL_TOP_K
    vector = _cached_embedder().embed_query(query)
    return search(_cached_client(), vector, top_k)


def rerank(query: str, docs: list[dict], top_n: int | None = None) -> list[dict]:
    """Reranks and drops anything below RERANK_MIN_SCORE.

    Measured score gap on this corpus: real matches score +2.7 to +3.7+,
    unrelated/noise queries score -5 to -11 — there's no ambiguous middle
    ground, so a 0.0 floor cleanly separates "actually relevant" from
    "nearest available junk" (which is what was previously getting handed
    to the answer composer for greetings and vague follow-ups).
    """
    top_n = top_n or config.RERANK_TOP_K
    if not docs:
        return []
    if not config.ENABLE_RERANKER:
        return docs[:top_n]
    model = _get_reranker()
    pairs = [(query, d.get("text", "")) for d in docs]
    scores = model.predict(pairs)
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    relevant = [d for d, score in ranked if score >= config.RERANK_MIN_SCORE]
    return relevant[:top_n]


def retrieval_node(state):
    query = state.get("standalone_query") or state["user_input"]
    docs = retrieve(query)
    docs = rerank(query, docs)
    return {"retrieved_docs": docs}
