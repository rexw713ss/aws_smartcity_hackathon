"""Gender label normalization without inventing unsupported categories."""

_ALIASES = {
    "m": "male",
    "male": "male",
    "man": "male",
    "男": "male",
    "男性": "male",
    "f": "female",
    "female": "female",
    "woman": "female",
    "女": "female",
    "女性": "female",
    "其他": "other",
    "other": "other",
    "未知": "unknown",
    "unknown": "unknown",
}


def normalize_gender(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().casefold()
    if not normalized:
        return None
    return _ALIASES.get(normalized)
