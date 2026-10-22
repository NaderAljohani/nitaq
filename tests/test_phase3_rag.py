from __future__ import annotations

import json
from pathlib import Path

from mizan.rag import RAGBuilder, RAGRetriever


def test_rag_manifest_includes_reviewed_ocr_regulation_and_metric_cards():
    manifest = json.loads(Path("data/processed/rag/manifest.json").read_text(encoding="utf-8"))
    assert manifest["chunk_count"] >= 250
    assert manifest["approved_catalog_sources"] == 8
    assert manifest["metric_cards"] == 17
    assert manifest["blocked_sources"] == []
    regulation = next(item for item in manifest["sources"] if item["source_id"] == "tga_goods_brokerage_regulation_2025")
    assert regulation["ocr_pages_used"] == list(range(1, 22))


def test_every_chunk_has_required_provenance_and_page_field():
    chunks = [
        json.loads(line)
        for line in Path("data/processed/rag/chunks.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    required = {
        "source_id",
        "agency",
        "year",
        "page_start",
        "page_end",
        "document_type",
        "source_path",
        "limitation_ar",
    }
    assert chunks
    assert all(required.issubset(chunk["metadata"]) for chunk in chunks)
    assert all(chunk["text"].strip() for chunk in chunks)
    assert all(chunk["token_count"] > 0 for chunk in chunks)
    assert any(chunk["metadata"]["source_id"] == "tga_goods_brokerage_regulation_2025" for chunk in chunks)
    assert not any(chunk["metadata"]["document_type"] == "region_card" for chunk in chunks)


def test_arabic_warehouse_definition_retrieval_has_citations():
    results = RAGRetriever().search("ما تعريف المستودعات وما حدود استخدام بيانات المستودعات المرخصة؟", top_k=5)
    assert results
    assert any("warehouse" in result["chunk_id"] for result in results)
    assert all(result["citation_label"] for result in results)
    assert all("agency" in result["metadata"] for result in results)


def test_page_aware_pdf_retrieval_preserves_original_page():
    results = RAGRetriever().search("مناولة الحاويات والموانئ السعودية", top_k=8)
    maritime = [result for result in results if result["metadata"]["source_id"] == "kapsarc_container_throughput_2022"]
    assert maritime
    assert all(isinstance(result["metadata"]["page_start"], int) for result in maritime)
    assert all("ص." in result["citation_label"] for result in maritime)


def test_selective_nidlp_ingestion_is_not_full_document_dump():
    manifest = json.loads(Path("data/processed/rag/manifest.json").read_text(encoding="utf-8"))
    nidlp = next(item for item in manifest["sources"] if item["source_id"] == "nidlp_annual_report_2025")
    assert 0 < nidlp["pages_included"] < nidlp["pages_total"]
