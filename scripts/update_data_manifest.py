"""Record a new data snapshot after intentionally regenerating the pipeline."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
files=[]
for p in sorted((ROOT/'data').rglob('*')):
    if p.is_file() and p.name!='publication_manifest.json':
        files.append({'path':p.relative_to(ROOT).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
(ROOT/'data/publication_manifest.json').write_text(json.dumps({'kind':'historical_publication_snapshot','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Recorded',len(files),'data files; review the diff before publishing')
