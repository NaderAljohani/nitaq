from __future__ import annotations

import re
import statistics
import time

from nitaq.agent import AgentConfig, MizanAgent
from tests.evaluation_cases import core_evaluation_cases
from nitaq.agent.providers import ModelTurn, ProviderError
from nitaq.agent.response_builder import compose_evidence_answer
from nitaq.agent.verification import verify_grounded_decision


TECHNICAL_TOKENS = (
    "ProviderError",
    "BadRequestError",
    "Traceback",
    "APIConnectionError",
    "invalid_tool_arguments",
    "unexpected_tool_error",
)


def _case_success(case, response) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if not response.answer.strip():
        failures.append("empty_answer")
    if any(token.casefold() in response.answer.casefold() for token in TECHNICAL_TOKENS):
        failures.append("technical_error_exposed")
    if response.status in {"blocked_ungrounded_output", "blocked_max_tool_iterations"}:
        failures.append(response.status)
    successful_tools = [trace.get("tool") for trace in response.tool_trace if trace.get("status") == "success"]
    if case.expected_tool and case.expected_tool not in successful_tools:
        failures.append(f"missing_tool:{case.expected_tool}")
    if case.expected_route and response.execution.get("route") != case.expected_route:
        failures.append(f"route:{response.execution.get('route')}")
    if response.status == "needs_clarification" and not case.accepts_clarification and case.expected_tool:
        failures.append("unnecessary_clarification")
    verification = response.guardrails.get("output", {}).get("programmatic_decision_verification", {})
    if verification and not verification.get("passed") and response.status in {"completed", "completed_fallback"}:
        failures.append("decision_verification")
    return not failures, failures


def test_phase4_core_evaluation_has_100_questions_and_exceeds_90_percent():
    cases = core_evaluation_cases()
    assert len(cases) == 100
    agent = MizanAgent(AgentConfig.from_env(), offline=True)
    outcomes = []
    latencies = []
    details = []
    for case in cases:
        started = time.perf_counter()
        response = agent.ask(case.question, conversation_id=f"core-{case.case_id}")
        latencies.append((time.perf_counter() - started) * 1000)
        passed, failures = _case_success(case, response)
        outcomes.append(passed)
        if not passed:
            details.append((case.case_id, case.question, failures, [t.get("tool") for t in response.tool_trace]))
    success_rate = sum(outcomes) / len(outcomes)
    assert success_rate >= 0.90, details
    assert statistics.median(latencies) < 1_000


class AlwaysFailProvider:
    def complete(self, **kwargs):
        raise ProviderError("simulated provider outage")


class PlainProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, *, model, messages, tools, tool_choice=None):
        self.calls += 1
        return ModelTurn(
            model="fixture",
            content="الخلاصة واضحة ومبنية على الأدلة المتاحة دون إضافة أرقام جديدة.",
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        )


def test_groq_failure_never_exposes_a_technical_error():
    agent = MizanAgent(AgentConfig.from_env(), provider=AlwaysFailProvider())
    for question in ("ما هو التخزين المتقاطع؟", "قارن طلبات التوصيل بين الرياض ومكة", "ما اشتراطات المستودعات؟"):
        response = agent.ask(question)
        assert response.answer
        assert not any(token.casefold() in response.answer.casefold() for token in TECHNICAL_TOKENS)
        assert response.status in {"completed_fallback", "needs_clarification"}


def test_web_failure_returns_local_or_understandable_fallback():
    provider = PlainProvider()
    agent = MizanAgent(AgentConfig.from_env(), provider=provider)
    agent.tools.web_research.search = lambda *args, **kwargs: {
        "ok": True,
        "tool": "search_official_web",
        "answerable": False,
        "web_status": "network_unavailable",
        "table": [],
        "citations": [],
        "sources": [],
        "limitations": ["تعذر الوصول للويب الرسمي، واستمر النظام دون خطأ تقني."],
        "limitations_en": ["Official web was unavailable; the system continued safely."],
        "missing_data_notes": ["لا توجد نتيجة ويب الآن."],
        "missing_data_notes_en": ["No web result is available now."],
    }
    response = agent.ask("وش أحدث أخبار الموانئ السعودية اليوم؟")
    assert response.answer
    assert not any(token.casefold() in response.answer.casefold() for token in TECHNICAL_TOKENS)
    assert any(trace.get("tool") == "search_official_web" for trace in response.tool_trace)


def test_weak_rag_escalates_to_official_web():
    provider = PlainProvider()
    agent = MizanAgent(AgentConfig.from_env(), provider=provider)
    agent.retriever.search = lambda *args, **kwargs: []
    agent.tools.web_research.search = lambda query, **kwargs: {
        "ok": True,
        "tool": "search_official_web",
        "answerable": True,
        "web_status": "completed",
        "table": [{"title": "لائحة رسمية", "text": "متطلبات رسمية مرتبطة بالسؤال", "source_url": "https://www.tga.gov.sa/ar/Regulations/Regulation/4789", "agency": "tga.gov.sa", "published_date": "2025-12-01", "access_date": "2026-07-30", "relevance_score": 1.0}],
        "citations": [{"source_id": "web_1", "source_url": "https://www.tga.gov.sa/ar/Regulations/Regulation/4789", "agency": "tga.gov.sa", "published_date": "2025-12-01", "access_date": "2026-07-30", "source_type": "official_web"}],
        "sources": [],
        "limitations": [],
        "limitations_en": [],
        "missing_data_notes": [],
        "missing_data_notes_en": [],
    }
    response = agent.ask("ما اشتراطات تشغيل مرافق نقل البضائع؟")
    tools = [trace.get("tool") for trace in response.tool_trace]
    assert tools == ["search_knowledge", "search_official_web"]
    assert any(citation.get("access_date") == "2026-07-30" for citation in response.citations)


def test_critic_runs_only_for_compound_questions():
    provider = PlainProvider()
    agent = MizanAgent(AgentConfig.from_env(), provider=provider)
    simple = agent.ask("ما هو مخزون الأمان؟")
    assert simple.execution["critic_attempted"] is False
    compound = agent.ask("وش أفضل مدينة أفتح فيها مستودع مع مراعاة اشتراطات الترخيص؟")
    assert compound.execution["route"] == "decision"
    assert compound.execution["critic_attempted"] is True
    assert compound.usage["provider_calls"] == 2


def test_programmatic_verifier_rejects_winner_mismatch_and_accepts_python_winner():
    agent = MizanAgent(AgentConfig.from_env(), offline=True)
    result, _ = agent.tools.execute("evaluate_warehouse_locations", {"locations": ["Riyadh", "Makkah"], "top_n": 2})
    assert result["ok"]
    grounded = compose_evidence_answer("وش الأفضل؟", [result], "ar")
    accepted = verify_grounded_decision(grounded, results=[result], citations=result.get("citations", []), tool_was_required=True)
    assert accepted["passed"] is True
    ranking = accepted["python_ranking"]
    wrong = ranking[-1]
    rejected = verify_grounded_decision(f"الأفضل هو {wrong}.", results=[result], citations=result.get("citations", []), tool_was_required=True)
    assert rejected["winner_matches_python"] is False
    assert rejected["passed"] is False
