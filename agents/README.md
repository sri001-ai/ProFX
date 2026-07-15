# Phase 3 — Multi-Agent RAG Bot (not yet built; this is the plan)

Built with **LangGraph** on top of **local Ollama models**
(`qwen2.5:7b` / `llama3.1:8b` class, per your setup), backed by the Qdrant
index from Phase 2.

## Proposed graph

```
                     ┌────────────────┐
                     │  Router Agent   │  classifies intent using the FAQ
                     │                 │  taxonomy you provided (product
                     └───────┬────────┘  query, price/quote, availability,
                             │            city/location, brand, install,
        ┌────────────────────┼────────────────────┐   warranty, demo, lead
        ▼                    ▼                     ▼   capture, etc.)
┌───────────────┐   ┌────────────────┐   ┌──────────────────┐
│ Retrieval Agent│   │  Lead-Capture   │   │  Escalation Agent │
│ (RAG over      │   │  Agent (collects│   │  ("connect me to  │
│  Qdrant KB)    │   │  city/budget/   │   │   a human/team")  │
└───────┬────────┘   │  contact, no    │   └──────────────────┘
        │             │  LLM needed)    │
        ▼             └────────────────┘
┌────────────────┐
│ Answer Composer │  grounds the answer in retrieved chunks, cites brand/
│    Agent        │  product/PDF source, and falls back gracefully when the
└────────────────┘  KB has no match (never hallucinate pricing/specs).
```

## Why multi-agent rather than a single RAG chain
- **Router** separates "answerable from KB" (product specs, brand info,
  installation FAQs) from "needs a human/CRM action" (price quotes,
  callback requests, demo booking) — these should never be answered from
  the LLM's imagination.
- **Lead-capture** is a structured-slot-filling agent, not a retrieval
  problem — keeping it separate avoids the RAG agent inventing pricing to
  "be helpful."
- **Retrieval agent** can do query rewriting + multi-query retrieval
  (e.g. "best speaker for movies" → separate retrieval for home-theatre
  speakers, subwoofers, AVR compatibility) before handing chunks to the
  composer.

## Setup for this phase (when we build it)
```bash
ollama pull qwen2.5:7b       # or llama3.1:8b
ollama pull nomic-embed-text
pip install langgraph langchain-ollama
```
