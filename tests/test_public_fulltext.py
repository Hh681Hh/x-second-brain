"""Parser/protocol tests use labeled fixtures; they do not simulate AI success."""

import httpx
import pytest
from fastapi.testclient import TestClient

from xsecondbrain import public_fulltext as module
from xsecondbrain.config import Settings
from xsecondbrain.main import create_app
from xsecondbrain.security import UserError
from tests.test_browser_bridge import pair, SOURCE


def fixture():
    return {'code': 200, 'status': {'id': '0', 'created_timestamp': 0,
        'author': {'name': '协议测试作者', 'screen_name': 'fixture'},
        'article': {'title': '【原创协议样例】', 'preview_text': '只有预览', 'content': {
            'blocks': [{'type': 'unstyled', 'text': '【原创协议样例】先收集原始证据，再核对引文，最后决定是否可以回答。'}],
            'entityMap': []}}}}


def test_article_body_not_preview_and_identity_verified():
    result = module.decode_fulltext(fixture(), '0')
    assert result.content.startswith('【原创协议样例】')
    assert result.content != '只有预览'
    assert result.source_kind == 'article'
    with pytest.raises(UserError, match='身份'):
        module.decode_fulltext(fixture(), '123')
    data = fixture(); data['status']['article']['content']['blocks'] = []
    with pytest.raises(UserError, match='预览'):
        module.decode_fulltext(data, '0')


def test_markdown_entities_are_not_lost_and_unknown_blocks_rejected():
    data = fixture(); body = data['status']['article']['content']
    body['blocks'] = [{'type': 'atomic', 'text': '', 'entityRanges': [{'key': 2}]}]
    body['entityMap'] = [{'key': '2', 'value': {'type': 'MARKDOWN', 'data': {
        'markdown': '# 【原创协议样例】\n保留全文，逐段验证来源，不能把只有标题的预览当作全文。'}}}]
    assert module.decode_fulltext(data, '0').content.startswith('# 【原创协议样例】')
    body['entityMap'][0]['value']['type'] = 'UNSUPPORTED'
    with pytest.raises(UserError, match='尚不支持'):
        module.decode_fulltext(data, '0')


def test_disabled_adapter_makes_no_network_request(monkeypatch):
    monkeypatch.setattr(module.httpx, 'Client', lambda **k: pytest.fail('No consent, no request'))
    with pytest.raises(UserError, match='尚未启用'):
        module.collect_public_fulltext(SOURCE['url'])


def test_fixed_endpoint_no_credentials_and_transient_retry(monkeypatch):
    requests = []
    original_client = httpx.Client
    def handle(request):
        requests.append(request)
        return httpx.Response(503 if len(requests) == 1 else 200, json=fixture())
    transport = httpx.MockTransport(handle)
    monkeypatch.setattr(module.httpx, 'Client', lambda **kwargs: original_client(transport=transport, **kwargs))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    assert module.collect_public_fulltext(SOURCE['url'], enabled=True).source_kind == 'article'
    assert len(requests) == 2
    for request in requests:
        assert str(request.url) == 'https://api.fxtwitter.com/2/status/0'
        assert 'cookie' not in request.headers and 'authorization' not in request.headers
    for url in ('https://attacker.test/a/status/0','https://x.com:999/a/status/0','https://x.com/i/article/0'):
        with pytest.raises(UserError): module.collect_public_fulltext(url, enabled=True)
    assert len(requests) == 2


def test_partial_capture_is_queued_only_when_opted_in(tmp_path, monkeypatch):
    app = create_app(Settings(data_dir=tmp_path, embedding_provider='none', x_public_fulltext_provider='fxembed'), start_worker=False)
    calls = []
    def resolve(url, *, enabled):
        calls.append((url, enabled))
        return module.decode_fulltext(fixture(), '0')
    monkeypatch.setattr(module, 'collect_public_fulltext', resolve)
    with TestClient(app) as client:
        headers = pair(client)
        saved = client.post('/api/browser/capture', headers=headers, json={**SOURCE, 'completeness':'partial'}).json()
        aid = saved['id']
        assert client.get('/api/articles/'+aid).json()['status'] == 'queued'
        app.state.service.process(aid)
        result = client.get('/api/articles/'+aid).json()
        assert result['content'].startswith('【原创协议样例】')
        assert result['source_kind'] == 'article'
        assert result['analysis'] is None  # No model configured in this protocol test.
        assert len(calls) == 1
        client.post('/api/browser/capture', headers=headers, json={**SOURCE, 'completeness':'partial'})
        assert len(calls) == 1


def test_resolution_failure_keeps_preview_and_out_of_answer_evidence(tmp_path, monkeypatch):
    app = create_app(Settings(data_dir=tmp_path, embedding_provider='none', x_public_fulltext_provider='fxembed'), start_worker=False)
    def unavailable(*a, **k): raise UserError('公开接口不可用，保留预览')
    monkeypatch.setattr(module, 'collect_public_fulltext', unavailable)
    with TestClient(app) as client:
        saved = client.post('/api/browser/capture', headers=pair(client), json={**SOURCE, 'completeness':'partial'}).json()
        app.state.service.process(saved['id'])
        article = client.get('/api/articles/'+saved['id']).json()
        assert article['status'] == 'needs_content'
        assert article['content'] == SOURCE['content']
        assert article['analysis'] is None
        assert client.get('/api/search',params={'q':'整理资料'}).json()['hits'] == []
