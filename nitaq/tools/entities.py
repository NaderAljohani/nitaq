from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


_ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")


def normalize_entity_text(value: str) -> str:
    """Normalize Arabic/English entity text without changing its meaning."""
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    text = _ARABIC_DIACRITICS.sub("", text).replace("ـ", "")
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي"}))
    text = re.sub(r"[^\w\u0600-\u06ff-]+", " ", text)
    return " ".join(text.split())


REGION_ENTITY_ALIASES = {
    "riyadh": "Riyadh",
    "riyadh city": "Riyadh",
    "الرياض": "Riyadh",
    "مدينة الرياض": "Riyadh",
    "makkah": "Makkah",
    "makkah al mukarramah": "Makkah",
    "mecca": "Makkah",
    "مكة": "Makkah",
    "مكه": "Makkah",
    "مكة المكرمة": "Makkah",
    "مدينة مكة": "Makkah",
    "jeddah": "Makkah",
    "جدة": "Makkah",
    "مدينة جدة": "Makkah",
    "madinah": "Madinah",
    "medina": "Madinah",
    "al madinah": "Madinah",
    "المدينة": "Madinah",
    "المدينة المنورة": "Madinah",
    "qassim": "Qassim",
    "al qassim": "Qassim",
    "القصيم": "Qassim",
    "buraydah": "Qassim",
    "buraidah": "Qassim",
    "بريدة": "Qassim",
    "eastern region": "Eastern Region",
    "eastern province": "Eastern Region",
    "الشرقية": "Eastern Region",
    "الشرقيه": "Eastern Region",
    "المنطقة الشرقية": "Eastern Region",
    "dammam": "Eastern Region",
    "الدمام": "Eastern Region",
    "khobar": "Eastern Region",
    "الخبر": "Eastern Region",
    "dhahran": "Eastern Region",
    "الظهران": "Eastern Region",
    "jubail": "Eastern Region",
    "الجبيل": "Eastern Region",
    "aseer": "Aseer",
    "asir": "Aseer",
    "عسير": "Aseer",
    "abha": "Aseer",
    "ابها": "Aseer",
    "tabuk": "Tabuk",
    "تبوك": "Tabuk",
    "hail": "Hail",
    "حائل": "Hail",
    "حايل": "Hail",
    "northern borders": "Northern Borders",
    "الحدود الشمالية": "Northern Borders",
    "arar": "Northern Borders",
    "عرعر": "Northern Borders",
    "jazan": "Jazan",
    "جازان": "Jazan",
    "najran": "Najran",
    "نجران": "Najran",
    "al baha": "Al-Baha",
    "al bahah": "Al-Baha",
    "الباحة": "Al-Baha",
    "al jouf": "Al-Jouf",
    "al jawf": "Al-Jouf",
    "الجوف": "Al-Jouf",
    "sakaka": "Al-Jouf",
    "سكاكا": "Al-Jouf",
}


PORT_ENTITY_ALIASES = {
    "sajed": "SAJED",
    "jeddah": "SAJED",
    "jeddah port": "SAJED",
    "jeddah islamic port": "SAJED",
    "جدة": "SAJED",
    "ميناء جدة": "SAJED",
    "مينا جدة": "SAJED",
    "ميناء جدة الاسلامي": "SAJED",
    "sadam": "SADAM",
    "dammam": "SADAM",
    "dammam port": "SADAM",
    "king abdulaziz port": "SADAM",
    "king abdulaziz port dammam": "SADAM",
    "الدمام": "SADAM",
    "ميناء الدمام": "SADAM",
    "مينا الدمام": "SADAM",
    "ميناء الملك عبدالعزيز": "SADAM",
    "الملك عبدالعزيز": "SADAM",
    "الملك عبد العزيز": "SADAM",
    "ميناء الملك عبدالعزيز بالدمام": "SADAM",
    "portwatch kap": "PORTWATCH_KAP",
    "king abdullah port": "PORTWATCH_KAP",
    "ميناء الملك عبدالله": "PORTWATCH_KAP",
    "sajub": "SAJUB",
    "jubail commercial port": "SAJUB",
    "ميناء الجبيل التجاري": "SAJUB",
    "saynb": "SAYNB",
    "yanbu": "SAYNB",
    "yanbu port": "SAYNB",
    "yanbu commercial port": "SAYNB",
    "ينبع": "SAYNB",
    "ميناء ينبع": "SAYNB",
    "مينا ينبع": "SAYNB",
    "ميناء ينبع التجاري": "SAYNB",
    "sajiz": "SAJIZ",
    "jazan port": "SAJIZ",
    "ميناء جازان": "SAJIZ",
    "sadhu": "SADHU",
    "duba port": "SADHU",
    "ميناء ضباء": "SADHU",
}


def _normalized_aliases(mapping: dict[str, str]) -> dict[str, str]:
    return {normalize_entity_text(alias): canonical for alias, canonical in mapping.items()}


NORMALIZED_REGION_ALIASES = _normalized_aliases(REGION_ENTITY_ALIASES)
NORMALIZED_PORT_ALIASES = _normalized_aliases(PORT_ENTITY_ALIASES)


def resolve_region_alias(value: str) -> str | None:
    return NORMALIZED_REGION_ALIASES.get(normalize_entity_text(value))


def resolve_port_alias(value: str) -> str | None:
    return NORMALIZED_PORT_ALIASES.get(normalize_entity_text(value))


@dataclass(frozen=True)
class EntityMention:
    text: str
    canonical: str
    start: int
    end: int


def _extract_mentions(text: str, aliases: dict[str, str]) -> list[EntityMention]:
    normalized = normalize_entity_text(text)
    candidates: list[EntityMention] = []
    for alias, canonical in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        # Arabic conjunctions and short prepositions are commonly attached to
        # entities ("ومكة", "بالشرقية", "للرياض").
        pattern = rf"(?<!\w)(?:و)?(?:ب|ل)?{re.escape(alias)}(?!\w)"
        for match in re.finditer(pattern, normalized):
            display_text = match.group(0)
            if display_text != alias and display_text.endswith(alias):
                display_text = alias
            candidates.append(EntityMention(display_text, canonical, match.start(), match.end()))
    selected: list[EntityMention] = []
    occupied: list[tuple[int, int]] = []
    for mention in sorted(candidates, key=lambda item: (item.start, -(item.end - item.start))):
        if any(mention.start < end and mention.end > start for start, end in occupied):
            continue
        occupied.append((mention.start, mention.end))
        selected.append(mention)
    return sorted(selected, key=lambda item: item.start)


def extract_region_mentions(text: str) -> list[EntityMention]:
    return _extract_mentions(text, NORMALIZED_REGION_ALIASES)


def extract_port_mentions(text: str) -> list[EntityMention]:
    return _extract_mentions(text, NORMALIZED_PORT_ALIASES)
