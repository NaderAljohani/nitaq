from __future__ import annotations

import re
from typing import Any


NUMBER_PATTERN = re.compile(
    r"(?<!\d)[-+]?\d[\d,٬\u00a0\u202f]*(?:[\.٫]\d+)?(?:\s?[٪%])?"
)
INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"اكشف .*تعليمات",
        r"system prompt",
        r"نفذ .*كود",
        r"احسب .*بنفسك",
    )
]
OVERRIDE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (all|the|previous) instructions",
        r"تجاهل .*التعليمات",
    )
]
UNSUPPORTED_CLAIMS = (
    "استثمر في",
    "ننصح بالاستثمار",
    "نقص فعلي",
    "ربحية مضمونة",
    "invest in",
    "guaranteed profit",
    "guaranteed return",
    "proven shortage",
)
SAFE_STRUCTURAL_NUMBERS = {0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 13.0, 100.0, 1000.0, 100000.0, 1000000.0, 2023.0, 2024.0, 2025.0, 2026.0}


def validate_user_input(text: str, max_chars: int = 4_000) -> dict[str, Any]:
    stripped = str(text).strip()
    violations = []
    if not stripped:
        violations.append("empty_input")
    if len(stripped) > max_chars:
        violations.append("input_too_long")
    if any(pattern.search(stripped) for pattern in INJECTION_PATTERNS):
        violations.append("prompt_injection_detected")
    warnings = []
    if any(pattern.search(stripped) for pattern in OVERRIDE_PATTERNS):
        warnings.append("instruction_override_ignored")
    return {"passed": not violations, "violations": violations, "warnings": warnings, "length": len(stripped)}


def _as_number(token: str) -> float | None:
    token = (
        token.replace(",", "")
        .replace("٬", "")
        .replace(" ", "")
        .replace("\u00a0", "")
        .replace("\u202f", "")
        .replace("٫", ".")
        .replace("٪", "%")
    )
    percent = token.endswith("%")
    token = token.rstrip("%")
    try:
        value = float(token)
    except ValueError:
        return None
    return value / 100 if percent else value


def _walk_numbers(value: Any) -> list[float]:
    numbers: list[float] = []
    if isinstance(value, bool) or value is None:
        return numbers
    if isinstance(value, (int, float)):
        numbers.append(float(value))
    elif isinstance(value, str):
        for token in NUMBER_PATTERN.findall(value):
            parsed = _as_number(token)
            if parsed is not None:
                numbers.append(parsed)
    elif isinstance(value, dict):
        for child in value.values():
            numbers.extend(_walk_numbers(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            numbers.extend(_walk_numbers(child))
    return numbers


def _variants(number: float) -> set[float]:
    variants = {number, number * 100, number / 100}
    for digits in range(0, 4):
        rounded = round(number, digits)
        variants.add(rounded)
        variants.add(rounded * 100)
        variants.add(rounded / 100)
        variants.add(round(number * 100, digits))
        variants.add(round(number / 100, digits))
    return variants


def validate_answer(
    answer: str,
    *,
    tool_results: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    tool_was_required: bool,
) -> dict[str, Any]:
    allowed = set(SAFE_STRUCTURAL_NUMBERS)
    for number in _walk_numbers(tool_results) + _walk_numbers(citations):
        allowed.update(_variants(number))
    ungrounded = []
    for token in NUMBER_PATTERN.findall(answer):
        number = _as_number(token)
        if number is None:
            continue
        if not any(abs(number - allowed_number) <= max(1e-6, abs(allowed_number) * 1e-6) for allowed_number in allowed):
            ungrounded.append(token)

    unsupported = []
    lowered = answer.lower()
    for claim in UNSUPPORTED_CLAIMS:
        position = lowered.find(claim.lower())
        if position < 0:
            continue
        prefix = lowered[max(0, position - 18):position]
        if not any(
            negation in prefix
            for negation in ("لا ", "ليس ", "لا يعني", "لا يثبت", "not ", "does not", "isn't ", "cannot ")
        ):
            unsupported.append(claim)

    no_tool_for_data = tool_was_required and not tool_results
    violations = []
    if ungrounded:
        violations.append("ungrounded_numbers")
    if unsupported:
        violations.append("unsupported_decision_claim")
    if no_tool_for_data:
        violations.append("data_answer_without_tool")
    return {
        "passed": not violations,
        "violations": violations,
        "ungrounded_numbers": ungrounded,
        "unsupported_claims": unsupported,
        "tool_was_required": tool_was_required,
    }


def remove_unverified_calculation_lines(
    answer: str,
    ungrounded_numbers: list[str],
) -> tuple[str, list[str]]:
    """Remove whole lines containing model-created calculations.

    This is a deterministic safety repair, not a recalculation. Raw, grounded
    values elsewhere in the answer remain untouched. Arithmetic comparison
    lines are removed because the LLM is not allowed to derive new figures.
    """
    ungrounded_values = {
        value
        for token in ungrounded_numbers
        if (value := _as_number(token)) is not None
    }
    kept: list[str] = []
    removed: list[str] = []
    for line in answer.splitlines():
        line_values = {
            value
            for token in NUMBER_PATTERN.findall(line)
            if (value := _as_number(token)) is not None
        }
        contains_ungrounded = any(
            any(abs(value - target) <= max(1e-6, abs(target) * 1e-6) for target in ungrounded_values)
            for value in line_values
        )
        contains_derived_arithmetic = "≈" in line or "×" in line
        if contains_ungrounded or contains_derived_arithmetic:
            removed.append(line)
        else:
            kept.append(line)
    return "\n".join(kept).strip(), removed


def requires_data_tool(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "منطقة",
            "الرياض",
            "مكة",
            "جدة",
            "الدمام",
            "الشرقية",
            "القصيم",
            "قارن",
            "مقارنة",
            "فرق",
            "فروقات",
            "رتب",
            "توسع",
            "توصيل",
            "مستودع",
            "تراخيص",
            "ميناء",
            "موانئ",
            "اتجاه",
            "كم",
            "compare",
            "region",
            "warehouse",
            "delivery",
            "port",
        )
    )


def clarification_before_llm(text: str) -> str | None:
    """Reserve clarification for genuinely unexecutable requests.

    Open-ended recommendations are executable through the disclosed baseline
    policy, so they must reach the model and tools instead of being blocked here.
    """
    return None
