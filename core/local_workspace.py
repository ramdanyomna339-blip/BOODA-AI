"""Explicit local commands usable from the menu or an existing agent dialogue."""
from pathlib import Path
from core.calculator import calculate_request
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.tool_readiness import inspect_tools

HELP = ('تقدر تستخدم: احسب 25% من 7000، أو /بحث ثم الكلمات، أو /مراجعي، أو /جاهزية. '
        'من المساحة المحلية بالخيار 40 تقدر تستخدم /تعليم ثم مسار حزمة الدروس. '
        'البحث يعرض نص المصدر وحالته ولا يؤكد صحته. هذه الأوامر محلية ولا تحتاج مفتاحًا أو نموذجًا.')


def local_reply(message, *, knowledge_base, scope=None, root=None):
    scope = scope or {}
    scope = {key: scope.get(key) for key in ('client_id', 'project_id')}
    if message in {'/مساعدة', '/help'}:
        return HELP
    calculation = calculate_request(message)
    if calculation is not None:
        return calculation
    if message == '/جاهزية':
        report = inspect_tools(root)
        return '\n'.join([report['message']] + [
            row['tool'] + ': ' + ('التبعية موجودة؛ الاستخدام الحي غير مثبت' if row['installed'] else 'تبعية ناقصة')
            for row in report['tools']])
    if message == '/مخرجات':
        from core.local_media_tools import list_media_outputs
        items = list_media_outputs(root or Path(__file__).resolve().parents[1], {key:value for key,value in scope.items() if value})
        return '\n'.join(item['path'] for item in items) if items else 'لا توجد مخرجات وسائط مسجلة في النطاق الحالي.'
    if message == '/مراجعي':
        if knowledge_base is None:
            return 'قاعدة المراجع غير متصلة بهذه الجلسة؛ لم أخمّن محتواها.'
        documents = [doc for doc in knowledge_base.list_documents() if all(
            doc.get(key) is None or doc.get(key) == value for key, value in scope.items())]
        return ('المراجع المتاحة في النطاق الحالي: ' + str(len(documents)) + '\n' + '\n'.join(
            str(doc['title']) + ' — ' + str(doc.get('reference_status', 'reference'))
            for doc in documents[:30]) + '\nوجود المرجع لا يثبت إتقانه أو صحة محتواه.')
    if message.startswith('/بحث '):
        if knowledge_base is None:
            return 'قاعدة المراجع غير متصلة بهذه الجلسة؛ لم أنفذ البحث.'
        sources = knowledge_base.search(message[5:].strip(), limit=3, **scope)
        if not sources:
            return 'لم أجد مقتطفًا مطابقًا في النطاق الحالي؛ هذا لا يثبت عدم وجود المعلومة.'
        return '\n\n'.join('المصدر: ' + source['title'] + ' | الحالة: ' + source['reference_status']
            + (' | صفحة: ' + str(source['page']) if source['page'] else '')
            + '\n' + source['text'] + '\n' + source.get('usage_note', '') for source in sources)
    return None


def review_teacher_import(source, *, scope, root, confirm=input):
    from tools.teach_examples import read_teacher_pack, teach_examples
    from hashlib import sha256
    raw, pack = read_teacher_pack(source)
    active = {key: value for key, value in scope.items() if key in {'client_id', 'project_id'} and value}
    if pack['scope'] != active:
        raise ValueError('نطاق حزمة الدروس مختلف عن نطاق المساحة الحالية؛ لم أستوردها أو أنقلها بين العملاء.')
    print('المصدر المعلن: ' + pack['teacher'] + '؛ عدد الدروس: ' + str(len(pack['examples'])))
    print('العناوين: ' + '، '.join(entry['topic'] for entry in pack['examples']))
    print('مراجع خاصة محلية فقط؛ المصدر غير موثق تلقائيًا، ولا تدريب أوزان أو اعتماد حقائق شخصية.')
    summary = pack['teacher'] + ' | ' + str(len(pack['examples'])) + ' درسًا\n' + '\n'.join(
        entry['topic'][:80] for entry in pack['examples'][:5])
    if confirm(summary + '\nهل راجعت الحزمة وتوافق على استيرادها في هذا النطاق؟ اكتب نعم: ').strip() != 'نعم':
        return 'لم تُستورد الدروس.'
    result = teach_examples(source, root=root, expected_digest=sha256(raw).hexdigest())
    return 'استوردت ' + str(len(result['documents'])) + ' درسًا مرجعيًا؛ إتقان النموذج لها غير مثبت.'


def run_workspace(*, root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    kb = BoodaLocalKnowledgeBase(root / 'knowledge/local_documents.json')
    print('مساحة بوده المحلية — بدون اتصال أو تنزيلات. Enter للرجوع.')
    scope = {key: value for key, value in (
        ('client_id', input('معرّف العميل، أو Enter للمراجع العامة: ').strip()),
        ('project_id', input('معرّف المشروع، أو Enter: ').strip())) if value}
    print(HELP)
    while True:
        message = input('أنت: ').strip()
        if not message:
            return
        try:
            if message.startswith('/تعليم '):
                print(review_teacher_import(message[7:].strip().strip('"'), scope=scope, root=root, confirm=input))
                kb = BoodaLocalKnowledgeBase(root / 'knowledge/local_documents.json')
                continue
            answer = local_reply(message, knowledge_base=kb, scope=scope, root=root)
            print('بوده: ' + (answer if answer is not None else
                'الطلب يحتاج قدرة أخرى؛ استخدم /مساعدة للمتاح محليًا. لم أنفذ إجراءً ولم أتصل بخدمة.'))
        except (ValueError, OSError, RuntimeError) as error:
            print('لم تكتمل العملية المحلية: ' + str(error))
