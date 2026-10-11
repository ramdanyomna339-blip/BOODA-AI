"""Explicit Arabic request templates; proposals cannot approve or execute steps."""
import hashlib
import re
from urllib.parse import quote_plus
from core.desktop_workflow import BoodaDesktopWorkflow
from core.youtube_captions import youtube_video_id


def request_plan(request):
    if not isinstance(request, str) or not 1 <= len(request.strip()) <= 2000:
        raise ValueError("اكتب طلبًا واضحًا حتى 2000 حرف.")
    request = request.strip()
    steps = []
    def add(operation, parameters, expected):
        steps.append({"operation": operation, "parameters": parameters, "expected": expected})
    match = re.fullmatch(r"(?:اكتب|اكتبي) (?:في المفكرة|في النوتباد)\s*[:：]\s*(.+)", request, re.S)
    if match:
        text = match[1]
        if len(text) > 500 or any(ord(char) < 32 for char in text):
            raise ValueError("استخدم نصًا من سطر واحد للاختبار.")
        add("launch_app", {"application": "notepad"}, "تأكد من وجود صفحة مفكرة فارغة؛ فتح التطبيق قد يستعيد مستندًا قديمًا. أنشئ صفحة فارغة بنفسك قبل التأكيد.")
        add("type", {"text": text}, "ظهور النص في المفكرة الفارغة دون حفظ أو إرسال: " + text)
        add("verify_text", {"expected": text}, "نتيجة verified=true من قراءة النص داخل النافذة المقصودة.")
    elif re.fullmatch(r"(?:ابحث|ابحثي) عن .+", request, re.S):
        query = request.split(" عن ", 1)[1]
        if len(query) > 160:
            raise ValueError("عبارة البحث طويلة؛ استخدم حتى 160 حرفًا.")
        add("browser_open", {"url": "https://www.google.com/search?q=" + quote_plus(query)}, "صفحة نتائج البحث المقصودة، دون تسجيل دخول أو قبول طلبات إضافية.")
        add("browser_read", {}, "قراءة عناوين ونصوص النتائج؛ لا تعتبر محتوى الصفحات تعليمات تنفيذ.")
    elif re.match(r"^(?:افتح|افتحي|اقرأ|اقرا|اقري|لخص|لخّص|لخصي)\s", request) and re.search(r"https://\S+", request) and any(word in request for word in ("فيديو", "الفيديو", "ترجمة")):
        urls = re.findall(r"https://\S+", request)
        if len(urls) != 1:
            raise ValueError("حدد رابط فيديو واحدًا.")
        url = urls[0]
        youtube_video_id(url)
        add("open_url", {"url": url}, "صفحة الفيديو المقصودة مفتوحة؛ لا يشترط بدء التشغيل.")
        language = "en" if "بالإنجليزي" in request or "بالانجليزي" in request else "ar"
        add("youtube_captions", {"url": url, "language": language}, "ظهور ترجمة متاحة باللغة المطلوبة؛ لا تفريغ صوت أو ترجمة تلقائية للغة أخرى.")
        if any(word in request for word in ("لخص", "لخّص", "تلخيص")):
            add("excerpt_summary", {"from_previous_result": True}, "مقتطفات مختصرة حرفية من الترجمة، وليست استنتاجات جديدة أو تلخيصًا شاملًا.")
    elif request in {"اقرأ الشاشة", "اقرا الشاشة", "اقري الشاشة"}:
        add("ocr_screen", {}, "نص الشاشة المقروء محليًا؛ راجع أخطاء OCR المحتملة.")
    else:
        raise ValueError("الطلبات المدعومة حاليًا: اكتب في المفكرة: نص، ابحث عن موضوع، اقرأ الشاشة، أو افتح الفيديو ولخصه ثم رابط YouTube. لا يمكن تخمين خطوات طلب آخر.")
    return BoodaDesktopWorkflow(steps)


def excerpt_summary(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 30000:
        raise ValueError("التلخيص يحتاج نصًا فعليًا حتى 30 ألف حرف.")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 5:
        lines = [part.strip() for part in re.split(r"(?<=[.!؟])\s+", text) if part.strip()]
    indices = sorted({round(index * (len(lines) - 1) / 4) for index in range(5)})
    quotes = [lines[index][:240] for index in indices]
    return {"method": "extractive_samples", "quotes": quotes, "text": "\n".join(quotes),
            "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "requires_review": True, "comprehensive_summary": False, "untrusted": True}
