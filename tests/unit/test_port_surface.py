"""Port surface conformance.

Feature: aws-stage1-foundation
Properties 1 (surface conformance), 2 (runtime_checkable), 3 (self-documentation).
"""

import ast
import inspect
import pkgutil
import sys
import typing
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol, get_args, get_origin, get_type_hints

import pytest
from pydantic import BaseModel

import youth_compass.ports as ports_pkg
from youth_compass.ports import (
    CheckpointStore,
    Clock,
    DataCatalog,
    EventBus,
    ForecastService,
    ModelProvider,
    ObjectStore,
    QueryEngine,
    SourceAdapter,
    SourceConnector,
    WorkflowRunner,
)

PORTS_DIR = Path(ports_pkg.__file__).parent

# Requirement 1 criteria 1, 2, 3, 10: the exact declared surface.
EXPECTED_SURFACE: dict[type, dict[str, tuple[str, ...]]] = {
    ObjectStore: {
        "put": ("key", "content", "metadata"),
        "get": ("uri",),
        "list": ("prefix",),
        "exists": ("uri",),
    },
    DataCatalog: {
        "register": ("dataset",),
        "get": ("dataset_id",),
        "search_compatible": ("profile",),
        "list_datasets": (),
        "list_versions": ("dataset_id",),
    },
    QueryEngine: {"execute": ("query",)},
    ModelProvider: {"generate": ("request",)},
    ForecastService: {
        "get_forecast": ("request",),
        "trigger_training": ("request",),
    },
    WorkflowRunner: {
        "start_ingestion": ("request",),
        "get_job_reference": ("job_id",),
        "resume_after_approval": ("job_id", "decision"),
    },
    CheckpointStore: {"save": ("workflow_id", "checkpoint"), "load": ("workflow_id",)},
    EventBus: {"publish": ("event",), "subscribe": ("event_type", "handler")},
    Clock: {"now": ()},
    SourceAdapter: {"normalize": ("file_name", "content")},
    SourceConnector: {
        "discover": ("requirement",),
        "get": ("candidate_id",),
        "fetch": ("candidate",),
    },
}

EXPECTED_MODULE_NAMES = {
    ObjectStore: "object_store",
    DataCatalog: "catalog",
    QueryEngine: "query_engine",
    ModelProvider: "model_provider",
    ForecastService: "forecast_service",
    WorkflowRunner: "workflow_runner",
    CheckpointStore: "checkpoint_store",
    EventBus: "event_bus",
    Clock: "clock",
    SourceAdapter: "source_adapter",
    SourceConnector: "source_connector",
}

# Requirement 1 criterion 11.
NAMED_PAYLOADS = {
    "QuerySpec": "query_engine",
    "QueryResult": "query_engine",
    "ModelRequest": "model_provider",
    "ModelResponse": "model_provider",
    "ForecastRequest": "forecast_service",
    "ForecastResult": "forecast_service",
    "TrainingRequest": "forecast_service",
    "TrainingRun": "forecast_service",
    "IngestionRequest": "workflow_runner",
    "JobReference": "workflow_runner",
    "ApprovalDecision": "workflow_runner",
    "NormalizedTabularSource": "source_adapter",
    "AcquiredSource": "source_connector",
    "DataRequirement": "source_connector",
    "SourceCandidate": "source_connector",
}

PERMITTED_SCALARS = {str, int, float, bool, bytes, type(None), datetime, date}
FORBIDDEN_BARE = {dict, list, tuple, set, frozenset}
ALL_PORTS = list(EXPECTED_SURFACE)


def _port_modules() -> list[str]:
    return [m.name for m in pkgutil.iter_modules([str(PORTS_DIR)])]


def _unwrap(annotation: object) -> object:
    alias = getattr(typing, "TypeAliasType", None)
    if alias is not None and isinstance(annotation, alias):
        return annotation.__value__
    return annotation


def _assert_annotation_ok(annotation: object, where: str) -> None:
    annotation = _unwrap(annotation)
    if annotation is None:
        annotation = type(None)  # Callable[..., None] yields the literal None
    assert annotation is not Any, f"{where}: typing.Any is forbidden"
    assert annotation is not Path, f"{where}: pathlib.Path is forbidden"
    if annotation in PERMITTED_SCALARS:
        return
    if annotation in FORBIDDEN_BARE:
        raise AssertionError(f"{where}: bare {annotation!r} must be parameterized")
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return
    if inspect.isclass(annotation) and issubclass(annotation, str):
        return  # StrEnum payload members
    origin = get_origin(annotation)
    if origin is not None:
        args = get_args(annotation)
        assert args, f"{where}: {annotation!r} has no type arguments"
        for arg in args:
            if arg is Ellipsis or isinstance(arg, list):
                continue
            _assert_annotation_ok(arg, where)
        return
    raise AssertionError(f"{where}: unsupported annotation {annotation!r}")


# --- Property 1 -------------------------------------------------------------


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_property_1_annotations_are_precise(port: type) -> None:
    for method_name in EXPECTED_SURFACE[port]:
        func = getattr(port, method_name)
        hints = get_type_hints(func)
        assert hints, f"{port.__name__}.{method_name} has no annotations"
        for name, annotation in hints.items():
            _assert_annotation_ok(annotation, f"{port.__name__}.{method_name}:{name}")


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_property_1_every_parameter_and_return_is_annotated(port: type) -> None:
    for method_name, params in EXPECTED_SURFACE[port].items():
        func = getattr(port, method_name)
        hints = get_type_hints(func)
        assert "return" in hints, f"{port.__name__}.{method_name} lacks a return annotation"
        for param in params:
            assert param in hints, f"{port.__name__}.{method_name} lacks annotation for {param}"


@pytest.mark.parametrize("module_name", _port_modules())
def test_property_1_imports_are_restricted(module_name: str) -> None:
    source = PORTS_DIR / f"{module_name}.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.append(node.module)
    for root in roots:
        top = root.split(".")[0]
        if root.startswith("youth_compass."):
            assert root.startswith("youth_compass.domain") or root.startswith(
                "youth_compass.ports"
            ), f"{module_name}: may not import {root}"
        else:
            assert top == "pydantic" or top in sys.stdlib_module_names, (
                f"{module_name}: third-party import {root} is not permitted"
            )


@pytest.mark.parametrize(("payload", "module_name"), sorted(NAMED_PAYLOADS.items()))
def test_property_1_named_payloads_live_beside_their_port(payload: str, module_name: str) -> None:
    obj = getattr(ports_pkg, payload)
    assert inspect.isclass(obj) and issubclass(obj, BaseModel)
    assert obj.__module__ == f"youth_compass.ports.{module_name}"


def test_property_1_domain_types_are_imported_not_redefined() -> None:
    from youth_compass.ports.catalog import DatasetMetadata, DatasetProfile

    assert DatasetMetadata.__module__.startswith("youth_compass.domain")
    assert DatasetProfile.__module__.startswith("youth_compass.domain")


def test_property_1_no_type_ignore_or_any_in_port_sources() -> None:
    offenders: list[str] = []
    for module_name in _port_modules():
        text = (PORTS_DIR / f"{module_name}.py").read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "type: ignore" in line:
                offenders.append(f"{module_name}.py:{lineno}: type: ignore")
            if "Any" in line and "Protocol" not in line and not line.lstrip().startswith("#"):
                offenders.append(f"{module_name}.py:{lineno}: Any")
    assert not offenders, offenders


# --- Property 2 -------------------------------------------------------------


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_property_2_runtime_checkable_tracks_method_presence(port: type) -> None:
    assert getattr(port, "_is_runtime_protocol", False), f"{port.__name__} not @runtime_checkable"
    declared = sorted(EXPECTED_SURFACE[port])
    total = len(declared)
    for mask in range(1 << total):
        subset = [declared[i] for i in range(total) if mask >> i & 1]

        class Candidate:
            pass

        for name in subset:
            setattr(Candidate, name, lambda self, *a, **k: None)
        expected = len(subset) == total
        assert isinstance(Candidate(), port) is expected, (
            f"{port.__name__}: subset {subset} -> expected {expected}"
        )


# --- Property 3 -------------------------------------------------------------

REQUIRED_DOCSTRING_FACTS = (
    ("Stage 1 proposal", "stage-1-proposal origin"),
    ("backend workstream may", "amendable-by-backend statement"),
    ("docs/0", "source document and section"),
)


@pytest.mark.parametrize("module_name", _port_modules())
def test_property_3_module_docstring_states_three_facts(module_name: str) -> None:
    module = __import__(f"youth_compass.ports.{module_name}", fromlist=["_"])
    doc = inspect.getdoc(module) or ""
    assert doc.strip(), f"{module_name} has no module docstring"
    for needle, description in REQUIRED_DOCSTRING_FACTS:
        assert needle in doc, f"{module_name} docstring is missing the {description}"


def test_property_3_workflow_runner_records_itself_as_proposed_addition() -> None:
    from youth_compass.ports import workflow_runner

    doc = inspect.getdoc(workflow_runner) or ""
    assert "PROPOSED ADDITION" in doc
    assert "docs/07-project-structure.md" in doc


# --- Requirement 1 criteria 1, 2, 10: exact surface --------------------------


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_declared_methods_and_parameter_names_match_the_table(port: type) -> None:
    public = {
        name
        for name, _ in inspect.getmembers(port, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == set(EXPECTED_SURFACE[port]), f"{port.__name__} surface drifted"
    for method_name, expected_params in EXPECTED_SURFACE[port].items():
        sig = inspect.signature(getattr(port, method_name))
        actual = tuple(p for p in sig.parameters if p != "self")
        assert actual == expected_params, f"{port.__name__}.{method_name}{actual}"


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_each_protocol_lives_in_its_fixed_filename(port: type) -> None:
    assert port.__module__ == f"youth_compass.ports.{EXPECTED_MODULE_NAMES[port]}"


def test_exactly_one_protocol_per_module() -> None:
    for module_name in _port_modules():
        module = __import__(f"youth_compass.ports.{module_name}", fromlist=["_"])
        protocols = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__ and Protocol in getattr(obj, "__bases__", ())
        ]
        assert len(protocols) == 1, f"{module_name}: {[p.__name__ for p in protocols]}"


def test_model_provider_generate_is_async() -> None:
    assert inspect.iscoroutinefunction(ModelProvider.generate)


def test_eleven_protocols_across_eleven_modules() -> None:
    assert len(ALL_PORTS) == 11
    assert len(_port_modules()) == 11


def test_object_store_put_metadata_is_parameterized_str_mapping() -> None:
    hints = get_type_hints(ObjectStore.put)
    assert hints["metadata"] == dict[str, str]
    assert hints["return"] is str


def test_checkpoint_load_returns_optional_checkpoint() -> None:
    from youth_compass.ports import WorkflowCheckpoint

    assert get_type_hints(CheckpointStore.load)["return"] == WorkflowCheckpoint | None
