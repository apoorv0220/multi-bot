"""Load and validate the global intent registry (YAML)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_EXECUTION_VALUES = frozenset({"working", "support", "coming_soon"})
_DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent / "data" / "intent_registry.yaml"


class ExecutionMode(str, Enum):
    WORKING = "working"
    SUPPORT = "support"
    COMING_SOON = "coming_soon"


@dataclass(frozen=True)
class IntentDef:
    id: str
    execution: ExecutionMode
    tool: str
    subtype: str
    required_slots: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    merge_action: str | None = None
    notes: str | None = None


@dataclass
class Registry:
    version: int
    schema: str
    intents: dict[str, IntentDef]
    bitext_to_canonical: dict[str, str]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def intent_ids(self) -> frozenset[str]:
        return frozenset(self.intents.keys())

    def get_intent(self, intent_id: str) -> IntentDef:
        try:
            return self.intents[intent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown intent: {intent_id}") from exc

    def map_bitext_label(self, label: str) -> str | None:
        return self.bitext_to_canonical.get(label)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.intents:
            errors.append("intents[] is empty")
        ids = list(self.intents.keys())
        if len(ids) != len(set(ids)):
            errors.append("duplicate intent ids")
        for intent_id, intent in self.intents.items():
            if intent.id != intent_id:
                errors.append(f"intent key {intent_id!r} != id field {intent.id!r}")
            if intent.execution.value not in _EXECUTION_VALUES:
                errors.append(f"{intent_id}: invalid execution {intent.execution!r}")
        for bitext_label, canonical in self.bitext_to_canonical.items():
            if canonical not in self.intents:
                errors.append(
                    f"bitext_to_canonical[{bitext_label!r}] -> {canonical!r} not in intents"
                )
        if "nlu_fallback" not in self.intents:
            errors.append("missing nlu_fallback intent")
        return errors


def _parse_intent(raw: dict[str, Any]) -> IntentDef:
    intent_id = str(raw["id"])
    execution = ExecutionMode(str(raw["execution"]))
    required = tuple(str(s) for s in (raw.get("required_slots") or []))
    flags = tuple(str(f) for f in (raw.get("flags") or []))
    return IntentDef(
        id=intent_id,
        execution=execution,
        tool=str(raw.get("tool") or ""),
        subtype=str(raw.get("subtype") or ""),
        required_slots=required,
        flags=flags,
        merge_action=raw.get("merge_action"),
        notes=raw.get("notes"),
    )


def load_registry(path: Path | str | None = None) -> Registry:
    registry_path = Path(path) if path is not None else _DEFAULT_REGISTRY_PATH
    data = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid registry YAML at {registry_path}")

    intents_list = data.get("intents") or []
    intents: dict[str, IntentDef] = {}
    for row in intents_list:
        if not isinstance(row, dict) or "id" not in row:
            raise ValueError(f"Invalid intent row in {registry_path}: {row!r}")
        intent = _parse_intent(row)
        intents[intent.id] = intent

    bitext_map = data.get("bitext_to_canonical") or {}
    if not isinstance(bitext_map, dict):
        raise ValueError("bitext_to_canonical must be a mapping")

    registry = Registry(
        version=int(data.get("version") or 0),
        schema=str(data.get("schema") or ""),
        intents=intents,
        bitext_to_canonical={str(k): str(v) for k, v in bitext_map.items()},
        raw=data,
    )
    errors = registry.validate()
    if errors:
        raise ValueError(f"Registry validation failed: {'; '.join(errors)}")
    return registry


@lru_cache(maxsize=1)
def get_registry() -> Registry:
    """Cached default registry (tests may call load_registry with explicit path)."""
    return load_registry()
