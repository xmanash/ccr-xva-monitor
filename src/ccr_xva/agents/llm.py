"""Optional explanation rewrite. Failure falls back to the grounded template."""

from __future__ import annotations

import httpx

from shared.settings import Settings


def rewrite(prompt: str, settings: Settings) -> str | None:
    """Phrase a grounded answer with Groq, then Google, when those calls succeed."""
    _enable_trust()
    if not settings.llm_enabled:
        return None
    if settings.groq_api_key:
        text = _groq(prompt, settings)
        if text:
            return text
        return _google(prompt, settings)
    text = _ollama(prompt, settings)
    if text:
        return text
    return _google(prompt, settings)


def _ollama(prompt: str, settings: Settings) -> str | None:
    try:
        response = httpx.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/generate",
            json={"model": settings.ollama_model, "prompt": prompt, "stream": False},
            timeout=8.0,
        )
        response.raise_for_status()
        return response.json().get("response")
    except Exception:
        return None


def _groq(prompt: str, settings: Settings) -> str | None:
    try:
        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=8.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def _google(prompt: str, settings: Settings) -> str | None:
    if not settings.google_api_key:
        return None
    try:
        from google import genai

        client = genai.Client(api_key=settings.google_api_key)
        response = client.models.generate_content(model=settings.adk_model or "gemini-2.5-flash", contents=prompt)
        return getattr(response, "text", None)
    except Exception:
        return None


def _enable_trust() -> None:
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        return


def llm_status(settings: Settings) -> str:
    if not settings.llm_enabled:
        return "disabled"
    if settings.groq_api_key:
        return "groq-configured"
    try:
        response = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=0.8)
        response.raise_for_status()
        return "ollama-reachable"
    except Exception:
        return "degraded"
