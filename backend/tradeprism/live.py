"""TLS-verified LTPC WebSocket ingestion. No invented OHLC/volume from price ticks.
One 5000-key subscription window; overflow rotates with explicit coverage status.
"""
import json
import math
import os
import time
import uuid
from urllib.parse import urlparse
import websocket
from .db import init, session, LiveQuote, now
from .universe import load_registry, status
from .providers import request
from .proto.MarketDataFeed_pb2 import FeedResponse

LIMIT=5000
ROTATE_SECONDS=300


def window(keys, offset):
    return (keys+keys)[offset:offset+min(len(keys),LIMIT)]


def decode(payload, mapping, stamp):
    message=FeedResponse()
    message.ParseFromString(payload)
    result={}
    for key,feed in message.feeds.items():
        symbol=mapping.get(key)
        if not symbol or not feed.HasField('ltpc'): continue
        q=feed.ltpc; trade=q.ltt/1000
        if not all(math.isfinite(v) for v in (q.ltp,q.cp,trade)): continue
        if q.ltp<=0 or trade<=0 or trade>stamp+60: continue
        result[symbol]={'price':q.ltp,'previous_close':q.cp,'trade_time':trade,'received':stamp}
    segments=dict(message.marketInfo.segmentStatus)
    return result,segments


def save_quotes(pending):
    with session() as s:
        for symbol,values in pending.items():
            row=s.get(LiveQuote,symbol)
            if row:
                if values['trade_time']<row.trade_time: continue
                for k,v in values.items(): setattr(row,k,v)
            else: s.add(LiveQuote(symbol=symbol,**values))


def run_connection(instruments, offset=0):
    mapping={info['instrument_key']:symbol for symbol,info in instruments.items()}
    keys=sorted(mapping)
    subscribed=window(keys,offset)
    token=os.getenv('UPSTOX_ACCESS_TOKEN','').strip()
    if not token: raise ValueError('Missing token')
    response=request('https://api.upstox.com/v3/feed/market-data-feed/authorize',
        {'Authorization':f'Bearer {token}','Accept':'application/json'})
    uri=response['data']['authorized_redirect_uri']
    host=urlparse(uri).hostname or ''
    if urlparse(uri).scheme!='wss' or not (host=='upstox.com' or host.endswith('.upstox.com')):
        raise ValueError('Unexpected authorized feed address')
    # Default certificate and hostname verification remain enabled.
    ws=websocket.create_connection(uri,timeout=10)
    pending={}; last_flush=now(); started=now(); last_message=0; segments={}
    try:
        for i in range(0,len(subscribed),100):
            ws.send_binary(json.dumps({'guid':uuid.uuid4().hex,'method':'sub',
                'data':{'mode':'ltpc','instrumentKeys':subscribed[i:i+100]}}).encode())
        while True:
            try:
                payload=ws.recv()
                if not payload: raise ConnectionError('Feed closed')
                if isinstance(payload,bytes):
                    quotes,market=decode(payload,mapping,now())
                    for symbol,q in quotes.items():
                        if symbol not in pending or q['trade_time']>=pending[symbol]['trade_time']: pending[symbol]=q
                    segments.update(market); last_message=now()
            except websocket.WebSocketTimeoutException:
                if now()-max(last_message,started)>60: raise ConnectionError('Feed heartbeat timed out')
            if now()-last_flush>=2:
                save_quotes(pending); pending.clear(); last_flush=now()
                status('feed',{'state':'connected','subscribed':len(subscribed),'universe':len(keys),
                    'outside_subscription':max(0,len(keys)-len(subscribed)),
                    'rotation_seconds':ROTATE_SECONDS if len(keys)>LIMIT else None,
                    'last_message':last_message,'segments':segments,
                    'mode':'LTPC prices only; charts use verified REST candles'})
            # Reconnect periodically to pick up daily instrument-master changes.
            if now()-started >= (ROTATE_SECONDS if len(keys)>LIMIT else 3600): break
    finally:
        ws.close(); save_quotes(pending)
    return (offset+LIMIT)%len(keys)


def main():
    init(); offset=0; delay=2
    while True:
        try:
            if os.getenv('CONTINUOUS_RESEARCH','1')!='1':
                status('feed',{'state':'disabled'}); time.sleep(30); continue
            instruments=load_registry()
            if not instruments:
                status('feed',{'state':'waiting for instrument discovery'}); time.sleep(5); continue
            status('feed',{'state':'connecting'})
            offset=run_connection(instruments,offset%len(instruments)); delay=2
        except Exception:
            # Never write authorized WebSocket URLs (temporary credentials) to logs.
            status('feed',{'state':'disconnected','detail':'Feed unavailable; check token, entitlement or connection',
                'retry_seconds':delay})
            time.sleep(delay); delay=min(60,delay*2)

if __name__=='__main__': main()
