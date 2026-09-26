"""Localized names of supported measures, shared by narratives and charts."""

from youth_compass.ontology.naming import humanize_code

METRIC_NAMES: dict[str, dict[str, str]] = {
    "population_count": {"zh": "人口數", "vi": "Dân số", "en": "Population count"},
    "education_population": {"zh": "教育程度人口數", "en": "Education population"},
    "unemployment_rate": {"zh": "失業率", "vi": "Tỷ lệ thất nghiệp", "en": "Unemployment rate"},
    "labor_participation_rate": {"zh": "勞動力參與率", "en": "Labor force participation rate"},
    "workforce_age_share": {"zh": "就業者年齡結構比", "en": "Workforce age share"},
    "literacy_rate": {"zh": "15歲以上識字率", "en": "Literacy rate (ages 15+)"},
    "population_age_share": {"zh": "人口年齡結構比", "en": "Population age share"},
}


def metric_name(code: str, language: str) -> str:
    return METRIC_NAMES.get(code, {}).get(language, humanize_code(code))


def metric_scope_notes(code: str, language: str) -> tuple[str, ...]:
    notes = {
        "labor_participation_rate": (
            "全市年齡組與性別資料。25–44歲等組別涵蓋非青年人口，不能視為18–35歲專屬參與率。",  # noqa: RUF001
            "Citywide age/sex groups, including non-youth ages; "
            "not an 18-35-specific participation rate.",
        ),
        "workforce_age_share": (
            "全市各性別就業者中的年齡結構百分比，並非就業率或就業人數。",  # noqa: RUF001
            "Citywide age shares within each sex's employed population; "
            "not employment rates or counts.",
        ),
        "literacy_rate": (
            "全市15歲以上人口識字率，沒有18–35歲或行政區細分。",  # noqa: RUF001
            "Citywide literacy for ages 15+, without an 18-35-only or district breakdown.",
        ),
        "population_age_share": (
            "全市各性別人口中的年齡結構比。15–64歲是青壯年，不能當成18–35歲青年占比。",  # noqa: RUF001
            "Citywide age shares by sex; ages 15-64 are not equivalent to youth ages 18-35.",
        ),
    }
    if code not in notes:
        return ()
    return (notes[code][0 if language == "zh" else 1],)
