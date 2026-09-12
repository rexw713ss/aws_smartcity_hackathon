"""Build the Transform Lambda deployment package (no Docker required).

Assembles ``build/transform_lambda/`` with the handler, the project source, the
adapter module, and the pure-Python runtime dependencies, ready for
``Code.from_asset``. Run before ``cdk deploy`` of the Workflow stack:

    uv run python scripts/build_lambda.py

Dependencies (polars, pydantic, pyarrow) publish manylinux aarch64 wheels, so
installing them with the ARM64 platform tag produces a Graviton-compatible
package.
"""

import shutil
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUILD_DIR = _REPO_ROOT / "build" / "transform_lambda"

# The handler's actual runtime import chain (profile_csv + analyze_mapping) uses
# only the standard library plus pydantic. polars and pyarrow are project
# dependencies but are not on this code path, so they are deliberately excluded
# to keep the package under Lambda's 250 MB unzipped limit (verified: the import
# chain loads pydantic only).
_RUNTIME_DEPS = ["pydantic"]


def build() -> Path:
    if _BUILD_DIR.exists():
        shutil.rmtree(_BUILD_DIR)
    _BUILD_DIR.mkdir(parents=True)

    # 1. Install runtime deps for ARM64 / CPython 3.12 (Graviton Lambda).
    # Use `uv pip` since the project venv is uv-managed and has no stdlib pip.
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python-platform",
            "aarch64-manylinux2014",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
            "--target",
            str(_BUILD_DIR),
            *_RUNTIME_DEPS,
        ],
        check=True,
    )

    # 2. Copy the project source.
    shutil.copytree(_REPO_ROOT / "src" / "youth_compass", _BUILD_DIR / "youth_compass")

    # 3. Copy the adapter modules the two Lambda handlers need.
    adapters_dir = _BUILD_DIR / "adapters" / "aws"
    adapters_dir.mkdir(parents=True)
    (_BUILD_DIR / "adapters" / "__init__.py").write_text("", encoding="utf-8")
    for module in (
        "__init__.py",
        "transform_lambda.py",
        "upload_event_handler.py",
        "s3_uploads.py",
        "step_functions_runner.py",
        "workflow_token_store.py",
        "dynamodb_checkpoint.py",
    ):
        shutil.copy(_REPO_ROOT / "adapters" / "aws" / module, adapters_dir)

    print(f"built Lambda package at {_BUILD_DIR}")
    return _BUILD_DIR


if __name__ == "__main__":
    build()
