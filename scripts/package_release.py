"""Package source, documentation and notices; exclude secrets, data, caches and runtimes."""
import argparse
from pathlib import Path
import zipfile
import subprocess

ROOT = Path(__file__).resolve().parents[1]


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    # Use the exact reviewed Git release tree, never recursively package a user's workspace.
    try:
        names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '-z', 'HEAD'], cwd=ROOT).decode('utf-8').split('\0')
    except (OSError, subprocess.CalledProcessError):
        raise SystemExit('Create a reviewed Git commit before packaging.') from None
    changed = subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=ROOT)
    if changed.strip():
        raise SystemExit('Commit or resolve tracked changes before packaging.')
    target = args.output.resolve()
    if target.exists():
        raise SystemExit('Choose a new output filename; existing release archives are not overwritten.')
    target.parent.mkdir(parents=True,exist_ok=True)
    count = 0
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name in sorted(filter(None, names)):
            content = subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=ROOT)
            archive.writestr('x-second-brain/' + name, content)
            count += 1
    print(f'{target}\n{count} files; {target.stat().st_size} bytes')
