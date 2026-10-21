بيانات تشغيل نطاق المعتمدة
==========================

هذا المجلد يحتوي فقط ما يحتاجه التطبيق مباشرة:

- mizan_region_master_2024.csv: الجدول الإقليمي الأساسي.
- mizan_metric_catalog_phase1.csv: تعريف المؤشرات ومصادرها وحدودها.
- mizan_region_master_2024_dictionary.csv: قاموس أعمدة الجدول الأساسي.
- port_region_mapping.csv: ربط الموانئ بالمناطق.
- saudi_regions_geography.csv: أسماء المناطق وبياناتها الجغرافية المختصرة.
- mizan_context_asset_catalog.csv: حالة المصادر السياقية وحدود استخدامها.
- runtime/: سياق الموانئ والمراكز اللوجستية والمدن الصناعية المستخدم وقت التشغيل.
- rag/: فهرس الوثائق والـembeddings المستخدم في الاسترجاع.

ملفات التحليل الوسيطة، مثل observations وcorrelations وoutliers وGeoJSON،
ليست مطلوبة للتشغيل. النسخة الكاملة منها محفوظة داخل:
NITAQ_CLIENT_PACKAGE/01_CORE_SOURCE_DATA/PROCESSED_DATA_SNAPSHOT/

لا تعدّل هذه الملفات يدويًا. أعد بناءها عبر scripts/data_pipeline/ عند الحاجة.
