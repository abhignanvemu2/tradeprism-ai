"""Load local .env without executing code or exposing its contents."""
import os
from pathlib import Path

def load_env(path=None):
    path=Path(path) if path else Path(__file__).resolve().parents[2]/'.env'
    if not path.exists():return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:continue
        name,value=line.split('=',1);name=name.strip();value=value.strip()
        if value[:1] in ('"',"'") and value[-1:]==value[:1]:value=value[1:-1]
        if name.isidentifier():os.environ.setdefault(name,value)
