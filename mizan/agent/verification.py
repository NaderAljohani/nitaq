from __future__ import annotations

import re
from typing import Any

from .guardrails import validate_answer
from .response_builder import summary_matches_primary_higher


def _ranked_winner(results: list[dict[str, Any]]) -> tuple[str | None, list[str], list[str]]:
    for result in reversed(results):
        if not result.get("ok"):
            continue
        rows = result.get("table") or []
        if result.get("tool") == "evaluate_warehouse_locations":
            ranked = sorted(rows, key=lambda row: float(row.get("decision_position") or 10_000))
            labels = [str(row.get("candidate") or row.get("region_ar") or row.get("region_en") or "") for row in ranked]
            aliases = [
                str(ranked[0].get(key))
                for key in ("candidate", "candidate_ar", "candidate_en", "region_ar", "region_en")
                if ranked and ranked[0].get(key)
            ]
            return (labels[0] if labels else None), [label for label in labels if label], aliases
        if result.get("tool") == "screen_regions":
            ranked = sorted(rows, key=lambda row: float(row.get("screening_position") or 10_000))
            labels = [str(row.get("region_ar") or row.get("region_en") or "") for row in ranked]
            aliases = [
                str(ranked[0].get(key))
                for key in ("region_ar", "region_en")
                if ranked and ranked[0].get(key)
            ]
            return (labels[0] if labels else None), [label for label in labels if label], aliases
    return None, [], []


def verify_grounded_decision(
    answer: str,
    *,
    results: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    tool_was_required: bool,
) -> dict[str, Any]:
    numeric = validate_answer(
        answer,
        tool_results=results,
        citations=citations,
        tool_was_required=tool_was_required,
    )
    winner, ranking, winner_aliases = _ranked_winner(results)
    answer_normalized = re.sub(r"\s+", " ", answer).casefold()
    winner_matches = True
    if winner and any(token in answer_normalized for token in ("الأفضل", "الافضل", "أوصي", "اوصي", "recommend", "best", "#1")):
        winner_matches = any(alias.casefold() in answer_normalized for alias in winner_aliases or [winner])
    primary_matches = summary_matches_primary_higher(answer, results)
    return {
        "passed": bool(numeric["passed"] and winner_matches and primary_matches),
        "numeric_grounding": numeric,
        "expected_winner": winner,
        "python_ranking": ranking,
        "winner_matches_python": winner_matches,
        "summary_matches_primary_higher": primary_matches,
    }
