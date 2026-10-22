from __future__ import annotations

from typing import Any

from .exceptions import MizanInputError
from .repository import MizanRepository
from .analytics import (
    compare_ports,
    compare_regions,
    evaluate_warehouse_locations,
    get_indicator_trend,
    get_port_context,
    get_region_profile,
    screen_regions,
)


ALLOWED_CHART_TYPES = {"bar", "line"}
def _column_metadata(tool_result: dict[str, Any], column: str) -> dict[str, Any]:
    return next((item for item in tool_result.get("columns", []) if item.get("column") == column), {})


def _chart(
    *,
    chart_id: str,
    chart_type: str,
    data: list[dict[str, Any]],
    x: str,
    y: str,
    title_ar: str,
    title_en: str,
    unit: str | None,
    color: str | None = None,
    orientation: str = "vertical",
    source_metric_ids: list[str] | None = None,
) -> dict[str, Any]:
    spec = {
        "chart_id": chart_id,
        "chart_type": chart_type,
        "data": data,
        "x": x,
        "y": y,
        "color": color,
        "orientation": orientation,
        "title_ar": title_ar,
        "title_en": title_en,
        "unit": unit,
        "source_metric_ids": source_metric_ids or [],
    }
    validate_chart_spec(spec)
    return spec


def validate_chart_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Reject unsupported charts or chart columns absent from their data."""
    required = {"chart_id", "chart_type", "data", "x", "y", "title_ar", "title_en", "unit"}
    missing = sorted(required - set(spec))
    if missing:
        raise MizanInputError(f"Chart spec is missing: {missing}")
    if spec["chart_type"] not in ALLOWED_CHART_TYPES:
        raise MizanInputError(f"Unsupported chart type: {spec['chart_type']}")
    if spec.get("orientation") not in {"vertical", "horizontal"}:
        raise MizanInputError("orientation must be vertical or horizontal")
    data = spec["data"]
    if not isinstance(data, list):
        raise MizanInputError("Chart data must be a list of records")
    if data:
        columns = set(data[0])
        needed = {spec["x"], spec["y"]}
        if spec.get("color"):
            needed.add(spec["color"])
        absent = sorted(needed - columns)
        if absent:
            raise MizanInputError(f"Chart columns absent from data: {absent}")
        if any(not needed.issubset(record) for record in data):
            raise MizanInputError("Not every chart row contains the declared columns")
    return {"valid": True, "rows": len(data), "chart_type": spec["chart_type"]}


def build_comparison_view(
    regions: list[str],
    metric_ids: list[str] | None = None,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    result = compare_regions(regions, metric_ids, repository=repository)
    charts: list[dict[str, Any]] = []
    for metric_id in result["metric_ids"]:
        metadata = _column_metadata(result, metric_id)
        data = [
            {
                "region_en": row["region_en"],
                "region_ar": row["region_ar"],
                "value": row[metric_id],
            }
            for row in result["table"]
        ]
        orientation = "horizontal" if len(regions) > 5 else "vertical"
        charts.append(
            _chart(
                chart_id=f"comparison__{metric_id}",
                chart_type="bar",
                data=data,
                x="value" if orientation == "horizontal" else "region_en",
                y="region_en" if orientation == "horizontal" else "value",
                title_ar=f"مقارنة المناطق — {metadata.get('label_ar') or metric_id}",
                title_en=f"Regional comparison — {metadata.get('label_en') or metric_id}",
                unit=metadata.get("unit"),
                orientation=orientation,
                source_metric_ids=[metric_id],
            )
        )
    return {
        "view_type": "comparison",
        "template_version": "phase2.v1",
        "title_ar": "مقارنة إقليمية موثقة",
        "title_en": "Documented regional comparison",
        "tool_result": result,
        "table": result["table"],
        "charts": charts,
        "sources": result["sources"],
        "limitations": result["limitations"],
        "missing_data_notes": result["missing_data_notes"],
    }


def build_region_profile_view(
    region: str,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    result = get_region_profile(region, repository=repository)
    region_name = result["region"]["region_en"]
    chart = _chart(
        chart_id="profile__quarterly_delivery",
        chart_type="line",
        data=[{"period": row["period"], "value": row["value"]} for row in result["quarterly_delivery"]],
        x="period",
        y="value",
        title_ar=f"طلبات التوصيل ربع السنوية — {result['region']['region_ar']}",
        title_en=f"Quarterly delivery requests — {region_name}",
        unit="request",
        source_metric_ids=[row["metric_id"] for row in result["quarterly_delivery"]],
    )
    return {
        "view_type": "region_profile",
        "template_version": "phase2.v1",
        "title_ar": f"ملف المنطقة — {result['region']['region_ar']}",
        "title_en": f"Regional profile — {region_name}",
        "tool_result": result,
        "table": result["table"],
        "raw_metric_cards": result["raw_values"],
        "normalized_metric_cards": result["normalized_values"],
        "port_context_summary": result["port_context_summary"],
        "charts": [chart],
        "sources": result["sources"],
        "limitations": result["limitations"],
        "missing_data_notes": result["missing_data_notes"],
    }


def build_trend_view(
    regions: list[str],
    indicator: str,
    *,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    result = get_indicator_trend(regions, indicator, repository=repository)
    data = [
        {
            "period": row["period"],
            "region_en": row["region_en"],
            "region_ar": row["region_ar"],
            "value": row["value"],
        }
        for row in result["table"]
    ]
    chart = _chart(
        chart_id=f"trend__{result['indicator']}",
        chart_type="line",
        data=data,
        x="period",
        y="value",
        color="region_en",
        title_ar=f"اتجاه المؤشر — {result['indicator']}",
        title_en=f"Indicator trend — {result['indicator'].replace('_', ' ')}",
        unit=result["columns"][-1].get("unit"),
        source_metric_ids=sorted({row["metric_id"] for row in result["table"]}),
    )
    return {
        "view_type": "trend",
        "template_version": "phase2.v1",
        "title_ar": "اتجاه زمني موثق",
        "title_en": "Documented time trend",
        "tool_result": result,
        "table": result["table"],
        "charts": [chart],
        "sources": result["sources"],
        "limitations": result["limitations"],
        "missing_data_notes": result["missing_data_notes"],
    }


def build_port_view(
    *,
    port: str | None = None,
    region: str | None = None,
    start: str | None = None,
    end: str | None = None,
    metric: str = "calls",
    direction: str | None = None,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    result = get_port_context(
        port=port,
        region=region,
        start=start,
        end=end,
        metric=metric,
        direction=direction,
        repository=repository,
    )
    data = [
        {
            "date": row["date"],
            "series": f"{row['location']} — {row['direction']}",
            "total_activity": row["total_activity"],
        }
        for row in result["table"]
    ]
    charts = []
    if data:
        charts.append(
            _chart(
                chart_id=f"port__{metric}",
                chart_type="line",
                data=data,
                x="date",
                y="total_activity",
                color="series",
                title_ar=f"سياق نشاط الموانئ — {metric}",
                title_en=f"Port activity context — {metric.replace('_', ' ')}",
                unit="PortWatch experimental activity unit",
                source_metric_ids=[],
            )
        )
    return {
        "view_type": "port_context",
        "template_version": "phase2.v1",
        "title_ar": "سياق البوابات البحرية",
        "title_en": "Maritime gateway context",
        "tool_result": result,
        "table": result["table"],
        "charts": charts,
        "sources": result["sources"],
        "limitations": result["limitations"],
        "missing_data_notes": result["missing_data_notes"],
    }


def build_port_comparison_view(
    ports: list[str],
    *,
    start: str | None = None,
    end: str | None = None,
    metric: str = "calls",
    direction: str | None = None,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    result = compare_ports(
        ports,
        start=start,
        end=end,
        metric=metric,
        direction=direction,
        repository=repository,
    )
    data = [
        {
            "date": row["date"],
            "series": f"{row['location']} — {row['direction']}",
            "total_activity": row["total_activity"],
        }
        for row in result["table"]
    ]
    chart = _chart(
        chart_id=f"port_comparison__{metric}",
        chart_type="line",
        data=data,
        x="date",
        y="total_activity",
        color="series",
        title_ar=f"مقارنة سياق نشاط الموانئ — {metric}",
        title_en=f"Port activity context comparison — {metric.replace('_', ' ')}",
        unit="PortWatch experimental activity unit",
        source_metric_ids=[],
    )
    return {
        "view_type": "port_comparison",
        "template_version": "phase2.v2",
        "title_ar": "مقارنة سياق البوابات البحرية",
        "title_en": "Maritime gateway context comparison",
        "tool_result": result,
        "table": result["table"],
        "summary": result["summary"],
        "charts": [chart],
        "sources": result["sources"],
        "limitations": result["limitations"],
        "missing_data_notes": result["missing_data_notes"],
    }


def build_screening_view(
    criteria: list[dict[str, Any]],
    *,
    top_n: int = 5,
    sensitivity_delta: float = 0.10,
    repository: MizanRepository | None = None,
) -> dict[str, Any]:
    result = screen_regions(
        criteria,
        top_n=top_n,
        sensitivity_delta=sensitivity_delta,
        repository=repository,
    )
    chart = _chart(
        chart_id="screening__conditional_index",
        chart_type="bar",
        data=[
            {
                "region_en": row["region_en"],
                "screening_index_0_100": row["screening_index_0_100"],
            }
            for row in result["table"]
        ],
        x="screening_index_0_100",
        y="region_en",
        title_ar="فرز أولي مشروط بالمعايير والأوزان الحالية",
        title_en="Screening conditional on user criteria and weights",
        unit="0-100 relative index",
        orientation="horizontal",
        source_metric_ids=[item["metric_id"] for item in result["criteria"]],
    )
    return {
        "view_type": "screening",
        "template_version": "phase2.v1",
        "title_ar": "فرز أولي محدود ومشروط",
        "title_en": "Limited conditional screening",
        "tool_result": result,
        "table": result["table"],
        "sensitivity": result["sensitivity"],
        "charts": [chart],
        "sources": result["sources"],
        "limitations": result["limitations"],
        "missing_data_notes": result["missing_data_notes"],
    }


def build_warehouse_decision_view(
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
    result = evaluate_warehouse_locations(
        locations,
        regional_criteria=regional_criteria,
        ports=ports,
        include_port=include_port,
        port_metric=port_metric,
        port_direction=port_direction,
        port_weight=port_weight,
        top_n=top_n,
        repository=repository,
    )
    chart = _chart(
        chart_id="warehouse_decision__index",
        chart_type="bar",
        data=[
            {
                "candidate_en": row["candidate_en"],
                "candidate_ar": row["candidate_ar"],
                "decision_index_0_100": row["decision_index_0_100"],
            }
            for row in result["table"]
        ],
        x="decision_index_0_100",
        y="candidate_en",
        title_ar="ترشيح مواقع المستودعات وفق المعايير الحالية",
        title_en="Warehouse-location ranking under the current criteria",
        unit="0-100 relative index",
        orientation="horizontal",
        source_metric_ids=[
            item["metric_id"] for item in result["criteria"] if item.get("criterion_type") == "regional"
        ],
    )
    return {
        "view_type": "warehouse_decision",
        "template_version": "phase4.v1",
        "title_ar": "قرار استكشافي متعدد المؤشرات",
        "title_en": "Exploratory multi-signal decision",
        "tool_result": result,
        "table": result["table"],
        "charts": [chart],
        "sources": result["sources"],
        "limitations": result["limitations"],
        "missing_data_notes": result["missing_data_notes"],
    }
