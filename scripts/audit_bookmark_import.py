"""Audit a real browser import against saved source text and citation offsets."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xsecondbrain.config import Settings


def audit(folder):
    settings = Settings.from_env()
    sources = json.loads((folder / 'sources.json').read_text(encoding='utf-8'))
    results = json.loads((folder / 'results.json').read_text(encoding='utf-8'))
    if isinstance(results, dict):
        results = results['results']
    assert len(sources) == len(results), 'Import result count does not match sources'
    headers = {'Authorization': f'Bearer {settings.app_token}'} if settings.app_token else {}
    report = {'checked_at': datetime.now(timezone.utc).isoformat(),
              'source_count': len(sources), 'source_chars': sum(len(s['content']) for s in sources),
              'exact_saved': 0, 'verified_quotes': 0, 'articles': []}
    with httpx.Client(base_url=f'http://127.0.0.1:{settings.port}', headers=headers,
                      trust_env=False, timeout=30) as client:
        for source, result in zip(sources, results):
            response = client.get('/api/articles/' + result['id'])
            response.raise_for_status()
            article = response.json()
            assert article['content'] == source['content'].strip(), f"Source changed: {article['id']}"
            for field in ('title', 'author', 'published_at'):
                assert article[field] == source[field].strip(), f"Metadata changed: {article['id']} {field}"
            report['exact_saved'] += 1
            quotes = 0
            if article['analysis']:
                for mode in ('quick', 'standard', 'deep', 'knowledge'):
                    for point in article['analysis'][mode]:
                        for evidence in point['evidence']:
                            assert evidence['article_id'] == article['id']
                            assert article['content'][evidence['start_offset']:evidence['end_offset']] == evidence['quote']
                            quotes += 1
            report['verified_quotes'] += quotes
            report['articles'].append({key: article[key] for key in
                ('id', 'title', 'url', 'status', 'category', 'tags', 'ai_error', 'embedding_error')})
        report['status'] = dict(Counter(a['status'] for a in report['articles']))
        report['categories'] = dict(Counter(a['category'] for a in report['articles'] if a['status'] == 'ready'))
    (folder / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    result = audit(parser.parse_args().folder)
    print(json.dumps({k: v for k, v in result.items() if k != 'articles'}, ensure_ascii=False, indent=2))
