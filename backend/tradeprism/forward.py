"""Prospective model predictions. Never reconstruct live wins from a later model.
One unresolved forecast per symbol/timeframe; all forecasts are research only.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, text
from .db import Forecast, ForecastResult, Candle, ResearchState, ChartTrack, session, now
from .quant import HORIZON, ENTRY_DELAY, VERSION
from .ml import wilson
from .providers import SECONDS

IST=ZoneInfo('Asia/Kolkata')


def quality_reasons(analysis):
    report=analysis.get('model') or {}
    p=(analysis.get('prediction') or {}).get('probability')
    results=report.get('selected_test') or {}
    reasons=[]
    if report.get('strategy')!=VERSION: reasons.append('Current strategy model unavailable')
    if p is None or p<report.get('threshold',.60): reasons.append('Estimated target-hit probability below research threshold')
    if results.get('trades',0)<30: reasons.append('Fewer than 30 selected holdout trades')
    if (results.get('net_expectancy') or 0)<=0: reasons.append('Positive holdout return after assumed costs not demonstrated')
    if report.get('test_brier',1)>=report.get('baseline_test_brier',0): reasons.append('Probability model has not beaten its baseline')
    if analysis.get('state')!='Completed historical candles — polling': reasons.append('Fresh completed chart data unavailable')
    return reasons


def evidence_lock(s,symbol,tf):
    # Serialize collector/worker publication and resolution for the same series.
    if s.bind.dialect.name=='sqlite':
        s.connection().exec_driver_sql('BEGIN IMMEDIATE')
    else:
        key=int(hashlib.sha256(f'{symbol}|{tf}'.encode()).hexdigest()[:15],16)
        s.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':key})


def publish(analysis, stamp=None):
    realtime=stamp is None
    stamp=now() if stamp is None else stamp
    tf=analysis['timeframe']; step=SECONDS[tf]
    # The current validated timing protocol is intraday. Do not silently invent
    # swing outcomes, a holiday calendar, shorts or probabilities for manual plans.
    if tf not in ('1m','5m','15m'): return None
    report=analysis.get('model') or {}
    p=(analysis.get('prediction') or {}).get('probability')
    plan=analysis.get('research_plan')
    if report.get('strategy')!=VERSION or report.get('trained_at',stamp+1)>stamp: return None
    if p is None or not math.isfinite(p) or not 0<=p<=1 or not plan: return None
    if analysis.get('state')!='Completed historical candles — polling': return None
    if not 0<plan['stop']<plan['entry']<plan['target']: return None
    bar=analysis.get('data_timestamp',0)
    entry=bar+(1+ENTRY_DELAY)*step
    end=entry+HORIZON*step
    local=datetime.fromtimestamp(bar,IST)
    close=local.replace(hour=15,minute=30,second=0,microsecond=0).timestamp()
    if not bar+step<=stamp<entry or end>close: return None
    if (analysis.get('metadata') or {}).get('stock_group') not in (None,'EQ','A','B','X'): return None
    identifier=hashlib.sha256(f'{analysis["symbol"]}|{tf}|{bar}|{VERSION}'.encode()).hexdigest()
    reasons=quality_reasons(analysis)
    body={'model_version':report['version'],'strategy':VERSION,'plan':plan,'source_bar':bar,
        'source':analysis.get('source'),'cost_bps_per_side':15,'qualification_reasons':reasons,
        'target':report.get('target'),'status':'Research forecast, not a live order',
        'assumptions':'One waiting bar; next full bar stop entry; gaps above entry unfilled; stop wins same-bar ambiguity; fixed 15 bps per side.'}
    with session() as s:
        evidence_lock(s,analysis['symbol'],tf)
        issued=now() if realtime else stamp
        if issued>=entry: return None
        if s.get(Forecast,identifier): return None
        pending=s.scalar(select(Forecast.id).outerjoin(ForecastResult,ForecastResult.id==Forecast.id)
            .where(Forecast.symbol==analysis['symbol'],Forecast.timeframe==tf,ForecastResult.id.is_(None)).limit(1))
        if pending: return None
        s.add(Forecast(id=identifier,symbol=analysis['symbol'],timeframe=tf,created=issued,
            entry_time=entry,end_time=end,probability=p,qualified=int(not reasons),body=json.dumps(body,allow_nan=False)))
    return identifier


def resolve(symbol, tf, meta, stamp=None):
    stamp=now() if stamp is None else stamp
    step=SECONDS[tf]
    with session() as s:
        evidence_lock(s,symbol,tf)
        pending=list(s.scalars(select(Forecast).outerjoin(ForecastResult,ForecastResult.id==Forecast.id)
            .where(Forecast.symbol==symbol,Forecast.timeframe==tf,ForecastResult.id.is_(None))))
        for f in pending:
            b=json.loads(f.body); plan=b['plan']; terminal=None; evidence=[]
            if meta.get('reconciled_at',0)>f.created:
                terminal={'event':'invalidated','reason':'Provider revision after forecast publication','event_time':stamp}
            else:
                rows=list(s.scalars(select(Candle).where(Candle.symbol==symbol,Candle.timeframe==tf,
                    Candle.time>=f.entry_time,Candle.time<f.end_time).order_by(Candle.time)))
                expected=f.entry_time
                for c in rows:
                    if c.time+step>stamp: break
                    if abs(c.time-expected)>.1:
                        terminal={'event':'data_gap','reason':'Missing expected candle; outcome cannot be verified','event_time':c.time+step}; break
                    evidence.append({k:getattr(c,k) for k in ('time','open','high','low','close','volume','source')})
                    first=c.time==f.entry_time
                    if first and (c.open>plan['entry'] or c.high<plan['entry']):
                        terminal={'event':'unfilled','event_time':c.time+step}; break
                    if c.low<=plan['stop']:
                        terminal={'event':'stop','exit':plan['stop'] if first else min(plan['stop'],c.open),'event_time':c.time+step}
                    elif c.high>=plan['target']:
                        terminal={'event':'target','exit':plan['target'],'event_time':c.time+step}
                    elif c.time+step>=f.end_time:
                        terminal={'event':'expired','exit':c.close,'event_time':c.time+step}
                    if terminal: break
                    expected+=step
                # Allow late REST backfill. Never turn missing evidence into a win/loss.
                if not terminal and stamp>f.end_time+86400:
                    terminal={'event':'data_gap','reason':'Outcome history still incomplete after one day','event_time':f.end_time}
            if terminal:
                net=None
                if 'exit' in terminal:
                    price=terminal['exit']; entry=plan['entry']; cost=b['cost_bps_per_side']/10000
                    net=(price-entry)/entry-cost*(1+price/entry)
                s.add(ForecastResult(id=f.id,resolved_at=stamp,event_time=terminal['event_time'],event=terminal['event'],
                    net_return=net,body=json.dumps({**terminal,'candles':evidence,'source':meta.get('source')},allow_nan=False)))


def metrics(items):
    closed=[x for x in items if x.get('net_return') is not None]
    wins=sum(x['net_return']>0 for x in closed); n=len(closed)
    return {'issued':len(items),'closed':n,'wins':wins,'losses':sum(x['net_return']<0 for x in closed),
        'breakeven':sum(x['net_return']==0 for x in closed),'pending':sum(x['event']=='pending' for x in items),
        'unfilled':sum(x['event']=='unfilled' for x in items),
        'unverifiable':sum(x['event'] in ('invalidated','data_gap') for x in items),
        'net_win_rate':wins/n if n else None,'win_rate_95ci':wilson(wins,n),
        'target_hit_rate':sum(x['event']=='target' for x in closed)/n if n else None,
        'mean_net_return':sum(x['net_return'] for x in closed)/n if n else None}


def dashboard(stamp=None):
    stamp=now() if stamp is None else stamp
    today=datetime.fromtimestamp(stamp,IST).date()
    start=datetime.combine(today-timedelta(days=35),datetime.min.time(),IST).timestamp()
    with session() as s:
        joined=s.execute(select(Forecast,ForecastResult).outerjoin(ForecastResult,ForecastResult.id==Forecast.id)
            .where(Forecast.created>=start).order_by(Forecast.created.desc())).all()
        all_pending=s.scalar(select(func.count()).select_from(Forecast).outerjoin(ForecastResult,ForecastResult.id==Forecast.id).where(ForecastResult.id.is_(None)))
        snapshots=list(s.scalars(select(ResearchState).where(ResearchState.last_bar>stamp-1800)))+list(s.scalars(select(ChartTrack).where(ChartTrack.last_bar>stamp-1800)))
    ledger=[]
    for f,r in joined:
        body=json.loads(f.body)
        event_time=r.event_time if r else f.created
        ledger.append({'id':f.id,'symbol':f.symbol,'timeframe':f.timeframe,'issued_at':f.created,
            'entry_time':f.entry_time,'end_time':f.end_time,'model_version':body['model_version'],
            'probability':f.probability,'qualified':bool(f.qualified),'plan':body['plan'],
            'event':r.event if r else 'pending','event_time':event_time,'net_return':r.net_return if r else None,
            'day':datetime.fromtimestamp(event_time,IST).date().isoformat()})
    monday=today-timedelta(days=today.weekday()); previous=monday-timedelta(days=7)
    previous_items=[x for x in ledger if previous.isoformat()<=x['day']<monday.isoformat()]
    today_items=[x for x in ledger if x['day']==today.isoformat()]
    daily=[]
    for ago in range(29,-1,-1):
        day=(today-timedelta(days=ago)).isoformat()
        items=[x for x in ledger if x['day']==day]
        daily.append({'day':day,**metrics(items)})
    candidates=[]; evaluated=0
    for state in snapshots:
        a=json.loads(state.analysis); prediction=a.get('prediction') or {}
        p=prediction.get('probability'); quality=a.get('quality') or {}
        tf=a.get('timeframe','15m'); step=SECONDS.get(tf,900)
        if p is None or tf not in ('1m','5m','15m') or stamp-a.get('data_timestamp',0)>step*2: continue
        evaluated+=1
        if quality.get('qualified') is not True: continue
        if not a.get('research_plan'): continue
        bar=a['data_timestamp']; entry=bar+(1+ENTRY_DELAY)*step
        close=datetime.fromtimestamp(bar,IST).replace(hour=15,minute=30,second=0,microsecond=0).timestamp()
        if not stamp<entry or entry+HORIZON*step>close: continue
        candidates.append({'symbol':state.symbol,'timeframe':tf,'probability':p,'plan':a['research_plan'],
            'model_version':prediction.get('version'),'data_timestamp':bar,'entry_time':entry,
            'holdout_expectancy':quality.get('holdout_expectancy'),'holdout_trades':quality.get('holdout_trades')})
    candidates.sort(key=lambda x:(x['holdout_expectancy'],x['probability']),reverse=True)
    candidates=[x for tf in ('1m','5m','15m') for x in [c for c in candidates if c['timeframe']==tf][:8]]
    return {'generated_at':stamp,'today':metrics(today_items),'previous_week':metrics(previous_items),
        'previous_week_start':previous.isoformat(),'previous_week_end':(monday-timedelta(days=1)).isoformat(),
        'daily':daily,'recent_forecasts':ledger[:100],'pending_total':all_pending,'evaluated_fresh':evaluated,
        'candidates':candidates[:25],'qualified_today':metrics([x for x in today_items if x['qualified']]),
        'basis':'Prospective research paper forecasts only. Net win = positive return after fixed costs. Completed results grouped by outcome date in IST; pending forecasts by issue date. Unfilled and unverifiable outcomes excluded from win-rate denominator. No portfolio-return claim.',
        'history_notice':'History begins when this feature records forecasts. Past-week results are not reconstructed using models trained later.'}
