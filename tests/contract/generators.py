"""Deterministic seeded generators for the property tests.

Feature: aws-stage1-foundation, design 7.1 (property tests without a PBT library).

Requirement 3 criterion 1 caps the dev group at ten entries, which excludes
Hypothesis. These generators stand in: a fixed default seed for reproducibility,
overridable via ``YOUTH_COMPASS_PROPERTY_SEED``. Each property test loops over
``samples(n)`` at 100 or more iterations. On failure the test reports the seed and
the failing sample, so a run is replayable. There is no shrinking; the boundary
values the requirements name are always included by construction.
"""

import os
import random
from collections.abc import Iterator

DEFAULT_SEED = 20260912


def seed() -> int:
    raw = os.environ.get("YOUTH_COMPASS_PROPERTY_SEED")
    return int(raw) if raw and raw.isdigit() else DEFAULT_SEED


def rng() -> random.Random:
    return random.Random(seed())


def samples(n: int = 100) -> Iterator[int]:
    """Yield ``n`` iteration indices; the count is the iteration budget."""

    yield from range(n)


# --- ObjectStore inputs (Property 5 boundary matrix) -------------------------

# Requirement 2 criterion 7: sizes 0, 1, and at least 1 MiB; keys 1 and >= 256.
BOUNDARY_SIZES = (0, 1, 1024 * 1024, 1024 * 1024 + 7)
BOUNDARY_KEY_LENGTHS = (1, 256, 300)


def payloads(source: random.Random, *, include_boundaries: bool = True) -> list[bytes]:
    values: list[bytes] = []
    if include_boundaries:
        values = [source.randbytes(size) for size in BOUNDARY_SIZES]
    for _ in range(4):
        values.append(source.randbytes(source.randint(2, 4096)))
    return values


_KEY_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-_/."


def object_keys(source: random.Random, *, include_boundaries: bool = True) -> list[str]:
    keys: list[str] = []
    if include_boundaries:
        keys = [
            "".join(source.choice(_KEY_ALPHABET) for _ in range(n)) for n in BOUNDARY_KEY_LENGTHS
        ]
    for _ in range(4):
        n = source.randint(2, 64)
        keys.append("".join(source.choice(_KEY_ALPHABET) for _ in range(n)))
    return keys
