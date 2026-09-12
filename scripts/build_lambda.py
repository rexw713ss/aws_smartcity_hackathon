"""Build the Lambda deployment packages (no Docker required).

Two targets:

``transform`` (default)
    ``build/transform_lambda/`` — the ingestion workflow handlers.

``api``
    ``build/api_lambda/`` — the FastAPI application behind API Gateway, wrapped
    by Mangum, plus the demo data root the dashboard endpoints read.

Usage::

    uv run python scripts/build_lambda.py            # transform
    uv run python scripts/build_lambda.py api        # API
    uv run python scripts/build_lambda.py all

Dependencies publish manylinux aarch64 wheels, so installing them with the ARM64
platform tag produces a Graviton-compatible package. Both targets assert the
unzipped size stays under Lambda's 250 MB limit.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUILD_DIR = _REPO_ROOT / "build" / "transform_lambda"
_API_BUILD_DIR = _REPO_ROOT / "build" / "api_lambda"

# Lambda's hard limit on an unzipped zip-deployed function.
_UNZIPPED_LIMIT_BYTES = 250 * 1024 * 1024

# The transform action now runs the real canonical transform
# (run_csv_transformation), which needs pyarrow and duckdb to write and verify
# the Parquet, so both are bundled alongside pydantic. polars is NOT required:
# the transform reads the CSV with the stdlib csv module and writes with
# pyarrow.parquet, so it is deliberately left out to stay under the 250 MB
# limit. openpyxl covers XLSX sources; boto3 is bundled because the runtime's
# copy lags the SDK.
_RUNTIME_DEPS = ["pydantic", "pyarrow", "duckdb", "openpyxl", "boto3"]


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

    _report_size(_BUILD_DIR, "transform")
    return _BUILD_DIR


# The API's real import chain. streamlit is a dashboard-only dependency, and
# polars/pyarrow are deliberately excluded because the read-only API defers them
# (see adapters/local/feature_store.py and application/ingestion_workflow.py).
# Those exclusions are what keep this package inside the 250 MB limit.
#
# boto3 is bundled rather than taken from the runtime: Lambda's built-in copy
# lags by many months, and Converse's structured-output field is recent enough
# that the bundled version made Bedrock reject every schema-constrained request
# with "This model doesn't support the outputConfig field".
_API_RUNTIME_DEPS = [
    "boto3",
    "fastapi",
    "mangum",
    "pydantic",
    "pydantic-settings",
    "python-multipart",
    "pyyaml",
    "jsonschema",
    "duckdb",
    "openpyxl",
    "pdfplumber",
]

# Demo data the dashboard endpoints read. Lambda's filesystem is read-only
# outside /tmp, which is fine: these reads never mutate the tree.
_API_DATA_DIRS = ("curated", "features", "metadata")


def build_api() -> Path:
    """Assemble the API Lambda package."""
    if _API_BUILD_DIR.exists():
        shutil.rmtree(_API_BUILD_DIR)
    _API_BUILD_DIR.mkdir(parents=True)

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
            str(_API_BUILD_DIR),
            *_API_RUNTIME_DEPS,
        ],
        check=True,
    )

    shutil.copytree(_REPO_ROOT / "src" / "youth_compass", _API_BUILD_DIR / "youth_compass")
    shutil.copytree(_REPO_ROOT / "adapters", _API_BUILD_DIR / "adapters")
    shutil.copytree(_REPO_ROOT / "apps", _API_BUILD_DIR / "apps")
    shutil.copytree(_REPO_ROOT / "configs", _API_BUILD_DIR / "configs")

    # The Streamlit dashboard is not part of the deployed API.
    shutil.rmtree(_API_BUILD_DIR / "apps" / "dashboard", ignore_errors=True)

    data_source = _REPO_ROOT / "data"
    data_target = _API_BUILD_DIR / "data"
    data_target.mkdir()
    for name in _API_DATA_DIRS:
        source = data_source / name
        if source.is_dir():
            shutil.copytree(source, data_target / name)

    _prune_bytecode(_API_BUILD_DIR)
    _report_size(_API_BUILD_DIR, "api")
    return _API_BUILD_DIR


def _prune_bytecode(root: Path) -> None:
    """Drop caches and test trees that only inflate the package."""
    for cache in root.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    for pyc in root.rglob("*.pyc"):
        pyc.unlink(missing_ok=True)


def _directory_size(root: Path) -> int:
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _report_size(root: Path, label: str) -> None:
    """Print the unzipped size and fail the build if it exceeds Lambda's limit."""
    size = _directory_size(root)
    megabytes = size / 1024 / 1024
    headroom = (_UNZIPPED_LIMIT_BYTES - size) / 1024 / 1024
    print(f"built {label} Lambda package at {root}")
    print(f"  unzipped size: {megabytes:.1f} MB (limit 250 MB, headroom {headroom:.1f} MB)")
    if size > _UNZIPPED_LIMIT_BYTES:
        raise SystemExit(
            f"{label} package is {megabytes:.1f} MB, over Lambda's 250 MB unzipped limit"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        nargs="?",
        default="transform",
        choices=["transform", "api", "all"],
    )
    args = parser.parse_args(argv)
    if args.target in {"transform", "all"}:
        build()
    if args.target in {"api", "all"}:
        build_api()
    return 0


if __name__ == "__main__":
    sys.exit(main())
