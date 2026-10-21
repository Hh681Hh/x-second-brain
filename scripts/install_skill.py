"""Install the project's self-contained skill without overwriting an existing skill."""
import argparse
import os
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',type=Path,help='Parent skills directory; default CODEX_HOME/skills or ~/.codex/skills')
    args = parser.parse_args()
    parent = args.target or (Path(os.environ['CODEX_HOME'])/'skills' if os.getenv('CODEX_HOME') else Path.home()/'.codex'/'skills')
    source = Path(__file__).resolve().parents[1]/'skills'/'x-second-brain'
    target = parent.resolve()/'x-second-brain'
    if target.exists():
        raise SystemExit(f'Already exists: {target}. Choose a different --target or back up the existing skill first.')
    parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,target)
    print(f'Installed: {target}\nOpen a new Codex session to discover $x-second-brain.')


if __name__ == '__main__':
    main()
