"""Run the downloaded Qwen3 model as a loopback-only compatible service (optional)."""
import os
from pathlib import Path
import subprocess
import sys


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    runtime = root/'.cache'/'smoke-model'
    gpu = runtime/'vulkan'/'llama-server.exe'
    executable = gpu if gpu.exists() and os.getenv('XSB_LOCAL_CPU') != '1' else runtime/'llama-server.exe'
    model = runtime/'Qwen3-4B-Q4_K_M.gguf'
    if not executable.exists() or not model.exists():
        raise SystemExit('Run scripts/prepare_local_smoke_model.py on Windows first; for other platforms use Ollama or llama.cpp directly. See README.')
    key = os.getenv('XSB_LOCAL_MODEL_KEY')
    if not key:
        raise SystemExit('Set XSB_LOCAL_MODEL_KEY to protect the local model API. Use the same value as LLM_API_KEY.')
    # Pass the key through a private temporary file, not command arguments or output.
    import tempfile
    descriptor, filename = tempfile.mkstemp(prefix='xsb-model-key-')
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8') as output:
            output.write(key)
        acceleration = ['--n-gpu-layers','24','--cache-type-k','q8_0','--cache-type-v','q8_0','--flash-attn','on'] if executable == gpu else []
        proc = subprocess.Popen([str(executable),'-m',str(model),'--host','127.0.0.1','--port','8766','-c','8192','-t','6','--parallel','1','--alias','xsb-local-qwen3','--no-webui','--reasoning','off','--api-key-file',filename,*acceleration],creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            raise SystemExit(proc.wait())
        except KeyboardInterrupt:
            proc.terminate()
            proc.wait(timeout=15)
    finally:
        Path(filename).unlink(missing_ok=True)
