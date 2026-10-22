# سكربتات ميزان

هذه السكربتات للصيانة وإعادة البناء فقط؛ التطبيق لا يعتمد على تشغيلها عند البدء.

- `data_pipeline/`: استخراج البيانات، بناء الجداول التشغيلية، وتدقيقها.
- `rag/build_rag_index.py`: إعادة بناء فهرس الوثائق بعد تغيير ملفات المعرفة.
- `rag/ocr_pdf_windows.py`: إنشاء نص جانبي لملفات PDF المصورة على Windows.
- `rag/requirements-ocr-windows.txt`: مكتبات OCR الاختيارية فقط.
- `evaluation/run_readiness.py`: تشغيل تقييم الجاهزية وإنشاء التقرير النهائي.
- `start_mizan.ps1`: المشغل الذي يستخدمه ملف Windows الرئيسي.

شغّل الأوامر من جذر المشروع، مثل:

```powershell
python scripts\rag\build_rag_index.py
python scripts\evaluation\run_readiness.py
```
