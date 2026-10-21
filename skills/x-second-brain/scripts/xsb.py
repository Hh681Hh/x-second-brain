#!/usr/bin/env python3
"""Dependency-free JSON client for a real X Second Brain service."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def request(method, path, body=None):
    base = os.getenv('XSB_URL', 'http://127.0.0.1:8787').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('XSB_URL 必须为不含账号密码的 HTTP/HTTPS 服务地址。')
    if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('远程知识库请使用 HTTPS，避免令牌明文传输。')
    headers = {'Accept': 'application/json'}
    token = os.getenv('XSB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = Request(base + '/api' + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=280) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            detail = json.load(exc).get('detail', '请求失败')
        except (ValueError, AttributeError):
            detail = '请求失败'
        raise RuntimeError(f'HTTP {exc.code}: {detail}') from None
    except (URLError, TimeoutError):
        raise RuntimeError('无法连接知识库或请求超时。确认服务已启动，并检查 XSB_URL/XSB_TOKEN。') from None


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    commands.add_parser('stats')
    commands.add_parser('browser-status')
    for name in ('sync-status','sync-now','sync-pause'):
        commands.add_parser(name)
    add = commands.add_parser('add')
    add.add_argument('--url', default='')
    add.add_argument('--file', type=Path)
    add.add_argument('--title', default='')
    add.add_argument('--author', default='')
    add.add_argument('--thread', action='store_true')
    batch = commands.add_parser('batch'); batch.add_argument('--file', type=Path, required=True)
    for cmd in ('get', 'process', 'related', 'wait'):
        sub = commands.add_parser(cmd); sub.add_argument('id')
        if cmd == 'wait': sub.add_argument('--timeout', type=int, default=45)
    for cmd in ('search', 'ask'):
        sub = commands.add_parser(cmd); sub.add_argument('question'); sub.add_argument('--limit', type=int, default=8)
        if cmd == 'ask': sub.add_argument('--session')
    listing = commands.add_parser('list'); listing.add_argument('--category', default=''); listing.add_argument('--limit', type=int, default=100); listing.add_argument('--offset', type=int, default=0)
    export = commands.add_parser('export'); export.add_argument('--output', type=Path, required=True)
    importing = commands.add_parser('import'); importing.add_argument('--file', type=Path, required=True)
    args = parser.parse_args()
    cmd = args.command
    if cmd == 'status': result = request('GET','/status')
    elif cmd == 'stats': result = request('GET','/summary')
    elif cmd == 'browser-status': result = request('GET','/browser')
    elif cmd == 'sync-status': result = request('GET','/integrations/x')
    elif cmd == 'sync-now': result = request('POST','/integrations/x/sync')
    elif cmd == 'sync-pause': result = request('POST','/integrations/x/switch',{'enabled':False})
    elif cmd == 'add':
        content = args.file.read_text(encoding='utf-8-sig') if args.file else ''
        result = request('POST','/articles',{'url':args.url,'title':args.title,'author':args.author,'content':content,'source_kind':'thread' if args.thread else 'article'})
    elif cmd == 'batch':
        urls = list(dict.fromkeys(u.strip() for u in args.file.read_text(encoding='utf-8-sig').splitlines() if u.strip()))
        result = request('POST','/articles/batch',{'articles':[{'url':u} for u in urls]})
    elif cmd == 'get': result = request('GET','/articles/' + args.id)
    elif cmd == 'related': result = request('GET','/articles/' + args.id + '/related')
    elif cmd == 'process': result = request('POST','/articles/' + args.id + '/process')
    elif cmd == 'wait':
        deadline = time.monotonic() + min(60,max(1,args.timeout))
        while True:
            result = request('GET','/articles/' + args.id)
            if result['status'] not in ('queued','processing') or time.monotonic() >= deadline: break
            time.sleep(min(2,max(0,deadline-time.monotonic())))
        result = {'id':result['id'],'status':result['status'],'ai_error':result['ai_error'],'embedding_error':result['embedding_error'],'analysis_ready':bool(result['analysis'])}
    elif cmd == 'list': result = request('GET','/articles?' + urlencode({'category':args.category,'limit':args.limit,'offset':args.offset}))
    elif cmd == 'search': result = request('GET','/search?' + urlencode({'q':args.question,'limit':args.limit}))
    elif cmd == 'ask': result = request('POST','/chat',{'question':args.question,'limit':args.limit,'session_id':args.session})
    elif cmd == 'export':
        payload = request('GET','/export')
        if args.output.exists(): raise ValueError('目标文件已存在，请选择新文件名，避免覆盖备份。')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        result = {'saved_to':str(args.output.resolve()),'articles':len(payload['articles'])}
    elif cmd == 'import': result = request('POST','/import',json.loads(args.file.read_text(encoding='utf-8-sig')))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr)
        sys.exit(1)
