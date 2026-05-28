"""
albedo/web/azure_openai_client.py — Azure OpenAI swarm member.

Optional Tier 0 LLM provider.  Insert before Gemini in the swarm chain
when both AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT are set.

Free options:
  • Azure AI Foundry serverless Phi-3.5 Mini — pay-per-token, very cheap
  • GPT-3.5-Turbo on Azure — $0.002/1K tokens
  • Azure OpenAI free trial credits on new accounts

Opt-in via .env:
    AZURE_OPENAI_KEY=<your-key>
    AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/
    AZURE_OPENAI_DEPLOYMENT=gpt-35-turbo       # or phi-3-mini, etc.
    AZURE_OPENAI_API_VERSION=2024-02-01        # default

Requires: pip install openai   (the openai package supports Azure endpoints)

When the key/endpoint is not set every function returns None/error string
gracefully so the swarm chain falls through to Gemini → Groq → Ollama.
"""
from __future__ import annotations

import os
from typing import Optional

# ---------------------------------------------------------------------------
# Lazy client singleton
# ---------------------------------------------------------------------------
_client = None
_client_checked = False


def _get_client():
    """Return an openai.AzureOpenAI client or None if not configured."""
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    key      = os.environ.get("AZURE_OPENAI_KEY",      "").strip()
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "").strip()
    version  = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01").strip()

    if not key or not endpoint:
        return None

    try:
        from openai import AzureOpenAI  # type: ignore[import]
        _client = AzureOpenAI(
            api_key=key,
            azure_endpoint=endpoint,
            api_version=version,
        )
        deploy = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-35-turbo").strip()
        print(f"[azure_openai] Client ready — deployment: {deploy}")
        return _client
    except Exception as exc:
        print(f"[azure_openai] Init failed: {exc}")
        return None


def is_available() -> bool:
    """Return True when the client initialised successfully."""
    return _get_client() is not None


def query(
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
) -> Optional[str]:
    """
    Send *prompt* to the configured Azure OpenAI deployment.

    Returns the response text or None on failure (caller should fall
    through to the next swarm provider).

    Parameters
    ----------
    prompt        : str — user message
    system_prompt : str | None — optional system instruction
    temperature   : float — 0.0–1.0 (default 0.3)
    max_tokens    : int   — max completion tokens
    """
    client = _get_client()
    if client is None:
        return None

    deploy = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-35-turbo").strip()
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    try:
        response = client.chat.completions.create(
            model=deploy,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        print(f"[azure_openai] Query error: {exc}")
        return None
