"""Chat LLM factory: Gemini primary, with Claude then OpenAI as automatic
fallbacks via LangChain's `.with_fallbacks()`.

If a call to Gemini errors out — rate limit, outage, bad key, content
filter — the *same* invocation transparently retries on Claude, then
OpenAI, before raising. Nodes don't need to know this is happening; they
just call `.invoke()` on whatever this returns.

Requires GOOGLE_API_KEY, ANTHROPIC_API_KEY, and OPENAI_API_KEY in the
environment (see .env.example) — each provider's SDK reads its own key
directly, so nothing is threaded through config.py.
"""
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

import config


def _flatten_content(message: AIMessage) -> AIMessage:
    """claude-sonnet-5 runs with extended thinking always on and returns
    content as a list of blocks (a "thinking" block plus a "text" block)
    instead of a plain string — every node in this app expects
    message.content to be a plain string (answer_composer/chitchat return
    it directly, the classifier nodes json.loads() it), so this normalizes
    it regardless of which provider in the fallback chain actually
    responded."""
    if isinstance(message.content, list):
        message.content = "".join(
            block.get("text", "") for block in message.content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return message


def build_chat_llm(temperature: float):
    primary = ChatGoogleGenerativeAI(model=config.GEMINI_MODEL, temperature=temperature)
    # No temperature for Claude: claude-sonnet-5's always-on extended
    # thinking rejects an explicit temperature with a 400 error.
    claude_fallback = ChatAnthropic(model=config.CLAUDE_MODEL)
    openai_fallback = ChatOpenAI(model=config.OPENAI_MODEL, temperature=temperature)
    chain = primary.with_fallbacks([claude_fallback, openai_fallback])
    return chain | RunnableLambda(_flatten_content)
