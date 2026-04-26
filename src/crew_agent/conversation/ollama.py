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

    def unload_model(self) -> None:
        """Explicitly unloads the model from VRAM/RAM."""
        try:
            requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "keep_alive": 0},
                timeout=5,
            )
        except:
            pass

    def warm_up(self) -> None:
        """Pings the model to force it into the GPU."""
        try:
            requests.post(
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": "hi", "stream": False},
                timeout=30,
            )
        except:
            pass

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
        raw = body.get("response", "").strip()
        
        if not raw:
            raise ValueError(f"LLM model '{self.model}' returned an empty response.")
            
        # Robust parsing: Find the first { and last } to handle possible markdown wrapping
        start = raw.find('{')
        end = raw.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = raw[start : end + 1]
        else:
            json_str = raw

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse JSON from model '{self.model}'.\n"
                f"Raw Response: {raw[:500]}\n"
                f"Error: {e}"
            )
            
        if not isinstance(data, dict):
            raise ValueError(f"Planner did not return a JSON object. Got: {type(data).__name__}")
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
