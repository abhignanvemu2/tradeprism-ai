import json
from datetime import datetime, timedelta
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DatabaseError
from tradeprism.db import session, Forecast, ForecastResult, Candle
from tradeprism.forward import publish, resolve, dashboard, metrics, IST
from tradeprism.quant import VERSION


def evidence(probability=.7):
    bar=datetime(2026,11,19,9,15,tzinfo=IST).timestamp()
    a={'symbol':'AXISBANK','timeframe':'15m','source':'upstox','state':'Completed historical candles — polling',
       'data_timestamp':bar,'research_plan':{'direction':'LONG','entry':100,'stop':95,'target':110},
       'metadata':{'stock_group':'EQ'},'prediction':{'probability':probability},
       'model':{'version':'test-model','strategy':VERSION,'trained_at':bar-100,'threshold':.60,
           'selected_test':{'trades':35,'net_expectancy':.01},'test_brier':.09,'baseline_test_brier':.10}}
    return a,bar+900+10


def candle(t,o=99,h=101,l=98,c=100):
    with session() as s:
        s.add(Candle(symbol='AXISBANK',timeframe='15m',time=t,open=o,high=h,low=l,close=c,volume=100,source='test-only',fetched_at=t+900))


def test_forecast_requires_future_entry_and_current_model():
    a,stamp=evidence()
    assert publish(a,stamp=a['data_timestamp']+899) is None
    assert publish(a,stamp=a['data_timestamp']+1800) is None
    a['model']['strategy']='old'
    assert publish(a,stamp) is None
    a['model']['strategy']=VERSION
    assert publish(a,stamp) is not None
    assert publish(a,stamp+1) is None
    with session() as s:
        f=s.scalar(select(Forecast)); assert f.created<f.entry_time


def test_no_early_expiry_and_net_success_not_merely_target_hit():
    a,stamp=evidence(); identifier=publish(a,stamp)
    first=a['data_timestamp']+1800
    candle(first)
    resolve('AXISBANK','15m',{},first+900)
    with session() as s: assert s.get(ForecastResult,identifier) is None
    for i in range(1,12): candle(first+900*i,c=102)
    resolve('AXISBANK','15m',{},first+900*12)
    with session() as s:
        r=s.get(ForecastResult,identifier)
        assert r.event=='expired' and r.net_return>0
    d=dashboard(first+900*12)
    assert d['today']['net_win_rate']==1 and d['today']['target_hit_rate']==0
    assert d['today']['closed']==1


def test_same_bar_stop_and_immutable_outcome():
    a,stamp=evidence(); identifier=publish(a,stamp)
    first=a['data_timestamp']+1800
    candle(first,h=112,l=94)
    resolve('AXISBANK','15m',{},first+900)
    resolve('AXISBANK','15m',{},first+900)
    with session() as s:
        r=s.get(ForecastResult,identifier); assert r.event=='stop' and r.net_return<0
    with pytest.raises(DatabaseError):
        with session() as s: s.execute(update(ForecastResult).values(event='target'))
    with pytest.raises(DatabaseError):
        with session() as s: s.execute(update(Forecast).values(probability=.99))


@pytest.mark.parametrize('mode',['gap','revision','unfilled'])
def test_gaps_revisions_unfilled_are_not_reported_as_losses(mode):
    a,stamp=evidence();identifier=publish(a,stamp);first=a['data_timestamp']+1800
    if mode=='gap':candle(first+900)
    if mode=='unfilled':
        for i in range(3):candle(first+900*i,o=97,h=99,l=96,c=98)
    resolve('AXISBANK','15m',{'reconciled_at':stamp+1} if mode=='revision' else {},first+2700)
    with session() as s:
        r=s.get(ForecastResult,identifier)
        if mode=='gap':assert r is None
        else:
            assert r.event=={'revision':'invalidated','unfilled':'unfilled'}[mode]
            assert r.net_return is None


def test_empty_history_and_ist_day_filter():
    a,stamp=evidence()
    assert dashboard(stamp)['today']['net_win_rate'] is None
    publish(a,stamp); first=a['data_timestamp']+1800
    candle(first,h=112);resolve('AXISBANK','15m',{},first+900)
    assert dashboard(first+900)['today']['wins']==1
    assert dashboard(first+86400)['today']['issued']==0


def test_failed_quality_gate_is_recorded_as_unqualified_research():
    a,stamp=evidence(.15); identifier=publish(a,stamp)
    with session() as s: assert s.get(Forecast,identifier).qualified==0


def test_training_forecast_horizon_matches_delayed_entry(monkeypatch):
    from tradeprism.quant import dataset, features, HORIZON, ENTRY_DELAY
    from test_quant import frame
    examples,_=dataset(features(frame(1000)),.01)
    assert examples and all(r['label_end']==r['index']+HORIZON+ENTRY_DELAY for r in examples)


def test_dashboard_requires_authentication():
    from fastapi.testclient import TestClient
    from tradeprism.api import app
    c=TestClient(app)
    assert c.get('/dashboard').status_code==401
    r=c.get('/dashboard',headers={'Authorization':'Bearer test-alice-key-at-least-24-chars'})
    assert r.status_code==200 and r.json()['today']['net_win_rate'] is None


def test_additional_training_queue_uses_each_timeframe_and_is_bounded():
    from tradeprism.db import Instrument, ChartTrack, Job
    from tradeprism.continuous import schedule_additional
    with session() as s:
        s.add(Instrument(symbol='AXISBANK',body=json.dumps({'segment':'NSE_EQ','instrument_key':'NSE_EQ|AXISBANK'})))
        for tf in ('1m','5m','1h','1d'):
            s.add(ChartTrack(key='AXISBANK:'+tf,symbol='AXISBANK',timeframe=tf,last_bar=100000))
    schedule_additional(); schedule_additional()
    with session() as s:
        jobs=list(s.scalars(select(Job)))
        assert {j.timeframe for j in jobs}=={'5m'} and len(jobs)==1


def test_full_forecast_audit_history_is_paginated():
    from fastapi.testclient import TestClient
    from tradeprism.api import app
    a,stamp=evidence(); identifier=publish(a,stamp)
    c=TestClient(app); headers={'Authorization':'Bearer test-alice-key-at-least-24-chars'}
    response=c.get('/forecasts?limit=1&date_from=2026-11-19',headers=headers).json()
    assert response['total']==1 and response['records'][0]['id']==identifier
    assert response['records'][0]['forecast']['model_version']=='test-model'
    assert c.get('/forecasts?offset=1&date_from=2026-11-19',headers=headers).json()['records']==[]
    assert c.get('/forecasts').status_code==401


def test_concurrent_publication_cannot_create_overlapping_forecasts():
    from concurrent.futures import ThreadPoolExecutor
    a,stamp=evidence()
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids=list(pool.map(lambda _:publish(a,stamp),range(2)))
    assert sum(x is not None for x in ids)==1
    with session() as s: assert len(list(s.scalars(select(Forecast))))==1


def test_monitor_coverage_is_a_list_for_the_dashboard():
    from fastapi.testclient import TestClient
    from tradeprism.api import app
    response=TestClient(app).get('/monitor',headers={'Authorization':'Bearer test-alice-key-at-least-24-chars'}).json()
    assert isinstance(response['coverage'],list)
    assert {c['timeframe'] for c in response['coverage']}=={'5m','15m'}


def test_discovery_creates_all_chart_tracks_and_preserves_existing_history(monkeypatch):
    from tradeprism.universe import discover
    from tradeprism.db import ChartTrack, ResearchState
    class Response:
        def __init__(self,exchange):
            self.content=json.dumps([{'segment':exchange+'_EQ','instrument_type':'EQ' if exchange=='NSE' else 'A',
                'trading_symbol':'AXISBANK','instrument_key':exchange+'_EQ|TEST'}]).encode()
        def raise_for_status(self):pass
    monkeypatch.setattr('tradeprism.universe.httpx.get',lambda url,**kw:Response('NSE' if '/NSE.' in url else 'BSE'))
    assert len(discover())==1
    with session() as s:
        assert len(list(s.scalars(select(ChartTrack))))==100
        s.get(ResearchState,'AXISBANK').last_bar=12345
    discover()
    with session() as s:
        assert s.get(ResearchState,'AXISBANK').last_bar==12345
        assert len(list(s.scalars(select(ChartTrack))))==100
