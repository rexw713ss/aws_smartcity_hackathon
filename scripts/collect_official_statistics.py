"""Collect bounded, versioned NTPC statistical snapshots; never publish implicitly.

Every output field is mapped from the official dataset description. Raw API
responses, retrieval time, checksums, scope, and license accompany the CSV.
"""

# ruff: noqa: RUF001 -- Traditional Chinese documentation intentionally uses CJK punctuation.

import argparse
import csv
import hashlib
import json
import math
import re
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StatisticalSource:
    topic: str
    dataset_id: str
    title: str
    folder: str
    metric: str
    fields: tuple[tuple[str, str | None, str], ...]
    all_fields: tuple[str, ...]
    scope: str

    @property
    def url(self) -> str:
        return f"https://data.ntpc.gov.tw/api/datasets/{self.dataset_id}/json"

    @property
    def page_url(self) -> str:
        return f"https://data.ntpc.gov.tw/datasets/{self.dataset_id}"


def _age_fields(
    prefix: str, first: int, bands: tuple[str, ...]
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (f"{prefix}{first + index * 2 + offset}", band, sex)
        for index, band in enumerate(bands)
        for offset, sex in enumerate(("男", "女"))
    )


SOURCES = (
    StatisticalSource(
        "labor_participation",
        "34ab136e-9296-4083-952a-4ee76394fcb0",
        "勞動力參與率",
        "11_勞動力參與率",
        "勞動力參與率",
        _age_fields("itemvalue", 4, ("15-24歲", "25-44歲", "45-64歲", "65歲以上")),
        tuple(f"itemvalue{i}" for i in range(2, 24)),
        "全市年齡組與性別；25–44歲等組別涵蓋非青年人口，不能視為18–35歲專屬參與率。",
    ),
    StatisticalSource(
        "workforce_age_share",
        "c285509a-7fb2-434f-8542-0b4986c337a8",
        "就業者年齡結構",
        "12_就業者年齡結構",
        "就業者年齡結構比",
        _age_fields(
            "percent",
            2,
            (
                "15-24歲",
                "25-29歲",
                "30-34歲",
                "35-39歲",
                "40-44歲",
                "45-49歲",
                "50-54歲",
                "55-59歲",
                "60-64歲",
                "65歲以上",
            ),
        ),
        tuple(f"percent{i}" for i in range(2, 22)),
        "各性別就業者中的年齡結構百分比；不是就業率，也不是就業人數。",
    ),
    StatisticalSource(
        "literacy",
        "ffef3ed1-867e-4013-ade0-47cfdba44b2d",
        "教育程度－15歲以上識字率",
        "13_識字率",
        "15歲以上識字率",
        (("itemvalue16", None, "男"), ("itemvalue17", None, "女")),
        tuple(f"itemvalue{i}" for i in range(2, 20)),
        "全市15歲以上人口，依性別；沒有18–35歲或行政區細分。僅擷取識字率兩欄。",
    ),
    StatisticalSource(
        "population_age_share",
        "387f4683-a92e-4884-a548-268d2f77d31e",
        "人口年齡分配",
        "14_人口年齡結構",
        "人口年齡結構比",
        _age_fields("itemvalue", 2, ("0-14歲", "15-64歲", "65歲以上")),
        tuple(f"itemvalue{i}" for i in range(2, 10)),
        "全市各性別人口中的年齡結構百分比；15–64歲是青壯年，不能當成18–35歲青年占比。未擷取平均壽命欄。",
    ),
)


def fetch(source: StatisticalSource) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    urls: list[str] = []
    fingerprints: set[str] = set()
    for page in range(20):
        url = f"{source.url}?page={page}&size=100"
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.geturl().split("/", 3)[:3] != ["https:", "", "data.ntpc.gov.tw"]:
                raise ValueError("unexpected redirect away from the official source")
            content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("source page exceeded 2 MiB")
        batch = json.loads(content)
        if not isinstance(batch, list) or not all(isinstance(row, dict) for row in batch):
            raise ValueError("source response is not a list of records")
        urls.append(url)
        if not batch:
            return rows, urls
        digest = hashlib.sha256(content).hexdigest()
        if digest in fingerprints:
            raise ValueError("source pagination repeated a page")
        fingerprints.add(digest)
        rows.extend(batch)
    raise ValueError("source exceeded the 20-page collection limit")


def reshape(source: StatisticalSource, raw: list[dict[str, Any]]) -> list[dict[str, object]]:
    if not raw:
        raise ValueError("source is empty; existing snapshot was not replaced")
    rows: list[dict[str, object]] = []
    years: set[int] = set()
    for record in raw:
        if set(record) != {"field1", *source.all_fields}:
            raise ValueError(f"{source.topic}: source schema changed; review the mapping")
        if not re.fullmatch(r"(?:19|20)\d{2}", str(record["field1"])):
            raise ValueError("unexpected Gregorian year")
        year = int(record["field1"])
        if year in years:
            raise ValueError("duplicate source year")
        years.add(year)
        for column, age, sex in source.fields:
            value = str(record[column]).strip()
            # Missing values are not zero; preserve them only in the raw snapshot.
            if value in {"", "-", "--", "…", "...", "None", "null"}:
                continue
            numeric = float(value)
            if not math.isfinite(numeric) or not 0 <= numeric <= 100:
                raise ValueError(f"invalid percentage at {year}/{column}")
            row: dict[str, object] = {"民國年": year - 1911, "行政區": "新北市"}
            if age is not None:
                row["年齡"] = age
            row.update({"性別": sex, source.metric: value})
            rows.append(row)
    if not rows:
        raise ValueError("source contains no usable observations")
    return sorted(
        rows, key=lambda row: (int(str(row["民國年"])), str(row.get("年齡", "")), str(row["性別"]))
    )


def collect(source: StatisticalSource, destination: Path) -> dict[str, object]:
    raw, urls = fetch(source)
    rows = reshape(source, raw)
    folder = destination / source.folder
    folder.mkdir(parents=True, exist_ok=True)
    raw_content = (json.dumps(raw, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    raw_sha = hashlib.sha256(raw_content).hexdigest()
    raw_name = f"raw-{raw_sha[:16]}.json"
    (folder / raw_name).write_bytes(raw_content)
    csv_path = folder / "_全部年度_全市.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    years = sorted({int(str(row["民國年"])) + 1911 for row in rows})
    manifest: dict[str, object] = {
        "topic": source.topic,
        "title": source.title,
        "publisher": "新北市政府主計處",
        "dataset_id": source.dataset_id,
        "source_url": source.page_url,
        "api_pages": urls,
        "license": "政府資料開放授權條款－第1版 (OGDL-1.0)",
        "license_url": "https://data.gov.tw/license",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "period_start": years[0],
        "period_end": years[-1],
        "years": years,
        "raw_rows": len(raw),
        "normalized_rows": len(rows),
        "raw_file": raw_name,
        "raw_sha256": raw_sha,
        "csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "geography": "新北市全市",
        "unit": "%",
        "scope": source.scope,
        "fields": [
            {"source": column, "age": age, "gender": sex, "metric": source.metric}
            for column, age, sex in source.fields
        ],
    }
    (folder / "provenance.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (folder / "README.md").write_text(
        f"# {source.title}\n\n來源：[新北市政府資料開放平臺]({source.page_url})"
        "，新北市政府主計處。\n\n"
        f"- 觀測期間：{years[0]}–{years[-1]}；共 {len(rows)} 列。\n"
        f"- 範圍：{source.scope}\n- 單位：%；不可跨性別、年齡組或年度加總。\n"
        "- 授權：政府資料開放授權條款－第1版。\n"
        "- 擷取時間、原始快照、欄位對應與 SHA-256 見 `provenance.json`。\n"
        "- 本檔是來源快照，經核准發布後才進入 Agent 查詢目錄。\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/source"))
    args = parser.parse_args()
    for source in SOURCES:
        result = collect(source, args.output)
        print(
            f"{source.topic}: {result['normalized_rows']} rows, "
            f"{result['period_start']}-{result['period_end']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
