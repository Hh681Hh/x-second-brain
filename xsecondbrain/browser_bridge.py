"""User-driven browser clipping. No calls to X, cookies, or private website APIs."""
import hashlib
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import Field
from typing import Literal

from .db import now
from .models import StrictModel, MAX_CONTENT
from .security import UserError, normalize_url
from .service import content_hash

EXTENSION_ID = re.compile(r'^[a-p]{32}$')
BRIDGE_PATHS = {'/api/browser/pair', '/api/browser/capture', '/api/browser/ping'}


class PairInput(StrictModel):
    code: str = Field(min_length=6, max_length=40)
    label: str = Field(default='浏览器插件', max_length=60)


class CaptureInput(StrictModel):
    event_id: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_-]+$')
    url: str = Field(max_length=2048)
    title: str = Field(default='', max_length=300)
    author: str = Field(default='', max_length=200)
    published_at: str = Field(default='', max_length=80)
    content: str = Field(default='', max_length=MAX_CONTENT)
    completeness: Literal['page_text', 'partial'] = 'partial'
    capture_method: Literal['bookmark', 'manual'] = 'bookmark'
    source_kind: Literal['article', 'thread', 'note'] = 'article'


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def extension_origin(headers):
    """A service worker may omit Origin; when present it must match its ID."""
    extension_id = headers.get('x-xsb-extension', '')
    origin = headers.get('origin', '')
    if not EXTENSION_ID.fullmatch(extension_id):
        raise UserError('需要有效的浏览器插件标识。', 403)
    if origin and origin != 'chrome-extension://' + extension_id:
        raise UserError('插件来源不匹配。', 403)
    return extension_id


class BrowserBridge:
    def __init__(self, service):
        self.service, self.db = service, service.db
        with self.db.connect() as conn:
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS browser_pair_code (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), code_hash TEXT NOT NULL,
                expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS browser_pairs (
                extension_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, label TEXT NOT NULL,
                created_at TEXT NOT NULL, last_seen TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS browser_clips (
                article_id TEXT PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
                extension_id TEXT NOT NULL, completeness TEXT NOT NULL, captured_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS browser_events (
                extension_id TEXT NOT NULL, event_id TEXT NOT NULL,
                article_id TEXT REFERENCES articles(id) ON DELETE SET NULL,
                PRIMARY KEY(extension_id,event_id));
            ''')

    def status(self):
        with self.db.connect() as conn:
            pairs = [dict(r) for r in conn.execute('SELECT extension_id,label,created_at,last_seen FROM browser_pairs ORDER BY created_at')]
            total = conn.execute('SELECT count(*) FROM browser_clips').fetchone()[0]
            partial = conn.execute("SELECT count(*) FROM browser_clips b JOIN articles a ON a.id=b.article_id WHERE a.status='needs_content'").fetchone()[0]
        return {'paired': bool(pairs), 'pairs': pairs, 'captured_total': total, 'needs_content': partial,
                'mode': 'user_driven_page_capture', 'account_sync': False,
                'public_fulltext_provider': self.service.settings.x_public_fulltext_provider}

    def issue_code(self):
        # 64 random bits, ten minutes, at most six guesses per locally issued code.
        code = secrets.token_hex(8).upper()
        with self.db.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO browser_pair_code VALUES(1,?,?,0)', (digest(code), time.time()+600))
        return {'code': code[:8]+'-'+code[8:], 'expires_in': 600}

    def pair(self, extension_id, item):
        token = secrets.token_urlsafe(32)
        error = False
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            code = conn.execute('SELECT * FROM browser_pair_code WHERE singleton=1').fetchone()
            candidate = item.code.replace('-', '').replace(' ', '').upper()
            if (not code or code['expires'] < time.time() or code['attempts'] >= 6
                    or not secrets.compare_digest(code['code_hash'], digest(candidate))):
                conn.execute('UPDATE browser_pair_code SET attempts=attempts+1 WHERE singleton=1')
                error = True
            else:
                stamp = now()
                conn.execute('INSERT OR REPLACE INTO browser_pairs VALUES(?,?,?,?,?)',
                             (extension_id, digest(token), item.label.strip() or '浏览器插件', stamp, stamp))
                conn.execute('DELETE FROM browser_pair_code')
        # Raise after commit: failed guesses must survive the transaction.
        if error:
            raise UserError('配对码无效、已使用或过期，请在本地连接页重新生成。', 403)
        return {'token': token, 'message': '插件已连接本地知识库。'}

    def authenticate(self, headers):
        extension_id = extension_origin(headers)
        token = headers.get('authorization', '').removeprefix('Bearer ')
        with self.db.connect() as conn:
            row = conn.execute('SELECT token_hash FROM browser_pairs WHERE extension_id=?', (extension_id,)).fetchone()
            if not row or not secrets.compare_digest(row[0], digest(token)):
                raise UserError('插件连接已失效，请重新配对；待发送内容仍保留在浏览器。', 401)
            conn.execute('UPDATE browser_pairs SET last_seen=? WHERE extension_id=?', (now(), extension_id))
        return extension_id

    def revoke(self):
        with self.db.connect() as conn:
            conn.execute('DELETE FROM browser_pairs')
            conn.execute('DELETE FROM browser_pair_code')
        return {'message': '已断开所有浏览器插件，原文和知识保留。'}

    def ping(self, extension_id):
        with self.db.connect() as conn:
            rows = conn.execute('SELECT a.status,count(*) AS count FROM browser_clips b JOIN articles a ON a.id=b.article_id WHERE b.extension_id=? GROUP BY a.status', (extension_id,))
            counts = {r['status']: r['count'] for r in rows}
            error = conn.execute("SELECT a.ai_error FROM browser_clips b JOIN articles a ON a.id=b.article_id WHERE b.extension_id=? AND a.status='error' ORDER BY a.updated_at DESC LIMIT 1",(extension_id,)).fetchone()
        return {'connected': True, 'received': sum(counts.values()), 'needs_content': counts.get('needs_content', 0),
                'learned': counts.get('ready', 0), 'failed': counts.get('error', 0),
                'reader_enabled':self.service.settings.llm_enabled,'reader_error':error[0] if error else '',
                'queued': counts.get('queued', 0)+counts.get('processing', 0)}

    def capture(self, extension_id, item):
        parts = urlsplit(item.url)
        if (parts.scheme != 'https' or parts.hostname not in ('x.com','www.x.com','twitter.com','www.twitter.com')
                or not re.fullmatch(r'/(?:[A-Za-z0-9_]+/status/\d+|i/(?:web/)?status/\d+|i/article/\d+)/?', parts.path)):
            raise UserError('插件只接收 X 帖子或 Article 的原文链接。')
        url = normalize_url(item.url)
        text = item.content.strip()
        if len(text) < 20:
            text = ''
        partial = item.completeness == 'partial' or not text
        resolve_public = partial and self.service.settings.x_public_fulltext_provider == 'fxembed'
        stamp = now()
        note = ('浏览器仅保存了预览或不完整片段，尚未生成文章分析；请展开全文后点击插件的“保存当前内容”。'
                if partial else '浏览器保存的已加载正文；未自动展开、翻页或读取整条帖子串，完整性和事实仍需核对。')
        # One transaction handles offline retries, duplicate URLs, upgrades and job creation.
        try:
            with self.db.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                previous = conn.execute('SELECT article_id FROM browser_events WHERE extension_id=? AND event_id=?', (extension_id,item.event_id)).fetchone()
                if previous:
                    return {'id': previous[0], 'duplicate': True, 'message': '此条已接收。'}
                hashed = content_hash(text)
                row = conn.execute('SELECT * FROM articles WHERE url=? OR (content_hash IS NOT NULL AND content_hash=?)', (url,hashed)).fetchone()
                duplicate = bool(row)
                aid = row['id'] if row else str(uuid4())
                clip = conn.execute('SELECT extension_id FROM browser_clips WHERE article_id=?',(aid,)).fetchone()
                extended_page = (row and clip and clip[0]==extension_id and item.capture_method=='manual'
                                 and row['extraction_note'].startswith('浏览器保存的已加载正文') and len(text)>len(row['content']))
                upgrade = row and not partial and (not row['content'] or row['status']=='needs_content' or row['extraction_note'].startswith('浏览器仅保存了预览') or extended_page)
                if not row:
                    status = 'needs_content' if partial and not resolve_public else 'queued'
                    conn.execute('INSERT INTO articles(id,url,title,author,published_at,saved_at,updated_at,content,content_hash,source_kind,status,extraction_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                                 (aid,url,item.title.strip() or (text.splitlines()[0][:100] if text else '待补全的 X 收藏'),item.author,item.published_at,stamp,stamp,text,hashed,item.source_kind,status,note))
                elif upgrade:
                    duplicate = False
                    conn.execute("UPDATE articles SET content=?,content_hash=?,title=?,author=?,published_at=?,status='queued',extraction_note=?,analysis_json=NULL,analysis_model=NULL,priority=NULL,ai_error='',embedding_error='',revision=revision+1,updated_at=? WHERE id=?",
                                 (text,hashed,item.title.strip() or row['title'],item.author or row['author'],item.published_at or row['published_at'],note,stamp,aid))
                # A later preview never overwrites an existing full capture or user-supplied body.
                if not row or upgrade:
                    conn.execute('INSERT OR REPLACE INTO browser_clips VALUES(?,?,?,?)', (aid,extension_id,'partial' if partial else 'page_text',stamp))
                    if text:
                        self.service._index_text(conn,self.service._row(conn,aid))
                    if not partial or resolve_public:
                        self.service._enqueue(conn,aid)
                conn.execute('INSERT INTO browser_events VALUES(?,?,?)', (extension_id,item.event_id,aid))
                actual = conn.execute('SELECT status FROM articles WHERE id=?', (aid,)).fetchone()[0]
                return {'id': aid, 'duplicate': duplicate, 'needs_content': actual=='needs_content',
                        'message': '已在知识库中，未重复处理。' if duplicate else '已保存链接，后台正在通过已启用的公开接口获取全文。' if resolve_public else '已保存预览，等待补全正文。' if partial else '已保存，后台将自动阅读分类。'}
        except sqlite3.IntegrityError:
            raise UserError('内容与其他收藏重复，未覆盖已有原文。',409) from None
