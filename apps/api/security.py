"""Write-path protection for the deployed API.

The reviewer endpoints mutate published state: approving an ingestion job writes
to the curated zone and registers a Glue table. Reads are intentionally public
so a demo audience can browse without credentials, but writes require a shared
secret supplied by the deployment.

This is deliberately a shared secret rather than full user authentication. It
closes the "anyone can publish data" hole with no frontend login flow, which is
the right trade for a demo deployment. Swapping it for a Cognito JWT authorizer
later touches only this module and the stack.
"""

import secrets

from fastapi import HTTPException, Request, status

from youth_compass.config import AppSettings

#: Header carrying the shared secret. A custom header (rather than
#: ``Authorization``) keeps it clearly distinct from real user auth.
WRITE_TOKEN_HEADER = "X-Youth-Compass-Token"


def require_write_token(request: Request) -> None:
    """Reject a mutating request that does not carry the configured secret.

    When no secret is configured the guard is inactive, so local development and
    the offline test suite behave exactly as before. Deployments always set one.

    Raises:
        HTTPException: 401 when a secret is configured and the request does not
            present a matching token.
    """
    settings: AppSettings | None = getattr(request.app.state, "settings", None)
    expected = settings.api.write_secret if settings is not None else None
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
