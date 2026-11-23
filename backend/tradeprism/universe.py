"""Provider-verified selected NSE equity instruments, shared across local processes."""
import gzip
import json
import re
import httpx
from sqlalchemy import select
from .scope import SYMBOLS, SECTORS, ALIASES, SCHEMA
from .db import Instrument, ResearchState, ChartTrack, MonitorState, session, now


def status(key, body=None):
    with session(write=body is not None) as s:
        row=s.get(MonitorState,key)
        if body is not None:
            if row: row.body=json.dumps(body); row.updated=now()
            else: s.add(MonitorState(key=key,body=json.dumps(body),updated=now()))
            return body
        return {**json.loads(row.body),'updated':row.updated} if row else {}


def load_registry():
    from .providers import REGISTRY
    with session() as s:
        rows=list(s.scalars(select(Instrument).where(Instrument.symbol.in_(SYMBOLS))))
    # Retired symbols must not stay selectable in a long-lived API process.
    active={row.symbol for row in rows}
    for symbol in list(REGISTRY):
        if REGISTRY[symbol].get('discovered') and symbol not in active: REGISTRY.pop(symbol)
    for row in rows:
        info=json.loads(row.body)
        REGISTRY[row.symbol]={'provider':'upstox','venue':info['segment'].split('_')[0],
            'discovered':True,'stock_group':info.get('instrument_type'),'asset':'equity','currency':'INR','zone':'Asia/Kolkata','name':info.get('name',row.symbol),'provider_symbol':info.get('trading_symbol',row.symbol),'sector':SECTORS.get(row.symbol),'available':bool(info.get('instrument_key'))}
    return {row.symbol:json.loads(row.body) for row in rows if json.loads(row.body).get('instrument_key')}


BSE_STOCK_GROUPS={'A','B','X','XT','T','Z','M','MT','P','IT','ZP','ZY','Y','TS'}

def discover():
    found={}
    for exchange in ('NSE',):
        r=httpx.get(f'https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz',timeout=60)
        r.raise_for_status()
        content=r.content
        if content[:2]==b'\x1f\x8b': content=gzip.decompress(content)
        for info in json.loads(content):
            if info.get('segment')!=exchange+'_EQ': continue
            groups={'EQ','BE','BZ','SM','ST'} if exchange=='NSE' else BSE_STOCK_GROUPS
            if info.get('instrument_type') not in groups: continue
            ticker=info.get('trading_symbol','')
            symbol=next((old for old,new in ALIASES.items() if new==ticker),ticker)
            if symbol not in SYMBOLS: continue
            # Names become model artifact directories on Windows; reject unsafe paths.
            if not re.fullmatch(r'[A-Za-z0-9&_.-]{1,40}',symbol) or symbol in ('.','..'): continue
            if not info.get('instrument_key'): continue
            if symbol in found: raise ValueError('Ambiguous provider symbol in instrument master')
            found[symbol]=info
    if not found: raise ValueError('No supported equity instruments in provider master')
    with session(write=True) as s:
        existing={row.symbol:row for row in s.scalars(select(Instrument))}
        states=set(s.scalars(select(ResearchState.symbol)))
        tracks=set(s.scalars(select(ChartTrack.key)))
        # Fetch identities once, then flush in bulk. Avoid tens of thousands of
        # SELECT/autoflush pairs while live quotes wait for the SQLite writer.
        for symbol in SYMBOLS:
            info=found.get(symbol,{'segment':'NSE_EQ','name':symbol,'unavailable_reason':'Not found in current provider master; no substitute instrument used'})
            if symbol in existing: existing[symbol].body=json.dumps(info)
            else: s.add(Instrument(symbol=symbol,body=json.dumps(info)))
            if symbol not in states: s.add(ResearchState(symbol=symbol))
            for tf in ('5m',):
                key=f'{symbol}:{tf}'
                if key not in tracks: s.add(ChartTrack(key=key,symbol=symbol,timeframe=tf))
        for symbol,row in existing.items():
            if symbol not in SYMBOLS: s.delete(row)
    status('universe',{'chart_schema':SCHEMA,'count':len(SYMBOLS),'available':len(found),'missing':[s for s in SYMBOLS if s not in found],'aliases':ALIASES,'source':'Upstox NSE master; fixed user-selected universe','discovered_at':now()})
    load_registry()
    return found


def enforce_scope():
    """Migrate the selectable universe/queue, never delete historical evidence."""
    from .db import Job
    with session(write=True) as s:
        existing={x.symbol:x for x in s.scalars(select(Instrument))}
        for symbol in SYMBOLS:
            if symbol not in existing:s.add(Instrument(symbol=symbol,body=json.dumps({'segment':'NSE_EQ','name':symbol})))
        for symbol,row in existing.items():
            if symbol not in SYMBOLS:s.delete(row)
        for job in s.scalars(select(Job).where(Job.status=='queued')):
            if job.symbol not in SYMBOLS or job.timeframe not in ('5m','15m'):
                job.status='cancelled';job.detail='Outside configured 100-stock / 5m / 15m scope';job.updated=now()
    load_registry()
