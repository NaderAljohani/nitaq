from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


FRESHNESS_CUES = (
    "اليوم",
    "حاليا",
    "حالياً",
    "الآن",
    "الان",
    "أحدث",
    "احدث",
    "آخر تحديث",
    "اخر تحديث",
    "أخبار جديدة",
    "تحديث جديد",
    "latest",
    "current",
    "today",
    "recent",
    "as of",
)

RESEARCH_CUES = (
    "اشتراط",
    "ترخيص",
    "لائحة",
    "نظام",
    "متطلبات",
    "مصدر",
    "requirement",
    "regulation",
    "license",
    "policy",
    "source",
)


@dataclass(frozen=True)
class ExecutionPlan:
    route: str
    complexity: str
    agents: tuple[str, ...]
    max_steps: int
    parallel_tools: bool
    needs_web: bool
    web_reason: str | None
    requires_critic: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["agents"] = list(self.agents)
        payload["reasons"] = list(self.reasons)
        return payload


class ComplexityRouter:
    """Choose the smallest useful execution path for a question.

    The router does not answer the question and is never a numeric source.  It
    only decides which specialist capabilities should be available.
    """

    def route(self, question: str, query: Any, *, today: date | None = None) -> ExecutionPlan:
        lowered = question.casefold()
        current_year = str((today or date.today()).year)
        explicit_freshness = any(cue in lowered for cue in FRESHNESS_CUES)
        explicit_current_year = current_year in lowered
        needs_web = bool(explicit_freshness or explicit_current_year)
        reasons: list[str] = []
        if explicit_freshness:
            reasons.append("freshness_cue")
        if explicit_current_year:
            reasons.append("current_year")

        wants_research = bool(
            query.intent_family == "regulatory"
            or query.warehouse_setup
            or any(cue in lowered for cue in RESEARCH_CUES)
        )
        wants_data = bool(
            query.intent_family in {"analytics", "recommendation"}
            or (query.warehouse_setup and query.current_regions)
        )
        compound = bool(
            query.complexity == "compound"
            or (query.intent_family == "recommendation" and wants_research)
            or (wants_data and needs_web)
        )

        if (query.general_knowledge or query.product_identity) and not needs_web:
            return ExecutionPlan(
                route="direct",
                complexity="simple",
                agents=("DirectAnswer",),
                max_steps=1,
                parallel_tools=False,
                needs_web=False,
                web_reason=None,
                requires_critic=False,
                reasons=("stable_general_knowledge",),
            )
        if compound:
            agents = ["DataAgent"] if wants_data else []
            agents.append("ResearchAgent")
            agents.append("DecisionComposer")
            return ExecutionPlan(
                route="decision",
                complexity="compound",
                agents=tuple(agents),
                max_steps=4,
                parallel_tools=True,
                needs_web=needs_web,
                web_reason="freshness" if needs_web else None,
                requires_critic=True,
                reasons=tuple(reasons or ["multiple_evidence_types"]),
            )
        if wants_data:
            return ExecutionPlan(
                route="data",
                complexity="tool",
                agents=("DataAgent", "DecisionComposer"),
                max_steps=3,
                parallel_tools=False,
                needs_web=needs_web,
                web_reason="freshness" if needs_web else None,
                requires_critic=False,
                reasons=tuple(reasons or ["deterministic_numeric_evidence"]),
            )
        return ExecutionPlan(
            route="research",
            complexity="tool",
            agents=("ResearchAgent", "DecisionComposer"),
            max_steps=3,
            parallel_tools=False,
            needs_web=needs_web,
            web_reason="freshness" if needs_web else None,
            requires_critic=False,
            reasons=tuple(reasons or ["document_evidence"]),
        )


def should_escalate_rag_to_web(result: dict[str, Any]) -> bool:
    """Escalate only when approved local evidence is absent or weak."""

    if result.get("tool") != "search_knowledge":
        return False
    if not result.get("answerable") or not result.get("table"):
        return True
    confidence = max(
        (float(row.get("relevance_confidence") or 0) for row in result.get("table", [])),
        default=0.0,
    )
    return confidence < 0.12
