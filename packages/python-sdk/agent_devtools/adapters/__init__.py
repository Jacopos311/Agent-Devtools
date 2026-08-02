"""Framework adapters that bridge external agent frameworks into agent-devtools."""

from .langchain import LangChainTraceHandler  # noqa: F401
from .groq import (  # noqa: F401
    DEFAULT_GROQ_MODEL,
    GroqApiKeyError,
    TracedGroq,
    check_groq_api_key,
    create_groq_llm,
    wrap_groq,
)

__all__ = [
    "LangChainTraceHandler",
    "DEFAULT_GROQ_MODEL",
    "GroqApiKeyError",
    "TracedGroq",
    "check_groq_api_key",
    "create_groq_llm",
    "wrap_groq",
]
