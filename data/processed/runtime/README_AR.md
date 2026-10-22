# بيانات التشغيل

هذه الملفات هي نسخ صغيرة ومعالجة من المصادر الخام، ويقرأها التطبيق مباشرة أثناء التشغيل. تفاصيل كل ملف ومصدره موجودة في `manifest.json`.

لإعادة بنائها:

1. استعد محتويات `MIZAN_CLIENT_PACKAGE/01_CORE_SOURCE_DATA/RAW_DATA_ARCHIVE/raw_sources_2026-07-30.zip` إلى جذر المشروع.
2. شغّل `python scripts/data_pipeline/build_runtime_context.py`.

لا يحتاج التطبيق إلى فك الأرشيف أو وجود `data/raw/` في التشغيل العادي.
