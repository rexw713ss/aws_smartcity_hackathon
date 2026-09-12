"""AWS Lambda entrypoint for the FastAPI application.

Mangum translates API Gateway HTTP API (payload format 2.0) events into ASGI
scope/receive/send, so the same app object serves both ``uvicorn`` locally and
Lambda in AWS with no branching in the routes themselves.

The data root is configurable because Lambda unpacks the package at
``/var/task``, which is read-only. Only read paths touch it; writes go to S3.
"""

import os
from pathlib import Path

from mangum import Mangum

from apps.api.main import create_app

_DATA_ROOT = Path(os.environ.get("YOUTH_COMPASS_DATA_ROOT", "/var/task/data"))

app = create_app(_DATA_ROOT)

# lifespan="off": API Gateway invokes a fresh handler per request and the app
# registers no startup/shutdown hooks, so running the lifespan protocol would
# only add cold-start latency.
handler = Mangum(app, lifespan="off")
