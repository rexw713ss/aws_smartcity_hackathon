"""ObjectStore contract.

Feature: aws-stage1-foundation
Properties 5 (round-trip), 6 (idempotent overwrite), 7 (prefix listing),
8 (unwritten URI raises the domain error).
"""

import pytest

from tests.contract import generators as gen
from youth_compass.domain.errors import ObjectNotFoundError
from youth_compass.ports import ObjectStore


class TestObjectStoreContract:
    def test_property_5_round_trip_preserves_bytes(self, object_store: ObjectStore) -> None:
        source = gen.rng()
        # Build the key/payload space once; the boundary payloads include a 1 MiB
        # value, so regenerating them per iteration would dominate the runtime.
        keys = gen.object_keys(source)
        payloads = gen.payloads(source)
        for i in gen.samples(100):
            key = source.choice(keys)
            payload = source.choice(payloads)
            # Namespace the key per iteration so one test's writes do not collide.
            scoped = f"{i}/{key}"
            uri = object_store.put(scoped, payload, {})
            read = object_store.get(uri)
            assert read == payload, f"seed={gen.seed()} key_len={len(key)} size={len(payload)}"
            assert len(read) == len(payload)

    def test_property_6_overwrite_leaves_one_object_and_one_listing(
        self, object_store: ObjectStore
    ) -> None:
        source = gen.rng()
        keys = gen.object_keys(source)
        payloads = gen.payloads(source)
        for i in gen.samples(100):
            key = f"{i}/{source.choice(keys)}"
            first, second = source.choice(payloads), source.choice(payloads)
            object_store.put(key, first, {})
            uri = object_store.put(key, second, {})
            assert object_store.get(uri) == second, f"seed={gen.seed()}"
            assert object_store.list(key).count(key) == 1

    def test_property_7_prefix_listing_is_exact_set_equality(
        self, object_store: ObjectStore
    ) -> None:
        source = gen.rng()
        for i in gen.samples(100):
            # Per-iteration prefixes keep the exact-set-equality assertion honest
            # without a fresh store, since prior iterations sit under other prefixes.
            a, b = f"a{i}/", f"b{i}/"
            under = {f"{a}{k}-{source.randint(0, 999)}" for k in range(source.randint(1, 5))}
            other = {f"{b}{k}-{source.randint(0, 999)}" for k in range(source.randint(1, 5))}
            for key in under | other:
                object_store.put(key, b"x", {})
            assert set(object_store.list(a)) == under, f"seed={gen.seed()}"
            assert set(object_store.list(b)) == other
            assert object_store.list(f"c{i}/") == []

    def test_property_8_get_of_unwritten_uri_raises_domain_error(
        self, object_store: ObjectStore
    ) -> None:
        with pytest.raises(ObjectNotFoundError):
            object_store.get("mem://never-written")

    def test_exists_is_false_before_and_true_after_put(self, object_store: ObjectStore) -> None:
        uri = "mem://k1"
        assert object_store.exists(uri) is False
        returned = object_store.put("k1", b"data", {})
        assert object_store.exists(returned) is True

    def test_put_uri_is_immediately_readable_and_listable(self, object_store: ObjectStore) -> None:
        uri = object_store.put("prefix/key", b"data", {})
        assert object_store.exists(uri) is True
        assert "prefix/key" in object_store.list("prefix/")

    def test_zero_byte_payload_round_trips(self, object_store: ObjectStore) -> None:
        uri = object_store.put("empty", b"", {})
        assert object_store.get(uri) == b""
