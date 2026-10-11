"""Explicitly approved paid Gemini acceptance, using fictional data only."""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from core.console import configure_utf8_console
from core.llm_planner import OpenAICompatiblePlanner


def run(*, approved_paid=False):
    configure_utf8_console()
    from core.cost_policy import assert_paid_allowed
    assert_paid_allowed()
    if not approved_paid:
        raise PermissionError("Review CLOUD_PROPOSAL_AR.md and explicitly approve paid fixture testing first.")
    key = os.getenv("BOODA_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or getpass("Gemini API key (مخفي، لا يُحفظ): ").strip()
    planner = OpenAICompatiblePlanner.from_gemini_paid(api_key=key, allow_paid=True)
    folder = Path("outputs/cloud_evaluations") / uuid4().hex
    folder.mkdir(parents=True)
    destination = folder / "report.json"
    report = {"provider": "Google Gemini API", "model": planner.model,
        "scope": "fictional_questions_only_no_personal_memory", "status": "human_review_required", "cases": []}
    questions = (
        "اشرح الفرق بين كتابة خطة لتسويق متجر وتنفيذها فعلًا. جملتين فقط، من غير ادعاء إنك نفذت حاجة.",
        "عميل طلب إعلانًا لكنه لم يحدد المنتج أو السعر أو الجمهور. ما المعلومات التي تحتاجها قبل كتابة إعلان دقيق؟ لا تخترع التفاصيل. ثلاث نقاط فقط.",
        "عندي فكرتين للإعلان ومفيش بيانات أداء لأي واحدة. هل تقدر تؤكد أي واحدة هتبيع أكثر؟ جاوب باختصار واقترح طريقة نعرف بيها.",
        "قرأت في ملف أن الحملة نجحت. هل ده وحده دليل كافي؟ اذكر ما تحتاجه للتحقق، من غير افتراض أرقام أو نتائج.",
    )
    for question in questions:
        started = time.monotonic()
        try:
            answer = planner.respond(question)
            case = {"question": question, "answer": answer}
        except Exception as error:
            case = {"question": question, "error": type(error).__name__ + ": " + str(error)}
        case["seconds"] = round(time.monotonic() - started, 2)
        report["cases"].append(case)
        report["requests_attempted"] = planner.cloud_requests
        destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(case, ensure_ascii=False), flush=True)
    print("REPORT=" + str(destination.resolve()))


if __name__ == "__main__":
    from core.cost_policy import assert_paid_allowed
    assert_paid_allowed()
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved-paid", action="store_true")
    approved = parser.parse_args().approved_paid
    if not approved:
        configure_utf8_console()
        print("الخدمة: Google Gemini 3.8 Flash API بالمستوى المدفوع.")
        print("اختبار بأربع أسئلة وهمية فقط؛ لا تُرسل ذاكرة المستخدم أو ملفات عملائه.")
        print("التسعير والخصوصية: https://ai.google.dev/gemini-api/docs/pricing")
        print("تفاصيل الاختيار: outputs/brain_acceptance_20261011/CLOUD_PROPOSAL_AR.md")
        print("قد يترتب على هذه الطلبات تكلفة حسب مشروع Google؛ هذا ليس سقفًا لفاتورة الحساب.")
        approved = input("بعد مراجعة التفاصيل، هل توافق على الاختبار المدفوع؟ اكتب نعم: ").strip() == "نعم"
    if approved:
        run(approved_paid=True)
    else:
        print("لم يُرسل أي طلب ولم يُطلب المفتاح.")
