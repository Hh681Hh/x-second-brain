import json
import sqlite3
import pytest
from fastapi.testclient import TestClient

from xsecondbrain.config import Settings
from xsecondbrain.main import create_app
from xsecondbrain.security import UserError, normalize_url
from .conftest import SECOND


def test_text_only_export_roundtrip(client, tmp_path):
    content = '这是一篇无链接的明确测试笔记，导出以后必须能够恢复正文，不能因空链接拒绝整份备份。'
    client.post('/api/articles', json={'title': '无链接笔记', 'content': content})
    payload = client.get('/api/export').json()
    assert payload['articles'][0]['url'] is None
    app = create_app(Settings(data_dir=tmp_path / 'restored', embedding_provider='none'), start_worker=False)
    with TestClient(app) as target:
        response = target.post('/api/import', json=payload)
        assert response.status_code == 200
        restored = target.get('/api/articles/' + response.json()['results'][0]['id']).json()
        assert restored['content'] == content and restored['url'] is None


def test_save_deduplicate_and_restart(client, app, sample):
    first = client.post('/api/articles', json=sample)
    assert first.status_code == 201
    aid = first.json()['id']
    assert client.post('/api/articles', json={**sample, 'url': sample['url']+'?utm_campaign=test#part'}).json()['duplicate']
    assert client.post('/api/articles', json={**sample,'url':'https://example.org/other'}).json()['duplicate']
    app.state.service.process(aid)
    article = client.get('/api/articles/'+aid).json()
    assert article['status'] == 'saved' and article['content'] == sample['content']
    assert article['analysis'] is None
    reopened = create_app(app.state.settings, start_worker=False)
    with TestClient(reopened) as other:
        assert other.get('/api/articles/'+aid).json()['content'] == sample['content']
        assert other.get('/api/status').json()['total'] == 1


def test_missing_x_token_and_manual_repair(client, app):
    aid = client.post('/api/articles',json={'url':'https://twitter.com/example/status/12345?s=20'}).json()['id']
    app.state.service.process(aid)
    article = client.get('/api/articles/'+aid).json()
    assert article['status'] == 'needs_content' and '官方 API' in article['ai_error']
    assert article['url'] == 'https://x.com/i/web/status/12345'
    content = '这是用户明确粘贴的完整帖子串。第一帖说明问题，第二帖提出方法，第三帖给出方法的适用条件和限制。'
    assert client.patch('/api/articles/'+aid,json={'content':content}).status_code == 200
    app.state.service.process(aid)
    assert client.get('/api/articles/'+aid).json()['status'] == 'saved'


def test_no_key_returns_real_fragments_and_no_fabricated_answer(client, app, sample):
    aid = client.post('/api/articles',json=sample).json()['id']
    app.state.service.process(aid)
    answer = client.post('/api/chat',json={'question':'帮助资料检索与转交人工应该怎么结合？'}).json()
    assert answer['mode'] == 'retrieval_only' and answer['insufficient']
    assert answer['claims'] == [] and answer['ai_suggestions'] == []
    assert answer['sources'][0]['text'] in sample['content']
    assert answer['sources'][0]['url'] == sample['url']
    history = client.get('/api/sessions/'+answer['session_id']).json()
    assert len(history['messages']) == 2
    unrelated = client.post('/api/chat',json={'question':'意大利番茄种植的温度管理'}).json()
    assert unrelated['mode'] == 'no_evidence' and not unrelated['sources'] and unrelated['insufficient']


def test_multi_article_retrieval_and_tag_management(client, app, sample):
    ids = [client.post('/api/articles',json=item).json()['id'] for item in (sample,SECOND)]
    for aid in ids: app.state.service.process(aid)
    result = client.get('/api/search',params={'q':'检索证据回答客户咨询并评估拒答率'}).json()
    assert {h['article_id'] for h in result['hits']} == set(ids)
    client.patch('/api/articles/'+ids[0],json={'tags':['客服','RAG'],'is_read':True})
    assert len(client.get('/api/articles',params={'tag':'客服'}).json()['articles']) == 1
    assert client.get('/api/articles',params={'unread':True}).json()['total'] == 1
    client.delete('/api/articles/'+ids[0])
    with app.state.service.db.connect() as conn:
        assert conn.execute('SELECT count(*) FROM chunks_fts WHERE chunk_id NOT IN (SELECT id FROM chunks)').fetchone()[0] == 0


def test_transfer_roundtrip_and_duplicates(client, app, sample, tmp_path):
    aid = client.post('/api/articles',json=sample).json()['id']
    app.state.service.process(aid)
    client.post('/api/chat',json={'question':'帮助资料如何检索？'})
    payload = client.get('/api/export').json()
    assert payload['format'] == 'x-second-brain' and 'llm_api_key' not in json.dumps(payload)
    other = create_app(Settings(data_dir=tmp_path/'restore',embedding_provider='none'),start_worker=False)
    with TestClient(other) as target:
        imported = target.post('/api/import',json=payload)
        assert imported.status_code == 200
        assert imported.json()['restored_sessions'] == 1
        imported_id = imported.json()['results'][0]['id']
        restored = target.get('/api/articles/'+imported_id).json()
        assert restored['content'] == sample['content']
        assert restored['saved_at'] == payload['articles'][0]['saved_at']
        assert target.post('/api/import',json=payload).json()['results'][0]['duplicate']
        assert target.get('/api/articles').json()['total'] == 1


def test_fetch_failure_retains_url(client, app, monkeypatch):
    def failure(*args): raise UserError('来源连接失败，请补充全文。')
    monkeypatch.setattr('xsecondbrain.service.collect',failure)
    aid = client.post('/api/articles',json={'url':'https://example.org/unavailable'}).json()['id']
    app.state.service.process(aid)
    article = client.get('/api/articles/'+aid).json()
    assert article['status'] == 'needs_content' and article['url']
    assert '连接失败' in article['ai_error']


def test_running_job_recovers_after_restart(client, app, sample):
    aid = client.post('/api/articles',json=sample).json()['id']
    with app.state.service.db.connect() as conn:
        conn.execute("UPDATE jobs SET state='running'")
        conn.execute("UPDATE articles SET status='processing'")
    reopened = create_app(app.state.settings,start_worker=False)
    with reopened.state.service.db.connect() as conn:
        assert conn.execute('SELECT state FROM jobs').fetchone()[0] == 'queued'
    reopened.state.service.process(aid)
    assert reopened.state.service.db.article(aid)['status'] == 'saved'


def test_patch_duplicate_and_bad_input(client, sample):
    aid = client.post('/api/articles',json=sample).json()['id']
    second_id = client.post('/api/articles',json=SECOND).json()['id']
    assert client.patch('/api/articles/'+second_id,json={'content':sample['content']}).status_code == 409
    assert client.post('/api/articles',json={'content':'too short'}).status_code == 422
    assert client.post('/api/articles',json={'url':'file:///etc/passwd'}).status_code == 400
    assert client.get('/api/articles/does-not-exist').status_code == 404
    assert client.post('/api/articles/batch',json={'articles':[]}).status_code == 422


def test_preferences(client):
    result = client.put('/api/preferences',json={'categories':['我的方法','我的方法','其他'],'interests':'自动化服务'})
    assert result.status_code == 200
    assert result.json()['categories'] == ['我的方法','其他']
    assert client.get('/api/preferences').json()['interests'] == '自动化服务'


def test_local_api_docs_have_no_cdn_dependencies(client):
    response = client.get('/api/docs')
    assert response.status_code == 200 and '/static/api-docs.js' in response.text
    assert 'cdn.jsdelivr' not in response.text
    assert '/api/articles' in client.get('/api/openapi.json').json()['paths']


def test_embedding_configuration_failure_keeps_manual_library(tmp_path,sample):
    app = create_app(Settings(data_dir=tmp_path,embedding_provider='api',embedding_api_key=''),start_worker=False)
    with TestClient(app) as client:
        aid = client.post('/api/articles',json=sample).json()['id']
        app.state.service.process(aid)
        article = client.get('/api/articles/'+aid).json()
        assert article['status'] == 'saved' and article['content'] == sample['content']
        assert 'EMBEDDING_API_KEY' in article['embedding_error']
        result = client.get('/api/search',params={'q':'检索帮助资料'}).json()
        assert result['hits'] and result['mode'] == 'keyword'


def test_invalid_backup_analysis_is_skipped(client,sample):
    payload = {'format':'x-second-brain','version':1,'articles':[{**sample,'id':'untrusted-backup','analysis':{'quick':[{'evidence':[{'chunk_id':'fake','quote':'编造的不存在的引用'}]}]}}]}
    result = client.post('/api/import',json=payload)
    assert result.status_code == 200
    aid = result.json()['results'][0]['id']
    assert result.json()['results'][0]['warnings']
    assert client.get('/api/articles/'+aid).json()['analysis'] is None
