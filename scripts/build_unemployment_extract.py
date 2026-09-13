"""Reshape New Taipei's unemployment-rate-by-age table into a canonical long table.

The open-data table (data.ntpc.gov.tw dataset c29c80d4, unemployment rate by
age) is one row per year with anonymous columns ``item value2`` ...
``item value21``. Their meaning (age band x sex) is published only in the
dataset description, so it is recorded once in ``COLUMNS``. The survey is
city-wide: no district breakdown exists, so each row is keyed to 新北市 as a
whole.

    uv run python -m scripts.build_unemployment_extract
"""

import argparse
import csv
import json
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_URL = "https://data.ntpc.gov.tw/api/datasets/c29c80d4-bef1-452c-8d9a-659e72f07831/json"
_OUTPUT = _ROOT / "data" / "source" / "10_失業率_年齡別" / "_全部年度_全市.csv"

# From the dataset's 主要欄位說明: item value2(15_24歲男), item value3(15_24歲女), ...
_BANDS = ("15-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54", "55-59", "60-64")
COLUMNS: dict[str, tuple[str, str]] = {
    **{
        f"item value{2 + index * 2 + offset}": (f"{band}歲", sex)
        for index, band in enumerate(_BANDS)
        for offset, sex in enumerate(("男", "女"))
    },
    "item value20": ("65歲以上", "男"),
    "item value21": ("65歲以上", "女"),
}


def _fetch(location: str) -> list[dict[str, str]]:
    if not location.startswith("https://"):
        return list(json.loads(Path(location).read_text(encoding="utf-8")))
    rows: list[dict[str, str]] = []
    page = 0
    while True:
        url = f"{location}?page={page}&size=100"
        with urllib.request.urlopen(url, timeout=30) as response:
            batch = json.loads(response.read())
        if not batch:
            return rows
        rows.extend(batch)
        page += 1


def build(source_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for source in sorted(source_rows, key=lambda row: int(row["field1"])):
        unexpected = set(source) - {"field1", *COLUMNS}
        if unexpected:
            raise ValueError(f"unexpected source columns: {', '.join(sorted(unexpected))}")
        year = int(source["field1"])
        for column, (age, sex) in COLUMNS.items():
            value = source.get(column)
            if value in (None, ""):
                continue
            rows.append(
                {
                    "民國年": year - 1911,
                    "行政區": "新北市",
                    "年齡": age,
                    "性別": sex,
                    "失業率": value,
                }
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=_SOURCE_URL, help="API URL or saved JSON path")
    parser.add_argument("--output", type=Path, default=_OUTPUT)
    arguments = parser.parse_args()

    rows = build(_fetch(arguments.source))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with arguments.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    years = sorted({int(str(row["民國年"])) for row in rows})
    print(f"wrote {len(rows)} rows for {years[0]}-{years[-1]} to {arguments.output}")


if __name__ == "__main__":
    main()
