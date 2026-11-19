"""Start local API, collector, live feed, training worker and web services; Ctrl+C stops the processes we own."""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent

def main():
    env_path=ROOT/'.env'
    if not env_path.exists():
        env_path.write_text('TRADEPRISM_USERS='+json.dumps({'bib':secrets.token_urlsafe(32)})+'\nUPSTOX_ACCESS_TOKEN=\n',encoding='utf-8')
        print('Created .env with a private app access key. Add your Upstox token there. Enter the app key from .env at login.')
    sys.path.insert(0,str(ROOT/'backend'))
    from tradeprism.config import load_env
    load_env(env_path)
    try:
        users=json.loads(os.getenv('TRADEPRISM_USERS') or '{}')
    except json.JSONDecodeError:
        raise SystemExit('TRADEPRISM_USERS must be valid JSON, e.g. {"bib":"your-24-character-or-longer-key"}. Check .env and PowerShell environment overrides.')
    if not isinstance(users,dict) or not users or any(not isinstance(v,str) or len(v)<24 or 'REPLACE_' in v for v in users.values()):
        raise SystemExit('Set a random TRADEPRISM_USERS key (24+ characters) in .env first.')
    for port in (8000,3000):
        with socket.socket() as s:
            try:s.bind(('127.0.0.1',port))
            except OSError:raise SystemExit(f'Port {port} is already in use. Stop the previous app instance first.')
    node=shutil.which('node')
    if not node:raise SystemExit('Install Node.js 24 and run setup.bat first.')
    nextjs=ROOT/'frontend/node_modules/next/dist/bin/next'
    if not nextjs.exists():raise SystemExit('Run setup.bat first to install frontend dependencies.')
    # Limit CPU contention so training does not monopolize the live-feed process.
    os.environ.setdefault('OMP_NUM_THREADS','2')
    os.environ.setdefault('MKL_NUM_THREADS','2')
    check=subprocess.run([sys.executable,'-c','import uvicorn, websocket; from tradeprism.proto.MarketDataFeed_pb2 import FeedResponse; from tradeprism.db import init; init()'],cwd=ROOT/'backend')
    if check.returncode:
        raise SystemExit('Backend dependency/database check failed. Stop the app, run setup.bat, and inspect the error above.')
    commands=[([sys.executable,'-m','uvicorn','tradeprism.api:app','--host','127.0.0.1','--port','8000'],ROOT/'backend'),([sys.executable,'-m','tradeprism.worker'],ROOT/'backend'),([sys.executable,'-m','tradeprism.continuous'],ROOT/'backend'),([sys.executable,'-m','tradeprism.live'],ROOT/'backend'),([node,str(nextjs),'dev','--hostname','127.0.0.1','--port','3000'],ROOT/'frontend')]
    processes=[]
    try:
        for index,(command,cwd) in enumerate(commands):
            processes.append(subprocess.Popen(command,cwd=cwd))
            if index==0:
                deadline=time.monotonic()+60
                healthy=False
                while time.monotonic()<deadline and processes[0].poll() is None:
                    try:
                        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8000/health',timeout=2) as response:
                            healthy=response.status==200
                        if healthy: break
                    except OSError: pass
                    time.sleep(.5)
                if not healthy: raise RuntimeError('API did not become healthy. Inspect its traceback above; other services were not started.')
        print('Starting TradePrism at http://localhost:3000 . Keep this window open. Ctrl+C stops all services.')
        while all(p.poll() is None for p in processes):time.sleep(1)
        names=['API','training worker','collector','live feed','website']
        for name,process in zip(names,processes):
            if process.poll() is not None: print(f'{name} exited with code {process.returncode}. Inspect its error above.')
        print('Stopping remaining services. Run setup.bat after stopping all old app terminals, then start.bat.')
    except KeyboardInterrupt:print('\nStopping TradePrism...')
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill()

if __name__=='__main__':main()
