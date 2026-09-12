"""AWS Lambda entrypoint for the FastAPI application.

Mangum translates API Gateway HTTP API (payload format 2.0) events into ASGI
scope/receive/send, so the same app object serves both ``uvicorn`` locally and
Lambda in AWS with no branching in the routes themselves.

Filesystem note: the deployment package is unpacked read-only at ``/var/task``,
but the offline runtime opens a SQLite index and a local object store, both of
which need to create files. So the baked demo data is copied once per execution
environment into ``/tmp``, the only writable location, and the app is pointed
there. The copy is small (curated Parquet, the feature snapshot, and the SQLite
catalog) and happens on cold start only.

That local tree is genuinely ephemeral: it disappears when the execution
environment is recycled. Nothing durable depends on it — ingestion job state
lives in DynamoDB and uploaded objects live in S3. It backs the read-only
dashboard and catalog endpoints, which serve the bundled demo snapshot.
"""

import os
import shutil
from pathlib import Path

# Where the build script bakes the demo data, and where it has to be copied to
# before anything opens it for writing.
_BAKED_DATA_ROOT = Path(os.environ.get("YOUTH_COMPASS_BAKED_DATA_ROOT", "/var/task/data"))
_WRITABLE_DATA_ROOT = Path(os.environ.get("YOUTH_COMPASS_DATA_ROOT", "/tmp/youth-compass-data"))

# Subdirectories the offline runtime expects to exist.
_REQUIRED_SUBDIRECTORIES = ("incoming", "curated", "quarantined", "metadata", "features")


def _prepare_writable_data_root() -> Path:
    """Seed a writable copy of the baked data root and return its path."""
    if _BAKED_DATA_ROOT.is_dir() and not _WRITABLE_DATA_ROOT.exists():
        # dirs_exist_ok keeps a warm container that already copied idempotent.
        shutil.copytree(_BAKED_DATA_ROOT, _WRITABLE_DATA_ROOT, dirs_exist_ok=True)
        # copytree replicates the source's permission bits, and the source is
        # read-only. Without this the copy is unwritable too.
        _grant_owner_write(_WRITABLE_DATA_ROOT)
    for name in _REQUIRED_SUBDIRECTORIES:
        (_WRITABLE_DATA_ROOT / name).mkdir(parents=True, exist_ok=True)
    return _WRITABLE_DATA_ROOT


def _grant_owner_write(root: Path) -> None:
    """Add owner write (and traverse) permission across a copied tree."""
    for path in (root, *root.rglob("*")):
        mode = path.stat().st_mode
        path.chmod(mode | (0o700 if path.is_dir() else 0o600))


# Must run before apps.api.main is imported: that module builds an application
# at import time using the data root from the environment.
_DATA_ROOT = _prepare_writable_data_root()
os.environ["YOUTH_COMPASS_DATA_ROOT"] = str(_DATA_ROOT)

from mangum import Mangum  # noqa: E402

from apps.api.main import create_app  # noqa: E402

app = create_app(_DATA_ROOT)

# lifespan="off": API Gateway invokes a fresh handler per request and the app
# registers no startup/shutdown hooks, so running the lifespan protocol would
# only add cold-start latency.
handler = Mangum(app, lifespan="off")
