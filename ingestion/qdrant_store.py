"""Qdrant collection management: create, upsert, and hash-based diffing for
incremental re-ingestion."""
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

import config


def get_client() -> QdrantClient:
    return QdrantClient(url=config.QDRANT_URL)


def ensure_collection(client: QdrantClient, vector_size: int):
    if client.collection_exists(config.QDRANT_COLLECTION):
        return
    client.create_collection(
        collection_name=config.QDRANT_COLLECTION,
        vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
    )


def fetch_existing_hashes(client: QdrantClient, chunk_ids: list[str]) -> dict[str, str]:
    """Returns {chunk_id: content_hash} for chunk_ids already present in the collection."""
    if not client.collection_exists(config.QDRANT_COLLECTION):
        return {}

    hashes: dict[str, str] = {}
    batch_size = 200
    for i in range(0, len(chunk_ids), batch_size):
        batch = chunk_ids[i:i + batch_size]
        points = client.retrieve(
            collection_name=config.QDRANT_COLLECTION,
            ids=batch,
            with_payload=["content_hash"],
            with_vectors=False,
        )
        for p in points:
            hashes[str(p.id)] = (p.payload or {}).get("content_hash")
    return hashes


def upsert_chunks(client: QdrantClient, chunks: list[dict], vectors: list[list[float]]):
    points = [
        qmodels.PointStruct(id=chunk["chunk_id"], vector=vector, payload=chunk)
        for chunk, vector in zip(chunks, vectors)
    ]
    client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)


def search(client: QdrantClient, query_vector: list[float], top_k: int) -> list[dict]:
    results = client.query_points(
        collection_name=config.QDRANT_COLLECTION,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    ).points
    hits = []
    for r in results:
        hit = dict(r.payload or {})
        hit["score"] = r.score
        hits.append(hit)
    return hits
