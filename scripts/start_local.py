"""Start the complete Windows app with downloaded local models; no paid API required."""
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import time

import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    runtime = root/'.cache'/'smoke-model'
    gpu = runtime/'vulkan'/'llama-server.exe'
    executable = gpu if gpu.exists() and os.getenv('XSB_LOCAL_CPU') != '1' else runtime/'llama-server.exe'
    model = runtime/'Qwen3-4B-Q4_K_M.gguf'
    if os.name != 'nt' or not executable.exists() or not model.exists():
        raise SystemExit('First run: python scripts/prepare_local_smoke_model.py (Windows). Other platforms: configure a compatible local service in .env.')
    key = secrets.token_urlsafe(32)
    descriptor, filename = tempfile.mkstemp(prefix='xsb-local-key-')
    process = None
    log = None
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as output:
            output.write(key)
        (root/'data').mkdir(exist_ok=True)
        log = (root/'data'/'local-model.log').open('a',encoding='utf-8')
        acceleration = ['--n-gpu-layers','24','--cache-type-k','q8_0','--cache-type-v','q8_0','--flash-attn','on'] if executable == gpu else []
        process = subprocess.Popen([str(executable),'-m',str(model),'--host','127.0.0.1','--port','8788','-c','8192','-t','6','--parallel','1','--alias','xsb-local-qwen3','--no-webui','--reasoning','off','--api-key-file',filename,*acceleration],stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic()+60
        with httpx.Client(timeout=2) as client:
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise SystemExit('Local model failed to start. Check data/local-model.log; port 8788 may already be occupied.')
                try:
                    response = client.get('http://127.0.0.1:8788/health',headers={'Authorization':'Bearer '+key})
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.5)
            else:
                raise SystemExit('Local model startup timed out. See data/local-model.log.')
        os.environ.update(LLM_PROVIDER='api',HOST='127.0.0.1',PORT='8787',LLM_BASE_URL='http://127.0.0.1:8788/v1',LLM_MODEL='xsb-local-qwen3',LLM_API_KEY=key,LLM_JSON_SCHEMA='true',LLM_MAX_TOKENS='4000',LLM_TIMEOUT='600',EMBEDDING_PROVIDER='local',EMBEDDING_MODEL='BAAI/bge-small-zh-v1.5')
        print('Local AI ready. Open http://127.0.0.1:8787 ; Ctrl+C stops both app and model.',flush=True)
        from xsecondbrain.main import run
        run()
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        Path(filename).unlink(missing_ok=True)
        if log:
            log.close()


if __name__ == '__main__':
    main()
