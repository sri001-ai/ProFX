"""Thin wrapper over the local Ollama embedding model."""
from langchain_ollama import OllamaEmbeddings

import config


def get_embedder() -> OllamaEmbeddings:
    return OllamaEmbeddings(model=config.OLLAMA_EMBED_MODEL, base_url=config.OLLAMA_BASE_URL)


def embed_texts(embedder: OllamaEmbeddings, texts: list[str]) -> list[list[float]]:
    return embedder.embed_documents(texts)
