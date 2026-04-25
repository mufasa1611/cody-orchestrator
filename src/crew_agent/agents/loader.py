from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    title: str
    kind: str
    description: str
    responsibilities: tuple[str, ...] = ()
    triggers: tuple[str, ...] = ()
    prompt: str = ""
    policy: dict[str, object] | None = None
    workflow: dict[str, object] | None = None
    source_path: Path | None = None


@dataclass(frozen=True)
class AgentCatalog:
    definitions: dict[str, AgentDefinition]
    directory: Path


def get_agents_dir() -> Path:
    return Path(__file__).resolve().parent / "definitions"


@lru_cache(maxsize=1)
def get_agent_catalog() -> AgentCatalog:
    directory = get_agents_dir()
    definitions: dict[str, AgentDefinition] = {}
    if not directory.exists():
        return AgentCatalog(definitions=definitions, directory=directory)

    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or path.stem).strip()
        if not name:
            continue
        responsibilities = tuple(
            str(item).strip()
            for item in raw.get("responsibilities", [])
            if str(item).strip()
        )
        triggers = tuple(
            str(item).strip()
            for item in raw.get("triggers", [])
            if str(item).strip()
        )
        definitions[name] = AgentDefinition(
            name=name,
            title=str(raw.get("title") or name).strip(),
            kind=str(raw.get("kind") or "specialist").strip(),
            description=str(raw.get("description") or "").strip(),
            responsibilities=responsibilities,
            triggers=triggers,
            prompt=str(raw.get("prompt") or "").strip(),
            policy=dict(raw.get("policy") or {}),
            workflow=dict(raw.get("workflow") or {}),
            source_path=path,
        )
    return AgentCatalog(definitions=definitions, directory=directory)


def get_agent_definition(name: str) -> AgentDefinition | None:
    return get_agent_catalog().definitions.get(name)
