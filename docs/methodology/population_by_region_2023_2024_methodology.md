# Population by Saudi Administrative Region, 2023–2024

> **Update — 2026-07-28:** A direct public KAPSARC dataset covering population by administrative region, year and gender was added to the project. `mizan_region_master_2024.csv` now uses the direct rows where `Gender = Total` for 2023 and 2024. The road-density recovery below is retained as an audit method, not as the primary regional population source. The 2024 regional values match exactly. For 2023, the national total matches exactly but regional values differ because the published road-density ratios are rounded; therefore the recovered 2023 regional values must not replace the direct KAPSARC values.

## Purpose

This dataset supplies a population denominator for comparing logistics activity and licensed infrastructure across Saudi Arabia's 13 administrative regions. It enables fairer measures such as delivery orders per 1,000 residents, licensed warehouse area per resident, and freight/postal licences per 100,000 residents.

## Official sources

- **2023:** General Authority for Statistics (GASTAT), *Land Transport Statistics 2023*.
  - Table 15: intercity road lengths by region.
  - Table 18: dirt-road lengths by region.
  - Table 19: road lengths within cities by region.
  - Table 20: road-network density per population by region.
  - Official publication page: https://www.stats.gov.sa/en/w/%D9%86%D8%B4%D8%B1%D8%A9-%D8%A5%D8%AD%D8%B5%D8%A7%D8%A1%D8%A7%D8%AA-%D8%A7%D9%84%D9%86%D9%82%D9%84-%D8%A7%D9%84%D8%A8%D8%B1%D9%8A
- **2024:** GASTAT, *Road Transport Statistics 2024*.
  - Table 7-1: road lengths within cities by region.
  - Table 7-2: intercity road lengths by region.
  - Table 7-4: dirt-road lengths by region.
  - Table 7-5: road-network density per population by region.
  - Official publications listing: https://www.stats.gov.sa/en/statistics-tabs?category=124894&periodicity=120156&tab=436312

Both density tables state that their population input is GASTAT's **preliminary mid-year population estimate** for the corresponding year. The population-estimates methodology uses July 1 as the mid-year reference date and publishes estimates for the 13 administrative regions.

## Deterministic derivation

The road-network population density is defined as total road-network kilometres divided by population. Therefore, the official population denominator can be recovered algebraically:

```text
total_road_length_km = roads_within_cities + intercity_roads + dirt_roads
population = round(total_road_length_km / road_network_km_per_person)
```

This is not a forecast, modelled estimate, or third-party approximation. It is a deterministic recovery of the population denominator from values published by GASTAT. The only rounding performed is to the nearest person after division.

## Validation and quality checks

- The 13 reconstructed regional values sum to **33,702,731** in 2023, exactly matching the national denominator implied by the national total road length and density.
- The 13 reconstructed regional values sum to **35,300,280** in 2024, exactly matching the national denominator implied by the national total road length and density.
- All 13 regions are present once in each year, with no missing values or duplicate region keys.
- `growth_rate_2023_2024` is stored as a decimal; for example, `0.057300` means 5.73%.

## Appropriate use and limitation

Use these values for per-capita normalization and regional comparison in Mizan AI. Label them in the interface as **GASTAT preliminary mid-year population estimates, derived from published road-network density tables**. They should not be presented as census counts.

No official 2025 regional population table was found during the source review performed on 2026-07-28. The latest official regional denominator located is 2024, so 2025 values should not be fabricated or extrapolated for the prototype.
