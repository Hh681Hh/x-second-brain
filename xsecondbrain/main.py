from contextlib import asynccontextmanager
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import io
import zipfile
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .db import Database, decode_article, dumps
from .models import ArticleInput, ArticlePatch, BatchInput, ChatInput, Preferences
from .providers import LLM, Embeddings
from .security import UserError
from .service import KnowledgeService
from .transfer import export_library, import_library
from .xsync import XSync, SyncConfig, SyncSwitch, CALLBACK_PATH, COOKIE
from .browser_bridge import BrowserBridge, PairInput, CaptureInput, BRIDGE_PATHS, extension_origin, EXTENSION_ID

STATIC = Path(__file__).parent / 'static'


def create_app(settings=None, start_worker=True):
    settings = settings or Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.data_dir / 'knowledge.sqlite3')
    db.init()
    service = KnowledgeService(db, settings, LLM(settings), Embeddings(settings))
    xsync = XSync(service)
    browser = BrowserBridge(service)

    @asynccontextmanager
    async def lifespan(app):
        if start_worker:
            service.start()
            xsync.start()
        yield
        xsync.stop()
        service.stop()

    app = FastAPI(title='X Second Brain', version='0.3.2', lifespan=lifespan, docs_url=None, openapi_url='/api/openapi.json', redoc_url=None)
    app.state.service = service
    app.state.settings = settings
    app.state.xsync = xsync
    app.state.browser = browser

    @app.middleware('http')
    async def boundaries(request: Request, call_next):
        # Bound the actual stream, not just the optional Content-Length header.
        limit = 12_000_000 if request.url.path == '/api/import' else 2_000_000
        if request.method in ('POST', 'PUT', 'PATCH'):
            try:
                length = int(request.headers.get('content-length') or '0')
            except ValueError:
                return JSONResponse({'detail': '请求长度格式不正确。'}, status_code=400)
            if length > limit:
                return JSONResponse({'detail': '请求过大，请拆分导入。'}, status_code=413)
            body = bytearray()
            async for piece in request.stream():
                body.extend(piece)
                if len(body) > limit:
                    return JSONResponse({'detail': '请求过大，请拆分导入。'}, status_code=413)
            request._body = bytes(body)
        bridge = request.url.path in BRIDGE_PATHS
        bridge_origin = request.headers.get('origin', '')
        if request.url.path.startswith('/api/'):
            host = request.url.hostname
            if settings.host in ('127.0.0.1', 'localhost', '::1') and host not in ('127.0.0.1', 'localhost', '::1', 'testserver'):
                return JSONResponse({'detail': '无效主机地址。'}, status_code=403)
            if bridge and settings.host not in ('127.0.0.1', 'localhost', '::1'):
                return JSONResponse({'detail': '浏览器接入仅用于本机后台。'},status_code=403)
            if bridge and request.method == 'OPTIONS':
                prefix = 'chrome-extension://'
                if not bridge_origin.startswith(prefix) or not EXTENSION_ID.fullmatch(bridge_origin[len(prefix):]):
                    return JSONResponse({'detail': '拒绝此来源。'},status_code=403)
                return Response(status_code=204,headers={'Access-Control-Allow-Origin':bridge_origin,
                    'Access-Control-Allow-Methods':'GET, POST, OPTIONS',
                    'Access-Control-Allow-Headers':'Authorization, Content-Type, X-XSB-Extension',
                    'Access-Control-Allow-Private-Network':'true','Vary':'Origin','Cache-Control':'no-store'})
            if settings.app_token and not bridge and request.url.path not in ('/api/docs', CALLBACK_PATH):
                value = request.headers.get('authorization', '').removeprefix('Bearer ')
                if not secrets.compare_digest(value, settings.app_token):
                    return JSONResponse({'detail': '需要访问令牌，请在页面连接设置中输入 APP_TOKEN。'}, status_code=401)
            # No CORS. Require same origin for browser writes; CLI requests have no Origin.
            origin = request.headers.get('origin')
            if origin and not bridge:
                parsed = urlsplit(origin)
                if parsed.netloc != request.headers.get('host') or parsed.scheme not in ('http', 'https'):
                    return JSONResponse({'detail': '拒绝跨站请求。'}, status_code=403)
            if bridge:
                try:
                    extension_origin(request.headers)
                except UserError as exc:
                    return JSONResponse({'detail':str(exc)},status_code=exc.status)
        response = await call_next(request)
        if bridge and bridge_origin:
            response.headers['Access-Control-Allow-Origin'] = bridge_origin
            response.headers['Vary'] = 'Origin'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        elif request.url.path in ('/', '/workbench', '/official-x') or request.url.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-cache'
        return response

    @app.exception_handler(UserError)
    async def handle_user_error(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=exc.status)

    @app.exception_handler(KeyError)
    async def handle_missing(request, exc):
        return JSONResponse({'detail': '记录不存在，可能已经删除。'}, status_code=404)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request, exc):
        errors = [{'field': '.'.join(str(p) for p in e['loc']), 'message': e['msg']} for e in exc.errors()]
        return JSONResponse({'detail': '输入格式不正确，请检查内容长度和必填项。', 'errors': errors}, status_code=422)

    @app.exception_handler(Exception)
    async def handle_internal(request, exc):
        logging.getLogger(__name__).error('request failed: path=%s error_type=%s', request.url.path, type(exc).__name__)
        return JSONResponse({'detail': '服务遇到内部错误，已保留数据。请查看日志中的错误类型并重试。'}, status_code=500)

    @app.get('/api/status')
    def status():
        with db.connect() as conn:
            total = conn.execute('SELECT count(*) FROM articles').fetchone()[0]
            learned = conn.execute('SELECT count(*) FROM articles WHERE analysis_json IS NOT NULL').fetchone()[0]
            unread = conn.execute('SELECT count(*) FROM articles WHERE is_read=0').fetchone()[0]
            indexed = conn.execute('SELECT count(DISTINCT article_id) FROM chunks WHERE embedding_model=?', (service.embeddings.signature,)).fetchone()[0]
            queued = conn.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]
            counts = dict(conn.execute('SELECT status,count(*) FROM articles GROUP BY status').fetchall())
            knowledge_cards = conn.execute("SELECT coalesce(sum(json_array_length(analysis_json,'$.knowledge')),0) FROM articles WHERE analysis_json IS NOT NULL").fetchone()[0]
            latest_updated_at = conn.execute("SELECT coalesce(max(updated_at),'') FROM articles").fetchone()[0]
        learning = {'knowledge_cards': knowledge_cards, 'needs_attention': sum(counts.get(key, 0) for key in ('needs_content','error','saved')),
                    'needs_content': counts.get('needs_content', 0), 'failed': counts.get('error', 0), 'saved': counts.get('saved', 0), 'latest_updated_at': latest_updated_at}
        sync = xsync.status()
        return {"total": total, "learned": learned, "unread": unread, "indexed": indexed, "queued": queued, **learning, "llm_enabled": settings.llm_enabled, "llm_model": settings.model_label if settings.llm_enabled else None, "llm_provider":settings.llm_provider,"headless":settings.headless,"pid":os.getpid(),"embedding_provider": settings.embedding_provider, "embedding_model": settings.embedding_model, "embedding_error": service.embeddings.error, "x_configured": bool(settings.x_bearer_token) or sync['connected'], "auth_required": bool(settings.app_token), "automatic_sync": sync['sync_enabled']}

    @app.get('/api/summary')
    def summary():
        with db.connect() as conn:
            categories=[dict(row) for row in conn.execute('SELECT category,count(*) AS count FROM articles GROUP BY category ORDER BY count DESC,category')]
        return {'status':status(),'categories':categories,'x_sync':xsync.status(),'browser':browser.status()}

    @app.get('/api/browser')
    def browser_status():
        return browser.status()

    @app.post('/api/browser/pair-code')
    def browser_code():
        return browser.issue_code()

    @app.delete('/api/browser/pairs')
    def browser_revoke():
        return browser.revoke()

    @app.post('/api/browser/pair')
    def browser_pair(request: Request, item: PairInput):
        return browser.pair(extension_origin(request.headers),item)

    @app.post('/api/browser/capture')
    def browser_capture(request: Request, item: CaptureInput):
        return browser.capture(browser.authenticate(request.headers),item)

    @app.get('/api/browser/ping')
    def browser_ping(request: Request):
        return browser.ping(browser.authenticate(request.headers))

    @app.get('/browser-extension.zip',include_in_schema=False)
    def browser_download():
        stream=io.BytesIO()
        root=Path(__file__).parent/'browser_extension'
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for source in sorted(root.glob('*')):
                if source.is_file(): archive.write(source,'x-bookmark-clipper/'+source.name)
        return Response(stream.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename="x-bookmark-clipper.zip"'})

    @app.get('/api/preferences')
    def preferences():
        return db.preferences()

    @app.put('/api/preferences')
    def update_preferences(item: Preferences):
        categories = list(dict.fromkeys(c.strip()[:80] for c in item.categories if c.strip()))
        if not categories:
            raise UserError('至少保留一个分类。')
        with db.connect() as conn:
            for key, value in {'categories': categories, 'interests': item.interests.strip()}.items():
                conn.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)', (key, dumps(value)))
        return db.preferences()

    @app.get('/api/articles')
    def list_articles(category: str = '', tag: str = '', sort: str = 'recent', unread: bool = False, attention: bool = False, limit: int = 100, offset: int = 0):
        clauses, params = [], []
        if category:
            clauses.append('category=?')
            params.append(category)
        if tag:
            clauses.append('EXISTS (SELECT 1 FROM json_each(articles.tags_json) WHERE value=?)')
            params.append(tag)
        if unread:
            clauses.append('is_read=0')
        if attention:
            clauses.append("status IN ('needs_content','error','saved')")
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        order = 'priority IS NULL,priority DESC,saved_at DESC' if sort == 'priority' else 'saved_at DESC'
        with db.connect() as conn:
            total = conn.execute('SELECT count(*) FROM articles' + where, params).fetchone()[0]
            rows = [decode_article(dict(r)) for r in conn.execute(f'SELECT * FROM articles{where} ORDER BY {order} LIMIT ? OFFSET ?', [*params, max(1, min(limit, 200)), max(0, offset)])]
        for row in rows:
            row['excerpt'] = row.pop('content')[:220]
            if row['analysis']:
                row['quick'] = row['analysis']['quick']
                row['ratings'] = row['analysis']['ratings']
            row.pop('analysis')
        return {"articles": rows, "total": total}

    @app.post('/api/articles', status_code=201)
    def add_article(item: ArticleInput):
        return service.add(item)

    @app.post('/api/articles/batch')
    def batch(item: BatchInput):
        results = []
        for entry in item.articles:
            try:
                results.append(service.add(entry))
            except UserError as exc:
                results.append({'url': entry.url, 'error': str(exc)})
        return {'results': results}

    @app.get('/api/articles/{article_id}')
    def get_article(article_id: str):
        return {**db.article(article_id), 'chunks': db.chunks(article_id)}

    @app.patch('/api/articles/{article_id}')
    def patch_article(article_id: str, item: ArticlePatch):
        return service.patch(article_id, item.model_dump(exclude_unset=True))

    @app.delete('/api/articles/{article_id}')
    def delete_article(article_id: str):
        with db.connect() as conn:
            cursor = conn.execute('DELETE FROM articles WHERE id=?', (article_id,))
            if not cursor.rowcount:
                raise KeyError(article_id)
        return {'message': '已删除收藏及其索引。历史对话保留当时的引用快照。'}

    @app.post('/api/articles/{article_id}/process')
    def process_article(article_id: str):
        return service.retry(article_id)

    @app.get('/api/search')
    def search(q: str, limit: int = 8, category: str = '', unread: bool = False):
        if not 2 <= len(q.strip()) <= 2000:
            raise UserError('请输入 2–2000 字的问题或关键词。')
        return service.search.query(q.strip(), max(1, min(limit, 20)), category or None, unread=unread)

    @app.get('/api/articles/{article_id}/related')
    def related(article_id: str):
        article = db.article(article_id)
        question = article['title']
        if article['analysis']:
            question += ' ' + ' '.join(c['problem'] for c in article['analysis']['knowledge'])
        else:
            question += ' ' + article['content'][:400]
        result = service.search.query(question, 5, exclude_article=article_id)
        result['note'] = '以下是相关性候选；相似度不能证明观点一致、互补或矛盾。'
        return result

    @app.post('/api/chat')
    def chat(item: ChatInput):
        return service.ask(item.question.strip(), item.session_id, item.limit)

    @app.get('/api/sessions')
    def sessions():
        with db.connect() as conn:
            return {'sessions': [dict(r) for r in conn.execute('SELECT * FROM sessions ORDER BY created_at DESC LIMIT 100')]}

    @app.get('/api/sessions/{session_id}')
    def session_messages(session_id: str):
        with db.connect() as conn:
            if not conn.execute('SELECT 1 FROM sessions WHERE id=?', (session_id,)).fetchone():
                raise KeyError(session_id)
            return {'messages': [{'id': r['id'], 'role': r['role'], 'payload': json.loads(r['payload_json']), 'created_at': r['created_at']} for r in conn.execute('SELECT * FROM messages WHERE session_id=? ORDER BY id', (session_id,))]}

    @app.get('/api/export')
    def export():
        return JSONResponse(export_library(db), headers={'Content-Disposition': 'attachment; filename="x-second-brain-backup.json"'})

    @app.post('/api/import')
    def import_backup(payload: dict):
        try:
            return import_library(service, payload)
        except ValueError:
            raise UserError('备份内容格式不正确，正文验证未通过。') from None

    @app.post('/api/reindex')
    def reindex():
        with db.connect() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM articles WHERE length(content)>0 AND status NOT IN ('processing','queued')")]
            for article_id in ids:
                # Reindex keeps original chunks/analysis and does not change revision.
                conn.execute("UPDATE articles SET status='queued' WHERE id=?", (article_id,))
                service._enqueue(conn, article_id)
        return {'queued': len(ids), 'message': '已加入处理队列；开启 LLM 时会重新分析，可能产生模型费用。'}

    @app.get('/api/integrations/x')
    def x_integration():
        return xsync.status()

    @app.put('/api/integrations/x/config')
    def x_config(item: SyncConfig):
        return xsync.configure(item)

    @app.post('/api/integrations/x/authorize')
    def x_authorize(request: Request):
        target = urlsplit(xsync.redirect_uri)
        if request.url.netloc != target.netloc or request.url.scheme != target.scheme:
            raise UserError('请从注册回调地址的同一域名打开知识库：'+target.scheme+'://'+target.netloc)
        url, nonce = xsync.authorize()
        response = JSONResponse({'authorization_url': url})
        response.set_cookie(COOKIE, nonce, max_age=600, httponly=True, secure=target.scheme=='https',
                            samesite='lax', path='/api/integrations/x')
        return response

    @app.get(CALLBACK_PATH, include_in_schema=False)
    def x_callback(request: Request, state: str='', code: str='', error: str=''):
        xsync.callback(state, code, request.cookies.get(COOKIE, ''), error)
        response = RedirectResponse('/official-x#sync' if settings.headless else '/#sync', status_code=303)
        response.delete_cookie(COOKIE, path='/api/integrations/x')
        return response

    @app.post('/api/integrations/x/switch')
    def x_switch(item: SyncSwitch):
        return xsync.switch(item.enabled, item.acknowledge_api_cost)

    @app.post('/api/integrations/x/sync')
    def x_sync():
        return {'result': xsync.sync_once(), 'status': xsync.status()}

    @app.post('/api/integrations/x/disconnect')
    def x_disconnect():
        return xsync.disconnect()

    @app.get('/')
    def home():
        return FileResponse(STATIC / ('connect.html' if settings.headless else 'index.html'))

    @app.get('/official-x',include_in_schema=False)
    def optional_official_connection():
        return FileResponse(STATIC / 'official-x.html')

    @app.get('/workbench', include_in_schema=False)
    def optional_workbench():
        return FileResponse(STATIC / 'index.html')

    @app.get('/api/docs', include_in_schema=False)
    def api_docs():
        return FileResponse(STATIC / 'api-docs.html')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app


def run():
    import uvicorn
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(settings.data_dir / 'app.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO'), handlers=[handler, logging.StreamHandler()])
    # HTTP client libraries can log full URL query strings; suppress them for saved-link privacy.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == '__main__':
    run()
