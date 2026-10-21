"""Read-only official X OAuth + bounded, resumable bookmark polling.

No browser cookies/passwords or unofficial endpoints. Transport injection exists only
for deterministic protocol tests; production always calls api.x.com over TLS.
"""
import base64
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit

import httpx
from pydantic import BaseModel, Field

from .collectors import post_text
from .db import dumps, now
from .models import ArticleInput, MAX_CONTENT
from .secret_store import SecretStore
from .security import UserError

SCOPES = ['tweet.read', 'users.read', 'bookmark.read', 'offline.access']
CALLBACK_PATH = '/api/integrations/x/callback'
COOKIE = 'xsb-oauth-flow'
log = logging.getLogger(__name__)


class SyncConfig(BaseModel):
    client_id: str = Field(default='', max_length=250, pattern=r'^[A-Za-z0-9_.:=+/-]*$')
    interval_minutes: int = Field(default=10, ge=5, le=1440)
    page_size: int = Field(default=20, ge=5, le=100)
    max_pages: int = Field(default=3, ge=2, le=10)
    long_only: bool = True


class SyncSwitch(BaseModel):
    enabled: bool
    acknowledge_api_cost: bool = False


class XAPIError(UserError):
    def __init__(self, message, status=502, retry_after=0, fatal=False):
        super().__init__(message, status)
        self.retry_after, self.fatal = retry_after, fatal


class XSync:
    def __init__(self, service, transport=None, clock=time.time):
        self.service, self.db, self.settings = service, service.db, service.settings
        self.store = SecretStore(self.settings.data_dir)
        self.transport, self.clock = transport, clock
        self.lock = threading.Lock()
        self.stop_event, self.wake = threading.Event(), threading.Event()
        self.thread = None
        with self.db.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS x_sync_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS x_sync_seen (
                    user_id TEXT NOT NULL, post_id TEXT NOT NULL, outcome TEXT NOT NULL,
                    article_id TEXT, discovered_at TEXT NOT NULL, PRIMARY KEY(user_id,post_id)
                );
            ''')
            initial = {**SyncConfig(client_id=self.settings.x_client_id).model_dump(), 'enabled': False,
                       'last_checked_at': '', 'last_success_at': '', 'last_error': '', 'next_run': 0,
                       'cursor': None, 'failures': 0, 'last_result': {}, 'auth_error': False}
            conn.execute('INSERT OR IGNORE INTO x_sync_state VALUES(1,?)', (dumps(initial),))

    def _state(self):
        with self.db.connect() as conn:
            return json.loads(conn.execute('SELECT payload FROM x_sync_state WHERE id=1').fetchone()[0])

    def _update(self, **values):
        with self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            data = json.loads(conn.execute('SELECT payload FROM x_sync_state WHERE id=1').fetchone()[0])
            data.update(values)
            conn.execute('UPDATE x_sync_state SET payload=? WHERE id=1', (dumps(data),))
        return data

    @property
    def redirect_uri(self):
        value = self.settings.x_redirect_uri or f'http://127.0.0.1:{self.settings.port}{CALLBACK_PATH}'
        parsed = urlsplit(value)
        if (parsed.path != CALLBACK_PATH or parsed.query or parsed.fragment or parsed.username or parsed.password
                or not parsed.netloc or (parsed.scheme != 'https' and not
                (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')))):
            raise UserError('X_REDIRECT_URI 必须是 HTTPS 或本机 HTTP 地址，且路径为 ' + CALLBACK_PATH)
        return value

    def status(self):
        data = self._state()
        storage_error = ''
        try:
            credentials = self.store.read('x-credentials.bin')
        except UserError as exc:
            credentials, storage_error = None, str(exc)
        connected = bool(credentials and credentials.get('access_token') and not data['auth_error'])
        with self.db.connect() as conn:
            count = conn.execute("SELECT count(*) FROM x_sync_seen WHERE outcome IN ('imported','needs_content')").fetchone()[0]
        return {**{key: data[key] for key in SyncConfig.model_fields},
                'client_configured': bool(data['client_id']), 'connected': connected,
                'sync_enabled': connected and data['enabled'], 'paused': not data['enabled'],
                'running': self.lock.locked(), 'account': credentials.get('account') if credentials else None,
                'last_checked_at': data['last_checked_at'], 'last_success_at': data['last_success_at'],
                'last_error': storage_error or data['last_error'], 'last_result': data['last_result'],
                'next_run': data['next_run'] if connected and data['enabled'] else None,
                'catching_up': bool(data['cursor']), 'imported_total': count,
                'redirect_uri': self.redirect_uri, 'required_scopes': SCOPES,
                'post_lookup_configured': bool(self.settings.x_bearer_token),
                'documentation': 'https://docs.x.com/x-api/posts/bookmarks/introduction'}

    def configure(self, config: SyncConfig):
        with self.lock:
            old = self._state()
            if old['client_id'] != config.client_id:
                self.store.delete('x-credentials.bin')
                self.store.delete('x-oauth-pending.bin')
                self._update(enabled=False, cursor=None, auth_error=False)
            if old['long_only'] and not config.long_only:
                with self.db.connect() as conn:
                    conn.execute("DELETE FROM x_sync_seen WHERE outcome='skipped'")
                self._update(cursor=None)
            self._update(**config.model_dump())
        self.wake.set()
        return self.status()

    def authorize(self):
        with self.lock:
            data = self._state()
            if not data['client_id']:
                raise UserError('请先填写 X 开发者应用的 OAuth 2.0 Client ID。')
            self._update(enabled=False)
            nonce, verifier, browser_nonce = (secrets.token_urlsafe(32) for _ in range(3))
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            self.store.write('x-oauth-pending.bin', {'state': nonce, 'verifier': verifier,
                             'browser_hash': hashlib.sha256(browser_nonce.encode()).hexdigest(),
                             'created_at': self.clock(), 'client_id': data['client_id'],
                             'redirect_uri': self.redirect_uri})
            query = urlencode({'response_type': 'code', 'client_id': data['client_id'],
                               'redirect_uri': self.redirect_uri, 'scope': ' '.join(SCOPES),
                               'state': nonce, 'code_challenge': challenge, 'code_challenge_method': 'S256'})
            return 'https://x.com/i/oauth2/authorize?' + query, browser_nonce

    def _client(self):
        return httpx.Client(timeout=25, follow_redirects=False, transport=self.transport)

    def _request(self, client, method, path, **kwargs):
        try:
            response = client.request(method, 'https://api.x.com/2/' + path, **kwargs)
        except httpx.HTTPError:
            raise XAPIError('X 官方接口连接失败，已保留同步位置，将稍后重试。') from None
        if not 200 <= response.status_code < 300:
            explanations = {400: '请求字段或分页令牌未被接受，请检查接口权限并重试',
                            401: 'X 授权已失效，请重新连接账号', 402: 'X API 额度不足，请在官方控制台检查',
                            403: 'X 应用权限或账号访问受限，请检查官方应用设置',
                            429: 'X 接口限流，后台将退避后重试'}
            retry = 0
            if response.status_code == 429:
                try:
                    retry = max(float(response.headers.get('retry-after', 0)),
                                float(response.headers.get('x-rate-limit-reset', 0)) - self.clock(), 60)
                except ValueError:
                    retry = 900
            # Never expose upstream response bodies: they can contain tokens or private text.
            raise XAPIError(explanations.get(response.status_code, f'X 接口暂不可用（HTTP {response.status_code}）'),
                            response.status_code if response.status_code in (400,401,402,403,429) else 502,
                            min(retry, 86400), response.status_code in (401,402,403))
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except ValueError:
            raise XAPIError('X 官方接口返回了无效数据，同步位置已保留。') from None

    def _token_request(self, client, data):
        data = {'client_id': self._state()['client_id'], **data}
        auth = httpx.BasicAuth(data['client_id'], self.settings.x_client_secret) if self.settings.x_client_secret else None
        payload = self._request(client, 'POST', 'oauth2/token', data=data, auth=auth)
        if not isinstance(payload.get('access_token'), str) or not payload['access_token']:
            raise XAPIError('X 授权返回缺少访问令牌，请重新授权。')
        if payload.get('token_type', 'bearer').lower() != 'bearer':
            raise XAPIError('X 返回的令牌类型不受支持。')
        try:
            payload['expires_at'] = self.clock() + max(1, int(payload.get('expires_in', 7200)))
        except (ValueError, TypeError):
            raise XAPIError('X 授权返回的有效期无效。') from None
        return payload

    def callback(self, state, code, browser_nonce, error=''):
        with self.lock:
            pending = self.store.read('x-oauth-pending.bin')
            if (not pending or not state or not browser_nonce or self.clock()-pending['created_at'] > 600
                    or not secrets.compare_digest(pending['state'].encode(), state.encode())
                    or not secrets.compare_digest(pending['browser_hash'], hashlib.sha256(browser_nonce.encode()).hexdigest())):
                raise UserError('X 授权校验失败或已过期。请从本机知识库重新点击连接 X。', 400)
            self.store.delete('x-oauth-pending.bin')  # One-use code flow, including denied authorization.
            if error:
                self._update(last_error='你取消了 X 授权，账号尚未连接。')
                return False
            if not code or len(code) > 4096 or pending['client_id'] != self._state()['client_id']:
                raise UserError('X 授权信息不完整，请重新连接。')
            with self._client() as client:
                token = self._token_request(client, {'grant_type': 'authorization_code', 'code': code,
                                                     'redirect_uri': pending['redirect_uri'], 'code_verifier': pending['verifier']})
                scopes = set(token.get('scope', '').split())
                if not set(SCOPES).issubset(scopes) or not token.get('refresh_token'):
                    raise UserError('X 授权未包含读取收藏和后台续期权限，请重新授权。')
                profile = self._request(client, 'GET', 'users/me', headers={'Authorization': 'Bearer '+token['access_token']})
                account = profile.get('data') or {}
                if not re.fullmatch(r'\d{1,25}', str(account.get('id', ''))):
                    raise XAPIError('X 未返回有效的当前用户，未保存连接。')
                token['account'] = {key: str(account.get(key, ''))[:200] for key in ('id','name','username')}
                self.store.write('x-credentials.bin', token)
            # Connecting never starts billable polling; the user explicitly enables it afterwards.
            self._update(enabled=False, auth_error=False, last_error='', next_run=0, cursor=None, failures=0)
        return True

    def _credentials(self, client):
        token = self.store.read('x-credentials.bin')
        if not token:
            raise UserError('尚未连接 X 账号。请先完成官方授权。', 409)
        if token.get('expires_at', 0) <= self.clock() + 90:
            if not token.get('refresh_token'):
                raise XAPIError('X 授权已过期，请重新连接。', 401, fatal=True)
            refreshed = self._token_request(client, {'grant_type': 'refresh_token', 'refresh_token': token['refresh_token']})
            token = {**token, **refreshed}
            self.store.write('x-credentials.bin', token)  # Persist rotated refresh token before other requests.
        return token

    def switch(self, enabled: bool, acknowledge_api_cost=False):
        with self.lock:
            if enabled:
                if not acknowledge_api_cost:
                    raise UserError('开启前请确认：官方 X API 按用量计费，请先在官方控制台设置支出上限。')
                if not self.status()['connected']:
                    raise UserError('请先连接 X 账号，自动同步尚未开启。', 409)
            self._update(enabled=enabled, next_run=0, failures=0)
        self.wake.set()
        return self.status()

    def disconnect(self):
        warning = ''
        with self.lock:
            self._update(enabled=False, cursor=None, auth_error=False, next_run=0, last_error='')
            try:
                token = self.store.read('x-credentials.bin')
                if token:
                    with self._client() as client:
                        data = {'token': token.get('refresh_token') or token['access_token'], 'client_id': self._state()['client_id']}
                        auth = httpx.BasicAuth(data['client_id'], self.settings.x_client_secret) if self.settings.x_client_secret else None
                        self._request(client, 'POST', 'oauth2/revoke', data=data, auth=auth)
            except UserError:
                warning = '本地连接已移除；未能确认 X 撤销授权，请到 X「已连接的应用」手动撤销。'
            finally:
                self.store.delete('x-credentials.bin')
                self.store.delete('x-oauth-pending.bin')
        return {'message': warning or '已断开 X 并撤销授权；已保存的知识仍保留。', **self.status()}

    def _page(self, client, token, config, cursor=None):
        params = {'max_results': config['page_size'], 'tweet.fields': 'created_at,author_id,conversation_id,note_tweet,article',
                  'expansions': 'author_id', 'user.fields': 'name,username'}
        if cursor:
            params['pagination_token'] = cursor
        try:
            return self._request(client, 'GET', f"users/{token['account']['id']}/bookmarks", params=params,
                                 headers={'Authorization': 'Bearer '+token['access_token']})
        except XAPIError as exc:
            if exc.status != 400:
                raise
            # The current reference calls these post.fields/note_post, while its quickstart
            # still uses tweet.fields. Try the documented alternate once, never retry charges blindly.
            params.pop('tweet.fields')
            params['post.fields'] = 'created_at,conversation_id,note_post,article'
            return self._request(client, 'GET', f"users/{token['account']['id']}/bookmarks", params=params,
                                 headers={'Authorization': 'Bearer '+token['access_token']})

    def _import(self, post, users, user_id, long_only):
        post_id = str(post.get('id', ''))
        if not re.fullmatch(r'\d{1,25}', post_id):
            raise XAPIError('X 收藏包含无效帖子标识，已保留同步位置。')
        with self.db.connect() as conn:
            if conn.execute('SELECT 1 FROM x_sync_seen WHERE user_id=? AND post_id=?', (user_id,post_id)).fetchone():
                return 'duplicate'
        text = post_text(post)
        article = post.get('article')
        is_long = bool(article or post.get('note_tweet') or post.get('note_post') or len(text) >= 300)
        if long_only and not is_long:
            result, outcome = None, 'skipped'
        else:
            # No title/preview is passed to AI as if it were an Article body.
            incomplete = bool(article and not article.get('plain_text')) or len(text) < 20 or len(text) > MAX_CONTENT or bool(re.fullmatch(r'https?://\S+', text))
            author_id = str(post.get('author_id', ''))
            author = users.get(author_id, {})
            author_name = f"{author.get('name', '')} (@{author['username']})" if author.get('username') else author.get('name', '')
            title = (article or {}).get('title') or (text.splitlines()[0][:120] if text else 'X 收藏 · '+post_id)
            result = self.service.add(ArticleInput(url=f'https://x.com/i/web/status/{post_id}', title=title[:300],
                    author=author_name[:200], published_at=str(post.get('created_at') or '')[:80],
                    content='' if incomplete else text, source_kind='article'), enqueue=not incomplete)
            outcome = 'duplicate' if result['duplicate'] else 'needs_content' if incomplete else 'imported'
            if not result['duplicate']:
                note = '通过 X 官方收藏接口自动导入；收藏时间为本系统发现时间。仅读取此帖，未补全 Thread 或图片文字。'
                with self.db.connect() as conn:
                    conn.execute('UPDATE articles SET extraction_note=? WHERE id=?', (note,result['id']))
                    if incomplete:
                        conn.execute("UPDATE articles SET status='needs_content',ai_error=? WHERE id=?",
                                     ('X 未返回可验证的完整正文，已保留链接，请补充全文。',result['id']))
        with self.db.connect() as conn:
            conn.execute('INSERT OR IGNORE INTO x_sync_seen VALUES(?,?,?,?,?)',
                         (user_id,post_id,outcome,result['id'] if result else None,now()))
        return outcome

    def sync_once(self, require_enabled=True):
        if not self.lock.acquire(blocking=False):
            raise UserError('上一次收藏同步仍在运行，请稍后查看结果。', 409)
        try:
            config = self._state()
            if require_enabled and not config['enabled']:
                raise UserError('自动同步尚未开启。请先连接账号并启用。', 409)
            if self.clock() < config['next_run']:
                raise UserError('尚在同步间隔或限流退避期内，请等候下一次检查。', 429)
            self._update(last_checked_at=now())
            counts = dict(imported=0, needs_content=0, duplicate=0, skipped=0, pages=0)
            with self._client() as client:
                token = self._credentials(client)
                cursor = None
                for index in range(config['max_pages']):
                    page = self._page(client, token, config, cursor)
                    if not isinstance(page.get('data', []), list):
                        raise XAPIError('X 收藏列表格式无效，未推进同步位置。')
                    if page.get('errors'):
                        raise XAPIError('X 只返回了部分收藏或权限错误，未推进同步位置。请检查官方权限后重试。')
                    users = {str(u['id']): u for u in page.get('includes', {}).get('users', [])}
                    for post in page.get('data', []):
                        counts[self._import(post, users, token['account']['id'], config['long_only'])] += 1
                    counts['pages'] += 1
                    next_cursor = page.get('meta', {}).get('next_token')
                    # Always check the head for new bookmarks, then resume an unfinished sweep.
                    cursor = config['cursor'] if index == 0 and config['cursor'] else next_cursor
                    self._update(cursor=cursor, last_result=counts)
                    if not cursor:
                        break
            self._update(last_success_at=now(), last_error='', failures=0, auth_error=False,
                         last_result=counts, next_run=self.clock()+config['interval_minutes']*60)
            return counts
        except XAPIError as exc:
            config = self._state()
            failures = config['failures']+1
            delay = max(exc.retry_after, min(3600, 60 * 2**min(failures,6)), config['interval_minutes']*60)
            self._update(last_error=str(exc), failures=failures, next_run=self.clock()+delay,
                         enabled=False if exc.fatal else config['enabled'],
                         auth_error=exc.status == 401, cursor=None if exc.status == 400 else config['cursor'])
            raise
        finally:
            self.lock.release()

    def start(self):
        self.thread = threading.Thread(target=self.work, name='x-bookmark-sync', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)

    def work(self):
        while not self.stop_event.is_set():
            data = self._state()
            if data['enabled'] and self.clock() >= data['next_run']:
                try:
                    self.sync_once()
                except UserError as exc:
                    if not isinstance(exc, XAPIError):
                        self._update(enabled=False, last_error=str(exc))
                    log.warning('X sync paused or retry scheduled: error_type=%s', type(exc).__name__)
                except Exception as exc:
                    self._update(last_error='收藏同步发生内部错误，将稍后重试。', next_run=self.clock()+600)
                    log.error('X sync failed: error_type=%s', type(exc).__name__)
            self.wake.wait(15)
            self.wake.clear()
