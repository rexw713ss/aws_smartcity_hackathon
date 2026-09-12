"""Runtime selection and deterministic fallback for the Bedrock decomposer."""

import asyncio
from pathlib import Path

import pytest

from adapters.aws import bedrock_model
from apps.api.dependencies import LocalRuntime
from youth_compass.config import AppSettings
from youth_compass.domain import ConfigurationError, ModelInvocationError
from youth_compass.ports import ModelRequest, ModelResponse


class UnavailableBedrockProvider:
    calls = 0

    def __init__(self, model_id: str, **kwargs: object) -> None:
        del model_id, kwargs

    async def generate(self, request: ModelRequest) -> ModelResponse:
        del request
        type(self).calls += 1
        raise ModelInvocationError("Bedrock unavailable")


def _settings(model_id: str | None) -> AppSettings:
    return AppSettings(
        model={
            "provider": "bedrock",
            "model_id": model_id,
            "region": "us-east-1",
            "timeout_seconds": 10,
            "max_attempts": 2,
        }
    )


def test_runtime_falls_back_when_bedrock_decomposition_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    UnavailableBedrockProvider.calls = 0
    monkeypatch.setattr(
        bedrock_model, "BedrockModelProvider", UnavailableBedrockProvider
    )
    runtime = LocalRuntime(tmp_path, _settings("test-model"))

    response = asyncio.run(
        runtime.copilot().answer(
            "Compare population trend", entity_ids=("banqiao", "linkou")
        )
    )

    assert UnavailableBedrockProvider.calls == 1
    assert response.decomposition is not None
    assert response.decomposition.metric_terms == ("population_count",)
    assert response.status == "insufficient_data"
    assert runtime.copilot() is runtime.copilot()


def test_runtime_requires_model_id_for_bedrock(tmp_path: Path) -> None:
    runtime = LocalRuntime(tmp_path, _settings(None))

    with pytest.raises(ConfigurationError, match=r"model\.model_id"):
        runtime.copilot()
