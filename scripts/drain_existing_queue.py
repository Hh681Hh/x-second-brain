"""One temporary bulk reader alongside a running local service; exits when drained.

Uses the same SQLite atomic claim as the service. Never initializes the live DB
(initialization would recover and requeue another process's active jobs).
"""
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xsecondbrain.agent_cli import running
from xsecondbrain.config import Settings
from xsecondbrain.db import Database, now
from xsecondbrain.providers import LLM, Embeddings
from xsecondbrain.service import KnowledgeService


if __name__ == '__main__':
    settings = Settings.from_env()
    if not running(settings):
        raise SystemExit('Start the local service first.')
    logging.basicConfig(level=logging.INFO)
    db = Database(settings.data_dir / 'knowledge.sqlite3')
    service = KnowledgeService(db, settings, LLM(settings), Embeddings(settings))
    while True:
        with db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute("SELECT article_id FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
            if not row:
                break
            article_id = row[0]
            conn.execute("UPDATE jobs SET state='running',updated_at=? WHERE article_id=?", (now(), article_id))
        try:
            service.process(article_id)
        except Exception as error:
            logging.error('Bulk reader failed: article=%s type=%s', article_id, type(error).__name__)
            with db.connect() as conn:
                conn.execute("UPDATE articles SET status='error',ai_error=? WHERE id=?",
                             ('批量阅读出现内部错误，原文已保留。', article_id))
                conn.execute("UPDATE jobs SET state='failed',error=? WHERE article_id=?", ('bulk_reader_error', article_id))
    print('Temporary bulk reader finished.')
