"""In-memory registries for stable feature and decision contracts."""

from collections.abc import Iterable

from youth_compass.decisioning.contracts import DecisionProfile, FeatureDefinition


class FeatureRegistry:
    """Resolve immutable feature definitions by stable code and version."""

    def __init__(self, definitions: Iterable[FeatureDefinition] = ()) -> None:
        self._definitions: dict[tuple[str, str], FeatureDefinition] = {}
        self._latest: dict[str, str] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: FeatureDefinition) -> None:
        key = (definition.feature_code, definition.version)
        existing = self._definitions.get(key)
        if existing is not None and existing != definition:
            raise ValueError(
                f"feature {definition.feature_code!r}@{definition.version!r} is already registered"
            )
        self._definitions[key] = definition
        self._latest[definition.feature_code] = definition.version

    def get(self, feature_code: str, version: str | None = None) -> FeatureDefinition:
        resolved_version = version or self._latest.get(feature_code)
        if resolved_version is None:
            raise KeyError(f"unknown feature {feature_code!r}")
        try:
            return self._definitions[(feature_code, resolved_version)]
        except KeyError as exc:
            raise KeyError(f"unknown feature {feature_code!r}@{resolved_version!r}") from exc

    def list(self) -> tuple[FeatureDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))


class DecisionProfileRegistry:
    """Resolve immutable decision profiles by code and version."""

    def __init__(self, profiles: Iterable[DecisionProfile] = ()) -> None:
        self._profiles: dict[tuple[str, str], DecisionProfile] = {}
        self._latest: dict[str, str] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: DecisionProfile) -> None:
        key = (profile.profile_code, profile.version)
        existing = self._profiles.get(key)
        if existing is not None and existing != profile:
            raise ValueError(
                f"decision profile {profile.profile_code!r}@{profile.version!r} exists"
            )
        self._profiles[key] = profile
        self._latest[profile.profile_code] = profile.version

    def get(self, profile_code: str, version: str | None = None) -> DecisionProfile:
        resolved_version = version or self._latest.get(profile_code)
        if resolved_version is None:
            raise KeyError(f"unknown decision profile {profile_code!r}")
        try:
            return self._profiles[(profile_code, resolved_version)]
        except KeyError as exc:
            raise KeyError(
                f"unknown decision profile {profile_code!r}@{resolved_version!r}"
            ) from exc

    def list(self) -> tuple[DecisionProfile, ...]:
        return tuple(self._profiles[key] for key in sorted(self._profiles))
