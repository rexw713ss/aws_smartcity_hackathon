"""Contract-suite fixtures and the credential/endpoint guards.

Feature: aws-stage1-foundation, design 3.3.2 and diagram 1.3.

Session start, in order:
  1. Guard before mutate: if any real AWS credential variable is set, abort the
     session before any case runs (Requirement 2 criterion 18).
  2. Snapshot all five AWS variables, set placeholders, unset AWS_PROFILE, set
     the region (Requirement 2 criterion 6).
  3. Restore every variable in a finally, absent staying absent, on pass or fail.

Each Port's registry becomes a function-scoped parametrized fixture, so one
contract class runs once per bound adapter with the class body untouched.
"""

import os
from collections.abc import Iterator

import pytest

# Importing these packages populates the registries via their adapter factories.
import tests.contract.reference

try:
    # Imported for their registration side effects (register_* decorators).
    import tests.contract.aws
    import tests.contract.aws.athena_query
    import tests.contract.aws.eventbridge_bus
    import tests.contract.aws.glue_catalog
    import tests.contract.aws.s3_store
    import tests.contract.aws.step_functions_runner  # noqa: F401
except ImportError:
    pass  # AWS adapters not yet present; reference adapters suffice
from tests.contract.registry import (
    CATALOG_FACTORIES,
    CHECKPOINT_STORE_FACTORIES,
    CLOCK_FACTORIES,
    EVENT_BUS_FACTORIES,
    FORECAST_SERVICE_FACTORIES,
    MODEL_PROVIDER_FACTORIES,
    OBJECT_STORE_FACTORIES,
    QUERY_ENGINE_FACTORIES,
    WORKFLOW_RUNNER_FACTORIES,
)

_CREDENTIAL_VARS = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
)
_ALL_VARS = (*_CREDENTIAL_VARS, "AWS_DEFAULT_REGION")
_PLACEHOLDER = "testing"
_REGION = "ap-northeast-1"


@pytest.fixture(scope="session", autouse=True)
def _neutralize_aws_credentials() -> Iterator[None]:
    # 1. Guard before mutate.
    ambient = [v for v in _CREDENTIAL_VARS if os.environ.get(v)]
    if ambient:
        pytest.exit(
            "ambient AWS credentials detected in "
            f"{', '.join(ambient)}; refusing to run the contract suite against "
            "real credentials. Unset them and re-run.",
            returncode=3,
        )

    # 2. Snapshot (including absence) and set placeholders.
    snapshot = {v: os.environ.get(v) for v in _ALL_VARS}
    os.environ["AWS_ACCESS_KEY_ID"] = _PLACEHOLDER
    os.environ["AWS_SECRET_ACCESS_KEY"] = _PLACEHOLDER
    os.environ["AWS_SESSION_TOKEN"] = _PLACEHOLDER
    os.environ.pop("AWS_PROFILE", None)
    os.environ["AWS_DEFAULT_REGION"] = _REGION
    try:
        yield
    finally:
        # 3. Restore exactly; absent stays absent.
        for var, value in snapshot.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value


def _make_fixture(registry: dict[str, object], label: str):  # type: ignore[no-untyped-def]
    @pytest.fixture(params=sorted(registry), ids=lambda name: f"{label}[{name}]")
    def fixture(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
        factory = registry[request.param]
        with factory() as adapter:  # type: ignore[operator]
            yield adapter

    return fixture


object_store = _make_fixture(OBJECT_STORE_FACTORIES, "objectstore")  # type: ignore[arg-type]
catalog = _make_fixture(CATALOG_FACTORIES, "catalog")  # type: ignore[arg-type]
query_engine = _make_fixture(QUERY_ENGINE_FACTORIES, "queryengine")  # type: ignore[arg-type]
model_provider = _make_fixture(MODEL_PROVIDER_FACTORIES, "modelprovider")  # type: ignore[arg-type]
forecast_service = _make_fixture(FORECAST_SERVICE_FACTORIES, "forecastservice")  # type: ignore[arg-type]
workflow_runner = _make_fixture(WORKFLOW_RUNNER_FACTORIES, "workflowrunner")  # type: ignore[arg-type]
checkpoint_store = _make_fixture(CHECKPOINT_STORE_FACTORIES, "checkpointstore")  # type: ignore[arg-type]
event_bus = _make_fixture(EVENT_BUS_FACTORIES, "eventbus")  # type: ignore[arg-type]
clock = _make_fixture(CLOCK_FACTORIES, "clock")  # type: ignore[arg-type]
