import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from tradeprism.api import app
from tradeprism.db import session, Candle, Record, now
from tradeprism.service import append, advance_paper, analyze, records

ALICE={'Authorization':'Bearer test-alice-key-at-least-24-chars'}
BOB={'Authorization':'Bearer test-bob-key-at-least-24-chars'}
client=TestClient(app)

def test_auth_required_and_empty_states_are_honest():
    assert client.get('/instruments').status_code==401
    r=client.get('/analysis/AXISBANK',headers=ALICE).json()
    assert r['candles']==[] and r['decision']=='NO TRADE' and r['probability'] is None
    assert r['state']=='Market data unavailable'

def test_workspace_isolation_and_history_isolation():
    r=client.put('/workspace/AXISBANK',headers=ALICE,json={'drawings':[{'id':'private'}]})
    assert r.status_code==200
    assert client.get('/workspace/AXISBANK',headers=BOB).json()['drawings']==[]
    client.post('/signals/AXISBANK',headers=ALICE)
    assert len(client.get('/history/signal',headers=ALICE).json())==1
    assert client.get('/history/signal',headers=BOB).json()==[]

def test_immutable_records_database_enforcement():
    with session() as s: append(s,'signal','alice','AXISBANK',{'decision':'NO TRADE'},'immutable')
    for statement in ["UPDATE records SET body='{}' WHERE id='immutable'","DELETE FROM records WHERE id='immutable'"]:
        with pytest.raises(DatabaseError):
            with session() as s:s.execute(text(statement))

def test_provider_failure_job_records_error_not_fake_data(monkeypatch):
    from tradeprism.worker import run_one
    from tradeprism.providers import DataUnavailable
    def fail(*args,**kwargs):raise DataUnavailable('Provider unavailable')
    monkeypatch.setattr('tradeprism.worker.ingest',fail)
    client.post('/jobs',headers=ALICE,json={'kind':'ingest','symbol':'BTC-USD'})
    assert run_one()
    job=client.get('/jobs',headers=ALICE).json()[0]
    assert job['status']=='failed' and job['detail']=='Provider unavailable'
    assert client.get('/analysis/BTC-USD',headers=ALICE).json()['candles']==[]

def test_job_deduplication():
    payload={'kind':'ingest','symbol':'BTC-USD'}
    a=client.post('/jobs',headers=ALICE,json=payload).json()
    b=client.post('/jobs',headers=ALICE,json=payload).json()
    assert a['id']==b['id']

def test_missing_llm_is_not_canned_ai():
    r=client.post('/explain',headers=ALICE,json={'symbol':'BTC-USD','question':'Explain'})
    assert r.status_code==503

def add_candle(s,t,o=99,h=101,l=98,c=100):
    s.add(Candle(symbol='BTC-USD',timeframe='1h',time=t,open=o,high=h,low=l,close=c,volume=100,source='isolated_test_fixture',fetched_at=now()))

def test_replay_hides_future_candles_and_prediction():
    with session() as s:
        for t in range(100):add_candle(s,t*3600)
    a=analyze('BTC-USD','1h',until=70*3600)
    assert len(a['candles'])==71 and a['window_end']==70*3600
    assert 'prediction' not in a and a['replay']

def test_paper_forward_only_and_idempotent():
    created=10000
    with session() as s:
        append(s,'paper','alice','BTC-USD',{'owner':'alice','timeframe':'1h','created':created,'direction':'LONG','entry':100,'stop':95,'target':110,'quantity':2,'cost_bps_per_side':15,'fx':1,'multiplier':1,'entry_deadline':20000,'exit_deadline':80000},'paper-test')
        # This bar precedes scenario creation and must never fill it.
        add_candle(s,9000,h=120,l=90)
        add_candle(s,11000,h=101,l=98)
        add_candle(s,14600,o=90,h=94,l=89,c=92)
    advance_paper()
    events=records('paper_event',owner='alice')
    assert all(x['bar_time']>created for x in events)
    stop=next(x for x in events if x['event']=='stop')
    assert stop['price']==90 and stop['net_pnl'] < -20
    advance_paper()
    assert len(records('paper_event',owner='alice'))==len(events)

def test_risk_and_paper_require_provider_metadata():
    r=client.post('/paper',headers=ALICE,json={'symbol':'AXISBANK','entry':100,'stop':95,'target':110,'equity':10000})
    assert r.status_code==409
