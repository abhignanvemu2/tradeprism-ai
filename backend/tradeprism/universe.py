"""Provider-discovered NSE/BSE EQ instruments, shared across local processes."""
import gzip
import json
import re
import httpx
from sqlalchemy import select
from .db import Instrument, ResearchState, ChartTrack, MonitorState, session, now


def status(key, body=None):
    with session() as s:
        row=s.get(MonitorState,key)
        if body is not None:
            if row: row.body=json.dumps(body); row.updated=now()
            else: s.add(MonitorState(key=key,body=json.dumps(body),updated=now()))
            return body
        return {**json.loads(row.body),'updated':row.updated} if row else {}


def load_registry():
    from .providers import REGISTRY
    with session() as s:
        rows=list(s.scalars(select(Instrument)))
    # Retired symbols must not stay selectable in a long-lived API process.
    active={row.symbol for row in rows}
    for symbol in list(REGISTRY):
        if REGISTRY[symbol].get('discovered') and symbol not in active: REGISTRY.pop(symbol)
    for row in rows:
        info=json.loads(row.body)
        REGISTRY[row.symbol]={'provider':'upstox','venue':info['segment'].split('_')[0],
            'discovered':True,'stock_group':info.get('instrument_type'),'asset':'equity','currency':'INR','zone':'Asia/Kolkata','name':info.get('name',row.symbol)}
    return {row.symbol:json.loads(row.body) for row in rows}


BSE_STOCK_GROUPS={'A','B','X','XT','T','Z','M','MT','P','IT','ZP','ZY','Y','TS'}

def discover():
    found={}
    for exchange in ('NSE','BSE'):
        r=httpx.get(f'https://assets.upstox.com/market-quote/instruments/exchange/{exchange}.json.gz',timeout=60)
        r.raise_for_status()
        content=r.content
        if content[:2]==b'\x1f\x8b': content=gzip.decompress(content)
        for info in json.loads(content):
            if info.get('segment')!=exchange+'_EQ': continue
            groups={'EQ','BE','BZ','SM','ST'} if exchange=='NSE' else BSE_STOCK_GROUPS
            if info.get('instrument_type') not in groups: continue
            ticker=info.get('trading_symbol','')
            symbol=ticker if exchange=='NSE' else 'BSE_'+ticker
            # Names become model artifact directories on Windows; reject unsafe paths.
            if not re.fullmatch(r'[A-Za-z0-9&_.-]{1,40}',symbol) or symbol in ('.','..'): continue
            if not info.get('instrument_key'): continue
            if symbol in found: raise ValueError('Ambiguous provider symbol in instrument master')
            found[symbol]=info
    if not found: raise ValueError('No supported equity instruments in provider master')
    with session() as s:
        existing={row.symbol:row for row in s.scalars(select(Instrument))}
        states=set(s.scalars(select(ResearchState.symbol)))
        tracks=set(s.scalars(select(ChartTrack.key)))
        # Fetch identities once, then flush in bulk. Avoid tens of thousands of
        # SELECT/autoflush pairs while live quotes wait for the SQLite writer.
        for symbol,info in found.items():
            if symbol in existing: existing[symbol].body=json.dumps(info)
            else: s.add(Instrument(symbol=symbol,body=json.dumps(info)))
            if symbol not in states: s.add(ResearchState(symbol=symbol))
            for tf in ('1m','5m','1h','1d'):
                key=f'{symbol}:{tf}'
                if key not in tracks: s.add(ChartTrack(key=key,symbol=symbol,timeframe=tf))
        for symbol,row in existing.items():
            if symbol not in found: s.delete(row)
    status('universe',{'chart_schema':2,'count':len(found),'source':'Upstox NSE/BSE equity-segment masters; supported stock groups','discovered_at':now()})
    load_registry()
    return found
