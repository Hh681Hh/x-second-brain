"""Background bookmark reader; pair the free browser extension once."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import webbrowser

import httpx

from .config import ROOT, Settings
from .security import UserError


def api(settings, path, method='GET', body=None):
    headers={'Authorization':'Bearer '+settings.app_token} if settings.app_token else {}
    with httpx.Client(timeout=4,trust_env=False) as client:
        response=client.request(method,f'http://127.0.0.1:{settings.port}/api'+path,headers=headers,json=body)
    if response.status_code!=200:
        raise UserError('本地服务拒绝请求。请检查 APP_TOKEN、端口及服务版本。')
    return response.json()


def running(settings):
    try:
        result=api(settings,'/status')
    except httpx.ConnectError:
        return None
    if 'total' not in result:
        raise UserError('这个端口运行的不是 X 书签助手，请检查 PORT。')
    return result


def start(settings, setup=False, engine='codex'):
    current=running(settings)
    if current and (not current.get('headless') or current.get('llm_provider')!=engine):
        raise UserError('旧服务仍在运行。请先停止旧启动命令，再运行这个后台脚本。')
    if not current:
        settings.data_dir.mkdir(parents=True,exist_ok=True)
        environment=os.environ.copy()
        environment.update(HOST='127.0.0.1',HEADLESS='true',LLM_PROVIDER=engine)
        environment.setdefault('LLM_TIMEOUT','600')
        options={'creationflags':subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}
        with (settings.data_dir/'agent-console.log').open('w',encoding='utf-8') as output:
            process=subprocess.Popen([sys.executable,'-X','utf8','-m','xsecondbrain.agent_cli','run','--engine',engine],
                cwd=ROOT,stdin=subprocess.DEVNULL,stdout=output,stderr=output,env=environment,**options)
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise UserError('后台启动失败，请查看 data/agent-console.log。')
            current=running(settings)
            if current:
                break
            time.sleep(0.3)
        else:
            raise UserError('后台启动超时，请检查 data/agent-console.log；不要重复启动。')
    print('后台脚本已运行。日常无需打开工作台。')
    browser=api(settings,'/browser')
    if setup and not browser['paired']:
        webbrowser.open(f'http://127.0.0.1:{settings.port}/')
        print('请在打开的连接页安装免费浏览器插件并完成一次配对。')
    elif not browser['paired']:
        print('浏览器插件尚未连接。运行 connect 打开安装和配对页。')
    return current


def stop(settings):
    marker=settings.data_dir/'agent-process.json'
    current=running(settings)
    if not marker.exists() or not current:
        raise UserError('没有可验证的后台脚本；未停止任何其他进程。')
    record=json.loads(marker.read_text(encoding='utf-8'))
    if (record.get('pid')!=current.get('pid') or not current.get('headless')
            or Path(record.get('project','')).resolve()!=ROOT.resolve()):
        raise UserError('后台进程身份不匹配，未执行停止。')
    pid=int(record['pid'])
    if pid<=1 or pid==os.getpid():
        raise UserError('无效后台进程标识。')
    if os.name=='nt':
        result=subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW,timeout=15)
        if result.returncode:
            raise UserError('后台停止失败，请检查进程权限。')
    else:
        if os.getpgid(pid)!=pid:
            raise UserError('后台进程组不匹配，未执行停止。')
        os.killpg(pid,signal.SIGTERM)
    marker.unlink(missing_ok=True)
    print('后台已停止。原文、知识、分类和连接信息已保留。')


def main():
    parser=argparse.ArgumentParser(description='X 书签后台助手：连接一次，以后直接在 Codex 提问。')
    commands=parser.add_subparsers(dest='action',required=True)
    for name in ('start','connect','run'):
        sub=commands.add_parser(name)
        sub.add_argument('--engine',choices=['codex','api'],default='codex')
        if name=='start': sub.add_argument('--setup-if-needed',action='store_true')
    commands.add_parser('stop')
    status=commands.add_parser('status'); status.add_argument('--json',action='store_true')
    args=parser.parse_args()
    settings=Settings.from_env()
    if args.action in ('start','connect'):
        start(settings,args.action=='connect' or args.setup_if_needed,args.engine)
    elif args.action=='run':
        if running(settings):
            raise UserError('这个端口已有服务运行，未覆盖后台进程信息。')
        os.environ.update(HOST='127.0.0.1',HEADLESS='true',LLM_PROVIDER=args.engine)
        os.environ.setdefault('LLM_TIMEOUT','600')
        settings=Settings.from_env()
        settings.data_dir.mkdir(parents=True,exist_ok=True)
        marker=settings.data_dir/'agent-process.json'
        marker.write_text(json.dumps({'pid':os.getpid(),'project':str(ROOT.resolve())}),encoding='utf-8')
        try:
            from .main import run
            run()
        finally:
            if marker.exists() and json.loads(marker.read_text(encoding='utf-8')).get('pid')==os.getpid():
                marker.unlink(missing_ok=True)
    elif args.action=='stop':
        stop(settings)
    else:
        summary=api(settings,'/summary')
        if args.json:
            print(json.dumps(summary,ensure_ascii=False,indent=2))
        else:
            s=summary['status']; x=summary['x_sync']; b=summary['browser']
            print(f"后台：已运行 · 阅读引擎：{s.get('llm_model') or '未配置'}")
            print(f"浏览器插件：{'已配对' if b['paired'] else '待配对'} · 网页入库：{b['captured_total']}篇 · 待补全：{b['needs_content']}篇")
            print(f"库内总计：{s['total']}篇 · 已分析：{s['learned']}篇 · 排队：{s['queued']}篇")
            if x['connected']:print(f"另有官方 API 连接 · 自动同步：{'已开启' if x['sync_enabled'] else '未开启'}")
            for category in summary['categories']:
                print(f"  {category['category']}：{category['count']}篇")
            if x['last_error']: print('同步提示：'+x['last_error'])


def cli():
    try:
        main()
    except (UserError,httpx.HTTPError,OSError,ValueError) as exc:
        message=str(exc) if isinstance(exc,UserError) else '无法连接后台或读取配置，请检查本地服务及 data/agent-console.log。'
        print(message,file=sys.stderr)
        sys.exit(1)


if __name__=='__main__':
    cli()
