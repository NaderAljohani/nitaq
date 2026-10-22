from __future__ import annotations

import re


# Compact domain notes used only when the online model is unavailable.  They
# are concepts, not stored questions or canned winners.  Numeric/regulatory
# claims are deliberately excluded because those require tools or documents.
_CONCEPTS = (
    (
        ("fulfillment", "تنفيذ الطلب", "تلبية الطلب"),
        "مركز تنفيذ الطلبات يركز على استقبال المخزون وتجهيز طلبات العملاء وتعبئتها وشحنها بسرعة، بينما قد يقتصر المستودع التقليدي على التخزين والمناولة.",
        "A fulfillment center receives inventory and rapidly picks, packs, and ships customer orders; a traditional warehouse may focus mainly on storage and handling.",
    ),
    (
        ("cross docking", "cross-docking", "العبور المباشر", "التخزين العابر"),
        "العبور المباشر ينقل البضائع من الاستلام إلى الشحن مع تخزين محدود جدًا، ويصلح عندما تكون التدفقات متوقعة والتنسيق بين المورد والنقل دقيقًا.",
        "Cross-docking moves goods from receiving to dispatch with minimal storage. It works best with predictable flows and tight supplier-carrier coordination.",
    ),
    (
        ("last mile", "الميل الأخير", "التوصيل الأخير"),
        "الميل الأخير هو مرحلة انتقال الشحنة من نقطة التوزيع الأخيرة إلى المستلم، وغالبًا تتأثر كفاءته بكثافة الطلب والمسافات ونوافذ التسليم ونسبة فشل التسليم.",
        "Last mile is the final movement from a distribution point to the recipient; its efficiency depends on demand density, distance, delivery windows, and failed deliveries.",
    ),
    (
        ("safety stock", "مخزون الأمان", "المخزون الآمن"),
        "مخزون الأمان كمية احتياطية تمتص تقلب الطلب أو تأخر التوريد. تحديده يعتمد على تذبذب الطلب وزمن التوريد ومستوى الخدمة المستهدف، لا على متوسط الطلب وحده.",
        "Safety stock buffers demand variability and replenishment delays. It depends on demand variation, lead time, and the target service level—not average demand alone.",
    ),
    (
        ("3pl", "طرف ثالث", "مزود لوجستي"),
        "مزود الخدمات اللوجستية من الطرف الثالث يدير عمليات مثل التخزين والنقل أو تنفيذ الطلبات نيابة عن العميل، مقابل اتفاق خدمة ومؤشرات أداء واضحة.",
        "A third-party logistics provider manages activities such as warehousing, transport, or fulfillment for a client under defined service levels and KPIs.",
    ),
    (
        ("cold chain", "سلسلة التبريد", "السلسلة المبردة"),
        "سلسلة التبريد تحافظ على نطاق حراري محدد أثناء التخزين والنقل والمناولة، وتحتاج مراقبة موثقة للحرارة وخطة للتعامل مع الانحرافات.",
        "A cold chain maintains a controlled temperature through storage, transport, and handling, with documented monitoring and deviation procedures.",
    ),
    (
        ("warehouse management system", "wms", "نظام ادارة مستودع", "نظام إدارة مستودع"),
        "اختيار نظام إدارة المستودع يبدأ من العمليات التي يجب أن يدعمها: الاستلام، تحديد المواقع، الجرد، الالتقاط والتعبئة والتكامل مع أنظمة الطلب والنقل. اختبر قابلية التوسع وسهولة التكامل ودقة التتبع قبل مقارنة السعر وحده.",
        "Choose a warehouse management system from the workflows it must support: receiving, put-away, inventory, picking, packing, and order/transport integrations. Test scalability, integration, and traceability before comparing price alone.",
    ),
    (
        ("port", "seaport", "ميناء", "موانئ"),
        "كبر نشاط الميناء لا يجعل المدينة تلقائيًا أفضل لمستودع؛ فهو مؤشر على قوة البوابة البحرية فقط. القرار يحتاج أيضًا كثافة الطلب، وجهات العملاء، اتصال الطرق، زمن النقل، تكلفة الموقع، المنافسة وطبيعة البضائع.",
        "A busier port does not automatically make its city the best warehouse location; it is only a maritime-gateway signal. Demand density, customer destinations, road access, transit time, site cost, competition, and cargo type still matter.",
    ),
    (
        ("warehouse", "مستودع", "مستودعات"),
        "المستودع منشأة لاستلام البضائع وحفظها ومناولتها ثم صرفها. جودة تشغيله تُقاس بتدفق آمن، دقة المخزون، استغلال المساحة، وسرعة تجهيز الطلبات.",
        "A warehouse receives, stores, handles, and dispatches goods. Its operation is judged by safe flow, inventory accuracy, space use, and order-processing speed.",
    ),
    (
        ("logistics", "لوجستي", "اللوجستية"),
        "اللوجستيات تنسق تدفق البضائع والمعلومات من المصدر إلى المستفيد عبر النقل والتخزين والمخزون وتنفيذ الطلبات، بهدف تحقيق مستوى الخدمة بتكلفة ومخاطر منضبطة.",
        "Logistics coordinates goods and information from origin to customer through transport, storage, inventory, and fulfillment to achieve service targets with controlled cost and risk.",
    ),
)


def general_knowledge_fallback(question: str, language: str = "ar") -> str:
    """Compose a useful, non-numeric answer when the model is unavailable."""
    normalized = re.sub(r"\s+", " ", str(question or "").lower()).strip()
    for aliases, arabic, english in _CONCEPTS:
        if any(alias in normalized for alias in aliases):
            return english if language == "en" else arabic
    if language == "en":
        return (
            "This is a general logistics question. A sound answer should separate the operating goal, demand pattern, "
            "inventory flow, transport constraints, service level, cost, and risk. If you share the specific process or "
            "decision, I can turn those factors into a practical analysis; current numbers or regulations would require a cited source."
        )
    return (
        "هذا سؤال لوجستي عام. لتحليله عمليًا نفصل بين هدف التشغيل، ونمط الطلب، وتدفق المخزون، وقيود النقل، "
        "ومستوى الخدمة، والتكلفة والمخاطر. اذكر العملية أو القرار المقصود وسأحوّل هذه العوامل إلى تحليل عملي؛ "
        "أما الأرقام الحالية والاشتراطات فتحتاج مصدرًا موثقًا."
    )
