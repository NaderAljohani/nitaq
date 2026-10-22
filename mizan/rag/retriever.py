from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from pypdf import PdfReader


ALLOWED_RAG_STATUSES = {
    "approved_for_ingestion",
    "approved_selective_ingestion",
    "approved_context_ingestion",
    "approved_ocr_ingestion",
}

SELECTIVE_KEYWORDS = {
    "لوجست",
    "النقل",
    "الموانئ",
    "ميناء",
    "المستودع",
    "سلاسل الإمداد",
    "الخدمات البريدية",
    "logistic",
    "transport",
    "port",
    "warehouse",
    "supply chain",
}

# Reviewed against the visible 2025 NIDLP report layout. Generic keywords in
# headers/footers otherwise pull unrelated industry/energy pages into RAG.
SELECTIVE_PAGES_BY_SOURCE = {
    "nidlp_annual_report_2025": {
        5,
        6,
        17,
        18,
        38,
        39,
        40,
        41,
        42,
        43,
        59,
        70,
        71,
    }
}

ARABIC_DIACRITICS = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u0600-\u06FF]+")

BILINGUAL_QUERY_GROUPS = (
    {"warehouse", "warehouses", "warehousing", "storage", "مستودع", "المستودع", "مستودعات", "المستودعات", "تخزين"},
    {"requirement", "requirements", "regulation", "regulations", "rules", "اشتراط", "اشتراطات", "متطلبات", "شروط", "لائحة"},
    {"logistics", "logistic", "لوجستي", "لوجستية", "اللوجستية", "الخدمات"},
    {"port", "ports", "maritime", "ميناء", "الميناء", "موانئ", "الموانئ", "بحري"},
    {"transport", "transportation", "freight", "نقل", "النقل", "بضائع", "البضائع"},
    {"definition", "define", "methodology", "meaning", "تعريف", "منهجية", "المقصود"},
    {"safety", "fire", "emergency", "سلامة", "السلامة", "حريق", "طوارئ"},
)

# These are retrieval concepts, not stored questions or answers.  A broad
# requirements question needs vocabulary from the main regulatory sections;
# otherwise repeated document titles can outrank the useful clauses.
REQUIREMENTS_DETAIL_TERMS = {
    "site", "architectural", "operation", "safety", "loading", "unloading",
    "الموقع", "المكانية", "المعمارية", "التشغيل", "السلامة", "التحميل", "التفريغ", "يجب",
}

REQUIREMENT_CLAUSE_TERMS = {
    "يجب", "يشترط", "يلزم", "الالتزام", "الموقع", "المساحة", "السلامة", "التحميل", "التفريغ",
    "must", "shall", "required", "site", "area", "safety", "loading", "unloading",
}

SECTION_HEADING = re.compile(
    r"^(?:(?:الباب|الفصل|المادة|القسم|الجزء)\s+[^\n]{1,90}|"
    r"(?:chapter|section|article|part)\s+[\w.\-]+[^\n]{0,80}|"
    r"\d+(?:\.\d+){1,4}\s+[^\n]{2,100})$",
    re.IGNORECASE,
)


class MultilingualSubwordEmbedder:
    """Small offline multilingual embedding used by the hybrid retriever.

    It combines bilingual concept expansion with stable word and character
    n-gram hashing.  This keeps the university project portable and gives
    Arabic/English queries a shared vector space without an API call or a
    downloaded neural model.
    """

    name = "mizan-multilingual-subword-hash-v1"

    def __init__(self, dimensions: int = 384):
        self.dimensions = dimensions

    def _features(self, text: str) -> list[tuple[str, float]]:
        tokens = bilingual_query_tokens(text)
        features: list[tuple[str, float]] = [(f"w:{token}", 1.0) for token in tokens]
        for token in tokenize(text):
            padded = f"^{token}$"
            features.extend((f"c:{padded[index:index + 3]}", 0.35) for index in range(max(0, len(padded) - 2)))
        return features

    def encode_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for feature, weight in self._features(text):
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.dimensions
            sign = 1.0 if (value >> 8) & 1 else -1.0
            vector[index] += sign * weight
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def encode(self, texts: Iterable[str]) -> np.ndarray:
        rows = [self.encode_one(text) for text in texts]
        return np.vstack(rows) if rows else np.empty((0, self.dimensions), dtype=np.float32)


def normalize_arabic(text: str) -> str:
    text = ARABIC_DIACRITICS.sub("", text)
    return text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ؤ": "و", "ئ": "ي"}))


def tokenize(text: str) -> list[str]:
    normalized = normalize_arabic(unicodedata.normalize("NFKC", text).lower())
    tokens = [token.strip("؟،؛ـ«»…") for token in TOKEN_PATTERN.findall(normalized)]
    return [token for token in tokens if len(token) > 1]


def bilingual_query_tokens(text: str) -> list[str]:
    tokens = tokenize(text)
    expanded = set(tokens)
    for group in BILINGUAL_QUERY_GROUPS:
        if expanded.intersection(group):
            expanded.update(group)
    requirements_group = BILINGUAL_QUERY_GROUPS[1]
    warehouse_group = BILINGUAL_QUERY_GROUPS[0]
    if expanded.intersection(requirements_group) and expanded.intersection(warehouse_group):
        expanded.update(REQUIREMENTS_DETAIL_TERMS)
    return list(dict.fromkeys([*tokens, *sorted(expanded - set(tokens))]))


def _merge_overlapping_text(parts: list[str]) -> str:
    merged = ""
    for part in parts:
        clean = str(part or "").strip()
        if not clean:
            continue
        if not merged:
            merged = clean
            continue
        overlap = 0
        maximum = min(300, len(merged), len(clean))
        for size in range(maximum, 39, -1):
            if merged[-size:] == clean[:size]:
                overlap = size
                break
        merged = f"{merged}\n{clean[overlap:].lstrip()}" if overlap else f"{merged}\n{clean}"
    return merged.strip()


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("\u00ad", "").replace("\u200f", " ").replace("\u200e", " ")
    text = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[A-Za-z])", "", text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    metadata: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip().strip('"')
    return metadata, parts[2].strip()


def _section(text: str, heading: str) -> str | None:
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    remainder = text[match.end():]
    next_heading = re.search(r"^##\s+", remainder, re.MULTILINE)
    return clean_text(remainder[: next_heading.start() if next_heading else None]) or None


def chunk_text(text: str, chunk_size: int = 1_400, overlap: int = 200) -> list[str]:
    text = clean_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        target = min(len(text), start + chunk_size)
        if target < len(text):
            candidates = [text.rfind("\n", start, target), text.rfind(". ", start, target)]
            boundary = max(candidates)
            if boundary > start + chunk_size // 2:
                target = boundary + 1
        piece = text[start:target].strip()
        if piece:
            chunks.append(piece)
        if target >= len(text):
            break
        start = max(start + 1, target - overlap)
    return chunks


def _heading_type(heading: str | None) -> str:
    normalized = normalize_arabic(str(heading or "").lower())
    for label, markers in (
        ("article", ("الماده", "article")),
        ("chapter", ("الفصل", "chapter")),
        ("part", ("الباب", "القسم", "الجزء", "part", "section")),
    ):
        if any(normalized.startswith(marker) for marker in markers):
            return label
    return "page_section"


def section_chunks(text: str, *, chunk_size: int = 1_400) -> list[dict[str, str]]:
    """Split a page by visible legal/report headings before bounded splitting."""
    lines = [line.strip() for line in clean_text(text).splitlines() if line.strip()]
    if not lines:
        return []
    sections: list[tuple[str | None, list[str]]] = []
    heading: str | None = None
    body: list[str] = []
    for line in lines:
        is_heading = bool(SECTION_HEADING.match(line))
        if is_heading and body:
            sections.append((heading, body))
            heading, body = line, []
        elif is_heading:
            heading = f"{heading} | {line}" if heading else line
        else:
            body.append(line)
    if body or heading:
        sections.append((heading, body))

    output: list[dict[str, str]] = []
    for section_heading, section_body in sections:
        value = "\n".join([*([section_heading] if section_heading else []), *section_body]).strip()
        if not value:
            continue
        for piece in chunk_text(value, chunk_size=chunk_size, overlap=120):
            output.append(
                {
                    "text": piece,
                    "heading": section_heading or "",
                    "section_type": _heading_type(section_heading),
                }
            )
    return output


def markdown_section_chunks(text: str, *, chunk_size: int = 1_400) -> list[dict[str, str]]:
    matches = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", text))
    if not matches:
        return section_chunks(text, chunk_size=chunk_size)
    output: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(2).strip()
        body = clean_text(text[match.end():end])
        value = f"{heading}\n{body}".strip()
        for piece in chunk_text(value, chunk_size=chunk_size, overlap=120):
            output.append({"text": piece, "heading": heading, "section_type": "markdown_heading"})
    return output


@dataclass
class RAGBuilder:
    root: Path

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
        self.catalog_path = self.root / "knowledge" / "rag" / "source_catalog.csv"
        self.output_dir = self.root / "data" / "processed" / "rag"

    def _catalog(self) -> list[dict[str, str]]:
        with self.catalog_path.open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def _base_metadata(self, source: dict[str, str]) -> dict[str, Any]:
        return {
            "source_id": source["source_id"],
            "title_ar": source["title_ar"],
            "agency": source["agency"],
            "year": source["year"],
            "language": source["language"],
            "document_type": source["document_role"],
            "rag_status": source["rag_status"],
            "source_path": source["path"],
            "source_url": source["source_url"],
            "limitation_ar": source["limitation_ar"],
            "extraction_quality": source.get("extraction_quality"),
        }

    def _ocr_pages(self, pdf_path: Path) -> dict[int, str]:
        sidecar = self.root / "knowledge" / "rag" / "ocr" / f"{pdf_path.stem}.ocr.jsonl"
        if not sidecar.exists():
            return {}
        pages: dict[int, str] = {}
        for line in sidecar.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            pages[int(row["page"])] = clean_text(str(row.get("text") or ""))
        return pages

    def _pdf_chunks(self, source: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        path = self.root / source["path"]
        reader = PdfReader(path)
        ocr_pages = self._ocr_pages(path)
        chunks: list[dict[str, Any]] = []
        included_pages: list[int] = []
        empty_pages: list[int] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = clean_text(page.extract_text() or "")
            extraction_method = "pdf_text_layer"
            if len(text) < 20 and len(ocr_pages.get(page_number, "")) >= 20:
                text = ocr_pages[page_number]
                extraction_method = "ocr_sidecar"
            if len(text) < 20:
                empty_pages.append(page_number)
                continue
            if source["rag_status"] == "approved_selective_ingestion":
                reviewed_pages = SELECTIVE_PAGES_BY_SOURCE.get(source["source_id"])
                if reviewed_pages is not None and page_number not in reviewed_pages:
                    continue
                lowered = normalize_arabic(text.lower())
                if not any(normalize_arabic(keyword.lower()) in lowered for keyword in SELECTIVE_KEYWORDS):
                    continue
            included_pages.append(page_number)
            for index, section in enumerate(section_chunks(text), start=1):
                if not tokenize(section["text"]):
                    continue
                metadata = self._base_metadata(source)
                metadata.update(
                    {
                        "page_start": page_number,
                        "page_end": page_number,
                        "locator": f"page {page_number}",
                        "chunk_index_on_page": index,
                        "heading": section["heading"],
                        "section_type": section["section_type"],
                        "extraction_method": extraction_method,
                        "citation_verified": bool(source.get("agency") and source.get("year") and page_number),
                    }
                )
                chunk_id = f"{source['source_id']}::p{page_number:03d}::c{index:02d}"
                chunks.append({"chunk_id": chunk_id, "text": section["text"], "metadata": metadata})
        audit = {
            "source_id": source["source_id"],
            "path": source["path"],
            "pages_total": len(reader.pages),
            "pages_included": len(included_pages),
            "included_page_numbers": included_pages,
            "empty_or_unusable_pages": empty_pages,
            "chunks": len(chunks),
            "ocr_pages_used": sorted(page for page in included_pages if page in ocr_pages),
            "selection_policy": (
                "visually reviewed logistics/ports page allowlist plus keyword relevance"
                if source["source_id"] in SELECTIVE_PAGES_BY_SOURCE
                else "all usable pages" if source["rag_status"] != "approved_selective_ingestion"
                else "keyword relevance"
            ),
        }
        return chunks, audit

    def _markdown_chunks(self, source: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        path = self.root / source["path"]
        raw = path.read_text(encoding="utf-8")
        frontmatter, body = _frontmatter(raw)
        chunks = []
        for index, section in enumerate(markdown_section_chunks(body), start=1):
            metadata = self._base_metadata(source)
            metadata.update(
                {
                    "page_start": None,
                    "page_end": None,
                    "locator": f"markdown chunk {index}",
                    "chunk_index_on_page": index,
                    "frontmatter": frontmatter,
                    "heading": section["heading"],
                    "section_type": section["section_type"],
                    "extraction_method": "markdown",
                    "citation_verified": bool(source.get("agency") and source.get("year")),
                }
            )
            chunks.append(
                {
                    "chunk_id": f"{source['source_id']}::md::c{index:03d}",
                    "text": section["text"],
                    "metadata": metadata,
                }
            )
        return chunks, {
            "source_id": source["source_id"],
            "path": source["path"],
            "pages_total": None,
            "pages_included": None,
            "included_page_numbers": [],
            "empty_or_unusable_pages": [],
            "chunks": len(chunks),
        }

    def _metric_card_chunks(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        chunks: list[dict[str, Any]] = []
        audits: list[dict[str, Any]] = []
        for path in sorted((self.root / "knowledge" / "cards" / "metrics").glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            frontmatter, body = _frontmatter(raw)
            metric_id = frontmatter.get("metric_id", path.stem)
            limitation = _section(body, "حدود الاستخدام") or "بطاقة تعريف مؤشر؛ القيم الإقليمية تسترجع من أدوات Python فقط."
            source_id = f"metric_card__{metric_id}"
            metadata = {
                "source_id": source_id,
                "title_ar": next((line.lstrip("# ") for line in body.splitlines() if line.startswith("# ")), metric_id),
                "agency": frontmatter.get("source_agency", "Mizan / official source"),
                "year": frontmatter.get("year"),
                "language": "ar",
                "document_type": "metric_card_definition",
                "rag_status": "approved_internal_card",
                "source_path": path.relative_to(self.root).as_posix(),
                "source_url": "",
                "limitation_ar": limitation,
                "page_start": None,
                "page_end": None,
                "locator": "metric card",
                "chunk_index_on_page": 1,
                "metric_id": metric_id,
                "heading": next((line.lstrip("# ") for line in body.splitlines() if line.startswith("# ")), metric_id),
                "section_type": "metric_card",
                "extraction_method": "markdown",
                "citation_verified": bool(frontmatter.get("source_agency") and frontmatter.get("year")),
            }
            # Metric cards contain definitions and caveats, but no regional rows.
            chunks.append({"chunk_id": f"{source_id}::c01", "text": clean_text(body), "metadata": metadata})
            audits.append({"source_id": source_id, "path": metadata["source_path"], "chunks": 1})
        return chunks, audits

    def build(self) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[dict[str, Any]] = []
        source_audits: list[dict[str, Any]] = []
        blocked: list[dict[str, str]] = []
        for source in self._catalog():
            if source["rag_status"] not in ALLOWED_RAG_STATUSES:
                blocked.append(
                    {
                        "source_id": source["source_id"],
                        "rag_status": source["rag_status"],
                        "path": source["path"],
                    }
                )
                continue
            if source["path"].lower().endswith(".pdf"):
                source_chunks, audit = self._pdf_chunks(source)
            elif source["path"].lower().endswith(".md"):
                source_chunks, audit = self._markdown_chunks(source)
            else:
                blocked.append(
                    {"source_id": source["source_id"], "rag_status": "unsupported_format", "path": source["path"]}
                )
                continue
            chunks.extend(source_chunks)
            source_audits.append(audit)

        metric_chunks, metric_audits = self._metric_card_chunks()
        chunks.extend(metric_chunks)
        source_audits.extend(metric_audits)
        for chunk in chunks:
            chunk["token_count"] = len(tokenize(chunk["text"]))

        chunks_path = self.output_dir / "chunks.jsonl"
        with chunks_path.open("w", encoding="utf-8", newline="\n") as stream:
            for chunk in chunks:
                stream.write(json.dumps(chunk, ensure_ascii=False) + "\n")

        embedder = MultilingualSubwordEmbedder()
        embedding_texts = [
            " ".join(
                str(value or "")
                for value in (
                    chunk["metadata"].get("title_ar"),
                    chunk["metadata"].get("heading"),
                    chunk["metadata"].get("agency"),
                    chunk["text"],
                )
            )
            for chunk in chunks
        ]
        embeddings = embedder.encode(embedding_texts)
        np.save(self.output_dir / "embeddings.npy", embeddings, allow_pickle=False)

        manifest = {
            "index_type": "hybrid BM25 + multilingual vector retrieval + deterministic cross-feature re-ranking",
            "chunking": "page-preserving semantic sections by headings/articles/chapters, then bounded sentence chunks",
            "chunk_size_chars_max": 1_400,
            "long_section_overlap_chars": 120,
            "embedding_backend": embedder.name,
            "embedding_dimensions": embedder.dimensions,
            "embedding_rows": int(embeddings.shape[0]),
            "chunk_count": len(chunks),
            "approved_catalog_sources": len(source_audits) - len(metric_audits),
            "metric_cards": len(metric_audits),
            "blocked_sources": blocked,
            "sources": source_audits,
            "numeric_policy": "RAG explains definitions/methodology/requirements; regional numeric answers must come from Phase 2 tools.",
        }
        (self.output_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest


class RAGRetriever:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).resolve() if root else Path(__file__).resolve().parents[2]
        self.chunks_path = self.root / "data" / "processed" / "rag" / "chunks.jsonl"
        self.embeddings_path = self.root / "data" / "processed" / "rag" / "embeddings.npy"
        if not self.chunks_path.exists() or not self.embeddings_path.exists():
            RAGBuilder(self.root).build()
        with self.chunks_path.open("r", encoding="utf-8") as stream:
            self.chunks = [json.loads(line) for line in stream if line.strip()]
        self.documents = [tokenize(chunk["text"]) for chunk in self.chunks]
        self.lengths = [len(document) for document in self.documents]
        self.avg_length = sum(self.lengths) / max(1, len(self.lengths))
        self.term_frequencies = [Counter(document) for document in self.documents]
        document_frequency: Counter[str] = Counter()
        for document in self.documents:
            document_frequency.update(set(document))
        self.idf = {
            term: math.log(1 + (len(self.documents) - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }
        self.embedder = MultilingualSubwordEmbedder()
        self.embeddings = np.load(self.embeddings_path, allow_pickle=False)
        if self.embeddings.shape != (len(self.chunks), self.embedder.dimensions):
            RAGBuilder(self.root).build()
            with self.chunks_path.open("r", encoding="utf-8") as stream:
                self.chunks = [json.loads(line) for line in stream if line.strip()]
            self.embeddings = np.load(self.embeddings_path, allow_pickle=False)

    def _rerank_bonus(
        self,
        index: int,
        *,
        original_query_tokens: list[str],
        query_tokens: list[str],
        requirements_intent: bool,
        warehouse_intent: bool,
    ) -> float:
        """Re-rank a small BM25 candidate pool using intent and passage quality signals."""
        chunk = self.chunks[index]
        document = self.documents[index]
        document_set = set(document)
        original_set = set(original_query_tokens)
        expanded_set = set(query_tokens)
        original_coverage = len(original_set & document_set) / max(1, len(original_set))
        expanded_coverage = len(expanded_set & document_set) / max(1, min(len(expanded_set), 20))
        bonus = original_coverage * 4.0 + expanded_coverage * 2.0

        metadata = chunk.get("metadata", {})
        metadata_tokens = set(
            tokenize(" ".join(str(metadata.get(key) or "") for key in ("title_ar", "heading", "document_type", "agency")))
        )
        # A document title is a strong semantic signal for narrow PDFs (for
        # example container throughput); give it enough weight to survive
        # repeated generic terms inside larger warehouse guides.
        bonus += 6.0 * len(original_set & metadata_tokens) / max(1, len(original_set))

        methodology_tokens = {"منهجية", "منهجيه", "احصاءات", "methodology", "statistics"}
        if original_set.intersection(methodology_tokens) and metadata.get("document_type") == "definitions_methodology_limitations":
            bonus += 8.0
        if {"الوساطة", "الوساطه", "وساطة", "وساطه", "brokerage"}.intersection(original_set) and metadata.get("document_type") == "legal_regulation":
            bonus += 12.0

        if requirements_intent:
            clause_hits = len(document_set & {normalize_arabic(term.lower()) for term in REQUIREMENT_CLAUSE_TERMS})
            bonus += min(clause_hits, 5) * 0.9
            if "ترخيص" in original_set and {"يشترط", "المتطلبات"}.intersection(document_set):
                bonus += 4.0
            if "ترخيص" in original_set and {"يشترط", "استيفاء", "المتطلبات"}.issubset(document_set):
                bonus += 8.0
            if metadata.get("document_type") == "legal_regulation":
                bonus += 2.0
        if requirements_intent and warehouse_intent:
            if metadata.get("document_type") == "regulatory_and_operational_requirements":
                bonus += 5.0
            if re.search(r"\d|[٪%]", chunk.get("text", "")):
                bonus += 1.2
            if metadata.get("document_type") == "metric_card_definition":
                bonus -= 4.0
        return bonus

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        document_types: Iterable[str] | None = None,
        language: str | None = None,
        merge_adjacent: bool = False,
    ) -> list[dict[str, Any]]:
        original_query_tokens = tokenize(query)
        query_tokens = bilingual_query_tokens(query)
        original_query_set = set(original_query_tokens)
        requirements_intent = bool(original_query_set.intersection(BILINGUAL_QUERY_GROUPS[1]))
        warehouse_intent = bool(original_query_set.intersection(BILINGUAL_QUERY_GROUPS[0]))
        if not query_tokens:
            return []
        allowed_types = set(document_types or [])
        scored: list[tuple[float, int]] = []
        lexical_scores: dict[int, float] = {}
        semantic_scores: dict[int, float] = {}
        query_embedding = self.embedder.encode_one(query)
        vector_scores = self.embeddings @ query_embedding if np.any(query_embedding) else np.zeros(len(self.chunks))
        k1, b = 1.5, 0.75
        for index, (chunk, frequencies, length) in enumerate(
            zip(self.chunks, self.term_frequencies, self.lengths, strict=True)
        ):
            if allowed_types and chunk["metadata"]["document_type"] not in allowed_types:
                continue
            score = 0.0
            for term in query_tokens:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                denominator = frequency + k1 * (1 - b + b * length / max(self.avg_length, 1))
                query_weight = 1.0 if term in original_query_set else 0.35
                score += query_weight * self.idf.get(term, 0.0) * frequency * (k1 + 1) / denominator
            metadata_text = " ".join(
                str(chunk["metadata"].get(key) or "") for key in ("title_ar", "agency", "document_type")
            )
            metadata_tokens = set(tokenize(metadata_text))
            score += 0.35 * sum(
                (1.0 if term in original_query_set else 0.35) * self.idf.get(term, 0.0)
                for term in query_tokens
                if term in metadata_tokens
            )
            source_language = str(chunk["metadata"].get("language") or "").lower()
            if language and (language in source_language or source_language == "ar/en"):
                score += 0.5
            if requirements_intent and warehouse_intent and chunk["metadata"].get("document_type") == "regulatory_and_operational_requirements":
                score += 10.0
            if original_query_set.intersection({"منهجية", "منهجيه", "احصاءات", "methodology", "statistics"}) and chunk["metadata"].get("document_type") == "definitions_methodology_limitations":
                score += 8.0
            if original_query_set.intersection({"الوساطة", "الوساطه", "وساطة", "وساطه", "brokerage"}) and chunk["metadata"].get("document_type") == "legal_regulation":
                score += 12.0
            lexical_scores[index] = score
            semantic = float(vector_scores[index])
            semantic_scores[index] = semantic
            hybrid_score = score + max(0.0, semantic) * 7.0
            if score > 0 or semantic >= 0.08:
                scored.append((hybrid_score, index))
        scored.sort(key=lambda item: (-item[0], self.chunks[item[1]]["chunk_id"]))
        candidate_pool = scored[: max(int(top_k) * 6, 24)]
        reranked = [
            (
                score
                + self._rerank_bonus(
                    index,
                    original_query_tokens=original_query_tokens,
                    query_tokens=query_tokens,
                    requirements_intent=requirements_intent,
                    warehouse_intent=warehouse_intent,
                ),
                score,
                index,
            )
            for score, index in candidate_pool
        ]
        reranked.sort(key=lambda item: (-item[0], self.chunks[item[2]]["chunk_id"]))
        results = []
        for score, retrieval_score, index in reranked:
            chunk = json.loads(json.dumps(self.chunks[index], ensure_ascii=False))
            document_set = set(self.documents[index])
            lexical_coverage = len(original_query_set & document_set) / max(1, len(original_query_set))
            metadata = chunk["metadata"]
            metadata_set = set(tokenize(" ".join(str(metadata.get(key) or "") for key in ("title_ar", "heading", "agency"))))
            metadata_coverage = len(original_query_set & metadata_set) / max(1, len(original_query_set))
            semantic_score = semantic_scores.get(index, 0.0)
            confidence = min(
                1.0,
                lexical_coverage * 0.55
                + metadata_coverage * 0.2
                + max(0.0, semantic_score) * 0.25
                + (0.1 if requirements_intent and warehouse_intent and metadata.get("document_type") == "regulatory_and_operational_requirements" else 0.0),
            )
            # Reject passages connected only by a generic expanded term. A
            # short query may survive through title coverage or a strong
            # multilingual vector match, but not from a tiny BM25 accident.
            if confidence < 0.08 or (lexical_coverage == 0 and metadata_coverage == 0 and semantic_score < 0.16):
                continue
            if merge_adjacent:
                anchor = chunk["metadata"]
                neighbour_indices: list[int] = []
                for candidate_index in (index - 1, index, index + 1):
                    if not 0 <= candidate_index < len(self.chunks):
                        continue
                    candidate = self.chunks[candidate_index]
                    metadata = candidate["metadata"]
                    if metadata.get("source_id") != anchor.get("source_id"):
                        continue
                    anchor_page = anchor.get("page_start")
                    if anchor_page is not None and metadata.get("page_start") != anchor_page:
                        continue
                    neighbour_indices.append(candidate_index)
                chunk["text"] = _merge_overlapping_text(
                    [self.chunks[candidate_index]["text"] for candidate_index in neighbour_indices]
                )
                chunk["matched_chunk_ids"] = [
                    self.chunks[candidate_index]["chunk_id"] for candidate_index in neighbour_indices
                ]
            chunk["score"] = round(score, 6)
            chunk["retrieval_score"] = round(lexical_scores.get(index, retrieval_score), 6)
            chunk["semantic_score"] = round(semantic_score, 6)
            chunk["relevance_confidence"] = round(confidence, 6)
            page = metadata.get("page_start")
            chunk["citation_label"] = (
                f"{metadata['title_ar']}، ص. {page}" if page else f"{metadata['title_ar']}، {metadata['locator']}"
            )
            results.append(chunk)
            if len(results) >= max(1, int(top_k)):
                break
        return results
