"""Human-reviewed code evolution and scoped laptop connection menus."""

import json
from pathlib import Path

from core.code_evolution import BoodaCodeEvolution, CODE_PERMISSION
from core.laptop import BoodaLaptopConnection, LAPTOP_WRITE, LAPTOP_READ


def _approval(permission, task_id, approval_manager):
    approval_id, approval = approval_manager.create_approval(permission, approved_by="user",
        reason="Explicitly reviewed operation", task_id=task_id, created_by="system_menu")
    approval_manager.approve_approval(approval_id, approved_by="user")
    return approval


def manage_code_evolution(permission_manager, approval_manager, audit_log):
    engine = BoodaCodeEvolution()
    while True:
        print("\nتطوير الكود: 1 تجهيز تعديل | 2 مراجعة واختبار | 3 تطبيق | 4 تراجع | 5 توليد مقترح محلي | 6 عرض التعديلات | 0 رجوع")
        try:
            choice = input("الاختيار: ").strip()
            if choice == "0":
                return
            if choice in {"1", "5"}:
                target = input("الموديول مثل core/learning.py: ").strip()
                tests = input("ملفات الاختبار مفصولة بفواصل؛ فارغ لكل الاختبارات: ").strip()
                test_files = [t.strip() for t in tests.split(",")] if tests else [p.as_posix() for p in Path("tests").glob("test_*.py")]
                if choice == "1":
                    draft = Path(input("ملف المسودة المحلية البديلة: ").strip()).resolve(strict=True)
                    if not draft.is_relative_to(engine.root) or draft.stat().st_size > 200_000:
                        raise ValueError("اختر مسودة صغيرة داخل المشروع.")
                    change = engine.prepare(target, draft.read_text(encoding="utf-8"), test_files=test_files)
                else:
                    from core.local_model import ensure_local_model_server
                    from core.semantic_research import BoodaSemanticAnalyzer
                    instruction = input("التحسين المحدد المطلوب: ")
                    with ensure_local_model_server() as endpoint:
                        change = engine.generate(target, instruction, generator=BoodaSemanticAnalyzer(base_url=endpoint), test_files=test_files)
                print(change["id"], change["diff"], "النسخة المجهزة:", engine.lab / change["id"])
            elif choice == "2":
                change = engine.get(input("معرّف التعديل: ").strip())
                print(change["diff"], "اختبارات:", change["test_files"], "المصدر والاختبارات الكاملة:", engine.lab / change["id"])
                print("التجهيز يعزل ملفات المشروع، لكنه ليس عزلًا أمنيًا للنظام؛ الاختبارات تعمل بصلاحيات المستخدم.")
                if input("بعد مراجعة الكود والاختبارات، اكتب راجعت لتشغيلها: ").strip() == "راجعت":
                    engine.mark_reviewed(change["id"], stage_digest=change["stage_digest"])
                    result = engine.validate(change["id"])
                    print(result["status"], result["validation"]["output"])
            elif choice in {"3", "4"}:
                change = engine.get(input("معرّف التعديل: ").strip())
                print(change["path"], change["diff"])
                rollback = choice == "4"
                phrase = "تراجع" if rollback else "تطبيق"
                if input(f"اكتب {phrase} لتأكيد العملية المحددة: ").strip() == phrase:
                    task_id = change["rollback_task_id"] if rollback else change["apply_task_id"]
                    approval = _approval(CODE_PERMISSION, task_id, approval_manager)
                    task = engine.transition(change["id"], rollback=rollback, permission_manager=permission_manager,
                                             approval=approval, audit_log=audit_log)
                    print(task.status, task.result)
            elif choice == "6":
                for change in engine.list_changes():
                    print(change["id"], change["path"], change["status"])
        except (ValueError, OSError, KeyError, RuntimeError, SyntaxError) as error:
            print("تعذرت العملية:", str(error))


def manage_laptop(permission_manager, approval_manager, audit_log):
    print("1 اتصال بالملفات | 2 التحكم في الشاشة والمتصفح والفيديو")
    if input("نوع الاتصال [1]: ").strip() == "2":
        return manage_desktop(permission_manager, approval_manager, audit_log)
    try:
        root = input("مسار المجلد الذي تسمح لبودا بالتعامل معه: ").strip()
        connection = BoodaLaptopConnection(root)
    except (ValueError, OSError) as error:
        print("لم يتم الاتصال:", str(error))
        return
    print("اتصال محلي بالمجلد:", connection.root, "الصلاحيات المطلوبة:", LAPTOP_READ, LAPTOP_WRITE)
    print("المرحلة الحالية للملفات ومعلومات النظام؛ لا تحكم بالماوس أو لوحة المفاتيح ولا أوامر عامة.")
    while True:
        print("1 معلومات النظام | 2 عرض ملفات | 3 قراءة ملف | 4 إنشاء ملف جديد بموافقة | 0 قطع الاتصال")
        choice = input("الاختيار: ").strip()
        try:
            if choice == "0":
                return
            operations = {"1": "system_info", "2": "list_files", "3": "read_file", "4": "write_file"}
            if choice not in operations:
                continue
            operation, parameters = operations[choice], {}
            if choice == "2":
                parameters["path"] = input("مجلد نسبي [.]: ").strip() or "."
            elif choice in {"3", "4"}:
                parameters["path"] = input("مسار ملف نسبي: ").strip()
            if choice == "4":
                parameters["content"] = input("النص الذي سيُحفظ: ")
            task = connection.task_for(operation, parameters)
            approval = None
            if choice == "4":
                print("المجلد:", connection.root, "طلب الكتابة:", parameters)
                if input("اكتب إنشاء للموافقة على هذا الملف والمحتوى: ").strip() != "إنشاء":
                    continue
                approval = _approval(LAPTOP_WRITE, task.task_id, approval_manager)
            connection.execute(task, permission_manager=permission_manager, approval=approval, audit_log=audit_log)
            print(task.status, json.dumps(task.result, ensure_ascii=False, default=str))
        except (ValueError, OSError, KeyError, RuntimeError) as error:
            print("تعذرت العملية:", str(error))


def manage_desktop(permission_manager, approval_manager, audit_log):
    from core.desktop_control import BoodaDesktopController, WindowsDesktopBackend, DESKTOP_PERMISSION
    try:
        media = input("مجلد الملفات والصور والفيديو المسموح به؛ فارغ لتخطيه: ").strip() or None
        default_model = Path(".local-ai-runtime/models/speech-tiny")
        model = input("مجلد نموذج faster-whisper المحلي؛ فارغ للنموذج الصغير إن كان مثبتًا: ").strip() or (str(default_model) if default_model.is_dir() else None)
        controller = BoodaDesktopController(WindowsDesktopBackend(media_root=media, model_path=model))
    except (ImportError, OSError, RuntimeError) as error:
        print("تعذر الاتصال:", error, "ثبّت requirements-desktop.txt في بيئة تشغيل بودا.")
        return
    print("كل إجراء يحتاج موافقة منفصلة. حرّك الماوس لركن الشاشة لإيقاف إدخال الماوس/الكيبورد، أو Ctrl+C لقطع الجلسة.")
    print("الصور والتفريغ محفوظة محليًا داخل outputs/desktop. فتح الرابط لا يضمن بدء تشغيل الفيديو؛ راجع الشاشة.")
    last_proposal = None
    workflow = None
    workflow_choice = "17"
    dialog_approval = False
    while True:
        try:
            print("1 صورة الشاشة | 2 تحريك | 3 نقرة | 4 سحب | 5 تمرير | 6 كتابة | 7 مفتاح | 8 فتح رابط/فيديو | 9 بحث | 10 تفريغ ملف صوت/فيديو | 11 يشاهد شغلي | 12 فتح تطبيق | 13 تشغيل ملف فيديو | 0 إيقاف")
            print("14 اسأل بودا عن الشاشة | 15 مراجعة آخر اقتراح لتنفيذه | 16 اطلب اقتراح خطوة")
            print("17 اختبار مهمة بخطوات: مفكرة جديدة ثم نص تجريبي، مع موافقة وتحقق لكل خطوة")
            print("18 إظهار نافذة مصغّرة | 19 قراءة أزرار وعناصر نافذة | 20 التحقق من ظهور نص")
            print("21 قراءة صفحة ويب عامة | 22 قراءة رابط ملف ترجمة فيديو VTT/SRT")
            print("23 تبديل الموافقة بين نافذة عربية والكتابة؛ الحالي:", "نافذة" if dialog_approval else "كتابة")
            print("24 فحص جاهزية الأدوات | 25 قراءة نص الشاشة عربي/إنجليزي")
            print("26 فتح متصفح بودا | 27 قراءة صفحته وعناصرها | 28 نقر عنصر بالاسم | 29 كتابة في مربع بالاسم")
            print("30 قراءة PDF/Word/Excel/صورة | 31 تنزيل رابط صوت/فيديو مباشر | 32 معلومات ملف الوسائط")
            print("33 اكتشاف روابط الفيديو والترجمة في صفحة | 34 قراءة ترجمة فيديو YouTube المتاحة")
            print("35 اطلب مهمة بالكلام واعرض خطواتها | 36 مراجعة الخطوة التالية | 37 حفظ تصحيح بموافقتك | 38 استرجاع تصحيحات")
            choice = input("الاختيار: ").strip()
            if choice == "0":
                controller.stop()
                return
            if choice == "23":
                dialog_approval = not dialog_approval
                continue
            if choice == "24":
                from core.tool_readiness import inspect_tools
                readiness = inspect_tools()
                for row in readiness["tools"]:
                    print(row["tool"], "جاهز للتجربة" if row["installed"] else "يحتاج تثبيت")
                print(readiness["message"])
                continue
            if choice not in {"17", "36"} and workflow is not None:
                workflow.stop()
                workflow = None
            if choice == "35":
                from core.desktop_requests import request_plan
                from core.desktop_lessons import DesktopLessons
                request_text = input("طلبك؛ مثال: اكتب في المفكرة: اختبار بودا، أو ابحث عن موضوع، أو افتح الفيديو ولخصه ثم رابط: ").strip()
                workflow = request_plan(request_text)
                workflow_choice = "36"
                if Path("memory/desktop_lessons.sqlite3").is_file():
                    for lesson in DesktopLessons().recall(request_text):
                        print("تصحيح معتمد للاستفادة منه فقط؛ ليس أمر تنفيذ:", lesson["correction"])
                for number, planned in enumerate(workflow.steps, 1):
                    print(number, planned["operation"], planned["expected"])
                print("لم تُنفذ أي خطوة. اختر 36 لمراجعة أول طلب والموافقة عليه.")
                continue
            operations = {"1": "observe", "2": "move", "3": "click", "4": "drag", "5": "scroll", "6": "type", "7": "key", "8": "open_url", "9": "search", "10": "transcribe", "11": "watch", "12": "launch_app", "13": "play_media"}
            operations.update({"18": "restore_window", "19": "read_elements", "20": "verify_text"})
            operations.update({"21": "read_webpage", "22": "read_captions"})
            operations.update({"25": "ocr_screen", "26": "browser_open", "27": "browser_read",
                               "28": "browser_click", "29": "browser_fill"})
            operations.update({"30": "read_document", "31": "download_media", "32": "inspect_media"})
            operations.update({"33": "discover_video", "34": "youtube_captions"})
            operations.update({"37": "save_correction", "38": "recall_corrections"})
            if choice in {"14", "16"}:
                operations[choice] = "assist"
            if choice in {"17", "36"}:
                from core.desktop_workflow import notepad_check
                if choice == "36" and (workflow is None or workflow_choice != "36"):
                    print("اختر 35 واعرض مهمة بالكلام أولًا.")
                    continue
                if choice == "17" and (workflow is None or workflow_choice != "17"):
                    workflow = notepad_check()
                    workflow_choice = "17"
                step = workflow.next_step()
                operation, parameters = step["operation"], step["parameters"]
                print("النتيجة المطلوب التحقق منها بعد الخطوة:", step["expected"])
            elif choice == "15":
                import time
                if (not last_proposal or time.monotonic() - last_proposal["proposed_at"] > 30
                        or time.monotonic() - last_proposal.get("observed_at", last_proposal["proposed_at"]) > 120):
                    print("لا يوجد اقتراح حديث؛ اسأل بودا مجددًا عن الشاشة الحالية.")
                    continue
                operation = last_proposal["action"]["operation"]
                parameters = dict(last_proposal["action"]["parameters"])
                last_proposal = None
            elif choice not in operations:
                continue
            else:
                operation, parameters = operations[choice], {}
            if operation == "assist":
                parameters["question"] = input("سؤالك أو المطلوب من بودا: ").strip()
                parameters["propose"] = choice == "16"
            if operation in {"move", "click", "drag", "scroll"}:
                parameters = {"x": int(input("X: ")), "y": int(input("Y: "))}
            if operation == "click":
                parameters["button"] = input("left/right/middle [left]: ").strip() or "left"
            if operation == "drag":
                parameters.update(x2=int(input("X النهائي: ")), y2=int(input("Y النهائي: ")))
            if operation == "scroll":
                parameters["amount"] = int(input("عدد الخطوات؛ الموجب لأعلى والسالب لأسفل: "))
            if operation == "watch":
                print("ستُشاهد الشاشة الرئيسية بالكامل، ويحلل نموذج محلي صورًا متتابعة. لا تنفيذ لأي حركة بهذه الموافقة ولا حفظ تسجيل.")
                parameters = {"duration": int(input("مدة المشاهدة بالثواني [300]: ") or "300"),
                              "interval": int(input("الفاصل بين التحليلات بالثواني [10]: ") or "10"),
                              "endpoint": "http://127.0.0.1:8081/v1",
                              "model": "screen-vision"}
            for op, field, prompt in [("type", "text", "النص: "), ("key", "key", "المفتاح مثل enter أو ctrl+l: "),
                                      ("open_url", "url", "رابط https عام: "), ("search", "query", "عبارة البحث التي ستُرسل إلى Google: "),
                                      ("transcribe", "path", "مسار الملف النسبي داخل مجلد الوسائط: "),
                                      ("play_media", "path", "مسار الفيديو النسبي داخل مجلد الوسائط: "),
                                      ("launch_app", "application", "calculator أو notepad: ")]:
                if operation == op and field not in parameters:
                    parameters[field] = input(prompt).strip()
            if operation == "verify_text":
                if "expected" not in parameters:
                    parameters["expected"] = input("النص الذي تريد التأكد من ظهوره: ").strip()
            if operation in {"save_correction", "recall_corrections"}:
                parameters["request"] = input("الطلب الذي يتعلق به التصحيح: ").strip()
                if operation == "save_correction":
                    parameters["correction"] = input("التصحيح الذي تريد حفظه للمراجعة، وليس أمر تنفيذ: ").strip()
            if operation in {"read_document", "inspect_media"}:
                parameters["path"] = input("مسار الملف النسبي داخل المجلد المسموح: ").strip()
            if operation == "download_media":
                parameters["url"] = input("رابط HTTPS مباشر للملف؛ حتى 100 ميجابايت، سيُحفظ داخل booda-downloads: ").strip()
            if operation in {"discover_video", "youtube_captions"}:
                if "url" not in parameters:
                    parameters["url"] = input("رابط صفحة الفيديو العامة: ").strip()
                if operation == "youtube_captions" and "language" not in parameters:
                    parameters["language"] = input("لغة الترجمة ar أو en [ar]: ").strip() or "ar"
            if operation in {"read_webpage", "read_captions", "browser_open"}:
                if "url" not in parameters:
                    parameters["url"] = input("رابط HTTPS عام؛ لن تُستخدم حسابات المتصفح أو ملفات الدخول: ").strip()
            if operation in {"browser_click", "browser_fill"}:
                parameters["snapshot"] = input("رمز snapshot من آخر قراءة للصفحة: ").strip()
                parameters["role"] = "textbox" if operation == "browser_fill" else input("نوع العنصر button أو link: ").strip()
                parameters["name"] = input("اسم العنصر بالضبط كما ظهر في القراءة: ").strip()
                if operation == "browser_fill":
                    parameters["text"] = input("النص المطلوب: ")
            if operation in {"move", "click", "drag", "scroll", "type", "key", "restore_window", "read_elements", "verify_text"}:
                windows = controller.backend.windows()
                for index, window in enumerate(windows):
                    print(index, window["title"])
                index = int(input("رقم النافذة المقصودة: "))
                if not 0 <= index < len(windows):
                    raise ValueError("رقم نافذة غير موجود.")
                controller.backend.selected_window = windows[index]
                if operation == "restore_window":
                    parameters = dict(windows[index])
            task = controller.prepare(operation, parameters)
            if workflow is not None:
                workflow.bind(task)
            print("العملية:", {"type": "كتابة نص", "launch_app": "فتح تطبيق", "assist": "قراءة الشاشة", "watch": "مشاهدة الشاشة"}.get(operation, operation))
            print("التفاصيل:", json.dumps(parameters, ensure_ascii=False))
            if task.metadata.get("target"):
                print("النافذة:", task.metadata["target"]["title"])
                print("بعد الموافقة، ارجع للنافذة المختارة خلال 3 ثوانٍ واترك مكان الكتابة محددًا.")
            if dialog_approval:
                from core.desktop_review import confirm_request
                confirmed = confirm_request(task)
            else:
                confirmed = input("للموافقة اكتب موافق أو موافقة؛ اكتب لا للإلغاء: ").strip() in {"موافق", "موافقة", "موافقه"}
            if not confirmed:
                controller.pending.pop(task.task_id, None)
                if workflow is not None:
                    workflow.stop()
                    workflow = None
                continue
            approval = _approval(DESKTOP_PERMISSION, task.task_id, approval_manager)
            import time
            time.sleep(3)
            controller.execute(task, permission_manager=permission_manager, approval=approval, audit_log=audit_log)
            print(task.status, json.dumps(task.result, ensure_ascii=False, default=str))
            if workflow is not None:
                workflow.record(task)
                if workflow.state == "awaiting_verification":
                    print("راجع الشاشة بنفسك:", step["expected"])
                    workflow.verify(input("هل ظهرت النتيجة المطلوبة؟ اكتب نعم فقط لتأكيدها: ").strip() == "نعم")
                if workflow.state == "ready":
                    print("تم تأكيد الخطوة. اختر", workflow_choice, "لمراجعة الخطوة التالية بموافقة جديدة.")
                else:
                    print("حالة المهمة:", workflow.state, "التحقق بشري؛ لا يُحسب تحققًا بصريًا آليًا.")
                    workflow = None
            if task.status == "completed" and operation == "assist" and task.result.get("action"):
                last_proposal = task.result
            if task.status == "completed" and operation == "watch":
                reply = task.result.get("assistant_reply")
                if reply and reply.get("action"):
                    last_proposal = reply
        except KeyboardInterrupt:
            controller.stop()
            print("تم قطع الاتصال وإلغاء الطلبات المعلقة.")
            return
        except (ValueError, OSError, KeyError, RuntimeError, ImportError) as error:
            if workflow is not None:
                workflow.stop()
                workflow = None
            print("لم يكتمل الطلب:", error)
