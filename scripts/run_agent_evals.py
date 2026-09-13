"""Run agent evals offline or against the configured Bedrock model.

Two suites, because they answer different questions. `routing` grades the plan:
did the question decompose into the right operations and reach the right tools.
`answers` runs the whole agent over the local data root and grades the turn a
user would actually read — status, numbers, citations, language, caveats, and
charts. A plan can be perfect and the answer still wrong, so neither suite
substitutes for the other.
"""

import argparse
import asyncio
from pathlib import Path

from youth_compass.agent import (
    AgentEvalHarness,
    AnswerEvalHarness,
    DeterministicQueryDecomposer,
    ModelQueryDecomposer,
    QueryDecomposer,
    SmartToolRouter,
    ToolCapabilityRegistry,
    default_decision_capabilities,
    load_answer_eval_cases,
    load_eval_cases,
    register_acquisition_capabilities,
    register_forecast_capabilities,
    register_impact_capabilities,
    register_observation_capabilities,
)
from youth_compass.config import ModelProviderName, load_settings
from youth_compass.domain import ConfigurationError


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("routing", "answers", "all"), default="routing")
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument("--provider", choices=("deterministic", "bedrock"), default="deterministic")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path("data"),
        help="Local data root the answer suite reads published datasets from.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optionally persist the machine-readable report as JSON.",
    )
    args = parser.parse_args()
    failed = 0
    if args.suite in ("routing", "all"):
        failed += _run_routing(
            args.cases or Path("evals/agent-routing.jsonl"), args.provider, args.output
        )
    if args.suite in ("answers", "all"):
        failed += _run_answers(args.cases or Path("evals/agent-answers.jsonl"), args.data_root)
    if failed:
        raise SystemExit(1)


def _run_routing(cases_path: Path, provider: str, output: Path | None = None) -> int:
    cases = load_eval_cases(cases_path)
    registry = _eval_capabilities()
    decomposer = _decomposer(provider, registry)
    report = asyncio.run(AgentEvalHarness(decomposer, SmartToolRouter(registry)).run(cases))
    print("== routing ==")
    print(report.model_dump_json(indent=2))
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report.failed


def _run_answers(cases_path: Path, data_root: Path) -> int:
    """Run every case through the same service the API serves."""

    # Imported here so the routing suite stays runnable without the API layer.
    from apps.api.dependencies import LocalRuntime

    cases = load_answer_eval_cases(cases_path)
    runtime = LocalRuntime(data_root)
    report = asyncio.run(AnswerEvalHarness(runtime.copilot()).run(cases))
    print("== answers ==")
    for result in report.results:
        mark = "PASS" if result.passed else "FAIL"
        print(f"  [{mark}] {result.case_id}")
        if result.error:
            print(f"         crashed: {result.error}")
        for failure in result.failures:
            print(f"         {failure}")
    print(
        f"  {report.passed}/{report.total} passed"
        + (f"; weakest: {', '.join(report.failing_dimensions)}" if report.failed else "")
    )
    return report.failed


def _eval_capabilities() -> ToolCapabilityRegistry:
    """Register every capability the served copilot registers.

    The harness judges routing, so its registry has to be the runtime's registry.
    Registering fewer capabilities here does not test a smaller system, it
    reports a routing failure for a tool the API would have found: a forecast
    question landed in `missing_operations` only because this script had not
    registered `forecast_metric`. Kept in the same order as
    `apps.api.dependencies.LocalRuntime.copilot`.
    """

    registry = default_decision_capabilities()
    register_observation_capabilities(registry)
    register_forecast_capabilities(registry)
    register_acquisition_capabilities(registry)
    register_impact_capabilities(registry)
    return registry


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
