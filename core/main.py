import json
import os
import re
import sqlite3
from getpass import getpass
from urllib.parse import urlparse
from uuid import uuid4
from contextlib import ExitStack

from core.approval_manager import BoodaApprovalManager
from core.agent_session import BoodaAgentSessionStore
from core.ad_intelligence import BoodaAdIntelligence
from core.ad_intelligence_cli import manage_ad_intelligence_menu
from core.integrations_cli import manage_integrations
from core.artifact_manager import BoodaArtifactManager
from core.audit_log import BoodaAuditLog
from core.audit_report import format_audit_events
from core.brain import BoodaAgent
from core.capability_registry import BoodaCapabilityRegistry
from core.console import configure_utf8_console
from core.context_builder import BoodaContextBuilder
from core.event_log import BoodaEventLog
from core.evolution_manager import BoodaEvolutionManager, EVOLUTION_PERMISSION
from core.executor import BoodaExecutor
from core.file_action import (
    list_saved_announcements,
    read_saved_announcement,
    save_plan_artifact,
    save_task_content,
    update_saved_announcement,
)
from core.goal_manager import BoodaGoalManager
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.result_verifier import BoodaArtifactVerifier
from core.reasoning_tools import register_reasoning_tools
from core.research import BoodaResearchManager
from core.research_cli import manage_research
from core.code_evolution import CODE_PERMISSION
from core.laptop import BoodaLaptopConnection, LAPTOP_READ, LAPTOP_WRITE
from core.desktop_control import DESKTOP_PERMISSION
from core.system_cli import manage_code_evolution, manage_laptop
from core.llm_planner import OpenAICompatiblePlanner
from core.learning import BoodaLearningManager
from core.marketing_course import (
    MARKETING_CURRICULUM,
    MARKETING_PATH_ID,
    ensure_marketing_path,
)
from core.local_model import (
    BASE_URL as LOCAL_LLM_BASE_URL,
    MODEL_NAME as LOCAL_LLM_MODEL,
    ensure_local_model_server,
)
from core.memory import BoodaStructuredMemoryStore, JsonlBoodaMemory
from core.mock_planner import BoodaMockPlanner
from core.offline_skills import (
    BoodaOfflineAdPlanner,
    BoodaOfflineMarketingPlanner,
)
from core.permission_manager import BoodaPermissionManager
from core.permission_policy import BoodaPermissionPolicy
from core.planning import BoodaGoal
from core.project_manager import BoodaProjectManager
from core.risk import RiskLevel
from core.scheduler import BoodaScheduler
from core.task_manager import BoodaTaskManager
from core.tool_registry import BoodaToolRegistry
from core.user_profile import BoodaUserProfileManager
from core.versioning import BoodaVersionStore


_SENSITIVE_PREFERENCE_KEY = re.compile(
    r"(?:api.?key|secret|token|password|credential|authorization)", re.IGNORECASE
)
_SENSITIVE_PREFERENCE_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{10,}|"
    r"Bearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.IGNORECASE,
)
OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
OLLAMA_DEFAULT_MODEL = "qwen3.5:4b"
MAX_VOICE_REPLY_CHARACTERS = 6000


def _contains_sensitive_preference_data(value):
    if isinstance(value, dict):
        return any(
            _SENSITIVE_PREFERENCE_KEY.search(str(key))
            or _contains_sensitive_preference_data(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_preference_data(item) for item in value)
    return (
        isinstance(value, str)
        and _SENSITIVE_PREFERENCE_VALUE.search(value) is not None
    )


def _resolve_ai_provider(provider, configured_url=None):
    provider = (provider or "").strip().casefold()
    if provider:
        return provider
    return "openai" if configured_url else "gemini"


def _read_preference_value():
    raw_value = input(
        "القيمة (نص عربي أو قيمة JSON مثل true أو 3؛ لن تُطبع): "
    )
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value
    if _contains_sensitive_preference_data(value):
        raise ValueError("رُفضت قيمة تبدو كبيانات سرية ولم تُحفظ.")
    return value


def show_preferences(
    preference_manager, *, active_only=False, project_id=None
):
    preferences = preference_manager.list_preferences(
        include_inactive=not active_only
    )
    if project_id is not None:
        preferences = [
            item for item in preferences
            if item.scope == "project" and item.scope_id == project_id
        ]
    if not preferences:
        print("لا توجد تفضيلات مطابقة.")
        return
    for item in preferences:
        key = (
            "[مفتاح مخفي]"
            if _SENSITIVE_PREFERENCE_KEY.search(item.key)
            else item.key
        )
        value = (
            "[REDACTED]"
            if (
                _SENSITIVE_PREFERENCE_KEY.search(item.key)
                or _contains_sensitive_preference_data(item.value)
            )
            else json.dumps(item.value, ensure_ascii=False)
        )
        print(
            f"{item.id} | {key}={value} | "
            f"scope={item.scope}:{item.scope_id} | source={item.source} | "
            f"type={item.preference_type} | "
            f"active={'yes' if item.active else 'no'}"
        )


def _preference_scope_input():
    scope_choice = input(
        "النطاق: 1 مستخدم، 2 مشروع، 3 مهمة: "
    ).strip()
    scope = {"1": "user", "2": "project", "3": "task"}.get(scope_choice)
    if scope is None:
        raise ValueError("النطاق غير صحيح.")
    if scope == "user":
        return scope, None
    scope_id = input("معرّف المشروع/المهمة: ").strip()
    if not scope_id:
        raise ValueError("معرّف النطاق مطلوب.")
    return scope, scope_id


def _preference_source_input():
    source_choice = input(
        "المصدر: 1 صريح، 2 مستورد، 3 مستنتج، 4 نظام: "
    ).strip()
    source = {
        "1": "explicit",
        "2": "imported",
        "3": "inferred",
        "4": "system",
    }.get(source_choice)
    if source is None:
        raise ValueError("مصدر التفضيل غير صحيح.")
    return source


def _preference_type_input():
    type_choice = input("النوع: 1 دائم، 2 مؤقت: ").strip()
    preference_type = {"1": "persistent", "2": "temporary"}.get(type_choice)
    if preference_type is None:
        raise ValueError("نوع التفضيل غير صحيح.")
    return preference_type


def manage_preferences(preference_manager):
    """Interactive CLI for the existing local profile/preference store."""
    while True:
        print("\nإدارة الملف الشخصي والتفضيلات:")
        print("1. عرض كل التفضيلات")
        print("2. عرض التفضيلات الفعالة فقط")
        print("3. عرض تفضيلات مشروع")
        print("4. إضافة تفضيل")
        print("5. تعديل تفضيل")
        print("6. تعطيل تفضيل")
        print("7. إعادة تفعيل تفضيل")
        print("8. حذف تفضيل")
        print("9. قبول تفضيل مستورد/مستنتج")
        print("10. إضافة تعليمات مؤقتة لمهمة")
        print("11. رجوع")
        choice = input("اختاري إجراءً: ").strip()
        try:
            if choice in {"0", "11"}:
                return
            if choice == "1":
                show_preferences(preference_manager)
            elif choice == "2":
                show_preferences(preference_manager, active_only=True)
            elif choice == "3":
                project_id = input("معرّف المشروع: ").strip()
                if not project_id:
                    raise ValueError("معرّف المشروع مطلوب.")
                show_preferences(preference_manager, project_id=project_id)
            elif choice == "4":
                key = input("مفتاح التفضيل: ").strip()
                if _SENSITIVE_PREFERENCE_KEY.search(key):
                    raise ValueError("لا تُخزّن بيانات اعتماد كتفضيلات.")
                value = _read_preference_value()
                scope, scope_id = _preference_scope_input()
                source = _preference_source_input()
                preference_type = _preference_type_input()
                preference = preference_manager.set_preference(
                    key,
                    value,
                    scope=scope,
                    scope_id=scope_id,
                    source=source,
                    preference_type=preference_type,
                    updated_by="cli",
                )
                print(f"تم حفظ التفضيل: {preference.id}")
            elif choice == "5":
                preference_id = input("معرّف التفضيل: ").strip()
                current = preference_manager.get_preference(preference_id)
                if current is None:
                    print("لم يُعثر على التفضيل.")
                    continue
                if _SENSITIVE_PREFERENCE_KEY.search(current.key):
                    raise ValueError("لا يمكن تعديل تفضيل بيانات اعتماد من CLI.")
                value = _read_preference_value()
                updated = preference_manager.set_preference(
                    current.key,
                    value,
                    user_id=current.user_id,
                    scope=current.scope,
                    scope_id=current.scope_id,
                    source=current.source,
                    confidence=current.confidence,
                    preference_type=current.preference_type,
                    active=current.active,
                    updated_by="cli",
                )
                print(f"تم تعديل التفضيل: {updated.id}")
            elif choice in {"6", "7", "8", "9"}:
                preference_id = input("معرّف التفضيل: ").strip()
                if choice == "6":
                    result = preference_manager.deactivate_preference(
                        preference_id, updated_by="cli"
                    )
                    action = "تعطيل"
                elif choice == "7":
                    result = preference_manager.activate_preference(
                        preference_id, updated_by="cli"
                    )
                    action = "إعادة التفعيل"
                elif choice == "8":
                    result = preference_manager.delete_preference(
                        preference_id, updated_by="cli"
                    )
                    action = "حذف"
                else:
                    result = preference_manager.promote_preference(
                        preference_id, updated_by="cli"
                    )
                    action = "القبول والتحويل إلى صريح"
                if result is None:
                    print("لم يُعثر على التفضيل.")
                else:
                    print(f"تم {action} التفضيل.")
            elif choice == "10":
                key = input("مفتاح التعليمات المؤقتة: ").strip()
                if _SENSITIVE_PREFERENCE_KEY.search(key):
                    raise ValueError("لا تُخزّن بيانات اعتماد كتفضيلات.")
                task_id = input("معرّف المهمة: ").strip()
                value = _read_preference_value()
                preference = preference_manager.set_preference(
                    key,
                    value,
                    scope="task",
                    scope_id=task_id,
                    source="explicit",
                    preference_type="temporary",
                    updated_by="cli",
                )
                print(f"تم حفظ التعليمات المؤقتة للمهمة: {preference.id}")
            else:
                print("الاختيار غير صحيح.")
        except ValueError as error:
            print("تعذر تنفيذ التغيير:", error)


def _read_memory_value():
    raw_value = input("القيمة (نص أو JSON؛ لن تُطبع): ")
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return raw_value


def manage_structured_memory(memory_manager):
    """Review and manage only explicitly entered local memory."""
    categories = {
        "1": "fact", "2": "preference", "3": "project", "4": "client",
        "5": "decision", "6": "lesson", "7": "temporary", "8": "suggestion",
    }
    while True:
        print("\nإدارة الذاكرة المنظمة:")
        print("1. عرض السجلات")
        print("2. إضافة معلومة أكدتها المستخدمة")
        print("3. إضافة اقتراح غير معتمد")
        print("4. اعتماد اقتراح")
        print("5. رفض اقتراح أو سحب اعتماد")
        print("6. تصحيح معلومة معتمدة")
        print("7. حذف سجل نهائيًا")
        print("8. رجوع")
        choice = input("اختاري إجراءً: ").strip()
        try:
            if choice in {"0", "8"}:
                return
            if choice == "1":
                entries = memory_manager.list_entries()
                if not entries:
                    print("لا توجد سجلات ذاكرة.")
                for entry in entries:
                    print(
                        f"{entry['entry_id']} | {entry['category']} | "
                        f"{entry['status']} | {entry['scope']}:{entry['scope_id']} | "
                        f"{entry['key']}={json.dumps(entry['value'], ensure_ascii=False)}"
                    )
            elif choice in {"2", "3"}:
                category_choice = input("نوع المعلومة (1-8): ").strip()
                category = categories.get(category_choice)
                if category is None:
                    raise ValueError("نوع المعلومة غير صحيح.")
                key = input("مفتاح/عنوان المعلومة: ").strip()
                value = _read_memory_value()
                scope_choice = input("النطاق: 1 المستخدم، 2 مشروع، 3 عميل: ").strip()
                scope = {"1": "user", "2": "project", "3": "client"}.get(scope_choice)
                if scope is None:
                    raise ValueError("نطاق المعلومة غير صحيح.")
                scope_id = (
                    None if scope == "user"
                    else input("معرّف المشروع/العميل: ").strip()
                )
                rationale = input("المصدر أو سبب الثقة: ").strip()
                options = {
                    "scope": scope,
                    "scope_id": scope_id,
                    "source": (
                        "user-confirmed" if choice == "2"
                        else "assistant-suggestion"
                    ),
                    "rationale": rationale,
                    "confidence": 1.0 if choice == "2" else 0.5,
                }
                if category == "temporary":
                    options["expires_at"] = input(
                        "انتهاء الصلاحية بصيغة ISO 8601 مع منطقة زمنية: "
                    ).strip()
                if choice == "2":
                    if input("للتأكيد اكتبي نعم: ").strip() != "نعم":
                        print("لم تُحفظ المعلومة.")
                        continue
                    entry = memory_manager.add_confirmed(
                        category, key, value, user_confirmed=True, actor="cli",
                        **options,
                    )
                    print(f"تم حفظ المعلومة المؤكدة: {entry['entry_id']}")
                else:
                    entry = memory_manager.propose(
                        category, key, value, actor="cli", **options
                    )
                    print(f"حُفظ الاقتراح بانتظار المراجعة: {entry['entry_id']}")
            elif choice == "4":
                entry_id = input("معرّف الاقتراح: ").strip()
                if input("اعتمدي هذه المعلومة؟ اكتبي نعم: ").strip() != "نعم":
                    print("ظل الاقتراح غير معتمد.")
                    continue
                entry = memory_manager.approve(
                    entry_id, user_confirmed=True, actor="cli"
                )
                print(f"تم اعتماد المعلومة: {entry['entry_id']}")
            elif choice in {"5", "6", "7"}:
                entry_id = input("معرّف السجل: ").strip()
                current = memory_manager.get_entry(entry_id)
                if current is None:
                    print("لم يُعثر على السجل.")
                    continue
                if choice == "6":
                    value = _read_memory_value()
                    rationale = input("سبب التصحيح: ").strip()
                    if input("اكتبي نعم لتأكيد التصحيح: ").strip() != "نعم":
                        print("لم يتغير السجل.")
                        continue
                    updated = memory_manager.correct(
                        entry_id, value, rationale=rationale,
                        user_confirmed=True, actor="cli",
                    )
                    print(f"تم تصحيح المعلومة: {updated['entry_id']}")
                else:
                    prompt = (
                        "الحذف نهائي. اكتبي نعم للتأكيد: "
                        if choice == "7" else "اكتبي نعم لتأكيد الإجراء: "
                    )
                    if input(prompt).strip() != "نعم":
                        print("لم يتغير السجل.")
                        continue
                    if choice == "7":
                        result = memory_manager.delete(entry_id, actor="cli")
                    elif current["status"] == "proposed":
                        result = memory_manager.reject(entry_id, actor="cli")
                    else:
                        result = memory_manager.withdraw(entry_id, actor="cli")
                    print("تم تحديث السجل." if result else "لم يتغير السجل.")
            else:
                print("الاختيار غير صحيح.")
        except (
            RuntimeError, ValueError, TypeError, PermissionError, OSError,
            sqlite3.Error,
        ) as error:
            print("تعذر تحديث الذاكرة:", error)


def manage_egyptian_dialect(memory_manager):
    """Store and apply only phrases the user explicitly confirms."""
    from core.dialect_learning import add_dialect_correction, list_dialect_corrections

    while True:
        print("\nتعليم اللهجة المصرية للصوت:")
        print("1. تعليم كلمة أو جملة جديدة")
        print("2. عرض التصحيحات المتعلمة")
        print("3. حذف تصحيح")
        print("0. رجوع")
        choice = input("اختاري إجراءً: ").strip()
        try:
            if choice == "0":
                return
            if choice == "1":
                source = input("اكتبي الكلمة أو الجملة التي تريدين تصحيحها: ").strip()
                egyptian = input("اكتبي الصياغة المصرية التي تفضلينها: ").strip()
                if input("أحفظ هذا التصحيح وأستخدمه في الردود الصوتية؟ اكتبي نعم: ").strip() != "نعم":
                    print("لم يُحفظ التصحيح.")
                    continue
                entry = add_dialect_correction(memory_manager, source, egyptian)
                print(f"اتحفظ التصحيح وهيدخل في الردود الصوتية: {entry['entry_id']}")
            elif choice == "2":
                entries = list_dialect_corrections(memory_manager)
                if not entries:
                    print("لسه مفيش تصحيحات متعلمة.")
                for entry in entries:
                    value = entry["value"]
                    print(
                        f"{entry['entry_id']} | {value['source_phrase']} "
                        f"← {value['egyptian_phrase']}"
                    )
            elif choice == "3":
                entry_id = input("معرّف التصحيح: ").strip()
                current = memory_manager.get_entry(entry_id)
                if current is None or not current["memory_key"].startswith("egyptian_dialect:"):
                    print("لم يُعثر على تصحيح لهجة بهذا المعرّف.")
                    continue
                if input("الحذف نهائي. اكتبي نعم للتأكيد: ").strip() != "نعم":
                    print("لم يُحذف التصحيح.")
                    continue
                memory_manager.delete(entry_id, actor="dialect-coach")
                print("تم حذف التصحيح.")
            else:
                print("الاختيار غير صحيح.")
        except (RuntimeError, ValueError, TypeError, PermissionError, OSError) as error:
            print("تعذر تحديث تعلّم اللهجة:", error)


def manage_experience_lessons(evolution_manager, learning_manager):
    while True:
        print("\nإدارة دروس الخبرة:")
        print("1. عرض الدروس النشطة")
        print("2. عرض كل الدروس")
        print("3. تعطيل درس")
        print("4. إعادة تفعيل درس")
        print("5. حذف درس")
        print("6. إضافة دروس تسويق تمهيدية")
        print("7. تجهيز مواد التسويق ليستفيد منها Booda")
        print("0. رجوع")
        choice = input("اختاري إجراءً: ").strip()
        try:
            if choice == "0":
                return
            if choice in {"1", "2"}:
                lessons = evolution_manager.list_experience_lessons(
                    include_inactive=choice == "2"
                )
                if not lessons:
                    print("لا توجد دروس خبرة.")
                    continue
                for lesson in lessons:
                    metadata = lesson.get("metadata", {})
                    active = metadata.get("active", True)
                    print(
                        f"{lesson['knowledge_id']} | {lesson['content']} | "
                        f"المصدر: {lesson['source']} | "
                        f"النوع: {'مادة تمهيدية' if metadata.get('origin') == 'curated_starter' else 'خبرة مسجلة'} | "
                        f"النتيجة: {metadata.get('outcome', 'غير محددة')} | "
                        f"الحالة: {'نشط' if active else 'معطل'}"
                    )
            elif choice in {"3", "4", "5"}:
                knowledge_id = input("معرّف الدرس: ").strip()
                if choice == "5":
                    evolution_manager.delete_experience_lesson(
                        knowledge_id, changed_by="cli"
                    )
                    print("تم حذف درس الخبرة.")
                else:
                    evolution_manager.set_experience_lesson_active(
                        knowledge_id,
                        active=choice == "4",
                        changed_by="cli",
                    )
                    print("تم تحديث حالة درس الخبرة.")
            elif choice == "6":
                added = evolution_manager.add_starter_marketing_lessons(
                    changed_by="cli"
                )
                if added:
                    print(f"تمت إضافة {len(added)} دروس تسويق تمهيدية.")
                else:
                    print("دروس التسويق التمهيدية موجودة بالفعل.")
            elif choice == "7":
                path = ensure_marketing_path(learning_manager)
                print(
                    f"مواد التسويق جاهزة لسياق Booda "
                    f"({len(path['units'])} موضوعات محلية)."
                )
            else:
                print("الاختيار غير صحيح.")
        except ValueError as error:
            print("تعذر تنفيذ التغيير:", error)


def manage_local_knowledge_base(knowledge_base):
    while True:
        print("\nالمعرفة المحلية:")
        print("1. استيراد PDF أو Word أو Excel أو صورة أو ملف نصي")
        print("2. البحث في المصادر")
        print("3. عرض المصادر المحفوظة")
        print("4. حذف مصدر")
        print("5. استيراد PDF مصوّر باستخدام OCR")
        print("0. رجوع")
        choice = input("اختاري إجراءً: ").strip()
        try:
            if choice == "0":
                return
            if choice in {"1", "5"}:
                file_path = input("مسار الملف المحلي: ").strip().strip('"')
                document = knowledge_base.import_file(file_path, ocr=choice == "5")
                print(
                    f"تم استيراد {document['title']} "
                    f"({len(document['chunks'])} مقاطع)."
                )
            elif choice == "2":
                query = input("عبارة البحث: ").strip()
                results = knowledge_base.search(query)
                if not results:
                    print("لم يُعثر على مقاطع مطابقة.")
                    continue
                for result in results:
                    page = (
                        f"، صفحة {result['page']}"
                        if result["page"] is not None else ""
                    )
                    print(
                        f"\n{result['title']}{page}\n"
                        f"المصدر: {result['source']}\n"
                        f"{result['text']}"
                    )
            elif choice == "3":
                documents = knowledge_base.list_documents()
                if not documents:
                    print("لا توجد مصادر محلية مستوردة.")
                    continue
                for document in documents:
                    print(
                        f"{document['document_id']} | {document['title']} | "
                        f"{document['format']} | {document['chunk_count']} مقاطع | "
                        f"{document['source']}"
                    )
            elif choice == "4":
                document_id = input("معرّف المصدر: ").strip()
                if knowledge_base.delete_document(document_id):
                    print("تم حذف المصدر ومقاطعه.")
                else:
                    print("المصدر غير موجود.")
            else:
                print("الاختيار غير صحيح.")
        except (FileNotFoundError, RuntimeError, ValueError, OSError) as error:
            print("تعذر تنفيذ العملية:", error)


def manage_learning_course(learning_manager):
    path = ensure_marketing_path(learning_manager)
    curriculum = {
        lesson["unit_id"]: lesson for lesson in MARKETING_CURRICULUM
    }
    print(f"\n{path['title']} — التقدم: {path['progress']:.0%}")
    for index, unit in enumerate(path["units"], start=1):
        print(f"{index}. {unit['title']} [{unit['status']}]")
    print("0. رجوع")

    while True:
        choice = input("اختاري رقم الدرس: ").strip()
        if choice == "0":
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(path["units"]):
            print("اختاري رقم درس موجودًا أو 0 للرجوع.")
            continue
        unit = path["units"][int(choice) - 1]
        lesson = curriculum.get(unit["unit_id"])
        if lesson is None:
            print("لا يوجد محتوى تدريسي لهذا الدرس.")
            return

        print(f"\n{unit['title']}\n{unit['description']}")
        print(f"\nالتطبيق العملي: {lesson['project']}")
        while True:
            submission = input("إجابتك على التطبيق العملي: ").strip()
            if not submission:
                print("اكتبي إجابة قبل المتابعة.")
            elif len(submission) > 10000:
                print("الإجابة لا يمكن أن تتجاوز 10,000 حرف.")
            else:
                break
        learning_manager.record_project_submission(
            MARKETING_PATH_ID,
            unit_id=unit["unit_id"],
            prompt=lesson["project"],
            submission=submission,
        )
        correct_answers = 0
        questions = lesson["quiz"]
        for index, question in enumerate(questions, start=1):
            print(f"\n{index}. {question['question']}")
            for option_number, option in enumerate(question["choices"], start=1):
                print(f"  {option_number}. {option}")
            while True:
                answer = input("إجابتك (1-3): ").strip()
                if answer in {"1", "2", "3"}:
                    break
                print("أدخلي رقمًا من 1 إلى 3.")
            if int(answer) == question["answer"]:
                correct_answers += 1
                print("إجابة صحيحة.")
            else:
                print(f"الإجابة الصحيحة: {question['answer']}. {question['explanation']}")

        score = correct_answers * 100 / len(questions)
        passed = correct_answers >= 2
        feedback = (
            f"{correct_answers}/{len(questions)} إجابات صحيحة؛ "
            + ("اجتياز الدرس." if passed else "أعيدي قراءة الدرس ثم حاولي مرة أخرى.")
        )
        learning_manager.record_assessment(
            MARKETING_PATH_ID,
            score=score,
            feedback=feedback,
            unit_id=unit["unit_id"],
        )
        if passed:
            path = learning_manager.update_unit_status(
                MARKETING_PATH_ID, unit["unit_id"], "completed"
            )
            if path is None:
                raise RuntimeError("The marketing learning path disappeared.")
            print(f"اجتزتِ الدرس. تقدم المسار: {path['progress']:.0%}")
        else:
            if unit["status"] == "not_started":
                learning_manager.update_unit_status(
                    MARKETING_PATH_ID, unit["unit_id"], "in_progress"
                )
            print("لم تجتازي الدرس بعد. تقدّم المسار لم يتغير.")
        return


def run_demo(
    audit_log,
    permission_manager,
    approval_manager,
    task_manager,
):
    executor = BoodaExecutor()
    permission_policy = BoodaPermissionPolicy()

    number = 1
    task_id = f"task-demo-{number:03d}"

    while task_id in task_manager.tasks:
        number += 1
        task_id = f"task-demo-{number:03d}"

    task = task_manager.add_task(
        task_id=task_id,
        title="Expired approval test",
        description="A demo action with an expired approval.",
    )

    approval_id, approval = approval_manager.create_approval(
        permission_name="spend_money",
        approved_by="Yomna",
        reason="Expired approval test.",
        task_id=task_id,
        expires_in_minutes=-1,
        created_by="Yomna",
    )

    approval_manager.approve_approval(approval_id)

    def spend_money():
        return "Money spent."

    result = executor.execute(
        task=task,
        action=spend_money,
        permission_manager=permission_manager,
        permission_name="spend_money",
        permission_policy=permission_policy,
        approval=approval,
        audit_log=audit_log,
        requested_by="Yomna",
    )

    print("Task ID:", task_id)
    print("Approval ID:", approval_id)
    print("Expired:", approval.is_expired())
    print("Result:", result)
    print("Task status:", task.status)
    print("Task result:", task.result)


def show_audit_report(audit_log):
    print("\nعايزة تعرضي السجل إزاي؟")
    print("1. البحث برقم المهمة")
    print("2. البحث بالتاريخ")
    print("3. عرض كل السجل")

    choice = input("اختاري 1 أو 2 أو 3: ").strip()

    if choice == "1":
        task_id = input("اكتبي رقم المهمة: ").strip()
        events = audit_log.get_events(task_id=task_id)

    elif choice == "2":
        day = input("اكتبي التاريخ بالشكل YYYY-MM-DD: ").strip()

        try:
            events = audit_log.get_events(day=day)
        except ValueError:
            print("التاريخ غير صحيح. استخدمي الشكل YYYY-MM-DD.")
            return

    elif choice == "3":
        events = audit_log.get_events()

    else:
        print("الاختيار غير صحيح.")
        return

    print("\nAudit report:")
    print(format_audit_events(events))


def change_permission(permission_manager, action):
    permission_name = input("اكتبي اسم الصلاحية: ").strip()
    changed_by = input("اكتبي اسم الشخص اللي بيغيّرها: ").strip()

    if action == "grant":
        success = permission_manager.grant_permission(
            permission_name,
            changed_by=changed_by,
        )
        action_text = "منحها"
    else:
        success = permission_manager.revoke_permission(
            permission_name,
            changed_by=changed_by,
        )
        action_text = "سحبها"

    if success:
        print(f"تم {action_text} الصلاحية: {permission_name}")
    else:
        print(f"الصلاحية غير موجودة: {permission_name}")


def create_approval(approval_manager):
    permission_name = input("اكتبي اسم الصلاحية: ").strip()
    approved_by = input("مين المفروض يوافق؟ ").strip()
    created_by = input("مين طلب الموافقة؟ ").strip()
    task_id = input("رقم المهمة، أو Enter للتخطي: ").strip() or None
    reason = input("سبب طلب الموافقة: ").strip()

    approval_id, _ = approval_manager.create_approval(
        permission_name=permission_name,
        approved_by=approved_by,
        created_by=created_by,
        task_id=task_id,
        reason=reason,
    )

    print("تم إنشاء الموافقة:", approval_id)


def approve_request(approval_manager):
    approval_id = input("اكتبي رقم الموافقة: ").strip()
    approved_by = input("مين وافق؟ ").strip()

    if approval_manager.approve_approval(
        approval_id,
        approved_by=approved_by,
    ):
        print("تم اعتماد الموافقة:", approval_id)
    else:
        print("الموافقة غير موجودة.")


def revoke_approval(approval_manager):
    approval_id = input("اكتبي رقم الموافقة: ").strip()
    revoked_by = input("مين ألغى الموافقة؟ ").strip()

    if approval_manager.revoke_approval(
        approval_id,
        revoked_by=revoked_by,
    ):
        print("تم إلغاء الموافقة:", approval_id)
    else:
        print("الموافقة غير موجودة.")


def show_approvals(approval_manager):
    if not approval_manager.approvals:
        print("مفيش موافقات محفوظة.")
        return

    print("\nالموافقات:")

    for approval_id, approval in approval_manager.approvals.items():
        if approval.used:
            status = "مستخدمة"
        elif approval.is_approved:
            status = "معتمدة"
        else:
            status = "غير معتمدة"

        print(
            f"- {approval_id}: "
            f"{approval.permission_name}, "
            f"المهمة: {approval.task_id or 'غير محددة'}, "
            f"الحالة: {status}"
        )


def create_task(task_manager, project_manager=None):
    task_id = input("اكتبي رقمًا مميزًا للمهمة: ").strip()

    if task_manager.get_task(task_id) is not None:
        print("رقم المهمة مستخدم بالفعل.")
        return

    title = input("اكتبي عنوان المهمة: ").strip()
    description = input("وصف المهمة، أو Enter للتخطي: ").strip()

    project_id = input("رقم المشروع، أو Enter لمهمة مستقلة: ").strip() or None
    if project_id and (
        project_manager is None or project_manager.get_project(project_id) is None
    ):
        print("المشروع غير موجود.")
        return
    due_at = input(
        "موعد الاستحقاق بصيغة ISO 8601، أو Enter للتخطي: "
    ).strip() or None

    try:
        task_manager.add_task(
            task_id=task_id,
            title=title,
            description=description,
            project_id=project_id,
            due_at=due_at,
        )
    except ValueError as error:
        print("موعد الاستحقاق غير صحيح:", error)
        return
    print("تم حفظ المهمة:", task_id)


def create_project(project_manager, goal_manager=None):
    project_id = input("اكتبي رقمًا مميزًا للمشروع: ").strip()
    title = input("اكتبي اسم المشروع: ").strip()
    description = input("وصف المشروع، أو Enter للتخطي: ").strip()
    goal_id = input("رقم الهدف المرتبط، أو Enter للتخطي: ").strip() or None
    due_at = input(
        "موعد المشروع بصيغة ISO 8601، أو Enter للتخطي: "
    ).strip() or None
    if goal_id and (goal_manager is None or goal_manager.get_goal(goal_id) is None):
        print("الهدف غير موجود.")
        return
    try:
        project_manager.add_project(
            project_id, title, description, goal_id=goal_id, due_at=due_at
        )
    except ValueError as error:
        print("ماقدرتش أحفظ المشروع:", error)
        return
    print("تم حفظ المشروع:", project_id)


def create_goal(goal_manager, project_manager=None):
    goal_id = input("اكتبي رقمًا مميزًا للهدف: ").strip()
    intent = input("اكتبي الهدف: ").strip()
    project_id = input("رقم المشروع المرتبط، أو Enter للتخطي: ").strip() or None
    if project_id and (
        project_manager is None or project_manager.get_project(project_id) is None
    ):
        print("المشروع غير موجود.")
        return
    try:
        goal = BoodaGoal(goal_id, intent, {"project_id": project_id} if project_id else {})
        record = goal_manager.add_goal(goal, project_id=project_id)
    except (TypeError, ValueError) as error:
        print("ماقدرتش أحفظ الهدف:", error)
        return
    print("تم حفظ الهدف:", record.goal.goal_id)


def show_goals(goal_manager):
    goals = goal_manager.list_goals()
    if not goals:
        print("مفيش أهداف محفوظة.")
        return
    print("\nالأهداف:")
    for record in goals:
        print(
            f"- {record.goal.goal_id}: {record.goal.intent}, "
            f"الحالة: {record.status}, المشروع: {record.project_id or 'بدون مشروع'}"
        )


def update_goal_status(goal_manager):
    goal_id = input("اكتبي رقم الهدف: ").strip()
    print("اختاري الحالة: active / paused / completed / cancelled")
    status = input("الحالة الجديدة: ").strip()
    try:
        record = goal_manager.update_status(goal_id, status)
    except ValueError as error:
        print("الحالة غير صحيحة:", error)
        return
    if record is None:
        print("الهدف غير موجود.")
    else:
        print("تم تحديث حالة الهدف إلى:", record.status)


def show_projects(project_manager, task_manager):
    projects = project_manager.list_projects()
    if not projects:
        print("مفيش مشاريع محفوظة.")
        return
    print("\nالمشاريع:")
    for project in projects:
        task_count = len(task_manager.list_tasks(project_id=project.project_id))
        print(
            f"- {project.project_id}: {project.title}, "
            f"الحالة: {project.status}, المهام: {task_count}, "
            f"الموعد: {project.due_at or 'غير محدد'}"
        )


def show_schedule(task_manager, days=7):
    scheduler = BoodaScheduler(task_manager)
    overdue = scheduler.get_overdue_tasks()
    upcoming = scheduler.get_upcoming_tasks(days=days)
    print("\nالمهام المتأخرة:")
    if not overdue:
        print("مفيش مهام متأخرة.")
    for task in overdue:
        print(f"- {task.task_id}: {task.title} — {task.due_at}")
    print(f"\nالمهام المستحقة خلال {days} أيام:")
    if not upcoming:
        print("مفيش مهام قريبة من موعدها.")
    for task in upcoming:
        print(f"- {task.task_id}: {task.title} — {task.due_at}")


def show_dashboard(goal_manager, project_manager, task_manager, *, as_of=None, days=7):
    """Show a read-only overview of local goals, projects, tasks, and deadlines."""
    goals = goal_manager.list_goals()
    projects = project_manager.list_projects()
    tasks = task_manager.list_tasks()
    scheduler = BoodaScheduler(task_manager)
    overdue = scheduler.get_overdue_tasks(as_of=as_of)
    upcoming = scheduler.get_upcoming_tasks(days=days, as_of=as_of)

    print("\nنظرة عامة على Booda")
    print(f"الأهداف: {len(goals)} (نشطة: {sum(goal.status == 'active' for goal in goals)}, "
          f"متوقفة: {sum(goal.status == 'paused' for goal in goals)}, "
          f"مكتملة: {sum(goal.status == 'completed' for goal in goals)})")
    print(f"المشاريع: {len(projects)} (نشطة: {sum(project.status == 'active' for project in projects)}, "
          f"مكتملة: {sum(project.status == 'completed' for project in projects)})")
    print(
        f"المهام: {len(tasks)} (معلّقة: {sum(task.status == 'pending' for task in tasks)}, "
        f"قيد التنفيذ: {sum(task.status == 'running' for task in tasks)}, "
        f"مكتملة: {sum(task.status == 'completed' for task in tasks)}, "
        f"تحتاج انتباه: {sum(task.status in {'failed', 'blocked', 'uncertain'} for task in tasks)})"
    )
    print(f"المواعيد: متأخرة {len(overdue)}، وقريبة خلال {days} أيام {len(upcoming)}")
    for label, items in (("متأخرة", overdue), ("قريبة", upcoming)):
        if items:
            print(f"\nمهام {label}:")
            for task in items[:5]:
                print(f"- {task.title} [{task.task_id}] — {task.due_at}")


def show_tasks(task_manager):
    if not task_manager.tasks:
        print("مفيش مهام محفوظة.")
        return

    print("\nالمهام المحفوظة:")

    for task in task_manager.tasks.values():
        result = task.result or "لا توجد نتيجة"
        print(
            f"- {task.task_id}: {task.title}, "
            f"الحالة: {task.status}, النتيجة: {result}"
        )


def show_task_details(task_manager):
    task_id = input("اكتبي رقم المهمة: ").strip()
    task = task_manager.get_task(task_id)

    if task is None:
        print("المهمة غير موجودة.")
        return

    print("\nتفاصيل المهمة:")
    print("رقم المهمة:", task.task_id)
    print("العنوان:", task.title)
    print("الوصف:", task.description or "لا يوجد وصف")
    print("الحالة:", task.status)
    print("النتيجة:", task.result or "لا توجد نتيجة")


def update_task_status(task_manager):
    task_id = input("اكتبي رقم المهمة: ").strip()
    task = task_manager.get_task(task_id)

    if task is None:
        print("المهمة غير موجودة.")
        return

    print("\nاختاري الحالة الجديدة:")
    print("1. قيد التنفيذ")
    print("2. مكتملة")
    print("3. فشلت")

    choice = input("اختاري 1 أو 2 أو 3: ").strip()

    if choice == "1":
        task.start()
        print("تم تحديث حالة المهمة إلى: قيد التنفيذ")

    elif choice == "2":
        result = input("اكتبي النتيجة: ").strip()
        task.complete(result or None)
        print("تم تحديث حالة المهمة إلى: مكتملة")

    elif choice == "3":
        result = input("اكتبي سبب الفشل: ").strip()
        task.fail(result or None)
        print("تم تحديث حالة المهمة إلى: فشلت")

    else:
        print("الاختيار غير صحيح.")


def simulate_saved_task(
    task_manager,
    permission_manager,
    approval_manager,
    audit_log,
):
    task_id = input("اكتبي رقم المهمة: ").strip()
    task = task_manager.get_task(task_id)

    if task is None:
        print("المهمة غير موجودة.")
        return

    permission_name = input("اكتبي اسم الصلاحية المطلوبة: ").strip()
    approval_id = input(
        "رقم الموافقة، أو Enter لو مفيش: "
    ).strip()

    approval = None
    if approval_id:
        approval = approval_manager.get_approval(approval_id)

    def simulated_action():
        return f"تم التنفيذ التجريبي للمهمة: {task.title}"

    executor = BoodaExecutor()
    permission_policy = BoodaPermissionPolicy()

    result = executor.execute(
        task=task,
        action=simulated_action,
        permission_manager=permission_manager,
        permission_name=permission_name,
        permission_policy=permission_policy,
        approval=approval,
        audit_log=audit_log,
        requested_by="Yomna",
    )

    if task.status == "completed":
        print(result)
    elif task.status == "uncertain":
        print("نتيجة التنفيذ غير مؤكدة؛ لا تعيدي المحاولة قبل مراجعة الأثر:", task.result)
    else:
        print("لم يتم تنفيذ المهمة:", task.result)


def save_task_as_file(task_manager, permission_manager, audit_log):
    task_id = input("اكتبي رقم المهمة: ").strip()
    task = task_manager.get_task(task_id)

    if task is None:
        print("المهمة غير موجودة.")
        return

    def save_announcement():
        return save_task_content(task)

    executor = BoodaExecutor()
    permission_policy = BoodaPermissionPolicy()

    result = executor.execute(
        task=task,
        action=save_announcement,
        permission_manager=permission_manager,
        permission_name="save_file",
        permission_policy=permission_policy,
        audit_log=audit_log,
        requested_by="Yomna",
    )

    if task.status == "completed":
        print("تم حفظ محتوى المهمة في:", result)
    elif task.status == "uncertain":
        print("نتيجة الحفظ غير مؤكدة؛ راجعي الملف قبل إعادة المحاولة:", task.result)
    else:
        print("لم يتم حفظ الملف:", task.result)


def show_saved_announcements():
    files = list_saved_announcements()

    if not files:
        print("مفيش إعلانات محفوظة.")
        return

    print("\nالإعلانات المحفوظة كمسودات:")

    for file_path in files:
        print(f"\n--- {file_path.name} ---")
        print(file_path.read_text(encoding="utf-8").rstrip())


def edit_saved_announcement():
    files = list_saved_announcements()

    if not files:
        print("مفيش إعلانات محفوظة للتعديل.")
        return

    print("\nاختاري الإعلان اللي عايزة تعدليه:")

    for number, file_path in enumerate(files, start=1):
        print(f"{number}. {file_path.name}")

    choice = input("اكتبي رقم الإعلان: ").strip()

    if not choice.isdigit():
        print("الاختيار غير صحيح.")
        return

    index = int(choice) - 1

    if index < 0 or index >= len(files):
        print("الاختيار غير صحيح.")
        return

    file_path = files[index]
    current = read_saved_announcement(file_path)

    print("\nالعنوان الحالي:", current["title"])
    print("الوصف الحالي:", current["description"])

    new_title = input(
        "اكتبي العنوان الجديد، أو Enter للإبقاء على الحالي: "
    ).strip()
    new_description = input(
        "اكتبي الوصف الجديد، أو Enter للإبقاء على الحالي: "
    ).strip()

    print("\n1. حفظ التعديل")
    print("2. إلغاء")

    confirmation = input("اختاري 1 أو 2: ").strip()

    if confirmation != "1":
        print("تم إلغاء التعديل.")
        return

    try:
        updated_path, backup_path = update_saved_announcement(
            file_path=file_path,
            new_title=new_title or current["title"],
            new_description=new_description or current["description"],
        )
    except (FileNotFoundError, ValueError) as error:
        print("ماقدرتش أعدّل الإعلان:", error)
        return

    print("تم تعديل الإعلان:", updated_path.name)
    print("النسخة الأصلية محفوظة في:", backup_path.name)


def show_permission_status(permission_manager):
    print("\nحالة الصلاحيات:")

    for permission in permission_manager.permissions.values():
        status = "مسموحة" if permission.allowed else "مرفوضة"
        print(f"- {permission.name}: {status}")


def run_ai_agent(audit_log, permission_manager, approval_manager, task_manager,
                 goal_manager=None, event_log=None, artifact_manager=None,
                 capability_registry=None, session_store=None,
                 learning_manager=None, evolution_manager=None,
                 user_profile_manager=None, knowledge_base=None,
                 structured_memory_manager=None, *, initial_goal=None,
                 voice_mode=False):
    if voice_mode and initial_goal is None:
        try:
            from core.voice import transcribe_microphone

            initial_goal = transcribe_microphone()["text"]
        except (ImportError, RuntimeError, ValueError, OSError, TimeoutError) as error:
            print("ماقدرتش أسمع الطلب:", error)
            return
        print("النص اللي سمعته Booda:", initial_goal)
        if input("هل ده طلبك؟ اكتبي نعم للمتابعة: ").strip() != "نعم":
            print("اتلغت الجلسة قبل التخطيط.")
            return

    session_store = session_store or BoodaAgentSessionStore()
    active_sessions = [
        session for session in session_store.list_sessions()
        if session.get("goal")
        and (session.get("phase") not in {"idle", "completed", "cancelled"}
             or session.get("phase") == "completed")
    ]
    resume_session = False
    if active_sessions and initial_goal is None:
        print("أهداف محفوظة للاستكمال أو مراجعة النتائج:")
        for index, session in enumerate(active_sessions, start=1):
            print(f"{index}. {session['goal']['intent']} — {session['phase']}")
        print("N. بدء هدف جديد")
        choice = input("اختاري رقم هدف، أو N لهدف جديد، أو Enter للإلغاء: ").strip()
        if choice.casefold() == "n":
            session_id = f"ai-{uuid4().hex}"
            intent = input("اكتبي هدف Booda: ").strip()
        elif choice.isdigit() and 1 <= int(choice) <= len(active_sessions):
            saved_session = active_sessions[int(choice) - 1]
            session_id = saved_session["session_id"]
            resume_session = True
            intent = None
        else:
            return
    else:
        session_id = f"ai-{uuid4().hex}"
        intent = initial_goal if initial_goal is not None else input("اكتبي هدف Booda: ").strip()
    if not resume_session and not intent:
        print("الهدف فارغ.")
        return

    try:
        user_profile_manager = user_profile_manager or BoodaUserProfileManager(
            audit_log=audit_log,
            event_log=event_log,
        )
        context_builder = BoodaContextBuilder(user_profile_manager)
        capability_registry = capability_registry or BoodaCapabilityRegistry()
        requested_provider = os.getenv("BOODA_AI_PROVIDER", "")
        provider = (
            _resolve_ai_provider(requested_provider)
            if requested_provider.strip()
            else _resolve_ai_provider("", os.getenv("BOODA_LLM_BASE_URL"))
        )
        capability = capability_registry.get("save_task_content")
        if capability is None:
            capability = capability_registry.register(
                "save_task_content",
                description="Save a task draft as a local text artifact.",
                permission_name="save_file",
                category="files",
            )
        if not capability.enabled:
            raise ValueError("The save_task_content capability is disabled.")
        if not capability.permission_name:
            raise ValueError("The save_task_content capability needs a permission policy.")
        if provider == "gemini-paid":
            from core.cost_policy import assert_paid_allowed
            assert_paid_allowed()
            print("الخدمة المقترحة: Google Gemini 3.8 Flash API، بالمستوى المدفوع.")
            print("راجع السعر الحالي: https://ai.google.dev/gemini-api/docs/pricing")
            print("سيُرسل طلبك الحالي وحالة المهام؛ الذاكرة الخاصة وسجل المحادثة محجوبان.")
            print("الحد داخل الجلسة: 20 طلبًا، و1024 توكن إخراج للطلب؛ ليس سقفًا لفاتورة حساب Google.")
            if input("هل تعتمد استخدام هذه الخدمة المدفوعة وإرسال الطلب الحالي إليها؟ اكتبي نعم: ").strip() != "نعم":
                print("لم يتم تفعيل الاتصال المدفوع.")
                return
            share_sources = input("هل تسمح بإرسال مقتطفات المراجع المسترجعة في نطاق هذه الجلسة؟ نعم أو لا: ").strip() == "نعم"
            gemini_key = os.getenv("BOODA_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not gemini_key:
                gemini_key = getpass("Gemini API key (إدخال مخفي، لا يُحفظ): ").strip()
            planner = OpenAICompatiblePlanner.from_gemini_paid(
                api_key=gemini_key, allow_paid=True, share_local_references=share_sources,
                capability_permissions={"save_task_content": (capability.permission_name,)}, max_plan_steps=3)
            _run_ai_agent_session(
                planner, audit_log, permission_manager, approval_manager,
                task_manager, goal_manager, event_log, artifact_manager,
                capability_registry, session_store, learning_manager,
                session_id, intent, resume_session, evolution_manager,
                context_builder, knowledge_base,
                structured_memory_manager=structured_memory_manager, voice_mode=voice_mode)
        elif provider == "gemini":
            share_dialogue = False
            gemini_key = os.getenv("BOODA_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
            if not gemini_key:
                print("اكتبي مفتاح Gemini API؛ الإدخال مخفي ولن يُحفظ في ملفات بوده.")
                gemini_key = getpass("Gemini API key: ").strip()
            if not gemini_key:
                print("لم يُدخل مفتاح؛ لم يتم إرسال أي طلب.")
                return
            if os.getenv("BOODA_GEMINI_FREE_TIER_CONFIRMED") != "1":
                print("لضمان عدم وجود تكلفة، استخدمي مفتاح مشروع Google AI Studio غير مربوط بالفوترة.")
                free_project_confirmed = input(
                    "هل تأكدتِ أن المشروع على المستوى المجاني وغير مربوط بالفوترة؟ اكتبي نعم: "
                ).strip()
                if free_project_confirmed != "نعم":
                    print("أوقفت الاتصال؛ لم يتم إرسال أي طلب إلى Gemini.")
                    return
            print("Google قد تستخدم محتوى المستوى المجاني لتحسين منتجاتها. الملفات والذاكرة الخاصة محجوبة.")
            share_dialogue = input("هل تسمح بإرسال آخر 3 تبادلات قصيرة من هذه المحادثة لفهم المتابعة؟ نعم أو لا: ").strip() == "نعم"
            share_sources = input("هل تسمح بإرسال مقتطفات المراجع المسترجعة في نطاق المهمة؟ بدون مسارات الملفات؛ نعم أو لا: ").strip() == "نعم"
            planner = OpenAICompatiblePlanner.from_gemini_free_tier(
                api_key=gemini_key,
                capability_permissions={
                    "save_task_content": (capability.permission_name,)
                },
                max_plan_steps=3,
                share_conversation_history=share_dialogue,
                share_local_references=share_sources,
            )
            print("بستخدم Gemini Flash من حصته المجانية؛ لا يوجد تحويل تلقائي لخدمة مدفوعة.")
            _run_ai_agent_session(
                planner, audit_log, permission_manager, approval_manager,
                task_manager, goal_manager, event_log, artifact_manager,
                capability_registry, session_store, learning_manager,
                session_id, intent, resume_session, evolution_manager,
                context_builder, knowledge_base,
                structured_memory_manager=structured_memory_manager,
                voice_mode=voice_mode,
            )
        elif provider == "mock":
            print("وضع Demo / Mock: لا يوجد اتصال خارجي ولا تشغيل لنموذج محلي.")
            planner = BoodaMockPlanner(
                permission_name=capability.permission_name
            )
            _run_ai_agent_session(
                planner, audit_log, permission_manager, approval_manager,
                task_manager, goal_manager, event_log, artifact_manager,
                capability_registry, session_store, learning_manager,
                session_id, intent, resume_session, evolution_manager,
                context_builder, knowledge_base,
                structured_memory_manager=structured_memory_manager,
                voice_mode=voice_mode,
            )
        elif provider == "local-tools":
            print("وضع الأدوات المحلي: الخطة تُراجع قبل التنفيذ، ولا تُمنح صلاحيات تلقائيًا.")
            with ExitStack() as runtime:
                server_started = False
                def local_transport(url, payload):
                    nonlocal server_started
                    if not server_started:
                        runtime.enter_context(ensure_local_model_server())
                        server_started = True
                    return planner._send_request(url, payload)
                planner = OpenAICompatiblePlanner(
                    base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL, timeout=90,
                    capability_permissions={"save_task_content": (capability.permission_name,)},
                    max_plan_steps=3, transport=local_transport,
                )
                _run_ai_agent_session(
                    planner, audit_log, permission_manager, approval_manager,
                    task_manager, goal_manager, event_log, artifact_manager,
                    capability_registry, session_store, learning_manager,
                    session_id, intent, resume_session, evolution_manager,
                    context_builder, knowledge_base,
                    structured_memory_manager=structured_memory_manager,
                    voice_mode=voice_mode,
                )
        elif provider == "local":
            if BoodaOfflineAdPlanner.supports_goal(intent):
                print(
                    "هستخدم مهارة إعلانات محلية بدون نموذج؛ "
                    "المسودة قالب أولي وستظهر للمراجعة قبل الحفظ."
                )
                planner = BoodaOfflineAdPlanner(
                    permission_name=capability.permission_name
                )
                _run_ai_agent_session(
                    planner, audit_log, permission_manager, approval_manager,
                    task_manager, goal_manager, event_log, artifact_manager,
                    capability_registry, session_store, learning_manager,
                    session_id, intent, resume_session, evolution_manager,
                    context_builder, knowledge_base,
                    structured_memory_manager=structured_memory_manager,
                    voice_mode=voice_mode,
                )
                return
            plan_capability = capability_registry.get("create_plan_artifact")
            if plan_capability is None:
                plan_capability = capability_registry.register(
                    "create_plan_artifact",
                    description=(
                        "Save an approved multi-step plan as a local-only artifact."
                    ),
                    permission_name="save_file",
                    category="planning",
                )
            if not plan_capability.enabled:
                raise ValueError("The create_plan_artifact capability is disabled.")
            if not plan_capability.permission_name:
                raise ValueError(
                    "The create_plan_artifact capability needs a permission policy."
                )
            if plan_capability.permission_name != "save_file":
                raise ValueError(
                    "The local create_plan_artifact capability must use save_file."
                )
            if BoodaOfflineMarketingPlanner.supports_goal(intent):
                print(
                    "هستخدم مهارة تخطيط تسويقي محلية بدون نموذج؛ "
                    "الخطة أولية وستظهر للمراجعة قبل الحفظ."
                )
                planner = BoodaOfflineMarketingPlanner(
                    permission_name=plan_capability.permission_name
                )
                _run_ai_agent_session(
                    planner, audit_log, permission_manager, approval_manager,
                    task_manager, goal_manager, event_log, artifact_manager,
                    capability_registry, session_store, learning_manager,
                    session_id, intent, resume_session, evolution_manager,
                    context_builder, knowledge_base,
                    structured_memory_manager=structured_memory_manager,
                    voice_mode=voice_mode,
                )
                return
            print("ببدأ تشغيل نموذج Booda المحلي المجاني...")
            with ensure_local_model_server() as base_url:
                planner = OpenAICompatiblePlanner(
                    base_url=base_url,
                    model=LOCAL_LLM_MODEL,
                    api_key=None,
                    timeout=180,
                    capability_permissions={
                        "create_plan_artifact": (plan_capability.permission_name,)
                    },
                    max_plan_steps=7,
                    min_plan_steps=3,
                    local_planning=True,
                )
                _run_ai_agent_session(
                    planner, audit_log, permission_manager, approval_manager,
                    task_manager, goal_manager, event_log, artifact_manager,
                    capability_registry, session_store, learning_manager,
                    session_id, intent, resume_session, evolution_manager,
                    context_builder, knowledge_base,
                    structured_memory_manager=structured_memory_manager,
                    voice_mode=voice_mode,
                )
        elif provider == "ollama":
            ollama_url = os.getenv("BOODA_OLLAMA_BASE_URL", OLLAMA_BASE_URL)
            hostname = (urlparse(ollama_url).hostname or "").casefold()
            if hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError(
                    "Ollama mode only accepts a model server on this computer."
                )
            if not capability.enabled:
                raise ValueError("The save_task_content capability is disabled.")
            model = os.getenv("BOODA_OLLAMA_MODEL", OLLAMA_DEFAULT_MODEL)
            planner = OpenAICompatiblePlanner(
                base_url=ollama_url,
                model=model,
                api_key=None,
                timeout=180,
                capability_permissions={
                    "save_task_content": (capability.permission_name,)
                },
                max_plan_steps=3,
            )
            print(f"بستخدم نموذج Ollama المحلي: {model}")
            _run_ai_agent_session(
                planner, audit_log, permission_manager, approval_manager,
                task_manager, goal_manager, event_log, artifact_manager,
                capability_registry, session_store, learning_manager,
                session_id, intent, resume_session, evolution_manager,
                context_builder, knowledge_base,
                structured_memory_manager=structured_memory_manager,
                voice_mode=voice_mode,
            )
        elif provider in {"openai", "remote"}:
            planner_options = {
                "capability_permissions": {
                    "save_task_content": (capability.permission_name,)
                },
                "max_plan_steps": 3,
            }
            planner = OpenAICompatiblePlanner.from_env(**planner_options)
            _run_ai_agent_session(
                planner, audit_log, permission_manager, approval_manager,
                task_manager, goal_manager, event_log, artifact_manager,
                capability_registry, session_store, learning_manager,
                session_id, intent, resume_session, evolution_manager,
                context_builder, knowledge_base,
                structured_memory_manager=structured_memory_manager,
                voice_mode=voice_mode,
            )
        else:
            raise ValueError(
                "Unknown BOODA_AI_PROVIDER. Choose 'gemini', 'gemini-paid', 'local', 'local-tools', 'ollama', 'mock', or 'openai'."
            )
    except (RuntimeError, ValueError, TypeError, OSError, sqlite3.Error) as error:
        print("ماقدرتش أجهز خطة AI:", error)


def _run_ai_agent_session(
    planner, audit_log, permission_manager, approval_manager, task_manager,
    goal_manager, event_log, artifact_manager, capability_registry,
    session_store, learning_manager, session_id, intent, resume_session,
    evolution_manager=None,
    context_builder=None,
    knowledge_base=None,
    structured_memory_manager=None,
    voice_mode=False,
):
    registry = BoodaToolRegistry(capability_registry)

    def save_and_catalog_task_content(task):
        path = save_task_content(task)
        if artifact_manager is not None:
            artifact_manager.register(
                path,
                kind="task_draft",
                goal_id=task.goal_id,
                project_id=task.project_id,
                task_id=task.task_id,
            )
        return path

    registry.register("save_task_content", save_and_catalog_task_content)
    planner_hostname = (
        urlparse(getattr(planner, "base_url", "")).hostname or ""
    ).casefold()
    laptop_tools_allowed = (
        planner_hostname in {"localhost", "127.0.0.1", "::1"}
        and not getattr(planner, "local_planning", False)
        and not isinstance(planner, BoodaMockPlanner)
    )
    laptop_root = os.getenv("BOODA_LAPTOP_ROOT") if laptop_tools_allowed else None
    if laptop_root:
        connection = BoodaLaptopConnection(laptop_root)
        connection.register_read_tools(registry, capability_registry)
        if planner.capability_permissions is not None:
            planner.capability_permissions = dict(planner.capability_permissions,
                **{name: (LAPTOP_READ,) for name in ("laptop_system_info", "laptop_list_files", "laptop_read_file")})
    agent = None
    if (laptop_tools_allowed or getattr(planner, "enable_local_reasoning_tools", False)) and isinstance(planner, OpenAICompatiblePlanner):
        added = register_reasoning_tools(
            registry, capability_registry, permission_manager,
            knowledge_base=knowledge_base, ad_intelligence=BoodaAdIntelligence(),
            scope_provider=lambda: agent.state.goal.context if agent and agent.state.goal else {},
        )
        if planner.capability_permissions is not None:
            planner.capability_permissions = dict(planner.capability_permissions, **added)
    if getattr(planner, "local_planning", False):
        saved_plan_paths = {}

        def create_plan_artifact(task):
            plan = agent.state.plan
            if plan is None:
                raise RuntimeError("Cannot create a plan artifact before planning.")
            cache_key = (task.goal_id, plan.plan_id)
            if cache_key in saved_plan_paths:
                return saved_plan_paths[cache_key]
            if artifact_manager is not None:
                for artifact in artifact_manager.list(
                    goal_id=task.goal_id, kind="plan"
                ):
                    if (
                        artifact.get("metadata", {}).get("plan_id") == plan.plan_id
                        and os.path.isfile(artifact["path"])
                    ):
                        saved_plan_paths[cache_key] = artifact["path"]
                        return artifact["path"]
            tasks = [
                task_manager.get_task(step.task_id) for step in plan.steps
            ]
            if any(item is None for item in tasks):
                raise RuntimeError("Cannot save a plan with missing persisted tasks.")
            goal_record = (
                goal_manager.get_goal(task.goal_id)
                if goal_manager is not None else None
            )
            goal_text = (
                goal_record.goal.intent if goal_record is not None
                else agent.state.goal.intent
            )
            path = save_plan_artifact(task.goal_id, goal_text, tasks)
            if artifact_manager is not None:
                artifact_manager.register(
                    path,
                    kind="plan",
                    title=f"خطة محلية: {goal_text}",
                    goal_id=task.goal_id,
                    project_id=task.project_id,
                    task_id=task.task_id,
                    metadata={
                        "provider": "local",
                        "scope": "local-only",
                        "plan_id": plan.plan_id,
                    },
                )
            saved_plan_paths[cache_key] = path
            return path

        registry.register("create_plan_artifact", create_plan_artifact)
    agent = BoodaAgent(
        planner,
        task_manager,
        registry,
        BoodaExecutor(),
        permission_manager=permission_manager,
        permission_policy=BoodaPermissionPolicy(),
        approval_provider=lambda task, step: next((
            approval for approval in approval_manager.approvals.values()
            if approval.task_id == task.task_id
            and approval.permission_name == step.permission_name
            and approval.is_approved
            and not approval.used
        ), None),
        memory=JsonlBoodaMemory(),
        structured_memory=structured_memory_manager,
        research_manager=BoodaResearchManager(event_log=event_log),
        audit_log=audit_log,
        requested_by="Yomna",
        goal_manager=goal_manager,
        event_log=event_log,
        session_store=session_store,
        session_id=session_id,
        learning_manager=learning_manager,
        evolution_manager=evolution_manager,
        context_builder=context_builder,
        knowledge_base=knowledge_base,
        verifier=BoodaArtifactVerifier(
            lambda: agent.state.plan.steps if agent.state.plan else (),
            task_manager,
            knowledge_base=knowledge_base,
        ),
    )
    speech_unavailable = False

    def speak_reply(text):
        nonlocal speech_unavailable
        if not voice_mode or speech_unavailable:
            return
        from core.voice import speak_arabic

        try:
            if not speak_arabic(
                str(text)[:MAX_VOICE_REPLY_CHARACTERS],
                dialect_memory=structured_memory_manager,
            ):
                speech_unavailable = True
                print("الصوت المصري المحلي مش جاهز؛ هتظهر الردود مكتوبة.")
        except (RuntimeError, OSError) as error:
            speech_unavailable = True
            print("الرد الصوتي غير متاح دلوقتي؛ هتظهر الردود مكتوبة:", error)

    try:
        if resume_session:
            goal = agent.state.goal
            if goal is None:
                raise ValueError("Saved agent session has no goal to resume.")
            plan = agent.state.plan or agent.plan()
            if agent.state.interrupted_task_id is not None:
                interrupted_id = agent.state.interrupted_task_id
                print(
                    f"المهمة {interrupted_id} توقفت أثناء التنفيذ؛ "
                    "قد يكون أثرها حصل بالفعل."
                )
                if input("إعادة المحاولة؟ اكتبي نعم للتأكيد: ").strip() != "نعم":
                    print("سيظل الهدف محفوظًا بانتظار قرارك.")
                    return
                agent.retry_interrupted_task(interrupted_id)
        else:
            scope = {key: os.getenv(variable).strip() for key, variable in (
                ("project_id", "BOODA_PROJECT_ID"), ("client_id", "BOODA_CLIENT_ID")
            ) if os.getenv(variable, "").strip()}
            goal = BoodaGoal(f"ai-{uuid4().hex}", intent, scope)
            if scope:
                print("نطاق الجلسة:", scope)
            agent.intake(goal)
            plan = agent.plan()
    except (RuntimeError, ValueError, TypeError) as error:
        print("ماقدرتش أجهز خطة AI:", error)
        return

    if resume_session and agent.state.phase == "completed":
        print("استكمال محادثة الهدف المكتمل؛ لن تُعاد خطوات التنفيذ.")
        _agent_chat_loop(agent, voice_mode=voice_mode, speak_reply=speak_reply)
        return
    print("\nخطة Booda للمراجعة:")
    for step in plan.steps:
        print(f"- {step.title}: {step.description}")
        print(f"  الصلاحية المطلوبة: {step.permission_name}")
    if not plan.steps:
        print("الخطة لا تحتوي مهام.")
        return
    if voice_mode:
        plan_summary = "دي خطة بوده للمراجعة. " + " ".join(
            f"{step.title}. {step.description}" for step in plan.steps
        )
        speak_reply(plan_summary)
    if input("تنفذي الخطة؟ اكتبي نعم للمتابعة: ").strip() != "نعم":
        print("تم إيقاف الخطة قبل التنفيذ.")
        return
    if not agent.state.plan_reviewed:
        agent.approve_plan(plan.plan_id)

    while True:
        outcomes = agent.run_until_blocked()
        waiting = outcomes[-1] if outcomes and isinstance(outcomes[-1], dict) else None
        if agent.state.phase == "completed":
            if all(step.capability == "create_plan_artifact" for step in agent.state.plan.steps):
                print("تم حفظ ملف الخطة ومراجعة محتواه؛ تنفيذ الهدف نفسه لم يتم بهذه الأداة.")
                speak_reply("الخطة اتحفظت واتراجع محتواها على الجهاز.")
            else:
                print("اكتملت خطوات الأدوات المسجلة؛ راجعي المخرجات وحدود التحقق.")
                speak_reply("خلصت الخطوات المسجلة. بصّي على النتيجة اللي ظاهرة على الشاشة.")
            break
        if agent.state.phase == "waiting_for_permission":
            pending = waiting["task"]
            step = next(step for step in plan.steps if step.task_id == pending.task_id)
            permission_name = step.permission_name
            print(f"المهمة {pending.task_id} تحتاج صلاحية {permission_name}.")
            speak_reply(f"المهمة محتاجة صلاحية {permission_name}. بصّي على الشاشة.")
            if input("هل تمنحي الصلاحية الآن؟ اكتبي نعم: ").strip() == "نعم":
                permission_manager.grant_permission(permission_name, changed_by="Yomna")
                continue
            print("توقّف التنفيذ بانتظار الصلاحية.")
            break
        if agent.state.phase == "waiting_for_approval":
            pending = waiting["task"]
            step = next(step for step in plan.steps if step.task_id == pending.task_id)
            print(f"المهمة {pending.task_id} تحتاج موافقة على {step.permission_name}.")
            speak_reply(f"المهمة محتاجة موافقة على {step.permission_name}. بصّي على الشاشة.")
            if input("هل تعتمدي هذه المهمة؟ اكتبي نعم: ").strip() == "نعم":
                approval_id, _ = approval_manager.create_approval(
                    permission_name=step.permission_name,
                    approved_by="Yomna",
                    reason=goal.intent,
                    task_id=pending.task_id,
                    created_by="Yomna",
                )
                approval_manager.approve_approval(approval_id, approved_by="Yomna")
                continue
            print("توقّف التنفيذ بانتظار الموافقة.")
            break
        if agent.state.phase == "waiting_for_capability":
            print("توقّف التنفيذ: الأداة المطلوبة غير متاحة.")
            break
        if agent.state.phase == "needs_attention":
            print("توقّف التنفيذ لأن مهمة فشلت أو تعذرت.")
            speak_reply("وقفت التنفيذ عشان خطوة ما نجحتش. شوفي التفاصيل على الشاشة.")
            if input("تحبي أجهز خطة إصلاح للمراجعة؟ اكتبي نعم: ").strip() != "نعم":
                break
            reason = input("إيه اللي محتاج يتغير في الخطة؟ ").strip()
            try:
                plan = agent.replan(reason)
            except (RuntimeError, ValueError, TypeError) as error:
                print("ماقدرتش أجهز خطة الإصلاح:", error)
                break
            print("\nالخطة الجديدة للمراجعة:")
            for step in plan.steps:
                print(f"- {step.title}: {step.description}")
            if input("تعتمدي الخطة الجديدة؟ اكتبي نعم: ").strip() == "نعم":
                agent.approve_plan(plan.plan_id)
                continue
            print("الخطة محفوظة بانتظار مراجعتك.")
            break
        print("لم تعد هناك مهام جاهزة للتنفيذ.")
        break

    _agent_chat_loop(agent, voice_mode=voice_mode, speak_reply=speak_reply)


def _agent_chat_loop(agent, *, voice_mode, speak_reply):
    while True:
        if voice_mode:
            typed_message = input(
                "اضغطي Enter للتحدث إلى Booda، أو اكتبي x للعودة للقائمة: "
            ).strip()
            if typed_message.casefold() == "x":
                break
            if typed_message:
                message = typed_message
            else:
                try:
                    from core.voice import transcribe_microphone

                    transcription = transcribe_microphone(seconds=12)
                    message = transcription["text"]
                    print("النص اللي سمعته Booda:", message)
                    if input("هل السؤال صحيح؟ اكتبي نعم للإجابة: ").strip() != "نعم":
                        continue
                except (ImportError, RuntimeError, ValueError, OSError, TimeoutError) as error:
                    print("ماقدرتش أسمع السؤال:", error)
                    continue
        else:
            message = input("اسألي بوده؛ /مهمة ثم الطلب لتنفيذ جديد، /نفذ للمتابعة، /حالة، /تصحيح، أو Enter للرجوع: ").strip()
        if not message:
            break
        from core.local_workspace import local_reply
        try:
            local_answer = local_reply(message, knowledge_base=agent.knowledge_base,
                scope=agent.state.goal.context if agent.state.goal else {})
        except (ValueError, OSError, RuntimeError) as error:
            print("لم تكتمل العملية المحلية:", error)
            continue
        if local_answer is not None:
            print("\nBooda:", local_answer)
            speak_reply(local_answer)
            continue
        if message in {"/نفذ", "/حالة"}:
            from core.autonomy import continue_reviewed_work, execution_report, describe_execution
            try:
                report = continue_reviewed_work(agent) if message == "/نفذ" else execution_report(agent)
                print("\nBooda:", describe_execution(report))
            except (RuntimeError, ValueError, OSError) as error:
                print("توقفت المتابعة:", error)
            continue
        if message.startswith("/مهمة "):
            from uuid import uuid4
            try:
                scope = dict(agent.state.goal.context) if agent.state.goal else {}
                # Acceptance criteria belong to the old request, never a new task.
                scope.pop("acceptance", None)
                agent.intake(BoodaGoal("ai-" + uuid4().hex, message[6:].strip(), scope))
                plan = agent.plan()
                print("خطة المهمة الجديدة:")
                for step in plan.steps:
                    print(f"- {step.title}: {step.description}؛ الصلاحية: {step.permission_name}")
                if input("اعتماد هذه الخطة؟ اكتبي نعم: ").strip() == "نعم":
                    agent.approve_plan(plan.plan_id)
                    from core.autonomy import continue_reviewed_work, describe_execution
                    print(describe_execution(continue_reviewed_work(agent)))
                else:
                    print("الخطة محفوظة ولم تُنفذ.")
            except (RuntimeError, ValueError, TypeError, OSError) as error:
                print("لم تكتمل المهمة الجديدة:", error)
            continue
        if message == "/تصحيح":
            wrong = input("إيه المعلومة أو التصرف الغلط؟ ").strip()
            correction = input("إيه التصحيح؟ ").strip()
            reason = input("إيه سبب التصحيح؟ ").strip()
            confirmed = input("أحفظ ده كدرس في نطاق الهدف الحالي؟ اكتبي نعم: ").strip() == "نعم"
            if not confirmed:
                print("لم يُحفظ التصحيح.")
                continue
            try:
                agent.record_user_correction(wrong, correction, reason, user_confirmed=True)
                print("اتحفظ الدرس؛ ده لا يغيّر أوزان النموذج أو يمنح صلاحيات.")
            except (ValueError, RuntimeError, PermissionError) as error:
                print("ماقدرتش أحفظ التصحيح:", error)
            continue
        try:
            answer = agent.respond(message)
            print("\nBooda:", answer)
            speak_reply(answer)
        except (RuntimeError, ValueError, TypeError, OSError) as error:
            print("ماقدرتش أرد على الرسالة:", error)


def main(*, shared_knowledge_base=None):
    configure_utf8_console()
    audit_log = BoodaAuditLog()
    permission_manager = BoodaPermissionManager(
        audit_log=audit_log,
        file_path="security/permissions.json",
    )
    approval_manager = BoodaApprovalManager(
        audit_log=audit_log,
        file_path="security/approvals.json",
    )
    event_log = BoodaEventLog()
    version_store = BoodaVersionStore()
    task_manager = BoodaTaskManager(
        file_path="memory/tasks.json",
        version_store=version_store,
        event_log=event_log,
    )
    project_manager = BoodaProjectManager(
        file_path="memory/projects.json",
        version_store=version_store,
        event_log=event_log,
    )
    goal_manager = BoodaGoalManager(
        version_store=version_store,
        event_log=event_log,
    )
    capability_registry = BoodaCapabilityRegistry()
    learning_manager = BoodaLearningManager(
        event_log=event_log,
        version_store=version_store,
    )
    ensure_marketing_path(learning_manager)
    knowledge_base = shared_knowledge_base or BoodaLocalKnowledgeBase(
        event_log=event_log,
        version_store=version_store,
    )
    if shared_knowledge_base is not None:
        knowledge_base.event_log = event_log
        knowledge_base.version_store = version_store
    artifact_manager = BoodaArtifactManager(
        event_log=event_log,
        version_store=version_store,
    )
    ad_intelligence = BoodaAdIntelligence(
        event_log=event_log,
        artifact_manager=artifact_manager,
    )
    evolution_manager = BoodaEvolutionManager(
        audit_log=audit_log,
        event_log=event_log,
        version_store=version_store,
    )
    user_profile_manager = BoodaUserProfileManager(
        audit_log=audit_log,
        event_log=event_log,
    )
    structured_memory_manager = BoodaStructuredMemoryStore(
        audit_log=audit_log,
    )

    if permission_manager.get_permission("save_file") is None:
        permission_manager.add_permission(
            name="save_file",
            category="files",
            risk_level="low",
            allowed=False,
        )
    if permission_manager.get_permission(EVOLUTION_PERMISSION) is None:
        permission_manager.add_permission(
            name=EVOLUTION_PERMISSION,
            category="system_evolution",
            risk_level=RiskLevel.HIGH,
            allowed=False,
        )

    permission_manager.add_permission(
        name="send_message",
        category="communication",
        allowed=False,
    )
    for permission_name, risk in ((CODE_PERMISSION, RiskLevel.HIGH), (LAPTOP_READ, RiskLevel.LOW), (LAPTOP_WRITE, RiskLevel.HIGH), (DESKTOP_PERMISSION, RiskLevel.HIGH)):
        if permission_manager.get_permission(permission_name) is None:
            permission_manager.add_permission(permission_name, category="local_system", risk_level=risk, allowed=False)
    permission_manager.add_permission(
        name="spend_money",
        category="finance",
        risk_level=RiskLevel.HIGH,
        allowed=True,
    )

    while True:
        print("\nاختاري:")
        print("1. عرض سجل التدقيق")
        print("2. تشغيل المثال التجريبي")
        print("3. منح صلاحية")
        print("4. سحب صلاحية")
        print("5. عرض حالة الصلاحيات")
        print("6. خروج")
        print("7. إنشاء موافقة")
        print("8. اعتماد موافقة")
        print("9. إلغاء موافقة")
        print("10. عرض الموافقات")
        print("11. إنشاء مهمة")
        print("12. عرض المهام")
        print("13. عرض تفاصيل مهمة")
        print("14. تحديث حالة مهمة")
        print("15. محاكاة تنفيذ مهمة محفوظة")
        print("16. حفظ محتوى المهمة كملف")
        print("17. عرض الإعلانات المحفوظة")
        print("18. تعديل إعلان محفوظ")
        print("19. تشغيل إيجنت AI على هدف")
        print("20. إنشاء مشروع")
        print("21. عرض المشاريع")
        print("22. عرض جدول المهام")
        print("23. إنشاء هدف")
        print("24. عرض الأهداف")
        print("25. تحديث حالة هدف")
        print("26. لوحة متابعة المشروع")
        print("27. إدارة الملف الشخصي والتفضيلات")
        print("28. إدارة دروس الخبرة")
        print("29. إدارة المعرفة المحلية")
        print("30. تعلم واختبار دروس التسويق")
        print("31. إدارة الذاكرة المنظمة")
        print("32. البحث والتعلم الموثق")
        print("33. تطوير كود مُراجع واختباره والتراجع عنه")
        print("34. اتصال اللابتوب بمجلد محدد")
        print("35. تحليل أداء إعلان")
        print("36. ربط التطبيقات والحسابات")
        print("37. بدء جلسة صوتية محلية")
        print("38. تعليم الصوت اللهجة المصرية")
        print("39. فحص اتصال Gemini المجاني")
        print("40. مساحة بوده المحلية بدون مفتاح")
        print("41. نافذة بوده المحلية")

        choice = input("اختاري رقمًا من 1 إلى 41: ").strip()

        if choice == "1":
            show_audit_report(audit_log)
        elif choice == "2":
            run_demo(
                audit_log,
                permission_manager,
                approval_manager,
                task_manager,
            )
        elif choice == "3":
            change_permission(permission_manager, "grant")
        elif choice == "4":
            change_permission(permission_manager, "revoke")
        elif choice == "5":
            show_permission_status(permission_manager)
        elif choice == "6":
            print("تم إغلاق Booda.")
            break
        elif choice == "7":
            create_approval(approval_manager)
        elif choice == "8":
            approve_request(approval_manager)
        elif choice == "9":
            revoke_approval(approval_manager)
        elif choice == "10":
            show_approvals(approval_manager)
        elif choice == "11":
            create_task(task_manager, project_manager)
        elif choice == "12":
            show_tasks(task_manager)
        elif choice == "13":
            show_task_details(task_manager)
        elif choice == "14":
            update_task_status(task_manager)
        elif choice == "15":
            simulate_saved_task(
                task_manager,
                permission_manager,
                approval_manager,
                audit_log,
            )
        elif choice == "16":
            save_task_as_file(
                task_manager,
                permission_manager,
                audit_log,
            )
        elif choice == "17":
            show_saved_announcements()
        elif choice == "18":
            edit_saved_announcement()
        elif choice == "19":
            run_ai_agent(
                audit_log,
                permission_manager,
                approval_manager,
                task_manager,
                goal_manager,
                event_log,
                artifact_manager,
                capability_registry,
                learning_manager=learning_manager,
                evolution_manager=evolution_manager,
                user_profile_manager=user_profile_manager,
                knowledge_base=knowledge_base,
                structured_memory_manager=structured_memory_manager,
            )
        elif choice == "20":
            create_project(project_manager, goal_manager)
        elif choice == "21":
            show_projects(project_manager, task_manager)
        elif choice == "22":
            show_schedule(task_manager)
        elif choice == "23":
            create_goal(goal_manager, project_manager)
        elif choice == "24":
            show_goals(goal_manager)
        elif choice == "25":
            update_goal_status(goal_manager)
        elif choice == "26":
            show_dashboard(goal_manager, project_manager, task_manager)
        elif choice == "27":
            manage_preferences(user_profile_manager)
        elif choice == "28":
            manage_experience_lessons(evolution_manager, learning_manager)
        elif choice == "29":
            manage_local_knowledge_base(knowledge_base)
        elif choice == "30":
            manage_learning_course(learning_manager)
        elif choice == "31":
            manage_structured_memory(structured_memory_manager)
        elif choice == "32":
            manage_research(BoodaResearchManager(knowledge_base=knowledge_base, event_log=event_log),
                            evolution_manager=evolution_manager, task_manager=task_manager)
        elif choice == "33":
            manage_code_evolution(permission_manager, approval_manager, audit_log)
        elif choice == "34":
            manage_laptop(permission_manager, approval_manager, audit_log)
        elif choice == "35":
            manage_ad_intelligence_menu(ad_intelligence)
        elif choice == "36":
            manage_integrations()
        elif choice == "37":
            run_ai_agent(
                audit_log,
                permission_manager,
                approval_manager,
                task_manager,
                goal_manager,
                event_log,
                artifact_manager,
                capability_registry,
                learning_manager=learning_manager,
                evolution_manager=evolution_manager,
                user_profile_manager=user_profile_manager,
                knowledge_base=knowledge_base,
                structured_memory_manager=structured_memory_manager,
                voice_mode=True,
            )
        elif choice == "38":
            manage_egyptian_dialect(structured_memory_manager)
        elif choice == "39":
            from tools.check_free_gemini import main as check_free_connection
            check_free_connection()
        elif choice == "40":
            from core.local_workspace import run_workspace
            run_workspace()
        elif choice == "41":
            try:
                from tools.local_workspace_gui import main as open_local_window
                open_local_window()
            except (ImportError, RuntimeError, OSError) as error:
                print("تعذر فتح النافذة؛ مساحة العمل النصية متاحة بالخيار 40:", error)
        else:
            print("الاختيار غير صحيح.")


if __name__ == "__main__":
    main()
