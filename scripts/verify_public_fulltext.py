"""Live optional test: public research sample -> clip -> FxEmbed -> real Codex.

Uses a separate database. Does not read or send personal bookmarks.
"""
from dataclasses import replace
import argparse
import json
from pathlib import Path
import sys
import tempfile

import httpx

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xsecondbrain.config import Settings
from xsecondbrain.main import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true', help='Allow public API access and real Codex usage')
    args = parser.parse_args()
    if not args.run_live:
        parser.error('Pass --run-live to allow network access and real Codex usage.')
    root = Path(__file__).resolve().parents[1]
    parent = root / 'data/public-fulltext-verification'
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='run-', dir=parent))
    # Independent public research sample, never a personal bookmark lookup.
    response = httpx.get('https://api.fxtwitter.com/2/status/2112586533610156368',
                         timeout=30, trust_env=False, follow_redirects=False)
    response.raise_for_status()
    sample = response.json()['status']
    settings = replace(Settings.from_env(), data_dir=folder / 'isolated-library',
                       x_public_fulltext_provider='fxembed', llm_provider='codex',
                       embedding_provider='none', app_token='', llm_timeout=600)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        extension = 'c' * 32
        headers = {'X-XSB-Extension': extension, 'Origin': 'chrome-extension://' + extension}
        code = client.post('/api/browser/pair-code').json()['code']
        paired = client.post('/api/browser/pair', headers=headers, json={'code':code})
        paired.raise_for_status()
        headers['Authorization'] = 'Bearer ' + paired.json()['token']
        saved = client.post('/api/browser/capture', headers=headers, json={
            'event_id':'public-research-sample-2112586533610156368', 'url':sample['url'],
            'title':sample['article']['title'], 'content':sample['article']['preview_text'],
            'completeness':'partial', 'capture_method':'bookmark', 'source_kind':'article'})
        saved.raise_for_status()
        aid = saved.json()['id']
        print('Public research preview accepted; resolving and running real Codex...', flush=True)
        app.state.service.process(aid)
        article = client.get('/api/articles/'+aid).json()
        (folder/'live-pipeline-article.json').write_text(json.dumps(article,ensure_ascii=False,indent=2),encoding='utf-8')
        quotes = 0
        if article['analysis']:
            for mode in ('quick','standard','deep','knowledge'):
                for point in article['analysis'][mode]:
                    for e in point['evidence']:
                        assert article['content'][e['start_offset']:e['end_offset']] == e['quote']
                        assert e['article_id'] == aid
                        quotes += 1
        report = {k:article[k] for k in ('url','title','status','category','analysis_model','ai_error')}
        report.update(content_chars=len(article['content']),preview_chars=len(sample['article']['preview_text']),
                      verified_quotes=quotes,personal_bookmarks_sent=False,native_browser_click_tested=False,
                      real_model_run=True,main_library_changed=False)
        (folder/'live-pipeline-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False,indent=2))
        print('Isolated report: ' + str(folder / 'live-pipeline-report.json'))
        assert article['status']=='ready' and article['analysis'] and quotes


if __name__=='__main__': main()
