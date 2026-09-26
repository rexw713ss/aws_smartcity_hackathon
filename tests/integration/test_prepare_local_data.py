"""Local onboarding publishes real source rows only after approval."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.dependencies import LocalRuntime
from apps.api.main import create_app
from scripts.prepare_local_data import SOURCES, prepare_sources
from youth_compass.config import AppSettings
from youth_compass.domain.contracts import DatasetStatus


def test_prepare_approve_and_reuse_sources(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    fixtures = {
        "population": "民國年,行政區,年齡,性別,人數\n114,板橋區,20-24歲,女,123\n",
        "education": "民國年,行政區,年齡,性別,教育程度,人數\n114,板橋區,20-24歲,女,大學,80\n",
        "employment": "民國年,行政區,年齡,性別,失業率\n114,新北市,20-24歲,女,4.2\n",
    }
    for topic, relative_path in SOURCES.items():
        path = source_root / relative_path
        path.parent.mkdir(parents=True)
        path.write_text(fixtures[topic], encoding="utf-8")
    runtime = LocalRuntime(tmp_path / "data", AppSettings())
    assert prepare_sources(runtime, source_root, approve=False, reviewed_by="")
    assert all(
        item.status is DatasetStatus.AWAITING_APPROVAL for item in runtime.catalog.list_datasets()
    )
    assert not list((tmp_path / "data" / "curated").rglob("*.parquet"))
    assert prepare_sources(runtime, source_root, approve=True, reviewed_by="test-reviewer")
    assert all(item.status is DatasetStatus.PUBLISHED for item in runtime.catalog.list_datasets())
    versions = {
        item.dataset_id: runtime.catalog.list_versions(item.dataset_id)
        for item in runtime.catalog.list_datasets()
    }
    assert prepare_sources(runtime, source_root, approve=True, reviewed_by="test-reviewer")
    assert versions == {topic: runtime.catalog.list_versions(topic) for topic in versions}
    client = TestClient(create_app(tmp_path / "data"))
    for question in ("板橋區青年人口", "概覽教育", "新北市青年失業率"):
        body = client.post(
            "/api/v1/copilot/query",
            json={
                "question": question,
                "responseLanguage": "zh-TW",
                "minQualityScore": 0.7,
            },
        ).json()
        assert body["status"] == "answered", body["answer"]
        assert body["citations"]


def test_approval_requires_reviewer(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="reviewed-by"):
        prepare_sources(
            LocalRuntime(tmp_path, AppSettings()), tmp_path, approve=True, reviewed_by=""
        )


def test_api_uses_configured_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOUTH_COMPASS_DATA_ROOT", raising=False)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "base.yaml").write_text("data_root: custom-data\n", encoding="utf-8")
    assert create_app().state.runtime.data_root == tmp_path / "custom-data"
    monkeypatch.setenv("YOUTH_COMPASS_DATA_ROOT", str(tmp_path / "env-data"))
    assert create_app().state.runtime.data_root == tmp_path / "env-data"
