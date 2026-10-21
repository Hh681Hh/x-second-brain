"""Opt-in public FxEmbed API adapter. Never accepts cookies or X credentials."""
from datetime import datetime, timezone
import json
import re
import time
from urllib.parse import urlsplit

import httpx

from .collectors import Collected
from .models import MAX_CONTENT
from .security import UserError

API = 'https://api.fxtwitter.com/2/status/'
MAX_RESPONSE = 4_000_000


def post_id(url):
    parts = urlsplit(url)
    match = re.fullmatch(r'/(?:[A-Za-z0-9_]+|i/web)/status/(\d+)/?', parts.path)
    if (parts.scheme != 'https' or parts.hostname not in ('x.com', 'www.x.com', 'twitter.com', 'www.twitter.com')
            or parts.username or parts.password or parts.port or not match):
        raise UserError('免费全文接口需要原始帖子链接；单独的 Article ID 暂不支持，链接已保留。')
    return match[1]


def decode_fulltext(payload, expected_id):
    if payload.get('code') != 200:
        raise UserError('免费全文服务未返回可用的公开内容，原链接与预览已保留。')
    status = payload.get('status')
    if not isinstance(status, dict) or str(status.get('id')) != expected_id:
        raise UserError('全文服务返回的帖子身份不匹配，未覆盖原收藏。')
    author = status.get('author') or {}
    if not isinstance(author, dict):
        raise UserError('全文服务作者格式异常，未覆盖原收藏。')
    article = status.get('article')
    omitted_quotes = 0
    if article is not None:
        if not isinstance(article, dict):
            raise UserError('全文服务文章格式异常，原预览已保留。')
        body = article.get('content') or {}
        blocks = body.get('blocks') if isinstance(body, dict) else None
        if not isinstance(blocks, list) or not blocks:
            raise UserError('免费接口仅返回 Article 预览，未冒充全文分析。')
        entities = body.get('entityMap') or []
        if not isinstance(entities, list):
            raise UserError('Article 内容结构变化，原预览已保留。')
        entity_map = {str(e.get('key')): e.get('value') or {} for e in entities if isinstance(e, dict)}
        paragraphs = []
        for block in blocks:
            if not isinstance(block, dict) or not isinstance(block.get('text'), str):
                raise UserError('Article 正文块格式异常，未保存不完整全文。')
            if block['text'].strip():
                paragraphs.append(block['text'].strip())
            if block.get('type') != 'atomic':
                continue
            for ref in block.get('entityRanges') or []:
                entity = entity_map.get(str(ref.get('key')), {})
                kind = entity.get('type')
                if kind == 'MARKDOWN':
                    markdown = (entity.get('data') or {}).get('markdown')
                    if not isinstance(markdown, str) or not markdown.strip():
                        raise UserError('Article 的 Markdown 正文块缺失，预览已保留。')
                    paragraphs.append(markdown.strip())
                elif kind == 'TWEET':
                    omitted_quotes += 1
                elif kind not in ('MEDIA', 'IMAGE', 'VIDEO', 'DIVIDER', 'LINK'):
                    raise UserError('Article 存在尚不支持的正文块，未将片段当作全文。')
        content = '\n\n'.join(paragraphs)
        title = str(article.get('title') or '')[:300]
        source_kind = 'article'
    else:
        raw = status.get('raw_text') or {}
        content = (raw.get('text') if isinstance(raw, dict) else None) or status.get('text') or ''
        if not isinstance(content, str):
            raise UserError('全文服务正文格式异常，原预览已保留。')
        content = content.strip()
        title = content.split('\n')[0][:300]
        source_kind = 'note'
    if len(content.strip()) < 20:
        raise UserError('免费服务返回内容过短或缺失，未作为完整文章分析。')
    if len(content) > MAX_CONTENT:
        raise UserError('全文超过12万字符上限，未截断冒充全文。')
    try:
        published = datetime.fromtimestamp(float(status['created_timestamp']), timezone.utc).isoformat()
    except (KeyError, ValueError, TypeError, OverflowError, OSError):
        published = str(status.get('created_at') or '')[:80]
    handle = author.get('screen_name') or ''
    name = author.get('name') or ''
    note = ('来自用户启用的非官方 FxEmbed 公开接口；已校验帖子ID。保存接口返回的文字正文，'
            '不含图片OCR、视频转写或整串帖子；服务并非X官方授权接口，内容完整性与事实仍需核对。')
    if omitted_quotes:
        note += f' 本文另有{omitted_quotes}个嵌入引用帖，未将其未取回的内容作为证据。'
    return Collected(content, title, (str(name) + (' @' + str(handle) if handle else '')).strip()[:200],
                     published, note, source_kind)


def collect_public_fulltext(url, *, enabled=False):
    # Consent is required at the caller as well; disabled is the default everywhere.
    if not enabled:
        raise UserError('尚未启用第三方公开全文接口，不会发送收藏ID。')
    identity = post_id(url)
    for attempt in range(3):
        try:
            # Fixed domain, no redirects, no account auth, no browser session or cookies.
            with httpx.Client(timeout=20, trust_env=False, follow_redirects=False,
                              headers={'User-Agent': 'XSecondBrain/0.3.2', 'Accept': 'application/json'}) as client:
                with client.stream('GET', API + identity) as response:
                    if response.status_code in (429, 500, 502, 503, 504):
                        if attempt < 2:
                            time.sleep(1 + attempt)
                            continue
                        raise UserError('免费全文服务限流或暂不可用，已重试3次；原文链接与预览已保留。')
                    if response.status_code != 200:
                        raise UserError(f'免费全文接口返回 HTTP {response.status_code}；无法读取私密、删除或受限内容，原预览已保留。')
                    parts, size = [], 0
                    for part in response.iter_bytes():
                        size += len(part)
                        if size > MAX_RESPONSE:
                            raise UserError('全文接口响应过大，已停止接收并保留原预览。')
                        parts.append(part)
            payload = json.loads(b''.join(parts))
            if not isinstance(payload, dict):
                raise ValueError('Unexpected response')
            return decode_fulltext(payload, identity)
        except httpx.HTTPError:
            if attempt == 2:
                raise UserError('免费全文服务网络异常，已重试3次；原链接与预览已保留。') from None
            time.sleep(1 + attempt)
        except (ValueError, TypeError, AttributeError):
            raise UserError('免费全文服务数据格式变化，未覆盖原预览。') from None
