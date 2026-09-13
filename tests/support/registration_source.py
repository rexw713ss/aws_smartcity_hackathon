"""A synthetic registration file in the source layout: 29 districts, single ages, both genders.

Birth cohorts shrink over time, so the youth count falls in a way a cohort model
sees coming and a last-value baseline does not. With ``shrinking=False`` every
count is constant, which the last value predicts perfectly.
"""

import csv
from pathlib import Path

from youth_compass.mapping.geography import DISTRICTS

_YEARS = [year for year in range(2012, 2024) if year != 2017]
_HEADER = [
    "民國年", "月", "區代碼", "行政區", "年齡標籤", "年齡下限", "年齡上限",
    "青年關係", "青年權重", "性別", "人數",
]  # fmt: skip


def write_registration_source(path: Path, *, shrinking: bool) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(_HEADER)
        for index, district in enumerate(DISTRICTS, start=1):
            # Three districts stay under 10,000 residents to exercise the small class.
            births = 60.0 if index <= 3 else 500.0
            retention = 0.995 + 0.001 * (index % 5)
            for year in _YEARS:
                for age in range(0, 41):
                    decline = 1 - 0.02 * (year - age - 1980) if shrinking else 1.0
                    rate = retention if shrinking else 1.0
                    count = births * max(decline, 0.2) * rate**age
                    for gender in ("男", "女"):
                        writer.writerow(
                            [
                                year - 1911, 7, index, district.name, f"{age}歲", age, age,
                                "完全落入" if 18 <= age <= 35 else "不相關", 1.0, gender,
                                round(count / 2),
                            ]
                        )  # fmt: skip
