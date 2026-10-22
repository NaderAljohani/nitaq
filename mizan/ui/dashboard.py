from __future__ import annotations

import math
import re
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from ..tools import (
    build_comparison_view,
    build_warehouse_decision_view,
    build_port_comparison_view,
    build_port_view,
    build_region_profile_view,
    build_screening_view,
    build_trend_view,
    compare_logistics_gateways,
    describe_available_data,
    get_metric_source,
    get_modon_context,
    identify_missing_data,
    list_logistics_centers,
    validate_comparison,
)


TOOL_LABELS = {
    "get_region_profile": "ملف منطقة",
    "compare_regions": "مقارنة مناطق",
    "screen_regions": "فرز أولي مشروط",
    "evaluate_warehouse_locations": "قرار موقع مستودع",
    "get_indicator_trend": "اتجاه مؤشر",
    "get_port_context": "سياق بحري",
    "compare_ports": "مقارنة موانئ",
    "compare_logistics_gateways": "ربط الموانئ بالمراكز",
    "get_metric_source": "مصدر مؤشر",
    "validate_comparison": "تحقق من المقارنة",
    "identify_missing_data": "فجوات البيانات",
    "search_knowledge": "بحث في الوثائق",
    "list_logistics_centers": "قائمة المراكز اللوجستية",
    "get_modon_context": "سياق MODON",
    "describe_available_data": "البيانات المتوفرة",
    "get_runtime_info": "معلومات التشغيل",
}

TOOL_PRESENTATION = {
    "screen_regions": ("ترشيح أولي", "workspace_premium", "orange"),
    "evaluate_warehouse_locations": ("قرار متعدد المؤشرات", "warehouse", "orange"),
    "compare_regions": ("مقارنة موثقة", "compare_arrows", "green"),
    "get_indicator_trend": ("اتجاه زمني", "query_stats", "blue"),
    "get_region_profile": ("ملف منطقة", "location_on", "green"),
    "get_port_context": ("سياق بحري", "directions_boat", "blue"),
    "compare_ports": ("مقارنة موانئ", "directions_boat", "blue"),
    "compare_logistics_gateways": ("بوابات ومراكز لوجستية", "hub", "blue"),
    "search_knowledge": ("من الوثائق", "description", "violet"),
    "get_metric_source": ("تعريف موثق", "fact_check", "green"),
    "validate_comparison": ("تحقق منهجي", "verified", "green"),
    "identify_missing_data": ("فجوات البيانات", "data_alert", "orange"),
    "list_logistics_centers": ("قائمة المراكز", "location_city", "green"),
    "get_modon_context": ("بيانات MODON", "factory", "blue"),
    "describe_available_data": ("تغطية البيانات", "database", "blue"),
    "get_runtime_info": ("معلومات التشغيل", "info", "blue"),
}

TOOL_PRESENTATION_EN = {
    "screen_regions": ("Initial screening", "workspace_premium", "orange"),
    "evaluate_warehouse_locations": ("Multi-signal decision", "warehouse", "orange"),
    "compare_regions": ("Evidence comparison", "compare_arrows", "green"),
    "get_indicator_trend": ("Documented trend", "query_stats", "blue"),
    "get_region_profile": ("Regional profile", "location_on", "green"),
    "get_port_context": ("Maritime context", "directions_boat", "blue"),
    "compare_ports": ("Port comparison", "directions_boat", "blue"),
    "compare_logistics_gateways": ("Ports and logistics centers", "hub", "blue"),
    "search_knowledge": ("From documents", "description", "violet"),
    "get_metric_source": ("Documented definition", "fact_check", "green"),
    "validate_comparison": ("Method check", "verified", "green"),
    "identify_missing_data": ("Evidence gaps", "data_alert", "orange"),
    "list_logistics_centers": ("Logistics centers", "location_city", "green"),
    "get_modon_context": ("MODON context", "factory", "blue"),
    "describe_available_data": ("Available data", "database", "blue"),
    "get_runtime_info": ("Runtime information", "info", "blue"),
}

GENERIC_COLUMN_LABELS = {
    "region_ar": "المنطقة",
    "period": "الفترة",
    "date": "التاريخ",
    "location": "الميناء أو الموقع",
    "metric": "المؤشر",
    "direction": "الاتجاه",
    "total_activity": "النشاط المرصود",
    "screening_index_0_100": "مؤشر الفرز الأولي من 100",
    "screening_position": "الموضع تحت المعايير المختارة",
    "value": "القيمة",
    "rank": "الموضع النسبي",
    "status": "حالة التغطية",
    "label_ar": "المفهوم",
    "note_ar": "الملاحظة",
    "metric_ids": "المؤشرات المتاحة",
    "total_centers": "إجمالي المراكز المدرجة",
    "active_centers": "المراكز المفعلة",
    "inactive_centers": "المراكز غير المفعلة",
    "center_name_ar": "اسم المركز",
    "owner_ar": "الجهة المالكة",
    "center_type_ar": "نوع المركز",
    "status_ar": "الحالة",
    "area_sqm_reconciled": "المساحة بالمتر المربع",
}

GENERIC_COLUMN_LABELS_EN = {
    "region_ar": "Region (Arabic)",
    "period": "Period",
    "date": "Date",
    "location": "Port or location",
    "metric": "Indicator",
    "direction": "Direction",
    "total_activity": "Observed activity",
    "screening_index_0_100": "Screening index (0–100)",
    "screening_position": "Position",
    "decision_index_0_100": "Decision index (0–100)",
    "decision_position": "Recommendation position",
    "candidate_en": "Candidate",
    "value": "Value",
    "rank": "Relative position",
    "status": "Coverage status",
    "label_ar": "Concept",
    "note_ar": "Note",
    "metric_ids": "Available indicators",
    "total_centers": "Listed centers",
    "active_centers": "Active centers",
    "inactive_centers": "Inactive centers",
    "center_name_ar": "Center name",
    "owner_ar": "Owner",
    "center_type_ar": "Center type",
    "status_ar": "Status",
    "area_sqm_reconciled": "Area (m²)",
}

UNIT_LABELS_AR = {
    "person": "نسمة",
    "executed request": "طلب منفذ",
    "request": "طلب",
    "licensed warehouse": "مستودع مرخص",
    "warehouse": "مستودع مرخص",
    "square meter": "متر مربع",
    "square meter per person": "متر مربع للفرد",
    "request per 1,000 persons": "طلب لكل ألف نسمة",
    "warehouse per 100,000 persons": "مستودع لكل 100 ألف نسمة",
    "active license": "ترخيص نشط",
    "license per 100,000 persons": "ترخيص لكل 100 ألف نسمة",
    "activated center": "مركز مفعّل",
    "center per 1,000,000 persons": "مركز لكل مليون نسمة",
    "decimal rate": "نسبة عشرية",
    "0-100": "نقطة من 100",
    "0-100 relative index": "نقطة من 100",
    "PortWatch experimental activity unit": "وحدة نشاط بحرية تجريبية",
}

UNIT_LABELS_EN = {
    "person": "people",
    "executed request": "completed requests",
    "request": "requests",
    "licensed warehouse": "licensed warehouses",
    "warehouse": "licensed warehouses",
    "square meter": "m²",
    "square meter per person": "m² per person",
    "request per 1,000 persons": "requests per 1,000 people",
    "warehouse per 100,000 persons": "warehouses per 100,000 people",
    "active license": "active licenses",
    "license per 100,000 persons": "licenses per 100,000 people",
    "activated center": "activated centers",
    "center per 1,000,000 persons": "centers per million people",
    "decimal rate": "decimal rate",
    "0-100": "points out of 100",
    "0-100 relative index": "points out of 100",
    "PortWatch experimental activity unit": "experimental PortWatch activity units",
}

VALUE_LABELS_EN = {
    "calls": "Vessel calls",
    "trade_volume": "Trade volume",
    "port": "Port",
    "incoming": "Inbound",
    "outgoing": "Outbound",
    "imports": "Imports",
    "exports": "Exports",
    "higher": "Higher",
    "lower": "Lower",
    "available": "Available",
    "available_with_caveat": "Available with caveats",
    "partial_context_only": "Partial context only",
    "missing": "Unavailable",
    "unknown_not_mapped": "Not mapped",
}

VALUE_LABELS_AR = {
    "calls": "زيارات السفن",
    "port": "إجمالي حركة الميناء",
    "imports": "الواردات",
    "exports": "الصادرات",
    "higher": "الأعلى",
    "lower": "الأدنى",
    "available": "متاح",
    "available_with_caveat": "متاح بقيود",
    "partial_context_only": "سياق جزئي فقط",
    "missing": "غير متاح",
    "unknown_not_mapped": "غير مصنف بعد",
    "jeddah": "ميناء جدة الإسلامي",
    "dammam": "ميناء الملك عبدالعزيز بالدمام",
    "yanbu": "ميناء ينبع التجاري",
    "Riyadh": "الرياض",
    "Makkah": "مكة المكرمة",
    "Eastern Region": "المنطقة الشرقية",
    "Madinah": "المدينة المنورة",
    "Qassim": "القصيم",
    "Asir": "عسير",
    "Tabuk": "تبوك",
    "Hail": "حائل",
    "Northern Borders": "الحدود الشمالية",
    "Jazan": "جازان",
    "Najran": "نجران",
    "Al Bahah": "الباحة",
    "Al Jawf": "الجوف",
    "delivery_requests": "طلبات التوصيل",
    "warehouse_count": "عدد المستودعات المرخصة",
    "warehouse_area": "مساحة المستودعات المرخصة",
    "freight_post_licenses": "تراخيص نقل الطرود",
    "activated_logistics_centers": "المراكز اللوجستية المفعّلة",
    "population": "السكان",
}

AGENCY_LABELS_AR = {
    "Transport General Authority": "الهيئة العامة للنقل",
    "Ministry of Municipalities and Housing": "وزارة البلديات والإسكان",
    "KAPSARC Data Portal": "بوابة بيانات كابسارك",
    "General Authority for Statistics": "الهيئة العامة للإحصاء",
    "Logisti / MOTLS": "منصة لوجستي / وزارة النقل والخدمات اللوجستية",
}

INTERNAL_COLUMNS = {
    "concept_id",
    "metric_id",
    "source_id",
    "port_code",
}


def _view_for_tool(tool: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    if tool == "get_region_profile":
        return build_region_profile_view(arguments["region"])
    if tool == "compare_regions":
        return build_comparison_view(arguments["regions"], arguments.get("metric_ids"))
    if tool == "screen_regions":
        return build_screening_view(
            arguments["criteria"],
            top_n=arguments.get("top_n", 5),
            sensitivity_delta=arguments.get("sensitivity_delta", 0.1),
        )
    if tool == "evaluate_warehouse_locations":
        return build_warehouse_decision_view(**arguments)
    if tool == "get_indicator_trend":
        return build_trend_view(arguments["regions"], arguments["indicator"])
    if tool == "get_port_context":
        return build_port_view(**arguments)
    if tool == "compare_ports":
        return build_port_comparison_view(**arguments)
    return None


def build_dashboard_payload(response: dict[str, Any]) -> dict[str, Any]:
    """Build the optional deterministic evidence package from the successful trace."""
    for trace in reversed(response.get("tool_trace", [])):
        if trace.get("status") != "success":
            continue
        tool = trace.get("tool", "")
        arguments = trace.get("arguments", {})
        view = _view_for_tool(tool, arguments)
        if view is not None:
            return {"kind": "view", "tool": tool, "view": view}
        if tool == "get_metric_source":
            return {"kind": "evidence", "tool": tool, "result": get_metric_source(**arguments)}
        if tool == "validate_comparison":
            return {"kind": "evidence", "tool": tool, "result": validate_comparison(**arguments)}
        if tool == "identify_missing_data":
            return {"kind": "evidence", "tool": tool, "result": identify_missing_data(**arguments)}
        if tool == "list_logistics_centers":
            return {"kind": "evidence", "tool": tool, "result": list_logistics_centers(**arguments)}
        if tool == "get_modon_context":
            return {"kind": "evidence", "tool": tool, "result": get_modon_context(**arguments)}
        if tool == "compare_logistics_gateways":
            return {"kind": "evidence", "tool": tool, "result": compare_logistics_gateways(**arguments)}
        if tool == "describe_available_data":
            return {"kind": "evidence", "tool": tool, "result": describe_available_data(**arguments)}
        if tool == "search_knowledge":
            return {"kind": "knowledge", "tool": tool}
    return {"kind": "empty", "tool": None}


def _last_successful_tool(response: dict[str, Any]) -> str | None:
    return next(
        (
            trace.get("tool")
            for trace in reversed(response.get("tool_trace", []))
            if trace.get("status") == "success"
        ),
        None,
    )


def _format_number(value: Any, language: str = "ar") -> str:
    if value is None:
        return "Not available" if language == "en" else "غير متاح"
    if isinstance(value, bool):
        if language == "en":
            return "Yes" if value else "No"
        return "نعم" if value else "لا"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.0f}" if value.is_integer() else f"{value:,.2f}"
    return str(_localize_value(value, language))


def _highlight_items(payload: dict[str, Any], language: str = "ar") -> list[tuple[str, str]]:
    if payload.get("kind") == "evidence" and payload.get("tool") in {"list_logistics_centers", "get_modon_context"}:
        summary = payload.get("result", {}).get("snapshot_summary", {})
        if payload.get("tool") == "get_modon_context":
            return [
                (("MODON centers" if language == "en" else "مراكز MODON"), _format_number(summary.get("matching_centers"), language)),
                (("Industrial files" if language == "en" else "ملفات صناعية"), _format_number(len(payload.get("result", {}).get("industrial_assets", [])), language)),
            ]
        filtered = bool(
            payload.get("result", {}).get("regions")
            and len(payload.get("result", {}).get("regions", [])) < 13
        ) or bool((payload.get("result", {}).get("selection") or {}).get("owner")) or (
            (payload.get("result", {}).get("selection") or {}).get("status") not in {None, "all"}
        )
        if filtered:
            return [
                (("Matching centers" if language == "en" else "المراكز المطابقة"), _format_number(summary.get("matching_centers"), language)),
                (("Active in full snapshot" if language == "en" else "المفعلة في اللقطة الكاملة"), _format_number(summary.get("active_centers"), language)),
            ]
        return [
            (("Listed" if language == "en" else "المدرجة"), _format_number(summary.get("listed_centers"), language)),
            (("Active" if language == "en" else "المفعلة"), _format_number(summary.get("active_centers"), language)),
            (("Inactive" if language == "en" else "غير المفعلة"), _format_number(summary.get("inactive_centers"), language)),
        ]
    if payload.get("kind") != "view":
        return []
    view = payload.get("view", {})
    result = view.get("tool_result", {})
    tool = payload.get("tool")
    table = result.get("table", [])
    metadata = _metadata_map(result)
    highlights: list[tuple[str, str]] = []

    if tool == "screen_regions" and table:
        first = table[0]
        highlights.append(("Position" if language == "en" else "الموضع", f"#{_format_number(first.get('screening_position'), language)}"))
        for criterion in result.get("criteria", [])[:2]:
            metric_id = criterion.get("metric_id")
            column = metadata.get(metric_id, {})
            value = _format_number(first.get(metric_id), language)
            highlights.append((column.get("label_en") if language == "en" else column.get("label_ar") or "المؤشر", value))
    elif tool == "evaluate_warehouse_locations" and table:
        first = table[0]
        highlights.append(("Position" if language == "en" else "الموضع", f"#{_format_number(first.get('decision_position'), language)}"))
        highlights.append(("Decision index" if language == "en" else "مؤشر القرار", _format_number(first.get("decision_index_0_100"), language)))
        if first.get("mean_monthly_activity") is not None:
            highlights.append(("Port activity" if language == "en" else "نشاط الميناء", _format_number(first.get("mean_monthly_activity"), language)))
    elif tool == "compare_regions" and table:
        metric_ids = result.get("metric_ids", [])
        metric_id = next((item for item in metric_ids if "_per_" in item), metric_ids[0] if metric_ids else None)
        column = metadata.get(metric_id, {})
        units = UNIT_LABELS_EN if language == "en" else UNIT_LABELS_AR
        unit = units.get(column.get("unit"), column.get("unit") or "")
        for row in table[:3]:
            value = _format_number(row.get(metric_id), language) if metric_id else "—"
            region = row.get("region_en") if language == "en" else row.get("region_ar") or row.get("region_en") or "المنطقة"
            highlights.append((region, f"{value} {unit}".strip()))
    elif tool == "get_indicator_trend":
        for row in result.get("trend_summary", [])[:3]:
            change = row.get("percent_change")
            value = f"{change:+.2f}{'%' if language == 'en' else '٪'}" if isinstance(change, (int, float)) else ("Not available" if language == "en" else "غير متاح")
            region = row.get("region_en") if language == "en" else row.get("region_ar") or row.get("region_en") or "المنطقة"
            highlights.append((region, value))
    elif tool == "get_region_profile" and table:
        row = table[0]
        highlights = (
            [
                ("Population", _format_number(row.get("population_2024"), language)),
                ("Delivery requests", _format_number(row.get("delivery_total_2024_source"), language)),
                ("Licensed warehouses", _format_number(row.get("warehouse_count_2024"), language)),
            ]
            if language == "en"
            else [
                ("السكان", f"{_format_number(row.get('population_2024'))} نسمة"),
                ("طلبات التوصيل", f"{_format_number(row.get('delivery_total_2024_source'))} طلب"),
                ("المستودعات المرخصة", f"{_format_number(row.get('warehouse_count_2024'))} مستودع"),
            ]
        )
    return highlights[:3]


def render_answer_card(
    content: str,
    response: dict[str, Any],
    payload: dict[str, Any],
    *,
    key: str,
    language: str = "ar",
) -> None:
    """Render one concise result card while preserving the grounded model wording."""
    tool = _last_successful_tool(response)
    status = response.get("status")
    presentation = TOOL_PRESENTATION_EN if language == "en" else TOOL_PRESENTATION
    if tool in presentation:
        label, icon, color = presentation[tool]
    elif status == "needs_clarification":
        label, icon, color = ("Clarification needed" if language == "en" else "توضيح مطلوب"), "help", "blue"
    elif status and str(status).startswith("blocked"):
        label, icon, color = ("Answer blocked" if language == "en" else "تعذر إكمال الإجابة"), "warning", "red"
    else:
        label, icon, color = ("Mizan answer" if language == "en" else "إجابة ميزان"), "auto_awesome", "green"

    with st.container(border=True, key=key, gap="small"):
        st.badge(label, icon=f":material/{icon}:", color=color)
        st.markdown(content)
        highlights = _highlight_items(payload, language)
        if highlights:
            with st.container(horizontal=True, gap="small"):
                for metric_label, metric_value in highlights:
                    st.metric(metric_label, metric_value, border=True)


def _metadata_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.get("column"): item
        for item in result.get("columns", [])
        if item.get("column")
    }


def _localize_value(value: Any, language: str = "ar") -> Any:
    if isinstance(value, str):
        if language == "en":
            return VALUE_LABELS_EN.get(value, value)
        mapped = VALUE_LABELS_AR.get(value, UNIT_LABELS_AR.get(value))
        if mapped:
            return mapped
        quarter = re.fullmatch(r"(\d{4}) Q([1-4])", value)
        if quarter:
            label = {"1": "الأول", "2": "الثاني", "3": "الثالث", "4": "الرابع"}[quarter.group(2)]
            return f"الربع {label} {quarter.group(1)}"
        localized = value
        for source, target in VALUE_LABELS_AR.items():
            localized = localized.replace(source, target)
        return localized
    if isinstance(value, list):
        separator = ", " if language == "en" else "، "
        return separator.join(str(_localize_value(item, language)) for item in value)
    return value


def _display_frame(rows: list[dict[str, Any]], result: dict[str, Any], language: str = "ar") -> pd.DataFrame:
    table = pd.DataFrame(rows)
    if table.empty:
        return table
    metadata = _metadata_map(result)
    hidden = [
        column
        for column in table.columns
        if column in INTERNAL_COLUMNS or column.startswith("component__")
    ]
    if language == "en":
        hidden.extend(column for column in ("region_ar", "candidate_ar", "category_ar", "coverage_ar") if column in table.columns)
        if "candidate_en" in table.columns:
            hidden.append("region_en")
    else:
        hidden.extend(column for column in ("region_en", "candidate_en", "category_en", "coverage_en") if column in table.columns)
        if "candidate_ar" in table.columns:
            hidden.append("region_ar")
    table = table.drop(columns=hidden, errors="ignore")
    generic = GENERIC_COLUMN_LABELS_EN if language == "en" else GENERIC_COLUMN_LABELS
    rename = {}
    for column in table.columns:
        column_meta = metadata.get(column, {})
        label = column_meta.get("label_en") if language == "en" else column_meta.get("label_ar")
        rename[column] = label or generic.get(column) or column.replace("_", " ")
    table = table.rename(columns=rename)
    for column in table.columns:
        if pd.api.types.is_float_dtype(table[column]):
            table[column] = table[column].round(2)
        elif table[column].dtype == "object":
            table[column] = table[column].map(lambda value: _localize_value(value, language))
    return table


def _display_table(view: dict[str, Any], language: str = "ar") -> pd.DataFrame:
    return _display_frame(view.get("table", []), view.get("tool_result", {}), language)


def _localized_title(value: str, language: str = "ar") -> str:
    if language == "en":
        return value
    localized = (
        value.replace("Screening", "الفرز الأولي")
        .replace("PortWatch", "بيانات النشاط البحري التجريبية")
        .replace("calls", "زيارات السفن")
        .replace("imports", "الواردات")
        .replace("exports", "الصادرات")
    )
    for source, target in VALUE_LABELS_AR.items():
        localized = localized.replace(source, target)
    return localized


def render_chart(spec: dict[str, Any], language: str = "ar") -> None:
    data = pd.DataFrame(spec.get("data", []))
    title = spec.get("title_en", "Chart") if language == "en" else _localized_title(spec.get("title_ar", "الرسم"))
    st.markdown(f"**{title}**")
    if data.empty:
        st.caption("No values are available for this selection." if language == "en" else "لا توجد قيم ضمن الاختيار الحالي.")
        return
    x_source = spec["x"]
    y_source = spec["y"]
    color_source = spec.get("color")
    quantitative_source = y_source if spec["chart_type"] == "line" or spec.get("orientation") != "horizontal" else x_source
    numeric_values = pd.to_numeric(data[quantitative_source], errors="coerce")
    finite_mask = numeric_values.map(lambda value: bool(pd.notna(value)) and math.isfinite(float(value)))
    data = data.loc[finite_mask].copy()
    data[quantitative_source] = numeric_values.loc[finite_mask].astype(float)
    if data.empty:
        st.caption("No finite numeric values are available for this chart." if language == "en" else "لا توجد قيم رقمية صالحة لعرض هذا الرسم.")
        return
    data["المحور الأفقي"] = data[x_source].map(lambda value: _localize_value(value, language))
    data["المحور الرأسي"] = data[y_source].map(lambda value: _localize_value(value, language))
    if color_source:
        data["السلسلة"] = data[color_source].map(lambda value: _localize_value(value, language))
    units = UNIT_LABELS_EN if language == "en" else UNIT_LABELS_AR
    unit_label = units.get(spec.get("unit"), spec.get("unit") or ("Value" if language == "en" else "القيمة"))
    st.caption(f"Unit: {unit_label}" if language == "en" else f"الوحدة: {unit_label}")
    if spec["chart_type"] == "line":
        color = (
            alt.Color(
                "السلسلة:N",
                title="المنطقة أو السلسلة",
                scale=alt.Scale(range=["#087F8C", "#142B40", "#20B5AD", "#647B8C", "#07515B"]),
            )
            if color_source
            else alt.value("#087F8C")
        )
        chart = (
            alt.Chart(data)
            .mark_line(point=True, strokeWidth=3)
            .encode(
                x=alt.X("المحور الأفقي:N", title="Period" if language == "en" else "الفترة", sort=None),
                y=alt.Y("المحور الرأسي:Q", title=unit_label, scale=alt.Scale(zero=True)),
                color=color,
                tooltip=[
                    alt.Tooltip("المحور الأفقي:N", title="Period" if language == "en" else "الفترة"),
                    alt.Tooltip("المحور الرأسي:Q", title=unit_label, format=",.2f"),
                    *([alt.Tooltip("السلسلة:N", title="Region or series" if language == "en" else "المنطقة أو السلسلة")] if color_source else []),
                ],
            )
            .properties(height=320)
        )
        st.altair_chart(chart)
    else:
        horizontal = spec.get("orientation") == "horizontal"
        numeric_column = "المحور الأفقي" if horizontal else "المحور الرأسي"
        maximum = data[numeric_column].max() if not data.empty else None
        data["التمييز"] = data[numeric_column].map(
            lambda value: ("Leading" if language == "en" else "الأبرز") if value == maximum else ("Other results" if language == "en" else "بقية النتائج")
        )
        x_encoding = (
            alt.X("المحور الأفقي:Q", title=unit_label, scale=alt.Scale(zero=True), stack=None)
            if horizontal
            else alt.X(
                "المحور الأفقي:N",
                title="Region or location" if language == "en" else "المنطقة أو الموقع",
                sort=None,
                axis=alt.Axis(labelAngle=0 if len(data) <= 5 else -35, labelLimit=180),
            )
        )
        y_encoding = (
            alt.Y("المحور الرأسي:N", title="Region or location" if language == "en" else "المنطقة أو الموقع", sort=None)
            if horizontal
            else alt.Y("المحور الرأسي:Q", title=unit_label, scale=alt.Scale(zero=True), stack=None)
        )
        tooltips = (
            [
                alt.Tooltip("المحور الأفقي:Q", title=unit_label, format=",.2f"),
                alt.Tooltip("المحور الرأسي:N", title="Region or location" if language == "en" else "المنطقة أو الموقع"),
            ]
            if horizontal
            else [
                alt.Tooltip("المحور الأفقي:N", title="Region or location" if language == "en" else "المنطقة أو الموقع"),
                alt.Tooltip("المحور الرأسي:Q", title=unit_label, format=",.2f"),
            ]
        )
        chart = (
            alt.Chart(data)
            .mark_bar(cornerRadiusEnd=5)
            .encode(
                x=x_encoding,
                y=y_encoding,
                color=alt.Color(
                    "التمييز:N",
                    scale=alt.Scale(
                        domain=["Leading", "Other results"] if language == "en" else ["الأبرز", "بقية النتائج"],
                        range=["#087F8C", "#A8C8CD"],
                    ),
                    legend=None,
                ),
                tooltip=tooltips,
            )
            .properties(height=320)
        )
        st.altair_chart(chart)


def render_sources(citations: list[dict[str, Any]], language: str = "ar") -> None:
    if not citations:
        st.caption("No additional references are linked to this answer." if language == "en" else "لا توجد مراجع إضافية مرتبطة بهذه الإجابة.")
        return
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for item in citations:
        identity = (
            item.get("source_path"),
            item.get("source_url"),
            item.get("source_id"),
            item.get("agency"),
        )
        group = grouped.setdefault(identity, {**item, "pages": [], "tables": []})
        if item.get("page_start") is not None:
            group["pages"].append(item["page_start"])
        if item.get("table_number"):
            group["tables"].append(item["table_number"])

    for index, item in enumerate(grouped.values(), start=1):
        agency = item.get("agency") or ("Documented reference" if language == "en" else "مرجع موثق")
        title = item.get("citation_label") or item.get("source_id") or (f"Reference {index}" if language == "en" else f"مرجع {index}")
        title = re.sub(r"[،,]\s*ص\.?\s*\d+.*$", "", str(title)).strip()
        pages = "، ".join(str(value) for value in sorted(set(item.get("pages", [])), key=str))
        tables = "، ".join(str(value) for value in dict.fromkeys(item.get("tables", [])))
        location_parts = []
        if pages:
            location_parts.append(f"Pages: {pages}" if language == "en" else f"الصفحات: {pages}")
        if tables:
            location_parts.append(f"Tables: {tables}" if language == "en" else f"الجداول: {tables}")
        if item.get("published_date"):
            location_parts.append(
                f"Published: {item['published_date']}"
                if language == "en"
                else f"تاريخ النشر: {item['published_date']}"
            )
        if item.get("access_date"):
            location_parts.append(
                f"Accessed: {item['access_date']}"
                if language == "en"
                else f"تاريخ الوصول: {item['access_date']}"
            )
        with st.container(border=True, gap="small"):
            st.markdown(f"**{title}**")
            st.caption(
                " · ".join(
                    part
                    for part in (
                        agency if language == "en" else AGENCY_LABELS_AR.get(agency, agency),
                        str(item.get("year") or ("Year not specified" if language == "en" else "سنة غير محددة")),
                        " · ".join(location_parts),
                    )
                    if part
                )
            )
            if item.get("source_url"):
                st.link_button(
                    "Open source" if language == "en" else "فتح المصدر",
                    item["source_url"],
                    icon=":material/open_in_new:",
                    type="tertiary",
                )


def _render_constraints(response: dict[str, Any], language: str = "ar") -> None:
    limitations = response.get("limitations", [])
    missing = [
        note
        for note in response.get("missing_data_notes", [])
        if note and not str(note).startswith("لا توجد قيم مفقودة") and not str(note).startswith("No missing values")
    ]
    if not limitations and not missing:
        st.caption("No additional limitations were identified for this question." if language == "en" else "لم تظهر قيود إضافية لهذا السؤال.")
        return
    with st.container(border=True, gap="small"):
        for limitation in limitations:
            st.caption(f":material/info: {limitation}")
        for note in missing:
            st.caption(f":material/database_off: {note}")


def _render_trace(response: dict[str, Any], language: str = "ar") -> None:
    traces = response.get("tool_trace", [])
    if not traces:
        st.caption("This question did not require numeric analysis." if language == "en" else "لم يحتج السؤال إلى تحليل رقمي.")
        return
    frame = pd.DataFrame([
        (
            {
                "Analysis": item.get("tool", "Data analysis").replace("_", " "),
                "Status": "Completed" if item.get("status") == "success" else "Incomplete",
                "Duration (ms)": item.get("duration_ms"),
                "Rows": item.get("result_summary", {}).get("table_rows"),
            }
            if language == "en"
            else {
                "التحليل": TOOL_LABELS.get(item.get("tool"), "تحليل بيانات"),
                "الحالة": "اكتمل" if item.get("status") == "success" else "لم يكتمل",
                "الزمن بالمللي ثانية": item.get("duration_ms"),
                "عدد الصفوف": item.get("result_summary", {}).get("table_rows"),
            }
        )
        for item in traces
    ])
    st.dataframe(frame, hide_index=True)
    st.caption(
        f"Model: {response.get('model', '—')} · Processing status: {response.get('status', '—')}"
        if language == "en"
        else f"النموذج: {response.get('model', '—')} · حالة المعالجة: {response.get('status', '—')}"
    )


def _render_result_data(payload: dict[str, Any], language: str = "ar") -> None:
    result = payload.get("result", {})
    tool = payload.get("tool")
    if tool == "identify_missing_data":
        for row in result.get("table", []):
            status = row.get("status")
            icon = ":material/check_circle:" if status == "available_with_caveat" else ":material/warning:"
            with st.container(border=True):
                label = row.get("label_en") or str(row.get("concept_id") or "Requested concept").replace("_", " ") if language == "en" else row.get("label_ar") or "المفهوم المطلوب"
                note = row.get("note_en") if language == "en" else row.get("note_ar") or row.get("note")
                st.markdown(f"{icon} **{label}**")
                st.write(note or "")
        return
    if tool == "get_metric_source":
        metadata = result.get("metadata", {})
        with st.container(border=True):
            st.markdown(f"**{metadata.get('metric_name_en') or 'Metric definition' if language == 'en' else metadata.get('metric_name_ar') or 'تعريف المؤشر'}**")
            st.write(("A documented source record is available." if language == "en" else metadata.get("definition_ar") or "لا يتوفر تعريف إضافي."))
            st.caption(
                " · ".join(
                    item
                    for item in (
                        (f"Unit: {UNIT_LABELS_EN.get(metadata.get('unit'), metadata.get('unit') or 'not specified')}" if language == "en" else f"الوحدة: {UNIT_LABELS_AR.get(metadata.get('unit'), metadata.get('unit') or 'غير محددة')}"),
                        (f"Period: {metadata.get('period') or metadata.get('year') or 'not specified'}" if language == "en" else f"الفترة: {metadata.get('period') or metadata.get('year') or 'غير محددة'}"),
                        (f"Geographic basis: {metadata.get('geographic_basis') or 'not specified'}" if language == "en" else f"النطاق الجغرافي: {metadata.get('geographic_basis_ar') or 'غير محدد'}"),
                    )
                    if item
                )
            )
        return
    if tool == "validate_comparison":
        if result.get("ok"):
            st.success("The comparison is allowed with its limitations displayed." if language == "en" else "المقارنة مسموحة مع إظهار القيود المرتبطة بالمؤشرات.", icon=":material/check_circle:")
        else:
            st.warning("The comparison needs revision before use." if language == "en" else "تحتاج المقارنة إلى تعديل قبل استخدامها.", icon=":material/warning:")
        for item in result.get("errors", []) + result.get("warnings", []):
            st.write(item.get("message_ar") or item.get("message") or "ملاحظة تحقق")
        return
    if tool in {"list_logistics_centers", "get_modon_context"}:
        summary_table = _display_frame(result.get("table", []), result, language)
        if not summary_table.empty:
            st.dataframe(summary_table, hide_index=True, height=min(420, 48 + 36 * len(summary_table)))
        details = result.get("details", [])
        if details:
            label = "Center-level listing" if language == "en" else "قائمة المراكز بالتفصيل"
            with st.expander(label, icon=":material/location_city:"):
                detail_columns = [
                    "center_name_ar", "region_ar_derived", "owner_ar", "center_type_ar",
                    "status_ar", "area_sqm_reconciled", "map_url",
                ]
                detail_frame = pd.DataFrame(details)
                detail_frame = detail_frame[[column for column in detail_columns if column in detail_frame.columns]]
                detail_frame = detail_frame.rename(columns={
                    **(GENERIC_COLUMN_LABELS_EN if language == "en" else GENERIC_COLUMN_LABELS),
                    "region_ar_derived": "Region" if language == "en" else "المنطقة",
                    "map_url": "Map" if language == "en" else "الخريطة",
                })
                st.dataframe(detail_frame, hide_index=True, height=min(520, 48 + 36 * len(detail_frame)))
        assets = result.get("industrial_assets", [])
        if assets:
            st.caption("Available MODON industrial workbooks" if language == "en" else "ملفات MODON الصناعية المتاحة")
            st.dataframe(pd.DataFrame(assets), hide_index=True, height=min(320, 48 + 36 * len(assets)))
        return
    table = _display_frame(result.get("table", []), result, language)
    if table.empty:
        st.caption("No additional rows are available." if language == "en" else "لا توجد صفوف إضافية للعرض.")
    else:
        st.dataframe(table, hide_index=True, height=min(420, 48 + 36 * len(table)))


def _render_sources_and_constraints(response: dict[str, Any], language: str = "ar") -> None:
    st.markdown("**References used**" if language == "en" else "**المراجع المستخدمة**")
    render_sources(response.get("citations", []), language)
    st.markdown("**What should be considered?**" if language == "en" else "**ما الذي يجب الانتباه له؟**")
    _render_constraints(response, language)


def _render_screening_method(view: dict[str, Any], language: str = "ar") -> None:
    result = view.get("tool_result", {})
    criteria = result.get("criteria", [])
    metadata = _metadata_map(result)
    if not criteria:
        st.caption("No additional criterion details are available." if language == "en" else "لا تتوفر تفاصيل إضافية للمعايير المستخدمة.")
        return
    with st.container(horizontal=True, gap="small"):
        for criterion in criteria:
            metric_id = criterion.get("metric_id")
            column = metadata.get(metric_id, {})
            weight = float(criterion.get("normalized_weight", criterion.get("weight", 0))) * 100
            direction = (
                ("Higher is preferred" if criterion.get("direction") == "higher" else "Lower is preferred")
                if language == "en"
                else ("القيمة الأعلى" if criterion.get("direction") == "higher" else "القيمة الأقل")
            )
            if metric_id == "port_activity":
                label = "Port activity" if language == "en" else "نشاط الميناء"
            else:
                label = column.get("label_en") if language == "en" else column.get("label_ar")
            st.metric(
                label or ("Criterion" if language == "en" else "المعيار"),
                f"{weight:.0f}{'%' if language == 'en' else '٪'}",
                delta=direction,
                delta_color="off",
                border=True,
            )
    sensitivity = result.get("sensitivity", [])
    if sensitivity:
        first = sensitivity[0]
        minimum = first.get("position_min")
        maximum = first.get("position_max")
        region = _localize_value(first.get("region_en"), language)
        st.caption(
            f"Stability: {region} moves between positions {minimum} and {maximum} when weights change in the sensitivity test."
            if language == "en"
            else f"ثبات النتيجة: {region} يتحرك بين الموضع {minimum} و{maximum} عند تغيير الأوزان ضمن اختبار الحساسية."
        )


def render_dashboard(
    payload: dict[str, Any],
    response: dict[str, Any] | None,
    *,
    developer_mode: bool = False,
    language: str = "ar",
) -> None:
    """Render the optional evidence layer. The caller keeps this behind a collapsed control."""
    if payload.get("kind") == "empty":
        return
    response = response or {}

    if payload.get("kind") == "view":
        view = payload["view"]
        st.caption(view.get("title_en", "Result details") if language == "en" else _localized_title(view.get("title_ar", "تفاصيل النتيجة")))
        tab_specs: list[tuple[str, str]] = []
        if payload.get("tool") in {"screen_regions", "evaluate_warehouse_locations"}:
            tab_specs.append(("method", ":material/tune: Why this result?" if language == "en" else ":material/tune: لماذا هذه النتيجة؟"))
        if view.get("charts"):
            tab_specs.append(("chart", ":material/bar_chart: Chart" if language == "en" else ":material/bar_chart: الرسم"))
        tab_specs.extend(
            [
                ("data", ":material/table_chart: Data" if language == "en" else ":material/table_chart: البيانات"),
                ("sources", ":material/library_books: Sources" if language == "en" else ":material/library_books: المصادر"),
            ]
        )
        if developer_mode:
            tab_specs.append(("trace", ":material/account_tree: Execution trace" if language == "en" else ":material/account_tree: سجل التنفيذ"))
        tabs = st.tabs([label for _, label in tab_specs])
        for (tab_kind, _), tab in zip(tab_specs, tabs, strict=True):
            with tab:
                if tab_kind == "method":
                    _render_screening_method(view, language)
                elif tab_kind == "chart":
                    for spec in view.get("charts", []):
                        render_chart(spec, language)
                elif tab_kind == "data":
                    table = _display_table(view, language)
                    if table.empty:
                        st.caption("No rows are available." if language == "en" else "لا توجد صفوف للعرض.")
                    else:
                        st.dataframe(table, hide_index=True, height=min(380, 48 + 36 * len(table)))
                elif tab_kind == "sources":
                    _render_sources_and_constraints(response, language)
                elif tab_kind == "trace":
                    _render_trace(response, language)
        return

    if payload.get("kind") == "knowledge":
        st.caption("Document references and pages used for the answer" if language == "en" else "مراجع الوثائق والصفحات التي بُني عليها الجواب")
        _render_sources_and_constraints(response, language)
        if developer_mode:
            with st.expander("Execution trace" if language == "en" else "سجل التنفيذ", icon=":material/account_tree:"):
                _render_trace(response, language)
        return

    labels = (
        [":material/table_chart: Data", ":material/library_books: Sources and limitations"]
        if language == "en"
        else [":material/table_chart: البيانات", ":material/library_books: المصادر والقيود"]
    )
    if developer_mode:
        labels.append(":material/account_tree: Execution trace" if language == "en" else ":material/account_tree: سجل التنفيذ")
    tabs = st.tabs(labels)
    with tabs[0]:
        if payload.get("kind") == "knowledge":
            st.caption("النص المختصر ظهر في الجواب، ويمكن مراجعة مراجعه هنا.")
        else:
            _render_result_data(payload, language)
    with tabs[1]:
        _render_sources_and_constraints(response, language)
    if developer_mode:
        with tabs[2]:
            _render_trace(response, language)
