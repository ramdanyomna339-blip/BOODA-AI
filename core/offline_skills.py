"""Small, explicit offline skills that do not depend on a language model."""

from core.planning import BoodaPlan, PlanStep


class BoodaOfflineAdPlanner:
    """Create a clearly labeled first-draft ad using only a bounded template."""

    requires_explicit_permissions = True
    capability_name = "save_task_content"

    _AD_TERMS = (
        "إعلان", "اعلان", "إعلانات", "اعلانات", "حملة", "تسويق",
        "ad ", "ads", "advertising", "campaign",
    )
    _STRATEGY_TERMS = (
        "خطة", "تعلم", "اتعلم", "أتعلم", "حلل", "تحليل", "استراتيجية",
        "ميزانية", "نتائج الحملة", "marketing strategy",
    )

    def __init__(self, *, permission_name):
        if not isinstance(permission_name, str) or not permission_name.strip():
            raise ValueError("Offline ad drafting requires a save permission.")
        self.permission_name = permission_name
        self._configured = False

    @classmethod
    def supports_goal(cls, intent):
        folded = str(intent).casefold()
        return (
            any(term in folded for term in cls._AD_TERMS)
            and not any(term in folded for term in cls._STRATEGY_TERMS)
        )

    def configure_agent(self, *, registry, permission_manager):
        if registry.get(self.capability_name) is None:
            raise ValueError("The save_task_content capability is not available.")
        permissions = getattr(permission_manager, "permissions", None)
        if permissions is None or self.permission_name not in permissions:
            raise ValueError("The offline ad skill requires a registered save permission.")
        capability_registry = getattr(registry, "capability_registry", None)
        if capability_registry is not None:
            definition = capability_registry.get(self.capability_name)
            if definition is None or not definition.enabled:
                raise ValueError("The save_task_content capability is disabled.")
            if definition.permission_name != self.permission_name:
                raise ValueError("Offline skill permission does not match capability policy.")
        self._configured = True

    @staticmethod
    def _product_label(intent):
        folded = intent.casefold()
        if any(term in folded for term in ("ميكب", "مكياج", "makeup", "make-up")):
            return "مستحضرات الميكب"
        if "عطر" in folded or "perfume" in folded:
            return "العطور"
        if any(term in folded for term in ("ملابس", "هدوم", "fashion", "clothes")):
            return "المنتجات"
        return "المنتج"

    def create_plan(self, goal, memory):
        if not self._configured:
            raise RuntimeError("Configure the offline skill with BoodaAgent first.")

        product = self._product_label(goal.intent)
        draft = (
            f"لمستك اللي بتحبيها تبدأ من هنا ✨\n\n"
            f"اختاري من {product} اللي يناسب ذوقك، وخلي إطلالتك بطريقتك.\n"
            "ابعتيلنا رسالة دلوقتي عشان تعرفي التفاصيل وتطلبي.\n\n"
            "قبل النشر: أضيفي السعر وتفاصيل المنتج ووسيلة الطلب المناسبة."
        )
        safe_goal_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in goal.goal_id
        ).strip("_\n") or "goal"
        return BoodaPlan(
            goal_id=goal.goal_id,
            plan_id=f"{safe_goal_id}-offline-ad-draft-v1",
            steps=(PlanStep(
                task_id=f"{safe_goal_id}-offline-ad-draft",
                title="مسودة إعلان أولية للمراجعة",
                description=(
                    "مسودة مبدئية أنشأتها مهارة محلية ثابتة، وليست ناتج نموذج AI. "
                    "راجعيها وأكملي التفاصيل الناقصة قبل النشر.\n\n"
                    f"{draft}"
                ),
                capability=self.capability_name,
                permission_name=self.permission_name,
                metadata={
                    "provider": "offline_ad_skill",
                    "scope": "local-only",
                    "template_version": 1,
                },
            ),),
        )

    def respond(self, message, *, context=None, memory=None):
        return (
            "مهارة الإعلانات المحلية تكتب مسودة أولية بقالب ثابت؛ "
            "راجعي المعلومات الناقصة قبل استخدامها."
        )


class BoodaOfflineMarketingPlanner:
    """Prepare a reviewed campaign plan without loading or contacting a model."""

    requires_explicit_permissions = True
    local_planning = True
    capability_name = "create_plan_artifact"

    _MARKETING_TERMS = (
        "حملة", "تسويق", "إعلان", "اعلان", "marketing", "campaign",
        "promote", "ad ", "ads",
    )
    _NON_MARKETING_TERMS = (
        "تعلم", "اتعلم", "أتعلم", "درس", "كورس", "برمجة", "software",
    )

    def __init__(self, *, permission_name):
        if permission_name != "save_file":
            raise ValueError("Offline campaign plans must use the save_file permission.")
        self.permission_name = permission_name
        self._configured = False

    @classmethod
    def supports_goal(cls, intent):
        folded = str(intent).casefold()
        return (
            any(term in folded for term in cls._MARKETING_TERMS)
            and not any(term in folded for term in cls._NON_MARKETING_TERMS)
        )

    def configure_agent(self, *, registry, permission_manager):
        if registry.get(self.capability_name) is None:
            raise ValueError("The create_plan_artifact capability is not available.")
        permissions = getattr(permission_manager, "permissions", None)
        if permissions is None or self.permission_name not in permissions:
            raise ValueError("Offline campaign planning requires save_file permission.")
        capability_registry = getattr(registry, "capability_registry", None)
        if capability_registry is not None:
            definition = capability_registry.get(self.capability_name)
            if definition is None or not definition.enabled:
                raise ValueError("The create_plan_artifact capability is disabled.")
            if definition.permission_name != self.permission_name:
                raise ValueError("Campaign planner permission does not match capability policy.")
        self._configured = True

    def create_plan(self, goal, memory):
        if not self._configured:
            raise RuntimeError("Configure the campaign planner with BoodaAgent first.")

        safe_goal_id = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in goal.goal_id
        ).strip("_\n") or "goal"
        stages = (
            (
                "تحديد هدف الحملة والجمهور",
                "حددي هدفًا واحدًا للحملة، والجمهور المقصود ومشكلته أو احتياجه. "
                "سجلي المنتج والمنطقة ومدة الحملة؛ اتركي أي معلومة ناقصة كسؤال بدل تخمينها.",
            ),
            (
                "تجهيز العرض والرسالة",
                "اكتبي brief قصيرًا يتضمن العرض المتاح وميزاته المؤكدة ونبرة التواصل. "
                "جهزي فكرتين للرسالة والدعوة إلى الإجراء دون إضافة سعر أو ضمان غير مذكور.",
            ),
            (
                "مراجعة المحتوى والمنصة",
                "راجعي أن النص واضح ومتوافق مع الجمهور والمنصة، وأن كل ادعاء يستند "
                "إلى معلومة قدمها المستخدم؛ أضيفي وسيلة الطلب والتفاصيل الناقصة قبل النشر.",
            ),
            (
                "تشغيل اختبار وقياس النتيجة",
                "حددي نسخة اختبار ومقياسًا يناسب هدف الحملة مثل الرسائل أو النقرات أو "
                "الطلبات. سجلي الميزانية والمدة والنتيجة الفعلية بعد التشغيل، ولا تفترضي أرقامًا مسبقًا.",
            ),
        )
        steps = tuple(
            PlanStep(
                task_id=f"{safe_goal_id}-campaign-{index}",
                title=title,
                description=(
                    f"{description}\n\nهدف المستخدم: {goal.intent}\n"
                    "المصدر: مهارة تخطيط محلية ثابتة؛ هذه خطة أولية وليست تحليلًا مبنيًا على بيانات سوق."
                ),
                capability=self.capability_name,
                permission_name=self.permission_name,
                metadata={
                    "provider": "offline_marketing_skill",
                    "scope": "local-only",
                    "template_version": 1,
                },
            )
            for index, (title, description) in enumerate(stages, start=1)
        )
        return BoodaPlan(
            goal_id=goal.goal_id,
            plan_id=f"{safe_goal_id}-offline-campaign-v1",
            steps=steps,
        )

    def respond(self, message, *, context=None, memory=None):
        return (
            "مهارة التخطيط المحلية تنظم الحملة في خطوات ثابتة؛ "
            "الخطة لا تعتمد على بيانات سوق مباشرة."
        )
