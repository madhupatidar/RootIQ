"""Thin Ollama HTTP wrapper. Isolated so swapping to a hosted API later touches only this file."""

from __future__ import annotations

import httpx

from app.config import get_settings


class OllamaError(RuntimeError):
    pass


def generate(prompt: str, *, system: str | None = None, temperature: float = 0.0, json_mode: bool = True) -> str:
    settings = get_settings()
    payload: dict = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"

    try:
        response = httpx.post(
            f"{settings.ollama_base_url.rstrip('/')}/api/generate",
            json=payload,
            headers=settings.ollama_headers,
            timeout=settings.ollama_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:  # network down, model not pulled, timeout, bad key...
        raise OllamaError(f"Ollama request failed: {exc}") from exc

    return (response.json() or {}).get("response", "")


def health() -> dict:
    settings = get_settings()
    hosted = "localhost" not in settings.ollama_base_url and "127.0.0.1" not in settings.ollama_base_url
    try:
        response = httpx.get(
            f"{settings.ollama_base_url.rstrip('/')}/api/tags",
            headers=settings.ollama_headers,
            timeout=10.0,
        )
        response.raise_for_status()
        models = [m.get("name") for m in response.json().get("models", [])]
    except httpx.HTTPError as exc:
        return {"available": False, "model": settings.ollama_model, "detail": str(exc)}
    return {
        "available": True,
        "host": settings.ollama_base_url,
        "model": settings.ollama_model,
        # Hosted Ollama does not advertise the full cloud catalogue via /api/tags.
        "model_pulled": True if hosted else settings.ollama_model in models,
        "models": models,
    }
