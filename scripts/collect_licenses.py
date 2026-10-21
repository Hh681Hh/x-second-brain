"""Snapshot installed dependency versions and their original bundled notices."""
from importlib import metadata
from pathlib import Path
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
if __name__ == '__main__':
    records = []
    for dist in sorted(metadata.distributions(),key=lambda d:(d.metadata.get('Name') or '').lower()):
        name = dist.metadata.get('Name','unknown')
        if name == 'x-second-brain': continue
        classifiers = [c.split(' :: ')[-1] for c in dist.metadata.get_all('Classifier',[]) if c.startswith('License ::')]
        license_value = dist.metadata.get('License-Expression') or dist.metadata.get('License') or '; '.join(classifiers) or 'Inspect bundled notices / upstream'
        files = []
        for item in dist.files or []:
            if not any(key in item.name.lower() for key in ('license','licence','copying','notice','copyright')):
                continue
            if item.suffix.lower() in ('.py','.pyc','.js','.pyd','.dll'): continue
            source = Path(dist.locate_file(item))
            if not source.is_file(): continue
            safe_name = re.sub(r'[^a-zA-Z0-9_.-]','_',name)
            relative = str(item).replace('..','_').replace('\\','--').replace('/','--')
            target = ROOT/'licenses'/safe_name/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
            files.append(target.relative_to(ROOT).as_posix())
        records.append({'name':name,'version':dist.version,'license':license_value,'classifiers':classifiers,'homepage':dist.metadata.get('Home-page'),'notices':files})
    target = ROOT/'docs'/'dependency-licenses.json'
    target.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(records)} distributions; {sum(len(r["notices"]) for r in records)} original notice files')
