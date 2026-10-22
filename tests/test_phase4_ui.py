from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from streamlit.testing.v1 import AppTest

from mizan.agent import AgentConfig, MizanAgent
from mizan.agent.providers import ProviderError
from mizan.ui import dashboard
from mizan.ui.dashboard import _localize_value, _localized_title, build_dashboard_payload


def _offline_response(question: str) -> dict:
    config = replace(AgentConfig.from_env(), log_enabled=False)
    return MizanAgent(config, offline=True).ask(question).to_dict()


def test_comparison_trace_builds_deterministic_dashboard():
    response = _offline_response("قارن بين الرياض ومكة")
    payload = build_dashboard_payload(response)
    assert payload["kind"] == "view"
    assert payload["tool"] == "compare_regions"
    assert payload["view"]["view_type"] == "comparison"
    assert len(payload["view"]["table"]) == 2
    assert payload["view"]["sources"]
    assert payload["view"]["limitations"]


def test_missing_data_trace_builds_evidence_panel():
    response = _offline_response("هل عندنا بيانات عن الإيجارات والإشغال والربحية حسب المنطقة؟")
    payload = build_dashboard_payload(response)
    assert payload["kind"] == "evidence"
    assert payload["tool"] == "identify_missing_data"
    statuses = {row["status"] for row in payload["result"]["table"]}
    assert "missing" in statuses


def test_center_listing_trace_builds_structured_evidence_panel():
    response = _offline_response("أين توجد المراكز الـ59؟")
    payload = build_dashboard_payload(response)
    assert payload["kind"] == "evidence"
    assert payload["tool"] == "list_logistics_centers"
    assert payload["result"]["snapshot_summary"]["listed_centers"] == 59
    assert len(payload["result"]["details"]) == 59


def test_available_data_trace_builds_live_inventory_panel():
    response = _offline_response("ماهي البيانات المتوفرة؟")
    payload = build_dashboard_payload(response)
    assert payload["kind"] == "evidence"
    assert payload["tool"] == "describe_available_data"
    assert payload["result"]["summary"]["listed_logistics_centers"] == 59


class UnavailableProvider:
    def complete(self, *, model, messages, tools):
        raise ProviderError("test outage")


def test_api_failure_uses_local_evidence_fallback_when_intent_is_known():
    config = replace(AgentConfig.from_env(), log_enabled=False)
    response = MizanAgent(config, provider=UnavailableProvider()).ask("اعطني ملف منطقة الرياض")
    assert response.status == "completed_fallback"
    assert response.tool_trace[-1]["status"] == "success"
    assert "الرياض" in response.answer
    assert "ProviderError" not in response.answer


def test_streamlit_app_runs_and_generates_comparison_dashboard(monkeypatch):
    monkeypatch.setenv("MIZAN_UI_OFFLINE", "1")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "streamlit_app.py", default_timeout=45).run()
    assert not app.exception
    assert "ميزان" in app.title[0].value
    assert len(app.chat_input) == 1

    # Streamlit 1.51 exposes pills as a generic ButtonGroup in AppTest.
    app.get("button_group")[0].set_value("العربية")
    app.get("button_group")[1].set_value([])
    app.chat_input[0].set_value("قارن بين الرياض ومكة").run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assistant_text = "\n".join(item.value for item in app.chat_message[-1].markdown)
    assert "**الخلاصة:**" in assistant_text
    assert "مقارنة موثقة" in assistant_text
    assert "المصادر:" not in assistant_text
    assert "compare_regions" not in assistant_text
    assert len(app.metric) >= 2
    assert len(app.dataframe) == 1
    assert "render_region_map" not in open("mizan/ui/dashboard.py", encoding="utf-8").read()


def test_streamlit_app_renders_current_center_listing_without_document_fallback(monkeypatch):
    monkeypatch.delenv("MIZAN_UI_OFFLINE", raising=False)
    monkeypatch.setenv("MIZAN_UI_OFFLINE", "1")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "streamlit_app.py", default_timeout=45).run()
    app.chat_input[0].set_value("أين توجد المراكز الـ59؟").run()
    assert not app.exception
    assistant_text = "\n".join(item.value for item in app.chat_message[-1].markdown)
    assert "59" in assistant_text
    assert "23" in assistant_text
    assert "36" in assistant_text
    assert "من الوثائق" not in assistant_text
    assert len(app.dataframe) >= 1


def test_streamlit_english_mode_renders_an_english_grounded_answer(monkeypatch):
    monkeypatch.delenv("MIZAN_UI_OFFLINE", raising=False)
    monkeypatch.setenv("MIZAN_UI_OFFLINE", "1")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "streamlit_app.py", default_timeout=45).run()
    app.get("button_group")[0].set_value("English").run()
    assert app.chat_input[0].placeholder.startswith("Ask Mizan")

    app.chat_input[0].set_value("Compare delivery demand in Riyadh and Makkah.").run()
    assert not app.exception
    assistant_text = "\n".join(item.value for item in app.chat_message[-1].markdown)
    assert "**Summary:**" in assistant_text
    assert "Riyadh" in assistant_text and "Makkah" in assistant_text
    assert "**الخلاصة:**" not in assistant_text
    assert len(app.dataframe) == 1


def test_chart_labels_are_localized_for_regions_periods_and_indicators():
    assert _localize_value("Eastern Region") == "المنطقة الشرقية"
    assert _localize_value("2024 Q1") == "الربع الأول 2024"
    assert _localized_title("اتجاه المؤشر — delivery_requests") == "اتجاه المؤشر — طلبات التوصيل"


def test_altair_charts_validate_and_do_not_use_negative_baseline(monkeypatch):
    charts = []
    monkeypatch.setattr(dashboard.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard.st, "altair_chart", lambda chart, *args, **kwargs: charts.append(chart.to_dict()))

    dashboard.render_chart(
        {
            "chart_type": "line",
            "data": [
                {"period": "2024 Q1", "region_en": "Makkah", "value": 10},
                {"period": "2024 Q2", "region_en": "Makkah", "value": 12},
            ],
            "x": "period",
            "y": "value",
            "color": "region_en",
            "title_ar": "اتجاه المؤشر — delivery_requests",
            "unit": "request",
        }
    )
    dashboard.render_chart(
        {
            "chart_type": "bar",
            "data": [{"region_en": "Eastern Region", "value": 8}],
            "x": "value",
            "y": "region_en",
            "color": None,
            "orientation": "horizontal",
            "title_ar": "مقارنة",
            "unit": "request",
        }
    )

    assert len(charts) == 2
    assert charts[0]["encoding"]["y"]["scale"]["zero"] is True
    assert charts[1]["encoding"]["x"].get("stack") is None
    line_rows = list(charts[0]["datasets"].values())[0]
    assert line_rows[0]["السلسلة"] == "مكة المكرمة"


def test_chart_skips_empty_and_non_finite_numeric_data(monkeypatch):
    charts = []
    captions = []
    monkeypatch.setattr(dashboard.st, "markdown", lambda *args, **kwargs: None)
    monkeypatch.setattr(dashboard.st, "caption", lambda value, *args, **kwargs: captions.append(value))
    monkeypatch.setattr(dashboard.st, "altair_chart", lambda chart, *args, **kwargs: charts.append(chart))

    dashboard.render_chart(
        {
            "chart_type": "line",
            "data": [
                {"period": "2024 Q1", "region_en": "Makkah", "value": None},
                {"period": "2024 Q2", "region_en": "Makkah", "value": float("inf")},
            ],
            "x": "period",
            "y": "value",
            "color": "region_en",
            "title_ar": "بيانات غير صالحة للرسم",
            "unit": "request",
        }
    )

    assert charts == []
    assert any("لا توجد قيم رقمية صالحة" in caption for caption in captions)


def test_landing_page_shows_documented_coverage_in_both_languages(monkeypatch):
    monkeypatch.setenv("MIZAN_UI_OFFLINE", "1")
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "streamlit_app.py", default_timeout=45).run()
    assert not app.exception
    assert [metric.value for metric in app.metric] == ["13", "17", "AR / EN"]
    app.get("button_group")[0].set_value("English").run()
    assert "Mizan" in app.title[0].value
    assert [metric.label for metric in app.metric] == ["Regions", "Source metrics", "Languages"]


def test_chat_uses_bottom_dock_natural_scroll_and_language_direction_styles():
    app_source = open("streamlit_app.py", encoding="utf-8").read()
    css = open("mizan/ui/theme.css", encoding="utf-8").read()
    assert 'key=f"mizan_chat_input_{ui_language}"' in app_source
    assert 'height="content"' in app_source
    assert 'key=f"mizan_direction_{ui_language}"' in app_source
    assert ".st-key-mizan_direction_ar" in css
    assert ".st-key-mizan_chat_input_ar" in css
    assert "direction: rtl" in css
