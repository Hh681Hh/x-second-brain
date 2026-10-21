"""Opt-in real model tests. No fabricated/model-stub responses are accepted here."""
import json
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from xsecondbrain.config import ROOT, Settings
from xsecondbrain.main import create_app
from xsecondbrain.providers import Embeddings
from .conftest import SAMPLE, SECOND


@pytest.mark.integration
def test_real_public_page_extraction(tmp_path):
    if os.getenv('XSB_RUN_NETWORK') != '1':
        pytest.skip('Set XSB_RUN_NETWORK=1 for a public Internet extraction test.')
    app = create_app(Settings(data_dir=tmp_path,embedding_provider='none',fetch_allow_benchmark_proxy=os.getenv('XSB_TEST_ALLOW_BENCHMARK_PROXY')=='1'),start_worker=False)
    with TestClient(app) as client:
        aid = client.post('/api/articles',json={'url':'https://example.com'}).json()['id']
        app.state.service.process(aid)
        article = client.get('/api/articles/'+aid).json()
        assert article['status'] == 'saved', article['ai_error']
        assert len(article['content']) >= 40
        assert article['url'] == 'https://example.com/'


@pytest.mark.integration
def test_real_semantic_paraphrase(tmp_path):
    if os.getenv('XSB_RUN_SEMANTIC') != '1':
        pytest.skip('Set XSB_RUN_SEMANTIC=1 to download/use the actual BGE model.')
    settings = Settings(data_dir=tmp_path,embedding_provider='local')
    app = create_app(settings,start_worker=False)
    service = app.state.service
    service.embeddings = Embeddings(Settings(data_dir=ROOT/'data',embedding_provider='local'))
    service.search.embeddings = service.embeddings
    with TestClient(app) as client:
        aid = client.post('/api/articles',json=SAMPLE).json()['id']
        service.process(aid)
        result = client.get('/api/search',params={'q':'售后机器人怎样减轻接线员的负担？'}).json()
        assert result['hits'] and result['hits'][0]['article_id'] == aid
        assert 'semantic' in result['hits'][0]['matched_by']
        assert service.db.article(aid)['embedding_error'] == ''
        print(json.dumps({'real_semantic':result},ensure_ascii=False),flush=True)


@pytest.mark.integration
def test_real_llm_end_to_end(tmp_path):
    url = os.getenv('XSB_TEST_LLM_URL')
    if not url:
        pytest.skip('Set XSB_TEST_LLM_URL, XSB_TEST_LLM_MODEL and XSB_TEST_LLM_KEY for a real provider.')
    settings = Settings(data_dir=tmp_path,llm_base_url=url,llm_model=os.environ['XSB_TEST_LLM_MODEL'],llm_api_key=os.environ['XSB_TEST_LLM_KEY'],llm_timeout=600,llm_max_tokens=4000,llm_json_schema=os.getenv('XSB_TEST_JSON_SCHEMA')=='1',embedding_provider='local')
    app = create_app(settings,start_worker=False)
    service = app.state.service
    service.embeddings = Embeddings(Settings(data_dir=ROOT/'data',embedding_provider='local'))
    service.search.embeddings = service.embeddings
    report = {'model':settings.llm_model,'real_inference':True,'started_at':time.time(),'articles':[]}
    output = ROOT/'artifacts'/'real-model-test.json'
    output.parent.mkdir(exist_ok=True)
    try:
        with TestClient(app) as client:
            ids = []
            for item in (SAMPLE,SECOND):
                aid = client.post('/api/articles',json=item).json()['id']; ids.append(aid)
                print('Real LLM analysis starting:',aid,flush=True)
                service.process(aid)
                article = client.get('/api/articles/'+aid).json()
                report['articles'].append(article)
                if article['analysis'] is None:
                    report['rejected_model_output'] = service.llm.last_output
                output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                assert article['analysis'], article['ai_error']
                assert all(article['analysis'][mode] for mode in ('quick','standard','deep','knowledge'))
                assert len(''.join(p['text'] for p in article['analysis']['quick'])) >= 60
                assert any('检索' in c['method'] or '评估' in c['method'] for c in article['analysis']['knowledge'])
                assert any(any(step != '原文未说明' for step in card['steps']) for card in article['analysis']['knowledge'])
                for mode in ('quick','standard','deep','knowledge'):
                    for point in article['analysis'][mode]:
                        for e in point['evidence']:
                            assert article['content'][e['start_offset']:e['end_offset']] == e['quote']
            question = '我想给小生意做一个自动客服。根据历史收藏，给出实现和上线评估步骤，区分原文建议与补充判断，并引用两篇文章。'
            print('Real LLM cross-article answer starting',flush=True)
            res = client.post('/api/chat',json={'question':question,'limit':8})
            report['chat_status'] = res.status_code
            report['answer'] = res.json()
            assert res.status_code == 200, res.text
            answer = res.json()
            assert answer['mode'] == 'ai' and answer['claims'] and not answer['insufficient']
            assert {e['article_id'] for c in answer['claims'] for e in c['evidence']} == set(ids)
            assert {s['url'] for s in answer['sources']} >= {SAMPLE['url'],SECOND['url']}
            assert client.get('/api/sessions/'+answer['session_id']).status_code == 200
            no_answer = client.post('/api/chat',json={'question':'如何种植意大利番茄并防治叶霉病？'}).json()
            report['unrelated_answer'] = no_answer
            assert no_answer['insufficient'] and not no_answer['claims']
        reopened = create_app(settings,start_worker=False)
        assert reopened.state.service.db.article(ids[0])['analysis'] is not None
        report['passed'] = True
    finally:
        report['finished_at'] = time.time()
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
