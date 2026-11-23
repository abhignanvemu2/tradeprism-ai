import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import pandas as pd
import pytest
from sqlalchemy import select
from fastapi.testclient import TestClient
from tradeprism.api import app
from tradeprism.scope import SYMBOLS, TIMEFRAMES
from tradeprism.db import session, engine, Forecast, ForecastResult, ForecastProgress, ForecastObservation, Instrument, Job, now
from tradeprism.forward import publish, resolve, observe_quotes, IST
from tradeprism.execution import evaluate
from tradeprism.ledger import history, summary
from tradeprism.quant import features, dataset
from tradeprism.training import research_frame
from test_forward import evidence, candle

HEADERS={'Authorization':'Bearer test-alice-key-at-least-24-chars'}

def test_fixed_universe_migration_and_api_restrictions():
    with session() as s:
        s.add(Instrument(symbol='UNWANTED',body='{"segment":"NSE_EQ"}'))
        for symbol,tf in [('UNWANTED','5m'),('AXISBANK','1m'),('AXISBANK','5m')]:
            s.add(Job(id=symbol+tf,symbol=symbol,timeframe=tf,status='queued',kind='train',created=now(),updated=now(),detail='test'))
    with TestClient(app) as c:
        rows=c.get('/instruments',headers=HEADERS).json()
        assert len(rows)==100 and {r['symbol'] for r in rows}==set(SYMBOLS)
        assert all(r['timeframes']==['5m','15m'] for r in rows)
        assert c.get('/stocks?limit=200',headers=HEADERS).json()['total']==100
        for symbol,tf in [('UNWANTED','5m'),('AXISBANK','1m'),('AXISBANK','1h')]:
            assert c.post('/jobs',headers=HEADERS,json={'kind':'train','symbol':symbol,'timeframe':tf}).status_code==422
        assert c.get('/scanner',headers=HEADERS).status_code==404
    with session() as s:
        assert s.get(Job,'AXISBANK5m').status=='queued'
        assert s.get(Job,'UNWANTED5m').status==s.get(Job,'AXISBANK1m').status=='cancelled'


def test_confirmed_rename_mapping_and_missing_stocks_are_not_replaced(monkeypatch):
    from tradeprism.universe import discover,load_registry
    class Response:
        content=json.dumps([{'segment':'NSE_EQ','instrument_type':'EQ','trading_symbol':symbol,
                            'instrument_key':'NSE_EQ|'+symbol,'name':symbol} for symbol in ('ETERNAL','LTM','UNWANTED')]).encode()
        def raise_for_status(self):pass
    monkeypatch.setattr('tradeprism.universe.httpx.get',lambda *a,**k:Response())
    found=discover()
    assert set(found)=={'ZOMATO','LTIM'}
    assert found['ZOMATO']['trading_symbol']=='ETERNAL'
    assert len(load_registry())==2
    with session() as s:
        assert len(list(s.scalars(select(Instrument))))==100
        assert 'instrument_key' not in json.loads(s.get(Instrument,'TATAMOTORS').body)


def test_later_bar_entry_and_short_target_are_confirmed():
    a,stamp=evidence();a['research_plan']={'direction':'SHORT','entry':100,'stop':105,'target':90}
    identifier=publish(a,stamp); first=a['data_timestamp']+1800
    candle(first,o=103,h=104,l=101,c=102)
    resolve('AXISBANK','15m',{},first+900)
    with session() as s:assert json.loads(s.get(ForecastProgress,identifier).body)['event']=='waiting_entry'
    candle(first+900,o=101,h=103,l=98,c=99)
    resolve('AXISBANK','15m',{},first+1800)
    with session() as s:
        assert s.get(ForecastResult,identifier) is None
        assert json.loads(s.get(ForecastProgress,identifier).body)['event']=='open'
    candle(first+1800,o=99,h=101,l=89,c=90)
    resolve('AXISBANK','15m',{},first+2700)
    with session() as s:
        r=s.get(ForecastResult,identifier);assert r.event=='target' and r.net_return>0
        assert json.loads(r.body)['entered_at']==first+900


def test_gap_entry_uses_actual_open_and_short_gap_stop_is_adverse():
    p={'direction':'SHORT','entry':100,'stop':105,'target':90}
    bars=[{'time':0,'open':98,'high':99,'low':96,'close':97}, {'time':300,'open':110,'high':112,'low':109,'close':110}]
    result=evaluate(bars,p,0,600,300,600)
    assert result['fill_price']==98 and result['exit']==110 and result['net_return']<-.12
    beyond=evaluate([{'time':0,'open':89,'high':91,'low':88,'close':90}],p,0,300,300,300)
    assert beyond['event']=='unfilled' and not beyond['entered']


def test_missing_candle_backfill_recovers_result_without_false_unfilled():
    a,stamp=evidence();identifier=publish(a,stamp);first=a['data_timestamp']+1800
    candle(first+900,h=112)
    resolve('AXISBANK','15m',{},first+1800)
    with session() as s:
        assert s.get(ForecastResult,identifier) is None
        assert json.loads(s.get(ForecastProgress,identifier).body)['event']=='awaiting_data'
    candle(first)
    resolve('AXISBANK','15m',{},first+1800)
    with session() as s:assert s.get(ForecastResult,identifier).event=='target'


def test_live_observations_keep_entry_and_target_even_if_latest_tick_falls_back():
    a,stamp=evidence();identifier=publish(a,stamp);first=a['data_timestamp']+1800
    def q(price,t):return ('AXISBANK',{'price':price,'trade_time':t,'received':t+.1})
    observe_quotes([q(100,first+1),q(111,first+2),q(101,first+3)])
    observe_quotes([q(94,first-.5)])  # earlier observations cannot invent an exit
    with session() as s:
        rows=list(s.scalars(select(ForecastObservation)))
        assert {json.loads(r.body)['event'] for r in rows}=={'entry_observed','target_observed'}
        assert s.get(ForecastResult,identifier) is None  # tick observations do not fabricate confirmed wins
    candle(first,h=112);resolve('AXISBANK','15m',{},first+900)
    with session() as s:assert s.get(ForecastResult,identifier).event=='target'


def test_old_one_bar_forecasts_retain_their_recorded_rules():
    a,stamp=evidence();identifier=publish(a,stamp);first=a['data_timestamp']+1800
    with session() as s:
        f=s.get(Forecast,identifier);body=json.loads(f.body);body['strategy']='long-breakout-v3-future-entry'
        # Create separate old-version fixture; never update immutable original evidence.
        s.add(Forecast(id='old',symbol='AXISBANK',timeframe='15m',created=stamp,entry_time=first,end_time=first+10800,probability=.7,qualified=0,body=json.dumps(body)))
    candle(first,o=101,h=102,l=99,c=101)
    resolve('AXISBANK','15m',{},first+900)
    with session() as s:
        assert s.get(ForecastResult,'old').event=='unfilled'
        assert s.get(ForecastResult,identifier) is None
        assert json.loads(s.get(ForecastProgress,identifier).body)['event']=='open'


def test_date_filters_position_pagination_and_daily_counts(monkeypatch):
    a,stamp=evidence();first=a['data_timestamp']+1800
    publish(a,stamp)
    short={**a,'research_plan':{'direction':'SHORT','entry':100,'stop':105,'target':90}}
    publish(short,stamp+1)
    candle(first,o=100,h=112,l=99,c=110);resolve('AXISBANK','15m',{},first+900)
    monkeypatch.setattr('tradeprism.ledger.now',lambda:stamp+86400)
    c=TestClient(app)
    assert c.get('/forecasts',headers=HEADERS).json()['total']==0
    assert c.get('/forecasts?date_from=2026-11-19&position=SHORT',headers=HEADERS).json()['records'][0]['position']=='SHORT'
    assert c.get('/forecasts?date_from=2026-11-19&limit=1',headers=HEADERS).json()['total']==2
    assert c.get('/forecasts?date_from=2026-11-19&symbol=TCS',headers=HEADERS).json()['total']==0
    assert c.get('/forecasts?date_from=2026-11-20&date_to=2026-11-19',headers=HEADERS).status_code==422
    d=c.get('/dashboard?date_from=2026-11-19',headers=HEADERS).json()['today']
    assert (d['long'],d['short'],d['wins'],d['losses'],d['closed'])==(1,1,1,1,2)
    # IST midnight: a forecast issued at 00:00 IST is the next day's record.
    from tradeprism.ledger import bounds
    start,end=bounds('2026-11-19','2026-11-19')
    assert datetime.fromtimestamp(start,IST).hour==0 and end-start==86400


def test_session_close_caps_new_forecast_horizon():
    a,stamp=evidence();a['data_timestamp']=datetime(2026,11,19,14,30,tzinfo=IST).timestamp()
    identifier=publish(a,a['data_timestamp']+910)
    with session() as s:
        f=s.get(Forecast,identifier)
        assert datetime.fromtimestamp(f.end_time,IST).strftime('%H:%M')=='15:30'
    a['data_timestamp']+=1800
    assert publish(a,a['data_timestamp']+910) is None


def test_features_reset_at_split_and_labels_never_cross_boundary():
    from test_quant import frame
    d=frame(500);start=datetime(2026,10,1,9,15,tzinfo=IST)
    d['time']=[(start+timedelta(days=i//25,minutes=(i%25)*15)).timestamp() for i in range(len(d))]
    d.loc[250:,['open','high','low','close']]*=.5
    research=research_frame(d,{'asset':'equity'},'15m');f=features(research)
    assert f.attrs['discontinuities'][0]['ratio']<.6
    pd.testing.assert_series_equal(f.iloc[300][['ema20','atr']].astype(float),features(d.iloc[250:]).iloc[50][['ema20','atr']],check_names=False)
    samples,_=dataset(f,.01)
    assert samples and {r['direction'] for r in samples}=={'LONG','SHORT'}
    assert all(not(r['index']<250<=r['label_end']) for r in samples)


def test_sqlite_wal_and_four_concurrent_writer_processes():
    with engine.connect() as c:
        assert c.exec_driver_sql('PRAGMA journal_mode').scalar()=='wal'
        assert c.exec_driver_sql('PRAGMA busy_timeout').scalar()==30000
    script="""import sys
from tradeprism.db import session,Job,now,engine
for i in range(20):
 with session(write=True) as s:
  s.add(Job(id=sys.argv[1]+'-'+str(i),symbol='AXISBANK',timeframe='5m',kind='test',status='completed',created=now(),updated=now(),detail='isolated concurrent writer test'))
engine.dispose()
"""
    def run(i):return subprocess.run([sys.executable,'-c',script,str(i)],env=os.environ.copy(),capture_output=True,text=True,timeout=60)
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(run,range(4)))
    assert all(r.returncode==0 for r in results),[r.stderr for r in results]
    with session() as s:assert len(list(s.scalars(select(Job))))==80
