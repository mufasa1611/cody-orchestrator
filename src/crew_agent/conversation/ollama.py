from __future__ import annotations

import json
import os
from typing import Any

import requests
from langchain_ollama import ChatOllama


def normalize_base_url(base_url: str | None) -> str:
    resolved = (
        base_url
        or os.getenv("CODY_BASE_URL")
        or os.getenv("CREW_AGENT_BASE_URL")
        or os.getenv("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).strip()
    if not resolved.startswith(("http://", "https://")):
        resolved = f"http://{resolved}"
    resolved = resolved.replace("://0.0.0.0", "://127.0.0.1")
    return resolved.rstrip("/")


class OllamaClient:
    def __init__(self, model: str, base_url: str | None = None, timeout: int = 180):
        self.model = model
        self.base_url = normalize_base_url(base_url)
        self.timeout = timeout

    def tags(self) -> dict[str, Any]:
        response = requests.get(
            f"{self.base_url}/api/tags",
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_model_names(self) -> list[str]:
        data = self.tags()
        return [
            str(item.get("name"))
            for item in data.get("models", [])
            if str(item.get("name", "")).strip()
        ]

    def generate_json(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        prompt = (
            f"{system_prompt.strip()}\n\n"
            f"USER REQUEST:\n{user_prompt.strip()}\n"
        )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
        }
        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        raw = body.get("response", "{}")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Planner did not return a JSON object")
        return data


def build_llm(
    model: str | None = None,
    temperature: float | None = None,
    base_url: str | None = None,
) -> ChatOllama:
    resolved_model = model or os.getenv("CODY_MODEL") or "gemma4:latest"
    resolved_temperature = 0 if temperature is None else temperature
    return ChatOllama(
        model=resolved_model,
        base_url=normalize_base_url(base_url),
        temperature=resolved_temperature,
    )
