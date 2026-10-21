from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from groq import APIConnectionError, APIError, Groq, RateLimitError

from ..tools.entities import extract_port_mentions, extract_region_mentions
from .i18n import detect_language
from .general_knowledge import general_knowledge_fallback
from .query_context import default_screening_arguments, default_warehouse_decision_arguments


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def as_message_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments, ensure_ascii=False)},
        }


@dataclass
class ModelTurn:
    model: str
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class LLMProvider(Protocol):
    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ModelTurn: ...


class GroqProvider:
    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key:
            raise ProviderError("GROQ_API_KEY is missing. Create .env from .env.example or use --offline.")
        self.client = Groq(api_key=key)

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ModelTurn:
        try:
            request: dict[str, Any] = dict(
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=650,
            )
            if tools:
                request.update(tools=tools, tool_choice=tool_choice or "auto")
            response = self.client.chat.completions.create(**request)
        except RateLimitError as exc:
            raise ProviderRateLimitError("Groq rate limit reached") from exc
        except (APIConnectionError, APIError) as exc:
            raise ProviderError(f"Groq API unavailable: {type(exc).__name__}") from exc
        choice = response.choices[0]
        message = choice.message
        calls = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                raise ProviderError("Model returned invalid JSON tool arguments") from exc
            calls.append(ToolCall(id=call.id, name=call.function.name, arguments=arguments))
        usage = {}
        if getattr(response, "usage", None):
            usage = {
                key: getattr(response.usage, key, None)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
        return ModelTurn(
            model=model,
            content=message.content,
            tool_calls=calls,
            finish_reason=choice.finish_reason,
            usage=usage,
        )


def extract_regions(text: str) -> list[str]:
    return list(dict.fromkeys(mention.canonical for mention in extract_region_mentions(text)))


class OfflineRuleProvider:
    """Deterministic test provider; never marketed as an LLM replacement."""

    def __init__(self):
        self.counter = 0

    def _call(self, name: str, arguments: dict[str, Any], model: str) -> ModelTurn:
        self.counter += 1
        return ModelTurn(
            model=f"offline::{model}",
            tool_calls=[ToolCall(id=f"offline_call_{self.counter}", name=name, arguments=arguments)],
            finish_reason="tool_calls",
        )

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] | None = None,
    ) -> ModelTurn:
        if messages and messages[-1].get("role") == "tool":
            payload = json.loads(messages[-1]["content"])
            if not payload.get("ok"):
                return ModelTurn(
                    model=f"offline::{model}",
                    content="تعذر تنفيذ الأداة بالمعايير الحالية. احتاج منك تصحيح المنطقة أو المؤشر أو معايير المقارنة.",
                    finish_reason="stop",
                )
            tool = payload.get("tool", "الأداة")
            if tool == "search_knowledge":
                answer = "استرجعت التعريفات والقيود من الوثائق المعتمدة. استخدم الاستشهادات المرفقة للتحقق من النص والصفحة."
            elif tool == "identify_missing_data":
                answer = "راجعت تغطية احتياجات القرار. بعض العناصر المطلوبة غير متاحة إقليميًا أو متاحة كسياق جزئي، لذلك لا يجوز حسم القرار بها."
            elif tool == "screen_regions":
                answer = "تم الفرز الأولي تحت المعايير والأوزان التي حددها المستخدم. النتيجة موضع نسبي للاستكشاف وليست اختيارًا استثماريًا أو إثبات نقص سعة."
            else:
                answer = "اكتمل التحليل اعتمادًا على البيانات المعتمدة."
            return ModelTurn(model=f"offline::{model}", content=answer, finish_reason="stop")

        user_text = next(
            (str(message.get("content", "")) for message in reversed(messages) if message.get("role") == "user"),
            "",
        )
        text = user_text.lower()
        language = detect_language(user_text)
        regions = extract_regions(user_text)
        if any(
            phrase in text
            for phrase in (
                "ماهو نطاق", "ما هو نطاق", "وش نطاق", "من أنت", "من انت", "عرف بنفسك", "عرّف بنفسك",
                "what is nitaq", "who is nitaq", "who are you", "tell me about nitaq",
            )
        ):
            content = (
                "Nitaq is a bilingual university logistics-intelligence copilot. It connects approved Saudi data and documents with deterministic Python analysis, then explains the evidence and its limits."
                if language == "en"
                else "نطاق مساعد جامعي ثنائي اللغة للذكاء اللوجستي. يربط البيانات والوثائق السعودية المعتمدة بتحليل Python حتمي، ثم يشرح الأدلة وحدودها بلغة واضحة."
            )
            return ModelTurn(model=f"offline::{model}", content=content, finish_reason="stop")
        if not tools:
            return ModelTurn(
                model=f"offline::{model}",
                content=general_knowledge_fallback(user_text, language),
                finish_reason="stop",
            )
        if any(word in text for word in ("تعريف", "منهج", "اشتراط", "شروط", "متطلبات", "لائحة", "دليل", "سياسة", "تقرير", "ما هي", "ماهي", "ما هو", "ماهو", "وش معنى", "ما المقصود", "requirement", "methodology")) and not any(
            word in text for word in ("أفضل", "أنسب", "انسب", "رشح", "ترشيح", "افتح", "أفتح")
        ):
            return self._call("search_knowledge", {"query": user_text, "top_k": 8, "language": language}, model)
        if any(word in text for word in ("مصدر", "جدول", "وحدة المؤشر", "source")):
            if any(word in text for word in ("مستودع", "warehouse")):
                metric_id = "warehouse_count_2024"
            elif any(word in text for word in ("سكان", "population")):
                metric_id = "population_2024"
            else:
                metric_id = "delivery_total_2024_source"
            return self._call("get_metric_source", {"metric_id": metric_id}, model)
        if any(word in text for word in ("تكلفة", "إيجار", "اشغال", "إشغال", "سعة", "منافس", "ربحية", "ميزانية", "sla")):
            concepts = []
            mapping = {
                "إيجار": "الإيجار",
                "تكلفة": "تكلفة التشغيل",
                "اشغال": "الإشغال",
                "إشغال": "الإشغال",
                "سعة": "السعة",
                "منافس": "المنافسة",
                "ربحية": "الربحية",
                "ميزانية": "تكلفة التشغيل",
                "sla": "sla",
            }
            for keyword, concept in mapping.items():
                if keyword.lower() in text and concept not in concepts:
                    concepts.append(concept)
            return self._call("identify_missing_data", {"requested_concepts": concepts or None}, model)
        if any(word in text for word in ("أفضل", "افضل", "أنسب", "انسب", "رشح", "ترشيح", "افتح", "أفتح", "best", "recommend", "where should", "open a warehouse")):
            arguments = default_warehouse_decision_arguments()
            if regions:
                arguments["locations"] = regions
                arguments["top_n"] = min(5, len(regions))
            ports = list(dict.fromkeys(mention.canonical for mention in extract_port_mentions(user_text)))
            if any(word in text for word in ("ميناء", "موانئ", "بحري", "port", "imports", "exports", "واردات", "صادرات")) and len(ports) >= 2:
                arguments.update(
                    ports=ports,
                    include_port=True,
                    port_metric="trade_volume" if any(word in text for word in ("واردات", "صادرات", "imports", "exports", "volume")) else "calls",
                    port_direction="outgoing" if any(word in text for word in ("صادرات", "exports")) else "incoming",
                )
            return self._call("evaluate_warehouse_locations", arguments, model)
        if any(word in text for word in ("ميناء", "موانئ", "بحري", "port", "ports", "maritime")):
            ports = list(dict.fromkeys(mention.canonical for mention in extract_port_mentions(user_text)))
            metric = "trade_volume" if any(word in text for word in ("حجم", "واردات", "صادرات", "trade", "volume", "imports", "exports")) else "calls"
            direction = "outgoing" if any(word in text for word in ("صادرات", "exports")) else "incoming" if metric == "trade_volume" else "port"
            if len(ports) >= 2:
                return self._call("compare_ports", {"ports": ports, "metric": metric, "direction": direction}, model)
            arguments: dict[str, Any] = {"metric": metric, "direction": direction}
            if regions:
                arguments["region"] = regions[0]
            return self._call("get_port_context", arguments, model)
        if any(word in text for word in ("اتجاه", "تغير", "تطور", "ربع", "trend")):
            indicator = "delivery_requests" if any(word in text for word in ("توصيل", "طلب", "delivery")) else "warehouse_count"
            return self._call("get_indicator_trend", {"regions": regions or ["Riyadh"], "indicator": indicator}, model)
        if any(word in text for word in ("عادلة", "صالحة للمقارنة", "تحقق من المقارنة", "valid")):
            return self._call(
                "validate_comparison",
                {"regions": regions or ["Riyadh"], "metric_ids": ["warehouse_count_2024"], "purpose": "comparison"},
                model,
            )
        if any(word in text for word in ("قارن", "مقارنة", "فرق", "فروقات", "compare")):
            if len(regions) < 2:
                return ModelTurn(
                    model=f"offline::{model}",
                    content="حدد منطقتين على الأقل للمقارنة، ويفضل أن تذكر المؤشر الذي يهمك.",
                    finish_reason="stop",
                )
            arguments: dict[str, Any] = {"regions": regions}
            if any(word in text for word in ("توصيل", "طلبات", "delivery")):
                arguments["metric_ids"] = ["delivery_total_2024_source"]
            elif any(word in text for word in ("مستودع", "مستودعات", "warehouse")):
                arguments["metric_ids"] = ["warehouse_count_2024"]
            return self._call("compare_regions", arguments, model)
        if any(word in text for word in ("رتب", "أولوية", "اختيار", "screen", "rank")):
            return self._call("screen_regions", default_screening_arguments(), model)
        if regions:
            return self._call("get_region_profile", {"region": regions[0]}, model)
        content = general_knowledge_fallback(user_text, language)
        return ModelTurn(model=f"offline::{model}", content=content, finish_reason="stop")
