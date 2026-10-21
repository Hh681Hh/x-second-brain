from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

DEFAULT_CATEGORIES = ["AI 工具与技术", "AI Agent", "商业模式", "获客与营销", "创业与副业", "编程与自动化", "投资与加密行业", "其他知识"]


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def init(self):
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("数据库版本较新，请升级应用。")
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY, url TEXT UNIQUE, title TEXT NOT NULL, author TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL DEFAULT '', saved_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '', content_hash TEXT UNIQUE, source_kind TEXT NOT NULL,
                status TEXT NOT NULL, extraction_note TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '其他知识', tags_json TEXT NOT NULL DEFAULT '[]',
                analysis_json TEXT, analysis_model TEXT, ai_error TEXT NOT NULL DEFAULT '',
                embedding_error TEXT NOT NULL DEFAULT '', is_read INTEGER NOT NULL DEFAULT 0,
                priority REAL, revision INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY, article_id TEXT NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
                ordinal INTEGER NOT NULL, start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
                text TEXT NOT NULL, search_text TEXT NOT NULL, embedding BLOB, embedding_model TEXT,
                UNIQUE(article_id, ordinal)
            );
            CREATE INDEX IF NOT EXISTS chunks_article ON chunks(article_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, tokens);
            CREATE TRIGGER IF NOT EXISTS chunks_delete AFTER DELETE ON chunks BEGIN
                DELETE FROM chunks_fts WHERE chunk_id = old.id;
            END;
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id TEXT NOT NULL UNIQUE REFERENCES articles(id) ON DELETE CASCADE,
                state TEXT NOT NULL DEFAULT 'queued', error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=1;
            """)
            conn.execute("INSERT OR IGNORE INTO preferences VALUES('categories',?)", (dumps(DEFAULT_CATEGORIES),))
            conn.execute("INSERT OR IGNORE INTO preferences VALUES('interests','\"\"')")
            conn.execute("UPDATE jobs SET state='queued' WHERE state='running'")
            conn.execute("UPDATE articles SET status='queued' WHERE status='processing'")

    def article(self, article_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        if not row:
            raise KeyError("收藏不存在，可能已被删除。")
        return decode_article(dict(row))

    def chunks(self, article_id):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute("SELECT id,article_id,ordinal,start_offset,end_offset,text FROM chunks WHERE article_id=? ORDER BY ordinal", (article_id,))]

    def preferences(self):
        with self.connect() as conn:
            return {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT * FROM preferences")}


def decode_article(row):
    row["tags"] = json.loads(row.pop("tags_json"))
    row["analysis"] = json.loads(row.pop("analysis_json")) if row.get("analysis_json") else None
    row.pop("analysis_json", None)
    row["is_read"] = bool(row["is_read"])
    return row
