"""Responsive local browser workspace. LAN exposure is explicit and token protected."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import secrets
import socket
from core.knowledge_base import BoodaLocalKnowledgeBase
from core.local_workspace import local_reply

PAGE = '''<!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>بوده المحلي</title>
<style>body{font:18px system-ui;background:#142238;color:white;max-width:800px;margin:auto;padding:20px}input,button,textarea{font:inherit;box-sizing:border-box;width:100%;padding:12px;margin:6px 0;border-radius:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}button{background:#f7c873;color:#142238;border:0}</style>
<h1>بوده المحلي</h1><p>حساب وبحث ومراجع فقط. لا نموذج ولا مفتاح خارجي. استخدم شبكة خاصة موثوقة.</p>
<input id="token" type="password" placeholder="رمز الدخول المعروض على اللابتوب" autocomplete="off">
<input id="client" placeholder="معرّف العميل، فارغ للمراجع العامة"><input id="project" placeholder="معرّف المشروع">
<textarea id="question" placeholder="احسب 25% من 7000 أو /بحث ثم الكلمات"></textarea><button id="send">تنفيذ محلي</button><pre id="answer"></pre>
<script>const el=id=>document.getElementById(id);for(const id of ['client','project'])el(id).oninput=()=>el('answer').textContent='تغير النطاق؛ النتائج السابقة مُسحت';
el('send').onclick=async()=>{el('send').disabled=true;try{const r=await fetch('/api',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+el('token').value},body:JSON.stringify({message:el('question').value,client_id:el('client').value,project_id:el('project').value})});const j=await r.json();el('answer').textContent=j.answer||j.error;}catch(e){el('answer').textContent='تعذر الاتصال بالمساحة المحلية';}finally{el('send').disabled=false;}};</script></html>'''


def handler_for(root, token):
    root = Path(root)
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)
        def log_message(self, *args): pass
        def respond(self, code, body, mime='application/json; charset=utf-8'):
            raw = body.encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(raw)
        def do_GET(self):
            if self.path != '/':
                self.respond(404, '{"error":"not found"}')
                return
            self.respond(200, PAGE, 'text/html; charset=utf-8')
        def do_POST(self):
            if self.path != '/api' or not hmac.compare_digest(self.headers.get('Authorization', '').encode('utf-8'), ('Bearer '+token).encode('utf-8')):
                self.respond(403, json.dumps({'error':'رمز دخول غير صحيح'}, ensure_ascii=False))
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 1 <= size <= 8192: raise ValueError('طلب أكبر من الحد أو فارغ')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict) or set(data) != {'message','client_id','project_id'} or any(
                    not isinstance(v,str) or len(v)>2000 for v in data.values()): raise ValueError('صيغة الطلب غير صالحة')
                kb = BoodaLocalKnowledgeBase(root/'knowledge/local_documents.json')
                answer = local_reply(data['message'], knowledge_base=kb,
                    scope={key:data[key].strip() or None for key in ('client_id','project_id')}, root=root)
                self.respond(200, json.dumps({'answer': answer or 'طلب خارج الأوامر المحلية؛ لم يُنفذ ولم يُرسل لخدمة.'}, ensure_ascii=False))
            except (ValueError, OSError, RuntimeError):
                self.respond(400, json.dumps({'error':'لم تكتمل العملية المحلية؛ راجع الصياغة وحجم الطلب'}, ensure_ascii=False))
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lan', action='store_true', help='Allow private LAN access; plain HTTP, no public hosting')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    token = secrets.token_urlsafe(24)
    root = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(('0.0.0.0' if args.lan else '127.0.0.1', args.port), handler_for(root, token))
    print('Local workspace: http://127.0.0.1:' + str(args.port), flush=True)
    if args.lan:
        try:
            for address in socket.gethostbyname_ex(socket.gethostname())[2]:
                if not address.startswith('127.'):
                    print('Private network candidate: http://' + address + ':' + str(args.port), flush=True)
        except OSError:
            print('Use the laptop private LAN address on the phone.', flush=True)
    print('Session access code: ' + token, flush=True)
    print('LAN mode requires a trusted private network; no TLS. Do not publish or forward this port.', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__ == '__main__': main()
