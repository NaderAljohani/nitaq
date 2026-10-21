from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROCESSED = ROOT / "data" / "processed"
DEMOGRAPHY = ROOT / "data" / "raw" / "context" / "demography"
REGION_CARDS = ROOT / "knowledge" / "cards" / "regions"
METRIC_CARDS = ROOT / "knowledge" / "cards" / "metrics"
RAG = ROOT / "knowledge" / "rag"
AUDIT = ROOT / "outputs" / "build"

MASTER = PROCESSED / "mizan_region_master_2024.csv"
DICTIONARY = PROCESSED / "mizan_region_master_2024_dictionary.csv"
METRIC_CATALOG = PROCESSED / "mizan_metric_catalog_phase1.csv"
OBSERVATIONS = PROCESSED / "mizan_region_observations_2023_2024.csv"
GEOMETRY_SOURCE = DEMOGRAPHY / "saudi-arabia-population-by-administrative-region-nationality-and-sex.csv"

OUT_GEOJSON = PROCESSED / "saudi_regions.geojson"
OUT_GEOGRAPHY = PROCESSED / "saudi_regions_geography.csv"
OUT_PORTS = PROCESSED / "port_region_mapping.csv"
OUT_CONTEXT = PROCESSED / "mizan_context_asset_catalog.csv"
OUT_RAG = RAG / "source_catalog.csv"
OUT_AUDIT = AUDIT / "mizan_phase1_final_validation.json"

REGIONS = [
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
REGION_BY_EN = {en: {"region_id": i, "region_en": en, "region_ar": ar} for i, en, ar in REGIONS}
REGION_ALIASES = {
    "Riyadh": "Riyadh",
    "Makkah": "Makkah",
    "Al-Madinah": "Madinah",
    "Madinah": "Madinah",
    "Al-Qassim": "Qassim",
    "Qassim": "Qassim",
    "Eastern Region": "Eastern Region",
    "Asir": "Aseer",
    "Aseer": "Aseer",
    "Tabuk": "Tabuk",
    "Hail": "Hail",
    "Northern Borders": "Northern Borders",
    "Jazan": "Jazan",
    "Najran": "Najran",
    "Al-Bahah": "Al-Baha",
    "Al-Baha": "Al-Baha",
    "Al-Jawf": "Al-Jouf",
    "Al-Jouf": "Al-Jouf",
}

PORTS = [
    ("SAJED", "Jeddah Islamic Port", "ميناء جدة الإسلامي", "Jeddah", "جدة", "Makkah", True, True),
    ("SADAM", "King Abdulaziz Port, Dammam", "ميناء الملك عبدالعزيز بالدمام", "Dammam", "الدمام", "Eastern Region", True, True),
    ("SAJUB", "Jubail Commercial Port", "ميناء الجبيل التجاري", "Jubail", "الجبيل", "Eastern Region", True, False),
    ("SAJBI", "King Fahd Industrial Port, Jubail", "ميناء الملك فهد الصناعي بالجبيل", "Jubail", "الجبيل", "Eastern Region", True, False),
    ("SARTA", "Ras Tanura Port", "ميناء رأس تنورة", "Ras Tanura", "رأس تنورة", "Eastern Region", True, False),
    ("SARSZ", "Ras Al-Khair Port", "ميناء رأس الخير", "Ras Al-Khair", "رأس الخير", "Eastern Region", True, False),
    ("SAKFJ", "Khafji Port", "ميناء الخفجي", "Khafji", "الخفجي", "Eastern Region", True, False),
    ("SAYNB", "Yanbu Commercial Port", "ميناء ينبع التجاري", "Yanbu", "ينبع", "Madinah", True, False),
    ("SAYBI", "King Fahd Industrial Port, Yanbu", "ميناء الملك فهد الصناعي بينبع", "Yanbu", "ينبع", "Madinah", True, False),
    ("SADHU", "Duba Port", "ميناء ضباء", "Duba", "ضباء", "Tabuk", True, False),
    ("SAJIZ", "Jazan Port", "ميناء جازان", "Jazan", "جازان", "Jazan", True, False),
    ("PORTWATCH_KAP", "King Abdullah Port", "ميناء الملك عبدالله", "King Abdullah Economic City / Rabigh", "مدينة الملك عبدالله الاقتصادية / رابغ", "Makkah", False, True),
]
PORTWATCH_LOCATION_BY_CODE = {
    "SAJED": "jeddah",
    "SADAM": "dammam",
    "PORTWATCH_KAP": "king_abdullah_port",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def round_coordinates(value, precision: int = 5):
    if isinstance(value, list):
        return [round_coordinates(item, precision) for item in value]
    if isinstance(value, float):
        return round(value, precision)
    return value


def build_geography() -> tuple[list[dict], dict]:
    csv.field_size_limit(100 * 1024 * 1024)
    selected: dict[str, dict] = {}
    with GEOMETRY_SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        required = {"Date", "Region", "Gender", "GeoShape", "geo_point_2d"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"Geometry source is missing columns: {sorted(required - set(reader.fieldnames or []))}")
        for row in reader:
            if row["Date"] != "2024" or row["Gender"] != "Total" or row["Region"] == "Total":
                continue
            canonical = REGION_ALIASES.get(row["Region"])
            if canonical is None:
                raise ValueError(f"Unknown geometry region: {row['Region']!r}")
            if canonical in selected:
                raise ValueError(f"Duplicate 2024 total geometry for {canonical}")
            lat_text, lon_text = [part.strip() for part in row["geo_point_2d"].split(",", 1)]
            geometry = json.loads(row["GeoShape"])
            selected[canonical] = {
                "geometry": {
                    "type": geometry["type"],
                    "coordinates": round_coordinates(geometry["coordinates"]),
                },
                "centroid_lat": round(float(lat_text), 6),
                "centroid_lon": round(float(lon_text), 6),
                "source_region_name": row["Region"],
            }

    if set(selected) != set(REGION_BY_EN):
        raise ValueError(f"Geometry coverage mismatch: {sorted(set(REGION_BY_EN) - set(selected))}")

    geography_rows = []
    features = []
    for region_id, region_en, region_ar in REGIONS:
        item = selected[region_en]
        properties = {
            "region_id": region_id,
            "region_en": region_en,
            "region_ar": region_ar,
            "centroid_lat": item["centroid_lat"],
            "centroid_lon": item["centroid_lon"],
            "reference_year": 2024,
            "data_role": "map_only_context",
            "source_file": str(GEOMETRY_SOURCE.relative_to(ROOT)).replace("\\", "/"),
            "source_url": "https://datasource.kapsarc.org/explore/dataset/saudi-arabia-population-by-administrative-region-nationality-and-sex/",
        }
        features.append({"type": "Feature", "id": region_id, "properties": properties, "geometry": item["geometry"]})
        geography_rows.append({
            **properties,
            "source_region_name": item["source_region_name"],
            "limitation_ar": "حدود خريطة للعرض والربط فقط؛ لا تمثل مؤشرًا لوجستيًا ولا تدخل Screening.",
        })

    collection = {
        "type": "FeatureCollection",
        "name": "Saudi administrative regions - Mizan canonical 13",
        "features": features,
    }
    OUT_GEOJSON.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    write_csv(OUT_GEOGRAPHY, geography_rows, list(geography_rows[0]))
    return geography_rows, collection


def build_port_mapping() -> list[dict]:
    rows = []
    for port_code, port_en, port_ar, city_en, city_ar, region_en, official_files, portwatch in PORTS:
        region = REGION_BY_EN[region_en]
        source_list = []
        if official_files:
            source_list.append("Saudi ports public-data exports in data/raw/context/ports")
        if portwatch:
            source_list.append("IMF PortWatch")
        rows.append({
            "port_code": port_code,
            "port_name_en": port_en,
            "port_name_ar": port_ar,
            "city_en": city_en,
            "city_ar": city_ar,
            "region_id": region["region_id"],
            "region_en": region_en,
            "region_ar": region["region_ar"],
            "official_port_files_available": str(official_files).lower(),
            "portwatch_available": str(portwatch).lower(),
            "portwatch_location": PORTWATCH_LOCATION_BY_CODE.get(port_code, ""),
            "mapping_basis": "port city mapped to the canonical Saudi administrative region",
            "mapping_confidence": "high",
            "data_role": "context_only",
            "comparison_rule": "compare ports only after harmonizing period, field definitions, and file overlap",
            "absence_semantics": "a region without a mapped seaport is not_applicable, not zero",
            "source_scope": " | ".join(source_list),
            "source_url": "https://www.mawani.gov.sa/" if official_files else "https://portwatch.imf.org/",
            "limitation_ar": "حركة أو حمولة الميناء لا تقيس السعة أو الإشغال أو زمن التخليص، ولا تغطي المناطق الـ13 على أساس عادل.",
        })
    write_csv(OUT_PORTS, rows, list(rows[0]))
    return rows


def build_context_catalog() -> list[dict]:
    rows = [
        {
            "asset_id": "population_geometry_2010_2024",
            "asset_name_ar": "السكان وحدود المناطق حسب المنطقة والجنس",
            "source_agency": "Saudi Central Bank via KAPSARC Data Portal",
            "period": "2010-2024",
            "coverage": "13 regions plus national total",
            "path": "data/raw/context/demography/saudi-arabia-population-by-administrative-region-nationality-and-sex.csv",
            "phase1_role": "map_and_validation_context",
            "regional_comparability": "population values duplicate the core source; geometry is mapping only",
            "screening_use": "prohibited_as_new_signal",
            "limitation_ar": "حجمه كبير بسبب تكرار المضلع؛ التطبيق يستخدم saudi_regions.geojson ولا يقرأ الملف الخام مباشرة.",
        },
        {
            "asset_id": "population_census_2022_detailed",
            "asset_name_ar": "السكان حسب العمر والجنس والمحافظة والجنسية والمنطقة",
            "source_agency": "General Authority for Statistics via KAPSARC Data Portal",
            "period": "2022 census",
            "coverage": "13 regions, 150 governorates",
            "path": "data/raw/context/demography/population-by-detailed-age-gender-governorate-nationality-and-region-2022.csv",
            "phase1_role": "demographic_context_only",
            "regional_comparability": "comparable as 2022 census context",
            "screening_use": "not_in_default_screening",
            "limitation_ar": "لا يقيس طلبًا لوجستيًا ولا يستخدم مقامًا لمؤشرات 2024.",
        },
        {
            "asset_id": "official_saudi_port_exports",
            "asset_name_ar": "حركة السفن والحمولات والسلع والتدفقات في الموانئ السعودية",
            "source_agency": "Saudi public port-data exports",
            "period": "mostly 2020-2024; varies by file",
            "coverage": "ports in five administrative regions",
            "path": "data/raw/context/ports/",
            "phase1_role": "maritime_context_only",
            "regional_comparability": "not comparable across all 13 regions",
            "screening_use": "prohibited_in_default_13-region_screening",
            "limitation_ar": "يجب توحيد الفترة وتسوية تداخل الملفات؛ الحمولة ليست سعة أو إشغالًا أو زمن تخليص.",
        },
        {
            "asset_id": "imf_portwatch",
            "asset_name_ar": "سياق PortWatch للبوابات البحرية والمضائق",
            "source_agency": "IMF PortWatch / University of Oxford",
            "period": "2019-2026-05",
            "coverage": "Jeddah, Dammam, King Abdullah Port, Hormuz, Bab el-Mandeb",
            "path": "data/raw/context/imf_portwatch_monthly_long_2019_2026.csv",
            "phase1_role": "experimental_maritime_context",
            "regional_comparability": "not comparable across all 13 regions",
            "screening_use": "prohibited_in_default_13-region_screening",
            "limitation_ar": "مؤشر تجريبي قائم على حركة السفن وليس إحصاءً سعوديًا رسميًا.",
        },
        {
            "asset_id": "modon_industrial_context",
            "asset_name_ar": "المصانع والمدن الصناعية والمساحات",
            "source_agency": "MODON",
            "period": "2023-2024; varies by file",
            "coverage": "industrial cities, not a uniform 13-region table",
            "path": "data/raw/context/industrial/",
            "phase1_role": "industrial_context_after_mapping",
            "regional_comparability": "requires a documented industrial-city-to-region map",
            "screening_use": "not_in_default_screening",
            "limitation_ar": "المصانع والمدن الصناعية ليست مستودعات ولا تثبت توفر أرض لوجستية جاهزة.",
        },
        {
            "asset_id": "logisti_centers_snapshot_2026",
            "asset_name_ar": "لقطة قائمة المراكز من منصة لوجستي",
            "source_agency": "Logisti / Ministry of Transport and Logistics Services",
            "period": "snapshot 2026-07-28",
            "coverage": "listed logistics centers",
            "path": "data/raw/context/logisti_logistics_centers_snapshot_2026-07-28.csv",
            "phase1_role": "current_listing_context",
            "regional_comparability": "not a substitute for the 2024 GASTAT activated-center table",
            "screening_use": "context_only",
            "limitation_ar": "تختلف السنة وتعريف القائمة عن جدول المراكز المفعلة لعام 2024؛ لا تدمج القيم مباشرة.",
        },
        {
            "asset_id": "sama_statistical_report_2026",
            "asset_name_ar": "تقرير ساما الإحصائي",
            "source_agency": "Saudi Central Bank",
            "period": "historical series; report downloaded 2026",
            "coverage": "national and regional population tables",
            "path": "data/raw/context/SAMA_StatisticalReport_2026.xls",
            "phase1_role": "historical_validation_context",
            "regional_comparability": "population content is redundant with the adopted KAPSARC/SAMA source",
            "screening_use": "not_in_screening",
            "limitation_ar": "لا يضيف مؤشر تكلفة أو نشاط لوجستي إقليمي جديد للنسخة الحالية.",
        },
    ]
    write_csv(OUT_CONTEXT, rows, list(rows[0]))
    return rows


def build_rag_catalog() -> list[dict]:
    rows = [
        ("gastat_warehousing_methodology_2024", "منهجية إحصاءات التخزين والخدمات اللوجستية 2024", "GASTAT", "2024", "ar/en", "knowledge/rag/gastat_warehousing_logistics_methodology_2024.md", "approved_for_ingestion", "high", "definitions_methodology_limitations", "https://stats.gov.sa/en/w/methodology-and-quality-report-for-warehousing-and-logistics-statistics-2024", "مصدر منهجي؛ لا يستخدم بدل الجداول الرقمية."),
        ("gastat_road_transport_methodology", "منهجية إحصاءات النقل البري", "GASTAT", "2024", "en", "knowledge/rag/gastat_road_transport_methodology_en.pdf", "approved_for_ingestion", "high", "definitions_methodology_limitations", "https://www.stats.gov.sa/", "مصدر منهجي وليس مؤشر مقارنة إقليميًا مستقلًا."),
        ("logisti_warehouse_technical_guide", "الدليل الفني لبناء وتشغيل المستودعات", "Logisti / MOTLS", "not stated", "ar", "knowledge/rag/technical-guide-for-construction-and-operation-of-warehouses-ar.pdf", "approved_for_ingestion", "high", "technical_requirements", "https://logisti.sa/", "دليل فني لا يثبت جودة أو جاهزية مستودعات منطقة بعينها."),
        ("momah_warehouse_requirements_2025", "اشتراطات المستودعات والمخازن", "Ministry of Municipalities and Housing", "2025", "ar", "knowledge/rag/warehouse_requirements_2025_ar.pdf", "approved_for_ingestion", "high", "regulatory_and_operational_requirements", "https://balady.gov.sa/", "يستخدم لشرح الاشتراطات، لا كمصدر أرقام أو توصية موقع."),
        ("nidlp_annual_report_2025", "التقرير السنوي لبرنامج ندلب 2025", "NIDLP", "2025", "ar", "knowledge/rag/nidlp_annual_report_2025_ar.pdf", "approved_selective_ingestion", "medium", "national_strategy_and_kpis", "https://spa.gov.sa/N2615750", "وطني ومجمع؛ لا ينسب المؤشرات إلى منطقة إلا إذا نص التقرير على ذلك صراحة."),
        ("kapsarc_sustainable_freight_2020", "تصميم سياسة نقل مستدام للبضائع في السعودية", "KAPSARC", "2020", "en", "knowledge/rag/kapsarc_sustainable_freight_policy_2020_en.pdf", "approved_context_ingestion", "high", "research_methodology_and_policy", "https://www.kapsarc.org/our-offerings/publications/designing-transport-policy-for-sustainable-freight-movement-in-saudi-arabia/", "بحث 2020؛ سياق منهجي وليس وصفًا آنيًا للسوق."),
        ("kapsarc_container_throughput_2022", "اتجاهات مناولة الحاويات السعودية", "KAPSARC", "2022", "en", "knowledge/rag/kapsarc_container_throughput_trends_2022_en.pdf", "approved_context_ingestion", "high", "historical_maritime_scenarios", "https://www.kapsarc.org/our-offerings/publications/current-and-future-trends-in-saudi-arabia-s-container-throughput", "السيناريوهات ليست حقائق حالية ولا تغطي المناطق الـ13."),
        ("tga_goods_brokerage_regulation_2025", "اللائحة التنفيذية لأنشطة الوساطة في نقل البضائع", "Transport General Authority", "2025", "ar", "knowledge/rag/pending_ocr/tga_goods_transport_brokerage_regulation_2025_ar.pdf", "blocked_pending_ocr", "unusable_text_layer", "legal_regulation", "https://www.uqn.gov.sa/", "لا يفهرس قبل OCR عربي ومراجعة المواد وأرقام الصفحات والتحقق من النسخة النافذة."),
    ]
    fieldnames = ["source_id", "title_ar", "agency", "year", "language", "path", "rag_status", "extraction_quality", "document_role", "source_url", "limitation_ar"]
    records = [dict(zip(fieldnames, row)) for row in rows]
    write_csv(OUT_RAG, records, fieldnames)
    return records


def safe_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def enrich_region_cards(geography_rows: list[dict], port_rows: list[dict]) -> None:
    geo_by_region = {row["region_en"]: row for row in geography_rows}
    ports_by_region: dict[str, list[dict]] = defaultdict(list)
    for row in port_rows:
        ports_by_region[row["region_en"]].append(row)

    start_marker = "<!-- PHASE1_CONTEXT_START -->"
    end_marker = "<!-- PHASE1_CONTEXT_END -->"
    for _, region_en, _ in REGIONS:
        card = REGION_CARDS / f"{safe_slug(region_en)}.md"
        text = card.read_text(encoding="utf-8")
        if start_marker in text and end_marker in text:
            prefix = text.split(start_marker, 1)[0].rstrip()
            suffix = text.split(end_marker, 1)[1].lstrip()
            text = prefix + ("\n\n" + suffix if suffix else "")
        geo = geo_by_region[region_en]
        mapped_ports = ports_by_region.get(region_en, [])
        if mapped_ports:
            port_lines = "\n".join(f"- {row['port_name_ar']} ({row['port_code']}) - {row['city_ar']}." for row in mapped_ports)
            port_note = "الموانئ التالية مرتبطة بالمنطقة كسياق وصول بحري فقط:\n\n" + port_lines
        else:
            port_note = "لا يوجد ميناء بحري في جدول الربط الحالي لهذه المنطقة؛ الحالة `not_applicable` وليست صفر نشاط لوجستي."
        block = f"""{start_marker}
## السياق الجغرافي والبحري

- مركز العرض التقريبي للخريطة: {geo['centroid_lat']}, {geo['centroid_lon']}.
- بيانات تعداد 2022 التفصيلية متاحة كسياق ديموغرافي، ولا تستخدم مقامًا لمؤشرات 2024.

{port_note}

بيانات الموانئ لا تدخل Screening المناطق الـ13، ولا تقيس السعة أو الإشغال أو زمن التخليص.
{end_marker}"""
        card.write_text(text.rstrip() + "\n\n" + block + "\n", encoding="utf-8")


def validate(geo_collection: dict, geography_rows: list[dict], port_rows: list[dict], context_rows: list[dict], rag_rows: list[dict]) -> dict:
    master = read_csv(MASTER)
    dictionary = read_csv(DICTIONARY)
    metric_catalog = read_csv(METRIC_CATALOG)
    observations = read_csv(OBSERVATIONS)
    master_columns = list(master[0])
    raw_metric_ids = {row["metric_id"] for row in metric_catalog}
    region_names = {row["region_en"] for row in master}
    expected_regions = set(REGION_BY_EN)

    totals_expected = {
        "population_2023": 33702731,
        "population_2024": 35300280,
        "delivery_total_2024_source": 288117656,
        "warehouse_count_2023": 12451,
        "warehouse_count_2024": 12234,
        "freight_post_licenses_2023": 7963,
        "freight_post_licenses_2024": 10402,
        "activated_logistics_centers_2023": 22,
        "activated_logistics_centers_2024": 23,
    }
    totals_actual = {
        key: int(round(sum(float(row[key]) for row in master)))
        for key in totals_expected
    }

    checks = {
        "master_has_13_rows": len(master) == 13,
        "master_regions_unique": len(region_names) == 13,
        "master_regions_canonical": region_names == expected_regions,
        "master_dictionary_covers_all_columns": {row["metric"] for row in dictionary} == set(master_columns),
        "raw_metric_catalog_has_17_metrics": len(metric_catalog) == 17 and len(raw_metric_ids) == 17,
        "raw_metric_catalog_has_source_urls": all(row["source_url"].strip() for row in metric_catalog),
        "raw_observations_have_221_rows": len(observations) == 221,
        "raw_observations_cover_all_region_metric_pairs": len({(row["region_en"], row["metric_id"]) for row in observations}) == 221,
        "raw_observations_have_no_missing_values": all(
            row["value_status"] in {"observed", "observed_zero"}
            and row["is_missing"].lower() == "false"
            for row in observations
        ),
        "delivery_totals_match_quarters": all(row["delivery_total_matches_quarters"].lower() == "true" for row in master),
        "published_totals_match": totals_actual == totals_expected,
        "no_score_or_rank_columns": not any("score" in column.lower() or "rank" in column.lower() for column in master_columns),
        "geojson_has_13_features": len(geo_collection["features"]) == 13,
        "geojson_regions_canonical": {feature["properties"]["region_en"] for feature in geo_collection["features"]} == expected_regions,
        "geography_csv_has_13_rows": len(geography_rows) == 13,
        "port_codes_unique": len({row["port_code"] for row in port_rows}) == len(port_rows),
        "port_mapping_uses_canonical_regions": {row["region_en"] for row in port_rows}.issubset(expected_regions),
        "port_mapping_is_context_only": all(row["data_role"] == "context_only" for row in port_rows),
        "context_catalog_paths_exist": all((ROOT / row["path"]).exists() for row in context_rows),
        "rag_catalog_paths_exist": all((ROOT / row["path"]).exists() for row in rag_rows),
        "regulation_blocked_until_ocr": any(row["source_id"] == "tga_goods_brokerage_regulation_2025" and row["rag_status"] == "blocked_pending_ocr" for row in rag_rows),
        "metric_cards_count_17": len(list(METRIC_CARDS.glob("*.md"))) == 17,
        "region_cards_count_13": len(list(REGION_CARDS.glob("*.md"))) == 13,
        "region_cards_have_context_block": all("PHASE1_CONTEXT_START" in path.read_text(encoding="utf-8") for path in REGION_CARDS.glob("*.md")),
        "data_ea_has_no_loose_files": not any((ROOT / "data_ea").glob("*.*")),
        "active_demography_has_two_unique_sources": len(list(DEMOGRAPHY.glob("*.csv"))) == 2,
        "unused_files_archived_not_deleted": len(list((ROOT / "data" / "archive" / "not_used" / "data_ea").glob("*"))) == 2,
        "duplicate_files_archived_not_deleted": len(list((ROOT / "data" / "archive" / "duplicates" / "data_ea").glob("*"))) == 5,
    }
    result = {
        "phase": 1,
        "status": "approved_for_evidence_exploration_and_limited_screening",
        "checks_pass": all(checks.values()),
        "checks": checks,
        "counts": {
            "regions": len(master),
            "master_columns": len(master_columns),
            "raw_metrics": len(metric_catalog),
            "observations": len(observations),
            "geojson_features": len(geo_collection["features"]),
            "mapped_ports": len(port_rows),
            "regions_with_mapped_ports": len({row["region_en"] for row in port_rows}),
            "context_assets": len(context_rows),
            "rag_sources": len(rag_rows),
            "rag_sources_blocked": sum(row["rag_status"].startswith("blocked") for row in rag_rows),
        },
        "totals": totals_actual,
        "product_decision": {
            "allowed": "evidence exploration, profiles, comparisons with metric-specific caveats, and limited user-defined screening",
            "prohibited": ["fixed gap score", "best-region claim", "capacity shortage claim", "investment recommendation", "budget or profitability fit"],
            "port_rule": "context only; no zero assigned to inland regions",
            "warehouse_rule": "choose count per 100k OR licensed area per capita; never double-count both",
        },
        "outputs": [
            str(OUT_GEOJSON.relative_to(ROOT)).replace("\\", "/"),
            str(OUT_GEOGRAPHY.relative_to(ROOT)).replace("\\", "/"),
            str(OUT_PORTS.relative_to(ROOT)).replace("\\", "/"),
            str(OUT_CONTEXT.relative_to(ROOT)).replace("\\", "/"),
            str(OUT_RAG.relative_to(ROOT)).replace("\\", "/"),
        ],
    }
    OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    OUT_AUDIT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not result["checks_pass"]:
        failed = [name for name, passed in checks.items() if not passed]
        raise AssertionError(f"Phase 1 final validation failed: {failed}")
    return result


def main() -> None:
    for directory in (PROCESSED, REGION_CARDS, RAG, AUDIT):
        directory.mkdir(parents=True, exist_ok=True)
    geography_rows, geo_collection = build_geography()
    port_rows = build_port_mapping()
    context_rows = build_context_catalog()
    rag_rows = build_rag_catalog()
    enrich_region_cards(geography_rows, port_rows)
    result = validate(geo_collection, geography_rows, port_rows, context_rows, rag_rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
