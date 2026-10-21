from __future__ import annotations

import re
from typing import Any

from ..tools.entities import normalize_entity_text

from .i18n import detect_language, normalize_language


UNIT_LABELS_AR = {
    "person": "نسمة",
    "executed request": "طلب منفذ",
    "request": "طلب",
    "request per 1,000 persons": "طلب لكل ألف نسمة",
    "licensed warehouse": "مستودع مرخص",
    "warehouse": "مستودع مرخص",
    "warehouse per 100,000 persons": "مستودع لكل 100 ألف نسمة",
    "square meter": "متر مربع",
    "square meter per person": "متر مربع للفرد",
    "active license": "ترخيص نشط",
    "license per 100,000 persons": "ترخيص لكل 100 ألف نسمة",
    "activated center": "مركز مفعّل",
    "center": "مركز",
    "port": "ميناء",
    "factory": "مصنع",
    "industrial city": "مدينة صناعية",
    "ready factory unit": "وحدة مصنع جاهز",
    "center per 1,000,000 persons": "مركز لكل مليون نسمة",
    "PortWatch experimental activity unit": "وحدة نشاط بحرية تجريبية",
    "0-100": "نقطة من 100",
    "0-100 relative index": "نقطة نسبية ضمن المرشحين الحاليين",
}

UNIT_LABELS_EN = {
    "person": "people",
    "executed request": "completed requests",
    "request": "requests",
    "request per 1,000 persons": "requests per 1,000 people",
    "licensed warehouse": "licensed warehouses",
    "warehouse": "licensed warehouses",
    "warehouse per 100,000 persons": "warehouses per 100,000 people",
    "square meter": "m²",
    "square meter per person": "m² per person",
    "active license": "active licenses",
    "license per 100,000 persons": "licenses per 100,000 people",
    "activated center": "activated centers",
    "center": "centers",
    "port": "ports",
    "factory": "factories",
    "industrial city": "industrial cities",
    "ready factory unit": "ready-factory units",
    "center per 1,000,000 persons": "centers per million people",
    "PortWatch experimental activity unit": "experimental PortWatch activity units",
    "0-100": "points out of 100",
    "0-100 relative index": "relative points within the current candidates",
}


def _number(value: Any) -> str:
    """Format user-facing numbers with no more than two decimal places."""
    if value is None:
        return "غير متاح"
    if isinstance(value, bool):
        return "نعم" if value else "لا"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return str(value)


def _unit(value: Any) -> str:
    if not value:
        return ""
    return UNIT_LABELS_AR.get(str(value), str(value))


def _unit_en(value: Any) -> str:
    if not value:
        return ""
    return UNIT_LABELS_EN.get(str(value), str(value))


def _important_limitation(result: dict[str, Any]) -> str | None:
    limitations = [str(item).strip() for item in result.get("limitations", []) if str(item).strip()]
    if not limitations:
        return None
    generic_fragments = ("النتائج للاستكشاف", "لا توجد قيم مفقودة", "يتكرر مفهوميًا")
    return next((item for item in limitations if not any(text in item for text in generic_fragments)), limitations[0])


def _with_warning(
    summary: str,
    facts: list[str],
    result: dict[str, Any],
    *,
    facts_label: str = "أهم الأرقام",
) -> str:
    parts = [f"**الخلاصة:** {summary}"]
    if facts:
        fact_text = "؛ ".join(facts[:3]).rstrip(" .،؛") + "."
        parts.append(f"**{facts_label}:** {fact_text}")
    warning = _important_limitation(result)
    if warning:
        parts.append(f"**تنبيه:** {warning}")
    return "\n\n".join(parts)


def _with_warning_en(
    summary: str,
    facts: list[str],
    result: dict[str, Any],
    *,
    facts_label: str = "Key evidence",
) -> str:
    parts = [f"**Summary:** {summary}"]
    if facts:
        parts.append(f"**{facts_label}:** " + "; ".join(facts[:3]).rstrip(" .;") + ".")
    limitations = [str(item).strip() for item in result.get("limitations_en", []) if str(item).strip()]
    if not limitations:
        tool = result.get("tool")
        if tool in {"compare_regions", "get_region_profile", "screen_regions"}:
            limitations = ["Licensed facilities and activity indicators do not measure occupancy, operating capacity, cost, or profitability."]
        elif tool in {"compare_ports", "get_port_context"}:
            limitations = ["PortWatch is partial experimental context and does not measure capacity, occupancy, or customs-clearance time."]
        elif tool == "get_indicator_trend":
            limitations = ["The available points describe a documented change, not a forecast."]
    if limitations:
        parts.append(f"**Caveat:** {limitations[0]}")
    return "\n\n".join(parts)


def _region_label(result: dict[str, Any], canonical: str | None) -> str:
    if not canonical:
        return "المنطقة"
    for row in result.get("table", []):
        if row.get("region_en") == canonical:
            return row.get("region_ar") or canonical
    return canonical


def _location_label(result: dict[str, Any], location: str | None) -> str:
    if not location:
        return "الميناء"
    for port in result.get("ports", []):
        if location in {port.get("portwatch_location"), port.get("port_code"), port.get("port_name_en")}:
            return port.get("port_name_ar") or port.get("port_name_en") or location
    return location


def _primary_difference(differences: list[dict[str, Any]]) -> dict[str, Any]:
    """Prefer population-normalized comparisons when the tool returned raw and normalized peers."""
    return next(
        (
            item
            for item in differences
            if "_per_" in str(item.get("metric_id") or item.get("measure") or "")
            or item.get("measure") == "mean_monthly_activity"
        ),
        differences[0],
    )


def _period_label(value: Any) -> str:
    text = str(value or "غير محدد")
    match = re.fullmatch(r"(\d{4}) Q([1-4])", text)
    if not match:
        return text
    quarter = {"1": "الأول", "2": "الثاني", "3": "الثالث", "4": "الرابع"}[match.group(2)]
    return f"الربع {quarter} {match.group(1)}"


def _primary_table_metric(result: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    metadata = {
        item.get("column"): item
        for item in result.get("columns", [])
        if item.get("column")
    }
    metric_ids = [
        metric_id
        for metric_id in result.get("metric_ids", [])
        if any(isinstance(row.get(metric_id), (int, float)) for row in result.get("table", []))
    ]
    metric_id = next((item for item in metric_ids if "_per_" in item), metric_ids[0] if metric_ids else None)
    return metric_id, metadata.get(metric_id, {})


def _metadata_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.get("column"): item
        for item in result.get("columns", [])
        if item.get("column")
    }


def _comparison_answer(question: str, result: dict[str, Any]) -> str:
    differences = result.get("pairwise_differences", [])
    if not differences:
        metric_id, metadata = _primary_table_metric(result)
        if not metric_id:
            return _with_warning("اكتملت المقارنة، ولا توجد قيم رقمية قابلة للعرض.", [], result)
        rows = [
            row for row in result.get("table", [])
            if isinstance(row.get(metric_id), (int, float))
        ]
        if not rows:
            return _with_warning("اكتملت المقارنة، ولا توجد قيم رقمية قابلة للعرض.", [], result)
        ranked = sorted(rows, key=lambda row: row[metric_id], reverse=True)
        top = ranked[0]
        metric_name = metadata.get("label_ar") or metric_id
        unit = _unit(metadata.get("unit"))
        summary = f"{top.get('region_ar') or top.get('region_en')} يتصدر المناطق المحددة في {metric_name}."
        values = "، ".join(
            f"{row.get('region_ar') or row.get('region_en')}: {_number(row.get(metric_id))}"
            for row in ranked[:3]
        )
        if unit:
            values = f"{values} {unit}"
        return _with_warning(summary, [f"{metric_name}: {values}"], result)

    requested = result.get("requested_metric_ids") or result.get("metric_ids") or []
    requested_differences = [item for item in differences if item.get("metric_id") in requested]
    displayed_differences = requested_differences or [_primary_difference(differences)]
    first = displayed_differences[0].get("first_region")
    second = displayed_differences[0].get("second_region")
    if len(result.get("regions", [])) == 2 and len(displayed_differences) > 1:
        higher_counts = {
            first: sum(item.get("higher_region") == first for item in displayed_differences),
            second: sum(item.get("higher_region") == second for item in displayed_differences),
        }
        equal_count = sum(not item.get("higher_region") for item in displayed_differences)
        first_label = _region_label(result, first)
        second_label = _region_label(result, second)
        if higher_counts[first] and higher_counts[second]:
            summary = (
                f"المقارنة بين {first_label} و{second_label} مختلطة: سجلت {first_label} قيمة أعلى في "
                f"{higher_counts[first]} مؤشرات مباشرة، و{second_label} في {higher_counts[second]}"
                + (f"، وتعادلا في {equal_count}" if equal_count else "")
                + ". لا توجد درجة فوز مركبة."
            )
        else:
            leader = first if higher_counts[first] else second
            summary = (
                f"{_region_label(result, leader)} سجل قيمة أعلى في {max(higher_counts.values())} من أصل "
                f"{len(displayed_differences)} مؤشرات مباشرة؛ هذا وصف رقمي وليس حكمًا بأن المنطقة أفضل استثماريًا."
            )
    else:
        primary = _primary_difference(differences)
        higher = primary.get("higher_region")
        if higher:
            other = primary.get("second_region") if higher == primary.get("first_region") else primary.get("first_region")
            summary = f"{_region_label(result, higher)} أعلى من {_region_label(result, other)} في {primary.get('metric_name_ar') or 'المؤشر المحدد'}."
        else:
            summary = f"القيم متساوية في {primary.get('metric_name_ar') or 'المؤشر المحدد'}."

    facts: list[str] = []
    for item in displayed_differences[:3]:
        metric = item.get("metric_name_ar") or "المؤشر"
        first_label = item.get("first_region_ar") or _region_label(result, item.get("first_region"))
        second_label = item.get("second_region_ar") or _region_label(result, item.get("second_region"))
        unit = _unit(item.get("unit"))
        suffix = f" {unit}" if unit else ""
        facts.append(
            f"{metric}: {first_label} {_number(item.get('first_value'))} مقابل "
            f"{second_label} {_number(item.get('second_value'))}{suffix}"
        )

    normalized_question = normalize_entity_text(question)
    city_notes: list[str] = []
    if "جدة" in normalized_question and "مكة" not in normalized_question:
        city_notes.append("جدة ممثلة بمنطقة مكة المكرمة")
    if "الدمام" in normalized_question and "الشرقية" not in normalized_question:
        city_notes.append("الدمام ممثلة بالمنطقة الشرقية")
    if city_notes:
        city_note = " و".join(city_notes) + "؛ الأدلة هنا على مستوى المناطق الإدارية وليست مقارنة مباشرة بين المدينتين."
        result = {**result, "limitations": [city_note, *result.get("limitations", [])]}
    return _with_warning(summary, facts, result)


def _trend_answer(result: dict[str, Any]) -> str:
    summaries = result.get("trend_summary", [])
    if not summaries:
        return _with_warning("لا توجد نقاط كافية لاستخلاص اتجاه زمني.", [], result)
    facts = []
    directions: list[tuple[str, str]] = []
    for row in summaries:
        region = row.get("region_ar") or row.get("region_en") or "المنطقة"
        change = row.get("percent_change")
        direction = "ارتفع" if isinstance(change, (int, float)) and change > 0 else "انخفض" if change else "استقر"
        directions.append((region, direction))
        facts.append(
            f"{region} — {_period_label(row.get('first_period'))}: {_number(row.get('first_value'))}؛ "
            f"{_period_label(row.get('last_period'))}: {_number(row.get('last_value'))}؛ "
            f"التغير: {direction} {_number(abs(change or 0))}٪"
        )
    unique_directions = {direction for _, direction in directions}
    if len(unique_directions) == 1:
        direction = next(iter(unique_directions))
        names = " و".join(name for name, _ in directions)
        summary = f"{direction} المؤشر في {names} خلال الفترة المتاحة."
    else:
        summary = "اختلف اتجاه المؤشر بين المناطق خلال الفترة المتاحة."
    return _with_warning(summary, facts, result)


def _ports_answer(result: dict[str, Any]) -> str:
    differences = result.get("pairwise_differences", [])
    summary_rows = result.get("summary", [])
    metric = (result.get("selection") or {}).get("metric")
    activity_unit = "زيارة سفينة مرصودة" if metric == "calls" else "وحدة نشاط تجاري بحري تجريبية"
    if differences:
        preferred = next(
            (item for item in differences if item.get("measure") == "mean_monthly_activity"),
            differences[0],
        )
        higher = _location_label(result, preferred.get("higher_location"))
        summary = f"{higher} سجّل النشاط المرصود الأعلى خلال الفترة المتطابقة."
    elif len(summary_rows) >= 2:
        leader = max(summary_rows, key=lambda row: float(row.get("mean_monthly_activity") or 0))
        summary = (
            f"{_location_label(result, leader.get('location'))} سجّل أعلى متوسط شهري بين "
            f"{_number(len(summary_rows))} موانئ ذات سلاسل متقابلة متاحة."
        )
    else:
        names = "، ".join(
            port.get("port_name_ar") or port.get("port_name_en") or "الميناء"
            for port in result.get("ports", [])
        )
        summary = f"تم استرجاع السياق البحري المتاح لـ{names}." if names else "لا تتوفر تغطية بحرية لهذا الاختيار."

    facts = []
    if differences:
        preferred = _primary_difference(differences)
        first_label = _location_label(result, preferred.get("first_location"))
        second_label = _location_label(result, preferred.get("second_location"))
        facts.append(
            f"المتوسط الشهري: {first_label} {_number(preferred.get('first_value'))} مقابل "
            f"{second_label} {_number(preferred.get('second_value'))} {activity_unit}، "
            f"والفارق {_number(preferred.get('absolute_gap'))}"
        )
    elif summary_rows:
        for row in sorted(summary_rows, key=lambda item: float(item.get("mean_monthly_activity") or 0), reverse=True)[:3]:
            label = _location_label(result, row.get("location"))
            facts.append(
                f"{label}: متوسط شهري {_number(row.get('mean_monthly_activity'))}، "
                f"وآخر شهر {_number(row.get('latest_month_activity'))} {activity_unit}"
            )
    elif result.get("ports"):
        coverage = result.get("coverage_summary", {})
        facts.extend(
            [
                f"التغطية الحالية: {_number(coverage.get('ports_with_portwatch'))} موانئ من أصل {_number(coverage.get('mapped_ports'))} ميناءً في دليل الربط",
                f"الفترة الشهرية المتاحة: {coverage.get('series_start') or 'غير محددة'} إلى {coverage.get('series_end') or 'غير محددة'}",
            ]
        )
    unavailable = result.get("unavailable_ports", [])
    if unavailable:
        names = "، ".join(
            port.get("port_name_ar") or port.get("port_name_en") or "الميناء"
            for port in unavailable
        )
        result = {
            **result,
            "limitations": [
                f"{names} معروف في دليل الموانئ، لكن لا تتوفر له سلسلة نشاط بحري منسقة للمقارنة الحالية.",
                *result.get("limitations", []),
            ],
        }
    return _with_warning(summary, facts, result)


def _gateway_answer(result: dict[str, Any]) -> str:
    rows = result.get("table", [])
    if not rows:
        return _with_warning("لم تتوفر إشارات بحرية ولوجستية قابلة للربط للمناطق المحددة.", [], result)
    selection = result.get("selection", {})
    metric = selection.get("port_metric")
    direction = selection.get("port_direction")
    if metric == "calls":
        port_label = "متوسط زيارات السفن شهريًا"
    elif direction == "outgoing":
        port_label = "متوسط النشاط التجاري البحري الصادر شهريًا"
    else:
        port_label = "متوسط النشاط التجاري البحري الوارد شهريًا"
    available = [row for row in rows if isinstance(row.get("mean_monthly_port_activity"), (int, float))]
    if len(rows) == 2 and len(available) == 2:
        port_leader = max(available, key=lambda row: row["mean_monthly_port_activity"])
        center_leader = max(rows, key=lambda row: row.get("current_listed_centers") or 0)
        if port_leader.get("region_en") == center_leader.get("region_en"):
            summary = f"{port_leader.get('region_ar') or port_leader.get('region_en')} أعلى في النشاط البحري المرصود وعدد المراكز المدرجة حاليًا، مع إبقاء المؤشرين منفصلين."
        else:
            summary = (
                f"الصورة مختلطة: {port_leader.get('region_ar') or port_leader.get('region_en')} أعلى بحريًا، "
                f"بينما {center_leader.get('region_ar') or center_leader.get('region_en')} لديها مراكز مدرجة أكثر."
            )
    else:
        summary = "اكتملت مقارنة النشاط البحري المرصود وحضور المراكز اللوجستية كمحورين مستقلين دون درجة مركبة."
    facts = []
    for row in rows[:3]:
        region = row.get("region_ar") or row.get("region_en")
        port_value = _number(row.get("mean_monthly_port_activity"))
        facts.append(
            f"{region}: {port_label} {port_value} بوحدة تجريبية؛ "
            f"{_number(row.get('current_listed_centers'))} مركزًا مدرجًا حاليًا "
            f"({_number(row.get('current_active_centers'))} مفعّلة)"
        )
    return _with_warning(summary, facts, result, facts_label="المحوران المقارنان")


def _profile_answer(result: dict[str, Any]) -> str:
    region = result.get("region", {})
    name = region.get("region_ar") or region.get("region_en") or "المنطقة"
    rows = result.get("table", [])
    row = rows[0] if rows else {}
    facts = [
        f"السكان {_number(row.get('population_2024'))} نسمة",
        f"طلبات التوصيل {_number(row.get('delivery_total_2024_source'))} طلبًا منفذًا",
        f"المستودعات المرخصة {_number(row.get('warehouse_count_2024'))} مستودعًا",
    ]
    return _with_warning(f"هذا ملخص الملف اللوجستي لمنطقة {name} وفق بيانات 2024 المتاحة.", facts, result)


def _logistics_centers_answer(result: dict[str, Any]) -> str:
    snapshot = result.get("snapshot_summary", {})
    rows = result.get("table", [])
    details = result.get("details", [])
    selection = result.get("selection", {})
    if selection.get("sort_by") in {"area_desc", "area_asc"} and details:
        descending = selection.get("sort_by") == "area_desc"
        direction = "أكبر" if descending else "أصغر"
        summary = f"هذه {direction} {_number(len(details))} مراكز حسب المساحة المسجلة في لقطة لوجستي الحالية."
        facts = [
            f"{row.get('center_name_ar')}: {_number(row.get('area_sqm_reconciled'))} متر مربع — {row.get('region_ar_derived')} — {row.get('status_ar')}"
            for row in details[:3]
        ]
        limitations = [
            "فسّرت كلمة «أكبر» على أنها المساحة المسجلة؛ المساحة لا تعني أن المركز أكثر نشاطًا أو أفضل تشغيليًا.",
            *result.get("limitations", []),
        ] if descending else result.get("limitations", [])
        return _with_warning(summary, facts, {**result, "limitations": limitations}, facts_label="الترتيب")
    matching = snapshot.get("matching_centers")
    selected_regions = result.get("regions", [])
    if selected_regions and len(selected_regions) < 13:
        scope = "المناطق المحددة"
        summary = f"تحتوي لقطة لوجستي الحالية على {_number(matching)} مركزًا مطابقًا في {scope}."
    else:
        summary = (
            f"تحتوي لقطة لوجستي الحالية على {_number(snapshot.get('listed_centers'))} مركزًا مدرجًا: "
            f"{_number(snapshot.get('active_centers'))} مفعّلًا و{_number(snapshot.get('inactive_centers'))} غير مفعّل."
        )
    facts = [
        f"{row.get('region_ar') or row.get('region_en')}: {_number(row.get('total_centers'))} مركزًا "
        f"({_number(row.get('active_centers'))} مفعّلة)"
        for row in rows[:3]
    ]
    facts.append(
        f"الإجمالي الرسمي على مستوى المملكة لعام 2024 يسجل {_number(snapshot.get('official_2024_activated_centers'))} مركزًا مفعّلًا"
    )
    return _with_warning(summary, facts, result, facts_label="أبرز التوزيع")


def _modon_answer(result: dict[str, Any]) -> str:
    snapshot = result.get("snapshot_summary", {})
    details = result.get("details", [])
    active = sum(1 for row in details if row.get("status_en") == "Active")
    inactive = sum(1 for row in details if row.get("status_en") == "Inactive")
    assets = result.get("industrial_assets", [])
    regions = result.get("regions", [])
    rows = result.get("table", [])
    if len(rows) == 2:
        factories_leader = max(rows, key=lambda row: row.get("productive_factories_q4_2023") or 0)
        area_leader = max(rows, key=lambda row: row.get("industrial_city_area_sqm_q2_2024") or 0)
        if factories_leader.get("region_en") == area_leader.get("region_en"):
            summary = f"{factories_leader.get('region_ar') or factories_leader.get('region_en')} أعلى في عدد المصانع المنتجة ومساحة المدن الصناعية ضمن ملفات MODON المتاحة."
        else:
            summary = (
                f"الصورة الصناعية مختلطة: {factories_leader.get('region_ar') or factories_leader.get('region_en')} أعلى في المصانع المنتجة، "
                f"و{area_leader.get('region_ar') or area_leader.get('region_en')} أعلى في مساحة المدن الصناعية."
            )
        facts = [
            f"{row.get('region_ar') or row.get('region_en')}: {_number(row.get('productive_factories_q4_2023'))} مصنعًا منتجًا (الربع الرابع 2023)، "
            f"ومساحة صناعية {_number(row.get('industrial_city_area_sqm_q2_2024'))} متر مربع (الربع الثاني 2024)، "
            f"و{_number(row.get('ready_factory_units_2023'))} وحدة مصنع جاهز"
            for row in rows
        ]
        return _with_warning(summary, facts, result, facts_label="المقارنة الصناعية")

    scope = " في المناطق المحددة" if regions else ""
    summary = (
        f"حوّل نطاق ملفات MODON إلى مؤشرات إقليمية للمصانع المنتجة والمساحات والمصانع الجاهزة، "
        f"إضافة إلى {_number(snapshot.get('matching_centers'))} مركزًا مدرجًا تحت ملكية الهيئة{scope}."
    )
    facts = [
        f"المراكز المدرجة: {_number(len(details))}؛ منها {_number(active)} مفعّل و{_number(inactive)} غير مفعّل",
        f"ملفات MODON المتاحة: {_number(len(assets))}",
        f"المناطق ذات صفوف صناعية قابلة للتجميع: {_number(len(rows))}",
    ]
    return _with_warning(summary, facts, result, facts_label="التغطية المحللة")


def _available_data_answer(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    facts = [
        f"{_number(summary.get('regional_metrics'))} مؤشرًا إقليميًا عبر {_number(summary.get('regions'))} منطقة",
        f"{_number(summary.get('listed_logistics_centers'))} مركزًا لوجستيًا مدرجًا",
        f"{_number(summary.get('mapped_ports'))} ميناءً مربوطًا، منها {_number(summary.get('ports_with_portwatch'))} بسلاسل نشاط شهرية",
    ]
    return _with_warning(
        "تغطي بيانات نطاق مؤشرات المناطق والمراكز اللوجستية والموانئ وMODON والاشتراطات والمنهجيات.",
        facts,
        result,
        facts_label="حجم التغطية",
    )


def _runtime_info_answer(result: dict[str, Any]) -> str:
    info = result.get("runtime_info", {})
    return _with_warning(
        f"أنت تستخدم {info.get('product') or 'نطاق Nitaq'}، والنموذج الأساسي المضبوط حاليًا هو {info.get('configured_primary_model') or 'غير محدد'}.",
        [
            f"تاريخ اليوم في توقيت الرياض: {info.get('current_date_riyadh') or 'غير محدد'}",
            f"النموذج السريع الاحتياطي: {info.get('configured_fast_model') or 'غير محدد'}",
        ],
        result,
        facts_label="معلومات التشغيل",
    )


def _screening_answer(question: str, result: dict[str, Any]) -> str:
    table = result.get("table", [])
    if not table:
        return _with_warning("لم ينتج الفرز الأولي صفوفًا قابلة للعرض.", [], result)
    first = table[0]
    region = first.get("region_ar") or first.get("region_en") or "المنطقة الأولى"
    criteria = result.get("criteria", [])
    facts = [f"{region}: الموضع {_number(first.get('screening_position'))} والنتيجة {_number(first.get('screening_index_0_100'))} من 100"]
    for item in criteria:
        metric_id = item.get("metric_id")
        if not metric_id or metric_id not in first:
            continue
        metadata = next(
            (column for column in result.get("columns", []) if column.get("column") == metric_id),
            {},
        )
        unit = _unit(metadata.get("unit"))
        facts.append(
            f"{metadata.get('label_ar') or metric_id}: {_number(first.get(metric_id))}{f' {unit}' if unit else ''}"
        )
    limitations = [
        "يعتمد الترشيح الافتراضي على وزن 60٪ للطلب و40٪ لحضور المستودعات، ويمكن تغييره حسب أولوياتك.",
        *result.get("limitations", []),
    ]
    normalized_question = normalize_entity_text(question)
    if any(token in normalized_question for token in ("مدينة", "افتح", "أفتح", "موقع")):
        limitations.insert(1, "البيانات رقمية على مستوى المنطقة الإدارية؛ اختيار الموقع داخل المدينة يحتاج بيانات موقعية أدق.")
    return _with_warning(
        f"ترشيحي الأولي هو {region}؛ جاءت في الموضع الأول وفق الطلب وحضور المستودعات في البيانات الحالية.",
        facts,
        {**result, "limitations": limitations},
    )


def _warehouse_decision_answer(result: dict[str, Any]) -> str:
    table = result.get("table", [])
    if not table:
        return _with_warning("لم ينتج تقييم المواقع مرشحين قابلين للمقارنة.", [], result)
    first = table[0]
    candidate = first.get("candidate_ar") or first.get("region_ar") or first.get("candidate_en") or "المرشح الأول"
    facts = [
        f"{candidate}: الموضع {_number(first.get('decision_position'))} ومؤشر نسبي {_number(first.get('decision_index_0_100'))} من 100 ضمن المرشحين الحاليين"
    ]
    metadata = _metadata_map(result)
    for criterion in result.get("criteria", []):
        metric_id = criterion.get("metric_id")
        if metric_id == "port_activity":
            if first.get("mean_monthly_activity") is not None:
                direction = criterion.get("port_direction")
                label = "الواردات البحرية" if direction == "incoming" else "الصادرات البحرية" if direction == "outgoing" else "نشاط الميناء"
                facts.append(f"{label}: متوسط شهري {_number(first.get('mean_monthly_activity'))} بوحدة PortWatch التجريبية")
            continue
        if metric_id not in first:
            continue
        column = metadata.get(metric_id, {})
        unit = _unit(column.get("unit"))
        facts.append(
            f"{column.get('label_ar') or metric_id}: {_number(first.get(metric_id))}{f' {unit}' if unit else ''}"
        )
    include_port = bool((result.get("selection") or {}).get("include_port"))
    basis = "الطلب والبصمة التخزينية ونشاط الميناء المطلوب" if include_port else "الطلب والبصمة التخزينية"
    return _with_warning(
        f"ترشيحي الأولي هو {candidate} وفق {basis} في البيانات الحالية.",
        facts,
        result,
    )


def _missing_data_answer(result: dict[str, Any]) -> str:
    rows = result.get("table", [])
    missing = [row for row in rows if row.get("status") not in {"available", "available_with_caveat"}]
    if not rows:
        return _with_warning("لم تُحدد مفاهيم قرار قابلة للفحص.", [], result)
    labels = [row.get("label_ar") or row.get("concept_id") or "المفهوم المطلوب" for row in missing[:3]]
    summary = (
        "البيانات المطلوبة غير مكتملة لاتخاذ قرار نهائي: " + "، ".join(labels) + "."
        if missing
        else "المؤشرات المطلوبة موجودة، لكنها قد تحمل قيودًا في التعريف أو التغطية."
    )
    facts = [row.get("note_ar") or row.get("note") for row in rows[:2]]
    alternatives = [item.get("label_ar") for item in result.get("alternative_evidence", []) if item.get("label_ar")]
    if alternatives:
        facts.append("بدائل استكشافية متاحة: " + "؛ ".join(alternatives[:3]))
    return _with_warning(
        summary,
        [item for item in facts if item],
        result,
        facts_label="ما نعرفه",
    )


def _metric_source_answer(result: dict[str, Any]) -> str:
    metadata = result.get("metadata", {})
    name = metadata.get("metric_name_ar") or "المؤشر المطلوب"
    definition = metadata.get("definition_ar") or "يتوفر للمؤشر سجل مصدر موثق."
    facts = [
        f"الوحدة {_unit(metadata.get('unit')) or 'غير محددة'}",
        f"الفترة {metadata.get('period') or metadata.get('year') or 'غير محددة'}",
    ]
    return _with_warning(f"تم العثور على تعريف موثق لـ{name}: {definition}", facts, result)


def _validation_answer(result: dict[str, Any]) -> str:
    if result.get("ok"):
        return _with_warning("المقارنة مسموحة بشرط إبراز القيود المرتبطة بالمؤشرات.", [], result)
    messages = [
        item.get("message_ar") or item.get("message")
        for item in result.get("errors", [])
        if item.get("message_ar") or item.get("message")
    ]
    detail = messages[0] if messages else "تحتاج المعايير إلى تعديل قبل المقارنة."
    return _with_warning(f"المقارنة غير صالحة بصورتها الحالية: {detail}", [], result)


def _clean_knowledge_excerpt(text: str) -> str:
    """Repair common PDF extraction artifacts without changing the cited meaning."""
    text = re.sub(r"^[.\s]*(?:\d{1,3}|[٠-٩]{1,3})[.)\-:؛]?\s*(?=[\u0600-\u06FF])", "", text)
    text = re.sub(r"(?<=[\u0600-\u06FF])(?=\d)", " ", text)
    text = re.sub(r"(?<=\d)\s*%\s*", "٪ ", text)
    text = re.sub(r"\s*-\s*(?=\d)", " - ", text)
    text = re.sub(r"\bب\s+(?=\d+(?:[.,]\d+)?٪)", "بنسبة ", text)
    text = re.sub(r"\s+([،؛:.!?؟])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip(" -:؛.")
    text = re.sub(r"\s+(?:من|في|فيها|على|إلى|عن|ثم|التي|حيث)$", "", text).strip()
    return text


def _is_dangling_knowledge_excerpt(text: str) -> bool:
    normalized = normalize_entity_text(text)
    endings = (
        "مع مراعاة", "ويراعى", "على ان", "وفقا ل", "وفق ل", "بما في ذلك",
        "subject to", "including", "in accordance with", "provided that",
    )
    return any(normalized.endswith(normalize_entity_text(ending)) for ending in endings)


def _knowledge_answer(question: str, result: dict[str, Any]) -> str:
    rows = result.get("table", [])
    if not rows:
        return "لم أعثر على مقطع معتمد يجيب عن السؤال."
    normalized_question = normalize_entity_text(question)
    requirements_query = any(
        token in normalized_question
        for token in ("اشتراط", "شروط", "متطلبات", "لائحة", "احتاج", "ابني", "أبني", "بناء", "انشاء", "إنشاء")
    )
    preferred_tokens = (
        ("يجب", "الالتزام", "يشترط", "يلزم")
        if requirements_query
        else ("يقصد بمصطلح", "المستودعات هي", "مستودع ", "مخصص لتخزين")
    )
    stop_words = {"ما", "هي", "هو", "وش", "عن", "في", "من", "على", "لي", "اللوجستية"}
    query_terms = {
        word[:6]
        for word in normalized_question.split()
        if len(word) >= 4 and word not in stop_words
    }
    candidates: list[tuple[int, str, str]] = []
    for row in rows:
        raw = str(row.get("text") or "")
        raw = re.sub(r"https?://\S+", " ", raw)
        raw = re.sub(r"[#*_]+", " ", raw)
        raw = re.sub(r"[\r\n]+", "\n", raw).replace("•", "\n")
        for segment in re.split(r"(?<=[.!؟])\s+|\n+", raw):
            segment = _clean_knowledge_excerpt(segment)
            latin = len(re.findall(r"[A-Za-z]", segment))
            arabic = len(re.findall(r"[\u0600-\u06FF]", segment))
            if (
                len(segment) < 45
                or len(segment) > 420
                or segment.isdigit()
                or segment.endswith("؟")
                or _is_dangling_knowledge_excerpt(segment)
                or latin > arabic * 2
            ):
                continue
            normalized_segment = normalize_entity_text(segment)
            relevance = sum(4 for term in query_terms if term in normalized_segment)
            preferred = sum(10 for token in preferred_tokens if token in segment)
            specificity = 14 if requirements_query and re.search(r"\d|[٪%]", segment) else 0
            readability = min(segment.count(" "), 12)
            ocr_penalty = 12 if len(segment) > 100 and segment.count(" ") / len(segment) < 0.06 else 0
            conciseness = 4 if len(segment) <= 180 else 0
            category = "general"
            if requirements_query:
                category_groups = (
                    ("safety", ("سلامة", "حريق", "إخلاء", "طفايات", "إسعاف", "طوارئ")),
                    ("loading", ("تحميل", "تفريغ", "شاحن", "مناورة", "رصيف")),
                    ("operation", ("تشغيل", "نظافة", "نفايات", "عاملين", "تدريب")),
                    ("site", ("موقع", "ارتداد", "مخصصة", "صناعية")),
                    ("design", ("مساحة", "فتحات", "واجهات", "أسطح", "مكاتب")),
                )
                category = next(
                    (name for name, tokens in category_groups if any(token in segment for token in tokens)),
                    "general",
                )
            candidates.append((relevance + preferred + specificity + readability + conciseness - ocr_penalty, segment, category))
    unique: dict[str, tuple[int, str]] = {}
    for score, segment, category in candidates:
        if segment not in unique or score > unique[segment][0]:
            unique[segment] = (score, category)
    ranked = sorted(((score, segment, category) for segment, (score, category) in unique.items()), reverse=True)
    snippets: list[str] = []
    seen_categories: set[str] = set()
    if requirements_query:
        design_anchor = next(
            (
                (segment, category)
                for _, segment, category in ranked
                if re.search(r"25\s*٪", segment) and "فتحات" in segment
            ),
            None,
        )
        if design_anchor:
            snippets.append(design_anchor[0])
            seen_categories.add(design_anchor[1])
    for _, segment, category in ranked:
        if segment in snippets:
            continue
        if requirements_query and category in seen_categories and len(seen_categories) < 3:
            continue
        snippets.append(segment)
        seen_categories.add(category)
        if len(snippets) == 3:
            break
    if len(snippets) < 3:
        for _, segment, _ in ranked:
            if segment not in snippets:
                snippets.append(segment)
            if len(snippets) == 3:
                break
    if not snippets:
        text = _clean_knowledge_excerpt(str(rows[0].get("text") or ""))
        latin = len(re.findall(r"[A-Za-z]", text))
        arabic = len(re.findall(r"[\u0600-\u06FF]", text))
        if text and len(text) <= 420 and not _is_dangling_knowledge_excerpt(text) and latin <= arabic * 2:
            snippets = [text]
        elif latin > arabic * 2:
            return "عُثر على مقاطع معتمدة باللغة الإنجليزية. في الوضع المتصل يترجم نطاق معناها إلى العربية مع إبقاء الصفحة والمصدر الأصليين في لوحة الأدلة."
        else:
            return "وجدت صفحات مرتبطة بالسؤال، لكن المقاطع المستخرجة غير مكتملة بما يكفي لعرضها كاشتراط موثوق. راجع المصدر في قسم الأدلة."
    lead = "تلخص الوثائق المعتمدة الإجابة في النقاط التالية:"
    return f"**الخلاصة:** {lead}\n\n" + "\n".join(f"- {item}" for item in snippets)


def _generic_answer(result: dict[str, Any]) -> str:
    rows = result.get("table", [])
    if not rows:
        return _with_warning("اكتمل الفحص، ولم تُرجع البيانات صفوفًا إضافية.", [], result)
    return _with_warning(f"اكتمل الفحص وعُثر على {_number(len(rows))} نتيجة.", [], result)


def _english_region(result: dict[str, Any], canonical: str | None) -> str:
    if not canonical:
        return "the region"
    for row in result.get("table", []):
        if row.get("region_en") == canonical:
            return row.get("candidate_en") or row.get("region_en") or canonical
    return canonical


def _english_location(result: dict[str, Any], location: str | None) -> str:
    if not location:
        return "the port"
    for port in result.get("ports", []):
        if location in {port.get("portwatch_location"), port.get("port_code"), port.get("port_name_en")}:
            return port.get("port_name_en") or location
    return location


def _knowledge_answer_en(result: dict[str, Any]) -> str:
    rows = result.get("table", [])
    if not rows:
        return "I could not find an approved passage that answers the question."
    candidates: list[str] = []
    for row in rows:
        raw = re.sub(r"https?://\S+|[#*_]+", " ", str(row.get("text") or ""))
        raw = re.sub(r"[\r\n]+", " ", raw).replace("•", ". ")
        for segment in re.split(r"(?<=[.!?])\s+", raw):
            segment = re.sub(r"\s+", " ", segment).strip(" -:;.")
            latin = len(re.findall(r"[A-Za-z]", segment))
            arabic = len(re.findall(r"[\u0600-\u06FF]", segment))
            if len(segment) >= 45 and latin > arabic * 2:
                candidates.append(segment[:260].rsplit(" ", 1)[0] + "…" if len(segment) > 260 else segment)
    unique = list(dict.fromkeys(candidates))[:3]
    if not unique:
        return (
            "**Summary:** The approved matching passages are in Arabic. In connected mode, Nitaq translates and summarizes them in English while preserving the cited page."
        )
    return "**Summary:** The approved documents support these points:\n\n" + "\n".join(f"- {item}" for item in unique)


def _official_web_answer(result: dict[str, Any], language: str) -> str:
    rows = result.get("table", [])
    if not rows:
        return (
            "No usable current result was found on the allowlisted official sites; the local evidence remains the fallback."
            if language == "en"
            else "لم أجد نتيجة حديثة قابلة للاستخدام في المواقع الرسمية المسموحة؛ لذلك يبقى الدليل المحلي هو البديل المتاح."
        )
    items: list[str] = []
    for row in rows[:3]:
        title = re.sub(r"\s+", " ", str(row.get("title") or row.get("agency") or "Official source")).strip()
        url = str(row.get("source_url") or "")
        published = row.get("published_date")
        accessed = row.get("access_date")
        if language == "en":
            date_note = f"published {published}; " if published else ""
            date_note += f"accessed {accessed}"
        else:
            date_note = f"نُشر {published}؛ " if published else ""
            date_note += f"تاريخ الوصول {accessed}"
        items.append(f"- [{title}]({url}) — {date_note}")
    lead = (
        "The current official-web check found the following relevant sources:"
        if language == "en"
        else "أظهر فحص الويب الرسمي الحالي المصادر المرتبطة التالية:"
    )
    return lead + "\n\n" + "\n".join(items)


def _combined_decision_research_answer(
    question: str,
    decision: dict[str, Any],
    knowledge: dict[str, Any] | None,
    web: dict[str, Any] | None,
    language: str,
) -> str:
    decision_answer = _compose_english(decision) if language == "en" else _warehouse_decision_answer(decision)
    sections = [decision_answer]
    if knowledge and knowledge.get("table"):
        research = _knowledge_answer_en(knowledge) if language == "en" else _knowledge_answer(question, knowledge)
        heading = "**Document evidence:**" if language == "en" else "**الدليل من الوثائق:**"
        sections.append(f"{heading}\n{research}")
    if web and web.get("table"):
        heading = "**Current official sources:**" if language == "en" else "**المصادر الرسمية الحديثة:**"
        sections.append(f"{heading}\n{_official_web_answer(web, language)}")
    return "\n\n".join(sections)


def _warehouse_setup_combined_answer(
    question: str,
    knowledge: dict[str, Any],
    regional: dict[str, Any],
    language: str,
) -> str:
    """Deterministic safety fallback for a requirements + regional-context answer."""
    if language == "en":
        knowledge_answer = _knowledge_answer_en(knowledge)
        requirements = knowledge_answer.split("\n\n", 1)[-1]
        if regional.get("tool") == "get_region_profile":
            region = regional.get("region", {}).get("region_en") or "the selected region"
            row = (regional.get("table") or [{}])[0]
            context = (
                f"Population {_number(row.get('population_2024'))}; "
                f"completed delivery requests {_number(row.get('delivery_total_2024_source'))}; "
                f"licensed warehouses {_number(row.get('warehouse_count_2024'))}."
            )
        else:
            region = "the selected regions"
            context = "The attached regional comparison provides the available demand and warehouse-footprint context."
        return (
            f"**Summary:** To plan a warehouse in {region}, start with the approved technical and operating requirements, "
            "then test the location against the available regional demand and warehouse footprint.\n\n"
            f"**Requirements from the documents:**\n{requirements}\n\n"
            f"**Regional context:** {context}\n\n"
            "**Caveat:** This is an exploratory evidence brief; site cost, occupancy, capacity, and parcel-level feasibility still require separate validation."
        )

    knowledge_answer = _knowledge_answer(question, knowledge)
    requirements = knowledge_answer.split("\n\n", 1)[-1]
    if regional.get("tool") == "get_region_profile":
        region = regional.get("region", {}).get("region_ar") or regional.get("region", {}).get("region_en") or "المنطقة المحددة"
        row = (regional.get("table") or [{}])[0]
        context = (
            f"السكان {_number(row.get('population_2024'))} نسمة؛ "
            f"طلبات التوصيل {_number(row.get('delivery_total_2024_source'))} طلبًا منفذًا؛ "
            f"المستودعات المرخصة {_number(row.get('warehouse_count_2024'))} مستودعًا."
        )
    else:
        region = "المناطق المحددة"
        context = "تعرض المقارنة المرفقة سياق الطلب والبصمة التخزينية المتاح للمناطق المحددة."
    return (
        f"**الخلاصة:** للتخطيط لمستودع في {region}، ابدأ بالاشتراطات الفنية والتشغيلية المعتمدة، "
        "ثم اختبر الموقع مقابل الطلب والبصمة التخزينية المتاحة للمنطقة.\n\n"
        f"**الاشتراطات من الوثائق:**\n{requirements}\n\n"
        f"**سياق المنطقة:** {context}\n\n"
        "**تنبيه:** هذه قراءة استكشافية؛ ما زالت تكلفة الموقع والإشغال والسعة والجدوى على مستوى قطعة الأرض بحاجة إلى تحقق مستقل."
    )


def _compose_english(result: dict[str, Any]) -> str:
    tool = result.get("tool")
    table = result.get("table", [])
    if tool == "evaluate_warehouse_locations":
        if not table:
            return _with_warning_en("The available evidence did not produce comparable candidates.", [], result)
        first = table[0]
        candidate = first.get("candidate_en") or first.get("region_en") or "the leading candidate"
        facts = [
            f"{candidate} ranks #{_number(first.get('decision_position'))} with a relative index of {_number(first.get('decision_index_0_100'))}/100 within the current candidates"
        ]
        metadata = _metadata_map(result)
        for criterion in result.get("criteria", []):
            metric_id = criterion.get("metric_id")
            if metric_id == "port_activity":
                if first.get("mean_monthly_activity") is not None:
                    direction = criterion.get("port_direction")
                    label = "Inbound port activity" if direction == "incoming" else "Outbound port activity" if direction == "outgoing" else "Port activity"
                    facts.append(f"{label}: {_number(first.get('mean_monthly_activity'))} mean monthly experimental units")
                continue
            if metric_id not in first:
                continue
            column = metadata.get(metric_id, {})
            unit = _unit_en(column.get("unit"))
            facts.append(f"{column.get('label_en') or metric_id}: {_number(first.get(metric_id))}{f' {unit}' if unit else ''}")
        basis = "demand, warehouse footprint, and the requested port signal" if (result.get("selection") or {}).get("include_port") else "demand and warehouse footprint"
        return _with_warning_en(f"My initial recommendation is {candidate} under the current {basis} evidence.", facts, result)

    if tool == "compare_regions":
        differences = result.get("pairwise_differences", [])
        if differences:
            requested = result.get("requested_metric_ids") or result.get("metric_ids") or []
            selected = [item for item in differences if item.get("metric_id") in requested] or [_primary_difference(differences)]
            first = selected[0].get("first_region")
            second = selected[0].get("second_region")
            first_wins = sum(item.get("higher_region") == first for item in selected)
            second_wins = sum(item.get("higher_region") == second for item in selected)
            if len(selected) > 1 and first_wins and second_wins:
                summary = f"The comparison is mixed: {_english_region(result, first)} is numerically higher on {first_wins} direct indicators and {_english_region(result, second)} on {second_wins}; no composite winner score was created."
            else:
                primary = selected[0]
                higher = primary.get("higher_region")
                other = second if higher == first else first
                metric = primary.get("metric_name_en") or str(primary.get("metric_id") or "selected metric").replace("_", " ")
                summary = f"{_english_region(result, higher)} is higher than {_english_region(result, other)} for {metric}." if higher else f"The candidates are equal for {metric}."
            facts = []
            for item in selected[:3]:
                unit = _unit_en(item.get("unit"))
                metric = item.get("metric_name_en") or str(item.get("metric_id") or "indicator").replace("_", " ")
                facts.append(
                    f"{metric}: {_english_region(result, item.get('first_region'))} {_number(item.get('first_value'))} versus "
                    f"{_english_region(result, item.get('second_region'))} {_number(item.get('second_value'))}{f' {unit}' if unit else ''}"
                )
            return _with_warning_en(summary, facts, result)
        metric_id, metadata = _primary_table_metric(result)
        rows = [row for row in table if metric_id and isinstance(row.get(metric_id), (int, float))]
        if not rows:
            return _with_warning_en("The comparison completed, but no numeric values were available.", [], result)
        ranked = sorted(rows, key=lambda row: row[metric_id], reverse=True)
        metric = metadata.get("label_en") or str(metric_id).replace("_", " ")
        unit = _unit_en(metadata.get("unit"))
        values = ", ".join(f"{row.get('region_en')}: {_number(row.get(metric_id))}" for row in ranked[:3])
        return _with_warning_en(
            f"{ranked[0].get('region_en')} leads the selected regions for {metric}.",
            [f"Top values: {values}{f' {unit}' if unit else ''}"],
            result,
        )

    if tool == "get_indicator_trend":
        rows = result.get("trend_summary", [])
        if not rows:
            return _with_warning_en("There are not enough observations to describe a trend.", [], result)
        facts = []
        for row in rows[:3]:
            change = row.get("percent_change")
            direction = "increased" if isinstance(change, (int, float)) and change > 0 else "decreased" if change else "was unchanged"
            facts.append(
                f"{row.get('region_en')}: {_number(row.get('first_value'))} in {row.get('first_period')} to {_number(row.get('last_value'))} in {row.get('last_period')} ({direction} {_number(abs(change or 0))}%)"
            )
        return _with_warning_en("The documented trend has been calculated for the selected regions.", facts, result)

    if tool in {"compare_ports", "get_port_context"}:
        differences = result.get("pairwise_differences", [])
        if differences:
            primary = _primary_difference(differences)
            higher = _english_location(result, primary.get("higher_location"))
            metric = (result.get("selection") or {}).get("metric")
            label = "trade activity" if metric == "trade_volume" else "vessel-call activity"
            fact = (
                f"Mean monthly activity: {_english_location(result, primary.get('first_location'))} {_number(primary.get('first_value'))} versus "
                f"{_english_location(result, primary.get('second_location'))} {_number(primary.get('second_value'))}; gap {_number(primary.get('absolute_gap'))}"
            )
            return _with_warning_en(f"{higher} recorded the higher comparable {label}.", [fact], result)
        names = ", ".join(port.get("port_name_en") or "port" for port in result.get("ports", []))
        coverage = result.get("coverage_summary", {})
        facts = []
        if names:
            facts = [
                f"Coverage: {_number(coverage.get('ports_with_portwatch'))} of {_number(coverage.get('mapped_ports'))} mapped ports",
                f"Monthly series: {coverage.get('series_start') or 'not specified'} to {coverage.get('series_end') or 'not specified'}",
            ]
        return _with_warning_en(f"Comparable maritime context was retrieved for {names}." if names else "No maritime coverage is available for this selection.", facts, result)

    if tool == "compare_logistics_gateways":
        if not table:
            return _with_warning_en("No comparable maritime and logistics-center signals were available.", [], result)
        facts = [
            f"{row.get('region_en')}: {_number(row.get('mean_monthly_port_activity'))} mean monthly experimental maritime units; "
            f"{_number(row.get('current_listed_centers'))} currently listed centers ({_number(row.get('current_active_centers'))} active)"
            for row in table[:3]
        ]
        return _with_warning_en(
            "Observed maritime activity and logistics-center presence were compared as separate axes; no composite winner score was created.",
            facts,
            result,
            facts_label="Compared axes",
        )

    if tool == "get_region_profile":
        region = result.get("region", {})
        row = table[0] if table else {}
        return _with_warning_en(
            f"This is the available 2024 logistics profile for {region.get('region_en') or 'the selected region'}.",
            [
                f"Population: {_number(row.get('population_2024'))}",
                f"Completed delivery requests: {_number(row.get('delivery_total_2024_source'))}",
                f"Licensed warehouses: {_number(row.get('warehouse_count_2024'))}",
            ],
            result,
        )

    if tool == "list_logistics_centers":
        snapshot = result.get("snapshot_summary", {})
        rows = result.get("table", [])
        details = result.get("details", [])
        selection = result.get("selection", {})
        if selection.get("sort_by") in {"area_desc", "area_asc"} and details:
            descending = selection.get("sort_by") == "area_desc"
            facts = [
                f"{row.get('center_name_ar')}: {_number(row.get('area_sqm_reconciled'))} m² — {row.get('region_en_derived')} — {row.get('status_en')}"
                for row in details[:3]
            ]
            limitations = [
                "Largest is interpreted as recorded area; area does not measure activity or operating quality.",
                *result.get("limitations_en", []),
            ] if descending else result.get("limitations_en", [])
            return _with_warning_en(
                f"These are the {'largest' if descending else 'smallest'} {_number(len(details))} centers by recorded area in the current Logisti snapshot.",
                facts,
                {**result, "limitations_en": limitations},
                facts_label="Ranking",
            )
        if result.get("regions") and len(result.get("regions", [])) < 13:
            summary = f"The current Logisti snapshot contains {_number(snapshot.get('matching_centers'))} matching listed centers in the selected regions."
        else:
            summary = (
                f"The current Logisti snapshot lists {_number(snapshot.get('listed_centers'))} centers: "
                f"{_number(snapshot.get('active_centers'))} active and {_number(snapshot.get('inactive_centers'))} inactive."
            )
        facts = [
            f"{row.get('region_en')}: {_number(row.get('total_centers'))} listed ({_number(row.get('active_centers'))} active)"
            for row in rows[:3]
        ]
        facts.append(f"Nationwide official activated-center total for 2024: {_number(snapshot.get('official_2024_activated_centers'))}")
        return _with_warning_en(summary, facts, result, facts_label="Leading distribution")

    if tool == "get_modon_context":
        snapshot = result.get("snapshot_summary", {})
        details = result.get("details", [])
        active = sum(1 for row in details if row.get("status_en") == "Active")
        if len(table) == 2:
            facts = [
                f"{row.get('region_en')}: {_number(row.get('productive_factories_q4_2023'))} productive factories (2023 Q4), "
                f"{_number(row.get('industrial_city_area_sqm_q2_2024'))} m² of industrial-city area (2024 Q2), "
                f"and {_number(row.get('ready_factory_units_2023'))} ready-factory units"
                for row in table
            ]
            return _with_warning_en(
                "The selected regions were compared using normalized MODON workbook evidence; the indicators remain separate because their periods and meanings differ.",
                facts,
                result,
                facts_label="Industrial comparison",
            )
        return _with_warning_en(
            "Nitaq normalized the available MODON workbooks into regional factory, industrial-area, and ready-factory indicators.",
            [
                f"Listed MODON-owned centers: {_number(len(details))}; {_number(active)} active",
                f"Available MODON workbooks: {_number(len(result.get('industrial_assets', [])))}",
                f"Regions with mapped industrial rows: {_number(len(table))}",
            ],
            result,
            facts_label="Analyzed coverage",
        )

    if tool == "describe_available_data":
        summary = result.get("summary", {})
        return _with_warning_en(
            "Nitaq currently covers regional indicators, listed logistics centers, ports, MODON context, requirements, and methodologies.",
            [
                f"{_number(summary.get('regional_metrics'))} regional indicators across {_number(summary.get('regions'))} regions",
                f"{_number(summary.get('listed_logistics_centers'))} listed logistics centers",
                f"{_number(summary.get('mapped_ports'))} mapped ports; {_number(summary.get('ports_with_portwatch'))} with monthly activity series",
            ],
            result,
            facts_label="Coverage size",
        )

    if tool == "get_runtime_info":
        info = result.get("runtime_info", {})
        return _with_warning_en(
            f"You are using {info.get('product') or 'Nitaq'}, currently configured with {info.get('configured_primary_model') or 'an unspecified primary model'}.",
            [
                f"Current Riyadh date: {info.get('current_date_riyadh') or 'not specified'}",
                f"Configured fast fallback model: {info.get('configured_fast_model') or 'not specified'}",
            ],
            result,
            facts_label="Runtime information",
        )

    if tool == "screen_regions":
        if not table:
            return _with_warning_en("The screening returned no comparable rows.", [], result)
        first = table[0]
        return _with_warning_en(
            f"The initial screening leader is {first.get('region_en')} under the current weights.",
            [f"Rank #{_number(first.get('screening_position'))}; index {_number(first.get('screening_index_0_100'))}/100"],
            result,
        )

    if tool == "search_knowledge":
        return _knowledge_answer_en(result)
    if tool == "search_official_web":
        return _official_web_answer(result, "en")
    if tool == "identify_missing_data":
        missing = [row for row in table if row.get("status") not in {"available", "available_with_caveat"}]
        labels = [str(row.get("label_en") or row.get("concept_id") or "requested evidence").replace("_", " ") for row in missing[:3]]
        facts = [row.get("note_en") for row in table[:2] if row.get("note_en")]
        alternatives = [item.get("label_en") for item in result.get("alternative_evidence", []) if item.get("label_en")]
        if alternatives:
            facts.append("Available exploratory alternatives: " + "; ".join(alternatives[:3]))
        return _with_warning_en(
            "The evidence is incomplete for a final decision" + (f": {', '.join(labels)}." if labels else "."),
            facts,
            result,
            facts_label="What is known",
        )
    if tool == "get_metric_source":
        metadata = result.get("metadata", {})
        name = metadata.get("metric_name_en") or "the requested metric"
        return _with_warning_en(
            f"A documented source record is available for {name}.",
            [f"Unit: {_unit_en(metadata.get('unit')) or 'not specified'}", f"Period: {metadata.get('period') or metadata.get('year') or 'not specified'}"],
            result,
        )
    if tool == "validate_comparison":
        return _with_warning_en(
            "The comparison is allowed with its metric limitations displayed." if result.get("ok") else "The comparison needs revised candidates or metrics.",
            [],
            result,
        )
    return _with_warning_en(f"The analysis returned {_number(len(table))} result(s).", [], result)


def compose_evidence_answer(
    question: str,
    results: list[dict[str, Any]],
    language: str | None = None,
) -> str:
    """Build a concise, result-driven answer without tables, sources, or internal tool names."""
    successful = [
        result
        for result in results
        if result.get("ok") or result.get("tool") == "validate_comparison"
    ]
    resolved_language = normalize_language(language or detect_language(question))
    if not successful:
        return (
            "The analysis could not be completed with the current input. Clarify the location or indicator and try again."
            if resolved_language == "en"
            else "تعذر إكمال التحليل بالمدخلات الحالية. وضّح المنطقة أو المؤشر المطلوب ثم أعد المحاولة."
        )
    knowledge_result = next((item for item in successful if item.get("tool") == "search_knowledge"), None)
    web_result = next((item for item in successful if item.get("tool") == "search_official_web"), None)
    decision_result = next(
        (item for item in successful if item.get("tool") in {"evaluate_warehouse_locations", "screen_regions"}),
        None,
    )
    regional_result = next(
        (item for item in reversed(successful) if item.get("tool") in {"get_region_profile", "compare_regions"}),
        None,
    )
    if knowledge_result and regional_result:
        return _warehouse_setup_combined_answer(
            question,
            knowledge_result,
            regional_result,
            resolved_language,
        )
    if decision_result and (knowledge_result or web_result):
        return _combined_decision_research_answer(
            question,
            decision_result,
            knowledge_result,
            web_result,
            resolved_language,
        )
    if web_result and knowledge_result:
        document_answer = _knowledge_answer_en(knowledge_result) if resolved_language == "en" else _knowledge_answer(question, knowledge_result)
        return document_answer + "\n\n" + _official_web_answer(web_result, resolved_language)
    result = successful[-1]
    if resolved_language == "en":
        return _compose_english(result)
    tool = result.get("tool")
    if tool == "compare_regions":
        return _comparison_answer(question, result)
    if tool == "get_indicator_trend":
        return _trend_answer(result)
    if tool in {"get_port_context", "compare_ports"}:
        return _ports_answer(result)
    if tool == "compare_logistics_gateways":
        return _gateway_answer(result)
    if tool == "get_region_profile":
        return _profile_answer(result)
    if tool == "list_logistics_centers":
        return _logistics_centers_answer(result)
    if tool == "get_modon_context":
        return _modon_answer(result)
    if tool == "describe_available_data":
        return _available_data_answer(result)
    if tool == "get_runtime_info":
        return _runtime_info_answer(result)
    if tool == "screen_regions":
        return _screening_answer(question, result)
    if tool == "evaluate_warehouse_locations":
        return _warehouse_decision_answer(result)
    if tool == "identify_missing_data":
        return _missing_data_answer(result)
    if tool == "get_metric_source":
        return _metric_source_answer(result)
    if tool == "validate_comparison":
        return _validation_answer(result)
    if tool == "search_knowledge":
        return _knowledge_answer(question, result)
    if tool == "search_official_web":
        return _official_web_answer(result, "ar")
    return _generic_answer(result)


def summary_matches_primary_higher(answer: str, results: list[dict[str, Any]]) -> bool:
    """Verify that the entity named before 'أعلى' matches Python's primary comparison result."""
    successful = [result for result in results if result.get("ok")]
    if not successful:
        return True
    result = successful[-1]
    differences = result.get("pairwise_differences", [])
    if not differences:
        return True
    primary = _primary_difference(differences)
    higher = primary.get("higher_region") or primary.get("higher_location")
    if not higher:
        return True
    expected = _region_label(result, higher) if primary.get("higher_region") else _location_label(result, higher)
    expected_aliases = {str(expected), str(higher)}
    if primary.get("higher_region"):
        for row in result.get("table", []):
            if row.get("region_en") == higher:
                expected_aliases.update(
                    str(row.get(key))
                    for key in ("region_ar", "region_en", "candidate", "candidate_ar", "candidate_en")
                    if row.get(key)
                )
    normalized_answer = normalize_entity_text(answer)
    markers = tuple(
        normalize_entity_text(item)
        for item in ("أعلى", "أكبر", "يتصدر", "يتفوق", "أكثر", "higher", "leads", "highest")
    )
    marker = next((item for item in markers if item in normalized_answer), None)
    if not marker:
        return True
    before_marker = normalized_answer.split(marker, 1)[0]
    return any(normalize_entity_text(alias) in before_marker for alias in expected_aliases if alias)


def missing_required_entities(answer: str, results: list[dict[str, Any]]) -> list[str]:
    """Return comparison/trend entities omitted by the user-facing summary."""
    successful = [result for result in results if result.get("ok")]
    if not successful:
        return []
    result = successful[-1]
    tool = result.get("tool")
    normalized_answer = normalize_entity_text(answer)
    required_groups: list[tuple[str, list[str]]] = []
    if tool in {"compare_regions", "get_indicator_trend"}:
        seen: set[str] = set()
        for row in result.get("table", []):
            canonical = row.get("region_en")
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            required_groups.append((canonical, [canonical, row.get("region_ar")]))
    elif tool == "compare_ports":
        for port in result.get("ports", []):
            label = port.get("port_code") or port.get("port_name_en")
            required_groups.append(
                (
                    label,
                    [
                        port.get("port_code"),
                        port.get("port_name_en"),
                        port.get("port_name_ar"),
                        port.get("portwatch_location"),
                    ],
                )
            )
    elif tool in {"screen_regions", "evaluate_warehouse_locations"} and result.get("table"):
        first = result["table"][0]
        required_groups.append(
            (
                first.get("region_en") or "top_region",
                [
                    first.get("region_en"),
                    first.get("region_ar"),
                    first.get("candidate_en"),
                    first.get("candidate_ar"),
                ],
            )
        )
    missing: list[str] = []
    for label, aliases in required_groups:
        normalized_aliases = [normalize_entity_text(alias) for alias in aliases if alias]
        if not any(alias and alias in normalized_answer for alias in normalized_aliases):
            missing.append(str(label))
    return missing
