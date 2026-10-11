"""One explicit, non-personal Gemini free-project probe; never stores the key."""
from getpass import getpass
import json
from pathlib import Path
from uuid import uuid4

from core.cloud_diagnostics import diagnose_cloud_error
from core.console import configure_utf8_console
from core.llm_planner import OpenAICompatiblePlanner


def check(*, api_key, confirmed_unbilled=False, transport=None, root=None):
    if confirmed_unbilled is not True:
        raise PermissionError('تأكد أولًا أن مشروع Google مجاني وغير مربوط بالفوترة.')
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError('لم يدخل مفتاح؛ لم يرسل طلب.')
    report = {'provider': 'Google Gemini API', 'model': OpenAICompatiblePlanner.GEMINI_FREE_MODEL,
              'billing_status': 'user_declared_unbilled_not_independently_verified',
              'private_memory_sent': False, 'automatic_retry': False, 'requests_attempted': 0}
    planner = None
    try:
        planner = OpenAICompatiblePlanner.from_gemini_free_tier(api_key=api_key.strip(), transport=transport)
        planner.timeout = 30
        report['model'] = planner.model
        answer = planner.respond('اختبار اتصال فقط. أجب بالكلمة التالية فقط: جاهز')
        report['status'] = 'passed' if answer.strip().strip('.!') == 'جاهز' else 'unexpected_answer'
    except Exception as error:
        report['status'] = 'failed'
        report['diagnosis'] = diagnose_cloud_error(error)
    finally:
        if planner is not None:
            report['requests_attempted'] = planner.cloud_requests
            planner.api_key = None
    folder = Path(root or Path(__file__).resolve().parents[1]) / 'outputs/free_cloud_checks' / uuid4().hex
    folder.mkdir(parents=True)
    destination = folder / 'report.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report, destination


def main():
    configure_utf8_console()
    print('اختبار Gemini المجاني: سؤال وهمي واحد، بدون ملفات أو ذاكرة أو إعادة محاولة.')
    print('لن يُحفظ المفتاح. تأكد من AI Studio أن المشروع غير مربوط بالفوترة وأن له حصة مجانية.')
    if input('هل تحققت وتوافق على إرسال سؤال الاختبار؟ اكتب نعم: ').strip() != 'نعم':
        print('لم يرسل طلب ولم يطلب مفتاح.')
        return
    key = getpass('المفتاح (مخفي، لهذه التجربة فقط): ').strip()
    if not key:
        print('لم يدخل مفتاح؛ لم يرسل طلب.')
        return
    report, destination = check(api_key=key, confirmed_unbilled=True)
    key = None
    print('نتيجة الاختبار: ' + report['status'])
    if report.get('diagnosis'):
        print(report['diagnosis']['advice'])
    print('التقرير: ' + str(destination))


if __name__ == '__main__':
    main()
