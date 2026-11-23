"""Read-only Upstox V3 completed candles. No orders or paid AI calls."""
import gzip
import json
import os
import time
from datetime import datetime,timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo
import httpx

IST=ZoneInfo('Asia/Kolkata')
_MASTER=(0,[])

def instrument(symbol):
    global _MASTER
    from .universe import load_registry
    saved=load_registry().get(symbol)
    if saved: return saved
    from .providers import DataUnavailable
    if time.time()-_MASTER[0]>3600:
        try:
            r=httpx.get('https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz',timeout=30)
            r.raise_for_status()
            content=r.content
            if content[:2]==b'\x1f\x8b':content=gzip.decompress(content)
            _MASTER=(time.time(),json.loads(content))
        except (httpx.HTTPError,ValueError,OSError) as e:
            raise DataUnavailable('Upstox instrument master unavailable; no guessed instrument metadata used.') from e
    from .scope import ALIASES, SYMBOLS
    if symbol not in SYMBOLS: raise DataUnavailable('Stock is outside the selected 100-stock universe')
    matches=[i for i in _MASTER[1] if i.get('trading_symbol')==ALIASES.get(symbol,symbol) and i.get('segment')=='NSE_EQ' and i.get('instrument_type')=='EQ']
    if len(matches)!=1:raise DataUnavailable('Instrument is missing or ambiguous in the Upstox master.')
    return matches[0]

def complete(t,tf,stamp):
    local=datetime.fromtimestamp(t,IST)
    close=local.replace(hour=15,minute=30,second=0,microsecond=0).timestamp()
    step={'1m':60,'5m':300,'15m':900,'1h':3600,'1d':86400}[tf]
    end=close if tf=='1d' else min(t+step,close)
    return end+10<=stamp

def fetch_upstox(symbol,tf,count,request,validate):
    from .providers import DataUnavailable,REGISTRY,SECONDS,timestamp
    token=os.getenv('UPSTOX_ACCESS_TOKEN','').strip()
    if not token:raise DataUnavailable('Add UPSTOX_ACCESS_TOKEN to the root .env, then restart. Use your read-only Analytics Token.')
    info=instrument(symbol)
    key=quote(info['instrument_key'],safe='')
    unit,interval={'1m':('minutes',1),'5m':('minutes',5),'15m':('minutes',15),'1h':('hours',1),'1d':('days',1)}[tf]
    headers={'Authorization':f'Bearer {token}','Accept':'application/json'}
    root='https://api.upstox.com/v3/historical-candle'
    today=datetime.now(IST).date(); cursor=today-timedelta(days=1)
    # Iterate within provider windows, stopping at the supported history boundary.
    earliest=datetime(2000 if tf=='1d' else 2022,1,1).date()
    chunk=365 if tf=='1d' else 28
    current=request(f'{root}/intraday/{key}/{unit}/{interval}',headers)
    rows=[[timestamp(c[0]),*c[1:6]] for c in current['data']['candles'] if complete(timestamp(c[0]),tf,time.time())]
    for _ in range(240):
        if len(rows)>=count:break
        left=max(earliest,cursor-timedelta(days=chunk-1))
        response=request(f'{root}/{key}/{unit}/{interval}/{cursor}/{left}',headers)
        rows.extend([timestamp(c[0]),*c[1:6]] for c in response['data']['candles'])
        if len(rows)>=count or left<=earliest:break
        cursor=left-timedelta(days=1)
        time.sleep(.25)
    stamp=time.time()
    rows=validate([r for r in rows if complete(r[0],tf,stamp)],stamp)[-count:]
    if not rows:raise DataUnavailable('Upstox returned no completed candles.')
    # BOD tick_size is in paise; OHLC is in INR.
    tick=float(info['tick_size'])/100
    lot=float(info['lot_size'])
    if tick<=0 or lot<=0:raise DataUnavailable('Invalid Upstox tick/lot metadata')
    return rows,{**REGISTRY[symbol],'symbol':symbol,'timeframe':tf,'source':'upstox','tick':tick,'lot':lot,'provider_id':info['instrument_key'],'fetched_at':stamp,'first':rows[0][0],'last':rows[-1][0],'count':len(rows),'volume_type':'NSE traded volume','adjustment':'provider OHLC; corporate-action reconciliation unverified','short_allowed':False,'missing_intervals':None,'delay':'Completed candles via REST polling, not a live tick stream','research_only':True}
