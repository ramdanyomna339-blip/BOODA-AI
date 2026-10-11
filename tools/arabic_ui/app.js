const fragment = new URLSearchParams(location.hash.slice(1));
const token = fragment.get('token') || sessionStorage.getItem('booda-token') || '';
if (fragment.has('token')) {sessionStorage.setItem('booda-token', token); history.replaceState(null, '', '/');}
const output = document.getElementById('output'), log = document.getElementById('log');
const prompt = document.getElementById('prompt'), answer = document.getElementById('answer');
const submit = document.getElementById('submit'), status = document.getElementById('status');
let pending = null, revision = -1, busy = false;
async function refresh() {
  try {
    const response = await fetch('/state', {headers:{'X-Booda-Token':token},cache:'no-store'});
    if (!response.ok) throw new Error('connection');
    const state = await response.json();
    if (revision !== state.revision) {
      const atEnd = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
      output.textContent = state.text;
      const messages = document.getElementById('messages');
      messages.replaceChildren();
      for (const message of state.messages || []) {
        const bubble = document.createElement('p');
        bubble.className = 'bubble ' + message.role;
        bubble.dir = 'auto';
        bubble.textContent = (message.role === 'user' ? 'أنت: ' : 'بودا: ') + message.text;
        messages.appendChild(bubble);
      }
      if (atEnd) log.scrollTop = log.scrollHeight;
      const changed = (pending?.id || null) !== (state.pending?.id || null);
      pending = state.pending;
      prompt.textContent = pending?.prompt || (state.finished ? 'انتهت الجلسة' : 'بودا بيجهّز الرد…');
      answer.type = pending?.secret ? 'password' : 'text';
      answer.disabled = !pending || busy;
      submit.disabled = !pending || busy;
      if (changed) {answer.value = ''; if (pending) answer.focus();}
      status.textContent = state.finished ? 'انتهت الجلسة. يمكنك إغلاق الصفحة.' : 'متصل محليًا — النصوص محفوظة بترتيبها الأصلي';
      status.className = '';
      revision = state.revision;
    }
  } catch {status.textContent = 'الاتصال متوقف. أعيدي تشغيل بودا إذا انتهت الجلسة.'; status.className = 'error'; answer.disabled = submit.disabled = true;}
}
document.getElementById('form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!pending || busy) return;
  busy = true; answer.disabled = submit.disabled = true;
  const body = {id:pending.id,value:answer.value};
  try {
    const response = await fetch('/answer', {method:'POST',headers:{'X-Booda-Token':token,'Content-Type':'application/json'},body:JSON.stringify(body)});
    if (!response.ok) throw new Error('submission');
    answer.value = ''; pending = null;
  } catch {status.textContent = 'لم يُقبل الإدخال؛ راجعي السؤال الحالي قبل إعادة الإرسال.';}
  finally {busy = false; revision = -1; await refresh();}
});
refresh(); setInterval(refresh, 500);

const libraryStatus = document.getElementById('library-status');
async function libraryRequest(path, body) {
  const response = await fetch(path, {method:'POST',headers:{'X-Booda-Token':token,'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'تعذر إكمال الطلب');
  return result;
}
document.getElementById('upload').addEventListener('click', async () => {
  const button = document.getElementById('upload');
  const file = document.getElementById('attachment').files[0];
  if (!file || file.size > 20000000) {libraryStatus.textContent = 'اختر ملفًا أصغر من 20 ميجابايت'; return;}
  button.disabled = true; libraryStatus.textContent = 'جارٍ قراءة المستند…';
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    let binary = '';
    for (let i=0; i<bytes.length; i+=8192) binary += String.fromCharCode(...bytes.subarray(i,i+8192));
    const result = await libraryRequest('/documents', {name:file.name,content:btoa(binary),ocr:document.getElementById('ocr').checked});
    libraryStatus.textContent = 'تمت إضافة ' + result.title + ' — ' + result.chunks + ' مقاطع';
  } catch(error) {libraryStatus.textContent = error.message;}
  finally {button.disabled = false;}
});
document.getElementById('search-form').addEventListener('submit', async event => {
  event.preventDefault();
  const sources = document.getElementById('sources');
  try {
    libraryStatus.textContent = 'جارٍ البحث…';
    const result = await libraryRequest('/search', {query:document.getElementById('query').value});
    sources.replaceChildren();
    for (const item of result.results) {
      const card = document.createElement('article');
      const title = document.createElement('h3'), text = document.createElement('p');
      title.textContent = item.title + (item.page ? ' — صفحة ' + item.page : '');
      text.textContent = item.text;
      const note = document.createElement('small');
      note.textContent = (item.source.startsWith('attachment:') ? 'الملف: ' + item.source.slice(11) : item.source) + (item.extraction_method === 'ocr' ? ' — نص مستخرج آليًا، راجعه مع الأصل' : '');
      card.append(title,text,note); sources.appendChild(card);
    }
    libraryStatus.textContent = result.results.length ? (result.mode === 'hybrid' ? 'نتائج بالكلمات والمعنى' : 'نتائج بالكلمات — البحث بالمعنى غير جاهز') : 'لا توجد نتائج مطابقة';
  } catch(error) {libraryStatus.textContent = error.message;}
});
