"""Consistent IST issue-date filters for both the ledger and daily cards."""
import json
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, cast, JSON
from .db import Forecast, ForecastResult, ForecastProgress, ForecastObservation, session, now
from .scope import SYMBOLS, TIMEFRAMES
IST=ZoneInfo('Asia/Kolkata')

def bounds(start=None,end=None,stamp=None):
    today=datetime.fromtimestamp(now() if stamp is None else stamp,IST).date()
    start=date.fromisoformat(str(start)) if start else today
    end=date.fromisoformat(str(end)) if end else start
    if end<start:raise ValueError('End date must be on or after start date')
    return datetime.combine(start,time.min,IST).timestamp(),datetime.combine(end+timedelta(days=1),time.min,IST).timestamp()

def query_for(start=None,end=None,symbol=None,direction=None,tf=None,stamp=None):
    a,b=bounds(start,end,stamp)
    q=select(Forecast,ForecastResult,ForecastProgress).outerjoin(ForecastResult,ForecastResult.id==Forecast.id)\
        .outerjoin(ForecastProgress,ForecastProgress.id==Forecast.id).where(
            Forecast.symbol.in_(SYMBOLS),Forecast.timeframe.in_(TIMEFRAMES),Forecast.created>=a,Forecast.created<b)
    if symbol:q=q.where(Forecast.symbol==symbol)
    if tf:q=q.where(Forecast.timeframe==tf)
    if direction:
        from .db import engine
        field=func.json_extract(Forecast.body,'$.plan.direction') if engine.dialect.name=='sqlite' else cast(Forecast.body,JSON)['plan']['direction'].as_string()
        q=q.where(func.coalesce(field,'LONG')==direction)
    return q

def serialize(f,r,p,observations=()):
    body=json.loads(f.body); progress=json.loads(p.body) if p else {}
    result=json.loads(r.body) if r else None
    state=result or progress
    event=r.event if r else progress.get('event','waiting_entry')
    if not r and not p and now()>f.entry_time+{'5m':300,'15m':900}[f.timeframe]+30:event='awaiting_data'
    return {'id':f.id,'symbol':f.symbol,'timeframe':f.timeframe,'position':body['plan'].get('direction','LONG'),
        'issued_at':f.created,'entry_time':f.entry_time,'end_time':f.end_time,'probability':f.probability,
        'qualified':bool(f.qualified),'forecast':body,'outcome':result,'progress':progress,'status':event,
        'entered':state.get('entered',bool(r and r.net_return is not None)),
        'fill_price':state.get('fill_price'),'entered_at':state.get('entered_at'),
        'checked_at':p.updated if p else None,'live_observations':[json.loads(o.body) for o in observations],
        'net_return':r.net_return if r else None}

def history(offset=0,limit=25,symbol=None,start=None,end=None,direction=None,tf=None):
    q=query_for(start,end,symbol,direction,tf)
    with session() as s:
        total=s.scalar(select(func.count()).select_from(q.subquery()))
        rows=s.execute(q.order_by(Forecast.created.desc(),Forecast.id).offset(offset).limit(limit)).all()
        ids=[f.id for f,_,_ in rows]
        obs=list(s.scalars(select(ForecastObservation).where(ForecastObservation.forecast_id.in_(ids)).order_by(ForecastObservation.observed_at))) if ids else []
        records=[serialize(f,r,p,[o for o in obs if o.forecast_id==f.id]) for f,r,p in rows]
    return {'total':total,'offset':offset,'limit':limit,'records':records,'updated':now(),'date_basis':'Forecast issue date in IST'}

def summary(start=None,end=None,symbol=None,stamp=None):
    from .forward import metrics
    with session() as s:rows=s.execute(query_for(start,end,symbol,stamp=stamp)).all()
    items=[]
    for f,r,p in rows:
        d=serialize(f,r,p)
        items.append({'event':d['status'],'net_return':d['net_return'],'plan':d['forecast']['plan'],'entered':d['entered']})
    return {'generated_at':now() if stamp is None else stamp,'today':metrics(items),'date_basis':'Forecast issue date · Asia/Kolkata',
        'basis':'Success/failure counts use positive/negative net paper returns after assumed costs. Unfilled and unverifiable are separate. Live tick observations are provisional until candle confirmation.'}
