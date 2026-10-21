"""Protocol fixtures, not a real X account or simulated successful AI output."""
import io
import time
import zipfile

from fastapi.testclient import TestClient
import pytest

from xsecondbrain.config import Settings
from xsecondbrain.main import create_app

EXTENSION = 'a'*32
ORIGIN = 'chrome-extension://'+EXTENSION
SOURCE = {'event_id':'fixture-event-0001','url':'https://x.com/xsb_fixture/status/0',
          'title':'【原创协议测试样例，并非真实X文章】', 'author':'测试角色',
          'content':'这是明确标记的测试样例。整理资料，保留每段出处，再用检索找到能回答问题的段落。证据不足时需要人工处理。',
          'completeness':'page_text','capture_method':'bookmark'}


def pair(client,owner=None):
    code=client.post('/api/browser/pair-code',headers=owner or {}).json()['code']
    result=client.post('/api/browser/pair',headers={'Origin':ORIGIN,'X-XSB-Extension':EXTENSION},json={'code':code})
    assert result.status_code==200,result.text
    return {'Origin':ORIGIN,'X-XSB-Extension':EXTENSION,'Authorization':'Bearer '+result.json()['token']}


def test_scoped_pairing_does_not_open_library_or_app_token(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,app_token='owner-secret',embedding_provider='none'),start_worker=False)
    with TestClient(app) as client:
        owner={'Authorization':'Bearer owner-secret'}
        assert client.post('/api/browser/pair-code').status_code==401
        headers=pair(client,owner)
        assert client.get('/api/browser/ping',headers=headers).status_code==200
        assert client.get('/api/articles',headers=headers).status_code==401
        assert client.post('/api/browser/pair-code',headers=headers).status_code==401
        assert client.get('/api/status',headers=headers).status_code==401
        assert client.post('/api/browser/capture',headers=headers,json=SOURCE).status_code==200
        with app.state.service.db.connect() as conn:
            raw=' '.join(str(tuple(r)) for r in conn.execute('SELECT * FROM browser_pairs'))
            assert headers['Authorization'].split()[1] not in raw and 'owner-secret' not in raw
        assert client.delete('/api/browser/pairs',headers=owner).status_code==200
        assert client.get('/api/browser/ping',headers=headers).status_code==401


def test_pair_code_one_use_expiry_and_guess_limit(client,app):
    code=client.post('/api/browser/pair-code').json()['code']
    headers={'Origin':ORIGIN,'X-XSB-Extension':EXTENSION}
    for _ in range(6):assert client.post('/api/browser/pair',headers=headers,json={'code':'wrong-code'}).status_code==403
    assert client.post('/api/browser/pair',headers=headers,json={'code':code}).status_code==403
    code=client.post('/api/browser/pair-code').json()['code']
    assert client.post('/api/browser/pair',headers=headers,json={'code':code}).status_code==200
    assert client.post('/api/browser/pair',headers=headers,json={'code':code}).status_code==403
    code=client.post('/api/browser/pair-code').json()['code']
    with app.state.service.db.connect() as conn:conn.execute('UPDATE browser_pair_code SET expires=?',(time.time()-1,))
    assert client.post('/api/browser/pair',headers=headers,json={'code':code}).status_code==403


def test_cors_limited_to_extension_bridge(client):
    preflight=client.options('/api/browser/capture',headers={'Origin':ORIGIN,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,x-xsb-extension,content-type'})
    assert preflight.status_code==204
    assert preflight.headers['access-control-allow-origin']==ORIGIN
    assert 'access-control-allow-credentials' not in preflight.headers
    for origin in ['https://x.com','https://attacker.example','null','chrome-extension://not-valid']:
        assert client.options('/api/browser/capture',headers={'Origin':origin}).status_code==403
    headers=pair(client)
    assert client.get('/api/browser/ping',headers={**headers,'Origin':'chrome-extension://'+'b'*32}).status_code==403
    assert client.get('/api/browser/ping',headers={**headers,'Host':'attacker.example'}).status_code==403
    assert client.get('/api/articles',headers={'Origin':ORIGIN}).status_code==403


def test_offline_retry_dedup_and_restart_preserve_same_capture(client,app):
    headers=pair(client)
    result=client.post('/api/browser/capture',headers=headers,json=SOURCE).json()
    aid=result['id']
    assert not result['duplicate'] and not result['needs_content']
    assert client.post('/api/browser/capture',headers=headers,json=SOURCE).json()['duplicate']
    another={**SOURCE,'event_id':'fixture-event-0002','url':'https://twitter.com/another_author/status/0?ref=anything'}
    assert client.post('/api/browser/capture',headers=headers,json=another).json()['id']==aid
    app.state.service.process(aid)  # No language model configured: no fake AI analysis.
    assert app.state.service.db.article(aid)['status']=='saved'
    restarted=create_app(app.state.settings,start_worker=False)
    with TestClient(restarted) as second:
        assert second.get('/api/browser/ping',headers=headers).json()['received']==1
        assert second.get('/api/articles/'+aid).json()['content']==SOURCE['content']
        assert second.post('/api/browser/capture',headers=headers,json=SOURCE).json()['duplicate']
        assert second.get('/api/status').json()['total']==1


def test_preview_waits_for_full_body_and_never_downgrades(client,app):
    headers=pair(client)
    partial={**SOURCE,'completeness':'partial'}
    aid=client.post('/api/browser/capture',headers=headers,json=partial).json()['id']
    assert app.state.service.db.article(aid)['status']=='needs_content'
    assert client.get('/api/status').json()['queued']==0
    assert not client.get('/api/search',params={'q':'检索段落人工处理'}).json()['hits']
    app.state.service.retry(aid);app.state.service.process(aid)
    assert app.state.service.db.article(aid)['status']=='needs_content'
    full={**SOURCE,'event_id':'fixture-full-0002','content':SOURCE['content']+'\n展开后的正文提供了新的具体步骤，仍然明确标记为原创协议测试。','capture_method':'manual'}
    result=client.post('/api/browser/capture',headers=headers,json=full).json()
    assert result['id']==aid and not result['duplicate'] and not result['needs_content']
    assert client.get('/api/status').json()['queued']==1
    app.state.service.process(aid)
    assert app.state.service.db.article(aid)['content']==full['content']
    assert client.get('/api/search',params={'q':'检索段落人工处理'}).json()['hits']
    client.post('/api/browser/capture',headers=headers,json={**partial,'event_id':'fixture-preview-again'})
    assert app.state.service.db.article(aid)['content']==full['content']
    assert client.get('/api/browser').json()['needs_content']==0
    extended={**full,'event_id':'fixture-expanded-again','content':full['content']+'\n页面继续展开后的文字，用户明确选择保存更新。'}
    assert not client.post('/api/browser/capture',headers=headers,json=extended).json()['duplicate']
    assert app.state.service.db.article(aid)['content']==extended['content']


@pytest.mark.parametrize('url',['http://x.com/user/status/0','https://x.com/home','https://example.org/','https://x.com.attacker.example/user/status/0','https://x.com:9000/user/status/0'])
def test_clipper_rejects_arbitrary_source_urls(client,url):
    assert client.post('/api/browser/capture',headers=pair(client),json={**SOURCE,'url':url}).status_code==400


def test_extension_download_contains_only_installable_source(client):
    response=client.get('/browser-extension.zip')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        assert 'x-bookmark-clipper/manifest.json' in archive.namelist()
        assert not any(name.endswith(('.sqlite3','.env','.bin')) for name in archive.namelist())


def test_preview_backup_remains_incomplete_and_no_pair_tokens_exported(client,tmp_path):
    headers=pair(client)
    client.post('/api/browser/capture',headers=headers,json={**SOURCE,'completeness':'partial'})
    backup=client.get('/api/export').json()
    assert 'browser_pairs' not in backup and headers['Authorization'].split()[1] not in str(backup)
    restored=create_app(Settings(data_dir=tmp_path/'restored',embedding_provider='none'),start_worker=False)
    with TestClient(restored) as second:
        result=second.post('/api/import',json=backup).json()['results'][0]
        assert second.get('/api/articles/'+result['id']).json()['status']=='needs_content'
        assert second.get('/api/status').json()['queued']==0
        assert not second.get('/api/search',params={'q':'检索段落人工处理'}).json()['hits']


def test_skill_can_supply_missing_body_without_later_clipper_overwrite(client,app):
    headers=pair(client)
    aid=client.post('/api/browser/capture',headers=headers,json={**SOURCE,'completeness':'partial'}).json()['id']
    full=SOURCE['content']+'\n用户确认并补充的完整正文，用来核对步骤和限制。'
    result=client.post('/api/articles',json={'url':SOURCE['url'],'content':full}).json()
    assert result['id']==aid and not result['duplicate']
    app.state.service.process(aid)
    client.post('/api/browser/capture',headers=headers,json={**SOURCE,'event_id':'fixture-browser-returns'})
    assert app.state.service.db.article(aid)['content']==full
