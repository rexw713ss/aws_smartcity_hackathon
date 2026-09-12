import json
from unittest.mock import patch

from apps.dashboard.api_client import (
    YouthCompassApi,
    _analytics_query,
    _decode_error,
    _multipart_body,
)


def test_analytics_query_omits_empty_period() -> None:
    assert _analytics_query("population", "population_count", None) == {
        "datasetId": "population",
        "metricCode": "population_count",
    }


def test_error_envelope_is_safely_decoded() -> None:
    raw = json.dumps(
        {"error": {"code": "DATASET_NOT_FOUND", "message": "dataset was not found"}}
    ).encode()

    assert _decode_error(raw) == {
        "code": "DATASET_NOT_FOUND",
        "message": "dataset was not found",
    }
    assert _decode_error(b"not-json") == {"message": "The API request failed."}


def test_multipart_body_contains_fields_and_exact_file_content() -> None:
    content = b"year,district,population\n2025,01,100\n"

    body = _multipart_body(
        "boundary",
        {"submitted_by": "reviewer@example.com", "topic_hint": "population"},
        "sample.csv",
        content,
    )

    assert b'name="submitted_by"' in body
    assert b"reviewer@example.com" in body
    assert b'filename="sample.csv"' in body
    assert content in body
    assert body.endswith(b"--boundary--\r\n")


def test_copilot_client_uses_camel_case_api_contract() -> None:
    api = YouthCompassApi("http://api.test")
    with patch.object(api, "_request", return_value={"status": "answered"}) as request:
        result = api.copilot(
            "Where should I buy a home?",
            entity_ids=["banqiao", "linkou"],
            min_quality_score=0.8,
        )

    assert result == {"status": "answered"}
    request.assert_called_once_with(
        "POST",
        "/api/v1/copilot/query",
        json_body={
            "question": "Where should I buy a home?",
            "entityIds": ["banqiao", "linkou"],
            "minQualityScore": 0.8,
        },
    )
