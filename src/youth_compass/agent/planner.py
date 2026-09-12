"""Planners that turn a question into an allowlisted decision intent.

A planner never produces facts. It maps natural language onto one registered
decision profile, or declines, and everything downstream works from retrieved
evidence. The model-backed planner is schema-constrained and its output is
checked against the allowlist, so an unexpected profile is dropped rather than
executed.
"""

import json
from typing import Protocol

from pydantic import ValidationError

from youth_compass.agent.contracts import CopilotIntent
from youth_compass.domain.errors import ModelInvocationError
from youth_compass.ports import ModelProvider, ModelRequest


class CopilotPlanner(Protocol):
    """Convert natural language into an allowlisted, schema-validated intent."""

    async def plan(self, question: str, entity_ids: tuple[str, ...]) -> CopilotIntent | None:
        """Return a supported intent, or None when no profile can answer."""
        ...


class DeterministicCopilotPlanner:
    """Offline planner for the two reference location decisions."""

    _HOME_TERMS = (
        "mua nhà",
        "nha o dau",
        "nhà ở đâu",
        "home buying",
        "buy a home",
        "buy house",
        "housing location",
        "買房",
        "購屋",
    )
    _CHARGER_TERMS = (
        "trụ sạc",
        "trạm sạc",
        "tru sac",
        "tram sac",
        "ev charger",
        "charging station",
        "charger placement",
        "充電站",
        "充電樁",
    )

    async def plan(self, question: str, entity_ids: tuple[str, ...]) -> CopilotIntent | None:
        normalized = " ".join(question.casefold().split())
        if any(term in normalized for term in self._HOME_TERMS):
            return CopilotIntent(profile_code="home_buying", entity_ids=entity_ids)
        if any(term in normalized for term in self._CHARGER_TERMS):
            return CopilotIntent(profile_code="ev_charger_placement", entity_ids=entity_ids)
        return None


class ModelCopilotPlanner:
    """Schema-constrained planner for a Bedrock-backed ModelProvider."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        allowed_profiles: tuple[str, ...] = ("home_buying", "ev_charger_placement"),
    ) -> None:
        self._provider = provider
        self._allowed_profiles = frozenset(allowed_profiles)

    async def plan(self, question: str, entity_ids: tuple[str, ...]) -> CopilotIntent | None:
        response = await self._provider.generate(
            ModelRequest(
                system=(
                    "Classify the user's decision question. Return only JSON matching the "
                    "provided schema. Never invent a profile. Use one of: "
                    + ", ".join(sorted(self._allowed_profiles))
                ),
                prompt=json.dumps(
                    {"question": question, "entity_ids": entity_ids},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                temperature=0,
                max_tokens=200,
                response_schema=CopilotIntent.model_json_schema(),
            )
        )
        try:
            intent = CopilotIntent.model_validate_json(response.text)
        except ValidationError as exc:
            raise ModelInvocationError("model returned an invalid copilot intent") from exc
        if intent.profile_code not in self._allowed_profiles:
            return None
        return intent.model_copy(update={"entity_ids": entity_ids})
