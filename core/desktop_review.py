"""Arabic per-request approval dialog. It grants no permissions itself."""
import json


def request_preview(task):
    data = task.metadata
    labels = {"type": "كتابة نص", "key": "ضغط مفتاح", "launch_app": "فتح تطبيق",
              "restore_window": "إظهار نافذة", "read_elements": "قراءة عناصر نافذة",
              "verify_text": "التحقق من نص", "read_webpage": "قراءة صفحة عامة",
              "read_captions": "قراءة ترجمة فيديو", "assist": "سؤال عن الشاشة",
              "watch": "مشاهدة الشاشة", "observe": "التقاط صورة للشاشة",
              "click": "نقرة ماوس", "move": "تحريك الماوس", "drag": "سحب بالماوس",
              "scroll": "تمرير", "search": "بحث على الإنترنت", "open_url": "فتح رابط",
              "transcribe": "تفريغ ملف صوتي", "play_media": "فتح ملف وسائط"}
    labels.update({"ocr_screen": "قراءة النص العربي والإنجليزي من الشاشة",
                   "browser_open": "فتح صفحة في متصفح بودا", "browser_read": "قراءة صفحة متصفح بودا",
                   "browser_click": "نقر عنصر في المتصفح", "browser_fill": "كتابة في مربع بالمتصفح"})
    labels.update({"read_document": "قراءة ملف داخل المجلد المسموح",
                   "download_media": "تنزيل ملف صوت أو فيديو مباشر حتى 100 ميجابايت",
                   "inspect_media": "قراءة معلومات ملف صوت أو فيديو"})
    labels.update({"discover_video": "اكتشاف روابط الفيديو والترجمة في صفحة عامة",
                   "youtube_captions": "قراءة ترجمة YouTube المتاحة باللغة المحددة"})
    labels.update({"excerpt_summary": "اختصار النص بمقتطفات حرفية للمراجعة",
                   "save_correction": "حفظ تصحيح معتمد للاسترجاع فقط", "recall_corrections": "قراءة التصحيحات المعتمدة"})
    fields = {"text": "النص", "url": "الرابط", "query": "عبارة البحث", "expected": "النص المتوقع",
              "question": "السؤال", "application": "التطبيق", "key": "المفتاح", "path": "الملف",
              "duration": "المدة بالثواني", "interval": "الفاصل بالثواني"}
    lines = ["العملية: " + labels.get(data["operation"], data["operation"])]
    target = data.get("target")
    if target:
        lines.append("النافذة: " + target["title"])
    for name, value in data["parameters"].items():
        lines.append(fields.get(name, name) + ": " + (value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)))
    lines.append("هذه موافقة على الطلب المعروض فقط. أي خطوة تالية تحتاج موافقة جديدة.")
    return "\n\n".join(lines)


def confirm_request(task):
    import builtins
    from core.arabic_console import ArabicConsole
    # The browser already provides native Arabic shaping; keep the exact
    # reviewed request and explicit consent in that same UI.
    if isinstance(getattr(builtins.input, "__self__", None), ArabicConsole):
        print(request_preview(task))
        return input("للموافقة على الطلب المعروض فقط اكتب موافق، أو لا للإلغاء: ").strip() in {"موافق", "موافقة", "موافقه"}
    import tkinter as tk
    window = tk.Tk()
    window.title("بودا — راجع الخطوة قبل التنفيذ")
    window.geometry("720x500")
    approved = [False]
    tk.Label(window, text="هل توافق على هذه الخطوة؟", font=("Segoe UI", 16), anchor="e").pack(fill="x", padx=18, pady=12)
    text = tk.Text(window, wrap="word", font=("Segoe UI", 12), height=14)
    text.tag_configure("arabic", justify="right")
    text.insert("1.0", request_preview(task), "arabic")
    text.configure(state="disabled")
    text.pack(fill="both", expand=True, padx=18)
    def approve():
        approved[0] = True
        window.destroy()
    buttons = tk.Frame(window)
    buttons.pack(pady=15)
    tk.Button(buttons, text="موافق على هذه الخطوة فقط", command=approve, width=28).pack(side="right", padx=8)
    tk.Button(buttons, text="إلغاء", command=window.destroy, width=12).pack(side="right", padx=8)
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.after(110000, window.destroy)
    window.mainloop()
    return approved[0]
