"""Automatic completed-candle collection and bounded retraining queue.
Live price streaming is a separate process, so model fitting cannot block ticks.
"""
import json
import os
import time
import uuid
from sqlalchemy import select, func
from .db import init, session, ResearchState, Instrument, Job, Candle, ChartTrack, now
from .universe import discover, load_registry, status
from .service import ingest, analyze
from .quant import HORIZON, VERSION

TF='15m'
STEP=900
_COLLECTION_TURN=0
_ADDITIONAL_TURN=0


def cache_analysis(symbol,tf=TF):
    result=analyze(symbol,tf)
    from .forward import quality_reasons, resolve, publish
    report=result.get('model') or {}
    reasons=quality_reasons(result)
    result['quality']={'qualified':not reasons,'reasons':reasons,'holdout_expectancy':report.get('selected_test',{}).get('net_expectancy'),'holdout_trades':report.get('selected_test',{}).get('trades',0)}
    resolve(symbol,tf,result.get('metadata') or {})
    publish(result)
    result.pop('candles',None); result.pop('overlays',None); result.pop('model',None)
    with session() as s:
        row=s.get(ResearchState,symbol) if tf==TF else s.get(ChartTrack,f'{symbol}:{tf}')
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


def collect_additional():
    global _ADDITIONAL_TURN
    from .providers import SECONDS
    with session() as s:
        due=select(ChartTrack).join(Instrument,Instrument.symbol==ChartTrack.symbol).where(ChartTrack.next_fetch<=now())
        preferred=ChartTrack.last_bar>0 if _ADDITIONAL_TURN%2==0 else ChartTrack.last_bar==0
        track=s.scalar(due.where(preferred).order_by(ChartTrack.next_fetch,ChartTrack.key).limit(1))
        if track is None: track=s.scalar(due.order_by(ChartTrack.next_fetch,ChartTrack.key).limit(1))
        _ADDITIONAL_TURN+=1
        if track is None: return False
        symbol,tf,previous,key=track.symbol,track.timeframe,track.last_bar,track.key
        track.next_fetch=now()+300
    status('collector',{'state':'collecting','symbol':symbol,'timeframe':tf})
    try:
        step=SECONDS[tf]
        count=(10000 if tf in ('1m','5m') else 1800) if not previous else min(10000,max(100,int((now()-previous)/step)+30))
        meta=ingest(symbol,tf,count)
        with session() as s:
            track=s.get(ChartTrack,key); track.last_bar=meta['last']; track.next_fetch=now()+step
            track.detail='Chart refreshed; automatic model training' if tf in ('1m','5m') else 'Chart available; swing model not implemented'
        cache_analysis(symbol,tf)
    except Exception as e:
        with session() as s:
            track=s.get(ChartTrack,key); track.next_fetch=now()+3600
            track.detail=str(e)[:400] if isinstance(e,ValueError) else 'Chart collection failed; retry in one hour'
    return True


def schedule_additional():
    with session() as s:
        active=list(s.scalars(select(Job).where(Job.status.in_(['queued','running']))))
        occupied={(j.symbol,j.timeframe) for j in active}; capacity=max(0,20-len(active))
        tracks=s.scalars(select(ChartTrack).join(Instrument,Instrument.symbol==ChartTrack.symbol)
            .where(ChartTrack.last_bar>0,ChartTrack.timeframe.in_(['1m','5m']))
            .order_by(ChartTrack.attempted_bar,ChartTrack.key))
        for track in tracks:
            if not capacity: break
            if (track.symbol,track.timeframe) in occupied: continue
            count=s.scalar(select(func.count()).select_from(Candle).where(Candle.symbol==track.symbol,
                Candle.timeframe==track.timeframe,Candle.time>track.attempted_bar,Candle.time<=track.last_bar))
            if track.attempted_bar and count<HORIZON: continue
            s.add(Job(id=uuid.uuid4().hex,kind='auto_train',symbol=track.symbol,timeframe=track.timeframe,
                status='queued',created=now(),updated=now(),detail='Automatic timeframe training'))
            track.attempted_bar=track.last_bar; capacity-=1

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
            if now()-status('universe').get('discovered_at',0)>86400 or status('universe').get('chart_schema')!=2:
                discover()
            else: load_registry()
            if status('training_strategy').get('version')!=VERSION:
                with session() as s:
                    for state in s.scalars(select(ResearchState)): state.attempted_bar=0
                    for state in s.scalars(select(ChartTrack)): state.attempted_bar=0
                status('training_strategy',{'version':VERSION})
            schedule_training(); schedule_additional()
            primary=collect_one()
            additional=collect_additional()
            if not primary and not additional: time.sleep(5)
        except Exception:
            status('collector',{'state':'retrying','detail':'Universe/collector unavailable; retry in 60 seconds'})
            time.sleep(60)

if __name__=='__main__': main()
