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


def _settings(model_id: str | None, *, decompose_queries: bool = False) -> AppSettings:
    return AppSettings(
        model={
            "provider": "bedrock",
            "model_id": model_id,
            "region": "us-east-1",
            "timeout_seconds": 10,
            "max_attempts": 2,
            "decompose_queries": decompose_queries,
        }
    )


def test_runtime_falls_back_when_bedrock_decomposition_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    UnavailableBedrockProvider.calls = 0
    monkeypatch.setattr(bedrock_model, "BedrockModelProvider", UnavailableBedrockProvider)
    # Model decomposition is opt-in, so this path has to ask for it.
    runtime = LocalRuntime(tmp_path, _settings("test-model", decompose_queries=True))

    response = asyncio.run(
        runtime.copilot().answer("Compare population trend", entity_ids=("banqiao", "linkou"))
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


def test_model_decomposition_is_off_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Measured to degrade answers, so it must never switch on implicitly.

    The composer still runs on the model: it only verbalizes an already-grounded
    payload and its output is rejected if it invents a citation or a number.
    """

    UnavailableBedrockProvider.calls = 0
    monkeypatch.setattr(bedrock_model, "BedrockModelProvider", UnavailableBedrockProvider)
    runtime = LocalRuntime(tmp_path, _settings("test-model"))

    settings = runtime.settings.model
    assert settings is not None
    assert settings.decompose_queries is False
    assert settings.compose_answers is True

    asyncio.run(runtime.copilot().answer("Compare population trend", entity_ids=("banqiao",)))
    assert UnavailableBedrockProvider.calls == 0, "the decomposer must not reach the model"
