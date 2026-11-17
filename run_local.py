"""Start all three local services; Ctrl+C stops the processes we own."""
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent

def main():
    env_path=ROOT/'.env'
    if not env_path.exists():
        env_path.write_text('TRADEPRISM_USERS='+json.dumps({'bib':secrets.token_urlsafe(32)})+'\nUPSTOX_ACCESS_TOKEN=\n',encoding='utf-8')
        print('Created .env with a private app access key. Add your Upstox token there. Enter the app key from .env at login.')
    sys.path.insert(0,str(ROOT/'backend'))
    from tradeprism.config import load_env
    load_env(env_path)
    users=json.loads(os.getenv('TRADEPRISM_USERS','{}'))
    if not users or any(len(v)<24 or 'REPLACE_' in v for v in users.values()):
        raise SystemExit('Set a random TRADEPRISM_USERS key (24+ characters) in .env first.')
    for port in (8000,3000):
        with socket.socket() as s:
            try:s.bind(('127.0.0.1',port))
            except OSError:raise SystemExit(f'Port {port} is already in use. Stop the previous app instance first.')
    node=shutil.which('node')
    if not node:raise SystemExit('Install Node.js 24 and run setup.bat first.')
    nextjs=ROOT/'frontend/node_modules/next/dist/bin/next'
    if not nextjs.exists():raise SystemExit('Run setup.bat first to install frontend dependencies.')
    commands=[([sys.executable,'-m','uvicorn','tradeprism.api:app','--host','127.0.0.1','--port','8000'],ROOT/'backend'),([sys.executable,'-m','tradeprism.worker'],ROOT/'backend'),([node,str(nextjs),'dev','--hostname','127.0.0.1','--port','3000'],ROOT/'frontend')]
    processes=[]
    try:
        for command,cwd in commands:processes.append(subprocess.Popen(command,cwd=cwd))
        print('Starting TradePrism at http://localhost:3000 . Keep this window open. Ctrl+C stops all services.')
        while all(p.poll() is None for p in processes):time.sleep(1)
        print('A service exited. Stopping the other services; inspect the errors above.')
    except KeyboardInterrupt:print('\nStopping TradePrism...')
    finally:
        for p in processes:
            if p.poll() is None:p.terminate()
        for p in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill()

if __name__=='__main__':main()
