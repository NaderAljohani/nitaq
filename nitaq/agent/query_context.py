from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..tools.entities import (
    extract_port_mentions,
    extract_region_mentions,
    normalize_entity_text,
)

from .i18n import detect_language


ALL_REGIONS = [
    "Riyadh",
    "Makkah",
    "Madinah",
    "Qassim",
    "Eastern Region",
    "Aseer",
    "Tabuk",
    "Hail",
    "Northern Borders",
    "Jazan",
    "Najran",
    "Al-Baha",
    "Al-Jouf",
]

PORT_WORDS = (
    "ميناء", "موانئ", "مينا", "بحري", "واردات", "صادرات",
    "port", "ports", "seaport", "maritime", "shipping", "imports", "exports", "throughput",
)
TREND_WORDS = (
    "اتجاه", "تغير", "تطور", "ربع", "زمني", "نمو",
    "trend", "change", "growth", "quarter", "quarterly", "over time",
)
COMPARE_WORDS = (
    "قارن", "مقارنة", "فرق", "فروقات", "الفرق", "مقابل", "بين",
    "compare", "comparison", "difference", "versus", " vs ",
)
STRONG_COMPARE_WORDS = (
    "قارن", "مقارنة", "فرق", "فروقات", "الفرق", "مقابل",
    "compare", "comparison", "difference", "versus", " vs ",
)
COMPREHENSIVE_COMPARE_WORDS = (
    "جميع المعايير", "كل المعايير", "جميع المؤشرات", "كل المؤشرات", "من جميع النواحي", "من كل النواحي",
    "all criteria", "all metrics", "every metric", "across all indicators", "comprehensive comparison",
)
PROFILE_WORDS = ("ملف", "نبذة", "وضع", "ملخص", "نظرة", "profile", "overview", "summary", "situation")
SOURCE_WORDS = ("مصدر", "جدول", "وحدة المؤشر", "source", "provenance", "data source")
KNOWLEDGE_WORDS = (
    "تعريف", "منهج", "اشتراط", "شروط", "متطلبات", "لائحة", "دليل", "سياسة", "تقرير",
    "methodology", "requirement", "requirements", "regulation", "regulations", "rules", "guide", "policy", "definition",
)
REGULATORY_WORDS = (
    "منهج", "اشتراط", "شروط", "متطلبات", "لائحة", "لوائح", "دليل فني", "سياسة", "تقرير رسمي",
    "ترخيص", "التزامات", "عقوبات", "مخالفة", "وثيقة الشحن", "عقد الشحن", "الوساطة", "نظامي",
    "حدود استخدام", "قيود استخدام", "نطاق استخدام",
    "methodology", "requirement", "requirements", "regulation", "regulations", "rules", "technical guide", "policy",
    "license", "licensing", "obligation", "obligations", "penalty", "penalties", "shipping document", "freight brokerage",
)
DEFINITION_CUES = (
    "ما هي", "ماهي", "ما هو", "ماهو", "وش معنى", "ما المقصود", "ماذا يعني", "تعريف", "عرف لي", "عرّف لي", "اشرح لي",
    "what is", "what are", "define", "explain",
)
MISSING_WORDS = (
    "تكلفة", "إيجار", "ايجار", "إشغال", "اشغال", "سعة", "منافس", "ربحية", "ميزانية", "sla",
    "cost", "rent", "occupancy", "capacity", "competition", "profitability", "budget", "service level",
)
SCREEN_WORDS = (
    "رتب", "أولوية", "أفضل", "افضل", "انسب", "أنسب", "رشح", "ترشيح", "توسع", "افتح", "أفتح", "اختار", "اختيار", "تنصح", "نصيحة",
    "قرار", "best", "recommend", "recommendation", "decision", "rank", "ranking", "choose", "select", "advise", "where should", "open a warehouse", "warehouse location",
)
VALIDATE_WORDS = (
    "عادلة", "صالحة للمقارنة", "تحقق من المقارنة", "valid comparison", "comparable", "fair comparison",
)
FOLLOWUP_WORDS = (
    "أضف", "اضف", "أيضا", "ايضا", "كذلك", "نفس", "هذا", "هذه", "هذي", "بينهما", "عليها", "عنه", "عنها", "وماذا", "طيب", "الحين",
    "add", "also", "include", "same", "those", "them", "what about", "now", "then", "next",
)
CENTER_LIST_WORDS = (
    "أين", "اين", "توجد", "مواقع", "الحالية", "حاليا", "قائمة", "عدد", "59", "جميع المناطق", "كل المناطق",
    "أكبر", "اكبر", "أصغر", "اصغر", "الأكبر", "الاكبر", "top",
    "where", "location", "locations", "current", "list", "listed", "all regions", "largest", "smallest", "biggest",
)
PORT_COVERAGE_WORDS = (
    "عندك عنها بيانات", "متوفر عنها", "متوفرة عنها", "تغطية", "قائمة الموانئ", "ماهي الموانئ", "ما هي الموانئ",
    "available ports", "ports do you have", "port coverage", "which ports",
)
AVAILABLE_DATA_WORDS = (
    "البيانات المتوفرة", "البيانات المتاحة", "وش عندك بيانات", "ما عندك من بيانات", "مصادر بياناتك", "تغطية البيانات",
    "كل البيانات", "وش البيانات اللي تقدر", "ما البيانات التي تستطيع", "available data", "data available",
    "what data do you have", "all the data", "what data can you use", "data coverage", "supported data",
    "describe all datasets", "available datasets", "datasets available",
    "what data can nitaq analyze", "what can nitaq analyze",
)
RUNTIME_INFO_WORDS = (
    "النموذج الحالي", "وش النموذج", "ما هو النموذج", "ماهو النموذج", "تاريخ اليوم", "كم التاريخ", "وش التاريخ",
    "current model", "what model", "today date", "today's date", "current date",
)
GENERAL_EXPLANATION_CUES = (
    "بشكل عام", "بصورة عامة", "اشرح", "وضح مفهوم", "كيف احسن", "كيف أحسن", "كيف يعمل",
    "ما الفرق بين", "وش الفرق بين", "الفرق بين", "in general", "explain", "how does", "how can i improve",
    "what does", "difference between",
)
PRODUCT_INFO_WORDS = (
    "ماهو نطاق", "ما هو نطاق", "وش هو نطاق", "وش نطاق", "من هو نطاق", "عرف نطاق", "عرّف نطاق",
    "من انت", "من أنت", "عرف بنفسك", "عرّف بنفسك",
    "what is nitaq", "who is nitaq", "who are you", "tell me about nitaq",
)
WAREHOUSE_SETUP_WORDS = (
    "ابني", "أبني", "بناء", "انشاء", "إنشاء", "اشتراط", "شروط", "متطلبات",
    "وش احتاج", "وش أحتاج", "ماذا احتاج", "ماذا أحتاج", "كيف ابدا", "كيف أبدأ", "لازم",
    "build a warehouse", "set up a warehouse", "warehouse setup", "warehouse requirements", "what do i need",
)
INDUSTRIAL_CONTEXT_WORDS = (
    "modon", "هيئة مدن", "مدن الصناعية", "المدن الصناعية", "مدينة صناعية", "منطقة صناعية", "المناطق الصناعية",
    "مصانع", "مصنع", "الصناعيه", "المدن الصناعيه", "مدينة صناعيه", "industrial city", "industrial cities", "industrial area", "factories",
)
REGIONAL_TOOLS = {
    "get_region_profile", "compare_regions", "screen_regions", "evaluate_warehouse_locations",
    "get_indicator_trend", "validate_comparison", "list_logistics_centers", "get_modon_context",
    "compare_logistics_gateways",
}
PORT_TOOLS = {"get_port_context", "compare_ports"}


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _has_word(text: str, terms: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"(?<![\w\u0600-\u06FF]){re.escape(term)}(?![\w\u0600-\u06FF])", text)
        for term in terms
    )


def _is_clear_followup(text: str) -> bool:
    words = text.split()
    return _has_any(text, FOLLOWUP_WORDS) or ("بين" in words and len(words) <= 7)


def _metric_hints(text: str) -> list[str]:
    hints: list[str] = []
    if _has_any(text, ("توصيل", "delivery", "demand")) or _has_word(text, ("طلبات", "طلب")):
        hints.append("delivery_total_2024_source")
    if _has_any(text, ("مساحة المستود", "مساحات المستود", "مساحة المخازن", "warehouse area", "storage area")):
        hints.append("warehouse_area_sqm_2024")
    elif _has_any(text, ("مستودع", "مستودعات", "مخزن", "مخازن", "warehouse", "warehouses")):
        hints.append("warehouse_count_2024")
    if _has_any(text, ("ترخيص", "تراخيص", "freight", "license", "licenses")) or re.search(r"(?<![\u0600-\u06FF])بريد(?![\u0600-\u06FF])", text):
        hints.append("freight_post_licenses_2024")
    if _has_any(text, ("مركز لوجستي", "مراكز لوجستية", "logistics center", "logistics centers")):
        hints.append("activated_logistics_centers_2024")
    if _has_any(text, ("سكان", "population")):
        hints.append("population_2024")
    return list(dict.fromkeys(hints))


def _trend_indicator(text: str) -> str | None:
    if _has_any(text, ("توصيل", "delivery")) or _has_word(text, ("طلبات", "طلب")):
        return "delivery_requests"
    if _has_any(text, ("مساحة المستود", "مساحة المخازن", "warehouse area")):
        return "warehouse_area"
    if _has_any(text, ("مستودع", "مستودعات", "مخزن", "مخازن", "warehouse")):
        return "warehouse_count"
    if _has_any(text, ("ترخيص", "تراخيص", "license")) or re.search(r"(?<![\u0600-\u06FF])بريد(?![\u0600-\u06FF])", text):
        return "freight_post_licenses"
    if _has_any(text, ("مركز لوجستي", "مراكز لوجستية", "logistics center")):
        return "activated_logistics_centers"
    if _has_any(text, ("سكان", "population")):
        return "population"
    return None


def _port_signal(text: str) -> tuple[str | None, str | None]:
    if _has_any(text, ("واردات", "وارد", "استيراد", "imports", "import", "incoming", "inbound")):
        return "trade_volume", "incoming"
    if _has_any(text, ("صادرات", "صادر", "تصدير", "exports", "export", "outgoing", "outbound")):
        return "trade_volume", "outgoing"
    if _has_any(text, ("حجم التجارة", "حجم الميناء", "حمولة", "مناولة", "trade volume", "throughput", "cargo volume")):
        return "trade_volume", None
    if _has_any(text, ("زيارة", "زيارات", "سفن", "calls", "vessel", "ship visits")):
        return "calls", "port"
    return None, None


def _mentions_all_regions(text: str) -> bool:
    return bool(
        re.search(r"(?:13|thirteen|الـ?13|الثلاث(?:ة|ه) عشر)\s+(?:منطقة|مناطق|region)", text)
        or _has_any(text, ("جميع المناطق", "كل المناطق", "كافة المناطق", "all regions", "every region"))
    )


@dataclass
class QueryContext:
    normalized_question: str
    language: str = "ar"
    current_regions: list[str] = field(default_factory=list)
    current_ports: list[str] = field(default_factory=list)
    geography_notes: list[str] = field(default_factory=list)
    metric_hints: list[str] = field(default_factory=list)
    trend_indicator: str | None = None
    port_metric: str | None = None
    port_direction: str | None = None
    decision_goal: str | None = None
    warehouse_setup: bool = False
    product_identity: bool = False
    comprehensive_comparison: bool = False
    intent_family: str = "general_knowledge"
    complexity: str = "simple"
    topic: str = "logistics_general"
    topic_changed: bool = False
    evidence_mode: str = "model_knowledge"
    general_knowledge: bool = False
    intent_hint: str | None = None
    requires_tool: bool = False
    incomplete: bool = False
    retains_previous_context: bool = False

    def to_prompt_dict(self, previous: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {
            "response_language": self.language,
            "previous_successful_context": (previous or {}) if self.retains_previous_context else {},
            "current_explicit_entities": {
                "regions": self.current_regions,
                "ports": self.current_ports,
                "geography_notes": self.geography_notes,
                "metric_hints": self.metric_hints,
                "trend_indicator": self.trend_indicator,
                "port_metric": self.port_metric,
                "port_direction": self.port_direction,
            },
            "decision_goal": self.decision_goal,
            "warehouse_setup": self.warehouse_setup,
            "product_identity": self.product_identity,
            "comprehensive_comparison": self.comprehensive_comparison,
            "intent_family": self.intent_family,
            "complexity": self.complexity,
            "topic": self.topic,
            "topic_changed": self.topic_changed,
            "evidence_mode": self.evidence_mode,
            "general_knowledge": self.general_knowledge,
            "intent_hint": self.intent_hint,
            "requires_tool": self.requires_tool,
            "retains_previous_context": self.retains_previous_context,
            "context_rule": "Current explicit entities override prior candidates. Keep prior goal, candidates and metric only for a genuine follow-up. A changed topic starts a fresh intent.",
        }
        if self.intent_hint in {"screen_regions", "evaluate_warehouse_locations"}:
            payload["default_decision_policy"] = {
                "use_when": "The user requests an open-ended warehouse-location recommendation without custom criteria.",
                "regional_criteria": default_screening_arguments()["criteria"],
                "port_policy": "Use inbound trade volume only when every named candidate has a comparable mapped PortWatch series.",
                "interpretation_ar": "ترشيح استكشافي يوازن الطلب والبصمة التخزينية، ويضيف نشاط الميناء فقط عند طلبه وبين مرشحين قابلين للمقارنة.",
                "interpretation_en": "An exploratory recommendation balancing demand and warehouse footprint, with port activity added only when requested and comparable.",
            }
        if self.warehouse_setup:
            payload["required_evidence"] = [
                "approved warehouse requirements from search_knowledge",
                *(["regional operating context from get_region_profile"] if self.current_regions else []),
            ]
            payload["planning_instruction"] = (
                "Preserve the warehouse-setup goal. Retrieve every required evidence category before answering, "
                "then connect requirements with the selected region without presenting a final investment guarantee."
            )
        return payload


def default_screening_arguments() -> dict[str, Any]:
    return {
        "criteria": [
            {"metric_id": "delivery_requests_per_1000_population_2024", "direction": "higher", "weight": 0.6},
            {"metric_id": "warehouse_area_sqm_per_capita_2024", "direction": "higher", "weight": 0.4},
        ],
        "top_n": 5,
    }


def default_warehouse_decision_arguments() -> dict[str, Any]:
    return {
        "regional_criteria": default_screening_arguments()["criteria"],
        "top_n": 5,
    }


def analyse_query(question: str, previous: dict[str, Any] | None = None) -> QueryContext:
    normalized = normalize_entity_text(question)
    normalized = re.sub(r"\bwarehous\b", "warehouse", normalized)
    normalized = re.sub(r"\breqirements?\b", "requirements", normalized)
    previous = previous or {}
    previous_tool = previous.get("last_tool")
    previous_goal = previous.get("goal")
    language = detect_language(question, previous.get("language"))
    clear_followup = _is_clear_followup(normalized)
    region_mentions = extract_region_mentions(question)
    all_port_mentions = extract_port_mentions(question)
    metric_hints = _metric_hints(normalized)
    regions = list(dict.fromkeys(item.canonical for item in region_mentions))
    if _mentions_all_regions(normalized):
        regions = list(ALL_REGIONS)
    explicit_port_topic = _has_any(normalized, PORT_WORDS)
    explicit_warehouse_topic = _has_any(normalized, ("مستودع", "مستودعات", "مخزن", "مخازن", "warehouse", "warehouses", "warehousing"))
    explicit_center_topic = _has_any(
        normalized,
        ("مركز لوجستي", "مراكز لوجستية", "المراكز اللوجستية", "المراكز", "مراكز", "logistics center", "logistics centers"),
    )
    explicit_center_listing = explicit_center_topic and _has_any(normalized, CENTER_LIST_WORDS)
    explicit_industrial_context = _has_any(normalized, INDUSTRIAL_CONTEXT_WORDS)
    explicit_port_coverage = explicit_port_topic and _has_any(normalized, PORT_COVERAGE_WORDS)
    explicit_available_data = _has_any(normalized, AVAILABLE_DATA_WORDS)
    explicit_runtime_info = _has_any(normalized, RUNTIME_INFO_WORDS)
    explicit_product_info = _has_any(normalized, PRODUCT_INFO_WORDS)
    explicit_definition = _has_any(normalized, DEFINITION_CUES)
    explicit_general_explanation = _has_any(normalized, GENERAL_EXPLANATION_CUES)
    non_generic_regions = [
        mention
        for mention in region_mentions
        if normalize_entity_text(mention.text) not in {"المدينة", "المدينه"}
    ]
    conceptual_relationship = bool(
        (normalized.startswith("هل ") or normalized.startswith("does ") or normalized.startswith("is "))
        and _has_any(normalized, ("يعني", "معناه", "necessarily mean", "does it mean"))
        and not non_generic_regions
    )
    if conceptual_relationship:
        explicit_general_explanation = True
    explicit_regulatory_topic = _has_any(normalized, REGULATORY_WORDS)
    # Definitions and explanatory questions are model-knowledge questions by
    # default.  Only an explicit regulatory/methodology cue forces document
    # retrieval.  This prevents ordinary logistics questions from being sent
    # to an unrelated PDF merely because they begin with "ما هو".
    explicit_knowledge_topic = explicit_regulatory_topic
    wms_general_question = bool(
        _has_any(normalized, ("نظام ادارة مستودع", "نظام إدارة مستودع", "warehouse management system", " wms "))
        and not regions
    )
    explicit_decision = bool(
        _has_any(normalized, SCREEN_WORDS)
        and not wms_general_question
        and not (explicit_general_explanation and not regions and _has_any(normalized, ("بشكل عام", "بصورة عامة", "in general")))
    )
    if wms_general_question:
        explicit_general_explanation = True
    if (explicit_definition or explicit_general_explanation) and not explicit_regulatory_topic and not regions:
        metric_hints = []
    warehouse_setup = bool(explicit_warehouse_topic and _has_any(normalized, WAREHOUSE_SETUP_WORDS))
    explicit_strong_compare = _has_any(normalized, STRONG_COMPARE_WORDS)
    comprehensive_comparison = _has_any(normalized, COMPREHENSIVE_COMPARE_WORDS)
    gateway_comparison = bool(
        (explicit_port_topic and explicit_center_topic)
        or _has_any(normalized, ("بوابات لوجستية", "البوابات اللوجستية", "logistics gateway", "logistics gateways"))
    )
    regional_selection_continuation = bool(
        previous_goal == "warehouse_location"
        and regions
        and len(normalized.split()) <= 4
        and not metric_hints
        and not explicit_industrial_context
    )
    location_goal_continuation = previous_goal == "warehouse_location" and not (explicit_strong_compare and not explicit_decision) and (
        explicit_decision
        or explicit_port_topic
        or regional_selection_continuation
        or (clear_followup and not metric_hints and not explicit_industrial_context)
    )
    setup_goal_continuation = bool(
        previous_goal == "warehouse_setup"
        and (warehouse_setup or regions or clear_followup)
        and not explicit_strong_compare
        and not explicit_product_info
        and not explicit_runtime_info
    )
    goal_continuation = location_goal_continuation or setup_goal_continuation
    port_comparison_continuation = bool(
        previous_tool in PORT_TOOLS
        and explicit_strong_compare
        and not regions
        and (explicit_available_data or clear_followup)
    )
    retains_previous_context = bool(
        previous
        and (
            clear_followup
            or goal_continuation
            or (gateway_comparison and previous.get("regions"))
            or port_comparison_continuation
        )
    )
    port_topic_switch = bool(
        explicit_port_topic
        and explicit_strong_compare
        and previous_tool not in PORT_TOOLS
        and not explicit_decision
        and not region_mentions
    )
    if port_topic_switch:
        retains_previous_context = False
    if explicit_knowledge_topic and not clear_followup and not (explicit_center_listing or explicit_industrial_context or explicit_decision):
        retains_previous_context = False

    if explicit_product_info:
        topic = "product"
    elif explicit_runtime_info:
        topic = "runtime"
    elif explicit_port_topic and not goal_continuation:
        topic = "ports"
    elif explicit_center_topic:
        topic = "logistics_centers"
    elif explicit_industrial_context:
        topic = "industrial_logistics"
    elif explicit_warehouse_topic:
        topic = "warehousing"
    elif (explicit_definition or explicit_general_explanation) and not explicit_regulatory_topic:
        topic = "logistics_general"
    elif regions or metric_hints or _has_any(normalized, TREND_WORDS + COMPARE_WORDS):
        topic = "regional_analytics"
    else:
        topic = "logistics_general"
    previous_topic = str(previous.get("topic") or "")
    if (
        clear_followup
        and topic == "logistics_general"
        and previous_topic
        and not explicit_definition
        and not explicit_general_explanation
        and not explicit_regulatory_topic
    ):
        topic = previous_topic
    topic_changed = bool(
        previous_topic
        and previous_topic != topic
        and not goal_continuation
        and not (gateway_comparison and previous.get("regions"))
    )
    # Explicit topic evidence wins over generic follow-up words such as "طيب"
    # or "الحين".  A true warehouse-location goal may still add a port signal.
    if topic_changed:
        retains_previous_context = False

    ports = list(dict.fromkeys(item.canonical for item in all_port_mentions)) if (explicit_port_topic or explicit_decision or goal_continuation) else []
    if retains_previous_context:
        if not regions:
            regions = list(previous.get("regions") or [])
        if not ports:
            ports = list(previous.get("ports") or [])
    if location_goal_continuation and explicit_port_topic and previous.get("regions"):
        # A port city mentioned while adding a maritime signal identifies the
        # port; it must not replace the decision candidates already in memory.
        regions = list(previous.get("regions") or [])
    warehouse_after_ports = bool(
        clear_followup
        and previous_tool in PORT_TOOLS
        and explicit_warehouse_topic
        and not explicit_decision
    )
    if warehouse_after_ports:
        regions = list(previous.get("port_regions") or [])
        ports = []
        retains_previous_context = bool(regions)

    geography_notes: list[str] = []
    for item in region_mentions:
        if item.text in {"جدة", "مدينة جدة", "jeddah", "الدمام", "dammam", "مدينة الرياض", "riyadh city"}:
            geography_notes.append(f"{item.text} is a city; regional evidence resolves it to {item.canonical}.")

    port_metric, port_direction = _port_signal(normalized)
    if retains_previous_context:
        port_metric = port_metric or previous.get("port_metric")
        port_direction = port_direction or previous.get("port_direction")

    single_site_setup = bool(
        (warehouse_setup or setup_goal_continuation)
        and len(regions) == 1
        and not _has_any(normalized, ("أفضل", "افضل", "أنسب", "انسب", "قارن", "مقارنة", "best", "recommend between", "compare"))
    )
    if single_site_setup:
        decision_goal = "warehouse_setup"
    elif explicit_decision or location_goal_continuation:
        decision_goal = "warehouse_location"
    elif warehouse_setup or setup_goal_continuation:
        decision_goal = "warehouse_setup"
    else:
        decision_goal = None
    intent: str | None = None
    if _has_any(normalized, VALIDATE_WORDS) and not decision_goal:
        intent = "validate_comparison"
    elif explicit_product_info:
        intent = None
    elif explicit_runtime_info:
        intent = "get_runtime_info"
    elif explicit_industrial_context:
        intent = "get_modon_context"
    elif gateway_comparison and (len(regions) >= 2 or clear_followup or previous.get("regions")):
        intent = "compare_logistics_gateways"
    elif decision_goal == "warehouse_location":
        intent = "evaluate_warehouse_locations"
    elif decision_goal == "warehouse_setup":
        intent = "search_knowledge"
    elif explicit_center_listing:
        intent = "list_logistics_centers"
    elif explicit_port_coverage:
        intent = "get_port_context"
    elif port_comparison_continuation or (explicit_port_topic and explicit_strong_compare):
        intent = "compare_ports"
    elif explicit_available_data and not (explicit_strong_compare and len(regions) >= 2):
        intent = "describe_available_data"
    elif regions and _has_any(normalized, PROFILE_WORDS):
        intent = "compare_regions" if len(regions) > 1 else "get_region_profile"
    elif explicit_knowledge_topic:
        intent = "search_knowledge"
    elif _has_any(normalized, MISSING_WORDS):
        intent = "identify_missing_data"
    elif _has_any(normalized, SOURCE_WORDS):
        intent = "get_metric_source"
    elif warehouse_after_ports:
        intent = "compare_regions" if len(regions) >= 2 else None
    elif explicit_port_topic and (len(ports) >= 2 or explicit_strong_compare):
        intent = "compare_ports"
    elif explicit_port_topic:
        intent = "get_port_context"
    elif retains_previous_context and previous_tool in PORT_TOOLS:
        intent = previous_tool
    elif _has_any(normalized, TREND_WORDS):
        intent = "get_indicator_trend"
    elif _has_any(normalized, COMPARE_WORDS) and len(regions) >= 2:
        if clear_followup and previous_tool in REGIONAL_TOOLS and not _has_any(normalized, STRONG_COMPARE_WORDS):
            intent = previous_tool
        else:
            intent = "compare_regions"
    elif metric_hints and len(regions) >= 2:
        intent = "compare_regions"
    elif metric_hints and len(regions) == 1:
        intent = "get_region_profile"
    elif regions and _has_any(normalized, PROFILE_WORDS):
        intent = "compare_regions" if len(regions) > 1 else "get_region_profile"
    elif len(regions) >= 2:
        intent = previous_tool if clear_followup and previous_tool in REGIONAL_TOOLS else "compare_regions"
    elif regions:
        intent = previous_tool if clear_followup and previous_tool in REGIONAL_TOOLS else "get_region_profile"
    elif retains_previous_context and previous_tool:
        intent = previous_tool

    if conceptual_relationship:
        intent = None
        decision_goal = None
        metric_hints = []
        regions = []
        ports = []

    truncated_stems = ("منط", "مناط", "مقار", "مينا", "مؤش", "مستود")
    incomplete = len(normalized) < 3 or any(normalized.endswith(stem) for stem in truncated_stems)
    general_knowledge = bool(
        not intent
        and not regions
        and not ports
        and not explicit_product_info
        and not explicit_runtime_info
        and (explicit_definition or explicit_general_explanation or not metric_hints)
    )
    requires_tool = bool((intent or regions or ports) and not explicit_product_info and not general_knowledge)
    if decision_goal == "warehouse_location":
        intent_family = "recommendation"
    elif warehouse_setup or explicit_regulatory_topic:
        intent_family = "regulatory"
    elif explicit_product_info or explicit_runtime_info:
        intent_family = "conversation"
    elif requires_tool:
        intent_family = "analytics"
    else:
        intent_family = "general_knowledge"
    complexity = "compound" if warehouse_setup and regions or gateway_comparison or comprehensive_comparison else "tool" if requires_tool else "simple"
    evidence_mode = {
        "recommendation": "analytics_plus_documents_if_needed",
        "regulatory": "approved_documents",
        "analytics": "deterministic_tools",
        "conversation": "runtime_or_product_identity",
        "general_knowledge": "model_knowledge",
    }[intent_family]
    return QueryContext(
        normalized_question=normalized,
        language=language,
        current_regions=regions,
        current_ports=ports,
        geography_notes=list(dict.fromkeys(geography_notes)),
        metric_hints=metric_hints,
        trend_indicator=_trend_indicator(normalized),
        port_metric=port_metric,
        port_direction=port_direction,
        decision_goal=decision_goal,
        warehouse_setup=warehouse_setup or setup_goal_continuation,
        product_identity=explicit_product_info,
        comprehensive_comparison=comprehensive_comparison,
        intent_family=intent_family,
        complexity=complexity,
        topic=topic,
        topic_changed=topic_changed,
        evidence_mode=evidence_mode,
        general_knowledge=general_knowledge,
        intent_hint=intent,
        requires_tool=requires_tool,
        incomplete=incomplete,
        retains_previous_context=retains_previous_context,
    )


def tool_names_for_query(query: QueryContext) -> list[str]:
    """Return a compact capability set, not a hard-coded final route.

    ``intent_hint`` is a deterministic safety/fallback hint.  The online LLM
    planner receives adjacent capabilities for analytical and decision
    questions so it can choose a better tool or combine evidence.  General
    knowledge stays tool-free.
    """
    if query.general_knowledge or query.product_identity:
        return []
    if query.warehouse_setup and query.intent_family != "recommendation":
        names = ["search_knowledge"]
        if len(query.current_regions) == 1:
            names.append("get_region_profile")
        elif len(query.current_regions) > 1:
            names.append("compare_regions")
        return names
    if query.intent_family == "recommendation":
        return [
            "evaluate_warehouse_locations",
            "search_knowledge",
            "get_region_profile",
            "compare_regions",
            "compare_logistics_gateways",
            "identify_missing_data",
        ]
    if query.intent_family == "regulatory":
        return ["search_knowledge"]
    if query.intent_hint:
        adjacent = {
            "compare_regions": ["compare_regions", "get_region_profile", "get_indicator_trend", "validate_comparison"],
            "get_region_profile": ["get_region_profile", "compare_regions", "get_indicator_trend"],
            "get_indicator_trend": ["get_indicator_trend", "compare_regions", "get_region_profile"],
            "compare_ports": ["compare_ports", "get_port_context", "compare_logistics_gateways"],
            "get_port_context": ["get_port_context", "compare_ports", "compare_logistics_gateways"],
        }
        return adjacent.get(query.intent_hint, [query.intent_hint])
    return [
        "get_region_profile",
        "compare_regions",
        "evaluate_warehouse_locations",
        "get_indicator_trend",
        "get_port_context",
        "compare_ports",
        "compare_logistics_gateways",
        "get_metric_source",
        "validate_comparison",
        "identify_missing_data",
        "list_logistics_centers",
        "get_modon_context",
        "describe_available_data",
        "get_runtime_info",
        "search_knowledge",
    ]


def context_from_results(
    previous: dict[str, Any] | None,
    query: QueryContext,
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    successful = [result for result in results if result.get("ok")]
    base = dict(previous or {}) if query.retains_previous_context else {}
    base["language"] = query.language
    base["intent_family"] = query.intent_family
    base["topic"] = query.topic
    base["complexity"] = query.complexity
    base["evidence_mode"] = query.evidence_mode
    base["topic_changed"] = query.topic_changed
    if query.intent_hint:
        base["last_intent"] = query.intent_hint
    else:
        base.pop("last_intent", None)
    if query.intent_hint in {"compare_regions", "compare_logistics_gateways", "get_modon_context"} and not query.decision_goal:
        base.pop("goal", None)
    if query.decision_goal:
        base["goal"] = query.decision_goal
    if query.current_regions:
        base["regions"] = list(query.current_regions)
    if query.current_ports:
        base["ports"] = list(query.current_ports)
    if query.metric_hints:
        base["metric_ids"] = list(query.metric_hints)
    if query.trend_indicator:
        base["indicator"] = query.trend_indicator
    if query.port_metric:
        base["port_metric"] = query.port_metric
    if query.port_direction:
        base["port_direction"] = query.port_direction
    if not successful:
        return base

    last = successful[-1]
    base["last_tool"] = last.get("tool")
    if last.get("regions"):
        base["regions"] = last["regions"]
    elif last.get("region"):
        region = last["region"]
        base["regions"] = [region.get("region_en") if isinstance(region, dict) else region]
    if last.get("indicator"):
        base["indicator"] = last["indicator"]
    if last.get("metric_ids"):
        base["metric_ids"] = last["metric_ids"]
    if last.get("ports"):
        codes = [item.get("port_code") for item in last["ports"] if item.get("port_code")]
        if codes:
            base["ports"] = codes
        base["port_regions"] = list(dict.fromkeys(item.get("region_en") for item in last["ports"] if item.get("region_en")))
    selection = last.get("selection") or {}
    if selection.get("metric"):
        base["port_metric"] = selection["metric"]
    if selection.get("port_metric"):
        base["port_metric"] = selection["port_metric"]
    if selection.get("direction"):
        base["port_direction"] = selection["direction"]
    if selection.get("port_direction"):
        base["port_direction"] = selection["port_direction"]
    if last.get("tool") == "evaluate_warehouse_locations":
        base["goal"] = "warehouse_location"
    return base
