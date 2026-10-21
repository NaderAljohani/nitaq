from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .definitions import (
    DERIVED_METRICS,
    MISSING_DATA_CATALOG,
    PRODUCT_LIMITATION,
    PROFILE_PAIRS,
    RAW_TO_NORMALIZED,
    SCREENING_ALLOWED,
    TREND_ALIASES,
    TREND_FAMILIES,
    WAREHOUSE_SCREENING_FAMILY,
)
from .exceptions import MizanInputError
from .entities import normalize_entity_text, resolve_port_alias
from .modon import load_modon_regional_context
from .repository import MizanRepository, clean_record, get_repository


DEFAULT_COMPARISON_METRICS = [
    "delivery_total_2024_source",
    "warehouse_count_2024",
    "freight_post_licenses_2024",
]

COMPREHENSIVE_COMPARISON_METRICS = [
    "population_2024",
    "delivery_total_2024_source",
    "warehouse_count_2024",
    "warehouse_area_sqm_2024",
    "freight_post_licenses_2024",
    "activated_logistics_centers_2024",
    "activated_logistics_centers_area_sqm_2024",
]

WAREHOUSE_DECISION_ALLOWED = SCREENING_ALLOWED | {
    "freight_post_licenses_per_100k_population_2024",
    "activated_logistics_centers_per_million_population_2024",
}

DEFAULT_WAREHOUSE_DECISION_CRITERIA = [
    {
        "metric_id": "delivery_requests_per_1000_population_2024",
        "direction": "higher",
        "weight": 0.6,
    },
    {
        "metric_id": "warehouse_area_sqm_per_capita_2024",
        "direction": "higher",
        "weight": 0.4,
    },
]


def _repo(repository: MizanRepository | None) -> MizanRepository:
    return repository or get_repository()


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, np.generic):
        return value.item()
    return value


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {str(key): _json_value(value) for key, value in record.items()}
        for record in frame.to_dict(orient="records")
    ]


def _unique_text(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value is None or (isinstance(value, float) and np.isnan(value)):
            continue
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


def _metadata_columns(repository: MizanRepository, metric_ids: list[str]) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = [
        {"column": "region_en", "label_ar": "المنطقة", "label_en": "Region", "unit": None, "value_kind": "dimension"},
        {"column": "region_ar", "label_ar": "المنطقة بالعربية", "label_en": "Region (Arabic)", "unit": None, "value_kind": "dimension"},
    ]
    for metric_id in metric_ids:
        metadata = repository.metric_metadata(metric_id)
        columns.append(
            {
                "column": metric_id,
                "label_ar": metadata.get("metric_name_ar"),
                "label_en": metadata.get("metric_name_en"),
                "unit": metadata.get("unit"),
                "period": metadata.get("period"),
                "raw_or_derived": metadata.get("raw_or_derived"),
                "comparability": metadata.get("comparability"),
                "value_kind": "normalized" if metric_id in DERIVED_METRICS else "raw",
            }
        )
    return columns


def _limitations(repository: MizanRepository, metric_ids: list[str]) -> list[str]:
    limits = [PRODUCT_LIMITATION]
    for metric_id in metric_ids:
        metadata = repository.metric_metadata(metric_id)
        limit = metadata.get("limitation_ar")
        if limit and str(limit).strip() not in limits:
            limits.append(str(limit).strip())
    return limits


def _missing_notes(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    notes: list[str] = []
    for column in columns:
        count = int(frame[column].isna().sum())
        if count:
            notes.append(f"{column}: {count} قيمة مفقودة بقيت null ولم تُحوّل إلى صفر.")
    if not notes:
        notes.append("لا توجد قيم مفقودة في نطاق الاستعلام؛ لم تُستخدم أي إحلالات.")
    return notes


def _normalised_companions(metric_ids: list[str]) -> list[str]:
    return [RAW_TO_NORMALIZED[m] for m in metric_ids if m in RAW_TO_NORMALIZED]


def _safe_percent_change(current: Any, baseline: Any) -> float | None:
    if current is None or baseline in (None, 0):
        return None
    return round((float(current) / float(baseline) - 1) * 100, 6)


def _pairwise_metric_differences(
    table: pd.DataFrame,
    metric_ids: list[str],
    repository: MizanRepository,
) -> list[dict[str, Any]]:
    """Calculate exact two-region differences in Python for grounded answers."""
    if len(table) != 2:
        return []
    left, right = table.iloc[0], table.iloc[1]
    differences: list[dict[str, Any]] = []
    for metric_id in metric_ids:
        left_value = _json_value(left.get(metric_id))
        right_value = _json_value(right.get(metric_id))
        absolute_difference = None
        absolute_gap = None
        higher_region = None
        percent_difference_from_second = None
        if left_value is not None and right_value is not None:
            absolute_difference = float(left_value) - float(right_value)
            absolute_gap = abs(absolute_difference)
            if absolute_difference > 0:
                higher_region = left["region_en"]
            elif absolute_difference < 0:
                higher_region = right["region_en"]
            else:
                higher_region = "equal"
            percent_difference_from_second = _safe_percent_change(left_value, right_value)
        metadata = repository.metric_metadata(metric_id)
        differences.append(
            {
                "metric_id": metric_id,
                "metric_name_ar": metadata.get("metric_name_ar"),
                "metric_name_en": metadata.get("metric_name_en"),
                "unit": metadata.get("unit"),
                "first_region": left["region_en"],
                "first_region_ar": left["region_ar"],
                "first_value": left_value,
                "second_region": right["region_en"],
                "second_region_ar": right["region_ar"],
                "second_value": right_value,
                "signed_difference_first_minus_second": _json_value(absolute_difference),
                "absolute_gap": _json_value(absolute_gap),
                "percent_difference_from_second": percent_difference_from_second,
                "higher_region": higher_region,
            }
        )
    return differences


def get_region_profile(
    region: str,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Return an evidence-rich 2024 profile for one canonical region."""
    repo = _repo(repository)
    row = repo.region_row(region)
    raw_values: list[dict[str, Any]] = []
    normalized_values: list[dict[str, Any]] = []
    metric_ids: list[str] = []

    table_record: dict[str, Any] = {
        "region_en": row["region_en"],
        "region_ar": row["region_ar"],
    }
    for raw_metric, normalized_metric in PROFILE_PAIRS:
        metric_ids.append(raw_metric)
        table_record[raw_metric] = _json_value(row.get(raw_metric))
        raw_values.append(
            {
                "metric_id": raw_metric,
                "value": _json_value(row.get(raw_metric)),
                **{
                    key: repo.metric_metadata(raw_metric).get(key)
                    for key in ("metric_name_ar", "metric_name_en", "unit", "period")
                },
            }
        )
        if normalized_metric:
            metric_ids.append(normalized_metric)
            table_record[normalized_metric] = _json_value(row.get(normalized_metric))
            normalized_values.append(
                {
                    "metric_id": normalized_metric,
                    "value": _json_value(row.get(normalized_metric)),
                    **{
                        key: repo.metric_metadata(normalized_metric).get(key)
                        for key in ("metric_name_ar", "metric_name_en", "unit", "period")
                    },
                }
            )

    quarterly = []
    for quarter in range(1, 5):
        metric_id = f"delivery_q{quarter}_2024"
        quarterly.append({"period": f"2024 Q{quarter}", "metric_id": metric_id, "value": _json_value(row[metric_id])})
        table_record[metric_id] = _json_value(row[metric_id])
        metric_ids.append(metric_id)

    port_rows = repo.ports.loc[repo.ports["region_en"] == row["region_en"]]
    port_summary = [
        clean_record(record)
        for record in port_rows[
            [
                "port_code",
                "port_name_en",
                "port_name_ar",
                "city_en",
                "official_port_files_available",
                "portwatch_available",
            ]
        ].to_dict(orient="records")
    ]

    return {
        "ok": True,
        "tool": "get_region_profile",
        "region": {"region_en": row["region_en"], "region_ar": row["region_ar"]},
        "raw_values": raw_values,
        "normalized_values": normalized_values,
        "table": [table_record],
        "columns": _metadata_columns(repo, metric_ids),
        "quarterly_delivery": quarterly,
        "port_context_summary": port_summary,
        "sources": repo.source_records(metric_ids),
        "limitations": _limitations(repo, metric_ids)
        + ["الموانئ سياق بوابة بحرية فقط؛ عدم وجود ميناء داخل المنطقة لا يُسجل كصفر."],
        "missing_data_notes": _missing_notes(pd.DataFrame([table_record]), metric_ids),
    }


def validate_comparison(
    regions: list[str],
    metric_ids: list[str],
    *,
    purpose: str = "comparison",
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Validate geographic coverage, metric roles, and double-counting rules."""
    repo = _repo(repository)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    resolved_regions: list[str] = []
    resolved_metrics: list[str] = []

    try:
        resolved_regions = repo.resolve_regions(regions)
    except MizanInputError as exc:
        errors.append({"code": "invalid_regions", "message": str(exc)})

    if not metric_ids:
        errors.append({"code": "missing_metrics", "message": "يجب تحديد مؤشر واحد على الأقل."})
    else:
        for metric_id in metric_ids:
            try:
                resolved_metrics.append(repo.resolve_metric(metric_id))
            except MizanInputError as exc:
                errors.append({"code": "unknown_metric", "message": str(exc)})

    if len(set(resolved_metrics)) != len(resolved_metrics):
        errors.append({"code": "duplicate_metrics", "message": "لا يُسمح بتكرار المؤشر نفسه."})

    if WAREHOUSE_SCREENING_FAMILY.issubset(set(resolved_metrics)):
        severity = errors if purpose == "screening" else warnings
        severity.append(
            {
                "code": "warehouse_double_count",
                "message": "عدد المستودعات ومساحتها وجهان للبصمة الترخيصية؛ اختر أحدهما في الفرز الأولي ولا تجمعهما في درجة واحدة.",
            }
        )

    quarterly_delivery = {f"delivery_q{quarter}_2024" for quarter in range(1, 5)}
    if "delivery_total_2024_source" in resolved_metrics and quarterly_delivery.intersection(resolved_metrics):
        warnings.append(
            {
                "code": "delivery_total_overlap",
                "message": "الإجمالي السنوي يساوي مجموع الأرباع؛ لا تعامل الإجمالي والأرباع كمعلومات مستقلة.",
            }
        )

    for metric_id in resolved_metrics:
        metadata = repo.metric_metadata(metric_id)
        if metadata.get("comparability") == "context_only":
            warnings.append(
                {
                    "code": "context_only_metric",
                    "message": f"{metric_id} للسياق أو الوصف فقط ولا يدعم استنتاج أفضلية مستقلة.",
                }
            )
        if int(metadata.get("coverage_regions") or 13) < 13:
            warnings.append(
                {
                    "code": "partial_coverage",
                    "message": f"{metric_id} لا يغطي المناطق الـ13 كاملة.",
                }
            )

    if purpose == "screening" and resolved_metrics:
        unknown = set(resolved_metrics) - SCREENING_ALLOWED
        if unknown:
            errors.append(
                {
                    "code": "screening_metric_not_allowed",
                    "message": f"غير مسموح في الفرز الأولي الحالي: {sorted(unknown)}",
                }
            )
        if "delivery_requests_per_1000_population_2024" not in resolved_metrics:
            errors.append(
                {
                    "code": "screening_requires_demand",
                    "message": "الفرز الأولي المحدود يتطلب إشارة التوصيل لكل ألف نسمة.",
                }
            )
        warehouse_count = len(set(resolved_metrics).intersection(WAREHOUSE_SCREENING_FAMILY))
        if warehouse_count != 1:
            errors.append(
                {
                    "code": "screening_requires_one_warehouse_family",
                    "message": "اختر مؤشرًا واحدًا فقط للبصمة الترخيصية: العدد السكاني المطبّع أو المساحة للفرد.",
                }
            )

    return {
        "ok": not errors,
        "tool": "validate_comparison",
        "purpose": purpose,
        "regions": resolved_regions,
        "metric_ids": resolved_metrics,
        "errors": errors,
        "warnings": warnings,
        "decision": "allowed_with_displayed_caveats" if not errors else "blocked",
    }


def compare_regions(
    regions: list[str],
    metric_ids: list[str] | None = None,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Compare regions without ranking and retain raw/normalized companions."""
    repo = _repo(repository)
    requested = list(metric_ids or DEFAULT_COMPARISON_METRICS)
    validation = validate_comparison(regions, requested, repository=repo)
    if not validation["ok"]:
        raise MizanInputError(str(validation["errors"]))

    normalized = _normalised_companions(validation["metric_ids"])
    selected = list(dict.fromkeys(validation["metric_ids"] + normalized))
    frame = repo.frame_for_regions(validation["regions"])
    table = frame[["region_en", "region_ar", *selected]].copy()

    raw_ids = [metric for metric in selected if metric not in DERIVED_METRICS]
    normalized_ids = [metric for metric in selected if metric in DERIVED_METRICS]
    limitations = _limitations(repo, selected)
    if set(validation["metric_ids"]) == set(COMPREHENSIVE_COMPARISON_METRICS):
        limitations.insert(
            0,
            "هذه مقارنة وصفية متعددة المؤشرات؛ القيمة الأعلى لا تعني دائمًا أداءً أفضل، لذلك لم تُنشأ درجة مركبة أو أوزان خفية.",
        )
    return {
        "ok": True,
        "tool": "compare_regions",
        "regions": validation["regions"],
        "requested_metric_ids": validation["metric_ids"],
        "comparison_scope": "comprehensive" if set(validation["metric_ids"]) == set(COMPREHENSIVE_COMPARISON_METRICS) else "selected",
        "metric_ids": selected,
        "raw_values": _records(table[["region_en", "region_ar", *raw_ids]]),
        "normalized_values": _records(table[["region_en", "region_ar", *normalized_ids]]) if normalized_ids else [],
        "table": _records(table),
        "pairwise_differences": _pairwise_metric_differences(table, selected, repo),
        "columns": _metadata_columns(repo, selected),
        "validation": validation,
        "sources": repo.source_records(selected),
        "limitations": limitations,
        "missing_data_notes": _missing_notes(table, selected),
    }


def _criterion_score(series: pd.Series, direction: str) -> pd.Series:
    if direction == "higher":
        return series.rank(method="average", pct=True) * 100
    if direction == "lower":
        return (-series).rank(method="average", pct=True) * 100
    raise MizanInputError("direction must be 'higher' or 'lower'")


def _screen_table(frame: pd.DataFrame, criteria: list[dict[str, Any]]) -> pd.DataFrame:
    result = frame[["region_id", "region_en", "region_ar"]].copy()
    total_weight = sum(float(item["weight"]) for item in criteria)
    weighted = pd.Series(0.0, index=frame.index)
    for item in criteria:
        metric_id = item["metric_id"]
        normalized_weight = float(item["weight"]) / total_weight
        component = _criterion_score(frame[metric_id], item["direction"])
        result[metric_id] = frame[metric_id]
        result[f"component__{metric_id}"] = component
        weighted = weighted + component * normalized_weight
    result["screening_index_0_100"] = weighted.round(6)
    # A documented region-id tie-break keeps the display position unique and
    # reproducible without pretending that tied index values differ.
    result = result.sort_values(
        ["screening_index_0_100", "region_id"], ascending=[False, True]
    ).reset_index(drop=True)
    result["screening_position"] = np.arange(1, len(result) + 1)
    return result.drop(columns="region_id")


def screen_regions(
    criteria: list[dict[str, Any]],
    *,
    top_n: int = 5,
    sensitivity_delta: float = 0.10,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Run the approved conditional two-signal screening."""
    repo = _repo(repository)
    if len(criteria) != 2:
        raise MizanInputError("الفرز الأولي المحدود يتطلب معيارين بالضبط: الطلب + مؤشر مستودعات واحد.")
    parsed: list[dict[str, Any]] = []
    for item in deepcopy(criteria):
        if not {"metric_id", "direction", "weight"}.issubset(item):
            raise MizanInputError("Each criterion requires metric_id, direction, and weight")
        metric_id = repo.resolve_metric(item["metric_id"])
        weight = float(item["weight"])
        if weight <= 0:
            raise MizanInputError("Weights must be positive")
        if item["direction"] not in {"higher", "lower"}:
            raise MizanInputError("direction must be 'higher' or 'lower'")
        parsed.append({"metric_id": metric_id, "direction": item["direction"], "weight": weight})

    validation = validate_comparison(
        list(repo.master["region_en"]),
        [item["metric_id"] for item in parsed],
        purpose="screening",
        repository=repo,
    )
    if not validation["ok"]:
        raise MizanInputError(str(validation["errors"]))
    if not 1 <= int(top_n) <= 13:
        raise MizanInputError("top_n must be between 1 and 13")
    if not 0 <= float(sensitivity_delta) <= 0.5:
        raise MizanInputError("sensitivity_delta must be between 0 and 0.5")

    frame = repo.master.copy()
    table = _screen_table(frame, parsed)

    scenarios: list[pd.DataFrame] = []
    base_weights = np.array([item["weight"] for item in parsed], dtype=float)
    base_weights = base_weights / base_weights.sum()
    for index in range(2):
        for sign in (-1, 1):
            changed = base_weights.copy()
            changed[index] = max(0.01, changed[index] + sign * float(sensitivity_delta))
            changed = changed / changed.sum()
            scenario_criteria = [dict(item, weight=float(changed[i])) for i, item in enumerate(parsed)]
            scenario = _screen_table(frame, scenario_criteria)[["region_en", "screening_position"]]
            scenario = scenario.rename(columns={"screening_position": f"scenario_{index}_{sign}"})
            scenarios.append(scenario)
    sensitivity = table[["region_en", "screening_position"]].copy()
    for scenario in scenarios:
        sensitivity = sensitivity.merge(scenario, on="region_en", how="left")
    scenario_columns = [column for column in sensitivity if column.startswith("scenario_")]
    sensitivity["position_min"] = sensitivity[scenario_columns].min(axis=1).astype(int)
    sensitivity["position_max"] = sensitivity[scenario_columns].max(axis=1).astype(int)
    sensitivity["position_range"] = sensitivity["position_max"] - sensitivity["position_min"]
    sensitivity = sensitivity[["region_en", "screening_position", "position_min", "position_max", "position_range"]]

    metric_ids = [item["metric_id"] for item in parsed]
    weights = sum(item["weight"] for item in parsed)
    criteria_echo = [dict(item, normalized_weight=item["weight"] / weights) for item in parsed]
    return {
        "ok": True,
        "tool": "screen_regions",
        "screening_scope": "conditional_evidence_exploration",
        "criteria": criteria_echo,
        "raw_values": [],
        "normalized_values": _records(table[["region_en", "region_ar", *metric_ids]]),
        "table": _records(table.head(int(top_n))),
        "full_table": _records(table),
        "sensitivity": _records(sensitivity),
        "columns": _metadata_columns(repo, metric_ids)
        + [
            {"column": "screening_index_0_100", "label_ar": "مؤشر الفرز الأولي المشروط", "label_en": "Conditional screening index", "unit": "0-100", "value_kind": "derived"},
            {"column": "screening_position", "label_ar": "الموضع تحت المعايير المختارة", "label_en": "Screening position", "unit": "ordinal", "value_kind": "derived"},
        ],
        "validation": validation,
        "sources": repo.source_records(metric_ids),
        "limitations": _limitations(repo, metric_ids)
        + [
            "الموضع يتغير بتغير الأوزان واتجاه المعايير، ولا توجد منطقة فائزة محفوظة.",
            "التحويل المئيني نسبي داخل المناطق الـ13 ولا يمثل احتمال نجاح أو درجة جدوى.",
        ],
        "missing_data_notes": _missing_notes(frame, metric_ids),
    }


def get_indicator_trend(
    regions: list[str],
    indicator: str,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Return annual or quarterly long-form series from approved snapshots."""
    repo = _repo(repository)
    family = TREND_ALIASES.get(indicator, indicator)
    if family not in TREND_FAMILIES:
        raise MizanInputError(f"Unknown trend family: {indicator!r}. Allowed: {sorted(TREND_FAMILIES)}")
    resolved = repo.resolve_regions(regions)
    metric_ids = TREND_FAMILIES[family]
    frame = repo.frame_for_regions(resolved)

    period_lookup: dict[str, str] = {}
    for metric_id in metric_ids:
        if "_q" in metric_id:
            quarter = metric_id.split("_q", 1)[1].split("_", 1)[0]
            period_lookup[metric_id] = f"2024 Q{quarter}"
        elif metric_id.endswith("_2023"):
            period_lookup[metric_id] = "2023"
        else:
            period_lookup[metric_id] = "2024"

    long_rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        for metric_id in metric_ids:
            metadata = repo.metric_metadata(metric_id)
            long_rows.append(
                {
                    "region_en": row["region_en"],
                    "region_ar": row["region_ar"],
                    "period": period_lookup[metric_id],
                    "metric_id": metric_id,
                    "value": _json_value(row[metric_id]),
                    "unit": metadata.get("unit"),
                }
            )
    long_frame = pd.DataFrame(long_rows)
    summaries: list[dict[str, Any]] = []
    for region in resolved:
        region_rows = long_frame.loc[long_frame["region_en"] == region].reset_index(drop=True)
        valid = region_rows.dropna(subset=["value"])
        if valid.empty:
            summaries.append({"region_en": region, "status": "no_values"})
            continue
        first = valid.iloc[0]
        last = valid.iloc[-1]
        minimum = valid.loc[valid["value"].idxmin()]
        maximum = valid.loc[valid["value"].idxmax()]
        absolute_change = float(last["value"]) - float(first["value"])
        summaries.append(
            {
                "region_en": region,
                "region_ar": first["region_ar"],
                "first_period": first["period"],
                "first_value": _json_value(first["value"]),
                "last_period": last["period"],
                "last_value": _json_value(last["value"]),
                "absolute_change": _json_value(absolute_change),
                "percent_change": _safe_percent_change(last["value"], first["value"]),
                "minimum_period": minimum["period"],
                "minimum_value": _json_value(minimum["value"]),
                "maximum_period": maximum["period"],
                "maximum_value": _json_value(maximum["value"]),
                "unit": first["unit"],
            }
        )
    return {
        "ok": True,
        "tool": "get_indicator_trend",
        "indicator": family,
        "regions": resolved,
        "raw_values": _records(long_frame),
        "normalized_values": [],
        "table": _records(long_frame),
        "trend_summary": summaries,
        "columns": [
            {"column": "region_en", "label_ar": "المنطقة", "label_en": "Region", "unit": None, "value_kind": "dimension"},
            {"column": "period", "label_ar": "الفترة", "label_en": "Period", "unit": None, "value_kind": "dimension"},
            {"column": "value", "label_ar": repo.metric_metadata(metric_ids[0]).get("metric_name_ar"), "label_en": repo.metric_metadata(metric_ids[0]).get("metric_name_en"), "unit": repo.metric_metadata(metric_ids[0]).get("unit"), "value_kind": "raw"},
        ],
        "sources": repo.source_records(metric_ids),
        "limitations": _limitations(repo, metric_ids),
        "missing_data_notes": _missing_notes(frame, metric_ids),
    }


def _resolve_ports(repo: MizanRepository, port: str | None, region: str | None) -> pd.DataFrame:
    ports = repo.ports.copy()
    if port:
        text = normalize_entity_text(port)
        canonical_code = resolve_port_alias(port)
        mask = pd.Series(False, index=ports.index)
        for column in ("port_code", "port_name_en", "port_name_ar", "portwatch_location"):
            if column in ports:
                normalized_column = ports[column].astype(str).map(normalize_entity_text)
                mask = mask | normalized_column.eq(text)
        if canonical_code:
            mask = mask | ports["port_code"].astype(str).str.upper().eq(canonical_code)
        ports = ports.loc[mask]
        if ports.empty:
            raise MizanInputError(f"Unknown port: {port!r}")
    if region:
        canonical = repo.resolve_region(region)
        ports = ports.loc[ports["region_en"] == canonical]
    if port is None and region is None:
        ports = ports.loc[ports["portwatch_available"].astype(bool)]
    return ports


def compare_ports(
    ports: list[str] | None = None,
    *,
    start: str | None = None,
    end: str | None = None,
    metric: str = "calls",
    direction: str | None = None,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Compare harmonized PortWatch series for selected or all covered ports."""
    repo = _repo(repository)
    requested_ports = list(ports or _unique_text(
        repo.ports.loc[repo.ports["portwatch_available"].astype(bool), "port_code"]
    ))
    if len(requested_ports) < 2:
        raise MizanInputError("Port comparison requires at least two ports")
    frames = [_resolve_ports(repo, port, None) for port in requested_ports]
    selected_all = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["port_code"])
    if len(selected_all) < 2:
        raise MizanInputError("Port comparison requires two distinct ports")
    unavailable = selected_all.loc[~selected_all["portwatch_available"].astype(bool)].copy()
    selected = selected_all.loc[selected_all["portwatch_available"].astype(bool)].copy()
    if len(selected) < 2:
        names = "، ".join(unavailable["port_name_ar"].fillna(unavailable["port_name_en"]).astype(str))
        raise MizanInputError(
            f"لا تتوفر سلسلتان بحريتان متوافقتان لإجراء المقارنة. الموانئ غير المغطاة حاليًا: {names or 'غير محدد'}."
        )

    locations = _unique_text(selected["portwatch_location"])
    series = repo.portwatch.loc[
        repo.portwatch["location"].isin(locations) & repo.portwatch["metric"].eq(metric)
    ].copy()
    if direction:
        series = series.loc[series["direction"].eq(direction)]
    if start:
        series = series.loc[series["date"] >= pd.Timestamp(start)]
    if end:
        series = series.loc[series["date"] <= pd.Timestamp(end)]
    series = series.sort_values(["location", "direction", "date"])
    if series.empty:
        raise MizanInputError("No comparable observations match the selected period, metric, and direction")

    summary_rows: list[dict[str, Any]] = []
    for (location, series_direction), group in series.groupby(["location", "direction"], sort=False):
        group = group.sort_values("date")
        summary_rows.append(
            {
                "location": location,
                "direction": series_direction,
                "metric": metric,
                "start": group.iloc[0]["date"].date().isoformat(),
                "end": group.iloc[-1]["date"].date().isoformat(),
                "observations": int(len(group)),
                "total_period_activity": _json_value(group["total_activity"].sum()),
                "mean_monthly_activity": _json_value(group["total_activity"].mean()),
                "latest_month_activity": _json_value(group.iloc[-1]["total_activity"]),
            }
        )
    summary = pd.DataFrame(summary_rows)
    differences: list[dict[str, Any]] = []
    if len(summary) == 2 and summary["direction"].nunique() == 1:
        left, right = summary.iloc[0], summary.iloc[1]
        for measure in ("total_period_activity", "mean_monthly_activity", "latest_month_activity"):
            signed = float(left[measure]) - float(right[measure])
            differences.append(
                {
                    "measure": measure,
                    "first_location": left["location"],
                    "first_value": _json_value(left[measure]),
                    "second_location": right["location"],
                    "second_value": _json_value(right[measure]),
                    "signed_difference_first_minus_second": _json_value(signed),
                    "absolute_gap": abs(signed),
                    "percent_difference_from_second": _safe_percent_change(left[measure], right[measure]),
                    "higher_location": left["location"] if signed > 0 else right["location"] if signed < 0 else "equal",
                }
            )

    table_columns = ["date", "location", "metric", "direction", "total_activity"]
    selected_ports = [
        clean_record(record)
        for record in selected_all[
            ["port_code", "port_name_en", "port_name_ar", "city_en", "region_en", "region_ar", "portwatch_location"]
        ].to_dict(orient="records")
    ]
    unavailable_ports = [
        clean_record(record)
        for record in unavailable[
            ["port_code", "port_name_en", "port_name_ar", "city_en", "region_en", "region_ar"]
        ].to_dict(orient="records")
    ]
    return {
        "ok": True,
        "tool": "compare_ports",
        "selection": {"ports": requested_ports, "start": start, "end": end, "metric": metric, "direction": direction},
        "ports": selected_ports,
        "unavailable_ports": unavailable_ports,
        "table": _records(series[table_columns]),
        "summary": _records(summary),
        "pairwise_differences": differences,
        "columns": [
            {"column": "date", "label_ar": "الشهر", "label_en": "Month", "unit": None, "value_kind": "dimension"},
            {"column": "location", "label_ar": "الميناء/الموقع", "label_en": "Port / location", "unit": None, "value_kind": "dimension"},
            {"column": "direction", "label_ar": "الاتجاه", "label_en": "Direction", "unit": None, "value_kind": "dimension"},
            {"column": "total_activity", "label_ar": "النشاط المرصود", "label_en": "Observed activity", "unit": "PortWatch experimental activity unit", "value_kind": "raw"},
        ],
        "sources": [
            {
                "dataset": "IMF PortWatch monthly long",
                "source_file": str(repo.paths["portwatch"].relative_to(repo.root)).replace("\\", "/"),
                "source_url": "https://portwatch.imf.org/",
                "coverage": "January 2019 to May 2026 for selected PortWatch locations",
            },
            {
                "dataset": "Saudi ports public-data mapping",
                "source_file": str(repo.paths["ports"].relative_to(repo.root)).replace("\\", "/"),
                "source_url": "https://www.mawani.gov.sa/",
            },
        ],
        "limitations": [
            PRODUCT_LIMITATION,
            "المقارنة تصف مؤشر PortWatch التجريبي للفترة المتطابقة فقط؛ لا تقيس السعة أو الإشغال أو زمن التخليص.",
            "هذه مقارنة بين موانئ مغطاة وليست مقارنة عادلة بين المناطق الإدارية الـ13.",
        ],
        "missing_data_notes": (
            [
                "لا تتوفر سلسلة نشاط بحري منسقة حاليًا لـ"
                + "، ".join(port.get("port_name_ar") or port.get("port_name_en") for port in unavailable_ports)
                + "؛ لم تُحوّل القيم غير المتاحة إلى أصفار."
            ]
            if unavailable_ports
            else ["لا توجد قيم مفقودة في السلاسل المتطابقة المسترجعة؛ لم تُستخدم أي إحلالات."]
        ),
    }


def evaluate_warehouse_locations(
    locations: list[str] | None = None,
    *,
    regional_criteria: list[dict[str, Any]] | None = None,
    ports: list[str] | None = None,
    include_port: bool = False,
    port_metric: str = "trade_volume",
    port_direction: str | None = "incoming",
    port_weight: float = 0.25,
    top_n: int = 5,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Evaluate warehouse-location candidates with transparent, computed evidence.

    The function never stores a preferred answer. It ranks the candidates supplied
    at runtime (or all 13 regions) from the selected regional criteria, and can add
    a comparable port signal only when every named candidate is covered.
    """
    repo = _repo(repository)
    requested_locations = list(locations or repo.master["region_en"].tolist())
    resolved_regions = repo.resolve_regions(requested_locations)
    if len(resolved_regions) < 2:
        raise MizanInputError("Warehouse-location evaluation requires at least two distinct candidates")
    if not 1 <= int(top_n) <= len(resolved_regions):
        raise MizanInputError("top_n must be between 1 and the number of candidates")

    criteria_input = deepcopy(regional_criteria or DEFAULT_WAREHOUSE_DECISION_CRITERIA)
    if not 2 <= len(criteria_input) <= 4:
        raise MizanInputError("Warehouse-location evaluation requires between two and four regional criteria")
    parsed: list[dict[str, Any]] = []
    for item in criteria_input:
        if not {"metric_id", "direction", "weight"}.issubset(item):
            raise MizanInputError("Each regional criterion requires metric_id, direction, and weight")
        metric_id = repo.resolve_metric(item["metric_id"])
        if metric_id not in WAREHOUSE_DECISION_ALLOWED:
            raise MizanInputError(f"Metric is not approved for warehouse-location evaluation: {metric_id}")
        direction = str(item["direction"])
        weight = float(item["weight"])
        if direction not in {"higher", "lower"} or weight <= 0:
            raise MizanInputError("Criterion direction must be higher/lower and weight must be positive")
        parsed.append({"metric_id": metric_id, "direction": direction, "weight": weight})
    metric_ids = [item["metric_id"] for item in parsed]
    if len(set(metric_ids)) != len(metric_ids):
        raise MizanInputError("Duplicate decision criteria are not allowed")
    if WAREHOUSE_SCREENING_FAMILY.issubset(set(metric_ids)):
        raise MizanInputError("Use warehouse count or warehouse area, not both, to avoid double counting")
    if "delivery_requests_per_1000_population_2024" not in metric_ids:
        raise MizanInputError("Warehouse-location evaluation requires the documented demand signal")

    frame = (
        repo.frame_for_regions(resolved_regions)[["region_id", "region_en", "region_ar", *metric_ids]]
        .copy()
        .reset_index(drop=True)
    )
    regional_weight_total = sum(item["weight"] for item in parsed)
    regional_share = 1.0
    if include_port:
        if port_metric not in {"calls", "trade_volume"}:
            raise MizanInputError("port_metric must be calls or trade_volume")
        if not 0 < float(port_weight) < 1:
            raise MizanInputError("port_weight must be greater than 0 and less than 1")
        regional_share = 1.0 - float(port_weight)

    score = pd.Series(0.0, index=frame.index)
    criteria_echo: list[dict[str, Any]] = []
    for item in parsed:
        normalized_weight = item["weight"] / regional_weight_total * regional_share
        component = _criterion_score(frame[item["metric_id"]], item["direction"])
        frame[f"component__{item['metric_id']}"] = component.round(6)
        score = score + component * normalized_weight
        criteria_echo.append({**item, "normalized_weight": normalized_weight, "criterion_type": "regional"})

    port_result: dict[str, Any] | None = None
    selected_port_records: list[dict[str, Any]] = []
    port_summary: list[dict[str, Any]] = []
    if include_port:
        selected_port_codes = list(dict.fromkeys(ports or []))
        if not selected_port_codes:
            for location, region in zip(requested_locations, resolved_regions, strict=True):
                alias = resolve_port_alias(location)
                if alias:
                    selected_port_codes.append(alias)
                    continue
                available = repo.ports.loc[
                    (repo.ports["region_en"] == region) & repo.ports["portwatch_available"].astype(bool)
                ]
                if len(available) == 1:
                    selected_port_codes.append(str(available.iloc[0]["port_code"]))
        if len(selected_port_codes) < len(resolved_regions):
            raise MizanInputError(
                "A comparable mapped port is required for every candidate when port activity is included"
            )
        effective_direction = port_direction or ("incoming" if port_metric == "trade_volume" else "port")
        port_result = compare_ports(
            selected_port_codes,
            metric=port_metric,
            direction=effective_direction,
            repository=repo,
        )
        selected_port_records = port_result.get("ports", [])
        location_to_region = {
            item.get("portwatch_location"): item.get("region_en")
            for item in selected_port_records
            if item.get("portwatch_location") and item.get("region_en")
        }
        port_frame = pd.DataFrame(port_result.get("summary", []))
        if port_frame.empty:
            raise MizanInputError("No comparable port activity was returned for the selected candidates")
        port_frame["region_en"] = port_frame["location"].map(location_to_region)
        port_frame = (
            port_frame.dropna(subset=["region_en"])
            .groupby("region_en", as_index=False)["mean_monthly_activity"]
            .sum()
        )
        if set(port_frame["region_en"]) != set(resolved_regions):
            raise MizanInputError("Port coverage is incomplete across the selected warehouse candidates")
        frame = frame.merge(port_frame, on="region_en", how="left", validate="one_to_one")
        port_component = _criterion_score(frame["mean_monthly_activity"], "higher")
        frame["component__port_activity"] = port_component.round(6)
        score = score + port_component * float(port_weight)
        criteria_echo.append(
            {
                "metric_id": "port_activity",
                "direction": "higher",
                "weight": float(port_weight),
                "normalized_weight": float(port_weight),
                "criterion_type": "port",
                "port_metric": port_metric,
                "port_direction": effective_direction,
            }
        )
        port_summary = _records(port_frame)

    frame["decision_index_0_100"] = score.round(6)
    frame = frame.sort_values(["decision_index_0_100", "region_id"], ascending=[False, True]).reset_index(drop=True)
    frame["decision_position"] = np.arange(1, len(frame) + 1)

    city_by_region: dict[str, tuple[str, str]] = {}
    for port in selected_port_records:
        if port.get("region_en") and port.get("city_en"):
            city_by_region[port["region_en"]] = (port.get("city_en"), port.get("city_ar") or port.get("city_en"))
    frame["candidate_en"] = frame.apply(
        lambda row: city_by_region.get(row["region_en"], (row["region_en"], row["region_ar"]))[0], axis=1
    )
    frame["candidate_ar"] = frame.apply(
        lambda row: city_by_region.get(row["region_en"], (row["region_en"], row["region_ar"]))[1], axis=1
    )

    result_columns = [
        "region_en", "region_ar", "candidate_en", "candidate_ar", *metric_ids,
        *( ["mean_monthly_activity"] if include_port else [] ),
        "decision_index_0_100", "decision_position",
        *[column for column in frame.columns if column.startswith("component__")],
    ]
    source_records = repo.source_records(metric_ids)
    if port_result:
        source_records.extend(port_result.get("sources", []))
    sources: list[dict[str, Any]] = []
    seen_sources: set[tuple[Any, Any]] = set()
    for source in source_records:
        identity = (source.get("source_file") or source.get("source_path"), source.get("source_url"))
        if identity not in seen_sources:
            seen_sources.add(identity)
            sources.append(source)

    limitations_ar = [
        "النتيجة ترشيح استكشافي محسوب من المعايير والأوزان الحالية وليست ضمان نجاح أو دراسة جدوى.",
        "ارتفاع بصمة المستودعات قد يدل على منظومة لوجستية قوية أو منافسة أعلى؛ لا تتوفر بيانات إشغال لحسم التفسير.",
        "قيم المدن ممثلة ببيانات مناطقها الإدارية، ويحتاج اختيار الموقع داخل المدينة إلى بيانات موقعية أدق.",
        *_limitations(repo, metric_ids),
    ]
    limitations_en = [
        "The result is an exploratory ranking computed from the current criteria and weights, not a feasibility study or guarantee of success.",
        "A larger licensed warehouse footprint may indicate a stronger logistics ecosystem or greater competition; occupancy data is unavailable to distinguish the two.",
        "City candidates use evidence from their administrative regions; choosing a site within a city requires more granular location data.",
    ]
    if port_result:
        limitations_ar.append("نشاط PortWatch سياق تجريبي جزئي ولا يقيس السعة أو الإشغال أو زمن التخليص.")
        limitations_en.append(
            "PortWatch activity is partial experimental context and does not measure capacity, occupancy, or customs-clearance time."
        )

    columns = _metadata_columns(repo, metric_ids) + [
        {"column": "candidate_en", "label_ar": "المرشح", "label_en": "Candidate", "unit": None, "value_kind": "dimension"},
        {"column": "candidate_ar", "label_ar": "المرشح", "label_en": "Candidate", "unit": None, "value_kind": "dimension"},
        {"column": "mean_monthly_activity", "label_ar": "متوسط نشاط الميناء الشهري", "label_en": "Mean monthly port activity", "unit": "PortWatch experimental activity unit", "value_kind": "context"},
        {"column": "decision_index_0_100", "label_ar": "مؤشر نسبي ضمن المرشحين", "label_en": "Relative index within candidates", "unit": "0-100 relative index", "value_kind": "derived"},
        {"column": "decision_position", "label_ar": "موضع الترشيح", "label_en": "Recommendation position", "unit": "ordinal", "value_kind": "derived"},
    ]
    return {
        "ok": True,
        "tool": "evaluate_warehouse_locations",
        "decision_scope": "runtime_multi_signal_warehouse_location_evaluation",
        "selection": {
            "locations": requested_locations,
            "include_port": bool(include_port),
            "ports": list(ports or []),
            "port_metric": port_metric if include_port else None,
            "port_direction": (port_direction or ("incoming" if port_metric == "trade_volume" else "port")) if include_port else None,
            "port_weight": float(port_weight) if include_port else 0.0,
        },
        "regions": resolved_regions,
        "ports": selected_port_records,
        "criteria": criteria_echo,
        "table": _records(frame[result_columns].head(int(top_n))),
        "full_table": _records(frame[result_columns]),
        "port_summary": port_summary,
        "columns": columns,
        "sources": sources,
        "limitations": list(dict.fromkeys(limitations_ar)),
        "limitations_en": limitations_en,
        "missing_data_notes": [
            "لا تتوفر بيانات موحدة للإيجارات والإشغال والسعة التشغيلية والمنافسة على مستوى المدن.",
        ],
        "missing_data_notes_en": [
            "Comparable city-level rent, occupancy, operating-capacity, and competition data is not available in the current evidence base.",
        ],
    }


def list_logistics_centers(
    regions: list[str] | None = None,
    *,
    status: str = "all",
    owner: str | None = None,
    sort_by: str = "regional_distribution",
    limit: int | None = None,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Return the current Logisti center listing without mixing it with 2024 statistics."""
    repo = _repo(repository)
    if status not in {"all", "active", "inactive"}:
        raise MizanInputError("status must be all, active, or inactive")
    if sort_by not in {"regional_distribution", "area_desc", "area_asc"}:
        raise MizanInputError("sort_by must be regional_distribution, area_desc, or area_asc")
    if limit is not None and not 1 <= int(limit) <= 59:
        raise MizanInputError("limit must be between 1 and 59")

    frame = repo.logistics_centers.copy()
    resolved_regions = repo.resolve_regions(regions) if regions else []
    if resolved_regions:
        frame = frame.loc[frame["region_en_derived"].isin(resolved_regions)].copy()

    if owner:
        owner_text = normalize_entity_text(owner)
        modon_aliases = {"modon", "مدن", "هيئة مدن", "الهيئة السعودية للمدن الصناعية ومناطق التقنية"}
        if owner_text in {normalize_entity_text(item) for item in modon_aliases}:
            owner_text = normalize_entity_text("الهيئة السعودية للمدن الصناعية ومناطق التقنية")
        normalized_owners = frame["owner_ar"].map(normalize_entity_text)
        frame = frame.loc[normalized_owners.str.contains(owner_text, regex=False)].copy()

    scoped = frame.copy()
    if status != "all":
        expected = "Active" if status == "active" else "Inactive"
        frame = frame.loc[frame["status_en"].eq(expected)].copy()

    if scoped.empty:
        summary = pd.DataFrame(
            columns=["region_en", "region_ar", "total_centers", "active_centers", "inactive_centers"]
        )
    else:
        summary = (
            scoped.assign(
                active_centers=scoped["status_en"].eq("Active").astype(int),
                inactive_centers=scoped["status_en"].eq("Inactive").astype(int),
            )
            .groupby(["region_en_derived", "region_ar_derived"], as_index=False)
            .agg(
                total_centers=("center_id", "count"),
                active_centers=("active_centers", "sum"),
                inactive_centers=("inactive_centers", "sum"),
            )
            .rename(columns={"region_en_derived": "region_en", "region_ar_derived": "region_ar"})
        )
        summary["_order"] = summary["region_en"].map(repo.region_order)
        summary = summary.sort_values(["total_centers", "_order"], ascending=[False, True]).drop(columns="_order")

    detail_columns = [
        "center_id",
        "center_name_ar",
        "region_ar_derived",
        "region_en_derived",
        "owner_ar",
        "center_type_ar",
        "area_sqm_reconciled",
        "status_ar",
        "status_en",
        "latitude",
        "longitude",
        "map_url",
    ]
    details = frame[detail_columns].copy()
    details["area_sqm_reconciled"] = pd.to_numeric(details["area_sqm_reconciled"], errors="coerce")
    matching_count = int(len(details))
    if sort_by == "area_desc":
        details = details.sort_values("area_sqm_reconciled", ascending=False, na_position="last", kind="stable")
    elif sort_by == "area_asc":
        details = details.sort_values("area_sqm_reconciled", ascending=True, na_position="last", kind="stable")
    else:
        details = details.sort_values(["region_en_derived", "center_id"], kind="stable")
    if limit is not None:
        details = details.head(int(limit))

    snapshot_total = int(len(repo.logistics_centers))
    snapshot_active = int(repo.logistics_centers["status_en"].eq("Active").sum())
    snapshot_inactive = int(repo.logistics_centers["status_en"].eq("Inactive").sum())
    official_2024_total = int(repo.master["activated_logistics_centers_2024"].sum())
    snapshot_date = str(repo.logistics_centers["snapshot_date"].iloc[0]) if snapshot_total else None
    source_url = str(repo.logistics_centers["source_url"].iloc[0]) if snapshot_total else None
    return {
        "ok": True,
        "tool": "list_logistics_centers",
        "regions": resolved_regions,
        "selection": {"status": status, "owner": owner, "sort_by": sort_by, "limit": limit},
        "snapshot_summary": {
            "snapshot_date": snapshot_date,
            "listed_centers": snapshot_total,
            "active_centers": snapshot_active,
            "inactive_centers": snapshot_inactive,
            "official_2024_activated_centers": official_2024_total,
            "matching_centers": matching_count,
        },
        "table": _records(summary),
        "details": _records(details),
        "columns": [
            {"column": "region_en", "label_ar": "المنطقة", "label_en": "Region", "value_kind": "dimension"},
            {"column": "region_ar", "label_ar": "المنطقة", "label_en": "Region (Arabic)", "value_kind": "dimension"},
            {"column": "total_centers", "label_ar": "إجمالي المراكز المدرجة", "label_en": "Listed centers", "unit": "center", "value_kind": "raw"},
            {"column": "active_centers", "label_ar": "المراكز المفعلة", "label_en": "Active centers", "unit": "center", "value_kind": "raw"},
            {"column": "inactive_centers", "label_ar": "المراكز غير المفعلة", "label_en": "Inactive centers", "unit": "center", "value_kind": "raw"},
        ],
        "sources": [
            {
                "source_id": "logisti_centers_snapshot_2026",
                "source_agency": "Logisti / Ministry of Transport and Logistics Services",
                "source_path": "data/processed/runtime/logistics_centers_snapshot_2026-07-28.csv",
                "source_url": source_url,
                "period": f"snapshot {snapshot_date}",
            },
            *repo.source_records(["activated_logistics_centers_2024"]),
        ],
        "limitations": [
            "لقطة لوجستي الحالية وقيمة المراكز المفعلة الرسمية لعام 2024 مصدران مختلفان في السنة والتعريف؛ لا تُجمع القيم ولا يُستبدل أحدهما بالآخر.",
            "حالة المركز في اللقطة لا تقيس الإشغال أو السعة التشغيلية أو توفر أرض للاستثمار.",
        ],
        "limitations_en": [
            "The current Logisti listing and the official 2024 activated-center statistic differ in date and definition; their values must not be combined or substituted.",
            "A listed status does not measure occupancy, operating capacity, or land availability for investment.",
        ],
        "missing_data_notes": [],
        "missing_data_notes_en": [],
    }


def compare_logistics_gateways(
    regions: list[str],
    *,
    ports: list[str] | None = None,
    port_metric: str = "trade_volume",
    port_direction: str | None = "incoming",
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Compare maritime activity and logistics-center presence without a composite score."""
    repo = _repo(repository)
    resolved_regions = repo.resolve_regions(regions)
    if len(resolved_regions) < 2:
        raise MizanInputError("Gateway comparison requires at least two distinct regions")
    if port_metric not in {"calls", "trade_volume"}:
        raise MizanInputError("port_metric must be calls or trade_volume")
    effective_direction = port_direction or ("incoming" if port_metric == "trade_volume" else "port")

    if ports:
        selected_codes = list(dict.fromkeys(resolve_port_alias(item) or item for item in ports))
        selected_records = _records(repo.ports.loc[repo.ports["port_code"].isin(selected_codes)].copy())
        if len(selected_records) != len(selected_codes):
            raise MizanInputError("One or more selected ports are unknown")
        outside = [item.get("port_name_en") for item in selected_records if item.get("region_en") not in resolved_regions]
        if outside:
            raise MizanInputError("Selected ports must belong to the selected regions")
    else:
        selected_records = _records(
            repo.ports.loc[
                repo.ports["region_en"].isin(resolved_regions) & repo.ports["portwatch_available"].astype(bool)
            ]
        )
        selected_codes = [item["port_code"] for item in selected_records]
    covered_regions = {item.get("region_en") for item in selected_records if item.get("portwatch_available")}
    missing_port_regions = [region for region in resolved_regions if region not in covered_regions]
    covered_records = [item for item in selected_records if item.get("portwatch_available")]
    if len(covered_records) < 2:
        raise MizanInputError("At least two mapped PortWatch series are required for this gateway comparison")

    port_result = compare_ports(
        [item["port_code"] for item in covered_records],
        metric=port_metric,
        direction=effective_direction,
        repository=repo,
    )
    port_lookup = {
        item.get("portwatch_location"): item
        for item in port_result.get("ports", [])
        if item.get("portwatch_location")
    }
    port_rows = pd.DataFrame(port_result.get("summary", []))
    port_rows["region_en"] = port_rows["location"].map(
        lambda location: (port_lookup.get(location) or {}).get("region_en")
    )
    port_rows["port_name_ar"] = port_rows["location"].map(
        lambda location: (port_lookup.get(location) or {}).get("port_name_ar")
    )
    port_grouped = (
        port_rows.dropna(subset=["region_en"])
        .groupby("region_en", as_index=False)
        .agg(
            covered_ports=("location", "nunique"),
            covered_port_names_ar=("port_name_ar", lambda values: "، ".join(str(value) for value in values if value)),
            mean_monthly_port_activity=("mean_monthly_activity", "sum"),
            latest_month_port_activity=("latest_month_activity", "sum"),
            port_series_start=("start", "min"),
            port_series_end=("end", "max"),
        )
    )

    centers_result = list_logistics_centers(resolved_regions, repository=repo)
    centers = pd.DataFrame(centers_result.get("table", []))
    if centers.empty:
        centers = pd.DataFrame({"region_en": resolved_regions})
    official = repo.frame_for_regions(resolved_regions)[
        ["region_en", "region_ar", "activated_logistics_centers_2024"]
    ].copy()
    table = official.merge(
        centers[["region_en", "total_centers", "active_centers", "inactive_centers"]],
        on="region_en",
        how="left",
    ).merge(port_grouped, on="region_en", how="left")
    for column in ("total_centers", "active_centers", "inactive_centers", "covered_ports"):
        table[column] = table[column].fillna(0).astype(int)
    table = table.rename(
        columns={
            "total_centers": "current_listed_centers",
            "active_centers": "current_active_centers",
            "inactive_centers": "current_inactive_centers",
        }
    )

    limitations = [
        "لا تُنتج هذه المقارنة درجة فوز واحدة؛ فهي تعرض نشاط الموانئ وحضور المراكز كمحورين مستقلين.",
        "نشاط PortWatch تغطية تجريبية جزئية للموانئ المتاحة فقط، ولا يساوي السعة التصميمية أو جودة الميناء أو زمن التخليص.",
        "لقطة المراكز الحالية وإحصاء المراكز المفعلة لعام 2024 يختلفان في التاريخ والتعريف ولا تُجمع قيمهما.",
    ]
    if missing_port_regions:
        limitations.insert(1, "لا تتوفر سلسلة PortWatch منسقة لبعض المناطق المحددة؛ تُعرض قيمها البحرية كغير متاحة لا كصفر.")
    return {
        "ok": True,
        "tool": "compare_logistics_gateways",
        "regions": resolved_regions,
        "ports": port_result.get("ports", []),
        "selection": {
            "regions": resolved_regions,
            "ports": selected_codes,
            "port_metric": port_metric,
            "port_direction": effective_direction,
        },
        "table": _records(table),
        "columns": [
            {"column": "region_en", "label_ar": "المنطقة", "label_en": "Region", "value_kind": "dimension"},
            {"column": "region_ar", "label_ar": "المنطقة", "label_en": "Region (Arabic)", "value_kind": "dimension"},
            {"column": "covered_ports", "label_ar": "الموانئ المغطاة", "label_en": "Covered ports", "unit": "port", "value_kind": "coverage"},
            {"column": "covered_port_names_ar", "label_ar": "الموانئ المشمولة", "label_en": "Included ports", "value_kind": "dimension"},
            {"column": "mean_monthly_port_activity", "label_ar": "متوسط النشاط البحري الشهري المرصود", "label_en": "Mean monthly observed maritime activity", "unit": "PortWatch experimental activity unit", "value_kind": "context"},
            {"column": "current_listed_centers", "label_ar": "المراكز المدرجة حاليًا", "label_en": "Current listed centers", "unit": "center", "value_kind": "raw"},
            {"column": "current_active_centers", "label_ar": "المراكز المفعلة حاليًا", "label_en": "Current active centers", "unit": "center", "value_kind": "raw"},
            {"column": "activated_logistics_centers_2024", "label_ar": "المراكز اللوجستية المفعلة رسميًا", "label_en": "Official activated logistics centers", "unit": "activated center", "period": "2024", "value_kind": "raw"},
        ],
        "sources": [*port_result.get("sources", []), *centers_result.get("sources", [])],
        "limitations": limitations,
        "limitations_en": [
            "This comparison produces no single winner score; port activity and center presence remain separate axes.",
            "PortWatch is partial experimental coverage and does not measure designed port capacity, port quality, or clearance time.",
            "The current center snapshot and the official 2024 activated-center statistic differ in date and definition and are not added together.",
        ],
        "missing_data_notes": [
            "لا تتوفر بيانات موحدة عن سعة الميناء التصميمية، إشغال المراكز، جودة الطرق، أو زمن التخليص."
        ],
        "missing_data_notes_en": [
            "Comparable designed port capacity, center occupancy, road quality, and clearance-time data are unavailable."
        ],
    }


def get_modon_context(
    regions: list[str] | None = None,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Normalize MODON workbooks into comparable regional industrial evidence."""
    repo = _repo(repository)
    result = list_logistics_centers(regions, owner="MODON", repository=repo)
    regional = load_modon_regional_context(repo.root)
    industrial_table = regional["table"].copy()
    if result.get("regions"):
        industrial_table = industrial_table.loc[industrial_table["region_en"].isin(result["regions"])].copy()

    center_table = pd.DataFrame(result.get("table", []))
    if not center_table.empty:
        center_table = center_table.rename(
            columns={
                "total_centers": "current_modon_listed_centers",
                "active_centers": "current_modon_active_centers",
                "inactive_centers": "current_modon_inactive_centers",
            }
        )
        center_table = center_table.drop(columns=["region_ar"], errors="ignore")
        industrial_table = industrial_table.merge(center_table, on="region_en", how="left")
    for column in (
        "current_modon_listed_centers",
        "current_modon_active_centers",
        "current_modon_inactive_centers",
    ):
        if column not in industrial_table:
            industrial_table[column] = 0
        industrial_table[column] = industrial_table[column].fillna(0).astype(int)

    assets = [
        {
            "file_name": str(source.get("source_path") or source.get("source_id")).split("/")[-1],
            "source_path": source.get("source_path"),
        }
        for source in regional.get("sources", [])
    ]
    result.update(
        tool="get_modon_context",
        center_table=result.get("table", []),
        table=_records(industrial_table),
        industrial_assets=assets,
        unmapped_industrial_cities=regional.get("unmapped_industrial_cities", []),
        columns=[
            {"column": "region_en", "label_ar": "المنطقة", "label_en": "Region", "value_kind": "dimension"},
            {"column": "region_ar", "label_ar": "المنطقة", "label_en": "Region (Arabic)", "value_kind": "dimension"},
            {"column": "productive_factories_q4_2023", "label_ar": "المصانع المنتجة", "label_en": "Productive factories", "unit": "factory", "period": "2023 Q4", "value_kind": "raw"},
            {"column": "productive_industrial_cities_q4_2023", "label_ar": "المدن الصناعية المغطاة ببيانات المصانع", "label_en": "Industrial cities in factory data", "unit": "industrial city", "period": "2023 Q4", "value_kind": "raw"},
            {"column": "industrial_city_area_sqm_q2_2024", "label_ar": "إجمالي مساحة المدن الصناعية", "label_en": "Total industrial-city area", "unit": "square meter", "period": "2024 Q2", "value_kind": "raw"},
            {"column": "industrial_cities_with_area_q2_2024", "label_ar": "المدن الصناعية المغطاة ببيانات المساحة", "label_en": "Industrial cities in area data", "unit": "industrial city", "period": "2024 Q2", "value_kind": "raw"},
            {"column": "ready_factory_units_2023", "label_ar": "وحدات المصانع الجاهزة", "label_en": "Ready-factory units", "unit": "ready factory unit", "period": "2023; published 2024", "value_kind": "raw"},
            {"column": "ready_factory_designated_area_sqm_2023", "label_ar": "المساحة المخصصة للمصانع الجاهزة", "label_en": "Designated ready-factory area", "unit": "square meter", "period": "2023; published 2024", "value_kind": "raw"},
            {"column": "ready_factory_sites_with_rental_available_2023", "label_ar": "مواقع المصانع الجاهزة ذات التأجير المتاح", "label_en": "Ready-factory sites with rental availability", "unit": "industrial city", "period": "2023; published 2024", "value_kind": "raw"},
            {"column": "current_modon_listed_centers", "label_ar": "مراكز MODON المدرجة حاليًا", "label_en": "Current listed MODON centers", "unit": "center", "period": result.get("snapshot_summary", {}).get("snapshot_date"), "value_kind": "raw"},
            {"column": "current_modon_active_centers", "label_ar": "مراكز MODON المفعلة حاليًا", "label_en": "Current active MODON centers", "unit": "center", "period": result.get("snapshot_summary", {}).get("snapshot_date"), "value_kind": "raw"},
        ],
        sources=[
            *result.get("sources", [])[:1],
            *regional.get("sources", []),
        ],
        limitations=[
            "جُمعت ملفات MODON المنشورة حسب المدينة الصناعية إلى المنطقة الإدارية عبر خريطة أسماء صريحة؛ الفترات تختلف بين 2023 و2024 ولا تُجمع المؤشرات في درجة واحدة.",
            "المساحة ووحدات المصانع الجاهزة مؤشرات للبصمة الصناعية وليست قياسًا مباشرًا لجودة البنية التحتية أو طاقتها التشغيلية.",
            "المدن الصناعية ليست مستودعات، ووجودها لا يثبت توفر أرض لوجستية أو سعة تشغيلية جاهزة.",
            *result.get("limitations", []),
        ],
        limitations_en=[
            "MODON files published by industrial city were aggregated to administrative regions using an explicit name map; periods differ across 2023 and 2024 and are not combined into one score.",
            "Area and ready-factory units are industrial-footprint proxies, not direct measures of infrastructure quality or operating capacity.",
            "Industrial cities are not warehouses, and their presence does not prove available logistics land or operating capacity.",
            *result.get("limitations_en", []),
        ],
    )
    return result


def describe_available_data(
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Describe the evidence actually loaded by Nitaq using live repository counts."""
    repo = _repo(repository)
    modon_source_count = len(load_modon_regional_context(repo.root).get("sources", []))
    portwatch_available = int(repo.ports["portwatch_available"].astype(bool).sum())
    portwatch_start = repo.portwatch["date"].min().date().isoformat() if not repo.portwatch.empty else None
    portwatch_end = repo.portwatch["date"].max().date().isoformat() if not repo.portwatch.empty else None
    snapshot_date = (
        str(repo.logistics_centers["snapshot_date"].iloc[0])
        if not repo.logistics_centers.empty
        else None
    )
    table = [
        {
            "category_id": "regional_indicators",
            "category_ar": "مؤشرات المناطق",
            "category_en": "Regional indicators",
            "coverage_ar": f"{len(repo.raw_metrics)} مؤشرًا خامًا لـ13 منطقة، تشمل السكان والتوصيل والمستودعات والتراخيص والمراكز",
            "coverage_en": f"{len(repo.raw_metrics)} raw indicators across 13 regions, including population, delivery, warehouses, licenses, and centers",
            "period": "2023-2024",
        },
        {
            "category_id": "logistics_centers",
            "category_ar": "المراكز اللوجستية المدرجة",
            "category_en": "Listed logistics centers",
            "coverage_ar": f"{len(repo.logistics_centers)} مركزًا مع المنطقة والمالك والنوع والحالة والمساحة والإحداثيات عند توفرها",
            "coverage_en": f"{len(repo.logistics_centers)} centers with region, owner, type, status, area, and coordinates when available",
            "period": f"لقطة {snapshot_date}",
        },
        {
            "category_id": "ports",
            "category_ar": "الموانئ والسياق البحري",
            "category_en": "Ports and maritime context",
            "coverage_ar": f"{len(repo.ports)} ميناءً في دليل الربط، منها {portwatch_available} موانئ لها سلاسل PortWatch شهرية",
            "coverage_en": f"{len(repo.ports)} mapped ports, including {portwatch_available} with monthly PortWatch series",
            "period": f"{portwatch_start} إلى {portwatch_end}",
        },
        {
            "category_id": "modon",
            "category_ar": "MODON والمدن الصناعية",
            "category_en": "MODON and industrial cities",
            "coverage_ar": f"{modon_source_count} مصادر مجمعة عن المدن الصناعية والمساحات والمصانع الجاهزة",
            "coverage_en": f"{modon_source_count} aggregated sources on industrial cities, areas, and ready factories",
            "period": "2023-2024؛ يختلف حسب الملف",
        },
        {
            "category_id": "documents",
            "category_ar": "الوثائق والاشتراطات",
            "category_en": "Documents and requirements",
            "coverage_ar": "اشتراطات المستودعات والمنهجيات وتعريفات المؤشرات وسياق السياسات",
            "coverage_en": "Warehouse requirements, methodologies, metric definitions, and policy context",
            "period": "يختلف حسب الوثيقة",
        },
    ]
    return {
        "ok": True,
        "tool": "describe_available_data",
        "table": table,
        "summary": {
            "regional_metrics": len(repo.raw_metrics),
            "regions": len(repo.master),
            "listed_logistics_centers": len(repo.logistics_centers),
            "mapped_ports": len(repo.ports),
            "ports_with_portwatch": portwatch_available,
            "modon_files": modon_source_count,
        },
        "columns": [
            {"column": "category_ar", "label_ar": "فئة البيانات", "label_en": "Data category", "value_kind": "dimension"},
            {"column": "category_en", "label_ar": "فئة البيانات بالإنجليزية", "label_en": "Data category", "value_kind": "dimension"},
            {"column": "coverage_ar", "label_ar": "ما الذي يتوفر؟", "label_en": "Available coverage (Arabic)", "value_kind": "description"},
            {"column": "coverage_en", "label_ar": "التغطية بالإنجليزية", "label_en": "Available coverage", "value_kind": "description"},
            {"column": "period", "label_ar": "الفترة", "label_en": "Period", "value_kind": "dimension"},
        ],
        "sources": [
            {"source_id": "regional_master", "source_path": "data/processed/mizan_region_master_2024.csv", "period": "2023-2024"},
            {"source_id": "logisti_centers_snapshot_2026", "source_path": "data/processed/runtime/logistics_centers_snapshot_2026-07-28.csv", "period": f"snapshot {snapshot_date}"},
            {"source_id": "port_mapping", "source_path": "data/processed/port_region_mapping.csv"},
            {"source_id": "portwatch", "source_path": "data/processed/runtime/portwatch_monthly_activity_2019_2026.csv", "period": f"{portwatch_start} to {portwatch_end}"},
            {"source_id": "modon_industrial_context", "source_path": "data/processed/runtime/modon_regional_context_2023_2024.csv", "period": "2023-2024; varies by source"},
        ],
        "limitations": [
            "ليست كل الفئات موحدة على مستوى المناطق الثلاث عشرة؛ يوضح كل تحليل نطاقه وسنته ومصدره.",
            "لا تتوفر حاليًا بيانات موحدة عن الإيجارات والإشغال والسعة التشغيلية والربحية على مستوى المدن.",
        ],
        "limitations_en": [
            "Not every category is uniform across all 13 regions; each analysis discloses its scope, period, and source.",
            "Comparable city-level rent, occupancy, operating-capacity, and profitability data is not currently available.",
        ],
        "missing_data_notes": [],
        "missing_data_notes_en": [],
    }


def get_port_context(
    *,
    port: str | None = None,
    region: str | None = None,
    start: str | None = None,
    end: str | None = None,
    metric: str = "calls",
    direction: str | None = None,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Return partial port context; inland or uncovered ports remain not_applicable/null."""
    repo = _repo(repository)
    if metric not in {"calls", "trade_volume"}:
        raise MizanInputError("metric must be 'calls' or 'trade_volume'")
    ports = _resolve_ports(repo, port, region)
    available = ports.loc[ports["portwatch_available"].astype(bool)].copy()
    locations = _unique_text(available.get("portwatch_location", pd.Series(dtype=str)))

    series = repo.portwatch.loc[
        repo.portwatch["location"].isin(locations) & repo.portwatch["metric"].eq(metric)
    ].copy()
    if direction:
        series = series.loc[series["direction"].eq(direction)]
    if start:
        series = series.loc[series["date"] >= pd.Timestamp(start)]
    if end:
        series = series.loc[series["date"] <= pd.Timestamp(end)]
    series = series.sort_values(["location", "direction", "date"])
    table_columns = ["date", "location", "metric", "direction", "total_activity"]
    table = _records(series[table_columns]) if not series.empty else []

    unavailable = ports.loc[~ports["portwatch_available"].astype(bool), ["port_code", "port_name_en", "region_en"]]
    notes: list[str] = []
    if ports.empty:
        notes.append("لا يوجد ميناء بحري مربوط بهذه المنطقة؛ الحالة not_applicable وليست صفرًا.")
    if not unavailable.empty:
        names = ", ".join(unavailable["port_name_en"].tolist())
        notes.append(f"توجد موانئ رسمية بلا سلسلة PortWatch منسقة حاليًا: {names}; لم تُحوّل إلى أصفار.")
    if available.empty:
        notes.append("لا توجد سلسلة PortWatch للموانئ المختارة؛ الجدول فارغ والقيمة غير متاحة.")
    elif series.empty:
        notes.append("لا توجد مشاهدات تطابق المقياس/الاتجاه/الفترة المختارة؛ لم تُستخدم أصفار بديلة.")
    else:
        notes.append("لا توجد قيم مفقودة في السلسلة المسترجعة؛ لم تُستخدم أي إحلالات.")

    selected_ports = [
        clean_record(record)
        for record in ports[
            [
                "port_code",
                "port_name_en",
                "port_name_ar",
                "city_en",
                "region_en",
                "region_ar",
                "official_port_files_available",
                "portwatch_available",
                "portwatch_location",
            ]
        ].to_dict(orient="records")
    ] if not ports.empty else []

    return {
        "ok": True,
        "tool": "get_port_context",
        "selection": {"port": port, "region": region, "start": start, "end": end, "metric": metric, "direction": direction},
        "coverage_summary": {
            "mapped_ports": int(len(repo.ports)),
            "ports_with_portwatch": int(repo.ports["portwatch_available"].astype(bool).sum()),
            "selected_ports": int(len(selected_ports)),
            "series_start": series["date"].min().date().isoformat() if not series.empty else None,
            "series_end": series["date"].max().date().isoformat() if not series.empty else None,
        },
        "ports": selected_ports,
        "raw_values": table,
        "normalized_values": [],
        "table": table,
        "columns": [
            {"column": "date", "label_ar": "الشهر", "label_en": "Month", "unit": None, "value_kind": "dimension"},
            {"column": "location", "label_ar": "الميناء/الموقع", "label_en": "Port / location", "unit": None, "value_kind": "dimension"},
            {"column": "direction", "label_ar": "الاتجاه", "label_en": "Direction", "unit": None, "value_kind": "dimension"},
            {"column": "total_activity", "label_ar": "النشاط المرصود", "label_en": "Observed activity", "unit": "PortWatch experimental activity unit", "value_kind": "raw"},
        ],
        "sources": [
            {
                "dataset": "IMF PortWatch monthly long",
                "source_file": str(repo.paths["portwatch"].relative_to(repo.root)).replace("\\", "/"),
                "source_url": "https://portwatch.imf.org/",
                "coverage": "January 2019 to May 2026 for selected PortWatch locations",
            },
            {
                "dataset": "Saudi ports public-data mapping",
                "source_file": str(repo.paths["ports"].relative_to(repo.root)).replace("\\", "/"),
                "source_url": "https://www.mawani.gov.sa/",
            },
        ],
        "limitations": [
            PRODUCT_LIMITATION,
            "PortWatch مؤشر تجريبي مبني على حركة السفن، وليس إحصاءً سعوديًا رسميًا ولا يقيس السعة أو الإشغال أو زمن التخليص.",
            "التغطية جزئية على مستوى الموانئ ولا تصلح لترتيب المناطق الـ13 أو إسناد صفر للمناطق الداخلية.",
        ],
        "missing_data_notes": notes,
    }


def get_metric_source(
    metric_id: str,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Return definition, provenance, formula, and caveat for one metric."""
    repo = _repo(repository)
    metadata = clean_record(repo.metric_metadata(metric_id))
    sources = repo.source_records([metric_id])
    return {
        "ok": True,
        "tool": "get_metric_source",
        "metric_id": metric_id,
        "metadata": metadata,
        "raw_values": [],
        "normalized_values": [],
        "table": [metadata],
        "sources": sources,
        "limitations": _limitations(repo, [metric_id]),
        "missing_data_notes": ["هذه أداة تعريف ومصدر؛ لا تسترجع قيمًا إقليمية."],
    }


def identify_missing_data(
    requested_concepts: list[str] | None = None,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    """Identify whether a decision concept is available, partial, or absent."""
    repo = _repo(repository)
    concepts = list(MISSING_DATA_CATALOG)
    unmatched: list[str] = []
    if requested_concepts:
        concepts = []
        for requested in requested_concepts:
            needle = str(requested).strip().lower()
            match = None
            for concept_id, item in MISSING_DATA_CATALOG.items():
                aliases = [concept_id, item["label_ar"], *item.get("aliases", [])]
                if any(needle == str(alias).strip().lower() for alias in aliases):
                    match = concept_id
                    break
            if match and match not in concepts:
                concepts.append(match)
            elif not match:
                unmatched.append(str(requested))

    table = []
    for concept_id in concepts:
        item = MISSING_DATA_CATALOG[concept_id]
        table.append(
            {
                "concept_id": concept_id,
                "label_ar": item["label_ar"],
                "label_en": item.get("label_en"),
                "status": item["status"],
                "metric_ids": item["metric_ids"],
                "note_ar": item["note_ar"],
                "note_en": item.get("note_en"),
            }
        )
    for requested in unmatched:
        table.append(
            {
                "concept_id": None,
                "label_ar": requested,
                "label_en": requested,
                "status": "unknown_not_mapped",
                "metric_ids": [],
                "note_ar": "المفهوم غير مربوط بعد بكتالوج احتياجات القرار؛ يلزم تعريفه قبل اعتباره متاحًا أو مفقودًا.",
                "note_en": "The concept is not yet mapped to the decision-needs catalog and must be defined before its coverage can be assessed.",
            }
        )

    alternative_metric_ids = [
        "delivery_total_2024_source",
        "warehouse_count_2024",
        "warehouse_area_sqm_2024",
        "activated_logistics_centers_2024",
    ]

    return {
        "ok": True,
        "tool": "identify_missing_data",
        "requested_concepts": requested_concepts,
        "raw_values": [],
        "normalized_values": [],
        "table": table,
        "alternative_evidence": [
            {
                "label_ar": "نشاط طلبات التوصيل المنفذة حسب المنطقة",
                "label_en": "Completed delivery-request activity by region",
                "metric_ids": ["delivery_total_2024_source"],
            },
            {
                "label_ar": "عدد ومساحة المستودعات المرخصة كبصمة للسوق، لا كإشغال أو سعة",
                "label_en": "Licensed warehouse count and area as market-footprint signals, not occupancy or capacity",
                "metric_ids": ["warehouse_count_2024", "warehouse_area_sqm_2024"],
            },
            {
                "label_ar": "المراكز اللوجستية المفعلة والسياق الصناعي المتاح",
                "label_en": "Activated logistics centers and the available industrial context",
                "metric_ids": ["activated_logistics_centers_2024"],
            },
        ],
        "columns": [
            {"column": "concept_id", "label_ar": "مفهوم القرار", "label_en": "Decision concept", "unit": None, "value_kind": "dimension"},
            {"column": "status", "label_ar": "حالة التغطية", "label_en": "Coverage status", "unit": None, "value_kind": "classification"},
            {"column": "metric_ids", "label_ar": "المؤشرات المتاحة", "label_en": "Available metrics", "unit": None, "value_kind": "reference"},
        ],
        "sources": repo.source_records(
            list(dict.fromkeys([
                *(metric for row in table for metric in row.get("metric_ids", [])),
                *alternative_metric_ids,
            ]))
        ),
        "limitations": [PRODUCT_LIMITATION, "عدم وجود المؤشر في نطاق لا يثبت عدم وجوده خارج المصادر المجمعة."],
        "missing_data_notes": [
            f"{sum(row['status'] == 'missing' for row in table)} مفاهيم مفقودة، "
            f"{sum(row['status'] == 'partial_context' for row in table)} جزئية، "
            f"{sum(row['status'] == 'available_with_caveat' for row in table)} متاحة بقيود."
        ],
    }
