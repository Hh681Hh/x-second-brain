"""Read upstream metadata and small architectural files; no upstream code is reused."""
import concurrent.futures
import json
import pathlib
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1] / "research-cache"
REPOS = ["karakeep-app/karakeep", "iamzifei/bookmark-is-learned", "loong-solvable/x-bookmark-digest-skill", "sharbelxyz/x-bookmarks", "steipete/summarize"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "XSecondBrain-Research/0.1"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def inspect(repo):
    try:
        meta = json.loads(get(f"https://api.github.com/repos/{repo}"))
        tree = json.loads(get(f"https://api.github.com/repos/{repo}/git/trees/{meta['default_branch']}?recursive=1"))
        paths = [x["path"] for x in tree["tree"] if x["type"] == "blob"]
    except Exception:
        meta = {"default_branch": "main", "license": "API rate limited; inspect LICENSE"}
        tree = {"sha": "unavailable"}
        paths = ["README.md", "LICENSE", "LICENSE.md", "package.json", "SKILL.md"]
    folder = ROOT / repo.replace("/", "--")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "paths.json").write_text(json.dumps(paths, indent=2), encoding="utf-8")
    candidates = [p for p in paths if p.lower() in ("readme.md", "license", "license.md", "license.txt", "package.json", "skill.md", "docker-compose.yml")]
    for path in candidates:
        try:
            content = get(f"https://raw.githubusercontent.com/{repo}/{meta['default_branch']}/{path}")
            (folder / path.replace("/", "--")).write_text(content, encoding="utf-8")
        except Exception:
            pass
    print(json.dumps({"repo": repo, "sha": tree["sha"], "license": meta.get("license"), "files_read": candidates, "architecture_paths": [p for p in paths if any(k in p.lower() for k in ["search", "schema", "storage", "extract", "pipeline", "summary"] )][:25]}, ensure_ascii=True))


if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(inspect, REPOS))
