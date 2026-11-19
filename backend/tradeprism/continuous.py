"""Automatic completed-candle collection and bounded retraining queue.
Live price streaming is a separate process, so model fitting cannot block ticks.
"""
import json
import os
import time
import uuid
from sqlalchemy import select, func
from .db import init, session, ResearchState, Instrument, Job, Candle, now
from .universe import discover, load_registry, status
from .service import ingest, analyze
from .quant import HORIZON

TF='15m'
STEP=900
_COLLECTION_TURN=0


def cache_analysis(symbol):
    result=analyze(symbol,TF)
    result.pop('candles',None); result.pop('overlays',None); result.pop('model',None)
    with session() as s:
        row=s.get(ResearchState,symbol)
        if row: row.analysis=json.dumps(result,allow_nan=False)


def schedule_training():
    with session() as s:
        active=list(s.scalars(select(Job).where(Job.status.in_(['queued','running']))))
        occupied={j.symbol for j in active}
        capacity=max(0,20-len(active))
        states=s.scalars(select(ResearchState).join(Instrument,Instrument.symbol==ResearchState.symbol)
            .where(ResearchState.last_bar>0).order_by(ResearchState.attempted_bar,ResearchState.symbol))
        for row in states:
            if capacity<=0: break
            if row.symbol in occupied: continue
            # Never retry the same failed dataset or train every price tick.
            if row.attempted_bar:
                new_bars=s.scalar(select(func.count()).select_from(Candle).where(Candle.symbol==row.symbol,Candle.timeframe==TF,Candle.time>row.attempted_bar,Candle.time<=row.last_bar))
                if new_bars<HORIZON: continue
            s.add(Job(id=uuid.uuid4().hex,kind='auto_train',symbol=row.symbol,timeframe=TF,
                status='queued',created=now(),updated=now(),detail='Automatic training queued; completed candles only'))
            row.attempted_bar=row.last_bar
            occupied.add(row.symbol); capacity-=1


def collect_one():
    global _COLLECTION_TURN
    with session() as s:
        due=select(ResearchState).join(Instrument,Instrument.symbol==ResearchState.symbol).where(ResearchState.next_fetch<=now())
        # Alternate refreshing existing charts and bootstrapping new ones. A large
        # undiscovered history backlog must not starve already monitored charts.
        preferred=ResearchState.last_bar>0 if _COLLECTION_TURN%2==0 else ResearchState.last_bar==0
        row=s.scalar(due.where(preferred).order_by(ResearchState.next_fetch,ResearchState.symbol).limit(1))
        if row is None: row=s.scalar(due.order_by(ResearchState.next_fetch,ResearchState.symbol).limit(1))
        _COLLECTION_TURN+=1
        if not row: return False
        symbol=row.symbol; previous=row.last_bar
        row.next_fetch=now()+300
    status('collector',{'state':'collecting','symbol':symbol,'timeframe':TF})
    try:
        # Bootstrap once, then request enough bars to cover elapsed time, including outages.
        count=10000 if not previous else min(10000,max(100,int((now()-previous)/STEP)+30))
        meta=ingest(symbol,TF,count)
        with session() as s:
            row=s.get(ResearchState,symbol)
            row.last_bar=meta['last']; row.next_fetch=now()+STEP
            row.detail='Completed candles refreshed; automatic training waits for new labels'
        cache_analysis(symbol)
    except Exception as e:
        # Provider responses do not contain credentials; avoid recording arbitrary network URLs.
        detail=str(e)[:400] if isinstance(e,ValueError) else 'Collection failed; retry in one hour'
        with session() as s:
            row=s.get(ResearchState,symbol); row.next_fetch=now()+3600; row.detail=detail
        status('collector',{'state':'retrying','symbol':symbol,'detail':detail})
    return True


def main():
    init()
    if os.getenv('CONTINUOUS_RESEARCH','1')!='1':
        status('collector',{'state':'disabled'})
        while True: time.sleep(30)
    while True:
        try:
            if not os.getenv('UPSTOX_ACCESS_TOKEN','').strip():
                status('collector',{'state':'missing token','detail':'Set UPSTOX_ACCESS_TOKEN and restart'})
                time.sleep(30); continue
            if now()-status('universe').get('discovered_at',0)>86400:
                discover()
            else: load_registry()
            schedule_training()
            if not collect_one(): time.sleep(5)
        except Exception:
            status('collector',{'state':'retrying','detail':'Universe/collector unavailable; retry in 60 seconds'})
            time.sleep(60)

if __name__=='__main__': main()
