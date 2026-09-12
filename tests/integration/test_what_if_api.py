import csv
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import create_app


def _write_population(data_root: Path) -> None:
    path = data_root / "source" / "01_人口" / "_全部年度_全區.csv"
    path.parent.mkdir(parents=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "民國年",
                "月",
                "區代碼",
                "行政區",
                "年齡標籤",
                "年齡下限",
                "年齡上限",
                "青年關係",
                "青年權重",
                "性別",
                "人數",
            ]
        )
        for code in range(1, 30):
            for age in range(0, 36):
                writer.writerow(
                    [
                        115,
                        7,
                        code,
                        f"district-{code}",
                        f"{age}歲",
                        age,
                        age,
                        "完全落入",
                        1,
                        "總計",
                        code * 100 if age == 18 else 0,
                    ]
                )


def test_what_if_endpoint_uses_camel_case_request_and_grounded_response(tmp_path: Path) -> None:
    _write_population(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/v1/copilot/what-if",
        json={
            "balanceMode": "redistribute",
            "adjustments": [
                {
                    "districtId": "Linkou",
                    "operation": "absolute_change",
                    "value": 500,
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["observed_period"] == "2026-07"
    assert body["population_conserved"] is True
    assert len(body["rows"]) == 29
    assert body["evidence"][0]["kind"] == "official"
    assert body["trajectory"][-1]["scenario_value"] == body["scenario_total"]
    assert "_全部年度_全區.csv" not in response.text


def test_what_if_endpoint_accepts_an_explicit_district_transfer(tmp_path: Path) -> None:
    _write_population(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/v1/copilot/what-if",
        json={
            "balanceMode": "redistribute",
            "adjustments": [
                {
                    "sourceDistrictId": "Banqiao",
                    "districtId": "Linkou",
                    "operation": "transfer",
                    "value": 50,
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    by_code = {row["district_code"]: row for row in body["rows"]}
    assert by_code["01"]["absolute_delta"] == -50
    assert by_code["17"]["absolute_delta"] == 50
    assert body["population_conserved"] is True


def test_what_if_endpoint_projects_to_a_target_year_with_a_benchmark(tmp_path: Path) -> None:
    _write_population(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/v1/copilot/what-if",
        json={
            "targetYear": 2030,
            "adjustments": [
                {
                    "districtId": "Linkou",
                    "operation": "match_top_quartile_retention",
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target_year"] == 2030
    assert len(body["trajectory"]) == 5
    assert body["baseline_method"] == ("observed_age_cohorts_with_historical_district_retention")


def test_agent_reads_a_traditional_chinese_population_shock(tmp_path: Path) -> None:
    """The Chinese starter question states its count through a measure word."""

    _write_population(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/v1/copilot/query",
        json={
            "question": "如果 2030 年前林口新增 2,000 名青年人口，應投資哪些基礎設施？"  # noqa: RUF001
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] != "unsupported_question"
    impact = body["impact_analysis"]
    assert impact["district_code"] == "17"
    assert impact["target_year"] == 2030
    assert impact["shock_people"] == 2_000


def test_agent_searches_tools_and_stops_impact_chain_at_evidence_gaps(
    tmp_path: Path,
) -> None:
    _write_population(tmp_path)
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/v1/copilot/query",
        json={
            "question": (
                "Nếu thêm 2.000 thanh niên chuyển đến Linkou trước 2030, nên đầu tư hạ tầng gì?"
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "acquisition_required"
    impact = body["impact_analysis"]
    assert impact["district_code"] == "17"
    assert impact["target_year"] == 2030
    assert impact["shock_people"] == 2_000
    assert impact["findings"][0]["absolute_delta"] == 2_000
    assert {gap["domain"] for gap in impact["data_gaps"]} == {
        "housing",
        "transport",
        "public_services",
    }
    assert impact["recommendations"] == []
    assert {item["candidate_id"] for item in body["source_candidates"]} == {
        "ntpc-building-permits",
        "ntpc-bus-stops",
        "ntpc-hospitals",
    }
    trace = {item["tool"]: item["outcome"] for item in body["tool_trace"]}
    assert trace["search_tools"] == "ok"
    assert trace["simulate_scenario"] == "ok"
    assert trace["assess_capacity"] == "data_gap"
    assert trace["discover_sources"] == "candidates"
    assert trace["recommend_investment"] == "withheld"
