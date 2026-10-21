"""Background mode boundaries; only negative CLI responses are simulated."""
import json
import os
from pathlib import Path
import sys
import time

from fastapi.testclient import TestClient
import pytest

from xsecondbrain import agent_cli
from xsecondbrain.codex_provider import reader_environment, strict_schema
from xsecondbrain.config import Settings, ROOT
from xsecondbrain.main import create_app
from xsecondbrain.providers import LLM
from xsecondbrain.security import UserError


def test_minimal_connect_page_and_category_statistics(client,sample):
    page=client.get('/')
    assert '连接一次' in page.text and 'primary-nav' not in page.text
    assert client.get('/workbench').status_code==200
    assert client.get('/static/connect.js').headers['cache-control']=='no-cache'
    client.post('/api/articles',json=sample)
    summary=client.get('/api/summary').json()
    assert summary['status']['headless'] and summary['status']['total']==1
    assert summary['categories']==[{'category':sample['category'],'count':1}]


def test_reader_environment_excludes_platform_credentials_and_current_chat(monkeypatch):
    for name in ['X_CLIENT_SECRET','LLM_API_KEY','APP_TOKEN','OPENAI_API_KEY','CODEX_THREAD_ID']:
        monkeypatch.setenv(name,'fixture-secret')
    environment=reader_environment()
    assert not any(name in environment for name in ['X_CLIENT_SECRET','LLM_API_KEY','APP_TOKEN','OPENAI_API_KEY','CODEX_THREAD_ID'])
    assert any(name.upper()=='PATH' for name in environment)


def test_missing_cli_never_claims_ai_analysis(tmp_path):
    settings=Settings(data_dir=tmp_path,llm_provider='codex',codex_binary=str(tmp_path/'missing-codex.exe'))
    assert not settings.llm_enabled
    from xsecondbrain.models import AnswerDraft
    with pytest.raises(UserError): LLM(settings).structured('fixture','fixture',AnswerDraft)


def test_cli_failure_does_not_expose_raw_source_or_credentials(tmp_path,monkeypatch):
    from xsecondbrain.models import AnswerDraft
    from xsecondbrain import codex_provider
    commands=[]
    class Failure:
        pid=123
        returncode=1
        def __init__(self,command,**kwargs): commands.extend(command)
        def communicate(self,prompt,timeout): return ('','fixture-private-source-and-token')
        def poll(self): return 1
    monkeypatch.setattr(codex_provider.subprocess,'Popen',Failure)
    settings=Settings(data_dir=tmp_path,llm_provider='codex',codex_binary=sys.executable)
    with pytest.raises(UserError) as error:
        LLM(settings).structured('fixture system','fixture article',AnswerDraft)
    assert 'fixture-private' not in str(error.value)
    assert '--ignore-user-config' in commands and '--ephemeral' in commands
    assert commands[commands.index('--sandbox')+1]=='read-only'
    assert 'shell_tool' in commands and 'multi_agent' in commands
    assert not list((tmp_path/'codex-reader').iterdir())


def test_strict_schema_keeps_grounding_enum_and_no_mutation():
    original={'type':'object','properties':{'quote':{'type':'string','enum':['原文证据']},'note':{'type':'string','default':''}},'required':['quote']}
    adapted=strict_schema(original)
    assert adapted['required']==['quote','note'] and not adapted['additionalProperties']
    assert adapted['properties']['quote']['enum']==['原文证据']
    assert original['required']==['quote'] and 'default' in original['properties']['note']


def test_background_stop_refuses_unverified_pid(tmp_path,monkeypatch):
    (tmp_path/'agent-process.json').write_text(json.dumps({'pid':123,'project':str(ROOT)}),encoding='utf-8')
    monkeypatch.setattr(agent_cli,'running',lambda settings:{'pid':456,'headless':True})
    with pytest.raises(UserError):agent_cli.stop(Settings(data_dir=tmp_path))


@pytest.mark.integration
def test_real_codex_analysis_classification_and_grounded_answer(tmp_path):
    if os.getenv('XSB_RUN_CODEX')!='1':pytest.skip('Requires explicitly enabled logged-in Codex CLI')
    from .conftest import SAMPLE
    settings=Settings(data_dir=tmp_path,llm_provider='codex',llm_timeout=600,embedding_provider='none')
    app=create_app(settings,start_worker=False)
    report={'started_at':time.time(),'source':'Explicitly marked original test fixture via browser ingest. https://x.com/i/article/0 is a nonexistent fixture URL, not a real X source. No real X account.','passed':False}
    output=ROOT/'docs'/'validation'/'codex-reader-test.json'
    try:
        with TestClient(app) as client:
            from .test_browser_bridge import pair
            headers=pair(client)
            source={k:v for k,v in SAMPLE.items() if k!='category'}
            source.update(url='https://x.com/i/article/0',event_id='real-codex-test-fixture',completeness='page_text',capture_method='manual')
            aid=client.post('/api/browser/capture',headers=headers,json=source).json()['id']
            app.state.service.process(aid)
            article=client.get('/api/articles/'+aid).json()
            report['article']=article
            assert article['status']=='ready',article['ai_error']
            assert article['category']!='其他知识' and article['analysis_model'].startswith('Codex CLI')
            assert article['analysis']['knowledge'][0]['steps']
            for mode in ('quick','standard','deep','knowledge'):
                for item in article['analysis'][mode]:
                    for evidence in item['evidence']:
                        assert article['content'][evidence['start_offset']:evidence['end_offset']]==evidence['quote']
            answer=client.post('/api/chat',json={'question':'根据收藏，检索资料回答客户咨询的执行流程和限制是什么？'}).json()
            report['answer']=answer
            assert answer['mode']=='ai' and answer['claims'] and not answer['insufficient']
            assert all(e['article_id']==aid for claim in answer['claims'] for e in claim['evidence'])
            summary=client.get('/api/summary').json()
            assert summary['status']['learned']==1 and summary['categories'][0]['count']==1
            assert summary['browser']['captured_total']==1
        reopened=create_app(settings,start_worker=False)
        assert reopened.state.service.db.article(aid)['analysis']==article['analysis']
        report['passed']=True
    finally:
        report['finished_at']=time.time()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
