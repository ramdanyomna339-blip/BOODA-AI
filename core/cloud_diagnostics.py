"""Actionable provider diagnostics without claiming every failure is a bad key."""
import re


def diagnose_cloud_error(error):
    text = str(error).casefold()
    match = re.search(r'http\s+(\d{3})', text)
    code = int(match[1]) if match else None
    if 'api_key_invalid' in text or 'api key not valid' in text or code == 401:
        kind, advice = 'authentication', 'المفتاح مرفوض؛ تحقق من المشروع والقيود، ولا تحفظه في الكود.'
    elif code == 429 or 'resource_exhausted' in text:
        kind, advice = 'quota', 'راجع حدود المشروع والنموذج داخل AI Studio. لا تفترض أن الانتظار دقيقة يكفي؛ قد تكون الحصة يومية أو صفرًا.'
    elif code == 404 or ('model' in text and 'not found' in text):
        kind, advice = 'model_unavailable', 'راجع اسم النموذج وإتاحته للمشروع؛ تغيير المفتاح وحده لا يعالج نموذجًا غير متاح.'
    elif code == 403:
        kind, advice = 'permission', 'راجع صلاحيات المشروع وقيود المفتاح وتفعيل الخدمة؛ هذا الخطأ وحده لا يثبت حجب البلد.'
    elif code == 400:
        kind, advice = 'request_or_eligibility', 'راجع صيغة الطلب وأهلية المشروع والنموذج. لا يمكن تحديد السبب من رقم 400 وحده.'
    elif code and code >= 500:
        kind, advice = 'provider_failure', 'عطل لدى الخدمة؛ لم نعد الطلب تلقائيًا ولم نغير المزود.'
    elif 'reach' in text or 'timeout' in text or 'timed out' in text:
        kind, advice = 'network', 'تعذر الاتصال أو انتهت المهلة؛ راجع الإنترنت والوكيل الشبكي. لا يوجد دليل أن المفتاح غير صالح.'
    else:
        kind, advice = 'unknown', 'السبب غير محسوم؛ لم نعتبر الاختبار ناجحًا ولم نفعل بديلًا مدفوعًا.'
    return {'category': kind, 'http_status': code, 'advice': advice}
