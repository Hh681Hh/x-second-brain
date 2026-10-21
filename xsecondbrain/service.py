import hashlib
import json
import logging
import re
import sqlite3
import threading
from uuid import uuid4

from .collectors import collect
from .db import decode_article, dumps, now
from .knowledge import analyze_article, answer_question, split_chunks, tokenize
from .models import ArticleInput
from .search import Search
from .security import UserError, normalize_url

log = logging.getLogger(__name__)


def content_hash(text):
    return hashlib.sha256(re.sub(r'\s+', ' ', text).strip().encode('utf-8')).hexdigest() if text else None


class KnowledgeService:
    def __init__(self, db, settings, llm, embeddings):
        self.db, self.settings, self.llm, self.embeddings = db, settings, llm, embeddings
        self.search = Search(db, embeddings, settings)
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.thread = None
        self.threads = []

    def start(self):
        self.threads = [threading.Thread(target=self.work, name=f'knowledge-worker-{i}', daemon=True)
                        for i in range(self.settings.knowledge_workers)]
        self.thread = self.threads[0]
        for thread in self.threads:
            thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        for thread in self.threads:
            thread.join(timeout=2)

    def work(self):
        while not self.stop_event.is_set():
            article_id = None
            try:
                with self.db.connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    row = conn.execute("SELECT article_id FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone()
                    if row:
                        article_id = row[0]
                        conn.execute("UPDATE jobs SET state='running',updated_at=? WHERE article_id=?", (now(), article_id))
                if article_id:
                    self.process(article_id)
                    continue
            except Exception as exc:
                log.error('worker failed: article=%s error_type=%s', article_id, type(exc).__name__)
                if article_id:
                    with self.db.connect() as conn:
                        conn.execute("UPDATE articles SET status='error',ai_error=? WHERE id=?", ('处理过程中发生内部错误；原文已保留，请重试。', article_id))
                        conn.execute("UPDATE jobs SET state='failed',error=? WHERE article_id=?", ('internal_error', article_id))
            self.wake.wait(1)
            self.wake.clear()

    def _enqueue(self, conn, article_id):
        stamp = now()
        conn.execute("INSERT INTO jobs(article_id,state,created_at,updated_at) VALUES(?,'queued',?,?) ON CONFLICT(article_id) DO UPDATE SET state='queued',error='',updated_at=excluded.updated_at", (article_id, stamp, stamp))
        self.wake.set()

    def _index_text(self, conn, article):
        conn.execute('DELETE FROM chunks WHERE article_id=?', (article['id'],))
        chunks = split_chunks(article['id'], article['content'], article['revision'])
        for chunk in chunks:
            text = article['title'] + '\n' + chunk['text']
            conn.execute('INSERT INTO chunks(id,article_id,ordinal,start_offset,end_offset,text,search_text) VALUES(?,?,?,?,?,?,?)', (chunk['id'], article['id'], chunk['ordinal'], chunk['start_offset'], chunk['end_offset'], chunk['text'], text))
            conn.execute('INSERT INTO chunks_fts(chunk_id,tokens) VALUES(?,?)', (chunk['id'], ' '.join(tokenize(text))))
        return chunks

    def add(self, item: ArticleInput, enqueue=True):
        url = normalize_url(item.url)
        hashed = content_hash(item.content)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            existing = conn.execute('SELECT id,content,status FROM articles WHERE (url IS NOT NULL AND url=?) OR (content_hash IS NOT NULL AND content_hash=?)', (url, hashed)).fetchone()
            if existing:
                article_id = existing['id']
                if not item.content or (existing['content'] and existing['status']!='needs_content'):
                    return {"id": article_id, "duplicate": True, "message": "已在知识库中，未重复处理。"}
            else:
                article_id = str(uuid4())
                stamp = now()
                title = item.title.strip() or (item.content.splitlines()[0][:100] if item.content else "等待获取正文")
                conn.execute('INSERT INTO articles(id,url,title,author,published_at,saved_at,updated_at,content,content_hash,source_kind,status,category,tags_json,extraction_note) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (article_id, url, title, item.author.strip(), item.published_at, stamp, stamp, item.content, hashed, item.source_kind, 'queued', item.category or '其他知识', dumps(item.tags), '用户粘贴正文，完整性由用户确认。' if item.content else ''))
                if item.content:
                    self._index_text(conn, self._row(conn, article_id))
                if enqueue:
                    self._enqueue(conn, article_id)
                return {"id": article_id, "duplicate": False, "message": "已保存，正在处理。"}
        self.patch(article_id, {k: v for k, v in item.model_dump().items() if k in ('content', 'title', 'author', 'published_at') and v}, enqueue=enqueue)
        return {"id": article_id, "duplicate": False, "message": "已为已有链接补充正文。"}

    def _row(self, conn, article_id):
        row = conn.execute('SELECT * FROM articles WHERE id=?', (article_id,)).fetchone()
        if row is None:
            raise KeyError('收藏不存在。')
        return decode_article(dict(row))

    def patch(self, article_id, patch, enqueue=True):
        allowed = {'title', 'author', 'published_at', 'content', 'category', 'tags', 'is_read'}
        updates = {k: v for k, v in patch.items() if k in allowed and v is not None}
        reprocess = 'content' in updates or 'title' in updates
        try:
            with self.db.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                self._row(conn, article_id)
                if 'content' in updates:
                    updates['content'] = updates['content'].strip()
                    if len(updates['content']) < 20:
                        raise UserError('正文至少需要 20 个字符。')
                    updates['content_hash'] = content_hash(updates['content'])
                    updates['extraction_note'] = '用户提供或修订正文，完整性由用户确认。'
                if 'tags' in updates:
                    updates['tags_json'] = dumps(list(dict.fromkeys(t.strip()[:60] for t in updates.pop('tags') if t.strip())))
                updates['updated_at'] = now()
                if reprocess:
                    updates.update(status='queued', analysis_json=None, analysis_model=None, priority=None, ai_error='', embedding_error='')
                assignments = ','.join(k + '=?' for k in updates)
                conn.execute(f"UPDATE articles SET {assignments}{',revision=revision+1' if reprocess else ''} WHERE id=?", [*updates.values(), article_id])
                if reprocess:
                    self._index_text(conn, self._row(conn, article_id))
                    if enqueue:
                        self._enqueue(conn, article_id)
        except sqlite3.IntegrityError:
            raise UserError('该正文已在另一条收藏中，未产生重复记录。', 409) from None
        return self.db.article(article_id)

    def retry(self, article_id):
        with self.db.connect() as conn:
            self._row(conn, article_id)
            conn.execute("UPDATE articles SET status='queued',ai_error='',embedding_error='',revision=revision+1 WHERE id=?", (article_id,))
            self._enqueue(conn, article_id)
        return {"message": "已加入处理队列。"}

    def process(self, article_id):
        try:
            article = self.db.article(article_id)
        except KeyError:
            return
        revision = article['revision']
        partial_capture = article['extraction_note'].startswith('浏览器仅保存了预览')
        if partial_capture and self.settings.x_public_fulltext_provider != 'fxembed':
            self._finish(article_id, revision, 'needs_content', '请展开全文并通过插件补全，或手工提供正文。')
            return
        with self.db.connect() as conn:
            conn.execute("UPDATE articles SET status='processing' WHERE id=? AND revision=?", (article_id, revision))
        if partial_capture or not article['content']:
            try:
                if partial_capture:
                    from .public_fulltext import collect_public_fulltext
                    result = collect_public_fulltext(article['url'], enabled=True)
                else:
                    result = collect(article['url'], self.settings)
                with self.db.connect() as conn:
                    cursor = conn.execute("UPDATE articles SET content=?,content_hash=?,title=?,author=?,published_at=?,extraction_note=?,source_kind=?,updated_at=? WHERE id=? AND revision=?", (result.content, content_hash(result.content), result.title or article['title'], result.author or article['author'], result.published_at or article['published_at'], result.note, result.source_kind, now(), article_id, revision))
                    if not cursor.rowcount:
                        return
                    if partial_capture:
                        conn.execute("UPDATE browser_clips SET completeness='page_text' WHERE article_id=?", (article_id,))
                article = self.db.article(article_id)
            except (UserError, sqlite3.IntegrityError) as exc:
                message = str(exc) if isinstance(exc, UserError) else '该网页正文与另一条收藏相同；请查看已有收藏或手工补充。'
                self._finish(article_id, revision, 'needs_content', message)
                return
        # Re-index when content or revision changed; stable chunk ids allow safe retry of existing analyses.
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM articles WHERE id=? AND revision=?', (article_id, revision)).fetchone():
                return
            chunks = self._index_text(conn, article)
        analysis = article['analysis']
        ai_error = ''
        if self.settings.llm_enabled:
            try:
                analysis = analyze_article(self.llm, article, chunks, self.db.preferences())
            except UserError as exc:
                ai_error = str(exc)
                analysis = None
        else:
            # Existing validated analysis can survive a re-index without an LLM, but not an edit.
            if analysis and any(e['chunk_id'] not in {c['id'] for c in chunks} for mode in ('quick','standard','deep','knowledge') for point in analysis[mode] for e in point['evidence']):
                analysis = None
        augmented = {c['id']: article['title'] + '\n' + c['text'] for c in chunks}
        semantic_context = {c['id']: '' for c in chunks}
        if analysis:
            for card in analysis['knowledge']:
                enrichment = '\n问题：' + card['problem'] + '\n方法：' + card['method'] + '\n' + '；'.join(card['steps'])
                for evidence in card['evidence']:
                    if evidence['chunk_id'] in augmented:
                        augmented[evidence['chunk_id']] += enrichment
                        semantic_context[evidence['chunk_id']] += card['problem'][:25] + ' ' + card['method'][:25]
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT 1 FROM articles WHERE id=? AND revision=?', (article_id, revision)).fetchone():
                return
            for cid, text in augmented.items():
                conn.execute('UPDATE chunks SET search_text=? WHERE id=?', (text, cid))
                conn.execute('DELETE FROM chunks_fts WHERE chunk_id=?', (cid,))
                conn.execute('INSERT INTO chunks_fts(chunk_id,tokens) VALUES(?,?)', (cid, ' '.join(tokenize(text))))
        embedding_error = ''
        if self.settings.embedding_provider != 'none':
            try:
                # Keep source + a short problem-oriented hint inside the local model's
                # 512-token window; the complete method remains in the FTS index.
                vector_texts = [article['title'][:35]+'\n'+semantic_context[c['id']][:50]+'\n'+c['text'] for c in chunks]
                vectors = self.embeddings.encode(vector_texts)
                with self.db.connect() as conn:
                    conn.execute('BEGIN IMMEDIATE')
                    if not conn.execute('SELECT 1 FROM articles WHERE id=? AND revision=?', (article_id, revision)).fetchone():
                        return
                    for chunk, vector in zip(chunks, vectors):
                        conn.execute('UPDATE chunks SET embedding=?,embedding_model=? WHERE id=?', (vector.tobytes(), self.embeddings.signature, chunk['id']))
            except UserError as exc:
                embedding_error = str(exc)
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            current = conn.execute('SELECT revision FROM articles WHERE id=?', (article_id,)).fetchone()
            if current is None or current[0] != revision:
                return
            priority = sum(v['score'] for v in analysis['ratings'].values()) / 5 if analysis else None
            category = analysis['category'] if analysis and article['category'] == '其他知识' and analysis['category'] in self.db.preferences()['categories'] else article['category']
            tags = list(dict.fromkeys(article['tags'] + (analysis['tags'] if analysis else [])))[:20]
            conn.execute("UPDATE articles SET analysis_json=?,analysis_model=?,category=?,tags_json=?,priority=?,embedding_error=?,updated_at=? WHERE id=?", (dumps(analysis) if analysis else None, self.settings.model_label if analysis and self.settings.llm_enabled else article['analysis_model'], category, dumps(tags), priority, embedding_error, now(), article_id))
        self._finish(article_id, revision, 'ready' if analysis else 'error' if ai_error else 'saved', ai_error, embedding_error)

    def _finish(self, article_id, revision, status, error='', embedding_error=''):
        with self.db.connect() as conn:
            cursor = conn.execute('UPDATE articles SET status=?,ai_error=?,embedding_error=? WHERE id=? AND revision=?', (status, error, embedding_error, article_id, revision))
            if cursor.rowcount:
                conn.execute('UPDATE jobs SET state=?,error=?,updated_at=? WHERE article_id=?', ('failed' if error or embedding_error else 'done', error or embedding_error, now(), article_id))
        log.info('article processed: id=%s status=%s', article_id, status)

    def ask(self, question, session_id=None, limit=8):
        history = []
        if session_id:
            with self.db.connect() as conn:
                if not conn.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone():
                    raise KeyError('对话不存在，请新建对话。')
                rows = conn.execute('SELECT role,payload_json FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 4', (session_id,)).fetchall()
                for row in reversed(rows):
                    payload = json.loads(row['payload_json'])
                    history.append({"role": row['role'], "content": payload.get('question') or '；'.join(c['text'] for c in payload.get('claims', []))[:1200]})
        # Include the previous user question to resolve short follow-ups, without inventing an expansion.
        retrieval_question = question
        if history and len(question) < 50:
            previous = next((h['content'] for h in reversed(history) if h['role'] == 'user'), '')
            retrieval_question = previous + '\n' + question
        retrieved = self.search.query(retrieval_question, limit)
        hits = retrieved['hits']
        result = {"claims": [], "ai_suggestions": [], "disagreements": [], "gaps": [], "insufficient": True, "mode": 'no_evidence'}
        if hits and self.settings.llm_enabled:
            result.update(answer_question(self.llm, question, hits, history), mode='ai')
        elif hits:
            result.update(mode='retrieval_only', gaps=['未配置语言模型，以下仅显示真实检索片段，尚未生成综合建议。'])
        else:
            result['gaps'] = ['历史收藏中没有找到匹配的可靠依据。请补充相关资料或尝试更具体的问题。']
        result.update(sources=hits, warnings=retrieved['warnings'], retrieval_mode=retrieved['mode'], question=question, created_at=now(), session_id=session_id or str(uuid4()))
        with self.db.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO sessions(id,title,created_at) VALUES(?,?,?)', (result['session_id'], question[:70], now()))
            conn.execute('INSERT INTO messages(session_id,role,payload_json,created_at) VALUES(?,?,?,?)', (result['session_id'], 'user', dumps({"question": question}), now()))
            conn.execute('INSERT INTO messages(session_id,role,payload_json,created_at) VALUES(?,?,?,?)', (result['session_id'], 'assistant', dumps(result), now()))
        return result
