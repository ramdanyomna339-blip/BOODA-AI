"""Interactive research workspace, also available independently of main menu."""

from core.knowledge_base import BoodaLocalKnowledgeBase
from core.research import BoodaResearchManager
import json


def manage_research(manager, *, evolution_manager=None, task_manager=None):
    while True:
        print("\nالبحث والتعلم: 1 بحث جديد | 2 عرض تقرير | 3 اقتراح معرفة | 4 مراجعة معرفة | 5 تسجيل تجربة | 6 استرجاع معرفة معتمدة")
        print("7 إضافة رابط | 8 استخراج مقترحات | 9 مقارنة الأدلة | 10 إضافة دليل | 11 تصحيح معلومة | 12 قياس رقمي | 13 ملخص التعلم | 14 اقتراح تطوير | 15 حذف بحث | 16 إزالة دليل | 0 رجوع")
        print("17 تحديد احتياجات البحث من سؤال أو مهمة")
        print("18 تحليل المعنى والتعارض بالنموذج المحلي")
        choice = input("الاختيار: ").strip()
        try:
            if choice == "0":
                return
            if choice == "1":
                topic = input("موضوع البحث: ")
                print("البحث المحلي لا يرسل بيانات. بحث الإنترنت يرسل الموضوع لمحرك البحث ثم يقرأ المصادر العامة.")
                online = input("للبحث عبر الإنترنت اكتب نعم، وإلا بحث محلي: ").strip() == "نعم"
                language, engine = "ar", "wikipedia"
                if online:
                    language = input("لغة الإنترنت ar أو en [ar]: ").strip() or "ar"
                    engine = "web" if input("للبحث العام اكتب web؛ وإلا ويكيبيديا: ").strip() == "web" else "wikipedia"
                session = manager.research(topic, online=online, language=language, engine=engine)
                candidates = manager.extract_candidates(session["id"])
                print(f"معرّف البحث: {session['id']} | الحالة: {session['status']}")
                print(manager.export_report(session["id"]))
                print("مقترحات مستخرجة للمراجعة:", len(candidates))
                for error in session["errors"]:
                    print(error)
            elif choice == "2":
                for session in manager.list_sessions():
                    print(session["id"], session["topic"], session["status"])
                session_id = input("معرّف البحث لعرضه (فارغ للرجوع): ").strip()
                if session_id:
                    print(manager.export_report(session_id).read_text(encoding="utf-8"))
            elif choice == "3":
                session_id = input("معرّف البحث: ").strip()
                statement = input("المعلومة المستخلصة: ")
                sources = input("معرّفات المصادر مفصولة بفواصل مثل S1,S2: ").split(",")
                finding = manager.propose(session_id, statement, [s.strip() for s in sources],
                                          usefulness=input("هتفيد أي مهمة وإزاي؟ "))
                print("اقتراح قيد المراجعة:", finding["id"])
            elif choice == "4":
                session_id = input("معرّف البحث: ").strip()
                session = manager.get(session_id)
                for finding in session["findings"]:
                    print(finding["id"], finding["status"], finding["statement"], finding["source_ids"])
                finding_id = input("معرّف المعلومة: ").strip()
                decision = input("اكتب اعتماد أو رفض، وأي شيء آخر للإلغاء: ").strip()
                if decision in {"اعتماد", "رفض"}:
                    manager.review(session_id, finding_id, approve=decision == "اعتماد")
                    print("تم حفظ قرار المراجعة.")
            elif choice == "5":
                session_id = input("معرّف البحث: ").strip()
                finding_id = input("معرّف المعلومة: ").strip()
                task_id = input("معرّف المهمة: ").strip()
                observation = input("النتيجة المشاهدة ودليلها: ")
                outcome = input("تحسنت؟ نعم / لا / غير معروف: ").strip()
                manager.record_application(session_id, finding_id, task_id=task_id,
                                           observation=observation,
                                           improved={"نعم": True, "لا": False}.get(outcome))
                print("تم تسجيل تجربة الاستخدام كتقرير منك.")
            elif choice == "6":
                for finding in manager.approved_knowledge(input("كلمات البحث: ")):
                    print(finding["statement"], finding["source_ids"], finding["research_id"])
            elif choice == "7":
                session_id = input("معرّف البحث: ").strip()
                print("سيتم الاتصال بالرابط العام الذي تدخله.")
                source = manager.add_source(session_id, input("رابط HTTPS للمصدر: ").strip())
                print(source["source_id"], source["title"])
            elif choice == "8":
                findings = manager.extract_candidates(input("معرّف البحث: ").strip())
                for finding in findings:
                    print(finding["id"], finding["statement"], "قيد المراجعة")
                print("عدد المقترحات المستخرجة:", len(findings))
            elif choice == "9":
                print(json.dumps(manager.compare(input("معرّف البحث: ").strip()), ensure_ascii=False, indent=2))
            elif choice == "10":
                session_id = input("معرّف البحث: ").strip()
                finding_id = input("معرّف المعلومة: ").strip()
                source_id = input("معرّف المصدر: ").strip()
                quote = input("اقتباس موجود حرفيًا في المصدر: ")
                relation = input("العلاقة supports / contradicts / unclear: ").strip()
                manager.add_evidence(session_id, finding_id, source_id, quote, relation=relation)
                print("تم حفظ الدليل وإعادة المعلومة للمراجعة.")
            elif choice == "11":
                session_id = input("معرّف البحث: ").strip()
                finding_id = input("معرّف المعلومة: ").strip()
                manager.correct_finding(session_id, finding_id, statement=input("المعلومة المصححة: "),
                                        usefulness=input("التطبيق المقصود: "))
                print("تم التصحيح؛ يلزم اعتماد جديد.")
            elif choice == "12":
                session_id = input("معرّف البحث: ").strip()
                finding_id = input("معرّف المعلومة: ").strip()
                task_id = input("معرّف المهمة: ").strip()
                observation = input("وصف التجربة والدليل: ")
                metric = input("اسم المقياس ووحدته: ")
                baseline = float(input("القيمة قبل: "))
                result = float(input("القيمة بعد: "))
                direction = input("الأفضل أعلى أم أقل؟ اكتب أعلى أو أقل: ").strip()
                if direction not in {"أعلى", "أقل"}:
                    raise ValueError("حدد اتجاه التحسن.")
                application = manager.record_application(session_id, finding_id, task_id=task_id,
                    observation=observation, metric=metric, baseline=baseline, result=result,
                    higher_is_better=direction == "أعلى")
                print(json.dumps(application, ensure_ascii=False, indent=2))
            elif choice == "13":
                print(json.dumps(manager.learning_summary(input("معرّف البحث: ").strip()), ensure_ascii=False, indent=2))
            elif choice == "14":
                if evolution_manager is None:
                    print("اقتراح التطوير متاح من القائمة الرئيسية رقم 32.")
                    continue
                session_id = input("معرّف البحث: ").strip()
                finding_id = input("معرّف المعلومة: ").strip()
                proposal = manager.propose_improvement(session_id, finding_id, evolution_manager=evolution_manager)
                print("اقتراح تطوير للمراجعة:", proposal["proposal_id"], proposal["status"])
            elif choice == "15":
                session_id = input("معرّف البحث المراد حذفه: ").strip()
                if input("اكتب حذف لتأكيد حذف البحث وتقريره: ").strip() == "حذف":
                    manager.delete_session(session_id)
                    print("تم حذف البحث والتقرير. مقترحات التطوير السابقة لها دورة مراجعتها المنفصلة.")
            elif choice == "16":
                session_id = input("معرّف البحث: ").strip()
                finding_id = input("معرّف المعلومة: ").strip()
                finding = next(f for f in manager.get(session_id)["findings"] if f["id"] == finding_id)
                for index, evidence in enumerate(finding.get("evidence", [])):
                    print(index, evidence)
                manager.remove_evidence(session_id, finding_id, int(input("رقم الدليل المراد إزالته: ")))
                print("تمت إزالة الدليل؛ يلزم اعتماد جديد.")
            elif choice == "17":
                needs = manager.research_needs(input("السؤال أو موضوع المهمة: "), task_manager=task_manager)
                print(json.dumps(needs, ensure_ascii=False, indent=2))
            elif choice == "18":
                from core.local_model import ensure_local_model_server
                from core.semantic_research import BoodaSemanticAnalyzer
                session_id = input("معرّف البحث: ").strip()
                print("تحليل محلي حتى 5 معلومات؛ الحكم اقتراح دلالي يحتاج مراجعة.")
                with ensure_local_model_server() as endpoint:
                    analyses = manager.semantic_compare(session_id, BoodaSemanticAnalyzer(base_url=endpoint))
                print(json.dumps(analyses, ensure_ascii=False, indent=2))
            else:
                print("اختيار غير صحيح.")
        except (ValueError, KeyError, StopIteration, OSError, RuntimeError) as error:
            print(f"تعذر إتمام العملية ({type(error).__name__}). راجع المدخلات والملفات.")


if __name__ == "__main__":
    from core.console import configure_utf8_console
    configure_utf8_console()
    manage_research(BoodaResearchManager(knowledge_base=BoodaLocalKnowledgeBase()))
