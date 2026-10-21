"""Run with Python from a prepared repository to check its publication files."""
from pathlib import Path
import hashlib,json,re,subprocess

ROOT=Path(__file__).resolve().parents[1]
try:
    result=subprocess.run(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT,capture_output=True,check=True)
    files=[ROOT/name for name in result.stdout.decode('utf-8').split('\0') if name]
except (OSError,subprocess.CalledProcessError):
    files=[p for p in ROOT.rglob('*') if p.is_file() and not any(x in p.relative_to(ROOT).parts for x in ['.git','.venv','__pycache__','.pytest_cache','.pytest_tmp']) and p.name not in ['.env','secrets.toml']]

patterns=[re.compile(r'gsk_[A-Za-z0-9]{24,}'),re.compile(r'AIza[0-9A-Za-z_-]{30,}'),re.compile(r'sk-(?:proj-)?[A-Za-z0-9_-]{24,}'),re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')]
issues=[]
for p in files:
    relative=p.relative_to(ROOT).as_posix()
    if p.name=='.env' or relative=='.streamlit/secrets.toml':issues.append(relative+': private configuration is included')
    if p.stat().st_size>50*1024**2:issues.append(relative+': file exceeds the 50 MiB publication limit')
    if p.suffix.lower() in {'.py','.md','.toml','.yml','.yaml','.json','.jsonl','.csv','.txt','.example','.ipynb'}:
        text=p.read_text(encoding='utf-8',errors='replace')
        if any(pattern.search(text) for pattern in patterns):issues.append(relative+': credential-like content detected (value omitted)')
    if p.suffix=='.ipynb':
        notebook=json.loads(p.read_text(encoding='utf-8'))
        if any(c.get('outputs') for c in notebook.get('cells',[])):issues.append(relative+': notebook output should be cleared before publication')

manifest=ROOT/'data/publication_manifest.json'
published={p.relative_to(ROOT).as_posix() for p in files}
for item in json.loads(manifest.read_text(encoding='utf-8'))['files']:
    p=ROOT/item['path']
    if item['path'] not in published:issues.append(item['path']+': required snapshot file is ignored or not included')
    if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
        issues.append(item['path']+': snapshot differs from publication manifest; regenerate intentionally')

for document in [ROOT/'README.md',ROOT/'README_AR.md']:
    for target in re.findall(r'\]\(([^)]+)\)',document.read_text(encoding='utf-8')):
        target=target.strip('<>').split('#')[0]
        if target and '://' not in target and not (document.parent/target).exists():issues.append(document.name+': missing link '+target)
if issues:
    print('\n'.join(issues));raise SystemExit(1)
print(json.dumps({'status':'passed','publication_files':len(files),'bytes':sum(p.stat().st_size for p in files),'snapshot_hashes':'matched','credential_patterns':'none detected'},ensure_ascii=True))
