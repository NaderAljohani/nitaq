from __future__ import annotations

import html
import json
import re
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zoneinfo import ZoneInfo


ALLOWED_OFFICIAL_DOMAINS = (
    "stats.gov.sa",
    "data.gov.sa",
    "tga.gov.sa",
    "mawani.gov.sa",
    "logisti.sa",
    "modon.gov.sa",
    "balady.gov.sa",
    "momah.gov.sa",
    "splonline.com.sa",
    "nidlp.gov.sa",
    "vision2030.gov.sa",
    "zatca.gov.sa",
)

# Verified official entry pages used when a site's own search endpoint or the
# discovery index is temporarily unavailable.  These are starting points, not
# stored answers: the page is fetched live, revalidated, scored, and dated on
# every uncached search.
OFFICIAL_TOPIC_ENTRYPOINTS = (
    (
        ("تخزين", "مستودع", "لوجست", "warehous", "logistics statistics"),
        (
            ("إحصاءات التخزين والخدمات اللوجستية 2024", "https://www.stats.gov.sa/ar/w/warehousing-and-logistics-statistics-2024"),
            ("منهجية إحصاءات التخزين والخدمات اللوجستية", "https://www.stats.gov.sa/ar/w/methodology-and-quality-report-for-warehousing-and-logistics-statistics-2024"),
            ("خبر إحصاءات التخزين والخدمات اللوجستية", "https://www.stats.gov.sa/ar/w/news/137"),
        ),
    ),
    (
        ("ترخيص", "اشتراط", "نقل البضائع", "شحن", "freight", "regulation"),
        (
            ("لائحة تشغيل مرافق نقل البضائع", "https://www.tga.gov.sa/ar/Regulations/Regulation/4789"),
        ),
    ),
    (
        ("ميناء", "موانئ", "بحري", "port", "maritime"),
        (
            ("الهيئة العامة للموانئ", "https://mawani.gov.sa/"),
        ),
    ),
)


def _allowed_host(host: str | None) -> bool:
    normalized = (host or "").lower().strip(".")
    return any(normalized == domain or normalized.endswith("." + domain) for domain in ALLOWED_OFFICIAL_DOMAINS)


def _safe_official_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or not _allowed_host(parsed.hostname):
        return False
    try:
        socket.inet_pton(socket.AF_INET, parsed.hostname or "")
        return False
    except OSError:
        return True


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg", "noscript", "nav", "footer"}:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript", "nav", "footer"} and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        if self.in_title:
            self.title_parts.append(value)
        if not self.skip_depth:
            self.parts.append(value)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current_url: str | None = None
        self.current_text: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.current_url = dict(attrs).get("href")
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.current_url:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current_url:
            self.links.append((self.current_url, re.sub(r"\s+", " ", " ".join(self.current_text)).strip()))
            self.current_url = None
            self.current_text = []


def _date_from_html(raw_html: str) -> str | None:
    patterns = (
        r'property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)',
        r'name=["\']date["\'][^>]+content=["\']([^"\']+)',
        r'"datePublished"\s*:\s*"([^"]+)"',
        r'<time[^>]+datetime=["\']([^"\']+)',
    )
    for pattern in patterns:
        match = re.search(pattern, raw_html, flags=re.IGNORECASE)
        if match:
            return match.group(1)[:10]
    return None


def _unwrap_search_url(url: str) -> str:
    parsed = urlparse(url)
    if "bing.com" in (parsed.hostname or ""):
        for key in ("url", "u", "r"):
            value = parse_qs(parsed.query).get(key)
            if value:
                return unquote(value[0])
    return url


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    search_snippet: str


class OfficialWebResearch:
    """Search and read only allowlisted Saudi official websites.

    Bing RSS is used only for discovery.  Every evidence page is fetched from
    and revalidated against the official-domain allowlist after redirects.
    """

    def __init__(self, *, timeout_seconds: float = 8.0, max_pages: int = 5):
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, min(max_pages, 8))
        self.user_agent = "Nitaq-Academic-Copilot/1.0 (+official-source-research)"

    @staticmethod
    def _preferred_domains(query: str) -> list[str]:
        lowered = query.casefold()
        selected: list[str] = []
        groups = (
            (("إحصاء", "بيانات", "مؤشر", "عدد", "statistics", "data"), "stats.gov.sa"),
            (("ترخيص", "اشتراط", "نقل", "شاحنة", "regulation", "transport"), "tga.gov.sa"),
            (("ميناء", "موانئ", "بحري", "port", "maritime"), "mawani.gov.sa"),
            (("مدينة صناعية", "مصانع", "مدن", "modon", "industrial"), "modon.gov.sa"),
            (("بلدي", "بناء", "مستودع", "balady", "warehouse"), "balady.gov.sa"),
            (("رؤية", "استراتيجية", "برنامج", "vision", "strategy"), "vision2030.gov.sa"),
        )
        for cues, domain in groups:
            if any(cue in lowered for cue in cues):
                selected.append(domain)
        for domain in ("stats.gov.sa", "tga.gov.sa", "mawani.gov.sa", "data.gov.sa"):
            if domain not in selected:
                selected.append(domain)
        return selected[:5]

    def _discover_domain(self, query: str, domain: str) -> list[SearchHit]:
        search_url = "https://www.bing.com/search?format=rss&q=" + quote_plus(f"site:{domain} {query}")
        request = Request(search_url, headers={"User-Agent": self.user_agent, "Accept": "application/rss+xml"})
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = response.read(1_000_000)
        root = ElementTree.fromstring(payload)
        hits: list[SearchHit] = []
        for item in root.findall(".//item"):
            url = _unwrap_search_url(item.findtext("link") or "")
            if not _safe_official_url(url):
                continue
            hits.append(
                SearchHit(
                    title=html.unescape(item.findtext("title") or "مصدر رسمي"),
                    url=url,
                    search_snippet=html.unescape(item.findtext("description") or ""),
                )
            )
        return hits

    def _discover_stats_search(self, query: str) -> list[SearchHit]:
        lowered = query.casefold()
        expansions: list[str] = []
        mapping = (
            (("تخزين", "مستودع", "لوجست"), "warehousing logistics"),
            (("ميناء", "موانئ", "بحري"), "ports maritime"),
            (("نقل", "شحن"), "transport freight"),
            (("سكان", "ديموغ"), "population demography"),
        )
        for cues, phrase in mapping:
            if any(cue in lowered for cue in cues):
                expansions.append(phrase)
        search_query = " ".join(expansions) or query
        url = "https://www.stats.gov.sa/ar/search?category=all&delta=20&q=" + quote_plus(search_query[:180])
        request = Request(url, headers={"User-Agent": self.user_agent, "Accept": "text/html"})
        with urlopen(request, timeout=max(22.0, self.timeout_seconds)) as response:
            raw = response.read(3_000_000)
            charset = response.headers.get_content_charset() or "utf-8"
        parser = _LinkParser()
        parser.feed(raw.decode(charset, errors="replace"))
        hits: list[SearchHit] = []
        for href, title in parser.links:
            official_url = urljoin("https://www.stats.gov.sa", html.unescape(href))
            if not _safe_official_url(official_url):
                continue
            path = urlparse(official_url).path
            if "/w/" not in path and "/documents/" not in path:
                continue
            hits.append(SearchHit(title=title or "الهيئة العامة للإحصاء", url=official_url, search_snippet=title))
        return hits

    def _discover(self, query: str, max_results: int) -> list[SearchHit]:
        domains = self._preferred_domains(query)
        discovered: list[SearchHit] = []
        lowered = query.casefold()
        for cues, entries in OFFICIAL_TOPIC_ENTRYPOINTS:
            if any(cue in lowered for cue in cues):
                discovered.extend(SearchHit(title=title, url=url, search_snippet=title) for title, url in entries)
        if "stats.gov.sa" in domains and not discovered:
            try:
                discovered.extend(self._discover_stats_search(query))
            except (HTTPError, URLError, TimeoutError, OSError, ValueError):
                pass
        with ThreadPoolExecutor(max_workers=min(4, len(domains))) as pool:
            futures = [pool.submit(self._discover_domain, query, domain) for domain in domains]
            for future in as_completed(futures):
                try:
                    discovered.extend(future.result())
                except (HTTPError, URLError, TimeoutError, OSError, ValueError, ElementTree.ParseError):
                    continue
        unique: list[SearchHit] = []
        seen: set[str] = set()
        for hit in discovered:
            if hit.url in seen:
                continue
            seen.add(hit.url)
            unique.append(hit)
            if len(unique) >= max_results:
                break
        return unique

    def _read_hit(self, hit: SearchHit) -> dict[str, Any] | None:
        request = Request(
            hit.url,
            headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"},
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            final_url = response.geturl()
            if not _safe_official_url(final_url):
                return None
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "html" not in content_type:
                return None
            raw = response.read(1_500_000)
            charset = response.headers.get_content_charset() or "utf-8"
        raw_html = raw.decode(charset, errors="replace")
        parser = _VisibleTextParser()
        parser.feed(raw_html)
        text = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
        if len(text) < 120:
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", hit.search_snippet)).strip()
        if len(text) < 60:
            return None
        parsed = urlparse(final_url)
        return {
            "title": " ".join(parser.title_parts).strip() or hit.title,
            "url": final_url,
            "domain": parsed.hostname,
            "agency": (parsed.hostname or "").removeprefix("www."),
            "published_date": _date_from_html(raw_html),
            "text": text[:4_000],
        }

    @staticmethod
    def _score(query: str, page: dict[str, Any]) -> float:
        stop = {
            "أحدث", "احدث", "حاليا", "حالياً", "اليوم", "الآن", "الان", "إحصاءات", "احصاءات",
            "بيانات", "عام", "latest", "current", "today", "statistics", "data", "the", "and",
        }
        query_terms = {
            term
            for term in re.findall(r"[\w\u0600-\u06ff]+", query.casefold())
            if len(term) > 2 and term not in stop and not term.isdigit()
        }
        content = f"{page.get('title', '')} {page.get('text', '')}".casefold()
        overlap = sum(1 for term in query_terms if term in content)
        return round(overlap / max(1, len(query_terms)), 4)

    def search(self, query: str, *, max_results: int = 5, language: str = "ar") -> dict[str, Any]:
        clean_query = re.sub(r"\s+", " ", query).strip()[:500]
        accessed = datetime.now(ZoneInfo("Asia/Riyadh")).date().isoformat()
        if not clean_query:
            return self._empty(query, accessed, "empty_query")
        try:
            hits = self._discover(clean_query, max(max_results * 2, self.max_pages))
            pages: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=min(4, len(hits) or 1)) as pool:
                futures = {pool.submit(self._read_hit, hit): hit for hit in hits[: self.max_pages]}
                for future in as_completed(futures):
                    try:
                        page = future.result()
                    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
                        page = None
                    if page:
                        page["relevance_score"] = self._score(clean_query, page)
                        pages.append(page)
            pages = [page for page in pages if page["relevance_score"] >= 0.08]
            pages.sort(key=lambda page: (page["relevance_score"], page.get("published_date") or ""), reverse=True)
            pages = pages[: max(1, min(max_results, 6))]
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, ElementTree.ParseError):
            return self._empty(query, accessed, "network_unavailable")
        if not pages:
            return self._empty(query, accessed, "no_relevant_official_result")
        table = [
            {
                "title": page["title"],
                "text": page["text"][:1_200],
                "source_url": page["url"],
                "agency": page["agency"],
                "published_date": page.get("published_date"),
                "access_date": accessed,
                "relevance_score": page["relevance_score"],
            }
            for page in pages
        ]
        return {
            "ok": True,
            "tool": "search_official_web",
            "query": query,
            "answerable": True,
            "web_status": "completed",
            "table": table,
            "citations": [
                {
                    "source_id": f"web_{index}",
                    "citation_label": row["title"],
                    "agency": row["agency"],
                    "year": (row.get("published_date") or "")[:4] or None,
                    "published_date": row.get("published_date"),
                    "access_date": row["access_date"],
                    "source_url": row["source_url"],
                    "source_type": "official_web",
                }
                for index, row in enumerate(table, 1)
            ],
            "sources": [
                {
                    "source_id": f"web_{index}",
                    "agency": row["agency"],
                    "year": (row.get("published_date") or "")[:4] or None,
                    "published_date": row.get("published_date"),
                    "access_date": row["access_date"],
                    "source_url": row["source_url"],
                    "source_type": "official_web",
                }
                for index, row in enumerate(table, 1)
            ],
            "limitations": ["نتائج الويب محصورة في المواقع الرسمية المسموحة وتعرض تاريخ الوصول؛ تحقق من تاريخ النشر عند غيابه."],
            "limitations_en": ["Web results are restricted to allowlisted official sites and include the access date; verify publication recency when no publication date is exposed."],
            "missing_data_notes": [],
            "missing_data_notes_en": [],
        }

    @staticmethod
    def _empty(query: str, accessed: str, status: str) -> dict[str, Any]:
        return {
            "ok": True,
            "tool": "search_official_web",
            "query": query,
            "answerable": False,
            "web_status": status,
            "access_date": accessed,
            "table": [],
            "citations": [],
            "sources": [],
            "limitations": ["تعذر الحصول على نتيجة رسمية حديثة؛ استمر النظام بأفضل دليل محلي متاح دون إظهار خطأ تقني."],
            "limitations_en": ["No current official result was available; the system continued with the best local evidence without exposing a technical error."],
            "missing_data_notes": ["لا توجد نتيجة ويب رسمية قابلة للاستخدام لهذا السؤال الآن."],
            "missing_data_notes_en": ["No usable official web result is available for this question right now."],
        }
