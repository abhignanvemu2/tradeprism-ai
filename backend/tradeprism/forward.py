"""Prospective model predictions. Never reconstruct live wins from a later model.
One unresolved forecast per symbol/timeframe; all forecasts are research only.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import select, func, text
from .db import Forecast, ForecastResult, ForecastProgress, ForecastObservation, Candle, ResearchState, ChartTrack, session, now
from .quant import HORIZON, ENTRY_DELAY, VERSION
from .scope import SYMBOLS, TIMEFRAMES
from .execution import evaluate, TERMINAL, ENTRY_BARS
from .ml import wilson
from .providers import SECONDS

IST=ZoneInfo('Asia/Kolkata')


def quality_reasons(analysis):
    report=analysis.get('model') or {}
    p=(analysis.get('prediction') or {}).get('probability')
    direction=(analysis.get('research_plan') or {}).get('direction','LONG')
    results=(report.get('direction_test') or {}).get(direction) or report.get('selected_test') or {}
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
    # swing outcomes, an exchange holiday calendar or probabilities for manual plans.
    if tf not in TIMEFRAMES or analysis['symbol'] not in SYMBOLS: return None
    report=analysis.get('model') or {}
    p=(analysis.get('prediction') or {}).get('probability')
    plan=analysis.get('research_plan')
    if report.get('strategy')!=VERSION or report.get('trained_at',stamp+1)>stamp: return None
    if p is None or not math.isfinite(p) or not 0<=p<=1 or not plan: return None
    if analysis.get('state')!='Completed historical candles — polling': return None
    long=plan.get('direction','LONG')=='LONG'
    if not (0<plan['stop']<plan['entry']<plan['target'] if long else 0<plan['target']<plan['entry']<plan['stop']):return None
    bar=analysis.get('data_timestamp',0)
    entry=bar+(1+ENTRY_DELAY)*step
    end=entry+HORIZON*step
    local=datetime.fromtimestamp(bar,IST)
    close=local.replace(hour=15,minute=30,second=0,microsecond=0).timestamp()
    end=min(end,close)
    if not bar+step<=stamp<entry or entry>=end: return None
    if (analysis.get('metadata') or {}).get('stock_group') not in (None,'EQ','A','B','X'): return None
    identifier=hashlib.sha256(f'{analysis["symbol"]}|{tf}|{bar}|{VERSION}|{plan.get('direction','LONG')}'.encode()).hexdigest()
    reasons=quality_reasons(analysis)
    body={'model_version':report['version'],'strategy':VERSION,'plan':plan,'source_bar':bar,
        'source':analysis.get('source'),'entry_window_bars':ENTRY_BARS,'cost_bps_per_side':15,'qualification_reasons':reasons,
        'target':report.get('target'),'status':'Research forecast, not a live order',
        'assumptions':'One waiting bar, then a three-bar stop-entry window; adverse gaps fill at open unless beyond target. Candle stop-first ambiguity; expiry at horizon/session close; fixed 15 bps per side.'}
    with session() as s:
        evidence_lock(s,analysis['symbol'],tf)
        issued=now() if realtime else stamp
        if issued>=entry: return None
        if s.get(Forecast,identifier): return None
        pending=list(s.scalars(select(Forecast).outerjoin(ForecastResult,ForecastResult.id==Forecast.id)
            .where(Forecast.symbol==analysis['symbol'],Forecast.timeframe==tf,ForecastResult.id.is_(None))))
        if any(json.loads(x.body)['plan'].get('direction','LONG')==plan.get('direction','LONG') for x in pending):return None
        s.add(Forecast(id=identifier,symbol=analysis['symbol'],timeframe=tf,created=issued,
            entry_time=entry,end_time=end,probability=p,qualified=int(not reasons),body=json.dumps(body,allow_nan=False)))
    return identifier


def resolve(symbol,tf,meta,stamp=None):
    stamp=now() if stamp is None else stamp; step=SECONDS[tf]
    with session() as s:
        evidence_lock(s,symbol,tf)
        pending=list(s.scalars(select(Forecast).outerjoin(ForecastResult,ForecastResult.id==Forecast.id)
            .where(Forecast.symbol==symbol,Forecast.timeframe==tf,ForecastResult.id.is_(None))))
        for f in pending:
            body=json.loads(f.body)
            if meta.get('reconciled_at',0)>f.created:
                result={'event':'invalidated','reason':'Provider history revised after forecast','event_time':stamp}
            else:
                rows=list(s.scalars(select(Candle).where(Candle.symbol==symbol,Candle.timeframe==tf,
                    Candle.time>=f.entry_time,Candle.time<f.end_time).order_by(Candle.time)))
                candles=[{k:getattr(c,k) for k in ('time','open','high','low','close','volume','source')} for c in rows]
                result=evaluate(candles,body['plan'],f.entry_time,f.end_time,step,stamp,
                    body.get('cost_bps_per_side',15),legacy=body.get('strategy')!=VERSION)
                if result['event'] not in TERMINAL and stamp>f.end_time+86400:
                    result.update(event='data_gap',reason='Incomplete outcome history after one day; no assumed win/loss',event_time=f.end_time)
            progress=s.get(ForecastProgress,f.id)
            value=json.dumps(result,allow_nan=False)
            if progress:progress.updated=stamp;progress.body=value
            else:s.add(ForecastProgress(id=f.id,updated=stamp,body=value))
            if result['event'] in TERMINAL:
                s.add(ForecastResult(id=f.id,resolved_at=stamp,event_time=result['event_time'],event=result['event'],
                    net_return=result.get('net_return'),body=value))


def observe_quotes(samples):
    """Keep entry/exit observations from every received tick, not just last-price snapshots.
    They remain provisional: missed ticks and outages require candle confirmation.
    """
    if not samples:return
    symbols={symbol for symbol,_ in samples}
    with session() as s:
        evidence_lock(s,'live-observations','all')
        forecasts=list(s.scalars(select(Forecast).outerjoin(ForecastResult,ForecastResult.id==Forecast.id)
            .where(ForecastResult.id.is_(None),Forecast.symbol.in_(symbols),Forecast.timeframe.in_(TIMEFRAMES))))
        for f in forecasts:
            b=json.loads(f.body)
            if b.get('strategy')!=VERSION:continue
            p=b['plan'];long=p['direction']=='LONG'
            existing=list(s.scalars(select(ForecastObservation).where(ForecastObservation.forecast_id==f.id)))
            events={json.loads(x.body)['event'] for x in existing}
            progress=s.get(ForecastProgress,f.id)
            confirmed=json.loads(progress.body) if progress else {}
            entered='entry_observed' in events or confirmed.get('entered',False)
            last_trade=max([json.loads(x.body)['trade_time'] for x in existing]+[confirmed.get('entered_at') or 0])
            deadline=min(f.end_time,f.entry_time+ENTRY_BARS*SECONDS[f.timeframe])
            for symbol,q in sorted(samples,key=lambda x:x[1]['trade_time']):
                if q['trade_time']<last_trade:continue
                if symbol!=f.symbol or q['trade_time']<max(f.entry_time,f.created) or q['trade_time']>=f.end_time:continue
                if q['received']-q['trade_time']>30:continue
                price=q['price']; event=None
                if not entered and q['trade_time']<deadline:
                    reached=p['entry']<=price<p['target'] if long else p['target']<price<=p['entry']
                    if reached:event='entry_observed';entered=True
                elif entered and not events.intersection({'target_observed','stop_observed'}):
                    if (price<=p['stop'] if long else price>=p['stop']):event='stop_observed'
                    elif (price>=p['target'] if long else price<=p['target']):event='target_observed'
                if event and event not in events:
                    events.add(event);last_trade=q['trade_time']
                    s.add(ForecastObservation(id=f.id+':'+event,forecast_id=f.id,observed_at=q['received'],
                        body=json.dumps({'event':event,'price':price,'trade_time':q['trade_time'],
                        'basis':'Live LTPC observation; awaiting completed-candle confirmation'})))


def refresh_pending():
    from .service import metadata
    with session() as s:
        pairs=s.execute(select(Forecast.symbol,Forecast.timeframe).outerjoin(ForecastResult,ForecastResult.id==Forecast.id)
            .where(ForecastResult.id.is_(None),Forecast.symbol.in_(SYMBOLS),Forecast.timeframe.in_(TIMEFRAMES)).distinct()).all()
    for symbol,tf in pairs:resolve(symbol,tf,metadata(symbol,tf) or {})


def metrics(items):
    closed=[x for x in items if x.get('net_return') is not None]
    wins=sum(x['net_return']>0 for x in closed); n=len(closed)
    return {'long':sum(x.get('plan',{}).get('direction','LONG')=='LONG' for x in items),'short':sum(x.get('plan',{}).get('direction')=='SHORT' for x in items),'issued':len(items),'closed':n,'wins':wins,'losses':sum(x['net_return']<0 for x in closed),
        'breakeven':sum(x['net_return']==0 for x in closed),'pending':sum(x['event'] in ('pending','waiting_entry','awaiting_data','open') for x in items),'entered':sum(x.get('entered',False) or x.get('net_return') is not None for x in items),'open':sum(x['event']=='open' for x in items),'waiting_entry':sum(x['event']=='waiting_entry' for x in items),'awaiting_data':sum(x['event']=='awaiting_data' for x in items),
        'unfilled':sum(x['event']=='unfilled' for x in items),
        'unverifiable':sum(x['event'] in ('invalidated','data_gap') for x in items),
        'net_win_rate':wins/n if n else None,'win_rate_95ci':wilson(wins,n),
        'target_hit_rate':sum(x['event']=='target' for x in closed)/n if n else None,
        'mean_net_return':sum(x['net_return'] for x in closed)/n if n else None}


def dashboard(stamp=None):
    from .ledger import summary
    return summary(stamp=stamp)
