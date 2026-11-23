"""Server-side stock ranking and complete job pagination."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, case, cast, Float, JSON, or_, and_
from .scope import SYMBOLS
from .db import Instrument, LiveQuote, Forecast, ForecastResult, Job, session, now


def stock_table(offset=0,limit=25,search='',timeframe='15m',period='all',sort='win_rate',direction='desc',minimum=0):
    stamp=now(); today=datetime.fromtimestamp(stamp,ZoneInfo('Asia/Kolkata')).replace(hour=0,minute=0,second=0,microsecond=0)
    start=None if period=='all' else (today.timestamp() if period=='today' else (today-timedelta(days=6)).timestamp())
    eligible=ForecastResult.net_return.is_not(None)
    if start is not None: eligible=and_(eligible,ForecastResult.event_time>=start)
    with session() as s:
        totals=select(Forecast.symbol.label('symbol'),
            func.sum(case((eligible,1),else_=0)).label('closed'),
            func.sum(case((and_(eligible,ForecastResult.net_return>0),1),else_=0)).label('wins'),
            func.sum(case((and_(eligible,ForecastResult.net_return<0),1),else_=0)).label('losses'),
            func.sum(case((ForecastResult.id.is_(None),1),else_=0)).label('pending'))\
            .outerjoin(ForecastResult,ForecastResult.id==Forecast.id).where(Forecast.timeframe==timeframe).group_by(Forecast.symbol).subquery()
        closed=func.coalesce(totals.c.closed,0); wins=func.coalesce(totals.c.wins,0)
        rate=cast(wins,Float)/func.nullif(closed,0)
        change=case((LiveQuote.previous_close>0,100*(LiveQuote.price-LiveQuote.previous_close)/LiveQuote.previous_close),else_=None)
        name=func.json_extract(Instrument.body,'$.name') if s.bind.dialect.name=='sqlite' else cast(Instrument.body,JSON)['name'].as_string()
        q=select(Instrument,LiveQuote,closed.label('closed'),wins.label('wins'),
            func.coalesce(totals.c.losses,0).label('losses'),func.coalesce(totals.c.pending,0).label('pending'),rate.label('rate'),change.label('change'))\
            .outerjoin(LiveQuote,LiveQuote.symbol==Instrument.symbol).outerjoin(totals,totals.c.symbol==Instrument.symbol).where(Instrument.symbol.in_(SYMBOLS))
        term=search.strip().lower()
        if term: q=q.where(or_(func.lower(Instrument.symbol).contains(term,autoescape=True),func.lower(name).contains(term,autoescape=True)))
        if minimum: q=q.where(closed>=minimum)
        filtered=q.subquery()
        total=s.scalar(select(func.count()).select_from(filtered))
        distribution=s.execute(select(
            func.sum(case((filtered.c.change>0,1),else_=0)),
            func.sum(case((filtered.c.change<0,1),else_=0)),
            func.sum(case((filtered.c.change==0,1),else_=0)),
            func.sum(case((filtered.c.change.is_(None),1),else_=0)))).one()
        breadth=dict(zip(('rising','falling','unchanged','unavailable'),[int(x or 0) for x in distribution]))
        column={'win_rate':rate,'change':change,'price':LiveQuote.price,'symbol':Instrument.symbol,'closed':closed}[sort]
        q=q.order_by(case((column.is_(None),1),else_=0),column.desc() if direction=='desc' else column.asc(),closed.desc(),Instrument.symbol.asc())
        rows=s.execute(q.offset(offset).limit(limit)).all()
        records=[]
        for inst,quote,n,w,losses,pending,win_rate,change_pct in rows:
            info=json.loads(inst.body)
            records.append({'symbol':inst.symbol,'name':info.get('name',inst.symbol),'exchange':info.get('segment','').split('_')[0],
                'provider_symbol':info.get('trading_symbol',inst.symbol),'available':bool(info.get('instrument_key')),'price':quote.price if quote else None,'previous_close':quote.previous_close if quote else None,
                'change':quote.price-quote.previous_close if quote and quote.previous_close>0 else None,'change_pct':change_pct,
                'quote_time':quote.trade_time if quote else None,'quote_fresh':bool(quote and stamp-quote.received<30 and stamp-quote.trade_time<60),
                'win_rate':win_rate,'closed':n,'wins':w,'losses':losses,'pending':pending,'limited_evidence':n<30})
    return {'breadth':breadth,'total':total,'offset':offset,'limit':limit,'records':records,'updated':stamp,'timeframe':timeframe,
        'basis':'Recorded prospective paper wins after assumed costs / resolved forecasts, selected timeframe and period. Unfilled and unverifiable forecasts excluded. Pending count is all-time. Price change is versus provider previous close.'}


def activity_table(offset=0,limit=25,search='',state='all'):
    with session() as s:
        q=select(Job)
        if search.strip(): q=q.where(func.lower(Job.symbol).contains(search.strip().lower(),autoescape=True))
        if state!='all':q=q.where(Job.status==state)
        total=s.scalar(select(func.count()).select_from(q.subquery()))
        rows=s.scalars(q.order_by(Job.created.desc(),Job.id.asc()).offset(offset).limit(limit))
        records=[{k:getattr(row,k) for k in ('id','kind','symbol','timeframe','status','created','updated','detail')} for row in rows]
    return {'total':total,'offset':offset,'limit':limit,'records':records,'updated':now()}
