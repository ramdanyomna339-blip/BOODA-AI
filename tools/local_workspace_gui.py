"""A small local desktop workspace; no language model or cloud connection."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk, simpledialog

from core.knowledge_base import BoodaLocalKnowledgeBase
from core.local_workspace import HELP, local_reply, review_teacher_import


class LocalWorkspaceWindow:
    def __init__(self, window, *, root=None):
        self.root = Path(root or Path(__file__).resolve().parents[1])
        self.window = window
        window.title('بوده — مساحة العمل المحلية')
        window.geometry('900x620')
        window.minsize(650, 450)
        self.client = tk.StringVar()
        self.project = tk.StringVar()
        self.question = tk.StringVar()
        frame = ttk.Frame(window, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='بوده المحلي — بحث وحساب ومراجع ودروس، بدون مفتاح', anchor='e').pack(fill='x')
        scope = ttk.Frame(frame)
        scope.pack(fill='x', pady=10)
        for label, variable in [('معرّف العميل', self.client), ('معرّف المشروع', self.project)]:
            ttk.Label(scope, text=label).pack(side='right', padx=6)
            ttk.Entry(scope, textvariable=variable, justify='right', width=22).pack(side='right')
        ttk.Label(frame, text='اترك النطاق فارغًا للمراجع العامة. العرض الحالي يُمسح عند تغيير العميل أو المشروع.', anchor='e').pack(fill='x')
        self.output = tk.Text(frame, wrap='word', state='disabled', font=('Segoe UI', 12), padx=12, pady=12)
        self.output.pack(fill='both', expand=True, pady=10)
        self.output.tag_configure('right', justify='right')
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill='x')
        for label, command in [('مراجعي', '/مراجعي'), ('مخرجاتي', '/مخرجات'), ('حالة الأدوات', '/جاهزية'), ('المساعدة', '/مساعدة')]:
            ttk.Button(toolbar, text=label, command=lambda value=command: self.submit(value)).pack(side='right', padx=4)
        ttk.Button(toolbar, text='استيراد دروس مُراجعة', command=self.import_lessons).pack(side='right', padx=4)
        entry = ttk.Entry(frame, textvariable=self.question, justify='right', font=('Segoe UI', 12))
        entry.pack(fill='x', pady=10)
        entry.bind('<Return>', lambda _: self.submit())
        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        ttk.Button(actions, text='تنفيذ الأمر المحلي', command=self.submit).pack(side='right', padx=4)
        ttk.Button(actions, text='بحث في المراجع', command=lambda: self.submit('/بحث ' + self.question.get().strip())).pack(side='right', padx=4)
        ttk.Button(actions, text='تصميم بقالب ثابت', command=self.poster).pack(side='right', padx=4)
        ttk.Button(actions, text='فيديو صور صامت', command=self.slideshow).pack(side='right', padx=4)
        self.client.trace_add('write', self.clear_scope)
        self.project.trace_add('write', self.clear_scope)
        self.append(HELP)
        entry.focus_set()

    def scope(self):
        return {key: value.strip() for key, value in (
            ('client_id', self.client.get()), ('project_id', self.project.get())) if value.strip()}

    def append(self, text):
        self.output.configure(state='normal')
        self.output.insert('end', text + '\n\n', 'right')
        self.output.configure(state='disabled')
        self.output.see('end')

    def clear_scope(self, *_):
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.configure(state='disabled')
        self.append('تغير نطاق العرض. النتائج القادمة من النطاق الحالي فقط.')

    def submit(self, message=None):
        message = message if message is not None else self.question.get().strip()
        if not message:
            return
        try:
            kb = BoodaLocalKnowledgeBase(self.root / 'knowledge/local_documents.json')
            answer = local_reply(message, knowledge_base=kb, scope=self.scope(), root=self.root)
            self.append('أنت: ' + message + '\nبوده: ' + (answer if answer is not None else
                'هذه المساحة لا تشغل نموذجًا؛ الطلب خارج أوامرها المحلية. لم أنفذ إجراءً ولم أتصل بخدمة.'))
            self.question.set('')
        except (ValueError, OSError, RuntimeError) as error:
            self.append('لم تكتمل العملية: ' + str(error))

    def import_lessons(self):
        source = filedialog.askopenfilename(parent=self.window, title='اختر حزمة دروس راجعتها', filetypes=[('JSON', '*.json')])
        if not source:
            return
        try:
            result = review_teacher_import(source, scope=self.scope(), root=self.root,
                confirm=lambda prompt: 'نعم' if messagebox.askyesno('اعتماد الدروس',
                    prompt + '\nلن تُدرّب أوزان النموذج أو تُرسل بيانات للخارج.', parent=self.window) else 'لا')
            self.append(result)
        except (ValueError, OSError, RuntimeError) as error:
            self.append('لم تُستورد الدروس: ' + str(error))

    def poster(self):
        title = simpledialog.askstring('تصميم محلي', 'العنوان (حتى 100 حرف):', parent=self.window)
        if not title:
            return
        subtitle = simpledialog.askstring('تصميم محلي', 'النص الفرعي (حتى 200 حرف):', parent=self.window)
        if subtitle is None:
            return
        from core.local_media_tools import create_poster
        try:
            result = create_poster(title=title, subtitle=subtitle, root=self.root, workspace_scope=self.scope())
            self.append('اتحفظ تصميم SVG بقالب ثابت؛ راجع توزيع النص قبل النشر:\n' + result['path'])
        except (ValueError, OSError) as error:
            self.append('لم يكتمل التصميم: ' + str(error))

    def slideshow(self):
        paths = filedialog.askopenfilenames(parent=self.window, title='اختر صورًا لفيديو رأسي صامت',
            filetypes=[('Images', '*.png *.jpg *.jpeg *.webp')])
        if not paths:
            return
        duration = simpledialog.askfloat('مدة الصورة', 'كم ثانية لكل صورة؟ من 0.5 إلى 5:',
            initialvalue=2, minvalue=.5, maxvalue=5, parent=self.window)
        if duration is None:
            return
        from core.local_media_tools import create_slideshow
        try:
            self.append('جاري تجهيز فيديو صور صامت؛ لن يُنشر أو يُرسل لخدمة خارجية.')
            self.window.update_idletasks()
            result = create_slideshow(list(paths), root=self.root, seconds_per_image=duration, workspace_scope=self.scope())
            self.append('اتحفظ الفيديو واتراجع عدد إطاراته؛ راجعه قبل النشر:\n' + result['path'])
        except (ValueError, OSError, RuntimeError) as error:
            self.append('لم يكتمل الفيديو: ' + str(error))


def main():
    try:
        window = tk.Tk()
    except tk.TclError as error:
        raise RuntimeError('مكتبة نافذة النظام غير جاهزة؛ استخدم الخيار 40 مؤقتًا.') from error
    LocalWorkspaceWindow(window)
    window.mainloop()


if __name__ == '__main__':
    main()
