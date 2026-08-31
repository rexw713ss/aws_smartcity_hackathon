"""Minimal API bootstrap for the first implementation milestone."""

from fastapi import FastAPI

from youth_compass import __version__

app = FastAPI(title="New Taipei Youth Compass API", version=__version__)


@app.get("/health", tags=["operations"])
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}
