"""
Central configuration for the PRO FX scraper / ingestion pipeline.
Edit values here rather than hardcoding them elsewhere.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ---- Target site ----------------------------------------------------------
BASE_URL = "https://profx.com"
ALLOWED_DOMAINS = {"profx.com", "www.profx.com"}

# ---- Paths ------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"

RAW_HTML_DIR = DATA_DIR / "raw_html"          # full HTML snapshot per page (debug/audit trail)
MARKDOWN_DIR = DATA_DIR / "markdown"          # clean, structured .md per page — primary ingestion artifact
STRUCTURED_DIR = DATA_DIR / "structured"      # extracted structured JSON, one file per page
PDF_DIR = DATA_DIR / "pdfs"                   # downloaded PDF binaries, organized by brand/product
PDF_TEXT_DIR = DATA_DIR / "pdf_text"          # extracted/OCR'd text from each PDF, as JSON
LOG_DIR = DATA_DIR / "logs"
STATE_DB = DATA_DIR / "crawl_state.sqlite3"   # resumability / checkpointing

for _d in (RAW_HTML_DIR, MARKDOWN_DIR, STRUCTURED_DIR, PDF_DIR, PDF_TEXT_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Raw HTML snapshots are invaluable for debugging extraction quality (this
# is literally how several extraction bugs got diagnosed) but cost disk
# space at scale. Keep by default; set to False once extraction is trusted.
SAVE_RAW_HTML = os.getenv("PROFX_SAVE_RAW_HTML", "true").lower() != "false"

# ---- Crawl behaviour --------------------------------------------------------
MAX_CONCURRENT_PAGES = int(os.getenv("PROFX_MAX_CONCURRENT_PAGES", 5))
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("PROFX_MAX_CONCURRENT_DOWNLOADS", 6))
REQUEST_DELAY_SECONDS = float(os.getenv("PROFX_REQUEST_DELAY", 0.5))  # politeness delay per worker
NAV_TIMEOUT_MS = 30_000
SCROLL_PAUSE_MS = 350
MAX_SCROLL_ATTEMPTS = 25
RETRY_ATTEMPTS = 3
USER_AGENT = "ProFXKnowledgeBot/1.0 (+internal RAG ingestion bot)"

# ---- PDF / OCR ---------------------------------------------------------------
# If a PDF page yields fewer than this many characters of embedded text,
# it's treated as a scanned image page and OCR'd instead.
OCR_MIN_TEXT_CHARS_PER_PAGE = 40
OCR_DPI = 300

# ---- Phase 2 (ingestion) settings ----
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = "profx_knowledge_base"
# Embeddings stay local/free via Ollama — only chat completions (below) moved
# to paid cloud providers.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

CHUNK_SIZE_CHARS = int(os.getenv("PROFX_CHUNK_SIZE", 1500))
CHUNK_OVERLAP_CHARS = int(os.getenv("PROFX_CHUNK_OVERLAP", 200))

# ---- Chat LLM: Gemini primary, Claude then OpenAI as automatic fallbacks ----
# API keys (GOOGLE_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY) are read
# directly from the environment by each provider's SDK — not surfaced as
# config constants here, same reasoning as LANGSMITH_API_KEY below.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# ---- Phase 3 (agentic RAG) settings ----
RETRIEVAL_TOP_K = int(os.getenv("PROFX_RETRIEVAL_TOP_K", 20))
RERANK_TOP_K = int(os.getenv("PROFX_RERANK_TOP_K", 5))
ENABLE_RERANKER = os.getenv("PROFX_ENABLE_RERANKER", "true").lower() != "false"
RERANKER_MODEL = os.getenv("PROFX_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
# Measured on this corpus: genuinely relevant matches score +2.7 to +3.7+,
# unrelated/noise queries score -5 to -11 — 0.0 cleanly separates the two.
RERANK_MIN_SCORE = float(os.getenv("PROFX_RERANK_MIN_SCORE", 0.0))

ENABLE_INPUT_GUARDRAILS = os.getenv("PROFX_ENABLE_INPUT_GUARDRAILS", "true").lower() != "false"
ENABLE_OUTPUT_GUARDRAILS = os.getenv("PROFX_ENABLE_OUTPUT_GUARDRAILS", "true").lower() != "false"

# How many prior turns (1 turn = 1 customer message + 1 reply) the router and
# answer composer see. Too short and the bot "forgets" what product it was
# just discussing a few messages back — this is shared so both stay in sync.
CONVERSATION_HISTORY_TURNS = int(os.getenv("PROFX_HISTORY_TURNS", 8))

CHAT_STATE_DB = DATA_DIR / "chat_state.sqlite3"

# ---- LangSmith observability ----
# LANGSMITH_API_KEY is read directly from the environment by the LangSmith
# SDK itself — it is intentionally not surfaced as a config constant here.
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "profx-agentic-rag")

if LANGSMITH_TRACING:
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_PROJECT"] = LANGSMITH_PROJECT
