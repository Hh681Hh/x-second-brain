"""Portable JSON backup. No secrets or model weight files in exports."""
from copy import deepcopy
import json
from uuid import uuid4

from .db import decode_article, dumps, now
from .knowledge import validate_analysis
from .models import Analysis, ArticleInput, Preferences
from .security import UserError


def export_library(db):
    with db.connect() as conn:
        articles = [decode_article(dict(r)) for r in conn.execute('SELECT * FROM articles ORDER BY saved_at')]
        sessions = [dict(r) for r in conn.execute('SELECT * FROM sessions')]
        messages = [dict(r) for r in conn.execute('SELECT * FROM messages ORDER BY id')]
    for article in articles:
        article['chunks'] = db.chunks(article['id'])
    return {"format": "x-second-brain", "version": 1, "exported_at": now(), "preferences": db.preferences(), "articles": articles, "sessions": sessions, "messages": messages}


def rebind_analysis(payload, chunks):
    candidate = deepcopy(payload)
    for mode in ('quick', 'standard', 'deep', 'knowledge'):
        for point in candidate.get(mode, []):
            rebound = []
            for evidence in point.get('evidence', []):
                quote = evidence.get('quote', '')
                position = evidence.get('start_offset')
                candidates = [c for c in chunks if quote and quote in c['text']]
                chunk = next((c for c in candidates if isinstance(position,int) and c['start_offset'] <= position and position + len(quote) <= c['end_offset'] and c['text'][position-c['start_offset']:position-c['start_offset']+len(quote)] == quote), candidates[0] if candidates else None)
                if chunk is None:
                    raise UserError('备份中的分析引文不在正文中，正文已导入，分析已跳过。')
                rebound.append({"chunk_id": chunk['id'], "quote": quote})
            point['evidence'] = rebound
    return validate_analysis(Analysis.model_validate(candidate), chunks)


def import_library(service, payload):
    if payload.get('format') != 'x-second-brain' or payload.get('version') != 1:
        raise UserError('只支持 X Second Brain version 1 JSON 备份。')
    articles = payload.get('articles')
    if not isinstance(articles, list) or len(articles) > 2000:
        raise UserError('备份文章列表无效或超过 2000 条，请拆分导入。')
    results, mapping = [], {}
    # Validate all raw articles before changing anything. Per-article processing issues remain visible.
    inputs = []
    for article in articles:
        values = {k: article[k] for k in ArticleInput.model_fields if k in article}
        # Text-only notes are stored with SQL NULL URLs and exported as JSON null.
        # They remain valid imports; an absent URL is not a lost source body.
        if values.get('url') is None:
            values['url'] = ''
        inputs.append(ArticleInput.model_validate(values))
    imported_preferences = Preferences.model_validate(payload['preferences']) if payload.get('preferences') else None
    if imported_preferences:
        current = service.db.preferences()
        categories = list(dict.fromkeys(current['categories'] + imported_preferences.categories))[:30]
        interests = current['interests'] or imported_preferences.interests
        with service.db.connect() as conn:
            for key,value in {'categories':categories,'interests':interests}.items():
                conn.execute('INSERT OR REPLACE INTO preferences VALUES(?,?)',(key,dumps(value)))
    for original, item in zip(articles, inputs):
        result = service.add(item, enqueue=False)
        mapping[original.get('id', '')] = result['id']
        result['warnings'] = []
        if not result['duplicate']:
            partial = str(original.get('extraction_note','')).startswith('浏览器仅保存了预览')
            with service.db.connect() as conn:
                # Preserve portable metadata, not execution state or provider error strings.
                conn.execute('UPDATE articles SET saved_at=?,is_read=? WHERE id=?', (str(original.get('saved_at') or now())[:80], bool(original.get('is_read', False)), result['id']))
                if str(original.get('extraction_note','')).startswith('浏览器'):
                    conn.execute('UPDATE articles SET extraction_note=? WHERE id=?',(original['extraction_note'][:1000],result['id']))
                if partial:
                    conn.execute("UPDATE articles SET status='needs_content' WHERE id=?",(result['id'],))
            if original.get('analysis') and item.content and not partial:
                try:
                    checked = rebind_analysis(original['analysis'], service.db.chunks(result['id']))
                    with service.db.connect() as conn:
                        conn.execute('UPDATE articles SET analysis_json=?,analysis_model=?,priority=? WHERE id=?', (dumps(checked), str(original.get('analysis_model') or 'imported')[:200], sum(v['score'] for v in checked['ratings'].values())/5, result['id']))
                except (UserError, ValueError, KeyError, TypeError):
                    result['warnings'].append('原分析未通过原文证据/结构校验，已跳过并等待重新处理。')
            if not partial:
                with service.db.connect() as conn:
                    service._enqueue(conn,result['id'])
        results.append(result)
    restored_sessions = 0
    sessions = payload.get('sessions', [])
    messages = payload.get('messages', [])
    if isinstance(sessions, list) and isinstance(messages, list):
        if len(sessions) > 5000 or len(messages) > 50000:
            raise UserError('对话备份过大，请拆分。')
        with service.db.connect() as conn:
            for session in sessions:
                sid = str(session.get('id') or uuid4())[:80]
                if conn.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
                    continue
                conn.execute('INSERT INTO sessions VALUES(?,?,?)', (sid, str(session.get('title', '导入对话'))[:100], str(session.get('created_at') or now())[:80]))
                for message in messages:
                    if message.get('session_id') != sid or message.get('role') not in ('user', 'assistant'):
                        continue
                    try:
                        body = json.loads(message['payload_json'])
                    except (ValueError, KeyError, TypeError):
                        continue
                    # Preserve answer snapshots. Remap article IDs; reading the UI rechecks current content.
                    for source in body.get('sources', []):
                        source['article_id'] = mapping.get(source.get('article_id'), source.get('article_id'))
                    for key in ('claims', 'disagreements'):
                        for claim in body.get(key, []):
                            for evidence in claim.get('evidence', []):
                                evidence['article_id'] = mapping.get(evidence.get('article_id'), evidence.get('article_id'))
                    body['session_id'] = sid
                    conn.execute('INSERT INTO messages(session_id,role,payload_json,created_at) VALUES(?,?,?,?)', (sid, message['role'], dumps(body), str(message.get('created_at') or now())[:80]))
                restored_sessions += 1
    return {"results": results, "restored_sessions": restored_sessions, "message": "正文已导入。向量会用当前模型重新建立；已存在的收藏未被覆盖。"}
