from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from .definitions import DERIVED_METRICS, REGION_ALIASES
from .entities import normalize_entity_text, resolve_region_alias
from .exceptions import MizanDataError, MizanInputError


def _clean_value(value: Any):
    if isinstance(value, list):
        return [_clean_value(item) for item in value]
    if isinstance(value, tuple):
        return [_clean_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _clean_value(item) for key, item in value.items()}
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    return value


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _clean_value(value) for key, value in record.items()}


class MizanRepository:
    """Read-only repository for approved Phase 1 sources."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
        processed = self.root / "data" / "processed"
        runtime = processed / "runtime"
        self.paths = {
            "master": processed / "mizan_region_master_2024.csv",
            "metric_catalog": processed / "mizan_metric_catalog_phase1.csv",
            "dictionary": processed / "mizan_region_master_2024_dictionary.csv",
            "ports": processed / "port_region_mapping.csv",
            "portwatch": runtime / "portwatch_monthly_activity_2019_2026.csv",
            "geography": processed / "saudi_regions_geography.csv",
            "context_catalog": processed / "mizan_context_asset_catalog.csv",
            "logistics_centers": runtime / "logistics_centers_snapshot_2026-07-28.csv",
        }
        missing = [str(path) for path in self.paths.values() if not path.exists()]
        if missing:
            raise MizanDataError(f"Approved Phase 1 files are missing: {missing}")

        self.master = pd.read_csv(self.paths["master"])
        self.metric_catalog = pd.read_csv(self.paths["metric_catalog"])
        self.dictionary = pd.read_csv(self.paths["dictionary"])
        self.ports = pd.read_csv(self.paths["ports"], keep_default_na=False)
        for boolean_column in ("official_port_files_available", "portwatch_available"):
            if boolean_column in self.ports:
                self.ports[boolean_column] = (
                    self.ports[boolean_column].astype(str).str.strip().str.lower().eq("true")
                )
        self.portwatch = pd.read_csv(self.paths["portwatch"], parse_dates=["date"])
        self.geography = pd.read_csv(self.paths["geography"])
        self.context_catalog = pd.read_csv(self.paths["context_catalog"])
        self.logistics_centers = pd.read_csv(
            self.paths["logistics_centers"],
            keep_default_na=False,
        )

        if len(self.master) != 13 or self.master["region_en"].nunique() != 13:
            raise MizanDataError("Master dataset must contain exactly 13 unique regions")
        if len(self.metric_catalog) != 17 or self.metric_catalog["metric_id"].nunique() != 17:
            raise MizanDataError("Phase 1 metric catalog must contain exactly 17 raw metrics")

        self.region_order = self.master.set_index("region_en")["region_id"].astype(int).to_dict()
        self.region_ar = self.master.set_index("region_en")["region_ar"].to_dict()
        self.raw_metrics = set(self.metric_catalog["metric_id"])
        # Public tools expose only approved raw metrics plus explicitly defined
        # deterministic derivations. Audit notes and source-reference columns in
        # the master file must never be treated as analysable metrics.
        self.all_metrics = set(self.raw_metrics) | set(DERIVED_METRICS)
        self._raw_catalog = self.metric_catalog.set_index("metric_id", drop=False)
        self._dictionary = self.dictionary.set_index("metric", drop=False)

    def resolve_region(self, value: str) -> str:
        text = " ".join(str(value).strip().split())
        if text in self.region_order:
            return text
        lowered = normalize_entity_text(text)
        canonical = resolve_region_alias(text) or REGION_ALIASES.get(lowered) or REGION_ALIASES.get(text)
        if canonical in self.region_order:
            return canonical
        raise MizanInputError(f"Unknown region: {value!r}")

    def resolve_regions(self, values: list[str] | tuple[str, ...]) -> list[str]:
        if not values:
            raise MizanInputError("At least one region is required")
        resolved = [self.resolve_region(value) for value in values]
        if len(set(resolved)) != len(resolved):
            raise MizanInputError("Duplicate regions are not allowed")
        return resolved

    def resolve_metric(self, metric_id: str) -> str:
        metric_id = str(metric_id).strip()
        if metric_id in self.all_metrics:
            return metric_id
        raise MizanInputError(f"Unknown metric: {metric_id!r}")

    def region_row(self, region: str) -> pd.Series:
        canonical = self.resolve_region(region)
        return self.master.loc[self.master["region_en"] == canonical].iloc[0]

    def metric_metadata(self, metric_id: str) -> dict[str, Any]:
        metric_id = self.resolve_metric(metric_id)
        if metric_id in DERIVED_METRICS:
            return {"metric_id": metric_id, "raw_or_derived": "derived", **DERIVED_METRICS[metric_id]}
        if metric_id in self.raw_metrics:
            row = clean_record(self._raw_catalog.loc[metric_id].to_dict())
            row.setdefault("source_metric_ids", [metric_id])
            row.setdefault("formula", None)
            return row
        if metric_id in self._dictionary.index:
            row = clean_record(self._dictionary.loc[metric_id].to_dict())
            return {
                "metric_id": metric_id,
                "metric_name_ar": row.get("label_ar"),
                "metric_name_en": metric_id,
                "unit": row.get("unit"),
                "period": row.get("period"),
                "raw_or_derived": "derived",
                "formula": row.get("definition_or_limitation"),
                "source_metric_ids": [],
                "screening_role": "descriptive",
                "comparability": "descriptive_only",
                "limitation_ar": row.get("definition_or_limitation"),
            }
        raise MizanInputError(f"Metric metadata is unavailable: {metric_id}")

    def source_records(self, metric_ids: list[str]) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        pending = list(metric_ids)
        while pending:
            metric_id = pending.pop(0)
            metadata = self.metric_metadata(metric_id)
            dependencies = metadata.get("source_metric_ids") or []
            if metadata.get("raw_or_derived") == "derived" and dependencies:
                pending.extend(dependencies)
                continue
            if metric_id in seen:
                continue
            seen.add(metric_id)
            sources.append({
                "metric_id": metric_id,
                "metric_name_ar": metadata.get("metric_name_ar"),
                "source_agency": metadata.get("source_agency"),
                "publisher": metadata.get("publisher"),
                "source_file": metadata.get("source_file"),
                "table_number": metadata.get("table_number"),
                "source_url": metadata.get("source_url"),
                "period": metadata.get("period"),
            })
        return sources

    def frame_for_regions(self, regions: list[str]) -> pd.DataFrame:
        resolved = self.resolve_regions(regions)
        frame = self.master[self.master["region_en"].isin(resolved)].copy()
        order = {region: index for index, region in enumerate(resolved)}
        frame["_requested_order"] = frame["region_en"].map(order)
        return frame.sort_values("_requested_order").drop(columns="_requested_order")


@lru_cache(maxsize=4)
def get_repository(root: str | Path | None = None) -> MizanRepository:
    cache_key = str(Path(root).resolve()) if root else None
    return MizanRepository(cache_key)
