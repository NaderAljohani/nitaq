from __future__ import annotations

import math

import pandas as pd
import pytest

from nitaq.tools import (
    MizanRepository,
    compare_ports,
    compare_logistics_gateways,
    compare_regions,
    describe_available_data,
    evaluate_warehouse_locations,
    get_indicator_trend,
    get_modon_context,
    get_metric_source,
    get_port_context,
    get_region_profile,
    identify_missing_data,
    list_logistics_centers,
    screen_regions,
    validate_comparison,
)
from nitaq.tools.exceptions import MizanInputError


@pytest.fixture(scope="module")
def repo() -> MizanRepository:
    return MizanRepository()


def test_repository_is_bound_to_approved_phase1_data(repo: MizanRepository):
    assert len(repo.master) == 13
    assert repo.master["region_en"].nunique() == 13
    assert len(repo.metric_catalog) == 17
    assert repo.master[list(repo.raw_metrics)].isna().sum().sum() == 0


def test_current_logistics_center_snapshot_is_not_mixed_with_2024_statistic(repo: MizanRepository):
    result = list_logistics_centers(repository=repo)
    assert result["snapshot_summary"] == {
        "snapshot_date": "2026-07-28",
        "listed_centers": 59,
        "active_centers": 23,
        "inactive_centers": 36,
        "official_2024_activated_centers": 23,
        "matching_centers": 59,
    }
    distribution = {row["region_en"]: row["total_centers"] for row in result["table"]}
    assert distribution["Eastern Region"] == 17
    assert distribution["Makkah"] == 12
    assert distribution["Riyadh"] == 12
    assert len(result["details"]) == 59


def test_modon_context_uses_structured_owner_and_asset_evidence(repo: MizanRepository):
    result = get_modon_context(repository=repo)
    assert result["snapshot_summary"]["matching_centers"] == 17
    assert len(result["details"]) == 17
    assert all("للمدن الصناعية" in row["owner_ar"] for row in result["details"])
    assert result["industrial_assets"]

    regional = get_modon_context(["Makkah", "Eastern Region"], repository=repo)
    assert set(regional["regions"]) == {"Makkah", "Eastern Region"}
    assert all(row["region_en"] in {"Makkah", "Eastern Region"} for row in regional["table"])
    by_region = {row["region_en"]: row for row in regional["table"]}
    assert by_region["Makkah"]["productive_factories_q4_2023"] > 0
    assert by_region["Eastern Region"]["industrial_city_area_sqm_q2_2024"] > 0
    assert regional["unmapped_industrial_cities"] == []


def test_gateway_analysis_keeps_port_and_center_signals_separate(repo: MizanRepository):
    result = compare_logistics_gateways(
        ["Makkah", "Eastern Region"],
        ports=["SAJED", "SADAM"],
        repository=repo,
    )
    assert result["tool"] == "compare_logistics_gateways"
    assert "score" not in " ".join(result["table"][0])
    rows = {row["region_en"]: row for row in result["table"]}
    assert rows["Makkah"]["covered_port_names_ar"] == "ميناء جدة الإسلامي"
    assert rows["Eastern Region"]["current_listed_centers"] == 17
    assert rows["Makkah"]["mean_monthly_port_activity"] > rows["Eastern Region"]["mean_monthly_port_activity"]


def test_largest_centers_are_ranked_by_recorded_area_at_runtime(repo: MizanRepository):
    result = list_logistics_centers(sort_by="area_desc", limit=3, repository=repo)
    areas = [row["area_sqm_reconciled"] for row in result["details"]]
    assert len(areas) == 3
    assert areas == sorted(areas, reverse=True)
    assert result["snapshot_summary"]["matching_centers"] == 59


def test_available_data_inventory_uses_live_repository_counts(repo: MizanRepository):
    result = describe_available_data(repository=repo)
    assert result["summary"]["regional_metrics"] == 17
    assert result["summary"]["regions"] == 13
    assert result["summary"]["listed_logistics_centers"] == 59
    assert result["summary"]["mapped_ports"] == 12
    assert result["summary"]["ports_with_portwatch"] == 3
    assert len(result["table"]) == 5


def test_region_aliases_and_profile_values_match_master(repo: MizanRepository):
    result = get_region_profile("الرياض", repository=repo)
    expected = repo.master.loc[repo.master["region_en"] == "Riyadh"].iloc[0]
    assert result["region"]["region_en"] == "Riyadh"
    assert result["table"][0]["population_2024"] == expected["population_2024"]
    assert result["table"][0]["delivery_total_2024_source"] == expected["delivery_total_2024_source"]
    assert result["table"][0]["delivery_q4_2024"] == expected["delivery_q4_2024"]
    normalized = {row["metric_id"]: row["value"] for row in result["normalized_values"]}
    assert normalized["warehouse_area_sqm_per_capita_2024"] == expected["warehouse_area_sqm_per_capita_2024"]
    assert result["missing_data_notes"] == ["لا توجد قيم مفقودة في نطاق الاستعلام؛ لم تُستخدم أي إحلالات."]


def test_compare_regions_retains_raw_and_population_normalized_values(repo: MizanRepository):
    result = compare_regions(
        ["Riyadh", "Makkah"],
        ["delivery_total_2024_source", "warehouse_count_2024"],
        repository=repo,
    )
    assert result["metric_ids"] == [
        "delivery_total_2024_source",
        "warehouse_count_2024",
        "delivery_requests_per_1000_population_2024",
        "warehouse_count_per_100k_population_2024",
    ]
    expected = repo.master.set_index("region_en")
    for row in result["table"]:
        assert row["delivery_total_2024_source"] == expected.loc[row["region_en"], "delivery_total_2024_source"]
        assert row["delivery_requests_per_1000_population_2024"] == expected.loc[
            row["region_en"], "delivery_requests_per_1000_population_2024"
        ]
    assert not any("screening_position" in row for row in result["table"])
    assert len(result["pairwise_differences"]) == len(result["metric_ids"])
    delivery_gap = next(
        row for row in result["pairwise_differences"] if row["metric_id"] == "delivery_total_2024_source"
    )
    assert delivery_gap["absolute_gap"] == abs(
        expected.loc["Riyadh", "delivery_total_2024_source"]
        - expected.loc["Makkah", "delivery_total_2024_source"]
    )


def test_city_aliases_resolve_to_administrative_regions(repo: MizanRepository):
    result = compare_regions(
        ["مدينة الرياض", "مدينة جدة"],
        ["delivery_total_2024_source"],
        repository=repo,
    )
    assert result["regions"] == ["Riyadh", "Makkah"]


def test_comparison_validation_blocks_invalid_screening_and_warns_context(repo: MizanRepository):
    both_warehouse = validate_comparison(
        ["Riyadh", "Makkah"],
        [
            "delivery_requests_per_1000_population_2024",
            "warehouse_count_per_100k_population_2024",
            "warehouse_area_sqm_per_capita_2024",
        ],
        purpose="screening",
        repository=repo,
    )
    assert not both_warehouse["ok"]
    assert {item["code"] for item in both_warehouse["errors"]} >= {
        "warehouse_double_count",
        "screening_requires_one_warehouse_family",
    }

    context = validate_comparison(
        ["Riyadh", "Makkah"],
        ["freight_post_licenses_2024"],
        repository=repo,
    )
    assert context["ok"]
    assert "context_only_metric" in {item["code"] for item in context["warnings"]}


def test_screening_is_dynamic_reproducible_and_not_a_fixed_gap_score(repo: MizanRepository):
    criteria = [
        {"metric_id": "delivery_requests_per_1000_population_2024", "direction": "higher", "weight": 0.6},
        {"metric_id": "warehouse_area_sqm_per_capita_2024", "direction": "lower", "weight": 0.4},
    ]
    result = screen_regions(criteria, top_n=5, repository=repo)
    assert len(result["full_table"]) == 13
    assert len({row["screening_position"] for row in result["full_table"]}) == 13
    assert all(0 < row["screening_index_0_100"] <= 100 for row in result["full_table"])
    assert all("gap" not in key.lower() for row in result["full_table"] for key in row)

    frame = repo.master.copy()
    demand = frame[criteria[0]["metric_id"]].rank(method="average", pct=True) * 100
    warehouse = (-frame[criteria[1]["metric_id"]]).rank(method="average", pct=True) * 100
    expected = (demand * 0.6 + warehouse * 0.4).round(6)
    actual = pd.DataFrame(result["full_table"]).set_index("region_en")["screening_index_0_100"]
    expected.index = frame["region_en"]
    for region, value in expected.items():
        assert math.isclose(actual.loc[region], value, abs_tol=1e-6)

    reversed_result = screen_regions(
        [
            {"metric_id": "delivery_requests_per_1000_population_2024", "direction": "lower", "weight": 0.1},
            {"metric_id": "warehouse_area_sqm_per_capita_2024", "direction": "higher", "weight": 0.9},
        ],
        repository=repo,
    )
    assert result["table"][0]["region_en"] != reversed_result["table"][0]["region_en"]


def test_screening_rejects_unapproved_or_redundant_metrics(repo: MizanRepository):
    with pytest.raises(MizanInputError):
        screen_regions(
            [
                {"metric_id": "delivery_requests_per_1000_population_2024", "direction": "higher", "weight": 0.5},
                {"metric_id": "freight_post_licenses_per_100k_population_2024", "direction": "lower", "weight": 0.5},
            ],
            repository=repo,
        )


def test_warehouse_decision_combines_region_and_requested_port_evidence(repo: MizanRepository):
    result = evaluate_warehouse_locations(
        locations=["Jeddah", "Dammam"],
        ports=["SAJED", "SADAM"],
        include_port=True,
        port_metric="trade_volume",
        port_direction="incoming",
        top_n=2,
        repository=repo,
    )
    assert result["ok"]
    assert len(result["table"]) == 2
    assert {row["candidate_en"] for row in result["table"]} == {"Jeddah", "Dammam"}
    assert result["selection"]["port_metric"] == "trade_volume"
    assert result["selection"]["port_direction"] == "incoming"
    assert any(item["metric_id"] == "port_activity" for item in result["criteria"])
    assert [row["decision_position"] for row in result["table"]] == [1, 2]
    assert all(0 < row["decision_index_0_100"] <= 100 for row in result["table"])


def test_quarterly_trend_values_match_source(repo: MizanRepository):
    result = get_indicator_trend(["Riyadh", "Makkah"], "delivery", repository=repo)
    assert len(result["table"]) == 8
    riyadh = [row for row in result["table"] if row["region_en"] == "Riyadh"]
    expected = repo.master.loc[repo.master["region_en"] == "Riyadh"].iloc[0]
    assert [row["value"] for row in riyadh] == [expected[f"delivery_q{q}_2024"] for q in range(1, 5)]
    summary = next(row for row in result["trend_summary"] if row["region_en"] == "Riyadh")
    assert summary["first_period"] == "2024 Q1"
    assert summary["last_period"] == "2024 Q4"
    assert summary["absolute_change"] == expected["delivery_q4_2024"] - expected["delivery_q1_2024"]


def test_port_context_uses_mapping_and_preserves_not_applicable(repo: MizanRepository):
    makkah = get_port_context(region="Makkah", metric="calls", repository=repo)
    assert {row["location"] for row in makkah["table"]} == {"jeddah", "king_abdullah_port"}
    assert len(makkah["table"]) == 178
    assert all(row["total_activity"] is not None for row in makkah["table"])

    inland = get_port_context(region="Riyadh", repository=repo)
    assert inland["table"] == []
    assert any("not_applicable" in note for note in inland["missing_data_notes"])


def test_port_comparison_accepts_common_names_and_calculates_summary(repo: MizanRepository):
    result = compare_ports(["ميناء جدة", "مينا الدمام"], repository=repo)
    assert {port["port_code"] for port in result["ports"]} == {"SAJED", "SADAM"}
    assert len(result["summary"]) == 2
    assert len(result["pairwise_differences"]) == 3
    assert {row["location"] for row in result["table"]} == {"jeddah", "dammam"}


def test_port_comparison_keeps_covered_series_when_yanbu_is_unavailable(repo: MizanRepository):
    result = compare_ports(["ميناء جدة", "ميناء الدمام", "ميناء ينبع"], repository=repo)
    assert result["ok"]
    assert {item["port_code"] for item in result["ports"]} == {"SAJED", "SADAM", "SAYNB"}
    assert [item["port_code"] for item in result["unavailable_ports"]] == ["SAYNB"]
    assert result["pairwise_differences"]
    assert "ميناء ينبع التجاري" in result["missing_data_notes"][0]


def test_metric_source_resolves_derived_dependencies(repo: MizanRepository):
    result = get_metric_source("delivery_requests_per_1000_population_2024", repository=repo)
    assert result["metadata"]["raw_or_derived"] == "derived"
    assert result["metadata"]["formula"] == "delivery_total_2024_source / population_2024 * 1000"
    assert {source["metric_id"] for source in result["sources"]} == {
        "delivery_total_2024_source",
        "population_2024",
    }


def test_missing_data_tool_does_not_confuse_licenses_with_competition(repo: MizanRepository):
    result = identify_missing_data(["المنافسة", "الإيجار", "port"], repository=repo)
    status = {row["concept_id"]: row["status"] for row in result["table"]}
    assert status == {
        "competition": "missing",
        "land_and_rent_cost": "missing",
        "port_activity": "partial_context",
    }
    assert all(row.get("label_en") and row.get("note_en") for row in result["table"])
    assert len(result["alternative_evidence"]) == 3
    assert result["sources"]


def test_unknown_metric_and_duplicate_regions_are_rejected(repo: MizanRepository):
    with pytest.raises(MizanInputError):
        compare_regions(["Riyadh", "Riyadh"], ["population_2024"], repository=repo)
    validation = validate_comparison(["Riyadh"], ["quality_notes_ar"], repository=repo)
    assert not validation["ok"]
    assert "unknown_metric" in {item["code"] for item in validation["errors"]}
