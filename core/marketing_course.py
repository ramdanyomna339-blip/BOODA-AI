"""Curated offline marketing material supplied to Booda's planning context."""

import re

MARKETING_PATH_ID = "booda-marketing-foundations-v1"
MARKETING_CURRICULUM = (
    {
        "unit_id": "audience-and-problem",
        "title": "الدرس 1: الجمهور والمشكلة",
        "description": (
            "ابدئي بتحديد فئة واضحة من الناس، ثم اكتبي المشكلة التي تريدين "
            "مساعدتهم في حلها. تحققي من وجود المشكلة بسؤال العملاء أو مراجعة "
            "استفساراتهم السابقة؛ لا تختاري الجمهور بناءً على التخمين وحده."
        ),
        "keywords": ("التسويق", "الجمهور", "العميل", "المشكلة", "احتياج"),
        "project": (
            "اكتبي وصفًا لفئة محددة ومشكلة واحدة لديها، ثم اكتبي سؤالًا "
            "يمكنك طرحه للتحقق من المشكلة."
        ),
        "quiz": (
            {
                "question": "ما أفضل طريقة أولية للتحقق من مشكلة الجمهور؟",
                "choices": (
                    "سؤال العملاء أو مراجعة استفساراتهم السابقة",
                    "اختيار المشكلة بالتخمين",
                    "زيادة الميزانية مباشرة",
                ),
                "answer": 1,
                "explanation": "التحقق يبدأ من أسئلة العملاء أو استفساراتهم.",
            },
            {
                "question": "كيف نختار الجمهور في البداية؟",
                "choices": (
                    "كل الناس دون تحديد",
                    "فئة واضحة لديها احتياج مشترك",
                    "الجمهور الأكبر فقط",
                ),
                "answer": 2,
                "explanation": "الفئة الواضحة تساعد على فهم الاحتياج والرسالة.",
            },
            {
                "question": "ما الذي ينبغي تجنبه عند تحديد المشكلة؟",
                "choices": (
                    "مراجعة الاستفسارات",
                    "سؤال العملاء",
                    "اعتبار التخمين دليلًا كافيًا",
                ),
                "answer": 3,
                "explanation": "التخمين وحده لا يثبت وجود المشكلة.",
            },
        ),
    },
    {
        "unit_id": "clear-offer",
        "title": "الدرس 2: العرض والرسالة",
        "description": (
            "اشرحي الفائدة بوضوح، وما الذي سيحصل عليه العميل، والسعر أو الشروط "
            "المهمة، ثم حددي خطوة تالية بسيطة. تجنبي ضمان نتائج لا تملكين دليلًا "
            "عليها."
        ),
        "keywords": ("التسويق", "العرض", "الرسالة", "الفائدة", "السعر"),
        "project": (
            "اكتبي عرضًا من جملتين يوضح الفائدة للعميل وخطوة تالية بسيطة، "
            "من دون ضمان نتيجة غير مثبتة."
        ),
        "quiz": (
            {
                "question": "ما العنصر الأهم في رسالة العرض؟",
                "choices": (
                    "فائدة واضحة وما سيحصل عليه العميل",
                    "وعود كثيرة دون تفاصيل",
                    "مصطلحات غامضة",
                ),
                "answer": 1,
                "explanation": "الرسالة الواضحة تشرح الفائدة للعميل.",
            },
            {
                "question": "متى نتجنب ضمان نتيجة؟",
                "choices": (
                    "دائمًا حتى مع وجود دليل",
                    "عندما لا يوجد دليل يدعم الضمان",
                    "فقط عند ذكر السعر",
                ),
                "answer": 2,
                "explanation": "لا ينبغي ضمان نتائج لا يدعمها دليل.",
            },
            {
                "question": "ما الذي يساعد العميل على معرفة ما يفعله بعد قراءة العرض؟",
                "choices": (
                    "إضافة تفاصيل غير مرتبطة",
                    "إخفاء الشروط",
                    "خطوة تالية بسيطة وواضحة",
                ),
                "answer": 3,
                "explanation": "حددي خطوة تالية واحدة واضحة.",
            },
        ),
    },
    {
        "unit_id": "small-experiments",
        "title": "الدرس 3: اختبار صغير",
        "description": (
            "قبل توسيع الحملة، اختبري فكرة على نطاق محدود وبميزانية تناسبك. "
            "قارني نسختين مع تغيير عنصر واحد قدر الإمكان، مثل العنوان، حتى "
            "تستطيعي فهم ما ارتبط بالفرق في النتيجة."
        ),
        "keywords": ("التسويق", "الإعلان", "اختبار", "تجربة", "ميزانية"),
        "project": (
            "صممي تجربة إعلان صغيرة: حددي النسختين والعنصر الوحيد الذي "
            "ستغيرينه وما النتيجة التي ستسجلينها."
        ),
        "quiz": (
            {
                "question": "ما الأنسب عند مقارنة نسختين من إعلان؟",
                "choices": (
                    "تغيير كل العناصر في النسختين",
                    "تغيير عنصر واحد قدر الإمكان",
                    "عدم تسجيل النتائج",
                ),
                "answer": 2,
                "explanation": "تغيير عنصر واحد يساعد على فهم الفرق.",
            },
            {
                "question": "كيف تبدأين قبل توسيع الحملة؟",
                "choices": (
                    "اختبار محدود بميزانية مناسبة",
                    "صرف الميزانية كلها فورًا",
                    "نشر نسخ كثيرة دون مقارنة",
                ),
                "answer": 1,
                "explanation": "ابدئي باختبار صغير قبل التوسع.",
            },
            {
                "question": "لماذا نسجل نتائج التجربة؟",
                "choices": (
                    "لإلغاء الحاجة إلى المقارنة",
                    "لضمان نجاح الإعلان",
                    "لفهم ما ارتبط بالفرق في النتيجة",
                ),
                "answer": 3,
                "explanation": "التسجيل يسمح بمقارنة النتائج بوضوح.",
            },
        ),
    },
    {
        "unit_id": "useful-metrics",
        "title": "الدرس 4: قياس ما يهم",
        "description": (
            "اختاري المقياس حسب الهدف: قد تكون الاستفسارات المؤهلة أو المبيعات "
            "أهم من المشاهدات. سجلي التكلفة والنتيجة والفترة، ولا تخلطي بين "
            "الاهتمام السطحي والنتيجة التجارية."
        ),
        "keywords": ("التسويق", "إعلان", "قياس", "نتائج", "مبيعات", "استفسارات"),
        "project": (
            "اختاري هدفًا لحملة، ثم اكتبي مقياسًا مناسبًا والبيانات التي "
            "ستسجلينها لتفسيره."
        ),
        "quiz": (
            {
                "question": "إذا كان الهدف مبيعات، ما المقياس الأقرب للهدف؟",
                "choices": (
                    "عدد المشاهدات فقط",
                    "المبيعات أو الاستفسارات المؤهلة",
                    "عدد الألوان في الإعلان",
                ),
                "answer": 2,
                "explanation": "اختاري مقياسًا يعكس الهدف التجاري.",
            },
            {
                "question": "ما البيانات التي تسجلينها لتفسير الأداء؟",
                "choices": (
                    "التكلفة والنتيجة والفترة",
                    "المشاهدات فقط",
                    "اسم الإعلان دون نتائج",
                ),
                "answer": 1,
                "explanation": "التكلفة والنتيجة والفترة توفر سياقًا للمقارنة.",
            },
            {
                "question": "هل المشاهدات وحدها تثبت نتيجة تجارية؟",
                "choices": (
                    "نعم في كل الحالات",
                    "نعم إذا كان الإعلان طويلًا",
                    "لا، اختاري مقياسًا يناسب الهدف",
                ),
                "answer": 3,
                "explanation": "الاهتمام السطحي ليس دائمًا نتيجة تجارية.",
            },
        ),
    },
    {
        "unit_id": "interpret-results",
        "title": "الدرس 5: قراءة النتائج والتحسين",
        "description": (
            "قارني النتائج بفترة أو مجموعة مناسبة، وتأكدي من أن حجم البيانات "
            "كافٍ لاتخاذ قرار عملي. النتيجة قد تكون مؤشرًا لا برهانًا على السبب؛ "
            "وثقي ما تعلمته واقترحي تجربة لاحقة صغيرة."
        ),
        "keywords": ("التسويق", "حملة", "نتائج", "تحسين", "بيانات"),
        "project": (
            "اكتبي كيف ستقارنين نتيجتين، وما الذي تحتاجين معرفته قبل اتخاذ "
            "قرار، واقتراح تجربة لاحقة صغيرة."
        ),
        "quiz": (
            {
                "question": "ما الذي ينبغي مراعاته قبل اتخاذ قرار من النتائج؟",
                "choices": (
                    "لون تصميم التقرير",
                    "كفاية حجم البيانات وملاءمة المقارنة",
                    "عدد أعضاء الفريق فقط",
                ),
                "answer": 2,
                "explanation": "البيانات القليلة قد لا تكفي لقرار عملي.",
            },
            {
                "question": "هل تحسن النتيجة يثبت وحده سبب التحسن؟",
                "choices": (
                    "لا، قد تكون مؤشرًا وليست برهانًا",
                    "نعم دائمًا",
                    "نعم إذا كانت المشاهدات كثيرة",
                ),
                "answer": 1,
                "explanation": "الارتباط وحده لا يثبت السبب.",
            },
            {
                "question": "ما الخطوة المفيدة بعد توثيق ما تعلمته؟",
                "choices": (
                    "تجاهل النتيجة",
                    "توسيع الحملة مباشرة دون مراجعة",
                    "اقتراح تجربة لاحقة صغيرة",
                ),
                "answer": 3,
                "explanation": "اختبارًا لاحقًا صغيرًا يساعد على تحسين القرار.",
            },
        ),
    },
)


def ensure_marketing_path(learning_manager):
    path = learning_manager.get_path(MARKETING_PATH_ID)
    if path is not None:
        return path
    return learning_manager.add_path(
        "أساسيات التسويق: تعلم واختبر",
        [
            {
                "unit_id": lesson["unit_id"],
                "title": lesson["title"],
                "description": lesson["description"],
                "metadata": {
                    "origin": "curated_starter",
                    "keywords": list(lesson["keywords"]),
                },
            }
            for lesson in MARKETING_CURRICULUM
        ],
        path_id=MARKETING_PATH_ID,
        metadata={"origin": "curated_starter", "domain": "marketing"},
    )

def _search_terms(text):
    terms = set()
    for token in re.findall(r"\w+", text.casefold()):
        token = token.translate(str.maketrans({
            "أ": "ا", "إ": "ا", "آ": "ا",
        }))
        for _ in range(2):
            prefix = next((
                candidate
                for candidate in (
                    "وال", "بال", "كال", "فال", "لل", "ال",
                    "و", "ف", "ب", "ل", "ك",
                )
                if token.startswith(candidate)
                and len(token) > len(candidate) + 1
            ), None)
            if prefix is None:
                break
            token = token[len(prefix):]
        if len(token) >= 2:
            terms.add(token)
    return terms


def recall_marketing_material(learning_manager, query, *, limit=5):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("A non-empty query is required.")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("limit must be a non-negative integer.")
    query_terms = _search_terms(query)
    path = learning_manager.get_path(MARKETING_PATH_ID)
    if path is None or not path.get("metadata", {}).get("active", True):
        return []

    ranked = []
    for unit in path["units"]:
        if not unit.get("metadata", {}).get("active", True):
            continue
        metadata = unit.get("metadata", {})
        searchable = " ".join((
            unit.get("title", ""),
            unit.get("description", ""),
            " ".join(metadata.get("keywords", [])),
        ))
        overlap = len(query_terms & _search_terms(searchable))
        if overlap:
            ranked.append((overlap, unit))
    ranked.sort(
        key=lambda item: (item[0], -item[1].get("order", 0)),
        reverse=True,
    )
    return [
        {
            "path_id": path["path_id"],
            "title": unit["title"],
            "content": unit["description"],
            "source": f"booda://starter/marketing/{unit['unit_id']}",
            "origin": "curated_starter",
            "relevance": overlap,
        }
        for overlap, unit in ranked[:limit]
    ]
