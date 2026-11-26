"""Read-only NSE session notice, backed by Upstox's dated calendar."""
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import httpx

IST=ZoneInfo('Asia/Kolkata')
_lock=threading.Lock()
_cache={}

def _fetch(day):
    token=os.getenv('UPSTOX_ACCESS_TOKEN','').strip()
    if not token:raise ValueError('Configure the Upstox token to verify the exchange calendar.')
    headers={'Authorization':'Bearer '+token,'Accept':'application/json'}
    data=[]
    with httpx.Client(timeout=8) as client:
        for path in ('holidays','timings'):
            response=client.get(f'https://api.upstox.com/v2/market/{path}/{day}',headers=headers)
            response.raise_for_status()
            body=response.json()
            if body.get('status')!='success' or not isinstance(body.get('data'),list):
                raise ValueError('Unexpected calendar response')
            data.append(body['data'])
    return data

def describe(day,stamp,holidays,timings):
    base={'date':day,'exchange':'NSE','timezone':'Asia/Kolkata','verified':True,'source':'Upstox market holidays and timings','checked_at':stamp}
    events=[h for h in holidays if h.get('date')==day]
    sessions=[t for t in timings if t.get('exchange')=='NSE']
    if not sessions:
        sessions=[t for h in events for t in h.get('open_exchanges',[]) if t.get('exchange')=='NSE']
    # An explicitly scheduled session takes priority over weekends/holiday labels.
    if sessions:
        spans=sorted((float(t['start_time'])/1000,float(t['end_time'])/1000) for t in sessions)
        if any(b<=a or datetime.fromtimestamp(a,IST).date().isoformat()!=day for a,b in spans):raise ValueError('Invalid session timing')
        state='open' if any(a<=stamp<b for a,b in spans) else 'before_open' if stamp<spans[0][0] else 'closed'
        special=bool(events) or datetime.fromisoformat(day).weekday()>=5
        title={'open':'NSE trading session is open','before_open':'NSE trading opens later today','closed':'NSE trading session is closed'}[state]
        return {**base,'state':state,'title':title,'special_session':special,'description':'; '.join(h.get('description','') for h in events),
                'sessions':[{'start':a,'end':b} for a,b in spans]}
    closed=[h for h in events if h.get('holiday_type')=='TRADING_HOLIDAY' and 'NSE' in h.get('closed_exchanges',[])]
    if closed:return {**base,'state':'holiday','title':'Today is an NSE market holiday','description':'; '.join(h.get('description','Market holiday') for h in closed),'sessions':[]}
    weekend=datetime.fromisoformat(day).weekday()>=5
    return {**base,'state':'weekend' if weekend else 'closed','title':'NSE is closed for the weekend' if weekend else 'No NSE trading session scheduled today','description':'No NSE session is listed in the exchange calendar.','sessions':[]}

def market_today(stamp=None):
    stamp=time.time() if stamp is None else stamp
    day=datetime.fromtimestamp(stamp,IST).date().isoformat()
    with _lock:
        cached=_cache.get(day)
        if not cached or time.monotonic()>=cached['expires']:
            try:
                holidays,timings=_fetch(day)
                describe(day,stamp,holidays,timings)  # Validate before caching.
                cached={'holidays':holidays,'timings':timings,'checked_at':stamp,'expires':time.monotonic()+900}
            except (httpx.HTTPError,ValueError,KeyError,TypeError,OverflowError):
                cached={'error':True,'checked_at':stamp,'expires':time.monotonic()+60}
            _cache.clear();_cache[day]=cached
    if cached.get('error'):
        return {'date':day,'exchange':'NSE','timezone':'Asia/Kolkata','verified':False,'state':'unknown',
                'title':'Market holiday status unavailable','description':'Could not verify today’s NSE calendar. Check your Upstox connection; no trading-day assumption has been made.',
                'source':'Upstox market calendar','checked_at':cached['checked_at'],'sessions':[]}
    return {**describe(day,stamp,cached['holidays'],cached['timings']),'checked_at':cached['checked_at']}
