from pathlib import Path

import pytest

from youth_compass.transformation import TransformOptions


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"approved_by": ""}, "approved_by"),
        ({"dataset_id": "Bad-ID"}, "dataset_id"),
        ({"max_rows": 0}, "max_rows"),
        ({"batch_size": 99}, "batch_size"),
        ({"max_rejection_rate": 1.1}, "max_rejection_rate"),
        ({"transformation_version": ""}, "transformation_version"),
    ],
)
def test_transform_options_reject_unsafe_values(
    overrides: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "approved_by": "reviewer",
        "curated_root": Path("curated"),
        "quarantine_root": Path("quarantined"),
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        TransformOptions(**values)  # type: ignore[arg-type]
