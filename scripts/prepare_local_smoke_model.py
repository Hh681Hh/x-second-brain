"""Optional test setup. Official llama.cpp (MIT) and Qwen weights (Apache-2.0), no credentials."""
from concurrent.futures import ThreadPoolExecutor
import argparse
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1] / '.cache' / 'smoke-model'


def download(url, target):
    if target.exists():
        return
    temp = target.with_suffix('.part')
    with urllib.request.urlopen(url, timeout=60) as source, temp.open('wb') as output:
        expected = source.headers.get('Content-Length')
        written = 0
        while block := source.read(1024*1024):
            output.write(block)
            written += len(block)
        if expected and written != int(expected):
            raise RuntimeError('Incomplete download; final model file was not installed. Retry the command.')
    temp.replace(target)
    print(target.name, target.stat().st_size, flush=True)


def binary(flavor='cpu'):
    destination = ROOT/'vulkan' if flavor == 'vulkan' else ROOT
    destination.mkdir(parents=True,exist_ok=True)
    if (destination/'llama-server.exe').exists():
        print('Using cached official llama.cpp runtime',flush=True)
        return
    # Follow the official stable release; derive a real observed asset URL, not a guessed mirror.
    with urllib.request.urlopen('https://github.com/ggml-org/llama.cpp/releases/latest', timeout=30) as res:
        tag = res.url.rsplit('/',1)[1]
    with urllib.request.urlopen('https://github.com/ggml-org/llama.cpp/releases/expanded_assets/' + tag, timeout=30) as res:
        html = res.read().decode()
    urls = [x for x in html.split('"') if x.endswith(f'-bin-win-{flavor}-x64.zip') and '/download/' in x]
    if not urls:
        pointers = [x for x in html.split('"') if x.endswith('/nightly-tag.txt') and '/download/' in x]
        if pointers:
            with urllib.request.urlopen('https://github.com' + pointers[0], timeout=30) as res:
                tag = res.read().decode().strip()
            with urllib.request.urlopen('https://github.com/ggml-org/llama.cpp/releases/expanded_assets/' + tag, timeout=30) as res:
                html = res.read().decode()
            urls = [x for x in html.split('"') if x.endswith(f'-bin-win-{flavor}-x64.zip') and '/download/' in x]
    if not urls:
        raise RuntimeError(f'Official {flavor} archive not found; install a local compatible model server manually.')
    url = 'https://github.com' + urls[0] if urls[0].startswith('/') else urls[0]
    archive = ROOT / f'llama-{flavor}.zip'
    download(url, archive)
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            dest = (destination / item.filename).resolve()
            if not dest.is_relative_to(destination.resolve()):
                raise RuntimeError('Unsafe archive path')
        bundle.extractall(destination)
    print('Official runtime', tag, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--small',action='store_true',help='Use 1.5B for transport experiments; not recommended for knowledge quality.')
    parser.add_argument('--vulkan',action='store_true',help='Download the optional official GPU runtime instead of CPU runtime.')
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    model = ('Qwen/Qwen2.5-1.5B-Instruct-GGUF','qwen2.5-1.5b-instruct-q4_k_m.gguf') if args.small else ('Qwen/Qwen3-4B-GGUF','Qwen3-4B-Q4_K_M.gguf')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(binary,'vulkan' if args.vulkan else 'cpu'), pool.submit(download, f'https://huggingface.co/{model[0]}/resolve/main/{model[1]}', ROOT / model[1])]
        for future in futures:
            future.result()
