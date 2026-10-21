from __future__ import annotations

import json
import math
import re
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
BUILD = ROOT / "outputs" / "build"
CHARTS = BUILD / "charts"
AUDIT = BUILD
METRIC_CARDS = ROOT / "knowledge" / "cards" / "metrics"
REGION_CARDS = ROOT / "knowledge" / "cards" / "regions"
TMP = BUILD / "temp"

MASTER_PATH = PROCESSED / "mizan_region_master_2024.csv"
CATALOG_PATH = PROCESSED / "mizan_metric_catalog.csv"

GASTAT_2024_URL = "https://stats.gov.sa/en/w/warehousing-and-logistics-statistics-2024"
GASTAT_2023_URL = "https://www.stats.gov.sa/documents/20117/2435267/Warehousing%2Band%2BLogistics%2BStatistics%2B2023-EN.pdf/bf8913b5-1064-e819-7285-810ddb046761?t=1735202770651"
KAPSARC_POP_URL = "https://data.kapsarc.org/explore/dataset/saudi-arabia-population-by-administrative-region-nationality-and-sex/table/?flg=en-gb"


POLICY = {
    "population_2023": ("denominator", "context_only", "none", "population", "سياق وحساب النمو فقط؛ ليس مؤشرًا لوجستيًا."),
    "population_2024": ("denominator", "context_only", "none", "population", "مقام التطبيع السكاني؛ لا يدخل وحده في Screening."),
    "delivery_q1_2024": ("secondary", "trend_only", "per_1000_population", "delivery_quarters", "يستخدم مع بقية الأرباع لفهم المسار داخل 2024، ولا يعامل كإشارة مستقلة."),
    "delivery_q2_2024": ("secondary", "trend_only", "per_1000_population", "delivery_quarters", "يستخدم مع بقية الأرباع لفهم المسار داخل 2024، ولا يعامل كإشارة مستقلة."),
    "delivery_q3_2024": ("secondary", "trend_only", "per_1000_population", "delivery_quarters", "يستخدم مع بقية الأرباع لفهم المسار داخل 2024، ولا يعامل كإشارة مستقلة."),
    "delivery_q4_2024": ("secondary", "trend_only", "per_1000_population", "delivery_quarters", "يستخدم مع بقية الأرباع لفهم المسار داخل 2024، ولا يعامل كإشارة مستقلة."),
    "delivery_total_2024_source": ("primary_candidate", "direct_with_caveat", "per_1000_population", "delivery_annual", "أفضل إشارة طلب حالية، لكن أساس إسناد المنطقة غير موضح تفصيليًا ولا يمثل كامل الطلب المحتمل."),
    "warehouse_count_2023": ("baseline", "change_only", "per_100k_population", "warehouse_footprint", "خط أساس لحساب التغير؛ لا يخلط مع قيمة 2024 كإشارتين مستقلتين."),
    "warehouse_count_2024": ("primary_candidate", "direct_with_caveat", "per_100k_population", "warehouse_footprint", "بصمة منشآت مرخصة وليست توافرًا أو إشغالًا؛ لا يكرر وزنه مع مساحة المستودعات."),
    "warehouse_area_sqm_2023": ("baseline", "change_only", "sqm_per_capita", "warehouse_footprint", "خط أساس لحساب تغير المساحة المرخصة."),
    "warehouse_area_sqm_2024": ("primary_candidate", "direct_with_caveat", "sqm_per_capita", "warehouse_footprint", "أفضل تمثيل لحجم البصمة الترخيصية، لا للسعة التشغيلية؛ لا يكرر وزنه مع العدد."),
    "freight_post_licenses_2023": ("baseline", "change_only", "per_100k_population", "licenses", "خط أساس إداري لحساب تغير التراخيص."),
    "freight_post_licenses_2024": ("context", "context_only", "per_100k_population", "licenses", "منطقة تسجيل الترخيص لا تثبت مكان التشغيل؛ يعرض كإشارة نشاط إداري فقط."),
    "activated_logistics_centers_2023": ("baseline", "change_only", "raw_count", "activated_centers", "خط أساس لبرنامج صغير ومتركز مكانيًا."),
    "activated_logistics_centers_2024": ("context", "context_only", "raw_count_and_presence", "activated_centers", "موقع أصل فعلي، لكن العدد صغير وصفره لا يعني غياب كل البنية اللوجستية."),
    "activated_logistics_centers_area_sqm_2023": ("baseline", "change_only", "raw_area", "activated_centers", "خط أساس لمساحة المراكز المفعلة."),
    "activated_logistics_centers_area_sqm_2024": ("context", "context_only", "raw_area", "activated_centers", "شديد الارتباط بعدد المراكز ومتركز في مناطق محدودة؛ سياق لا مكوّن ترتيب."),
}


ANALYSIS_FEATURES = {
    "delivery_requests_per_1000_population_2024": "طلبات التوصيل لكل 1,000 نسمة",
    "warehouse_count_per_100k_population_2024": "المستودعات المرخصة لكل 100 ألف نسمة",
    "warehouse_area_sqm_per_capita_2024": "مساحة المستودعات المرخصة للفرد",
    "freight_post_licenses_per_100k_population_2024": "التراخيص لكل 100 ألف نسمة",
    "activated_logistics_centers_per_million_population_2024": "المراكز المفعلة لكل مليون نسمة — عرض وصفي فقط",
    "delivery_q4_vs_q1_growth_pct": "تغير التوصيل Q4 مقابل Q1 — ليس نموًا سنويًا",
    "warehouse_count_growth_pct": "تغير عدد المستودعات 2023–2024",
    "warehouse_area_growth_pct": "تغير مساحة المستودعات 2023–2024",
    "freight_post_licenses_growth_pct": "تغير التراخيص 2023–2024",
    "delivery_requests_per_warehouse_sqm_2024": "طلبات لكل م² مستودع مرخص — استكشافي",
    "delivery_requests_per_freight_post_license_2024": "طلبات لكل ترخيص — استكشافي",
}

CORRELATION_LABELS = {
    "delivery_requests_per_1000_population_2024": "Delivery / 1k residents",
    "warehouse_count_per_100k_population_2024": "Warehouses / 100k residents",
    "warehouse_area_sqm_per_capita_2024": "Warehouse m² / resident",
    "freight_post_licenses_per_100k_population_2024": "Licenses / 100k residents",
    "activated_logistics_centers_per_million_population_2024": "Activated centers / 1m residents",
}


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def fmt(value: float | int | None, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "null"
    if float(value).is_integer():
        return f"{int(value):,}"
    return f"{float(value):,.{digits}f}"


def iqr_outliers(series: pd.Series) -> tuple[float, float, pd.Series]:
    clean = series.dropna().astype(float)
    q1, q3 = clean.quantile([0.25, 0.75])
    iqr = q3 - q1
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return float(low), float(high), (series < low) | (series > high)


def write_cards(master: pd.DataFrame, catalog: pd.DataFrame, outliers: pd.DataFrame) -> None:
    outlier_map: dict[str, list[str]] = {}
    for row in outliers.itertuples(index=False):
        outlier_map.setdefault(row.region_en, []).append(row.feature_id)

    for row in catalog.to_dict("records"):
        metric_id = row["metric_id"]
        policy = POLICY[metric_id]
        content = f"""---
card_type: metric
metric_id: {metric_id}
year: {row['year']}
indicator_type: {row['indicator_type_en']}
screening_role: {policy[0]}
comparability: {policy[1]}
normalization: {policy[2]}
redundancy_group: {policy[3]}
source_agency: {row['source_agency']}
table_number: {row['table_number']}
---

# {row['metric_name_ar']}

- **الوحدة:** {row['unit']}
- **الفترة:** {row['period']}
- **التغطية:** 13 من 13 منطقة.
- **نوع المؤشر:** {row['indicator_type_ar']}.
- **أساس الإسناد الجغرافي:** {row['geographic_basis_ar']}.
- **هل يقيس مكان النشاط؟** {row['measures_activity_location']}.
- **قاعدة التطبيع:** {policy[2]}.
- **قرار المقارنة:** {policy[1]}.
- **دوره في Screening:** {policy[0]}.

## التعريف

{row['definition_ar']}

## حدود الاستخدام

{row['limitation_ar']}

## قرار الفيز 1

{policy[4]}

## المصدر

- الملف: `{row['source_file']}`
- الجدول: {row['table_number']}
- الرابط: {row['source_url']}
"""
        (METRIC_CARDS / f"{metric_id}.md").write_text(content, encoding="utf-8")

    for row in master.to_dict("records"):
        flags = outlier_map.get(row["region_en"], [])
        flags_text = ", ".join(flags) if flags else "لا توجد إشارة شذوذ آلية وفق IQR في الخصائص المختبرة."
        content = f"""---
card_type: region
region_id: {row['region_id']}
region_en: {row['region_en']}
region_ar: {row['region_ar']}
reference_year: 2024
---

# {row['region_ar']} — {row['region_en']}

هذه بطاقة أدلة وصفية وليست ترتيبًا أو توصية استثمارية.

## لقطة 2024

- السكان: {fmt(row['population_2024'])} نسمة.
- طلبات التوصيل المنفذة: {fmt(row['delivery_total_2024_source'])}.
- الطلبات لكل 1,000 نسمة: {fmt(row['delivery_requests_per_1000_population_2024'])}.
- المستودعات التجارية المرخصة: {fmt(row['warehouse_count_2024'])}.
- مساحة المستودعات المرخصة: {fmt(row['warehouse_area_sqm_2024'])} م².
- مساحة المستودعات المرخصة للفرد: {fmt(row['warehouse_area_sqm_per_capita_2024'], 3)} م².
- تراخيص نقل البضائع والبريد: {fmt(row['freight_post_licenses_2024'])}.
- المراكز اللوجستية المفعلة: {fmt(row['activated_logistics_centers_2024'])}.
- مساحة المراكز المفعلة: {fmt(row['activated_logistics_centers_area_sqm_2024'])} م².

## إشارات التغير

- تغير التوصيل Q4 مقابل Q1: {fmt(row['delivery_q4_vs_q1_growth_pct'] * 100)}% — تغير داخل السنة وليس نموًا سنويًا.
- تغير عدد المستودعات 2023–2024: {fmt(row['warehouse_count_growth_pct'] * 100)}%.
- تغير مساحة المستودعات 2023–2024: {fmt(row['warehouse_area_growth_pct'] * 100)}%.
- تغير التراخيص 2023–2024: {fmt(row['freight_post_licenses_growth_pct'] * 100)}%.

## إشارات تتطلب انتباهًا

{flags_text}

## القيود الإلزامية

- المستودعات تقيس التراخيص والمساحة المرخصة، لا الإشغال أو السعة التشغيلية.
- التراخيص مرتبطة بالتسجيل ولا تثبت مكان تنفيذ النشاط.
- أساس إسناد طلبات التوصيل للمنطقة غير موضح تفصيليًا في الجدول.
- المراكز المفعلة سياق لبرنامج محدد؛ الصفر لا يعني غياب كل أصل لوجستي.
- لا توجد بيانات تكلفة أو ربحية أو منافسة إقليمية كافية.
"""
        (REGION_CARDS / f"{safe_slug(row['region_en'])}.md").write_text(content, encoding="utf-8")


def create_charts(master: pd.DataFrame, corr: pd.DataFrame) -> None:
    plt.rcParams.update({"font.size": 9, "figure.dpi": 150})
    green, gold, gray = "#0B5D46", "#C69B32", "#667085"

    plot = master.sort_values("delivery_requests_per_1000_population_2024")
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(plot["region_en"], plot["delivery_requests_per_1000_population_2024"], color=green)
    ax.set_title("Executed delivery requests per 1,000 residents (2024)")
    ax.set_xlabel("requests per 1,000 residents")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(CHARTS / "delivery_per_1000_2024.png", bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    specs = [
        ("warehouse_count_per_100k_population_2024", "Licensed warehouses per 100k residents", green),
        ("warehouse_area_sqm_per_capita_2024", "Licensed warehouse area per resident (m²)", gold),
    ]
    for ax, (column, title, color) in zip(axes, specs):
        plot = master.sort_values(column)
        ax.barh(plot["region_en"], plot[column], color=color)
        ax.set_title(title)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Two related views of the licensed warehouse footprint — do not double-count")
    fig.tight_layout()
    fig.savefig(CHARTS / "warehouse_footprint_2024.png", bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(13, 6))
    specs = [
        ("delivery_q4_vs_q1_growth_pct", "Delivery change: Q4 vs Q1 2024", green),
        ("warehouse_area_growth_pct", "Licensed warehouse area change: 2023–2024", gold),
    ]
    for ax, (column, title, color) in zip(axes, specs):
        plot = master.sort_values(column)
        ax.barh(plot["region_en"], plot[column] * 100, color=np.where(plot[column] >= 0, color, gray))
        ax.axvline(0, color="#333333", linewidth=0.8)
        ax.set_title(title)
        ax.set_xlabel("percent")
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Change signals are descriptive and use different time concepts")
    fig.tight_layout()
    fig.savefig(CHARTS / "change_signals.png", bbox_inches="tight")
    plt.close(fig)

    labels = [CORRELATION_LABELS[c] for c in corr.columns]
    fig, ax = plt.subplots(figsize=(10, 8))
    image = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdYlGn")
    ax.set_xticks(range(len(labels)), labels, rotation=45, ha="right")
    ax.set_yticks(range(len(labels)), labels)
    for i in range(len(labels)):
        for j in range(len(labels)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}", ha="center", va="center", fontsize=7)
    ax.set_title("Spearman correlations among normalized 2024 indicators")
    fig.colorbar(image, ax=ax, shrink=0.75)
    fig.tight_layout()
    fig.savefig(CHARTS / "normalized_correlations_2024.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    for directory in (CHARTS, AUDIT, METRIC_CARDS, REGION_CARDS, TMP):
        directory.mkdir(parents=True, exist_ok=True)

    master = pd.read_csv(MASTER_PATH)
    catalog = pd.read_csv(CATALOG_PATH).fillna("")

    assert len(master) == 13
    assert master["region_id"].nunique() == 13
    assert master["region_en"].nunique() == 13
    assert not master["region_en"].duplicated().any()
    assert set(catalog["metric_id"]) == set(POLICY)
    assert master["delivery_total_matches_quarters"].all()
    assert not any("score" in c.lower() or "rank" in c.lower() for c in master.columns)

    source_url_by_metric = {}
    for metric_id in catalog["metric_id"]:
        if metric_id.startswith("population"):
            source_url_by_metric[metric_id] = KAPSARC_POP_URL
        elif metric_id.endswith("2023") and metric_id.startswith("freight"):
            source_url_by_metric[metric_id] = GASTAT_2023_URL
        else:
            source_url_by_metric[metric_id] = GASTAT_2024_URL
    catalog["source_url"] = catalog["metric_id"].map(source_url_by_metric)

    quality_rows = []
    for item in catalog.to_dict("records"):
        metric_id = item["metric_id"]
        values = master[metric_id]
        low, high, outlier_mask = iqr_outliers(values)
        role, comparability, normalization, group, rationale = POLICY[metric_id]
        quality_rows.append({
            "metric_id": metric_id,
            "metric_name_ar": item["metric_name_ar"],
            "indicator_type_ar": item["indicator_type_ar"],
            "coverage_regions": int(values.notna().sum()),
            "coverage_pct": float(values.notna().mean()),
            "missing_count": int(values.isna().sum()),
            "observed_zero_count": int((values == 0).sum()),
            "iqr_outlier_count": int(outlier_mask.sum()),
            "measures_activity_location": item["measures_activity_location"],
            "geographic_basis_ar": item["geographic_basis_ar"],
            "screening_role": role,
            "comparability": comparability,
            "normalization_rule": normalization,
            "redundancy_group": group,
            "phase1_decision_ar": rationale,
        })
    quality = pd.DataFrame(quality_rows)

    outlier_rows = []
    for feature_id, label in ANALYSIS_FEATURES.items():
        low, high, mask = iqr_outliers(master[feature_id])
        for row in master.loc[mask, ["region_id", "region_en", "region_ar", feature_id]].to_dict("records"):
            outlier_rows.append({
                "region_id": row["region_id"],
                "region_en": row["region_en"],
                "region_ar": row["region_ar"],
                "feature_id": feature_id,
                "feature_label_ar": label,
                "value": row[feature_id],
                "iqr_lower_fence": low,
                "iqr_upper_fence": high,
                "interpretation_ar": "إشارة مراجعة وليست خطأ؛ تُعرض مع القيمة الخام وحجم المقام ولا تُحذف أو تُقص تلقائيًا.",
            })
    outliers = pd.DataFrame(outlier_rows)

    corr_features = [
        "delivery_requests_per_1000_population_2024",
        "warehouse_count_per_100k_population_2024",
        "warehouse_area_sqm_per_capita_2024",
        "freight_post_licenses_per_100k_population_2024",
        "activated_logistics_centers_per_million_population_2024",
    ]
    corr = master[corr_features].corr(method="spearman")
    corr_long = corr.stack().reset_index()
    corr_long.columns = ["metric_a", "metric_b", "spearman_rho"]
    corr_long = corr_long[corr_long["metric_a"] < corr_long["metric_b"]].sort_values(
        "spearman_rho", key=lambda s: s.abs(), ascending=False
    )

    extended_catalog = catalog.merge(
        quality[[
            "metric_id", "coverage_regions", "coverage_pct", "missing_count", "observed_zero_count",
            "iqr_outlier_count", "screening_role", "comparability", "normalization_rule",
            "redundancy_group", "phase1_decision_ar",
        ]],
        on="metric_id",
        how="left",
    )

    quality.to_csv(PROCESSED / "mizan_phase1_metric_quality.csv", index=False, encoding="utf-8-sig")
    extended_catalog.to_csv(PROCESSED / "mizan_metric_catalog_phase1.csv", index=False, encoding="utf-8-sig")
    outliers.to_csv(PROCESSED / "mizan_phase1_outliers.csv", index=False, encoding="utf-8-sig")
    corr_long.to_csv(PROCESSED / "mizan_phase1_correlations_spearman.csv", index=False, encoding="utf-8-sig")

    create_charts(master, corr)
    write_cards(master, extended_catalog, outliers)

    top_corr = corr_long.iloc[0].to_dict()
    validation = {
        "phase": 1,
        "master_dataset": str(MASTER_PATH.relative_to(ROOT)),
        "status": "approved_for_evidence_exploration_and_limited_screening",
        "region_count": int(len(master)),
        "unique_region_count": int(master["region_en"].nunique()),
        "duplicate_regions": int(master["region_en"].duplicated().sum()),
        "raw_metric_count": int(len(catalog)),
        "raw_missing_value_count": int(master[list(POLICY)].isna().sum().sum()),
        "all_delivery_totals_match_quarters": bool(master["delivery_total_matches_quarters"].all()),
        "contains_gap_score_or_rank": any("score" in c.lower() or "rank" in c.lower() for c in master.columns),
        "metric_cards_created": int(len(list(METRIC_CARDS.glob("*.md")))),
        "region_cards_created": int(len(list(REGION_CARDS.glob("*.md")))),
        "outlier_flags": int(len(outliers)),
        "strongest_normalized_pair": top_corr,
        "screening_gate": {
            "passed_with_restrictions": True,
            "allowed_primary_signal": "delivery_total_2024_source normalized per 1,000 population",
            "allowed_supply_family": "choose warehouse count per 100k OR licensed area per capita; do not double-count",
            "context_only": ["freight/post licenses", "activated logistics centers", "PortWatch"],
            "prohibited_claims": ["best region", "proven capacity shortage", "investment recommendation", "budget fit", "profitability"],
        },
        "checks_pass": True,
    }
    (AUDIT / "mizan_phase1_validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    payload = {
        "master": master.replace({np.nan: None}).to_dict("records"),
        "metric_quality": quality.replace({np.nan: None}).to_dict("records"),
        "metric_catalog": extended_catalog.replace({np.nan: None}).to_dict("records"),
        "outliers": outliers.replace({np.nan: None}).to_dict("records"),
        "correlations": corr_long.replace({np.nan: None}).to_dict("records"),
        "validation": validation,
    }
    (TMP / "phase1_workbook_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
