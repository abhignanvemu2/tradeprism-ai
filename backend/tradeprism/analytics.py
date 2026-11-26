"""Bounded-memory chart aggregates over the full filtered forecast ledger."""
from collections import defaultdict
from datetime import datetime, timedelta
from .ledger import query_for, serialize, IST
from .db import session, now
from .scope import SYMBOLS

STATUSES=('success','failed','breakeven','open','waiting_entry','not_entered','awaiting_data','unverifiable')

def category(row):
    net=row['net_return']
    if net is not None:return 'success' if net>0 else 'failed' if net<0 else 'breakeven'
    return {'unfilled':'not_entered','waiting_entry':'waiting_entry','open':'open',
            'pending':'awaiting_data','awaiting_data':'awaiting_data'}.get(row['status'],'unverifiable')

def empty():
    return dict.fromkeys((*STATUSES,'forecasts','entered','closed','long','short'),0)

def add(counts,row,status):
    counts['forecasts']+=1;counts[status]+=1
    counts['entered']+=int(bool(row['entered']) or row['net_return'] is not None)
    counts['closed']+=int(row['net_return'] is not None)
    counts['short' if row['position']=='SHORT' else 'long']+=1

def finish(counts):
    return {**counts,'win_rate':counts['success']/counts['closed'] if counts['closed'] else None}

def charts(start=None,end=None,symbol=None,position=None,timeframe=None,period='range',group='day',status=None,qualified=None):
    if symbol and symbol not in SYMBOLS:raise ValueError('Choose one of the selected 100 stocks')
    if period=='all':
        start='1970-01-01'
        end=end or datetime.fromtimestamp(now(),IST).date().isoformat()
    q=query_for(start,end,symbol,position,timeframe)
    if qualified is not None:
        from .db import Forecast
        q=q.where(Forecast.qualified==qualified)
    total=empty();timeline=defaultdict(empty);stocks=defaultdict(empty);directions=defaultdict(empty)
    with session() as s:
        for f,r,p in s.execute(q.execution_options(yield_per=500)):
            row=serialize(f,r,p);state=category(row)
            if status and status!=state:continue
            day=datetime.fromtimestamp(f.created,IST).date()
            if group=='week':day-=timedelta(days=day.weekday())
            elif group=='month':day=day.replace(day=1)
            for bucket in (total,timeline[day.isoformat()],stocks[f.symbol],directions[row['position']]):add(bucket,row,state)
    return {'totals':finish(total),'timeline':[{'label':k,**finish(v)} for k,v in sorted(timeline.items())],
            'stocks':[{'label':k,**finish(v)} for k,v in sorted(stocks.items())],
            'positions':[{'label':k,**finish(directions[k])} for k in ('LONG','SHORT')],
            'generated_at':now(),'date_basis':'Forecast issue date · Asia/Kolkata',
            'basis':'Success/failure uses net paper returns after assumed costs. Win rate = successes / closed trades, including breakeven. Unentered and unverifiable forecasts are excluded. Live observations remain provisional.'}
