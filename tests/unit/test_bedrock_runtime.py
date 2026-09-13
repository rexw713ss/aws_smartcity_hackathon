"""Runtime selection and keyword-table fallback for the Bedrock decomposer."""

import asyncio
import json
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


def _settings(model_id: str | None, *, decompose_queries: bool = True) -> AppSettings:
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
    runtime = LocalRuntime(tmp_path, _settings("test-model"))

    response = asyncio.run(
        runtime.copilot().answer("Compare population trend", entity_ids=("banqiao", "linkou"))
    )

    assert UnavailableBedrockProvider.calls == 1
    assert response.decomposition is not None
    assert response.decomposition.metric_terms == ("population_count",)
    assert response.status == "insufficient_data"
    assert runtime.copilot() is runtime.copilot()


def test_a_degraded_decomposition_says_so_in_the_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A keyword-planned turn must not be indistinguishable from a model-planned one.

    This is the failure mode the inversion introduces: once the model is the
    primary decomposer, a throttled or misconfigured provider still produces
    grounded, correctly cited answers — just planned by keyword matching. Without
    a record in the response, nobody can tell the two apart.
    """

    UnavailableBedrockProvider.calls = 0
    monkeypatch.setattr(bedrock_model, "BedrockModelProvider", UnavailableBedrockProvider)
    runtime = LocalRuntime(tmp_path, _settings("test-model"))

    response = asyncio.run(runtime.copilot().answer("Compare population trend"))

    planning = [item for item in response.tool_trace if item.tool == "query_decomposer"]
    assert [item.outcome for item in planning] == ["decomposed", "degraded"]
    assert "keyword_table" in planning[0].summary
    assert "Bedrock unavailable" in planning[1].summary


def test_a_healthy_model_decomposition_is_recorded_as_the_model_s(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same trace field must name the model when the model actually planned."""

    class WorkingProvider:
        def __init__(self, model_id: str, **kwargs: object) -> None:
            del model_id, kwargs

        async def generate(self, request: ModelRequest) -> ModelResponse:
            del request
            return ModelResponse(
                text=json.dumps(
                    {
                        "original_question": "ignored",
                        "objective": "analyze a time trend",
                        "metric_terms": ["population_count"],
                        "operations": ["search_catalog", "inspect_dataset"],
                    }
                ),
                model_id="bedrock-test",
            )

    monkeypatch.setattr(bedrock_model, "BedrockModelProvider", WorkingProvider)
    runtime = LocalRuntime(tmp_path, _settings("test-model"))

    response = asyncio.run(runtime.copilot().answer("Compare population trend"))

    planning = [item for item in response.tool_trace if item.tool == "query_decomposer"]
    assert [item.outcome for item in planning] == ["decomposed"]
    assert "planned by model" in planning[0].summary


def test_runtime_requires_model_id_for_bedrock(tmp_path: Path) -> None:
    runtime = LocalRuntime(tmp_path, _settings(None))

    with pytest.raises(ConfigurationError, match=r"model\.model_id"):
        runtime.copilot()


def test_the_model_is_the_default_decomposer_not_the_keyword_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The keyword table is the fallback, so nothing should have to opt in.

    A cue table cannot generalize past the phrasings written into it, which caps
    what the product understands at whatever someone remembered to list in three
    languages. Reaching the model by default is the point; this asserts the
    default rather than trusting the config comment.
    """

    UnavailableBedrockProvider.calls = 0
    monkeypatch.setattr(bedrock_model, "BedrockModelProvider", UnavailableBedrockProvider)
    runtime = LocalRuntime(tmp_path, _settings("test-model"))

    settings = runtime.settings.model
    assert settings is not None
    assert settings.decompose_queries is True
    assert settings.compose_answers is True

    asyncio.run(runtime.copilot().answer("Compare population trend", entity_ids=("banqiao",)))
    assert UnavailableBedrockProvider.calls >= 1, "the decomposer must reach the model"


def test_the_keyword_table_can_still_be_selected_deliberately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Turning the model decomposer off must keep working, offline or to save spend."""

    UnavailableBedrockProvider.calls = 0
    monkeypatch.setattr(bedrock_model, "BedrockModelProvider", UnavailableBedrockProvider)
    runtime = LocalRuntime(tmp_path, _settings("test-model", decompose_queries=False))

    asyncio.run(runtime.copilot().answer("Compare population trend", entity_ids=("banqiao",)))

    assert UnavailableBedrockProvider.calls == 0, "the decomposer must not reach the model"
