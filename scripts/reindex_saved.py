"""Rebuild search context from existing grounded analyses without new LLM calls."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xsecondbrain.config import Settings
from xsecondbrain.db import Database
from xsecondbrain.providers import Embeddings
from xsecondbrain.service import KnowledgeService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--article', help='Article ID with an existing grounded analysis')
    choice.add_argument('--all', action='store_true', help='All idle, already-analyzed articles')
    args = parser.parse_args()
    settings = replace(Settings.from_env(), llm_provider='api', llm_model='', llm_api_key='')
    db = Database(settings.data_dir / 'knowledge.sqlite3')
    with db.connect() as conn:
        rows = conn.execute("SELECT id FROM articles WHERE analysis_json IS NOT NULL AND status='ready'").fetchall()
        ids = [r[0] for r in rows if not args.article or r[0] == args.article]
    if args.article and not ids:
        raise SystemExit('The article must be ready and already analyzed. No data was changed.')
    service = KnowledgeService(db, settings, None, Embeddings(settings))
    for aid in ids:
        before = db.article(aid)
        service.process(aid)
        after = db.article(aid)
        if after['analysis'] != before['analysis'] or after['content'] != before['content']:
            raise SystemExit('Article changed concurrently; inspect it before continuing.')
        if after['embedding_error']:
            raise SystemExit(after['embedding_error'])
    print(json.dumps({'reindexed': len(ids), 'llm_calls': 0, 'originals_and_analysis_preserved': True}))


if __name__ == '__main__':
    main()
