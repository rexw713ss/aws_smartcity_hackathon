import json

from apps.dashboard.api_client import _analytics_query, _decode_error, _multipart_body


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
