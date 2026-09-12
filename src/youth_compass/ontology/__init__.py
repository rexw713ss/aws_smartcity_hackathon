"""Local ontology: multilingual place names and demographic concept resolution."""

from youth_compass.ontology.districts import (
    DISTRICT_NAMES,
    DistrictNames,
    DistrictResolution,
    NameLanguage,
    district_names,
    district_spellings,
    extract_districts,
    localized_district_name,
    resolve_district_name,
)
from youth_compass.ontology.naming import (
    display_name,
    humanize_code,
    question_language,
    readable_entity_name,
    readable_feature_name,
)
from youth_compass.ontology.population import (
    RegistrationBasis,
    registration_basis_caveat,
    resolve_registration_basis,
)
from youth_compass.ontology.topics import (
    TOPIC_NAMES,
    TopicNames,
    extract_topics,
    resolve_topic_name,
    topic_spellings,
)

__all__ = [
    "DISTRICT_NAMES",
    "TOPIC_NAMES",
    "DistrictNames",
    "DistrictResolution",
    "NameLanguage",
    "RegistrationBasis",
    "TopicNames",
    "display_name",
    "district_names",
    "district_spellings",
    "extract_districts",
    "extract_topics",
    "humanize_code",
    "localized_district_name",
    "question_language",
    "readable_entity_name",
    "readable_feature_name",
    "registration_basis_caveat",
    "resolve_district_name",
    "resolve_registration_basis",
    "resolve_topic_name",
    "topic_spellings",
]
