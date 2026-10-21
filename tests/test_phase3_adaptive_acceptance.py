from __future__ import annotations

from dataclasses import dataclass

import pytest

from nitaq.agent import AgentConfig, MizanAgent
from nitaq.agent.providers import ModelTurn


class MinimalPlanner:
    """A deterministic provider stub; orchestration, not prose, is under test."""

    def __init__(self):
        self.calls = 0

    def complete(self, *, model, messages, tools, tool_choice=None):
        self.calls += 1
        return ModelTurn(
            model=f"fixture::{model}",
            content="الخلاصة مبنية على الأدلة المرفقة، مع إبقاء القرار استكشافيًا وحدوده واضحة.",
            finish_reason="stop",
            usage={"prompt_tokens": 20, "completion_tokens": 12, "total_tokens": 32},
        )


def _official_web_fixture(query: str, *, max_results: int = 5, language: str = "ar"):
    return {
        "ok": True,
        "tool": "search_official_web",
        "query": query,
        "answerable": True,
        "web_status": "completed",
        "table": [
            {
                "title": "تحديث رسمي لقطاع النقل والخدمات اللوجستية",
                "text": "صفحة رسمية حديثة مرتبطة بالسؤال وتعرض التحديث في سياقه.",
                "source_url": "https://www.stats.gov.sa/ar/w/news/137",
                "agency": "stats.gov.sa",
                "published_date": "2026-06-01",
                "access_date": "2026-07-30",
                "relevance_score": 0.9,
            }
        ],
        "citations": [
            {
                "source_id": "web_1",
                "citation_label": "تحديث رسمي لقطاع النقل والخدمات اللوجستية",
                "agency": "stats.gov.sa",
                "year": "2026",
                "published_date": "2026-06-01",
                "access_date": "2026-07-30",
                "source_url": "https://www.stats.gov.sa/ar/w/news/137",
                "source_type": "official_web",
            }
        ],
        "sources": [],
        "limitations": ["مصدر ويب رسمي مع تاريخ وصول."],
        "limitations_en": ["Official web source with access date."],
        "missing_data_notes": [],
        "missing_data_notes_en": [],
    }


@dataclass(frozen=True)
class Case:
    question: str
    route: str
    expected_tool: str | None
    web: bool = False
    parallel: bool = False


CASES = [
    Case("ما هو المستودع اللوجستي؟", "direct", None),
    Case("وش الفرق بين المستودع ومركز تنفيذ الطلبات؟", "direct", None),
    Case("اشرح لي مخزون الأمان", "direct", None),
    Case("What is cross-docking?", "direct", None),
    Case("كيف يعمل الميل الأخير؟", "direct", None),
    Case("ما المقصود بمقدم الخدمات اللوجستية 3PL؟", "direct", None),
    Case("كيف أختار موقع مركز توزيع بشكل عام؟", "direct", None),
    Case("وش فائدة سلسلة التبريد؟", "direct", None),
    Case("Explain safety stock in simple terms.", "direct", None),
    Case("ما الفرق بين النقل والتوزيع؟", "direct", None),
    Case("قارن طلبات التوصيل بين الرياض ومكة", "data", "compare_regions"),
    Case("كم عدد المستودعات في منطقة الرياض؟", "data", "get_region_profile"),
    Case("وش اتجاه طلبات التوصيل في مكة؟", "data", "get_indicator_trend"),
    Case("قارن الموانئ المتاحة من ناحية الواردات", "data", "compare_ports"),
    Case("قارن البنية اللوجستية بين الرياض والشرقية", "data", "compare_regions"),
    Case("ما اشتراطات المستودعات اللوجستية؟", "research", "search_knowledge"),
    Case("ما البيانات الإلزامية في وثيقة الشحن؟", "research", "search_knowledge"),
    Case("What are Saudi warehouse operating requirements?", "research", "search_knowledge"),
    Case("أبي أبني مستودع في حائل، اربط المتطلبات بواقع المنطقة", "decision", "search_knowledge", parallel=True),
    Case("وش أفضل مدينة أفتح فيها مستودع مع مراعاة اشتراطات الترخيص؟", "decision", "evaluate_warehouse_locations", parallel=True),
    Case("وش أحدث أخبار الموانئ السعودية اليوم؟", "decision", "search_official_web", web=True, parallel=True),
    Case("ما آخر تحديث لاشتراطات نقل البضائع حاليًا؟", "research", "search_official_web", web=True),
    Case("أعطني أحدث إحصاءات التخزين والخدمات اللوجستية 2026", "research", "search_official_web", web=True),
    Case("What are the latest Saudi logistics regulations today?", "research", "search_official_web", web=True),
    Case("هل صدرت أخبار جديدة عن المراكز اللوجستية الآن؟", "research", "search_official_web", web=True),
    Case("قارن الرياض ومكة بأحدث بيانات الطلب الحالية", "decision", "search_official_web", web=True, parallel=True),
    Case("وش أفضل منطقة لمستودع حسب البيانات وآخر اشتراطات 2026؟", "decision", "search_official_web", web=True, parallel=True),
    Case("ما أحدث تحديث من الهيئة العامة للنقل للشحن؟", "research", "search_official_web", web=True),
    Case("Latest official Saudi port update as of today?", "decision", "search_official_web", web=True, parallel=True),
    Case("هل تغيّر عدد المراكز اللوجستية في 2026؟", "decision", "search_official_web", web=True, parallel=True),
]


def test_phase3_acceptance_has_30_cases_and_10_web_cases():
    assert len(CASES) == 30
    assert sum(case.web for case in CASES) == 10


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.question)
def test_adaptive_phase3_routes_and_executes(case: Case):
    provider = MinimalPlanner()
    agent = MizanAgent(AgentConfig.from_env(), provider=provider)
    agent.tools.web_research.search = _official_web_fixture
    response = agent.ask(case.question)

    assert response.answer
    assert response.execution["route"] == case.route
    assert response.execution["max_steps"] <= 4
    assert response.usage["provider_calls"] >= 0
    assert not any(token in response.answer for token in ("ProviderError", "BadRequestError", "Traceback"))
    tools = [trace["tool"] for trace in response.tool_trace if trace.get("status") == "success"]
    if case.expected_tool:
        assert case.expected_tool in tools
    else:
        assert tools == []
        assert response.usage["provider_calls"] == 1
    if case.web:
        assert "search_official_web" in tools
        assert response.execution["web_used"] is True
        assert any(citation.get("source_url", "").startswith("https://") for citation in response.citations)
        assert any(citation.get("access_date") == "2026-07-30" for citation in response.citations)
    if case.parallel:
        assert response.execution["parallel_execution_used"] is True
