"""TaggedStack: a Stack that enforces the four mandatory cost-allocation tags.

Validation runs before ``super().__init__``, so a missing, empty, or over-long
tag raises before any resource or template exists. All problems are reported
together, because fixing one tag per synth cycle is not viable on competition
morning.
"""

from collections.abc import Mapping
from typing import Any

from aws_cdk import Stack, Tags
from constructs import Construct

from infra.environments import MANDATORY_TAGS
from infra.errors import InfraConfigError

_MAX_TAG_VALUE = 255


class TaggedStack(Stack):
    """Base stack that applies and enforces mandatory cost-allocation tags."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        tags: Mapping[str, str],
        **kwargs: Any,
    ) -> None:
        problems: list[str] = []
        for key in MANDATORY_TAGS:
            value = tags.get(key)
            if value is None:
                problems.append(f"{key}: missing")
            elif not value.strip():
                problems.append(f"{key}: empty")
        problems += [
            f"{key}: exceeds {_MAX_TAG_VALUE} characters"
            for key, value in tags.items()
            if value is not None and len(value) > _MAX_TAG_VALUE
        ]
        if problems:
            raise InfraConfigError("mandatory cost-allocation tags invalid: " + "; ".join(problems))

        super().__init__(scope, construct_id, **kwargs)
        for key, value in tags.items():
            Tags.of(self).add(key, value)
