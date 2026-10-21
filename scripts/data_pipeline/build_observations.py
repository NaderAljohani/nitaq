from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data/processed"
BUILD = ROOT / "outputs/build"
TMP = BUILD / "temp"

MASTER_CSV = PROCESSED / "mizan_region_master_2024.csv"
OUT_CSV = PROCESSED / "mizan_region_observations_2023_2024.csv"
OUT_JSON = PROCESSED / "mizan_region_observations_2023_2024.json"
OUT_CATALOG = PROCESSED / "mizan_metric_catalog.csv"
OUT_QA = BUILD / "mizan_region_observations_validation.json"
OUT_BUNDLE = TMP / "mizan_region_observations_bundle.json"

CANONICAL_REGIONS = [
    (1, "Riyadh", "الرياض"),
    (2, "Makkah", "مكة المكرمة"),
    (3, "Madinah", "المدينة المنورة"),
    (4, "Qassim", "القصيم"),
    (5, "Eastern Region", "المنطقة الشرقية"),
    (6, "Aseer", "عسير"),
    (7, "Tabuk", "تبوك"),
    (8, "Hail", "حائل"),
    (9, "Northern Borders", "الحدود الشمالية"),
    (10, "Jazan", "جازان"),
    (11, "Najran", "نجران"),
    (12, "Al-Baha", "الباحة"),
    (13, "Al-Jouf", "الجوف"),
]

GASTAT_PUBLICATION = "Warehousing and Logistics Statistics"
GASTAT_PUBLISHER = "General Authority for Statistics (GASTAT)"
GASTAT_2024_URL = "https://stats.gov.sa/en/w/warehousing-and-logistics-statistics-2024"
GASTAT_2023_URL = "https://www.stats.gov.sa/documents/20117/2435267/Warehousing%2Band%2BLogistics%2BStatistics%2B2023-EN.pdf/bf8913b5-1064-e819-7285-810ddb046761?t=1735202770651"
KAPSARC_POPULATION_URL = "https://datasource.kapsarc.org/explore/dataset/saudi-arabia-population-by-administrative-region-nationality-and-sex/"


def metric(
    metric_id: str,
    name_ar: str,
    name_en: str,
    unit: str,
    year: int,
    period: str,
    periodicity: str,
    indicator_type_ar: str,
    indicator_type_en: str,
    source_agency: str,
    publisher: str,
    source_dataset: str,
    source_file: str,
    table_number: str,
    definition_ar: str,
    limitation_ar: str,
    geographic_basis: str,
    geographic_basis_ar: str,
    geographic_basis_note_ar: str,
    measures_activity_location: str,
    zero_semantics_ar: str,
    relationship_note_ar: str = "",
    source_url: str | None = None,
) -> dict:
    if source_url is None:
        if publisher == "KAPSARC":
            source_url = KAPSARC_POPULATION_URL
        elif source_file.endswith("gastat_warehousing_logistics_2023_en.xlsx"):
            source_url = GASTAT_2023_URL
        elif publisher == GASTAT_PUBLISHER:
            source_url = GASTAT_2024_URL
    return {
        "metric_id": metric_id,
        "metric_name_ar": name_ar,
        "metric_name_en": name_en,
        "unit": unit,
        "year": year,
        "period": period,
        "periodicity": periodicity,
        "indicator_type_ar": indicator_type_ar,
        "indicator_type_en": indicator_type_en,
        "source_agency": source_agency,
        "publisher": publisher,
        "source_dataset": source_dataset,
        "source_file": source_file,
        "table_number": table_number,
        "source_url": source_url,
        "definition_ar": definition_ar,
        "limitation_ar": limitation_ar,
        "geographic_basis": geographic_basis,
        "geographic_basis_ar": geographic_basis_ar,
        "geographic_basis_note_ar": geographic_basis_note_ar,
        "measures_activity_location": measures_activity_location,
        "zero_semantics_ar": zero_semantics_ar,
        "missing_value_policy": "null — لا يُستبدل بصفر",
        "relationship_note_ar": relationship_note_ar,
        "raw_or_derived": "raw",
        "quality_tier": "official_administrative_record" if publisher == GASTAT_PUBLISHER else "public_data_platform",
    }


CATALOG = [
    metric(
        f"population_{year}", f"عدد سكان المنطقة في {year}", f"Regional population {year}", "person",
        year, str(year), "annual", "سياق", "context", "KAPSARC Data Portal", "KAPSARC",
        "Saudi Arabia Population by Administrative Region, Nationality and Sex",
        "data/raw/core/saudi-arabia-population-by-administrative-region-nationality-and-sex.xlsx", "Sheet1; Gender=Total",
        "إجمالي السكان المنشور للمنطقة الإدارية مع اختيار الجنس = الإجمالي.",
        "تقدير سكاني سنوي وليس قياسًا للنشاط اللوجستي. لا تستخدم استعادة السكان من كثافة الطرق بديلًا إقليميًا لعام 2023.",
        "regional_population_estimate", "تقدير السكان حسب المنطقة الإدارية",
        "يقيس السكان المنسوبين للمنطقة، وليس مكان تنفيذ نشاط لوجستي.", "no",
        "الصفر غير متوقع لسكان منطقة؛ إن ظهر يُعامل كإشارة جودة لا كقيمة طبيعية.",
    ) for year in (2023, 2024)
] + [
    metric(
        f"delivery_q{q}_2024", f"طلبات التوصيل المنفذة في الربع {q}", f"Executed delivery orders Q{q} 2024",
        "executed request", 2024, f"2024 Q{q}", "quarterly", "طلب", "demand",
        "Transport General Authority", GASTAT_PUBLISHER, f"{GASTAT_PUBLICATION} 2024",
        "data/raw/core/gastat_warehousing_logistics_2024_en.xlsx", "Table 13",
        "عدد الطلبات المنفذة لأنشطة التوصيل المرخصة والمنشورة حسب المنطقة الإدارية والربع.",
        "يمثل طلبًا محققًا عبر أنشطة مرخصة، وليس كل الطلب المحتمل أو التجارة الإلكترونية، ولا يبيّن حجم أو قيمة الشحنة.",
        "reported_delivery_region", "المنطقة المسند إليها طلب التوصيل في السجل",
        "المصدر لا يوضح في الجدول هل الإسناد يعتمد على نقطة التسليم أو مقر مقدم الخدمة؛ لذلك لا نجزم بأنه مكان النشاط الفعلي بالكامل.",
        "unclear", "صفر يعني عدم تسجيل طلبات منفذة في السجل للفترة، ولا يعني تلقائيًا غياب الطلب الحقيقي.",
        "الأرباع الأربعة تجمع إلى إجمالي 2024 المنشور.",
    ) for q in range(1, 5)
] + [
    metric(
        "delivery_total_2024_source", "إجمالي طلبات التوصيل المنفذة لعام 2024", "Executed delivery orders total 2024",
        "executed request", 2024, "2024", "annual", "طلب", "demand", "Transport General Authority",
        GASTAT_PUBLISHER, f"{GASTAT_PUBLICATION} 2024", "data/raw/core/gastat_warehousing_logistics_2024_en.xlsx",
        "Table 13", "الإجمالي السنوي المنشور لطلبات التوصيل المنفذة لأنشطة التوصيل المرخصة حسب المنطقة.",
        "يتكرر مفهوميًا مع مجموع الأرباع ويُحتفظ به للتحقق، ولا يدخل معه مرة ثانية في أي نموذج مستقبلي.",
        "reported_delivery_region", "المنطقة المسند إليها طلب التوصيل في السجل",
        "المصدر لا يوضح في الجدول هل الإسناد يعتمد على نقطة التسليم أو مقر مقدم الخدمة.", "unclear",
        "صفر يعني عدم تسجيل طلبات منفذة في السجل السنوي، ولا يثبت غياب الطلب الحقيقي.",
        "يساوي مجموع Q1+Q2+Q3+Q4 لكل منطقة؛ متغير تجميعي لا مؤشر مستقل عن الأرباع.",
    ),
] + [
    metric(
        f"warehouse_count_{year}", f"عدد المستودعات التجارية المرخصة في {year}", f"Licensed commercial warehouses {year}",
        "licensed warehouse", year, str(year), "annual", "عرض", "supply", "Ministry of Municipalities and Housing",
        GASTAT_PUBLISHER, f"{GASTAT_PUBLICATION} 2024", "data/raw/core/gastat_warehousing_logistics_2024_en.xlsx",
        "Table 5", "عدد المستودعات التجارية المرخصة المنشورة حسب المنطقة الإدارية.",
        "يقيس التراخيص/المنشآت المرخصة، ولا يقيس الإشغال أو الطاقة التشغيلية أو جودة المستودع.",
        "licensed_facility_region", "منطقة المنشأة المرخصة",
        "يرتبط بموقع المستودع المرخص حسب عنوان الجدول، لكنه لا يثبت أن المستودع عامل أو مشغول خلال السنة.", "partial",
        "صفر يعني عدم ظهور مستودع مرخص في السجل، ولا يعني بالضرورة عدم وجود تخزين غير مشمول أو غير مرخص.",
        "قيمة 2023 في إصدار 2024 مطابقة لـTable 5 من إصدار 2023.",
    ) for year in (2023, 2024)
] + [
    metric(
        f"warehouse_area_sqm_{year}", f"مساحة المستودعات التجارية المرخصة في {year}", f"Licensed warehouse area {year}",
        "square meter", year, str(year), "annual", "عرض", "supply", "Ministry of Municipalities and Housing",
        GASTAT_PUBLISHER, f"{GASTAT_PUBLICATION} 2024", "data/raw/core/gastat_warehousing_logistics_2024_en.xlsx",
        "Table 5", "إجمالي المساحة المرخصة للمستودعات التجارية حسب المنطقة الإدارية.",
        "مساحة ترخيصية وليست مساحة مشغولة أو سعة تخزين تشغيلية؛ قد تختلف كفاءة الاستخدام حسب نوع المستودع.",
        "licensed_facility_region", "منطقة المنشأة المرخصة",
        "ترتبط بموقع المستودع المرخص، لكنها لا تقيس نشاطه أو إشغاله الفعلي.", "partial",
        "صفر يعني عدم وجود مساحة مرخصة مسجلة، ولا يثبت غياب كل مساحات التخزين.",
        "قيمة 2023 في إصدار 2024 مطابقة لـTable 5 من إصدار 2023.",
    ) for year in (2023, 2024)
] + [
    metric(
        f"freight_post_licenses_{year}", f"تراخيص نقل البضائع والخدمات البريدية النشطة في {year}",
        f"Active freight and postal transport licenses {year}", "active license", year, f"end-{year}", "annual_snapshot",
        "نشاط", "activity", "Transport General Authority", GASTAT_PUBLISHER,
        f"{GASTAT_PUBLICATION} {year}", f"data/raw/core/gastat_warehousing_logistics_{year}_en.xlsx",
        "Table 8" if year == 2023 else "Table 9",
        "عدد التراخيص السارية/النشطة في أنشطة نقل البضائع والخدمات البريدية حتى نهاية السنة.",
        "تجميع لأنشطة ترخيصية متعددة، ولا يقيس عدد الرحلات أو حجم البضائع أو القدرة التشغيلية.",
        "license_registration_region", "منطقة تسجيل الترخيص",
        "الأقرب أنه يعكس منطقة الترخيص أو السجل؛ لا يثبت أن حامل الترخيص يمارس كل نشاطه داخل المنطقة نفسها.", "no",
        "صفر يعني عدم وجود ترخيص نشط مسجل ضمن الفئات المشمولة، وليس غياب النقل الفعلي.",
        "لا يُقارن مع طلبات التوصيل باعتباره سعة تشغيلية مباشرة؛ العلاقة استكشافية فقط.",
    ) for year in (2023, 2024)
] + [
    metric(
        f"activated_logistics_centers_{year}", f"عدد المراكز اللوجستية المفعلة في {year}",
        f"Activated logistics centers {year}", "activated center", year, str(year), "annual_snapshot", "عرض", "supply",
        "Ministry of Transport and Logistics Services — Logisti", GASTAT_PUBLISHER, f"{GASTAT_PUBLICATION} 2024",
        "data/raw/core/gastat_warehousing_logistics_2024_en.xlsx", "Tables 1-2",
        "عدد المراكز التي تحمل الحالة Activated في قائمة المراكز، مجمعًا حسب المنطقة الإدارية.",
        "يعتمد على تعريف المصدر للمركز المفعّل؛ صفر لا يعني غياب كل أصل أو منطقة لوجستية في المنطقة.",
        "physical_center_location", "الموقع الفعلي للمركز المدرج",
        "الجدول يسمي المركز والمحافظة والمنطقة، لذلك يمثل موقع أصل فعلي أكثر من عنوان تسجيل.", "yes",
        "صفر ملاحظة صحيحة تعني عدم ظهور مركز بحالة Activated في القائمة، وليس قيمة مفقودة.",
        "العدد مشتق بتجميع صفوف Table 2 ذات الحالة Activated ويطابق الإجمالي الوطني في Table 1.",
    ) for year in (2023, 2024)
] + [
    metric(
        f"activated_logistics_centers_area_sqm_{year}", f"مساحة المراكز اللوجستية المفعلة في {year}",
        f"Activated logistics centers area {year}", "square meter", year, str(year), "annual_snapshot", "عرض", "supply",
        "Ministry of Transport and Logistics Services — Logisti", GASTAT_PUBLISHER, f"{GASTAT_PUBLICATION} 2024",
        "data/raw/core/gastat_warehousing_logistics_2024_en.xlsx", "Table 2",
        "مجموع مساحة المراكز ذات الحالة Activated بعد تحويل ألف متر مربع إلى متر مربع.",
        "المساحة الإجمالية لا تقيس الجزء المستخدم أو الطاقة التشغيلية أو نوع الاستخدام الفعلي للمركز.",
        "physical_center_location", "الموقع الفعلي للمركز المدرج",
        "يمثل مساحة أصول محددة مكانيًا، لكن لا يبين مقدار المساحة المشغلة فعليًا.", "yes",
        "صفر يعني عدم ظهور مساحة لمركز مفعّل في القائمة، وليس قيمة مفقودة.",
        "يرتبط بعدد المراكز وقد يكون عالي الارتباط به؛ يجب فحص التكرار قبل أي Screening.",
    ) for year in (2023, 2024)
]

CATALOG_BY_ID = {item["metric_id"]: item for item in CATALOG}


def parse_number(value: str):
    if value is None or value == "":
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


with MASTER_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
    master_rows = list(csv.DictReader(handle))

observations = []
for source_row in master_rows:
    for item in CATALOG:
        value = parse_number(source_row.get(item["metric_id"]))
        is_missing = value is None
        value_status = "missing" if is_missing else ("observed_zero" if value == 0 else "observed")
        quality_flag = "review_missing" if is_missing else "ok"
        observation = {
            "observation_id": f"R{int(source_row['region_id']):02d}__{item['metric_id']}",
            "region_id": int(source_row["region_id"]),
            "region_en": source_row["region_en"],
            "region_ar": source_row["region_ar"],
            **item,
            "value": value,
            "is_missing": is_missing,
            "value_status": value_status,
            "quality_flag": quality_flag,
            "quality_note_ar": "قيمة خام من المصدر" if not is_missing else "قيمة غير متاحة؛ بقيت null ولم تتحول إلى صفر",
        }
        observations.append(observation)

OBSERVATION_COLUMNS = [
    "observation_id", "region_id", "region_en", "region_ar", "metric_id", "metric_name_ar", "metric_name_en",
    "value", "unit", "year", "period", "periodicity", "indicator_type_ar", "indicator_type_en",
    "source_agency", "publisher", "source_dataset", "source_file", "table_number", "source_url",
    "definition_ar", "limitation_ar", "geographic_basis", "geographic_basis_ar", "geographic_basis_note_ar",
    "measures_activity_location", "zero_semantics_ar", "missing_value_policy", "is_missing", "value_status",
    "quality_tier", "quality_flag", "quality_note_ar", "relationship_note_ar", "raw_or_derived",
]

CATALOG_COLUMNS = [
    "metric_id", "metric_name_ar", "metric_name_en", "unit", "year", "period", "periodicity",
    "indicator_type_ar", "indicator_type_en", "source_agency", "publisher", "source_dataset", "source_file",
    "table_number", "source_url", "definition_ar", "limitation_ar", "geographic_basis", "geographic_basis_ar",
    "geographic_basis_note_ar", "measures_activity_location", "zero_semantics_ar", "missing_value_policy",
    "quality_tier", "relationship_note_ar", "raw_or_derived",
]

PROCESSED.mkdir(parents=True, exist_ok=True)
OUT_QA.parent.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)

with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=OBSERVATION_COLUMNS)
    writer.writeheader()
    writer.writerows(observations)

OUT_JSON.write_text(json.dumps(observations, ensure_ascii=False, indent=2), encoding="utf-8")

with OUT_CATALOG.open("w", encoding="utf-8-sig", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=CATALOG_COLUMNS)
    writer.writeheader()
    writer.writerows(CATALOG)

canonical_set = {(i, en, ar) for i, en, ar in CANONICAL_REGIONS}
observed_region_set = {
    (int(row["region_id"]), row["region_en"], row["region_ar"]) for row in master_rows
}
observation_keys = {(row["region_id"], row["metric_id"]) for row in observations}
expected_observation_count = len(CANONICAL_REGIONS) * len(CATALOG)
coverage = {
    item["metric_id"]: sum(row["metric_id"] == item["metric_id"] for row in observations)
    for item in CATALOG
}
missing_by_metric = {
    item["metric_id"]: sum(row["metric_id"] == item["metric_id"] and row["is_missing"] for row in observations)
    for item in CATALOG
}

qa = {
    "dataset": str(OUT_CSV.relative_to(ROOT)),
    "catalog": str(OUT_CATALOG.relative_to(ROOT)),
    "region_count": len(observed_region_set),
    "metric_count": len(CATALOG),
    "observation_count": len(observations),
    "expected_observation_count": expected_observation_count,
    "unique_observation_key_count": len(observation_keys),
    "duplicate_observation_keys": len(observations) - len(observation_keys),
    "canonical_regions_match": observed_region_set == canonical_set,
    "coverage_by_metric": coverage,
    "all_metrics_cover_13_regions": all(count == 13 for count in coverage.values()),
    "missing_value_count": sum(row["is_missing"] for row in observations),
    "missing_by_metric": missing_by_metric,
    "observed_zero_count": sum(row["value_status"] == "observed_zero" for row in observations),
    "observed_zeros_are_not_missing": all(
        not row["is_missing"] for row in observations if row["value_status"] == "observed_zero"
    ),
    "metadata_complete": all(
        row[field] not in (None, "")
        for row in observations
        for field in (
            "metric_name_ar", "unit", "year", "period", "source_agency", "publisher", "source_file",
            "table_number", "definition_ar", "limitation_ar", "indicator_type_ar", "geographic_basis",
            "geographic_basis_note_ar", "measures_activity_location",
        )
    ),
    "allowed_indicator_types": sorted({row["indicator_type_ar"] for row in observations}),
    "contains_score_or_ranking": any(
        token in row["metric_id"].lower() for row in observations for token in ("score", "rank", "priority")
    ),
    "contains_only_raw_metrics": all(row["raw_or_derived"] == "raw" for row in observations),
    "delivery_annual_equals_quarters_for_all_regions": all(
        parse_number(row["delivery_total_2024_source"])
        == sum(parse_number(row[f"delivery_q{q}_2024"]) for q in range(1, 5))
        for row in master_rows
    ),
    "raw_files_preserved": [
        "data/raw/core/gastat_warehousing_logistics_2023_en.xlsx",
        "data/raw/core/gastat_warehousing_logistics_2024_en.xlsx",
        "data/raw/core/saudi-arabia-population-by-administrative-region-nationality-and-sex.xlsx",
    ],
}
qa["all_checks_pass"] = (
    qa["region_count"] == 13
    and qa["observation_count"] == expected_observation_count
    and qa["duplicate_observation_keys"] == 0
    and qa["canonical_regions_match"]
    and qa["all_metrics_cover_13_regions"]
    and qa["observed_zeros_are_not_missing"]
    and qa["metadata_complete"]
    and not qa["contains_score_or_ranking"]
    and qa["contains_only_raw_metrics"]
    and qa["delivery_annual_equals_quarters_for_all_regions"]
)

OUT_QA.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
OUT_BUNDLE.write_text(
    json.dumps({"observations": observations, "catalog": CATALOG, "qa": qa}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

print(json.dumps({
    "regions": qa["region_count"],
    "metrics": qa["metric_count"],
    "observations": qa["observation_count"],
    "missing_values": qa["missing_value_count"],
    "observed_zeros": qa["observed_zero_count"],
    "all_checks_pass": qa["all_checks_pass"],
    "outputs": [str(OUT_CSV), str(OUT_JSON), str(OUT_CATALOG), str(OUT_QA)],
}, ensure_ascii=False, indent=2))
