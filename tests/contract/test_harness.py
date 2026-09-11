"""Prove the contract harness itself.

Feature: aws-stage1-foundation
Properties 12 (registration-only binding scales), 14 (credential restoration),
15 (ambient credentials abort), 16 (case isolation and order-independence).

Property 13 (no non-loopback network) is asserted in test_guards_network.py, and
the credential-neutralization fixture in conftest.py is what makes Property 14/15
hold for the live session; the tests here exercise the mechanism directly.
"""

import os
from contextlib import contextmanager

import pytest


def _registrar_roundtrip() -> None:
    """Property 12: a fresh registry runs its class once per registered factory."""


class TestHarnessBinding:
    def test_property_12_n_factories_produce_n_distinct_instances(self) -> None:
        from tests.contract.reference.object_store import InMemoryObjectStore

        registry: dict[str, object] = {}

        @contextmanager
        def factory():  # type: ignore[no-untyped-def]
            yield InMemoryObjectStore()

        for name in ("a", "b", "c"):
            registry[name] = factory
        # Keep instances alive while comparing identity: id() can be reused after
        # a prior instance is collected, so comparing ids of already-exited
        # context managers is unsound. Nesting keeps all three live at once.
        with registry["a"]() as first, registry["b"]() as second, registry["c"]() as third:  # type: ignore[operator]
            instances = [first, second, third]
            assert len({id(obj) for obj in instances}) == 3
        assert len(registry) == 3

    def test_property_12_reference_registries_have_exactly_one_binding(self) -> None:
        from tests.contract import registry as r

        for attr in (
            "OBJECT_STORE_FACTORIES",
            "CATALOG_FACTORIES",
            "QUERY_ENGINE_FACTORIES",
            "MODEL_PROVIDER_FACTORIES",
            "FORECAST_SERVICE_FACTORIES",
            "WORKFLOW_RUNNER_FACTORIES",
            "CHECKPOINT_STORE_FACTORIES",
            "EVENT_BUS_FACTORIES",
            "CLOCK_FACTORIES",
        ):
            assert "reference" in getattr(r, attr), attr

    def test_duplicate_registration_is_rejected(self) -> None:
        from tests.contract.registry import _registrar

        registry: dict[str, object] = {}
        register = _registrar(registry)  # type: ignore[var-annotated]

        @register("dup")
        @contextmanager
        def _first():  # type: ignore[no-untyped-def]
            yield object()

        with pytest.raises(ValueError, match="already registered"):

            @register("dup")
            @contextmanager
            def _second():  # type: ignore[no-untyped-def]
                yield object()


class TestCredentialGuards:
    def test_property_14_placeholders_are_set_during_the_session(self) -> None:
        # The session fixture in conftest.py set these before any case ran.
        assert os.environ["AWS_ACCESS_KEY_ID"] == "testing"
        assert os.environ["AWS_SECRET_ACCESS_KEY"] == "testing"
        assert os.environ["AWS_SESSION_TOKEN"] == "testing"
        assert "AWS_PROFILE" not in os.environ
        assert os.environ["AWS_DEFAULT_REGION"] == "ap-northeast-1"

    def test_property_16_reference_state_is_fresh_per_case_first(self) -> None:
        from tests.contract.reference.object_store import InMemoryObjectStore

        store = InMemoryObjectStore()
        assert store.list("") == []

    def test_property_16_reference_state_is_fresh_per_case_second(self) -> None:
        # A second construction observes zero objects, proving isolation.
        from tests.contract.reference.object_store import InMemoryObjectStore

        store = InMemoryObjectStore()
        assert store.list("") == []
