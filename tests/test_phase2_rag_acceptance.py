from __future__ import annotations

import re

import pytest

from mizan.agent.config import AgentConfig
from mizan.agent.orchestrator import MizanAgent
from mizan.rag import RAGRetriever
from mizan.tools.registry import ToolRegistry


WAREHOUSE_SOURCES = {"momah_warehouse_requirements_2025", "logisti_warehouse_technical_guide"}

PHASE2_PDF_ACCEPTANCE = [
    ("ما اشتراطات موقع المستودع؟", WAREHOUSE_SOURCES, None),
    ("ما الحد الأقصى لنسبة فتحات الواجهات الخارجية للمستودع؟", {"momah_warehouse_requirements_2025"}, None),
    ("ما اشتراطات أسطح المستودعات؟", {"momah_warehouse_requirements_2025"}, None),
    ("ما متطلبات السلامة والحريق في المستودعات؟", {"momah_warehouse_requirements_2025"}, None),
    ("ما ضوابط التحميل والتفريغ في المستودع؟", WAREHOUSE_SOURCES, None),
    ("ما متطلبات مواقف الشاحنات ومناورتها؟", WAREHOUSE_SOURCES, None),
    ("كيف تعالج نفايات المستودع؟", WAREHOUSE_SOURCES, None),
    ("ما اشتراطات التهوية والإضاءة؟", WAREHOUSE_SOURCES, None),
    ("ما شروط مستودعات المواد الغذائية؟", WAREHOUSE_SOURCES, None),
    ("ما متطلبات مستودعات المواد الخطرة؟", WAREHOUSE_SOURCES, None),
    ("ما تعريف التخزين في إحصاءات التخزين والخدمات اللوجستية؟", {"gastat_warehousing_methodology_2024"}, None),
    ("ما منهجية إحصاءات التخزين والخدمات اللوجستية؟", {"gastat_warehousing_methodology_2024"}, None),
    ("What methodology is used for Saudi road transport statistics?", {"gastat_road_transport_methodology"}, None),
    ("What does the KAPSARC report say about container throughput trends?", {"kapsarc_container_throughput_2022"}, None),
    ("What policy options support sustainable freight movement in Saudi Arabia?", {"kapsarc_sustainable_freight_2020"}, None),
    ("ما أبرز سياق النقل والخدمات اللوجستية في تقرير ندلب 2025؟", {"nidlp_annual_report_2025"}, None),
    ("ما متطلبات ترخيص الوساطة في نقل البضائع؟", {"tga_goods_brokerage_regulation_2025"}, 6),
    ("ما متطلبات ترخيص الوساطة الإلكترونية في نقل البضائع؟", {"tga_goods_brokerage_regulation_2025"}, 9),
    ("ما الشروط التشغيلية على مقدم خدمة الوساطة؟", {"tga_goods_brokerage_regulation_2025"}, 11),
    ("ما البيانات التي تتضمنها وثيقة الشحن؟", {"tga_goods_brokerage_regulation_2025"}, 12),
    ("ماذا يجب أن يحدد عقد الشحن؟", {"tga_goods_brokerage_regulation_2025"}, 14),
    ("ما التزامات المستفيد في عقد الشحن؟", {"tga_goods_brokerage_regulation_2025"}, 16),
    ("ما التزامات المرسل إليه؟", {"tga_goods_brokerage_regulation_2025"}, 17),
    ("ما عقوبة مخالفة لائحة الوساطة؟", {"tga_goods_brokerage_regulation_2025"}, 19),
    ("كم مدة الاحتفاظ بمستندات عمليات الوساطة؟", {"tga_goods_brokerage_regulation_2025"}, 11),
]


@pytest.fixture(scope="module")
def retriever() -> RAGRetriever:
    return RAGRetriever()


@pytest.mark.parametrize("question,expected_sources,expected_page", PHASE2_PDF_ACCEPTANCE)
def test_phase2_twenty_five_new_pdf_questions(
    retriever: RAGRetriever,
    question: str,
    expected_sources: set[str],
    expected_page: int | None,
) -> None:
    language = "en" if question[0].isascii() else "ar"
    results = retriever.search(question, top_k=5, language=language)
    assert results, question
    top = results[0]
    assert top["metadata"]["source_id"] in expected_sources
    if expected_page is not None:
        assert top["metadata"]["page_start"] == expected_page
    assert top["relevance_confidence"] >= 0.08
    for result in results:
        metadata = result["metadata"]
        assert metadata["citation_verified"] is True
        assert metadata["agency"]
        assert metadata["year"]
        if metadata["source_path"].lower().endswith(".pdf"):
            assert isinstance(metadata["page_start"], int)
            assert f"ص. {metadata['page_start']}" in result["citation_label"]


def test_phase2_dataset_contains_exactly_twenty_five_questions() -> None:
    assert len(PHASE2_PDF_ACCEPTANCE) == 25


def test_phase2_rejects_an_unrelated_weak_passage(retriever: RAGRetriever) -> None:
    assert retriever.search("طريقة طبخ الكبسة", top_k=5, language="ar") == []


@pytest.mark.parametrize(
    "question,language",
    [
        ("ما سياسة النقل المستدام للبضائع؟", "ar"),
        ("What are the official warehouse requirements?", "en"),
    ],
)
def test_phase2_fallback_answer_does_not_mix_languages(question: str, language: str) -> None:
    response = MizanAgent(AgentConfig.from_env(), offline=True).ask(question)
    assert response.citations
    arabic = len(re.findall(r"[\u0600-\u06FF]", response.answer))
    latin = len(re.findall(r"[A-Za-z]", response.answer))
    if language == "ar":
        assert arabic > latin * 2
    else:
        assert latin > arabic * 2


def test_phase2_tool_exposes_source_page_agency_and_year(retriever: RAGRetriever) -> None:
    result, trace = ToolRegistry(retriever).execute(
        "search_knowledge",
        {"query": "ما متطلبات ترخيص الوساطة في نقل البضائع؟", "top_k": 5, "language": "ar"},
    )
    assert trace["status"] == "success"
    assert result["answerable"] is True
    assert result["citations"]
    citation = result["citations"][0]
    assert citation["source_id"] == "tga_goods_brokerage_regulation_2025"
    assert citation["page_start"] == 6
    assert citation["agency"] == "Transport General Authority"
    assert citation["year"] == "2025"
