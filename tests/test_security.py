import socket
from fastapi.testclient import TestClient
import httpx
import pytest
from xsecondbrain.config import Settings
from xsecondbrain.main import create_app
from xsecondbrain.models import Analysis
from xsecondbrain.providers import LLM
from xsecondbrain.security import UserError, normalize_url, public_connect


def test_auth_origin_and_no_secret_exposure(tmp_path):
    app = create_app(Settings(data_dir=tmp_path,app_token='test-app-secret',llm_api_key='test-model-secret',embedding_provider='none'),start_worker=False)
    with TestClient(app) as client:
        assert client.get('/api/status').status_code == 401
        headers = {'Authorization':'Bearer test-app-secret'}
        res = client.get('/api/status',headers=headers)
        assert res.status_code == 200 and 'test-model-secret' not in res.text
        assert client.post('/api/reindex',headers={**headers,'Origin':'https://attacker.example'}).status_code == 403
        assert client.get('/api/status',headers={**headers,'Host':'attacker.example'}).status_code == 403
        assert client.get('/').status_code == 200


@pytest.mark.parametrize('ip',['127.0.0.1','10.1.2.3','169.254.169.254','::1','fc00::1','224.1.2.3'])
def test_fetch_blocks_non_public_ip(monkeypatch,ip):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,0,'',(ip,80))])
    with pytest.raises(UserError,match='公共'):
        public_connect(('untrusted.example',80))


def test_proxy_option_still_blocks_loopback(monkeypatch):
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**k:[(socket.AF_INET,socket.SOCK_STREAM,0,'',('127.0.0.1',80))])
    with pytest.raises(UserError):
        public_connect(('untrusted.example',80),allow_benchmark_proxy=True)


@pytest.mark.parametrize('value',['file:///etc/passwd','http://user:secret@example.com','https://example.com:9000/path','javascript:alert(1)'])
def test_invalid_source_url(value):
    with pytest.raises(UserError): normalize_url(value)


def test_real_provider_timeout_path(monkeypatch,tmp_path):
    original = httpx.Client
    def timeout(req): raise httpx.ReadTimeout('Simulated transport timeout')
    monkeypatch.setattr('xsecondbrain.providers.httpx.Client',lambda **kwargs:original(transport=httpx.MockTransport(timeout),**kwargs))
    llm = LLM(Settings(data_dir=tmp_path,llm_api_key='test-secret',llm_model='test-model'))
    with pytest.raises(UserError,match='超时'):
        llm.structured('test','test',Analysis)


def test_bad_model_output_is_not_saved(monkeypatch,tmp_path):
    original = httpx.Client
    monkeypatch.setattr('xsecondbrain.providers.httpx.Client',lambda **kwargs:original(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'choices':[{'message':{'content':'not JSON'}}]})),**kwargs))
    llm = LLM(Settings(data_dir=tmp_path,llm_api_key='test-secret',llm_model='test-model'))
    with pytest.raises(UserError,match='结构'):
        llm.structured('test','test',Analysis)
