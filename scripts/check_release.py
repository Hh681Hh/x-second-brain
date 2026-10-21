"""Check the Git index for release mistakes without printing any secret values."""
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def main():
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    names = sorted(filter(None, names))
    tracked = set(names)
    failures = []
    secret_patterns = [r'gh[pousr]_[A-Za-z0-9]{25,}', r'github_pat_[A-Za-z0-9_]{30,}',
                       r'sk-[A-Za-z0-9_-]{24,}', r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']
    local_secrets = []
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.partition('=')
            value = value.strip().strip('\"\'')
            if sep and re.search(r'(TOKEN|SECRET|API_KEY)$', key) and len(value) >= 12:
                local_secrets.append(value)
    for name in names:
        path = Path(name)
        if (path.parts[0] in ('data', '.venv', '.cache', 'artifacts', 'research-cache')
                or (path.name.startswith('.env') and path.name != '.env.example')
                or path.suffix in ('.sqlite', '.sqlite3', '.db', '.log', '.pem', '.key', '.pyc')
                or re.match(r'docs/(IMPORT-|AUTOSTART-|DEPLOYMENT-)', name)):
            failures.append((name, 'private/runtime path tracked'))
        raw = subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT)
        text = raw.decode('utf-8', errors='replace')
        if any(re.search(pattern, text) for pattern in secret_patterns) or any(s in text for s in local_secrets):
            failures.append((name, 'possible credential; value withheld'))
        if path.suffix == '.md' and path.parts[0] != 'licenses':
            for link in re.findall(r'\]\(([^)]+)\)', text):
                target = link.strip('<>').split('#')[0]
                if not target or re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                    continue
                resolved = (ROOT / path.parent / unquote(target)).resolve()
                try:
                    relative = resolved.relative_to(ROOT).as_posix()
                except ValueError:
                    failures.append((name, 'link escapes repository'))
                    continue
                if relative not in tracked and not any(n.startswith(relative.rstrip('/') + '/') for n in tracked):
                    failures.append((name, 'unpublished link: ' + target))
    print(json.dumps({'tracked_files': len(names), 'failures': failures}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
