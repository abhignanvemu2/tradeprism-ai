import json
import uuid
import pandas as pd
from sqlalchemy import select
from .db import Candle, Record, session, now
from .providers import fetch, REGISTRY, SECONDS
from .quant import features, plan
from .ml import infer

def append(s, kind, owner, symbol, body, identifier=None):
    identifier=identifier or uuid.uuid4().hex
    s.add(Record(id=identifier,kind=kind,owner=owner,symbol=symbol,created=now(),body=json.dumps(body,allow_nan=False)))
    return identifier

def records(kind, owner=None, symbol=None, limit=100):
    with session() as s:
        q=select(Record).where(Record.kind==kind)
        if owner is not None: q=q.where(Record.owner==owner)
        if symbol is not None: q=q.where(Record.symbol==symbol)
        return [{'id':x.id,'created':x.created,'symbol':x.symbol,**json.loads(x.body)} for x in s.scalars(q.order_by(Record.created.desc()).limit(limit))]

def bars(symbol, tf, until=None):
    with session() as s:
        q=select(Candle).where(Candle.symbol==symbol,Candle.timeframe==tf)
        if until is not None: q=q.where(Candle.time<=until)
        rows=list(s.scalars(q.order_by(Candle.time)))
        return pd.DataFrame([{k:getattr(r,k) for k in ('time','open','high','low','close','volume')} for r in rows],columns=['time','open','high','low','close','volume'])

def metadata(symbol, tf):
    return next((x for x in records('ingestion',symbol=symbol) if x['timeframe']==tf),None)

def ingest(symbol, tf, count=1800):
    rows, meta=fetch(symbol,tf,count)
    with session() as s:
        existing={x.time:x for x in s.scalars(select(Candle).where(Candle.symbol==symbol,Candle.timeframe==tf))}
        for t,o,h,l,c,v in rows:
            if t in existing:
                old=existing[t]
                # Do not silently rewrite research history after provider corrections.
                if [old.open,old.high,old.low,old.close,old.volume]!=[o,h,l,c,v]:
                    raise ValueError('Provider historical revision detected; ingestion rejected. Reconcile adjusted prices before training.')
                old.fetched_at=meta['fetched_at']
            else:
                s.add(Candle(symbol=symbol,timeframe=tf,time=t,open=o,high=h,low=l,close=c,volume=v,source=meta['source'],fetched_at=meta['fetched_at']))
        append(s,'ingestion','system',symbol,meta)
    return meta

def analyze(symbol,tf,until=None):
    raw=bars(symbol,tf,until)
    meta=metadata(symbol,tf)
    result={'symbol':symbol,'timeframe':tf,'generated_at':now(),'source':REGISTRY[symbol]['provider'],'state':'Market data unavailable','decision':'NO TRADE','reasons':[],'probability':None,'candles':raw.tail(1000).to_dict('records'),'metadata':meta,'replay':until is not None}
    if raw.empty:
        result['reasons']=['Fetch genuine provider data first.']; return result
    last=float(raw.iloc[-1].time); age=now()-last-SECONDS[tf]
    stale=age>SECONDS[tf]*2 or not meta or now()-meta['fetched_at']>max(300,SECONDS[tf])
    result.update(state='Historical replay — practice only' if until else ('Stale historical data' if stale else 'Completed historical candles — polling'),data_timestamp=last,window_start=float(raw.iloc[0].time),window_end=last,bars_used=len(raw))
    if len(raw)<60:
        result['reasons']=['Insufficient historical data: need at least 60 completed bars.']; return result
    f=features(raw); r=f.iloc[-1]
    numeric=lambda value: float(value) if pd.notna(value) else None
    result['indicators']={k:numeric(r[k]) for k in ['rsi','atr','ema20','ema50','support','resistance','macd','bb_upper','bb_lower']}
    result['trend']='Bullish' if r.ema20>r.ema50 else 'Bearish'
    result['overlays']=[{'time':float(x.time),'ema20':numeric(x.ema20),'ema50':numeric(x.ema50)} for _,x in f.tail(1000).iterrows()]
    if meta and r.atr>0:
        result['research_plan']=plan(r,meta['tick'])
    result['reasons']=['Research workflow: live execution alignment, spread checks and walk-forward validation are not yet approved.']
    if stale and until is None: result['reasons'].append('Data is stale; new actionable signals suppressed.')
    if meta and meta.get('missing_intervals'): result['reasons'].append('Historical gaps detected; inspect data quality.')
    if REGISTRY[symbol]['asset']=='equity': result['reasons'].append('Corporate-action and exchange-calendar reconciliation is pending.')
    models=[x for x in records('model',symbol=symbol) if x['timeframe']==tf]
    if until is not None:
        result['reasons'].append('Replay uses only the selected past bars; predictive inference is disabled in practice replay.')
    elif models:
        result['model']=models[0]
        result['prediction']=infer(f,models[0])
        result['decision']='WATCH' if not stale else 'NO TRADE'
    else:
        result['reasons'].append('Predictive model not trained.')
    return result

def advance_paper():
    """Paper scenarios use only full bars opening after creation. Append-only events."""
    plans=records('paper',limit=10000)
    for p in plans:
        with session() as s:
            events=list(s.scalars(select(Record).where(Record.kind=='paper_event',Record.symbol==p['symbol'])))
            own=[json.loads(e.body) for e in events if json.loads(e.body).get('paper_id')==p['id']]
            if any(e['event'] in ('target','stop','expired','unfilled') for e in own): continue
            processed=max([e['bar_time'] for e in own]+[p['created']])
            filled=any(e['event']=='filled' for e in own)
            candidates=list(s.scalars(select(Candle).where(Candle.symbol==p['symbol'],Candle.timeframe==p['timeframe'],Candle.time>processed).order_by(Candle.time)))
            for c in candidates:
                # First full observed bar after creation is the only entry window.
                body={'paper_id':p['id'],'bar_time':c.time,'source':c.source,'event':'observed'}
                entered_this_bar=False
                if not filled:
                    possible=(c.open<=p['entry']<=c.high) if p['direction']=='LONG' else (c.low<=p['entry']<=c.open)
                    if c.time>p['entry_deadline'] or not possible:
                        body['event']='unfilled'
                    else:
                        filled=True
                        entered_this_bar=True
                        append(s,'paper_event',p['owner'],p['symbol'],{**body,'event':'filled','price':p['entry']},f"{p['id']}-fill")
                if filled:
                    long=p['direction']=='LONG'
                    stop_hit=c.low<=p['stop'] if long else c.high>=p['stop']
                    target_hit=c.high>=p['target'] if long else c.low<=p['target']
                    price=None
                    if stop_hit:
                        body['event']='stop'; price=p['stop'] if entered_this_bar else (min(c.open,p['stop']) if long else max(c.open,p['stop']))
                    elif target_hit:
                        body['event']='target'; price=p['target']
                    elif c.time>=p['exit_deadline']:
                        body['event']='expired'; price=c.close
                    if price is not None:
                        sign=1 if long else -1
                        body.update(price=price,net_pnl=(sign*(price-p['entry'])-(price+p['entry'])*p['cost_bps_per_side']/10000)*p['quantity']*p['fx']*p['multiplier'])
                append(s,'paper_event',p['owner'],p['symbol'],body,f"{p['id']}-{int(c.time)}")
                if body['event']!='observed':
                    append(s,'alert',p['owner'],p['symbol'],body,f"alert-{p['id']}-{int(c.time)}")
                    break
