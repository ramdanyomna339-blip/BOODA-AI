import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import pytest
from core.knowledge_base import BoodaLocalKnowledgeBase
from tools.mobile_workspace import handler_for


def test_mobile_http_requires_session_code_and_preserves_client_scope(tmp_path):
    kb = BoodaLocalKnowledgeBase(tmp_path/'knowledge/local_documents.json')
    path = tmp_path/'a.txt'
    path.write_text('رمز العقد: هاتف-404',encoding='utf-8')
    kb.import_file(path, client_id='a', private=True, reference_status='unverified_historical')
    server = ThreadingHTTPServer(('127.0.0.1',0),handler_for(tmp_path,'fixture-token'))
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    def send(message, client='a', token='fixture-token'):
        request = Request('http://127.0.0.1:'+str(server.server_port)+'/api',
            data=json.dumps({'message':message,'client_id':client,'project_id':''}).encode(),
            headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with urlopen(request,timeout=5) as response: return json.loads(response.read())
    try:
        with pytest.raises(HTTPError) as error: send('/بحث رمز العقد',token='wrong')
        assert error.value.code == 403
        assert '1750' in send('احسب 25% من 7000')['answer']
        assert 'هاتف-404' in send('/بحث رمز العقد')['answer']
        assert 'هاتف-404' not in send('/بحث رمز العقد',client='b')['answer']
        with pytest.raises(HTTPError):
            urlopen('http://127.0.0.1:'+str(server.server_port)+'/knowledge/local_documents.json')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
