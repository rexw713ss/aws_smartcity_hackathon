"""Documentation-consistency guard for the Stage 1 document.

Feature: aws-stage1-foundation, Properties 54 and 55.

Every `make` target, script path, and `--option` named in the command tables of
docs/12 must actually exist in the Makefile or the corresponding script's parser.
Every recorded artifact path must exist on disk.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "12-aws-stage1-foundation.md"
MAKEFILE = ROOT / "Makefile"


def _doc_text() -> str:
    return DOC.read_text(encoding="utf-8")


def test_doc_exists() -> None:
    assert DOC.exists()


def test_property_55_make_targets_exist() -> None:
    make_targets = set(re.findall(r"make ([a-z0-9-]+)", _doc_text()))
    defined = set(re.findall(r"^([a-zA-Z0-9_-]+):.*##", MAKEFILE.read_text(encoding="utf-8"), re.M))
    missing = make_targets - defined
    assert not missing, f"doc names make targets not in the Makefile: {missing}"


def test_property_55_script_paths_exist() -> None:
    script_paths = set(re.findall(r"scripts/[a-z_]+\.py", _doc_text()))
    for rel in script_paths:
        assert (ROOT / rel).exists(), f"doc names a missing script: {rel}"


def test_property_54_recorded_artifact_paths_exist() -> None:
    # Paths appear in the artifact table as inline `code` spans.
    candidates = re.findall(r"`([a-zA-Z0-9_./-]+/[a-zA-Z0-9_./-]+)`", _doc_text())
    checked = 0
    for rel in candidates:
        if rel.startswith(("src/", "tests/", "infra/", "scripts/", "configs/", "docs/")):
            assert (ROOT / rel).exists(), f"doc references a missing path: {rel}"
            checked += 1
    assert checked >= 8  # the artifact inventory


def test_property_54_required_statements_present() -> None:
    text = _doc_text()
    assert "Deploys nothing" in text or "deploys nothing" in text.lower()
    assert "Stage 3" in text  # deferred services named with their stage
    assert "僅限使用 Amazon Bedrock" in text  # competition rule, original wording
    assert "Moto fidelity boundary" in text


def test_property_55_options_named_in_doc_are_accepted() -> None:
    text = _doc_text()
    if "ASSUME_YES=1" in text:
        assert "ASSUME_YES" in MAKEFILE.read_text(encoding="utf-8")
    if "ENV=dev|demo|hackathon" in text:
        assert "ENV" in MAKEFILE.read_text(encoding="utf-8")


def test_doc_registered_in_readme_map() -> None:
    readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    assert "12-aws-stage1-foundation.md" in readme
