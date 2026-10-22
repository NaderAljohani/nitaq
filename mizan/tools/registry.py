from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from . import (
    compare_ports,
    compare_logistics_gateways,
    compare_regions,
    describe_available_data,
    evaluate_warehouse_locations,
    get_indicator_trend,
    get_modon_context,
    get_metric_source,
    get_port_context,
    get_region_profile,
    identify_missing_data,
    list_logistics_centers,
    screen_regions,
    validate_comparison,
)
from .exceptions import MizanError

from ..rag import OfficialWebResearch, RAGRetriever
from ..agent.config import AgentConfig


REGIONS = [
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

RAW_METRICS = [
    "population_2023",
    "population_2024",
    "delivery_q1_2024",
    "delivery_q2_2024",
    "delivery_q3_2024",
    "delivery_q4_2024",
    "delivery_total_2024_source",
    "warehouse_count_2023",
    "warehouse_area_sqm_2023",
    "warehouse_count_2024",
    "warehouse_area_sqm_2024",
    "freight_post_licenses_2023",
    "freight_post_licenses_2024",
    "activated_logistics_centers_2023",
    "activated_logistics_centers_2024",
    "activated_logistics_centers_area_sqm_2023",
    "activated_logistics_centers_area_sqm_2024",
]

DERIVED_METRICS = [
    "delivery_requests_per_1000_population_2024",
    "warehouse_count_per_100k_population_2024",
    "warehouse_area_sqm_per_capita_2024",
    "warehouse_area_sqm_per_capita_2023",
    "freight_post_licenses_per_100k_population_2024",
    "activated_logistics_centers_per_million_population_2024",
    "population_growth_pct",
    "delivery_q4_vs_q1_growth_pct",
    "warehouse_count_growth_pct",
    "warehouse_area_growth_pct",
    "freight_post_licenses_growth_pct",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegionProfileArgs(StrictModel):
    region: str = Field(description="One Saudi administrative region, Arabic alias or canonical English name.")


class CompareRegionsArgs(StrictModel):
    regions: list[str] = Field(min_length=2, max_length=13, description="Two or more Saudi regions.")
    metric_ids: list[str] | None = Field(
        default=None,
        description="Approved metric IDs. Omit to use the documented descriptive default; never invent IDs.",
    )


class ScreeningCriterion(StrictModel):
    metric_id: str
    direction: str = Field(pattern="^(higher|lower)$")
    weight: float = Field(gt=0)


class ScreenRegionsArgs(StrictModel):
    criteria: list[ScreeningCriterion] = Field(
        min_length=2,
        max_length=2,
        description="Exactly demand per 1,000 plus one warehouse footprint metric; user must supply priorities.",
    )
    top_n: int = Field(default=5, ge=1, le=13)
    sensitivity_delta: float = Field(default=0.1, ge=0, le=0.5)


class WarehouseDecisionArgs(StrictModel):
    locations: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=13,
        description="One or more candidate cities or administrative regions. A single candidate yields a profile-like provisional score, not a comparative winner; omit to evaluate all 13 regions.",
    )
    regional_criteria: list[ScreeningCriterion] | None = Field(
        default=None,
        min_length=2,
        max_length=4,
        description="Runtime criteria. Omit for the transparent demand-plus-warehouse-footprint baseline.",
    )
    ports: list[str] | None = Field(
        default=None,
        min_length=2,
        max_length=13,
        description="Mapped ports aligned with coastal candidates when port activity is requested.",
    )
    include_port: bool = False
    port_metric: str = Field(default="trade_volume", pattern="^(calls|trade_volume)$")
    port_direction: str | None = Field(default="incoming", pattern="^(incoming|outgoing|port)$")
    port_weight: float = Field(default=0.25, gt=0, lt=1)
    top_n: int = Field(default=5, ge=1, le=13)


class TrendArgs(StrictModel):
    regions: list[str] = Field(min_length=1, max_length=13)
    indicator: str = Field(
        description="One of population, delivery_requests, warehouse_count, warehouse_area, freight_post_licenses, activated_logistics_centers, activated_logistics_centers_area."
    )


class PortArgs(StrictModel):
    port: str | None = None
    region: str | None = None
    start: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    end: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    metric: str = Field(default="calls", pattern="^(calls|trade_volume)$")
    direction: str | None = None


class ComparePortsArgs(StrictModel):
    ports: list[str] | None = Field(
        default=None,
        min_length=2,
        max_length=6,
        description=(
            "Two or more port names/codes. City aliases such as Jeddah and Dammam are accepted. "
            "Omit this field when the user asks to compare every port with a comparable available series."
        ),
    )
    start: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    end: str | None = Field(default=None, description="ISO date YYYY-MM-DD")
    metric: str = Field(default="calls", pattern="^(calls|trade_volume)$")
    direction: str | None = None


class LogisticsGatewayArgs(StrictModel):
    regions: list[str] = Field(min_length=2, max_length=13)
    ports: list[str] | None = Field(default=None, min_length=2, max_length=6)
    port_metric: str = Field(default="trade_volume", pattern="^(calls|trade_volume)$")
    port_direction: str | None = Field(default="incoming", pattern="^(incoming|outgoing|port)$")


class MetricSourceArgs(StrictModel):
    metric_id: str


class ValidateArgs(StrictModel):
    regions: list[str] = Field(min_length=1, max_length=13)
    metric_ids: list[str] = Field(min_length=1)
    purpose: str = Field(default="comparison", pattern="^(comparison|screening)$")


class MissingDataArgs(StrictModel):
    requested_concepts: list[str] | None = None


class SearchKnowledgeArgs(StrictModel):
    query: str = Field(min_length=3, max_length=1_000)
    top_k: int = Field(default=5, ge=1, le=8)
    language: str | None = Field(default=None, pattern="^(ar|en)$")


class OfficialWebSearchArgs(StrictModel):
    query: str = Field(min_length=3, max_length=500)
    max_results: int = Field(default=5, ge=1, le=6)
    language: str = Field(default="ar", pattern="^(ar|en)$")


class LogisticsCentersArgs(StrictModel):
    regions: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=13,
        description="Optional administrative-region filter. Omit to summarize the complete current listing.",
    )
    status: str = Field(default="all", pattern="^(all|active|inactive)$")
    owner: str | None = Field(default=None, max_length=200)
    sort_by: str = Field(default="regional_distribution", pattern="^(regional_distribution|area_desc|area_asc)$")
    limit: int | None = Field(default=None, ge=1, le=59)


class ModonContextArgs(StrictModel):
    regions: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=13,
        description="Optional regions carried from the current question or a genuine follow-up.",
    )


class AvailableDataArgs(StrictModel):
    pass


class RuntimeInfoArgs(StrictModel):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    args_model: type[StrictModel]
    function: Callable[..., dict[str, Any]]

    def llm_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


def _search_knowledge(
    retriever: RAGRetriever,
    query: str,
    top_k: int = 5,
    language: str | None = None,
) -> dict[str, Any]:
    results = retriever.search(query, top_k=top_k, language=language, merge_adjacent=True)
    # A tiny lexical match can otherwise make an unrelated PDF look authoritative
    # (for example, interpreting "What is Mizan?" as a warehouse definition).
    # Keep the threshold deliberately low so genuine short Arabic questions survive.
    results = [
        item
        for item in results
        if item.get("metadata", {}).get("citation_verified")
        and float(item.get("relevance_confidence") or 0) >= 0.08
    ]
    answerable = bool(results and float(results[0].get("relevance_confidence") or 0) >= 0.12)
    if not answerable:
        results = []
    table = [
        {
            "chunk_id": item["chunk_id"],
            "text": item["text"],
            "score": item["score"],
            "retrieval_score": item.get("retrieval_score"),
            "semantic_score": item.get("semantic_score"),
            "relevance_confidence": item.get("relevance_confidence"),
            "citation_label": item["citation_label"],
            **{
                key: item["metadata"].get(key)
                for key in (
                    "source_id",
                    "title_ar",
                    "agency",
                    "year",
                    "page_start",
                    "page_end",
                    "document_type",
                    "source_url",
                    "source_path",
                    "limitation_ar",
                    "heading",
                    "section_type",
                    "extraction_method",
                    "citation_verified",
                )
            },
        }
        for item in results
    ]
    return {
        "ok": True,
        "tool": "search_knowledge",
        "query": query,
        "answerable": answerable,
        "table": table,
        "citations": [
            {
                "chunk_id": row["chunk_id"],
                "citation_label": row["citation_label"],
                "source_id": row["source_id"],
                "title_ar": row["title_ar"],
                "heading": row.get("heading"),
                "agency": row["agency"],
                "year": row["year"],
                "page_start": row["page_start"],
                "page_end": row["page_end"],
                "source_url": row["source_url"],
                "source_path": row["source_path"],
            }
            for row in table
        ],
        "sources": [
            {
                "source_id": row["source_id"],
                "agency": row["agency"],
                "year": row["year"],
                "source_url": row["source_url"],
                "source_path": row["source_path"],
            }
            for row in table
        ],
        "limitations": list(dict.fromkeys(row["limitation_ar"] for row in table if row["limitation_ar"])),
        "limitations_en": [
            "Retrieved passages may come from Arabic or English source documents; citations point to the original wording."
        ],
        "missing_data_notes": [
            "لم يُعثر على Chunk مطابق؛ لا تُنشئ تعريفًا أو قيدًا من الذاكرة."
            if not table
            else "استُخدم بحث هجين BM25 ومتجهات متعددة اللغات ثم إعادة ترتيب واعية بالسؤال؛ كل مقطع اجتاز حد الصلة والتحقق من المصدر والصفحة."
        ],
        "missing_data_notes_en": [
            "No matching approved passage was found; do not invent a definition or requirement."
            if not table
            else "Hybrid BM25 and multilingual vector retrieval with question-aware re-ranking was used; every passage passed relevance and citation checks."
        ],
        "numeric_policy": "لا تستخدم RAG لإجابة رقمية إقليمية؛ استدعِ أداة Python المناسبة.",
    }


def _get_runtime_info() -> dict[str, Any]:
    config = AgentConfig.from_env()
    today = datetime.now(ZoneInfo("Asia/Riyadh")).date().isoformat()
    return {
        "ok": True,
        "tool": "get_runtime_info",
        "runtime_info": {
            "product": "ميزان Mizan",
            "configured_primary_model": config.primary_model,
            "configured_fast_model": config.fast_model,
            "current_date_riyadh": today,
            "timezone": "Asia/Riyadh",
        },
        "table": [],
        "sources": [],
        "limitations": ["اسم النموذج يعكس إعداد التطبيق الحالي وقد يتغير إذا تغيرت إعدادات التشغيل."],
        "limitations_en": ["The model name reflects the current app configuration and may change when runtime settings change."],
        "missing_data_notes": [],
        "missing_data_notes_en": [],
    }


class ToolRegistry:
    def __init__(self, retriever: RAGRetriever, web_research: OfficialWebResearch | None = None):
        self.retriever = retriever
        self.web_research = web_research or OfficialWebResearch()
        self.definitions: dict[str, ToolDefinition] = {
            "get_region_profile": ToolDefinition(
                "get_region_profile",
                "Get documented raw and population-normalized evidence for one Saudi administrative region. City aliases are resolved to their containing region (for example Jeddah to Makkah and Dammam to Eastern Region); disclose that conversion. Never claim investment suitability.",
                RegionProfileArgs,
                get_region_profile,
            ),
            "compare_regions": ToolDefinition(
                "compare_regions",
                "Compare two or more administrative regions without ranking. City aliases are resolved to their containing region. Returns raw and normalized values plus Python-calculated pairwise differences when exactly two regions are selected.",
                CompareRegionsArgs,
                compare_regions,
            ),
            "screen_regions": ToolDefinition(
                "screen_regions",
                "Run a conditional two-signal regional screening. Use the user's priorities when stated; for an open-ended recommendation use the transparent default policy supplied in structured context. Requires demand per 1,000 and exactly one warehouse footprint metric.",
                ScreenRegionsArgs,
                screen_regions,
            ),
            "evaluate_warehouse_locations": ToolDefinition(
                "evaluate_warehouse_locations",
                "Evaluate warehouse-location candidates at runtime using transparent regional criteria. Use for best, recommended, or open-a-warehouse questions. Add port activity only when requested and every named candidate has comparable mapped coverage. This is dynamic analysis, not a stored recommendation.",
                WarehouseDecisionArgs,
                evaluate_warehouse_locations,
            ),
            "get_indicator_trend": ToolDefinition(
                "get_indicator_trend",
                "Get a documented annual or quarterly trend for selected administrative regions, accepting city aliases and returning Python-calculated trend summaries. Do not call two annual points a forecast.",
                TrendArgs,
                get_indicator_trend,
            ),
            "get_port_context": ToolDefinition(
                "get_port_context",
                "Get partial maritime gateway context from mapped Saudi ports and experimental PortWatch. Never use it to rank all 13 regions.",
                PortArgs,
                get_port_context,
            ),
            "compare_ports": ToolDefinition(
                "compare_ports",
                "Compare two or more named ports, or all ports with comparable available series when no ports are supplied, using the same PortWatch metric, direction, and date window. Returns Python-calculated summaries and differences; it is context only, not regional ranking.",
                ComparePortsArgs,
                compare_ports,
            ),
            "compare_logistics_gateways": ToolDefinition(
                "compare_logistics_gateways",
                "Compare mapped maritime activity and logistics-center presence across two or more regions. Keep the signals separate and do not create a composite winner score. Use when the user explicitly links ports with logistics centers or cities.",
                LogisticsGatewayArgs,
                compare_logistics_gateways,
            ),
            "get_metric_source": ToolDefinition(
                "get_metric_source",
                "Get metric definition, formula, official source, table, geographic basis, and limitation.",
                MetricSourceArgs,
                get_metric_source,
            ),
            "validate_comparison": ToolDefinition(
                "validate_comparison",
                "Check whether selected metrics and regions can be compared and whether warehouse signals are double-counted.",
                ValidateArgs,
                validate_comparison,
            ),
            "identify_missing_data": ToolDefinition(
                "identify_missing_data",
                "Identify whether requested decision concepts such as rent, occupancy, capacity, competition, SLA, or profitability are available, partial, or missing.",
                MissingDataArgs,
                identify_missing_data,
            ),
            "list_logistics_centers": ToolDefinition(
                "list_logistics_centers",
                "List and summarize the current 59-center Logisti snapshot by region, owner, and active/inactive status. Use for where centers are, the 59 centers, current centers, or listings across regions. Keep it distinct from the official 2024 activated-center statistic.",
                LogisticsCentersArgs,
                list_logistics_centers,
            ),
            "get_modon_context": ToolDefinition(
                "get_modon_context",
                "Describe the MODON evidence currently available and summarize MODON-owned listed logistics centers, optionally for selected regions. Use for MODON, industrial cities, industrial areas, or factories; disclose the non-uniform regional coverage.",
                ModonContextArgs,
                get_modon_context,
            ),
            "describe_available_data": ToolDefinition(
                "describe_available_data",
                "Describe the datasets and evidence currently available inside Mizan, with live counts, periods, and limitations. Use for what data is available, what Mizan knows, data coverage, or supported analyses.",
                AvailableDataArgs,
                describe_available_data,
            ),
            "get_runtime_info": ToolDefinition(
                "get_runtime_info",
                "Return Mizan's current configured model names, Riyadh date, and timezone. Use only for questions about the current model, product, date, or runtime identity.",
                RuntimeInfoArgs,
                _get_runtime_info,
            ),
            "search_knowledge": ToolDefinition(
                "search_knowledge",
                "Search approved Arabic/English methodology, requirements, strategy/policy context, and metric definition cards. Set language to the user's response language. Use for definitions and caveats, not regional numeric values.",
                SearchKnowledgeArgs,
                lambda **kwargs: _search_knowledge(self.retriever, **kwargs),
            ),
            "search_official_web": ToolDefinition(
                "search_official_web",
                "Search only allowlisted Saudi official websites. Use when the question explicitly needs current information or when approved local RAG evidence is too weak. Return official links and access dates; never use the search provider itself as evidence.",
                OfficialWebSearchArgs,
                lambda **kwargs: self.web_research.search(**kwargs),
            ),
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [definition.llm_schema() for definition in self.definitions.values()]

    def schemas_for(self, names: list[str]) -> list[dict[str, Any]]:
        """Expose only intent-relevant tools to reduce quota and tool drift."""
        return [self.definitions[name].llm_schema() for name in names if name in self.definitions]

    def execute(self, name: str, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        started = time.perf_counter()
        trace = {"tool": name, "arguments": arguments, "status": "started"}
        if name not in self.definitions:
            result = {"ok": False, "error": "tool_not_allowed", "message": f"Unknown or disallowed tool: {name}"}
            trace.update(status="blocked", duration_ms=0)
            return result, trace
        definition = self.definitions[name]
        try:
            validated = definition.args_model.model_validate(arguments)
            kwargs = validated.model_dump(exclude_none=True)
            result = definition.function(**kwargs)
            trace["status"] = "success"
        except ValidationError as exc:
            result = {"ok": False, "error": "invalid_tool_arguments", "details": exc.errors(include_url=False)}
            trace["status"] = "validation_error"
        except (MizanError, ValueError) as exc:
            result = {"ok": False, "error": "tool_execution_error", "message": str(exc)}
            trace["status"] = "execution_error"
        except Exception as exc:  # the trace is safe; no secret or stack is exposed to the model
            result = {"ok": False, "error": "unexpected_tool_error", "message": type(exc).__name__}
            trace["status"] = "unexpected_error"
        trace["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        trace["result_summary"] = {
            "ok": result.get("ok"),
            "table_rows": len(result.get("table", [])),
            "source_count": len(result.get("sources", [])),
            "limitation_count": len(result.get("limitations", [])),
        }
        return result, trace


def compact_tool_result(result: dict[str, Any], max_chars: int = 24_000) -> str:
    """Keep the evidence needed by the final answer while bounding free-tier tokens."""
    preferred = {
        key: result[key]
        for key in (
            "ok",
            "tool",
            "region",
            "regions",
            "indicator",
            "selection",
            "criteria",
            "table",
            "pairwise_differences",
            "trend_summary",
            "summary",
            "snapshot_summary",
            "coverage_summary",
            "runtime_info",
            "details",
            "industrial_assets",
            "port_summary",
            "sensitivity",
            "validation",
            "sources",
            "citations",
            "limitations",
            "missing_data_notes",
            "numeric_policy",
            "error",
            "message",
            "details",
        )
        if key in result
    }
    text = json.dumps(preferred, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= max_chars:
        return text
    # Never truncate JSON into an invalid tool result. Remove long RAG text first.
    if preferred.get("tool") == "search_knowledge":
        for row in preferred.get("table", []):
            if len(row.get("text", "")) > 600:
                row["text"] = row["text"][:600] + "…"
        text = json.dumps(preferred, ensure_ascii=False, separators=(",", ":"))
    if len(text) > max_chars:
        preferred["table"] = preferred.get("table", [])[:13]
        preferred["truncation_note"] = "Tool payload compacted for LLM; full result remains in trace."
        text = json.dumps(preferred, ensure_ascii=False, separators=(",", ":"))
    return text
