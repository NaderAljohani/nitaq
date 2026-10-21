"""Deterministic analytics tools for Nitaq.

The package contains no LLM calls. Public tools return JSON-serializable
evidence, tables, provenance, limitations, and deterministic chart specs.
"""

from .repository import MizanRepository, get_repository
from .analytics import (
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
from .views import (
    build_comparison_view,
    build_warehouse_decision_view,
    build_port_view,
    build_port_comparison_view,
    build_region_profile_view,
    build_screening_view,
    build_trend_view,
    validate_chart_spec,
)

__all__ = [
    "MizanRepository",
    "get_repository",
    "get_region_profile",
    "compare_regions",
    "describe_available_data",
    "compare_ports",
    "compare_logistics_gateways",
    "evaluate_warehouse_locations",
    "screen_regions",
    "get_indicator_trend",
    "get_modon_context",
    "get_port_context",
    "get_metric_source",
    "validate_comparison",
    "identify_missing_data",
    "list_logistics_centers",
    "build_comparison_view",
    "build_warehouse_decision_view",
    "build_region_profile_view",
    "build_trend_view",
    "build_port_view",
    "build_port_comparison_view",
    "build_screening_view",
    "validate_chart_spec",
]
