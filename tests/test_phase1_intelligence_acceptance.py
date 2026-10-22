from __future__ import annotations

import pytest

from mizan.agent.config import AgentConfig
from mizan.agent.orchestrator import MizanAgent
from mizan.agent.providers import ProviderError
from mizan.agent.query_context import analyse_query


PHASE1_ACCEPTANCE = [
    ("ما المقصود بمخزون الأمان؟", "general_knowledge", None, None),
    ("اشرح لي العبور المباشر في الخدمات اللوجستية", "general_knowledge", None, None),
    ("ما الفرق بين مركز تنفيذ الطلبات والمستودع التقليدي؟", "general_knowledge", None, None),
    ("كيف تؤثر مرحلة الميل الأخير على تجربة العميل؟", "general_knowledge", None, None),
    ("ما هي سلسلة التبريد؟", "general_knowledge", None, None),
    ("كيف أحسن مسارات التوصيل بشكل عام؟", "general_knowledge", None, None),
    ("اشرح دوران المخزون بطريقة بسيطة", "general_knowledge", None, None),
    ("ما هو مركز تنفيذ الطلبات؟", "general_knowledge", None, None),
    ("What does lead time mean in logistics?", "general_knowledge", None, None),
    ("What is safety stock?", "general_knowledge", None, None),
    ("قارن طلبات التوصيل بين الرياض ومكة", "analytics", "compare_regions", None),
    ("اعرض اتجاه طلبات التوصيل في الرياض", "analytics", "get_indicator_trend", None),
    ("قارن بين الموانئ المتاحة من حيث الواردات", "analytics", "compare_ports", None),
    ("وش البيانات المتوفرة في ميزان؟", "analytics", "describe_available_data", None),
    ("وين توجد المراكز اللوجستية الحالية؟", "analytics", "list_logistics_centers", None),
    ("ما اشتراطات بناء وتشغيل المستودعات؟", "regulatory", "search_knowledge", None),
    ("وش متطلبات السلامة والحريق للمستودع؟", "regulatory", "search_knowledge", None),
    ("اشرح منهجية إحصاءات النقل البري", "regulatory", "search_knowledge", None),
    ("ما متطلبات ترخيص الوساطة في نقل البضائع؟", "regulatory", "search_knowledge", None),
    ("ما البيانات الإلزامية في وثيقة الشحن؟", "regulatory", "search_knowledge", None),
    ("وش أفضل مدينة أفتح فيها مستودع؟", "recommendation", "evaluate_warehouse_locations", None),
    ("رشح بين الرياض وجدة لمركز توزيع", "recommendation", "evaluate_warehouse_locations", None),
    ("وش هو ميزان باختصار؟", "conversation", None, None),
    ("وش النموذج الحالي وكم تاريخ اليوم؟", "conversation", "get_runtime_info", None),
    ("وش تقدر تساعدني فيه لوجستيًا؟", "general_knowledge", None, None),
    ("طيب ما المقصود بمخزون الأمان؟", "general_knowledge", None, {"topic": "ports", "last_tool": "compare_ports", "ports": ["SAJED"]}),
    ("طيب وش الاشتراطات المطلوبة؟", "regulatory", "search_knowledge", {"topic": "warehousing", "goal": "warehouse_setup", "last_tool": "search_knowledge"}),
    ("غيّر الموضوع: ما اشتراطات المستودعات؟", "regulatory", "search_knowledge", {"topic": "ports", "last_tool": "compare_ports", "ports": ["SAJED"]}),
    ("ومن أنت؟", "conversation", None, {"topic": "regional_analytics", "last_tool": "compare_regions", "regions": ["Riyadh", "Makkah"]}),
    ("وأضف واردات ميناء جدة للقرار", "recommendation", "evaluate_warehouse_locations", {"topic": "warehousing", "goal": "warehouse_location", "last_tool": "evaluate_warehouse_locations", "regions": ["Makkah", "Riyadh"], "ports": ["SAJED"]}),
]


@pytest.mark.parametrize("question,family,expected_tool,previous", PHASE1_ACCEPTANCE)
def test_phase1_thirty_question_acceptance(
    question: str,
    family: str,
    expected_tool: str | None,
    previous: dict | None,
) -> None:
    query = analyse_query(question, previous)
    assert query.intent_family == family
    assert query.intent_hint == expected_tool
    response = MizanAgent(AgentConfig.from_env(), offline=True).ask(question, context=previous)
    assert response.status not in {"provider_error", "blocked_max_tool_iterations", "blocked_ungrounded_output"}
    assert response.answer.strip()
    assert not any(marker in response.answer for marker in ("BadRequestError", "ProviderError", "Traceback", "tool_not_allowed"))
    if family == "general_knowledge":
        assert response.status in {"completed", "completed_fallback"}
        assert "حدّد المنطقة" not in response.answer
        assert not response.tool_trace
    if expected_tool:
        assert expected_tool in [item["tool"] for item in response.tool_trace if item["status"] == "success"]


def test_phase1_dataset_contains_exactly_thirty_questions() -> None:
    assert len(PHASE1_ACCEPTANCE) == 30


class _FailingProvider:
    def complete(self, **_: object):
        raise ProviderError("simulated internal provider failure")


@pytest.mark.parametrize(
    "question",
    [
        "ما المقصود بمخزون الأمان؟",
        "قارن طلبات التوصيل بين الرياض ومكة",
        "ما اشتراطات بناء المستودعات؟",
        "وش أفضل مدينة أفتح فيها مستودع؟",
    ],
)
def test_phase1_provider_failure_always_returns_a_public_safe_answer(question: str) -> None:
    response = MizanAgent(AgentConfig.from_env(), provider=_FailingProvider()).ask(question)
    assert response.status in {"completed_fallback", "needs_clarification"}
    assert response.answer.strip()
    assert not any(marker in response.answer for marker in ("ProviderError", "BadRequestError", "simulated", "Traceback"))
