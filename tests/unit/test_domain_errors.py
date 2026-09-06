"""Domain error hierarchy: every port-boundary error derives from one base."""

import inspect

import pytest

from youth_compass.domain import errors

EXPECTED_SUBCLASSES = (
    "ConfigurationError",
    "DatasetNotFoundError",
    "ForecastNotAvailableError",
    "ModelInvocationError",
    "ObjectNotFoundError",
    "QueryExecutionError",
    "QueryNotPermittedError",
    "TrainingRejectedError",
    "WorkflowStateError",
)


def test_base_derives_from_exception() -> None:
    assert issubclass(errors.YouthCompassError, Exception)


@pytest.mark.parametrize("name", EXPECTED_SUBCLASSES)
def test_subclass_derives_from_base(name: str) -> None:
    cls = getattr(errors, name)
    assert issubclass(cls, errors.YouthCompassError)
    assert cls is not errors.YouthCompassError


def test_module_declares_exactly_the_expected_hierarchy() -> None:
    declared = {
        name
        for name, obj in vars(errors).items()
        if inspect.isclass(obj) and issubclass(obj, BaseException)
    }
    assert declared == {"YouthCompassError", *EXPECTED_SUBCLASSES}


def test_module_contains_only_exception_classes() -> None:
    public = [
        name
        for name, obj in vars(errors).items()
        if not name.startswith("_") and (inspect.isclass(obj) or inspect.isfunction(obj))
    ]
    for name in public:
        assert issubclass(getattr(errors, name), BaseException), name


@pytest.mark.parametrize("name", ("YouthCompassError", *EXPECTED_SUBCLASSES))
def test_reexported_from_domain_package(name: str) -> None:
    import youth_compass.domain as domain

    assert getattr(domain, name) is getattr(errors, name)
    assert name in domain.__all__


def test_errors_carry_a_message() -> None:
    err = errors.ObjectNotFoundError("s3://bucket/missing.parquet")
    assert str(err) == "s3://bucket/missing.parquet"
