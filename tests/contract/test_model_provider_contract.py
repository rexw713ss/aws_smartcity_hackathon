"""ModelProvider contract.

Feature: aws-stage1-foundation. Requirement 1 criterion 1 (async generate).
"""

import asyncio

from youth_compass.ports import ModelProvider, ModelRequest, ModelResponse


class TestModelProviderContract:
    def test_generate_returns_schema_valid_response(self, model_provider: ModelProvider) -> None:
        response = asyncio.run(model_provider.generate(ModelRequest(prompt="hello")))
        assert isinstance(response, ModelResponse)
        assert response.text
        assert response.model_id

    def test_generate_respects_or_reports_max_tokens(self, model_provider: ModelProvider) -> None:
        long_prompt = "x" * 100
        response = asyncio.run(
            model_provider.generate(ModelRequest(prompt=long_prompt, max_tokens=10))
        )
        # Either the text is truncated to the budget, or the stop reason reports it.
        assert len(response.text) <= 10 or response.stop_reason == "length"
