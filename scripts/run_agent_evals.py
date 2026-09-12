"""Run routing evals offline or against the configured Bedrock model."""

import argparse
import asyncio
from pathlib import Path

from youth_compass.agent import (
    AgentEvalHarness,
    DeterministicQueryDecomposer,
    ModelQueryDecomposer,
    QueryDecomposer,
    SmartToolRouter,
    ToolCapabilityRegistry,
    default_decision_capabilities,
    load_eval_cases,
    register_observation_capabilities,
)
from youth_compass.config import ModelProviderName, load_settings
from youth_compass.domain import ConfigurationError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evals/agent-routing.jsonl"))
    parser.add_argument("--provider", choices=("deterministic", "bedrock"), default="deterministic")
    args = parser.parse_args()
    cases = load_eval_cases(args.cases)
    registry = default_decision_capabilities()
    register_observation_capabilities(registry)
    decomposer = _decomposer(args.provider, registry)
    report = asyncio.run(AgentEvalHarness(decomposer, SmartToolRouter(registry)).run(cases))
    print(report.model_dump_json(indent=2))
    if report.failed:
        raise SystemExit(1)


def _decomposer(provider: str, capabilities: ToolCapabilityRegistry) -> QueryDecomposer:
    if provider == "deterministic":
        return DeterministicQueryDecomposer()
    settings = load_settings()
    model = settings.model
    if model is None or model.provider is not ModelProviderName.BEDROCK or not model.model_id:
        raise ConfigurationError(
            "Bedrock eval requires YOUTH_COMPASS_MODEL__PROVIDER=bedrock and MODEL__MODEL_ID"
        )
    from adapters.aws.bedrock_model import BedrockModelProvider

    return ModelQueryDecomposer(
        BedrockModelProvider(
            model.model_id,
            region=model.region,
            timeout_seconds=model.timeout_seconds,
            max_attempts=model.max_attempts,
        ),
        capabilities,
    )


if __name__ == "__main__":
    main()
