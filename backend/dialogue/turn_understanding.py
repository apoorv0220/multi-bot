"""Stable per-turn contract for semantic NLU + dialogue policy (Phase 0+)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class PolicyAction(str, Enum):
    PROCEED = "proceed"
    CLARIFY = "clarify"
    CONFIRM = "confirm"
    RESET = "reset"


class MergeAction(str, Enum):
    INHERIT = "inherit"
    REPLACE = "replace"
    APPEND = "append"
    CLEAR = "clear"
    BACKTRACK = "backtrack"


@dataclass(frozen=True)
class IntentCandidate:
    intent: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "score": self.score}


@dataclass
class TurnUnderstanding:
    """Output of NLU/P + DST/P before catalog execution."""

    intent: str = ""
    entities: dict[str, Any] = field(default_factory=dict)
    intent_confidence: float = 0.0
    intent_candidates: list[IntentCandidate] = field(default_factory=list)
    policy_action: PolicyAction = PolicyAction.PROCEED
    merge_action: MergeAction = MergeAction.INHERIT
    session_context: dict[str, Any] = field(default_factory=dict)
    pending_clarification: dict[str, Any] | None = None

    def to_debug_dict(self) -> dict[str, Any]:
        """JSON-friendly slice for DIALOGUE_DEBUG meta (Phase 2+)."""
        data = asdict(self)
        data["policy_action"] = self.policy_action.value
        data["merge_action"] = self.merge_action.value
        data["intent_candidates"] = [c.to_dict() for c in self.intent_candidates]
        return data
