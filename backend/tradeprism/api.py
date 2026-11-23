import hashlib
import hmac
import json
import os
import threading
import uuid
from datetime import date
from .scope import SYMBOLS, TIMEFRAMES
from collections import defaultdict, deque
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from .db import init, session, Job, Workspace, Favorite, now
from .providers import REGISTRY, SECONDS
from .quant import risk, HORIZON
from .service import analyze, records, append, metadata

limits=defaultdict(deque); rate_lock=threading.Lock()

def auth(authorization: str=Header(default='')):
    configured=json.loads(os.getenv('TRADEPRISM_USERS','{}'))
    token=authorization.removeprefix('Bearer ')
    owner=next((name for name,key in configured.items() if len(key)>=24 and hmac.compare_digest(token,key)),None)
    if not owner: raise HTTPException(401,'Enter a configured access key. See server TRADEPRISM_USERS setting.')
    with rate_lock:
        q=limits[owner]; stamp=now()
        while q and q[0]<stamp-60: q.popleft()
        if len(q)>=180: raise HTTPException(429,'Request limit reached; retry in one minute.')
        q.append(stamp)
    return owner

@asynccontextmanager
async def lifespan(app):
    init()
    from .universe import enforce_scope
    enforce_scope()
    yield

app=FastAPI(title='TradePrism AI',version='0.1.0',lifespan=lifespan)

def valid(symbol,tf):
    from .universe import load_registry
    load_registry()
    if symbol not in SYMBOLS or tf not in TIMEFRAMES: raise HTTPException(422,'Unsupported instrument or timeframe')

class Task(BaseModel):
    kind: str
    symbol: str
    timeframe: str='15m'

class Scenario(BaseModel):
    model_config=ConfigDict(allow_inf_nan=False)
    symbol: str
    timeframe: str='15m'
    direction: str='LONG'
    entry: float
    stop: float
    target: float
    equity: float=Field(gt=0)
    risk_pct: float=Field(gt=0,le=3,default=1)
    cost_bps: float=Field(ge=0,le=1000,default=15)
    fx: float=Field(gt=0,default=1)
    account_currency: str='USD'

class DrawingState(BaseModel):
    drawings: list[dict]=Field(max_length=100,default_factory=list)
    settings: dict=Field(default_factory=dict)

class Explain(BaseModel):
    symbol: str
    timeframe: str='15m'
    question: str=Field(max_length=1000)

@app.get('/health')
def health(): return {'service':'TradePrism','state':'running','real_order_placement':False}

@app.get('/instruments')
def instruments(owner=Depends(auth)):
    from .universe import load_registry
    load_registry()
    return [{'symbol':s,**m,'timeframes':list(TIMEFRAMES)} for s,m in REGISTRY.items() if m['asset']=='equity']

@app.get('/analysis/{symbol}')
def analysis(symbol:str,timeframe:str='15m',until:float|None=None,owner=Depends(auth)):
    valid(symbol,timeframe)
    if until is not None and (until<=0 or until>now()): raise HTTPException(422,'Invalid replay time')
    return analyze(symbol,timeframe,until)

@app.post('/signals/{symbol}')
def snapshot(symbol:str,timeframe:str='15m',owner=Depends(auth)):
    valid(symbol,timeframe); result=analyze(symbol,timeframe)
    result.pop('candles',None); result.pop('overlays',None)
    with session() as s: identifier=append(s,'signal',owner,symbol,result)
    return {'id':identifier,**result}

class Focus(BaseModel):
    symbol: str
    timeframe: str='15m'

@app.post('/focus')
def focus(p:Focus,owner=Depends(auth)):
    valid(p.symbol,p.timeframe)
    from .db import ResearchState, ChartTrack
    with session() as s:
        if p.timeframe=='15m':
            row=s.get(ResearchState,p.symbol)
            if row: row.next_fetch=-now()
        else:
            row=s.get(ChartTrack,f'{p.symbol}:{p.timeframe}')
            if row: row.next_fetch=-now()
    return {'state':'Selected chart prioritized; universe collection remains automatic'}

@app.get('/stocks')
def stocks(offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=200),search:str=Query('',max_length=100),
    timeframe:str=Query('15m',pattern='^(5m|15m)$'),period:str=Query('all',pattern='^(all|today|week)$'),
    sort:str=Query('win_rate',pattern='^(win_rate|change|price|symbol|closed)$'),direction:str=Query('desc',pattern='^(asc|desc)$'),
    minimum:int=Query(0,ge=0),owner=Depends(auth)):
    from .tables import stock_table
    return stock_table(offset,limit,search,timeframe,period,sort,direction,minimum)

@app.get('/activity')
def activity(offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=200),search:str=Query('',max_length=100),
    state:str=Query('all',pattern='^(all|queued|running|completed|failed|cancelled)$'),owner=Depends(auth)):
    from .tables import activity_table
    return activity_table(offset,limit,search,state)

@app.get('/dashboard')
def dashboard(date_from:date|None=None,date_to:date|None=None,symbol:str|None=None,owner=Depends(auth)):
    from .ledger import summary
    try:return summary(date_from,date_to,symbol)
    except ValueError as e:raise HTTPException(422,str(e))

@app.get('/forecasts')
def forecast_history(offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=200),symbol:str|None=None,
    date_from:date|None=None,date_to:date|None=None,
    position:str|None=Query(None,pattern='^(LONG|SHORT)$'),timeframe:str|None=Query(None,pattern='^(5m|15m)$'),owner=Depends(auth)):
    from .ledger import history
    try:return history(offset,limit,symbol,date_from,date_to,position,timeframe)
    except ValueError as e:raise HTTPException(422,str(e))

@app.get('/monitor')
def monitor(owner=Depends(auth)):
    from .db import Instrument, ResearchState, LiveQuote, ChartTrack
    from .universe import status
    with session() as s:
        total=s.scalar(select(func.count()).select_from(Instrument))
        collected=s.scalar(select(func.count()).select_from(ResearchState).join(Instrument,Instrument.symbol==ResearchState.symbol).where(ResearchState.last_bar>0))
        trained=s.scalar(select(func.count()).select_from(ResearchState).join(Instrument,Instrument.symbol==ResearchState.symbol).where(ResearchState.trained_bar>0))
        fresh=s.scalar(select(func.count()).select_from(LiveQuote).join(Instrument,Instrument.symbol==LiveQuote.symbol).where(LiveQuote.received>now()-30,LiveQuote.trade_time>now()-60))
        pending=s.scalar(select(func.count()).select_from(Job).where(Job.status.in_(['queued','running'])))
        coverage=[{'timeframe':'15m','histories':collected,'trained':trained}]
        for tf in ('5m',):
            histories=s.scalar(select(func.count()).select_from(ChartTrack).join(Instrument,Instrument.symbol==ChartTrack.symbol).where(ChartTrack.timeframe==tf,ChartTrack.last_bar>0))
            models=s.scalar(select(func.count()).select_from(ChartTrack).join(Instrument,Instrument.symbol==ChartTrack.symbol).where(ChartTrack.timeframe==tf,ChartTrack.trained_bar>0))
            coverage.append({'timeframe':tf,'histories':histories,'trained':models})
    return {'coverage':coverage,'universe':total,'histories':sum(x['histories'] for x in coverage),'auto_trained':sum(x['trained'] for x in coverage),'recent_trades':fresh,'pending_jobs':pending,
        'feed':status('feed'),'collector':status('collector'),'outcomes':status('outcomes'),'discovery':status('universe'),
        'timeframes':list(TIMEFRAMES),'training':'Automatic 5m/15m batch retraining after new completed outcomes; not tick-by-tick learning',
        'coverage_note':'Only the selected 100 NSE stocks. Long/short research on 5m and 15m; live observations and completed-candle confirmation are shown separately.'}

@app.get('/quotes/{symbol}')
def quote(symbol:str,owner=Depends(auth)):
    from .db import LiveQuote
    valid(symbol,'5m')
    with session() as s:
        q=s.get(LiveQuote,symbol)
        if not q: return {'symbol':symbol,'state':'No streamed price yet'}
        return {'symbol':symbol,'price':q.price,'previous_close':q.previous_close,'trade_time':q.trade_time,
            'received':q.received,'state':'Recent trade' if now()-q.received<30 and now()-q.trade_time<60 else 'Last known trade — stale or market closed'}

@app.post('/jobs',status_code=202)
def enqueue(task:Task,owner=Depends(auth)):
    valid(task.symbol,task.timeframe)
    if task.kind not in ('ingest','train','prepare','reconcile'): raise HTTPException(422,'Unsupported task')
    with session() as s:
        pending=s.scalar(select(Job).where(Job.status.in_(['queued','running']),Job.symbol==task.symbol,Job.timeframe==task.timeframe,Job.kind==task.kind))
        if pending: return {'id':pending.id,'state':pending.status}
        total=list(s.scalars(select(Job).where(Job.status.in_(['queued','running']))))
        if len(total)>=20: raise HTTPException(429,'Job queue is full')
        identifier=uuid.uuid4().hex
        s.add(Job(id=identifier,kind=task.kind,symbol=task.symbol,timeframe=task.timeframe,status='queued',created=now(),updated=now(),detail='Queued'))
        append(s,'audit',owner,task.symbol,{'action':'enqueue','kind':task.kind,'job_id':identifier})
    return {'id':identifier,'state':'queued'}

@app.get('/jobs')
def jobs(owner=Depends(auth)):
    with session() as s:
        return [{k:getattr(x,k) for k in ['id','kind','symbol','timeframe','status','created','updated','detail']} for x in s.scalars(select(Job).order_by(Job.created.desc()).limit(30))]

def calculate(p):
    valid(p.symbol,p.timeframe)
    meta=metadata(p.symbol,p.timeframe)
    if not meta: raise HTTPException(409,'Provider tick and lot metadata unavailable. Fetch data before calculating a plan.')
    if p.account_currency==meta['currency'] and p.fx!=1: raise HTTPException(422,'Same-currency conversion must be 1')
    try: return risk(p.entry,p.stop,p.target,p.direction,p.equity,p.risk_pct,meta['tick'],meta['lot'],p.cost_bps,p.fx)
    except ValueError as e: raise HTTPException(422,str(e)) from e

@app.post('/risk')
def calculate_risk(p:Scenario,owner=Depends(auth)): return calculate(p)

@app.post('/plans',status_code=201)
def save_plan(p:Scenario,owner=Depends(auth)):
    result=calculate(p)
    with session() as s: identifier=append(s,'plan',owner,p.symbol,{**p.model_dump(),**result})
    return {'id':identifier,**result}

@app.post('/paper',status_code=201)
def create_paper(p:Scenario,owner=Depends(auth)):
    result=calculate(p); meta=metadata(p.symbol,p.timeframe)
    if p.direction=='SHORT' and not (meta.get('short_allowed') or (p.symbol in SYMBOLS and p.timeframe in TIMEFRAMES)): raise HTTPException(422,'Shorting is not supported for this configured instrument.')
    if meta.get('missing_intervals'): raise HTTPException(409,'Historical gaps must be reconciled before starting a paper scenario.')
    a=analyze(p.symbol,p.timeframe)
    if a['state']!='Completed historical candles — polling': raise HTTPException(409,'Fresh genuine data required for paper scenarios.')
    if result['quantity']<=0: raise HTTPException(422,'Risk budget cannot fund one lot')
    # Keep forward scenarios deliberately small until portfolio risk is implemented.
    plans=records('paper',owner=owner,limit=10000); events=records('paper_event',owner=owner,limit=10000)
    terminal={e['paper_id'] for e in events if e['event'] in ('target','stop','expired','unfilled')}
    if any(x['id'] not in terminal for x in plans): raise HTTPException(409,'Close or resolve the existing paper scenario first; one concurrent scenario is supported.')
    stamp=now(); step=SECONDS[p.timeframe]
    body={**p.model_dump(),**result,'owner':owner,'created':stamp,'entry_deadline':stamp+2*step,'exit_deadline':stamp+(HORIZON+1)*step,'data_timestamp':a['data_timestamp'],'source':a['source'],'mode':'Forward user scenario; not model performance','fill_assumption':'Stop entry in first completed bar opening after creation; gap beyond entry cancels. Stop wins same-bar ambiguity.'}
    with session() as s: identifier=append(s,'paper',owner,p.symbol,body)
    return {'id':identifier,**body}

@app.get('/history/{kind}')
def history(kind:str,owner=Depends(auth)):
    if kind not in ['signal','plan','paper','paper_event','alert','audit']: raise HTTPException(404,'Unknown history')
    return records(kind,owner=owner)

@app.get('/models')
def models(owner=Depends(auth)):
    seen=set(); result=[]
    for row in records('model',limit=10000):
        identity=(row['symbol'],row.get('timeframe'))
        if identity[0] in SYMBOLS and identity[1] in TIMEFRAMES and identity not in seen:
            result.append(row); seen.add(identity)
    return result

@app.get('/workspace/{symbol}')
def workspace(symbol:str,owner=Depends(auth)):
    valid(symbol,'15m')
    with session() as s:
        row=s.get(Workspace,f'{owner}:{symbol}')
        return json.loads(row.body) if row else {'drawings':[],'settings':{}}

@app.put('/workspace/{symbol}')
def save_workspace(symbol:str,p:DrawingState,owner=Depends(auth)):
    valid(symbol,'15m'); body=p.model_dump_json()
    if len(body)>100000: raise HTTPException(413,'Workspace exceeds 100 KB')
    with session() as s:
        key=f'{owner}:{symbol}'; row=s.get(Workspace,key)
        if row: row.body=body; row.updated=now()
        else: s.add(Workspace(key=key,body=body,updated=now()))
    return {'saved':True}

@app.post('/explain')
def explain(p:Explain,owner=Depends(auth)):
    valid(p.symbol,p.timeframe)
    from .explanations import explain_evidence
    a=analyze(p.symbol,p.timeframe)
    return explain_evidence(a,p.question)


@app.get('/favorites')
def favorites(owner=Depends(auth)):
    with session() as s:
        return list(s.scalars(select(Favorite.symbol).where(Favorite.owner==owner,Favorite.symbol.in_(SYMBOLS)).order_by(Favorite.symbol)))

@app.put('/favorites/{symbol}')
def add_favorite(symbol:str,owner=Depends(auth)):
    valid(symbol,'15m')
    from sqlalchemy.exc import IntegrityError
    try:
        with session() as s:
            if not s.get(Favorite,(owner,symbol)):
                s.add(Favorite(owner=owner,symbol=symbol,created=now()))
    except IntegrityError:
        # Concurrent identical PUT requests are idempotent.
        with session() as s:
            if not s.get(Favorite,(owner,symbol)): raise
    return {'symbol':symbol,'favorite':True}

@app.delete('/favorites/{symbol}')
def remove_favorite(symbol:str,owner=Depends(auth)):
    # Allow removal even if an instrument is no longer in the discovered universe.
    from sqlalchemy import delete
    with session() as s:
        s.execute(delete(Favorite).where(Favorite.owner==owner,Favorite.symbol==symbol))
    return {'symbol':symbol,'favorite':False}
