from __future__ import annotations

import json
import inspect
import re
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..tools.analytics import COMPREHENSIVE_COMPARISON_METRICS
from ..tools.registry import ToolRegistry, compact_tool_result
from ..rag import RAGRetriever

from .config import AgentConfig
from .guardrails import (
    clarification_before_llm,
    remove_unverified_calculation_lines,
    requires_data_tool,
    validate_answer,
    validate_user_input,
)
from .general_knowledge import general_knowledge_fallback
from .prompts import CRITIC_PROMPT, SYSTEM_PROMPT_AR
from .adaptive import ComplexityRouter, ExecutionPlan, should_escalate_rag_to_web
from .i18n import choose, detect_language
from .query_context import (
    analyse_query,
    context_from_results,
    default_screening_arguments,
    default_warehouse_decision_arguments,
    tool_names_for_query,
)
from .response_builder import (
    compose_evidence_answer,
    missing_required_entities,
    summary_matches_primary_higher,
)
from .providers import (
    GroqProvider,
    LLMProvider,
    ModelTurn,
    OfflineRuleProvider,
    ProviderError,
    ProviderRateLimitError,
    ToolCall,
)
from .verification import verify_grounded_decision


@dataclass
class AgentResponse:
    answer: str
    conversation_id: str
    model: str
    status: str
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    missing_data_notes: list[str] = field(default_factory=list)
    guardrails: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)
    offline: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    language: str = "ar"
    execution: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _simple_conversation(text: str) -> bool:
    lowered = text.lower().strip()
    return any(
        token in lowered
        for token in (
            "السلام", "مرحبا", "هلا", "وش تقدر", "من أنت", "من انت", "ماهو ميزان", "ما هو ميزان",
            "وش هو ميزان", "وش ميزان", "عرف ميزان", "عرّف ميزان", "عرف بنفسك", "عرّف بنفسك", "help", "hello", "hi", "what can you do",
            "who are you", "what is mizan", "tell me about mizan",
        )
    ) and not requires_data_tool(text)


def _requested_result_limit(text: str) -> int | None:
    normalized = str(text or "")
    match = re.search(r"(?<!\d)([1-9]|[1-5]\d)(?!\d)", normalized)
    if match:
        return int(match.group(1))
    word_limits = {
        "واحد": 1, "واحدة": 1, "اثنين": 2, "اثنان": 2, "ثنتين": 2,
        "ثلاث": 3, "ثلاثة": 3, "اربع": 4, "اربعة": 4,
        "خمس": 5, "خمسة": 5, "ست": 6, "ستة": 6,
        "سبع": 7, "سبعة": 7, "ثمان": 8, "ثمانية": 8,
        "تسع": 9, "تسعة": 9, "عشر": 10, "عشرة": 10,
    }
    words = set(normalized.split())
    return next((value for word, value in word_limits.items() if word in words), None)


def _deduplicate(items: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in items:
        identity = tuple(item.get(key) for key in keys)
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


_INLINE_DOCUMENT_CITATION = re.compile(r"【[^】]{1,240}】")


def _sanitize_answer_text(answer: str, language: str | None = None) -> str:
    """Remove model formatting artifacts while keeping the evidence panel authoritative."""
    cleaned = unicodedata.normalize("NFC", str(answer or ""))
    cleaned = "".join(char for char in cleaned if unicodedata.category(char) != "Cf")
    cleaned = cleaned.replace("\u00a0", " ").replace("\u202f", " ")
    cleaned = _INLINE_DOCUMENT_CITATION.sub("", cleaned)
    if language == "ar":
        cleaned = cleaned.replace("Decision Index", "مؤشر القرار")
    cleaned = re.sub(r"\(\s*\)", "", cleaned)
    cleaned = "\n".join(re.sub(r"[ \t]+", " ", line).rstrip() for line in cleaned.splitlines())
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _knowledge_requires_translation(result: dict[str, Any], language: str) -> bool:
    if result.get("tool") != "search_knowledge":
        return False
    text = " ".join(str(row.get("text") or "") for row in result.get("table", [])[:3])
    arabic = sum("\u0600" <= char <= "\u06ff" for char in text)
    latin = sum(char.isascii() and char.isalpha() for char in text)
    return (language == "en" and arabic > latin) or (language == "ar" and latin > arabic * 2)


def _default_english_limitations(result: dict[str, Any]) -> list[str]:
    tool = result.get("tool")
    if tool in {"compare_ports", "get_port_context"}:
        return ["PortWatch is partial experimental context and does not measure capacity, occupancy, or customs-clearance time."]
    if tool in {"compare_regions", "get_region_profile", "screen_regions", "get_indicator_trend"}:
        return ["The available indicators do not measure warehouse occupancy, operating capacity, cost, or profitability."]
    return []


def _uses_adaptive_model_synthesis(query: Any) -> bool:
    """Spend one extra model turn only where semantic synthesis adds real value."""
    return bool(
        query.warehouse_setup
        or query.retains_previous_context
        or query.intent_hint in {"search_knowledge", "evaluate_warehouse_locations", "compare_ports"}
    )


def _required_tool_names(query: Any, plan: ExecutionPlan | None = None) -> list[str]:
    """Evidence that must exist before the model is allowed to answer a compound goal."""
    if query.warehouse_setup:
        regional_tool = "compare_regions" if len(query.current_regions) > 1 else "get_region_profile"
        names = ["search_knowledge", *([regional_tool] if query.current_regions else [])]
    else:
        names = [query.intent_hint] if query.requires_tool and query.intent_hint else []
    if plan and plan.needs_web:
        names.append("search_official_web")
    return list(dict.fromkeys(name for name in names if name))


def _disclose_screening_weights(
    answer: str,
    results: list[dict[str, Any]],
    language: str = "ar",
) -> tuple[str, bool]:
    """Append the actual screening weights when the model omitted them."""
    result = next(
        (
            item
            for item in reversed(results)
            if item.get("ok") and item.get("tool") in {"screen_regions", "evaluate_warehouse_locations"}
        ),
        None,
    )
    if not result:
        return answer, False
    criteria = result.get("criteria", [])
    percentages = [round(float(item.get("normalized_weight", item.get("weight", 0))) * 100) for item in criteria]
    if not percentages or all(str(value) in answer for value in percentages):
        return answer, False
    labels = []
    for item, percentage in zip(criteria, percentages):
        metric_id = str(item.get("metric_id") or "")
        if language == "en":
            label = "demand" if "delivery" in metric_id else "port activity" if metric_id == "port_activity" else "warehouse footprint"
            labels.append(f"{percentage}% {label}")
        else:
            label = "للطلب" if "delivery" in metric_id else "لنشاط الميناء" if metric_id == "port_activity" else "لحضور المستودعات"
            labels.append(f"{percentage}٪ {label}")
    disclosure = (", ".join(labels) if language == "en" else " و".join(labels))
    if language == "en":
        return f"{answer.rstrip()}\n\n**Assumption used:** {disclosure}; you can change these weights to match your priorities.", True
    return f"{answer.rstrip()}\n\n**الافتراض المستخدم:** {disclosure}، ويمكن تغييره حسب أولوياتك.", True


class MizanAgent:
    def __init__(
        self,
        config: AgentConfig | None = None,
        *,
        provider: LLMProvider | None = None,
        offline: bool = False,
    ):
        self.config = config or AgentConfig.from_env()
        self.offline = offline
        self.retriever = RAGRetriever(self.config.root)
        self.tools = ToolRegistry(self.retriever)
        self.complexity_router = ComplexityRouter()
        if provider is not None:
            self.provider = provider
        elif offline:
            self.provider = OfflineRuleProvider()
        else:
            self.provider = GroqProvider()

    def _model_for(self, text: str) -> str:
        return self.config.fast_model if _simple_conversation(text) else self.config.primary_model

    def _call_provider(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> tuple[ModelTurn, bool]:
        kwargs = {"model": model, "messages": messages, "tools": tools}
        if "tool_choice" in inspect.signature(self.provider.complete).parameters:
            kwargs["tool_choice"] = tool_choice
        try:
            return self.provider.complete(**kwargs), False
        except ProviderRateLimitError:
            if model == self.config.fast_model:
                raise
            kwargs["model"] = self.config.fast_model
            return self.provider.complete(**kwargs), True

    def _write_trace(self, payload: dict[str, Any]) -> None:
        if not self.config.log_enabled:
            return
        # Technical telemetry is opt-in and never stores user questions,
        # assistant answers, chat history, or retrieved document text.
        safe_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"question", "answer", "citations", "limitations", "missing_data_notes"}
        }
        if "tool_trace" in safe_payload:
            safe_payload["tool_trace"] = [
                {
                    key: item.get(key)
                    for key in ("tool", "status", "duration_ms", "result_summary", "iteration")
                    if key in item
                }
                for item in safe_payload["tool_trace"]
            ]
        safe_payload["question_chars"] = len(str(payload.get("question") or ""))
        path = self.config.trace_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(safe_payload, ensure_ascii=False) + "\n")

    def _execute_requests_parallel(
        self,
        requests: list[tuple[str, dict[str, Any]]],
        *,
        iteration: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Execute independent specialist requests concurrently, preserving plan order."""
        if not requests:
            return [], []
        indexed: dict[int, tuple[dict[str, Any], dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(requests))) as pool:
            futures = {
                pool.submit(self.tools.execute, name, arguments): (index, name)
                for index, (name, arguments) in enumerate(requests)
            }
            for future in as_completed(futures):
                index, name = futures[future]
                try:
                    result, trace = future.result()
                except Exception:
                    result = {"ok": False, "tool": name, "error": "specialist_unavailable"}
                    trace = {"tool": name, "arguments": {}, "status": "unexpected_error", "duration_ms": 0}
                trace.update(iteration=iteration, tool_call_id=f"adaptive_{index + 1}", parallel=True)
                indexed[index] = (result, trace)
        ordered = [indexed[index] for index in sorted(indexed)]
        return [item[0] for item in ordered], [item[1] for item in ordered]

    @staticmethod
    def _fallback_tool_request(
        question: str,
        query: Any,
        context: dict[str, Any] | None,
    ) -> tuple[str, dict[str, Any]] | None:
        """Create a conservative local tool request when the model provider is unavailable."""
        intent = query.intent_hint
        context = context or {}
        regions = list(query.current_regions)
        ports = list(query.current_ports)
        if query.retains_previous_context:
            regions = regions or list(context.get("regions") or [])
            ports = ports or list(context.get("ports") or [])
        if intent == "compare_regions" and len(regions) >= 2:
            arguments: dict[str, Any] = {"regions": regions}
            if query.comprehensive_comparison:
                arguments["metric_ids"] = COMPREHENSIVE_COMPARISON_METRICS
            elif query.metric_hints:
                arguments["metric_ids"] = query.metric_hints
            return intent, arguments
        if intent == "compare_logistics_gateways" and len(regions) >= 2:
            arguments = {
                "regions": regions,
                "port_metric": query.port_metric or context.get("port_metric") or "trade_volume",
                "port_direction": query.port_direction or context.get("port_direction") or "incoming",
            }
            if ports:
                arguments["ports"] = ports
            return intent, arguments
        if intent == "evaluate_warehouse_locations":
            arguments = default_warehouse_decision_arguments()
            if regions:
                arguments["locations"] = regions
                arguments["top_n"] = min(5, len(regions))
            port_requested = bool(
                query.port_metric
                or any(
                    token in query.normalized_question
                    for token in ("ميناء", "موانئ", "بحري", "واردات", "صادرات", "port", "maritime", "imports", "exports")
                )
            )
            if port_requested and len(ports) >= max(2, len(regions)):
                metric = query.port_metric or context.get("port_metric") or "trade_volume"
                direction = query.port_direction or context.get("port_direction")
                if not direction:
                    direction = "incoming" if metric == "trade_volume" else "port"
                arguments.update(
                    ports=ports,
                    include_port=True,
                    port_metric=metric,
                    port_direction=direction,
                )
            return intent, arguments
        if intent == "screen_regions":
            return intent, default_screening_arguments()
        if intent == "get_region_profile" and regions:
            return intent, {"region": regions[0]}
        if intent == "get_indicator_trend" and regions:
            indicator = query.trend_indicator or (context.get("indicator") if query.retains_previous_context else None)
            if indicator:
                return intent, {"regions": regions, "indicator": indicator}
        if intent == "compare_ports":
            metric = query.port_metric or (context.get("port_metric") if query.retains_previous_context else None) or "calls"
            direction = query.port_direction or (context.get("port_direction") if query.retains_previous_context else None)
            arguments = {"metric": metric}
            if ports:
                arguments["ports"] = ports
            if direction:
                arguments["direction"] = direction
            return intent, arguments
        if intent == "get_port_context":
            metric = query.port_metric or (context.get("port_metric") if query.retains_previous_context else None) or "calls"
            arguments = {"metric": metric}
            direction = query.port_direction or (context.get("port_direction") if query.retains_previous_context else None)
            if direction:
                arguments["direction"] = direction
            if ports:
                arguments["port"] = ports[0]
            elif regions:
                arguments["region"] = regions[0]
            return intent, arguments
        if intent == "identify_missing_data":
            return intent, {"requested_concepts": None}
        if intent == "list_logistics_centers":
            arguments: dict[str, Any] = {"status": "all"}
            if regions:
                arguments["regions"] = regions
            normalized = query.normalized_question
            if any(token in normalized for token in ("غير مفعلة", "غير مفعله", "inactive")):
                arguments["status"] = "inactive"
            elif any(token in normalized for token in ("المفعلة", "المفعله", "النشطة", "active")):
                arguments["status"] = "active"
            if any(token in normalized for token in ("أكبر", "اكبر", "الأكبر", "الاكبر", "largest", "biggest", "top")):
                arguments["sort_by"] = "area_desc"
            elif any(token in normalized for token in ("أصغر", "اصغر", "الأصغر", "الاصغر", "smallest")):
                arguments["sort_by"] = "area_asc"
            requested_limit = _requested_result_limit(normalized)
            if requested_limit:
                arguments["limit"] = requested_limit
            return intent, arguments
        if intent == "get_modon_context":
            return intent, {"regions": regions} if regions else {}
        if intent == "describe_available_data":
            return intent, {}
        if intent == "get_runtime_info":
            return intent, {}
        if intent == "get_metric_source" and query.metric_hints:
            return intent, {"metric_id": query.metric_hints[0]}
        if intent == "validate_comparison" and regions:
            metric_ids = query.metric_hints or list(context.get("metric_ids") or [])
            if metric_ids:
                return intent, {"regions": regions, "metric_ids": metric_ids, "purpose": "comparison"}
        if intent == "search_knowledge":
            return intent, {"query": question, "top_k": 8, "language": query.language}
        return None

    @classmethod
    def _fallback_tool_requests(
        cls,
        question: str,
        query: Any,
        context: dict[str, Any] | None,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Return the minimum grounded evidence plan when the provider omits a required step."""
        if query.warehouse_setup and query.intent_family != "recommendation":
            requests: list[tuple[str, dict[str, Any]]] = [
                ("search_knowledge", {"query": question, "top_k": 8, "language": query.language})
            ]
            if len(query.current_regions) == 1:
                requests.append(("get_region_profile", {"region": query.current_regions[0]}))
            elif len(query.current_regions) > 1:
                requests.append(("compare_regions", {"regions": query.current_regions}))
            return requests
        request = cls._fallback_tool_request(question, query, context)
        return [request] if request else []

    def ask(
        self,
        question: str,
        *,
        history: list[dict[str, str]] | None = None,
        conversation_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResponse:
        started = time.perf_counter()
        conversation_id = conversation_id or str(uuid.uuid4())
        input_guard = validate_user_input(question, self.config.max_user_chars)
        if not input_guard["passed"]:
            language = detect_language(question, (context or {}).get("language"))
            response = AgentResponse(
                answer=choose(
                    language,
                    "تعذر قبول الطلب لأنه فارغ أو طويل جدًا أو يحاول تجاوز قواعد النظام. أعد صياغته كسؤال لوجستي مباشر.",
                    "The request could not be accepted because it is empty, too long, or attempts to bypass system rules. Rephrase it as a direct logistics question.",
                ),
                conversation_id=conversation_id,
                model="none",
                status="blocked_input",
                guardrails={"input": input_guard},
                offline=self.offline,
                language=language,
            )
            self._write_trace({"event": "agent_response", "question": question, **response.to_dict()})
            return response

        query = analyse_query(question, context)
        execution_plan = self.complexity_router.route(
            question,
            query,
            today=datetime.now(ZoneInfo("Asia/Riyadh")).date(),
        )
        evidence_required = bool(query.requires_tool or execution_plan.needs_web)
        if query.incomplete:
            response = AgentResponse(
                answer=choose(query.language, "يبدو أن السؤال لم يكتمل. أكمل العبارة وحدد ما تريد مقارنته أو تحليله.", "The question appears incomplete. Finish it and specify what you want to compare or analyze."),
                conversation_id=conversation_id,
                model="deterministic_input_check",
                status="needs_clarification",
                guardrails={"input": input_guard, "incomplete_input": True},
                offline=self.offline,
                context=dict(context or {}),
                language=query.language,
            )
            self._write_trace({"event": "agent_response", "question": question, **response.to_dict()})
            return response

        if query.metric_hints and not query.current_regions and not query.intent_hint and not query.general_knowledge:
            response = AgentResponse(
                answer=choose(query.language, "حدّد المنطقة أو المناطق التي تريد تحليل هذا المؤشر لها.", "Specify the region or regions for this indicator."),
                conversation_id=conversation_id,
                model="deterministic_context_check",
                status="needs_clarification",
                guardrails={"input": input_guard, "entity_required": True},
                offline=self.offline,
                context={},
                language=query.language,
            )
            self._write_trace({"event": "agent_response", "question": question, **response.to_dict()})
            return response

        clarification = clarification_before_llm(question) if not query.intent_hint else None
        if clarification:
            response = AgentResponse(
                answer=clarification,
                conversation_id=conversation_id,
                model="deterministic_guardrail",
                status="needs_clarification",
                guardrails={"input": input_guard, "clarification_required": True},
                offline=self.offline,
                context=dict(context or {}),
                language=query.language,
            )
            self._write_trace({"event": "agent_response", "question": question, **response.to_dict()})
            return response

        # Product identity is still generated (not a stored Q&A), but the primary
        # model is used because the small planner model produced repetitive Arabic.
        model = self.config.primary_model if query.product_identity else self._model_for(question)
        candidate_tool_names = tool_names_for_query(query)
        if execution_plan.needs_web and not self.offline and "search_official_web" not in candidate_tool_names:
            candidate_tool_names.append("search_official_web")
        # OfflineRuleProvider validates deterministic fallbacks rather than
        # semantic planning.  Keep it pinned to the inferred tool so tests do
        # not mistake a rule-provider choice for the online planner's choice.
        if self.offline and query.intent_hint and not query.warehouse_setup:
            candidate_tool_names = [query.intent_hint]
        tool_schemas = [] if _simple_conversation(question) else self.tools.schemas_for(candidate_tool_names)
        adaptive_model_synthesis = _uses_adaptive_model_synthesis(query) and not self.offline
        structured_context = json.dumps(query.to_prompt_dict(context), ensure_ascii=False, separators=(",", ":"))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT_AR},
            {
                "role": "system",
                "content": json.dumps(
                    {
                        "runtime_date_riyadh": datetime.now(ZoneInfo("Asia/Riyadh")).date().isoformat(),
                        "configured_model_for_this_request": model,
                        "product_name": "ميزان Mizan",
                        "adaptive_execution_plan": execution_plan.to_dict(),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
            {
                "role": "system",
                "content": (
                    "Structured conversation state extracted locally (never a numeric source): " + structured_context
                    + "\nTreat intent_hint as a fallback hint, not a forced route. Select from the exposed capabilities according to the user's actual goal, and combine tools only when their evidence is needed. "
                    "Keep the previous goal, candidates, and port metric only when retains_previous_context is true. "
                    "Current explicit entities override prior entities. The analytics tool resolves city evidence to its administrative region."
                ),
            },
        ]
        relevant_history = (history or [])[-4:] if query.retains_previous_context else []
        for item in relevant_history:
            if item.get("role") in {"user", "assistant"} and item.get("content"):
                messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": question})

        traces: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        provider_calls = 0
        critic_applied = False
        critic_attempted = False
        answer = ""
        local_answer_built = False
        used_model = model
        fallback_used = False
        status = "completed"

        # Compound questions have independent data and research needs.  Run the
        # specialist evidence requests concurrently, then spend a single model
        # turn on composition.  This is the adaptive multi-agent path; simple
        # questions never pay for these agents.
        if execution_plan.route == "decision":
            adaptive_requests = self._fallback_tool_requests(question, query, context)
            if query.intent_family == "recommendation" and not any(name == "search_knowledge" for name, _ in adaptive_requests):
                adaptive_requests.append(
                    ("search_knowledge", {"query": question, "top_k": 8, "language": query.language})
                )
            if execution_plan.needs_web and not self.offline:
                adaptive_requests.append(
                    ("search_official_web", {"query": question, "max_results": 5, "language": query.language})
                )
            adaptive_requests = list(dict((name, (name, arguments)) for name, arguments in adaptive_requests).values())[:4]
            pre_results, pre_traces = self._execute_requests_parallel(
                adaptive_requests,
                iteration="adaptive_parallel",
            )
            results.extend(pre_results)
            traces.extend(pre_traces)
            for result in pre_results:
                messages.append(
                    {
                        "role": "system",
                        "content": "Grounded specialist evidence: " + compact_tool_result(result, max_chars=10_000),
                    }
                )
            if self.offline and any(result.get("ok") for result in pre_results):
                answer = compose_evidence_answer(question, results, query.language)
                local_answer_built = True
                used_model = "local_adaptive_composer"
            else:
                adaptive_model_synthesis = False
        if (
            not any(result.get("ok") for result in results)
            and query.intent_hint in {"list_logistics_centers", "get_modon_context", "compare_logistics_gateways", "describe_available_data", "get_runtime_info"}
        ):
            direct_request = self._fallback_tool_request(question, query, context)
            if direct_request:
                direct_name, direct_arguments = direct_request
                direct_result, direct_trace = self.tools.execute(direct_name, direct_arguments)
                direct_trace.update(iteration="local_structured", tool_call_id="local_structured")
                traces.append(direct_trace)
                results.append(direct_result)
                if direct_result.get("ok"):
                    answer = compose_evidence_answer(question, results, query.language)
                    local_answer_built = True
                    used_model = "local_structured_evidence"
        try:
            iteration_limit = min(self.config.max_tool_iterations, execution_plan.max_steps)
            for iteration in ([] if local_answer_built else range(1, iteration_limit + 1)):
                active_tools = tool_schemas if not any(result.get("ok") for result in results) else []
                tool_choice = "required" if evidence_required and not results and active_tools else None
                turn, fallback = self._call_provider(
                    model=model,
                    messages=messages,
                    tools=active_tools,
                    tool_choice=tool_choice,
                )
                provider_calls += 1
                fallback_used = fallback_used or fallback
                used_model = turn.model
                for key in usage:
                    usage[key] += int(turn.usage.get(key) or 0)
                if not turn.tool_calls:
                    if evidence_required and not results:
                        for fallback_name, fallback_arguments in self._fallback_tool_requests(question, query, context):
                            fallback_result, fallback_trace = self.tools.execute(fallback_name, fallback_arguments)
                            fallback_trace.update(iteration=iteration, tool_call_id="intent_fallback")
                            traces.append(fallback_trace)
                            results.append(fallback_result)
                        if execution_plan.needs_web and not self.offline:
                            web_result, web_trace = self.tools.execute(
                                "search_official_web",
                                {"query": question, "max_results": 5, "language": query.language},
                            )
                            web_trace.update(iteration=iteration, tool_call_id="freshness_fallback")
                            traces.append(web_trace)
                            results.append(web_result)
                        local_rag = next((item for item in reversed(results) if item.get("tool") == "search_knowledge"), None)
                        if (
                            not self.offline
                            and local_rag
                            and should_escalate_rag_to_web(local_rag)
                            and not any(item.get("tool") == "search_official_web" for item in results)
                        ):
                            web_result, web_trace = self.tools.execute(
                                "search_official_web",
                                {"query": question, "max_results": 5, "language": query.language},
                            )
                            web_trace.update(iteration=iteration, tool_call_id="weak_rag_fallback")
                            traces.append(web_trace)
                            results.append(web_result)
                        if any(result.get("ok") for result in results):
                            answer = compose_evidence_answer(question, results, query.language)
                            local_answer_built = True
                            break
                    answer = (turn.content or "").strip()
                    break
                messages.append(
                    {
                        "role": "assistant",
                        "content": turn.content or "",
                        "tool_calls": [call.as_message_dict() for call in turn.tool_calls],
                    }
                )
                for call in turn.tool_calls:
                    allowed_tool_names = set(candidate_tool_names)
                    if call.name not in allowed_tool_names:
                        fallback_request = self._fallback_tool_request(question, query, context)
                        if fallback_request is None:
                            result = {"ok": False, "tool": call.name, "error": "tool_not_allowed_for_intent"}
                            trace = {
                                "tool": call.name,
                                "arguments": {},
                                "status": "blocked",
                                "error": "tool_not_allowed_for_intent",
                            }
                            trace.update(iteration=iteration, tool_call_id=call.id)
                            traces.append(trace)
                            results.append(result)
                            continue
                        call = ToolCall(call.id, fallback_request[0], fallback_request[1])
                    grounded_arguments = dict(call.arguments)
                    fallback_request = self._fallback_tool_request(question, query, context)
                    fallback_arguments = fallback_request[1] if fallback_request and fallback_request[0] == call.name else {}
                    if call.name in {"evaluate_warehouse_locations", "compare_ports", "get_port_context"}:
                        for key in ("locations", "ports", "include_port", "port_metric", "port_direction", "metric", "direction", "top_n"):
                            if key in fallback_arguments and (
                                key not in grounded_arguments
                                or key in {"port_metric", "port_direction", "metric", "direction", "include_port"}
                            ):
                                grounded_arguments[key] = fallback_arguments[key]
                    if call.name == "evaluate_warehouse_locations" and grounded_arguments.get("include_port"):
                        locations_count = len(grounded_arguments.get("locations") or query.current_regions or [])
                        ports_count = len(grounded_arguments.get("ports") or [])
                        if ports_count < max(2, locations_count):
                            grounded_arguments["include_port"] = False
                            grounded_arguments.pop("ports", None)
                    if call.name == "compare_regions":
                        if "regions" in fallback_arguments:
                            grounded_arguments["regions"] = fallback_arguments["regions"]
                        if "metric_ids" in fallback_arguments:
                            grounded_arguments["metric_ids"] = fallback_arguments["metric_ids"]
                    if call.name == "search_knowledge":
                        grounded_arguments["language"] = query.language
                        grounded_arguments.setdefault("top_k", 8)
                    result, trace = self.tools.execute(call.name, grounded_arguments)
                    trace.update(iteration=iteration, tool_call_id=call.id)
                    traces.append(trace)
                    results.append(result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": compact_tool_result(result),
                        }
                    )
                local_rag = next(
                    (item for item in reversed(results) if item.get("tool") == "search_knowledge"),
                    None,
                )
                web_completed = any(item.get("tool") == "search_official_web" for item in results)
                web_needed = bool(
                    not self.offline
                    and not web_completed
                    and (execution_plan.needs_web or (local_rag and should_escalate_rag_to_web(local_rag)))
                )
                if web_needed:
                    web_result, web_trace = self.tools.execute(
                        "search_official_web",
                        {"query": question, "max_results": 5, "language": query.language},
                    )
                    web_trace.update(
                        iteration=iteration,
                        tool_call_id="research_escalation",
                        escalation_reason="freshness" if execution_plan.needs_web else "weak_local_rag",
                    )
                    traces.append(web_trace)
                    results.append(web_result)
                    messages.append(
                        {
                            "role": "system",
                            "content": "Official web fallback evidence: " + compact_tool_result(web_result, max_chars=10_000),
                        }
                    )
                completed_names = {item.get("tool") for item in results if item.get("ok")}
                missing_required = [name for name in _required_tool_names(query, execution_plan) if name not in completed_names]
                if missing_required:
                    fallback_requests = dict(self._fallback_tool_requests(question, query, context))
                    for missing_name in missing_required:
                        if missing_name == "search_official_web":
                            missing_result, missing_trace = self.tools.execute(
                                missing_name,
                                {"query": question, "max_results": 5, "language": query.language},
                            )
                            missing_trace.update(iteration=iteration, tool_call_id="evidence_completion")
                            traces.append(missing_trace)
                            results.append(missing_result)
                            messages.append(
                                {
                                    "role": "system",
                                    "content": "Additional official web evidence: " + compact_tool_result(missing_result, max_chars=10_000),
                                }
                            )
                            continue
                        if missing_name not in fallback_requests:
                            continue
                        missing_result, missing_trace = self.tools.execute(missing_name, fallback_requests[missing_name])
                        missing_trace.update(iteration=iteration, tool_call_id="evidence_completion")
                        traces.append(missing_trace)
                        results.append(missing_result)
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Additional required grounded evidence completed locally: "
                                    + compact_tool_result(missing_result)
                                ),
                            }
                        )
                successful_result = next((item for item in reversed(results) if item.get("ok")), None)
                if successful_result:
                    if adaptive_model_synthesis:
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "The grounded evidence needed for this answer is now available. "
                                    "Write the final concise answer in the requested language, connect multiple evidence sets when present, "
                                    "and do not call another tool or introduce unsupported numbers."
                                ),
                            }
                        )
                        adaptive_model_synthesis = False
                        continue
                    answer = compose_evidence_answer(question, results, query.language)
                    local_answer_built = True
                    break
            else:
                if not local_answer_built:
                    status = "blocked_max_tool_iterations"
                    answer = choose(query.language, "أوقفت الحلقة بعد بلوغ الحد الآمن لاستدعاءات الأدوات. بسّط السؤال أو قسمه إلى خطوتين.", "The tool-call safety limit was reached. Simplify the question or split it into two steps.")
        except ProviderError as exc:
            if any(result.get("ok") or result.get("tool") == "validate_comparison" for result in results):
                status = "completed_fallback"
                answer = compose_evidence_answer(question, results, query.language)
                local_answer_built = True
            else:
                for fallback_name, fallback_arguments in self._fallback_tool_requests(question, query, context):
                    fallback_result, fallback_trace = self.tools.execute(fallback_name, fallback_arguments)
                    fallback_trace.update(iteration="local_fallback", tool_call_id="local_fallback")
                    traces.append(fallback_trace)
                    results.append(fallback_result)
                local_rag = next((item for item in reversed(results) if item.get("tool") == "search_knowledge"), None)
                if (
                    not self.offline
                    and not any(item.get("tool") == "search_official_web" for item in results)
                    and (execution_plan.needs_web or (local_rag and should_escalate_rag_to_web(local_rag)))
                ):
                    web_result, web_trace = self.tools.execute(
                        "search_official_web",
                        {"query": question, "max_results": 5, "language": query.language},
                    )
                    web_trace.update(iteration="local_fallback", tool_call_id="web_fallback")
                    traces.append(web_trace)
                    results.append(web_result)
                if any(result.get("ok") or result.get("tool") == "validate_comparison" for result in results):
                    status = "completed_fallback"
                    used_model = "local_evidence_fallback"
                    answer = compose_evidence_answer(question, results, query.language)
                    local_answer_built = True
                else:
                    # A provider outage must not end an ordinary domain question
                    # with a technical failure.  Numeric and regulatory questions
                    # still require evidence, but general knowledge has a safe
                    # local conceptual fallback with no invented figures.
                    if query.general_knowledge or query.product_identity:
                        status = "completed_fallback"
                        used_model = "local_general_knowledge_fallback"
                        answer = general_knowledge_fallback(question, query.language)
                    else:
                        status = "needs_clarification"
                        used_model = "local_safe_fallback"
                        answer = choose(
                            query.language,
                            "لم أتمكن من الوصول إلى مصدر موثوق لهذا الطلب الآن. أعد المحاولة، أو حدّد الجزء الذي تريد تحليله وسأستخدم أفضل دليل محلي متاح.",
                            "I could not reach a reliable source for this request right now. Try again, or narrow the part to analyze and I will use the best local evidence available.",
                        )

        citations: list[dict[str, Any]] = []
        limitations: list[str] = []
        missing_notes: list[str] = []
        for result in results:
            citations.extend(result.get("citations", []))
            for source in result.get("sources", []):
                citations.append(
                    {
                        "source_id": source.get("source_id") or source.get("metric_id") or source.get("dataset"),
                        "agency": source.get("agency") or source.get("source_agency") or source.get("publisher"),
                        "year": source.get("year") or source.get("period"),
                        "page_start": source.get("page_start"),
                        "source_url": source.get("source_url"),
                        "source_path": source.get("source_path") or source.get("source_file"),
                        "table_number": source.get("table_number"),
                        "citation_label": source.get("citation_label"),
                    }
                )
            if query.language == "en":
                limitations.extend(result.get("limitations_en") or _default_english_limitations(result))
                missing_notes.extend(result.get("missing_data_notes_en", []))
            else:
                limitations.extend(result.get("limitations", []))
                missing_notes.extend(result.get("missing_data_notes", []))
        citations = _deduplicate(citations, ("source_path", "table_number", "page_start", "source_url"))
        limitations = list(dict.fromkeys(str(item) for item in limitations if item))
        missing_notes = list(dict.fromkeys(str(item) for item in missing_notes if item))
        for index, citation in enumerate(citations, start=1):
            citation["citation_id"] = f"C{index}"

        answer, weights_disclosed = _disclose_screening_weights(answer, results, query.language)

        summary_policy_meta: dict[str, Any] = {}
        if weights_disclosed:
            summary_policy_meta["screening_weights_disclosed"] = True
        successful_tool = next(
            (
                result.get("tool")
                for result in reversed(results)
                if result.get("ok") or result.get("tool") == "validate_comparison"
            ),
            None,
        )
        if results and status in {"completed", "completed_fallback"} and successful_tool:
            initial_guard = validate_answer(
                answer,
                tool_results=results,
                citations=citations,
                tool_was_required=evidence_required,
            )
            initial_missing_entities = missing_required_entities(answer, results)
            initial_alignment = summary_matches_primary_higher(answer, results)
            needs_evidence_fallback = (
                not local_answer_built
                and (
                not answer
                or not initial_guard["passed"]
                or bool(initial_missing_entities)
                or not initial_alignment
                )
            )
            if needs_evidence_fallback:
                answer = compose_evidence_answer(question, results, query.language)
                local_answer_built = True
                status = "completed_fallback"
                summary_policy_meta["deterministic_fallback_applied"] = True
                summary_policy_meta["initial_violations"] = initial_guard["violations"]
                if initial_missing_entities:
                    summary_policy_meta["completeness_fallback_applied"] = True
                    summary_policy_meta["initial_missing_entities"] = initial_missing_entities
                if not initial_alignment:
                    summary_policy_meta["initial_summary_alignment_failed"] = True
            elif local_answer_built:
                summary_policy_meta["local_evidence_synthesis"] = True
            else:
                summary_policy_meta["model_synthesis_preserved"] = True

        if (
            execution_plan.requires_critic
            and not self.offline
            and results
            and answer
            and status in {"completed", "completed_fallback"}
        ):
            critic_attempted = True
            evidence_payload = json.dumps(
                [json.loads(compact_tool_result(result, max_chars=4_000)) for result in results if result.get("ok")],
                ensure_ascii=False,
                separators=(",", ":"),
            )[:12_000]
            critic_messages = [
                {"role": "system", "content": CRITIC_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"question": question, "language": query.language, "draft": answer, "grounded_evidence": evidence_payload},
                        ensure_ascii=False,
                    ),
                },
            ]
            try:
                critic_turn, critic_fallback = self._call_provider(
                    model=self.config.fast_model,
                    messages=critic_messages,
                    tools=[],
                )
                provider_calls += 1
                fallback_used = fallback_used or critic_fallback
                for key in usage:
                    usage[key] += int(critic_turn.usage.get(key) or 0)
                revised = _sanitize_answer_text((critic_turn.content or "").strip(), query.language)
                critic_check = verify_grounded_decision(
                    revised,
                    results=results,
                    citations=citations,
                    tool_was_required=evidence_required,
                )
                if revised and critic_check["passed"]:
                    answer = revised
                    critic_applied = True
                    summary_policy_meta["critic_applied"] = True
                else:
                    summary_policy_meta["critic_rejected_by_verifier"] = True
            except ProviderError:
                summary_policy_meta["critic_unavailable_fallback_preserved"] = True

        if results and not successful_tool and status == "completed":
            answer = choose(query.language, "تعذر إكمال التحليل بالمدخلات الحالية. وضّح المنطقة أو المؤشر المطلوب ثم أعد المحاولة.", "The analysis could not be completed with the current input. Clarify the location or indicator and try again.")
            status = "needs_clarification"

        if self.offline and results and not answer:
            answer = compose_evidence_answer(question, results, query.language)
            local_answer_built = True
            status = "completed_fallback" if status == "completed" else status

        if not results and not answer and (query.general_knowledge or query.product_identity):
            answer = general_knowledge_fallback(question, query.language)
            used_model = "local_general_knowledge_fallback"
            status = "completed_fallback"

        if not results and status == "completed" and re.search(
            r"(?<![\u0600-\u06FF])(?:حد[دّ]|احتاج منك|أعطني|قبل الفرز الأولي)",
            answer,
        ):
            status = "needs_clarification"

        answer = _sanitize_answer_text(answer, query.language)
        output_guard = validate_answer(
            answer,
            tool_results=results,
            citations=citations,
            tool_was_required=evidence_required and status != "needs_clarification",
        )
        omitted_entities = missing_required_entities(answer, results)
        if omitted_entities and status in {"completed", "completed_fallback"}:
            answer = compose_evidence_answer(question, results, query.language)
            status = "completed_fallback"
            output_guard = validate_answer(
                answer,
                tool_results=results,
                citations=citations,
                tool_was_required=evidence_required,
            )
            output_guard["completeness_fallback_applied"] = True
            output_guard["initial_missing_entities"] = omitted_entities
        summary_alignment = summary_matches_primary_higher(answer, results)
        if not summary_alignment and status in {"completed", "completed_fallback"} and results:
            answer = compose_evidence_answer(question, results, query.language)
            summary_alignment = summary_matches_primary_higher(answer, results)
            output_guard = validate_answer(
                answer,
                tool_results=results,
                citations=citations,
                tool_was_required=evidence_required,
            )
            output_guard["summary_alignment_repair_applied"] = True
        output_guard["summary_matches_primary_higher"] = summary_alignment
        if output_guard["violations"] == ["ungrounded_numbers"] and status == "completed":
            repaired_answer, removed_lines = remove_unverified_calculation_lines(
                answer,
                output_guard["ungrounded_numbers"],
            )
            repaired_guard = validate_answer(
                repaired_answer,
                tool_results=results,
                citations=citations,
                tool_was_required=evidence_required,
            )
            if repaired_answer and repaired_guard["passed"]:
                answer = repaired_answer
                output_guard = {
                    **repaired_guard,
                    "deterministic_repair_applied": True,
                    "removed_line_count": len(removed_lines),
                    "initial_violations": ["ungrounded_numbers"],
                }
        if not output_guard["passed"] and status in {"completed", "completed_fallback"} and results:
            deterministic_answer = compose_evidence_answer(question, results, query.language)
            deterministic_guard = validate_answer(
                deterministic_answer,
                tool_results=results,
                citations=citations,
                tool_was_required=evidence_required,
            )
            if deterministic_guard["passed"]:
                answer = deterministic_answer
                status = "completed_fallback"
                output_guard = {
                    **deterministic_guard,
                    "deterministic_fallback_applied": True,
                    "initial_violations": output_guard["violations"],
                }
            else:
                status = "blocked_ungrounded_output"
                answer = choose(query.language, "تعذر عرض نتيجة آمنة من الأدلة المسترجعة. راجع الجدول والمصادر أو أعد صياغة الطلب.", "A grounded answer could not be produced from the retrieved evidence. Review the data and sources or rephrase the request.")
        elif not output_guard["passed"] and status == "completed" and not results:
            status = "needs_clarification"
            answer = choose(query.language, "لم تُنفذ أداة بيانات لهذا الطلب. وضّح المنطقة أو الميناء أو المؤشر المطلوب حتى أستطيع تقديم إجابة موثقة.", "No data tool was run for this request. Specify the region, port, or indicator so I can provide an evidence-based answer.")

        output_guard.update(summary_policy_meta)
        output_guard["summary_matches_primary_higher"] = summary_matches_primary_higher(answer, results)
        output_guard["programmatic_decision_verification"] = verify_grounded_decision(
            answer,
            results=results,
            citations=citations,
            tool_was_required=evidence_required and status != "needs_clarification",
        )

        updated_context = context_from_results(context, query, results)

        answer = _sanitize_answer_text(answer, query.language)
        response = AgentResponse(
            answer=answer or choose(query.language, "لم ينتج النموذج جوابًا. أعد صياغة السؤال وحدد المنطقة أو المؤشر.", "No answer was produced. Rephrase the question and specify the location or indicator."),
            conversation_id=conversation_id,
            model=used_model,
            status=status,
            tool_trace=traces,
            citations=citations,
            limitations=limitations,
            missing_data_notes=missing_notes,
            guardrails={
                "input": input_guard,
                "output": output_guard,
                "fallback_model_used": fallback_used,
                "max_tool_iterations": self.config.max_tool_iterations,
            },
            usage={**usage, "provider_calls": provider_calls},
            offline=self.offline,
            context=updated_context,
            language=query.language,
            execution={
                **execution_plan.to_dict(),
                "tool_steps": len(traces),
                "parallel_execution_used": any(bool(trace.get("parallel")) for trace in traces),
                "web_used": any(result.get("tool") == "search_official_web" and result.get("answerable") for result in results),
                "critic_attempted": critic_attempted,
                "critic_applied": critic_applied,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        self._write_trace(
            {
                "event": "agent_response",
                "timestamp_unix": time.time(),
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "question": question,
                **response.to_dict(),
            }
        )
        return response
