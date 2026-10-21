"""Protocol fixtures for X integration; no real X account and no fabricated AI output."""
import hashlib
import base64
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from xsecondbrain.config import Settings
from xsecondbrain.main import create_app
from xsecondbrain.security import UserError
from xsecondbrain.xsync import COOKIE, CALLBACK_PATH, SCOPES, SyncConfig, XAPIError

TOKEN = 'protocol-fixture-access-never-a-real-token'
REFRESH = 'protocol-fixture-refresh-never-a-real-token'
ARTICLE = '【协议测试夹具，不是真实 X 文章】将帮助文档分段并保留来源。收到重复咨询时先检索相关资料，再依据原段落回答。证据不足时拒答并转交人工。'


def post(post_id='200', **extra):
    return {'id': post_id, 'author_id':'17', 'created_at':'2020-01-01T00:00:00Z',
            'text': '长文预览', 'note_tweet': {'text': ARTICLE+' 标识 '+post_id}, **extra}


def page(posts, cursor=None):
    return {'data': posts, 'includes': {'users':[{'id':'17','name':'协议测试作者','username':'fixture'}]},
            'meta': {'result_count':len(posts), **({'next_token':cursor} if cursor else {})}}


def configured(app, handler):
    sync = app.state.xsync
    sync.transport = httpx.MockTransport(handler)
    moment = [1000.0]
    sync.clock = lambda: moment[0]
    sync.configure(SyncConfig(client_id='protocol-fixture-client', page_size=5, max_pages=2))
    sync.store.write('x-credentials.bin', {'access_token':TOKEN,'refresh_token':REFRESH,
        'expires_at':10000, 'scope':' '.join(SCOPES),'account':{'id':'9','username':'test-owner','name':'测试角色'}})
    sync.switch(True, True)
    return sync, moment


def test_oauth_pkce_browser_binding_single_use_encrypted_and_no_export(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, port=8765, app_token='local-test-secret', embedding_provider='none'), start_worker=False)
    sync = app.state.xsync
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/oauth2/token'):
            fields = parse_qs(request.content.decode())
            assert fields['grant_type']==['authorization_code']
            verifier = fields['code_verifier'][0]
            expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            assert expected == authorization['code_challenge'][0]
            return httpx.Response(200,json={'access_token':TOKEN,'refresh_token':REFRESH,'scope':' '.join(SCOPES),'expires_in':7200,'token_type':'bearer'})
        assert request.url.path == '/2/users/me'
        assert request.headers['Authorization'] == 'Bearer '+TOKEN
        return httpx.Response(200,json={'data':{'id':'9','name':'协议角色','username':'fixture-owner'}})
    sync.transport = httpx.MockTransport(handler)
    auth = {'Authorization':'Bearer local-test-secret'}
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        assert client.post('/api/integrations/x/authorize').status_code==401
        assert client.put('/api/integrations/x/config',json={'client_id':'protocol-fixture'},headers=auth).status_code==200
        start = client.post('/api/integrations/x/authorize',headers=auth)
        assert start.status_code == 200
        assert 'HttpOnly' in start.headers['set-cookie'] and 'SameSite=lax' in start.headers['set-cookie']
        authorization = parse_qs(urlsplit(start.json()['authorization_url']).query)
        assert authorization['code_challenge_method']==['S256']
        assert set(authorization['scope'][0].split()) == set(SCOPES)
        pending_state = authorization['state'][0]
        # Cross-browser callback has no binding cookie and cannot connect the account.
        with TestClient(app,base_url='http://127.0.0.1:8765') as other:
            assert other.get(CALLBACK_PATH,params={'state':pending_state,'code':'fixture-code'}).status_code==400
        assert client.get(CALLBACK_PATH,params={'state':'恶意状态','code':'fixture-code'}).status_code==400
        result = client.get(CALLBACK_PATH,params={'state':pending_state,'code':'fixture-code'},follow_redirects=False)
        assert result.status_code==303 and result.headers['location']=='/official-x#sync'
        status = client.get('/api/integrations/x',headers=auth)
        assert status.json()['connected'] and not status.json()['sync_enabled']
        assert TOKEN not in status.text and REFRESH not in status.text
        assert client.get(CALLBACK_PATH,params={'state':pending_state,'code':'fixture-code'}).status_code==400
        assert TOKEN.encode() not in (tmp_path/'x-credentials.bin').read_bytes()
        exported = client.get('/api/export',headers=auth).text
        assert TOKEN not in exported and REFRESH not in exported and 'protocol-fixture' not in exported
    assert len(requests)==2  # Connecting never polls bookmarks.


def test_unconfigured_no_network_no_false_enabled(client, app):
    app.state.xsync.transport=httpx.MockTransport(lambda request: pytest.fail('Must not call X without authorization'))
    status = client.get('/api/integrations/x').json()
    assert not status['connected'] and not status['sync_enabled']
    assert client.post('/api/integrations/x/authorize').status_code==400
    assert client.post('/api/integrations/x/switch',json={'enabled':True,'acknowledge_api_cost':True}).status_code==409
    assert client.post('/api/integrations/x/sync').status_code==409


def test_cost_acknowledgment_and_cross_origin_required(app):
    sync, _ = configured(app,lambda request: httpx.Response(200,json=page([])))
    sync.switch(False)
    with TestClient(app) as client:
        assert client.post('/api/integrations/x/switch',json={'enabled':True}).status_code==400
        assert client.post('/api/integrations/x/switch',json={'enabled':True,'acknowledge_api_cost':True},headers={'Origin':'https://evil.example'}).status_code==403
        assert not sync.status()['sync_enabled']


def test_import_full_text_filter_short_metadata_only_and_process(app):
    posts = [post(), {'id':'201','text':'短帖','author_id':'17'},
             {'id':'202','text':'预览链接','article':{'title':'只返回标题的 Article'},'author_id':'17'},
             {'id':'203','text':'兼容字段预览','note_post':{'text':ARTICLE+' 使用新字段'}}]
    sync, _ = configured(app,lambda request: httpx.Response(200,json=page(posts)))
    counts=sync.sync_once()
    assert counts==dict(imported=2,needs_content=1,duplicate=0,skipped=1,pages=1)
    with sync.db.connect() as conn:
        articles=conn.execute('SELECT id,url,content,status,extraction_note FROM articles ORDER BY url').fetchall()
        assert len(articles)==3
        assert articles[1]['status']=='needs_content' and not articles[1]['content']
        assert '官方收藏接口' in articles[0]['extraction_note']
        assert conn.execute("SELECT count(*) FROM jobs WHERE state='queued'").fetchone()[0]==2
    app.state.service.process(articles[0]['id'])
    saved=sync.db.article(articles[0]['id'])
    assert saved['status']=='saved' and saved['analysis'] is None and ARTICLE in saved['content']
    assert saved['author']=='协议测试作者 (@fixture)' and saved['url'].endswith('/200')
    assert sync.status()['imported_total']==3


def test_new_bookmark_of_old_post_and_restart_deduplicates(app):
    posts=[post('900')]
    sync, moment=configured(app,lambda request: httpx.Response(200,json=page(posts)))
    assert sync.sync_once()['imported']==1
    posts.insert(0,post('100'))  # Newly bookmarked article was published years earlier.
    moment[0]+=601
    assert sync.sync_once()['imported']==1
    reopened=create_app(app.state.settings,start_worker=False)
    restored=reopened.state.xsync
    restored.clock=lambda:moment[0]+601
    restored.transport=sync.transport
    assert restored.status()['connected'] and restored.status()['sync_enabled']
    assert restored.sync_once()['duplicate']==2
    with restored.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM articles').fetchone()[0]==2


def test_head_priority_bounded_pages_and_resume(app):
    calls=[]
    head=[post('700')]
    def handler(request):
        cursor=request.url.params.get('pagination_token')
        calls.append(cursor)
        data={None:page(head,'older-one'),'older-one':page([post('600')],'older-two'),'older-two':page([post('500')])}
        return httpx.Response(200,json=data[cursor])
    sync,moment=configured(app,handler)
    assert sync.sync_once()['pages']==2
    assert sync.status()['catching_up']
    head.insert(0,post('50'))
    moment[0]+=601
    assert sync.sync_once()['imported']==2
    assert calls==[None,'older-one',None,'older-two']
    assert not sync.status()['catching_up']


def test_partial_failure_keeps_cursor_and_saved_posts(app):
    failing=[True]
    def handler(request):
        if request.url.params.get('pagination_token'):
            if failing[0]: raise httpx.ConnectError('fixture network failure')
            return httpx.Response(200,json=page([post('90')]))
        return httpx.Response(200,json=page([post('99')],'resume-here'))
    sync,moment=configured(app,handler)
    with pytest.raises(XAPIError): sync.sync_once()
    assert sync._state()['cursor']=='resume-here'
    assert sync.status()['imported_total']==1 and sync.status()['last_error']
    failing[0]=False
    moment[0]=sync._state()['next_run']+1
    assert sync.sync_once()['imported']==1
    assert sync.status()['imported_total']==2 and not sync.status()['last_error']


@pytest.mark.parametrize('status',[401,402,403,429,503])
def test_upstream_failure_pauses_or_backs_off_without_leaking_response(app,status):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'detail':TOKEN},headers={'x-rate-limit-reset':'4000'})
    sync,moment=configured(app,handler)
    with pytest.raises(XAPIError) as failure: sync.sync_once()
    state=sync.status()
    assert TOKEN not in str(failure.value) and TOKEN not in json.dumps(state)
    assert state['last_error'] and not state['last_success_at']
    assert state['sync_enabled']==(status not in (401,402,403))
    assert state['connected']==(status!=401)
    assert sync._state()['next_run']>=1600
    if status==429: assert sync._state()['next_run']>=4000
    with pytest.raises(UserError): sync.sync_once()
    assert len(calls)==1


def test_expired_token_refresh_rotation_saved_before_bookmark_request(app):
    def handler(request):
        if request.url.path.endswith('/oauth2/token'):
            fields=parse_qs(request.content.decode())
            assert fields['grant_type']==['refresh_token'] and fields['refresh_token']==[REFRESH]
            return httpx.Response(200,json={'access_token':TOKEN+'-new','refresh_token':REFRESH+'-new','expires_in':7200})
        assert request.headers['Authorization']=='Bearer '+TOKEN+'-new'
        assert app.state.xsync.store.read('x-credentials.bin')['refresh_token']==REFRESH+'-new'
        return httpx.Response(200,json=page([post()]))
    sync,_=configured(app,handler)
    credentials=sync.store.read('x-credentials.bin'); credentials['expires_at']=999
    sync.store.write('x-credentials.bin',credentials)
    assert sync.sync_once()['imported']==1
    assert sync.store.read('x-credentials.bin')['account']['id']=='9'


def test_documented_field_compatibility_and_malformed_partial_response(app):
    calls=[]
    def handler(request):
        calls.append(request.url.params)
        if 'tweet.fields' in request.url.params: return httpx.Response(400,json={})
        return httpx.Response(200,json=page([post()]))
    sync,_=configured(app,handler)
    assert sync.sync_once()['imported']==1
    assert len(calls)==2 and 'post.fields' in calls[1]
    sync._update(next_run=0)
    sync.transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'data':[post('300')],'errors':[{'detail':'unavailable'}]}))
    with pytest.raises(XAPIError): sync.sync_once()
    assert sync.status()['imported_total']==1


def test_disconnect_revoke_failure_removes_local_credentials_keeps_library(app):
    sync,_=configured(app,lambda request:httpx.Response(200,json=page([post()])))
    sync.sync_once()
    sync.transport=httpx.MockTransport(lambda request:httpx.Response(503,json={}))
    result=sync.disconnect()
    assert not result['connected'] and not result['sync_enabled'] and '手动撤销' in result['message']
    assert not (sync.settings.data_dir/'x-credentials.bin').exists()
    assert sync.status()['imported_total']==1


def test_oauth_expiry_denial_and_untrusted_callback_origin(app):
    sync=app.state.xsync
    sync.configure(SyncConfig(client_id='protocol-fixture'))
    now=[1000]
    sync.clock=lambda:now[0]
    url,nonce=sync.authorize(); state=parse_qs(urlsplit(url).query)['state'][0]
    now[0]+=601
    with pytest.raises(UserError): sync.callback(state,'fixture-code',nonce)
    url,nonce=sync.authorize(); state=parse_qs(urlsplit(url).query)['state'][0]
    assert sync.callback(state,'',nonce,'access_denied') is False
    assert not sync.status()['connected']
    with TestClient(app,base_url='http://localhost:8765') as client:
        assert client.post('/api/integrations/x/authorize').status_code==400


def test_ciphertext_corruption_reported_and_disconnect_recovers(app):
    sync,_=configured(app,lambda request:httpx.Response(200,json={}))
    (sync.settings.data_dir/'x-credentials.bin').write_bytes(b'corrupt-fixture')
    assert not sync.status()['connected'] and '解密' in sync.status()['last_error']
    sync.disconnect()
    assert not sync.status()['last_error']


def test_background_worker_imports_and_pause_prevents_more_requests(app):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json=page([post()]))
    sync,_=configured(app,handler)
    sync.start()
    try:
        deadline=time.monotonic()+3
        while not sync._state()['last_success_at'] and time.monotonic()<deadline:
            time.sleep(0.01)
        assert sync.status()['imported_total']==1 and len(calls)==1
        sync.switch(False)
        sync._update(next_run=0)
        sync.wake.set()
        time.sleep(0.05)
        assert len(calls)==1
    finally:
        sync.stop()
    assert not sync.thread.is_alive()


def test_successful_revoke_and_filter_change_reconsiders_short_posts(app):
    def handler(request):
        if request.url.path.endswith('/oauth2/revoke'):
            assert parse_qs(request.content.decode())['token']==[REFRESH]
            return httpx.Response(200,json={'revoked':True})
        return httpx.Response(200,json=page([{'id':'303','text':'【协议夹具】短帖也可以保存，只有明确切换全部收藏时才导入。'}]))
    sync,moment=configured(app,handler)
    assert sync.sync_once()['skipped']==1
    sync.configure(SyncConfig(client_id='protocol-fixture-client',long_only=False,page_size=5,max_pages=2))
    moment[0]+=601
    assert sync.sync_once()['imported']==1
    assert '撤销授权' in sync.disconnect()['message']
    assert not sync.status()['connected']
