from __future__ import annotations

import re
from typing import Any


ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
LATIN_RE = re.compile(r"[A-Za-z]")


def normalize_language(value: Any, default: str = "ar") -> str:
    text = str(value or "").strip().lower()
    if text.startswith("en") or text == "english":
        return "en"
    if text.startswith("ar") or text in {"arabic", "العربية", "عربي"}:
        return "ar"
    return default


def detect_language(text: str, previous: str | None = None) -> str:
    """Detect the user's dominant script without an external model call."""
    value = str(text or "")
    arabic = len(ARABIC_RE.findall(value))
    latin = len(LATIN_RE.findall(value))
    if arabic == 0 and latin == 0:
        return normalize_language(previous)
    if arabic >= max(1, latin * 0.6):
        return "ar"
    return "en"


def choose(language: str, arabic: str, english: str) -> str:
    return english if normalize_language(language) == "en" else arabic
