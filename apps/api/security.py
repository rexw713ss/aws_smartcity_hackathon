"""Write-path protection for the deployed API.

The reviewer endpoints mutate published state: approving an ingestion job writes
to the curated zone and registers a Glue table. Reads are intentionally public
so a demo audience can browse without credentials, but writes require a shared
secret supplied by the deployment.

This is deliberately a shared secret rather than full user authentication. It
closes the "anyone can publish data" hole with no frontend login flow, which is
the right trade for a demo deployment. Swapping it for a Cognito JWT authorizer
later touches only this module and the stack.

Where the secret lives matters as much as the comparison. A deployment sets
``write_secret_arn`` and the value is read from Secrets Manager at runtime, so
it appears in neither the Lambda configuration nor the CloudFormation template.
A literal ``write_secret`` remains supported and takes precedence, because local
development and the offline suite configure one directly.
"""

import secrets
import time
from typing import Any

from fastapi import HTTPException, Request, status

from youth_compass.config import AppSettings

#: Header carrying the shared secret. A custom header (rather than
#: ``Authorization``) keeps it clearly distinct from real user auth.
WRITE_TOKEN_HEADER = "X-Youth-Compass-Token"

#: How long a fetched secret is reused before it is read again. Long enough that
#: the common case costs no API call, short enough that rotating the secret
#: takes effect without redeploying the function.
_SECRET_CACHE_TTL_SECONDS = 300.0

#: arn -> (value, fetched_at). Module-level so it survives across requests in one
#: Lambda execution environment.
_secret_cache: dict[str, tuple[str, float]] = {}


def _fetch_secret(arn: str) -> str:
    """Read the write secret from Secrets Manager, caching it briefly."""

    cached = _secret_cache.get(arn)
    now = time.monotonic()
    if cached is not None and now - cached[1] < _SECRET_CACHE_TTL_SECONDS:
        return cached[0]

    # Imported lazily: the offline runtime never reaches this path, and the
    # import costs cold-start time in the one that does.
    import boto3

    client: Any = boto3.client("secretsmanager")
    value = str(client.get_secret_value(SecretId=arn)["SecretString"])
    _secret_cache[arn] = (value, now)
    return value


def resolve_write_secret(settings: AppSettings | None) -> str | None:
    """The configured write secret, or None when the guard is inactive.

    Raises:
        HTTPException: 503 when a secret is configured but cannot be read. The
            guard fails closed: an unreachable secret store must not turn into
            an unguarded write path.
    """

    if settings is None:
        return None
    if settings.api.write_secret:
        return settings.api.write_secret
    arn = settings.api.write_secret_arn
    if not arn:
        return None
    try:
        return _fetch_secret(arn)
    except Exception as exc:  # Any failure must fail closed.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the write guard is temporarily unavailable",
        ) from exc


def require_write_token(request: Request) -> None:
    """Reject a mutating request that does not carry the configured secret.

    When no secret is configured the guard is inactive, so local development and
    the offline test suite behave exactly as before. Deployments always set one.

    Raises:
        HTTPException: 401 when a secret is configured and the request does not
            present a matching token; 503 when the configured secret cannot be
            read.
    """
    settings: AppSettings | None = getattr(request.app.state, "settings", None)
    expected = resolve_write_secret(settings)
    if not expected:
        return

    provided = request.headers.get(WRITE_TOKEN_HEADER)
    # compare_digest keeps the comparison time independent of how many leading
    # characters happen to match.
    if provided is None or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"this endpoint requires a valid {WRITE_TOKEN_HEADER} header",
        )
