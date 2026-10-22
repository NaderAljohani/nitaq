from __future__ import annotations

import pytest

from mizan.tools import (
    build_comparison_view,
    build_port_view,
    build_region_profile_view,
    build_screening_view,
    build_trend_view,
    validate_chart_spec,
)
from mizan.tools.exceptions import MizanInputError


def test_comparison_chart_uses_exact_tool_table_values():
    view = build_comparison_view(
        ["Riyadh", "Makkah", "Qassim"],
        ["delivery_total_2024_source"],
    )
    chart = next(item for item in view["charts"] if item["source_metric_ids"] == ["delivery_total_2024_source"])
    chart_values = {row["region_en"]: row["value"] for row in chart["data"]}
    table_values = {row["region_en"]: row["delivery_total_2024_source"] for row in view["table"]}
    assert chart_values == table_values


def test_profile_chart_uses_exact_quarterly_tool_values():
    view = build_region_profile_view("Riyadh")
    chart = view["charts"][0]
    expected = [row["value"] for row in view["tool_result"]["quarterly_delivery"]]
    assert [row["value"] for row in chart["data"]] == expected


def test_trend_chart_is_long_form_copy_of_tool_table():
    view = build_trend_view(["Riyadh", "Makkah"], "warehouse_count")
    chart_rows = {
        (row["region_en"], row["period"], row["value"])
        for row in view["charts"][0]["data"]
    }
    table_rows = {
        (row["region_en"], row["period"], row["value"])
        for row in view["tool_result"]["table"]
    }
    assert chart_rows == table_rows


def test_port_chart_uses_exact_portwatch_values():
    view = build_port_view(port="SAJED", start="2024-01-01", end="2024-12-01")
    chart = view["charts"][0]
    assert [row["total_activity"] for row in chart["data"]] == [
        row["total_activity"] for row in view["table"]
    ]


def test_inland_port_view_returns_no_chart_not_a_fake_zero():
    view = build_port_view(region="Riyadh")
    assert view["table"] == []
    assert view["charts"] == []


def test_screening_chart_uses_exact_conditional_index():
    view = build_screening_view(
        [
            {"metric_id": "delivery_requests_per_1000_population_2024", "direction": "higher", "weight": 0.5},
            {"metric_id": "warehouse_count_per_100k_population_2024", "direction": "lower", "weight": 0.5},
        ]
    )
    chart_values = {row["region_en"]: row["screening_index_0_100"] for row in view["charts"][0]["data"]}
    table_values = {row["region_en"]: row["screening_index_0_100"] for row in view["table"]}
    assert chart_values == table_values


def test_chart_whitelist_and_declared_columns_are_enforced():
    with pytest.raises(MizanInputError):
        validate_chart_spec(
            {
                "chart_id": "bad",
                "chart_type": "pie",
                "data": [{"x": "a", "y": 1}],
                "x": "x",
                "y": "y",
                "orientation": "vertical",
                "title_ar": "سيئ",
                "title_en": "Bad",
                "unit": "count",
            }
        )
    with pytest.raises(MizanInputError):
        validate_chart_spec(
            {
                "chart_id": "bad_columns",
                "chart_type": "bar",
                "data": [{"x": "a"}],
                "x": "x",
                "y": "y",
                "orientation": "vertical",
                "title_ar": "سيئ",
                "title_en": "Bad",
                "unit": "count",
            }
        )
