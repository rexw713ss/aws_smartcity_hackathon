"""Small standard-library client for the local FastAPI boundary."""

from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(slots=True)
class ApiError(Exception):
    """Safe API failure that can be rendered directly in the dashboard."""

    message: str
    status_code: int | None = None
    code: str | None = None

    def __str__(self) -> str:
        return self.message


class YouthCompassApi:
    """HTTP client that keeps Streamlit independent from local/AWS adapters."""

    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._request("GET", "/health"))

    def datasets(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/v1/datasets")
        return cast(list[dict[str, Any]], payload)

    def city_summary(
        self, dataset_id: str, metric_code: str, period: str | None = None
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request(
                "GET",
                "/api/v1/city/summary",
                query=_analytics_query(dataset_id, metric_code, period),
            ),
        )

    def districts(
        self, dataset_id: str, metric_code: str, period: str | None = None
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request(
                "GET",
                "/api/v1/districts",
                query=_analytics_query(dataset_id, metric_code, period),
            ),
        )

    def upload(
        self,
        *,
        file_name: str,
        content: bytes,
        submitted_by: str,
        topic_hint: str | None,
    ) -> dict[str, Any]:
        boundary = f"----YouthCompass{uuid.uuid4().hex}"
        fields = {"submitted_by": submitted_by}
        if topic_hint:
            fields["topic_hint"] = topic_hint
        body = _multipart_body(boundary, fields, file_name, content)
        return cast(
            dict[str, Any],
            self._request(
                "POST",
                "/api/v1/datasets/upload",
                body=body,
                content_type=f"multipart/form-data; boundary={boundary}",
            ),
        )

    def job(self, job_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request("GET", f"/api/v1/ingestion-jobs/{job_id}"),
        )

    def mapping(self, job_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request("GET", f"/api/v1/ingestion-jobs/{job_id}/mapping"),
        )

    def decide(
        self, job_id: str, *, decision: str, decided_by: str, comment: str | None
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request(
                "POST",
                f"/api/v1/ingestion-jobs/{job_id}/decision",
                json_body={
                    "decision": decision,
                    "decidedBy": decided_by,
                    "comment": comment or None,
                },
            ),
        )

    def quality(self, job_id: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._request("GET", f"/api/v1/ingestion-jobs/{job_id}/quality-report"),
        )

    def copilot(
        self,
        question: str,
        *,
        entity_ids: list[str] | None = None,
        min_quality_score: float = 0.0,
    ) -> dict[str, Any]:
        """Ask the grounded copilot to execute an allowlisted decision plan."""

        return cast(
            dict[str, Any],
            self._request(
                "POST",
                "/api/v1/copilot/query",
                json_body={
                    "question": question,
                    "entityIds": entity_ids or [],
                    "minQualityScore": min_quality_score,
                },
            ),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Accept": "application/json"}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif content_type:
            headers["Content-Type"] = content_type
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            payload = _decode_error(exc.read())
            raise ApiError(
                message=payload["message"],
                status_code=exc.code,
                code=payload.get("code"),
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise ApiError(
                "FastAPI is not reachable. Start it on port 8000, then refresh this page."
            ) from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ApiError("The API returned an unreadable response.") from exc


def _analytics_query(dataset_id: str, metric_code: str, period: str | None) -> dict[str, str]:
    query = {"datasetId": dataset_id, "metricCode": metric_code}
    if period:
        query["period"] = period
    return query


def _decode_error(raw: bytes) -> dict[str, str]:
    try:
        payload = json.loads(raw.decode("utf-8"))
        error = payload.get("error", {})
        message = error.get("message")
        if isinstance(message, str):
            result = {"message": message}
            if isinstance(error.get("code"), str):
                result["code"] = error["code"]
            return result
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        pass
    return {"message": "The API request failed."}


def _multipart_body(
    boundary: str,
    fields: dict[str, str],
    file_name: str,
    content: bytes,
) -> bytes:
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    safe_name = file_name.replace('"', "")
    mime_type = mimetypes.guess_type(file_name)[0] or "text/csv"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            (f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n').encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks)
