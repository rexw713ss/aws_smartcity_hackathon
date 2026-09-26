"""Collected official statistics retain provenance, rates, and geographic scope."""

import asyncio
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest

from apps.api.dependencies import LocalRuntime
from scripts.collect_official_statistics import SOURCES, StatisticalSource, reshape
from youth_compass.agent.planning import DeterministicQueryDecomposer
from youth_compass.config import AppSettings
from youth_compass.domain.contracts import DatasetStatus
from youth_compass.ontology import extract_topics
from youth_compass.ports import ApprovalDecision

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "data" / "source"


@pytest.mark.parametrize("source", SOURCES, ids=lambda item: item.topic)
def test_collected_snapshot_checksums_and_exact_reshape(source: StatisticalSource) -> None:
    folder = SOURCE_ROOT / source.folder
    manifest = json.loads((folder / "provenance.json").read_text(encoding="utf-8"))
    raw_bytes = (folder / manifest["raw_file"]).read_bytes()
    csv_bytes = (folder / "_全部年度_全市.csv").read_bytes()
    assert hashlib.sha256(raw_bytes).hexdigest() == manifest["raw_sha256"]
    assert hashlib.sha256(csv_bytes).hexdigest() == manifest["csv_sha256"]
    expected = [
        {key: str(value) for key, value in row.items()}
        for row in reshape(source, json.loads(raw_bytes))
    ]
    assert list(csv.DictReader(csv_bytes.decode("utf-8-sig").splitlines())) == expected
    assert len(expected) == manifest["normalized_rows"]
    assert manifest["license_url"] == "https://data.gov.tw/license"


@pytest.fixture
def runtime(tmp_path: Path) -> LocalRuntime:
    runtime = LocalRuntime(tmp_path, AppSettings())
    for source in SOURCES:
        job = runtime.workflow.submit_file(
            SOURCE_ROOT / source.folder / "_全部年度_全市.csv", submitted_by="test-reviewer"
        )
        runtime.workflow.resume_after_approval(
            job.job_id,
            ApprovalDecision(
                approved=True, decided_by="test-reviewer", decided_at=datetime.now(UTC)
            ),
        )
        published = runtime.workflow.get_job(job.job_id)
        assert published.metadata.status is DatasetStatus.PUBLISHED
        assert published.metadata.topic == source.topic
        assert published.manifest is not None
        rows = pq.read_table(published.manifest.parquet_uri).to_pylist()
        assert len(rows) == len(
            list(
                csv.DictReader(
                    (SOURCE_ROOT / source.folder / "_全部年度_全市.csv")
                    .read_text(encoding="utf-8-sig")
                    .splitlines()
                )
            )
        )
        assert all(row["metric_value"] == row["metric_value_original"] for row in rows)
        assert all(not row["is_estimated"] for row in rows)
        assert all(row["population_scope"] == "general_population" for row in rows)
    return runtime


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("新北市勞動力參與率", "labor_participation"),
        ("新北市就業者年齡結構", "workforce_age_share"),
        ("新北市識字率", "literacy"),
        ("新北市人口年齡結構", "population_age_share"),
    ],
)
def test_new_questions_query_the_named_metric(
    runtime: LocalRuntime, question: str, topic: str
) -> None:
    response = asyncio.run(runtime.copilot().answer(question, response_language="zh-TW"))
    assert response.status.value == "answered"
    assert response.dataset_inspection is not None
    assert response.dataset_inspection.dataset_id == topic
    assert not response.dataset_inspection.additive
    assert response.citations
    assert response.warnings
    assert "個觀測分組" in response.answer


def test_citywide_data_does_not_answer_a_district_comparison(runtime: LocalRuntime) -> None:
    response = asyncio.run(runtime.copilot().answer("比較各行政區的勞動力參與率"))
    assert response.status.value != "answered"
    assert any("no district breakdown" in item.summary for item in response.tool_trace)


def test_single_gender_rate_trend_keeps_percent_units(runtime: LocalRuntime) -> None:
    response = asyncio.run(
        runtime.copilot().answer("查看女性識字率趨勢", response_language="zh-TW")
    )
    assert response.status.value == "answered"
    assert "99.2%" in response.answer
    assert "百分點" in response.answer
    assert "青年人口" not in response.answer


@pytest.mark.parametrize(
    ("question", "topics"),
    [
        ("人口年齡結構", ("population_age_share",)),
        ("比較人口與人口年齡結構", ("population", "population_age_share")),
        ("勞動力參與率", ("labor_participation",)),
        ("employment age structure", ("workforce_age_share",)),
    ],
)
def test_specific_topic_does_not_also_select_its_parent(
    question: str, topics: tuple[str, ...]
) -> None:
    assert extract_topics(question) == topics


@pytest.mark.parametrize("bad_value", ["NaN", "101", "-1", "infinity"])
def test_invalid_percentages_are_rejected(bad_value: str) -> None:
    source = SOURCES[0]
    record = {"field1": "2024", **{field: "10" for field in source.all_fields}}
    record[source.fields[0][0]] = bad_value
    with pytest.raises(ValueError):
        reshape(source, [record])


def test_changed_schema_and_duplicate_years_are_rejected() -> None:
    source = SOURCES[0]
    record = {"field1": "2024", **{field: "10" for field in source.all_fields}}
    with pytest.raises(ValueError, match="schema changed"):
        reshape(source, [{**record, "new_column": "10"}])
    with pytest.raises(ValueError, match="duplicate"):
        reshape(source, [record, record])


def test_explicit_count_and_share_are_both_preserved() -> None:
    query = asyncio.run(
        DeterministicQueryDecomposer().decompose("比較人口與人口年齡結構", ())
    ).query
    assert query.metric_terms == ("population_count", "population_age_share")
