from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd


ARCHIVE_PATH = "NITAQ_CLIENT_PACKAGE/01_CORE_SOURCE_DATA/RAW_DATA_ARCHIVE/raw_sources_2026-07-30.zip"


@lru_cache(maxsize=4)
def _load_modon_regional_context_cached(root_text: str, modified_ns: int, size: int) -> dict[str, Any]:
    root = Path(root_text)
    path = root / "data" / "processed" / "runtime" / "modon_regional_context_2023_2024.csv"
    table = pd.read_csv(path)
    return {
        "table": table,
        "unmapped_industrial_cities": [],
        "sources": [
            {
                "source_id": "modon_productive_factories_q4_2023",
                "source_agency": "MODON",
                "source_path": f"{ARCHIVE_PATH}::data/raw/context/industrial/Q4-مجموعة بيانات المصانع المنتجة لعام 2023.xlsx",
                "period": "2023 Q4",
            },
            {
                "source_id": "modon_industrial_city_area_q2_2024",
                "source_agency": "MODON",
                "source_path": f"{ARCHIVE_PATH}::data/raw/context/industrial/مساحات المدن الصناعية-الربع الثاني 2024 (002).xlsx",
                "period": "2024 Q2",
            },
            {
                "source_id": "modon_ready_factories_2023_published_2024",
                "source_agency": "MODON",
                "source_path": f"{ARCHIVE_PATH}::data/raw/context/industrial/المصانع الجاهزة الربع الثالث 2024.xlsx",
                "period": "2023; published 2024-08-29",
            },
        ],
    }


def load_modon_regional_context(root: Path) -> dict[str, Any]:
    path = root / "data" / "processed" / "runtime" / "modon_regional_context_2023_2024.csv"
    stat = path.stat()
    return _load_modon_regional_context_cached(str(root.resolve()), stat.st_mtime_ns, stat.st_size)
