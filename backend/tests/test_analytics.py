import json
from datetime import datetime
from fastapi.testclient import TestClient
from tradeprism.api import app
from tradeprism.db import Forecast, ForecastResult, ForecastProgress, session
from tradeprism.ledger import IST
from tradeprism.analytics import charts, STATUSES

AUTH={'Authorization':'Bearer test-alice-key-at-least-24-chars'}

def insert(id,event='waiting_entry',net=None,day='2026-11-25',symbol='AXISBANK',position='LONG',tf='5m',qualified=1):
    stamp=datetime.fromisoformat(day+'T10:00:00').replace(tzinfo=IST).timestamp()
    entered=event=='open' or net is not None
    with session() as s:
        s.add(Forecast(id=id,symbol=symbol,timeframe=tf,created=stamp,entry_time=stamp+600,end_time=stamp+3600,
                       probability=.6,qualified=qualified,body=json.dumps({'plan':{'direction':position}})))
        body=json.dumps({'event':event,'entered':entered})
        if event in ('waiting_entry','open','awaiting_data'):
            s.add(ForecastProgress(id=id,updated=stamp,body=body))
        else:s.add(ForecastResult(id=id,resolved_at=stamp,event_time=stamp,event=event,net_return=net,body=body))

def test_all_outcomes_are_exclusive_and_win_rate_excludes_nontrades():
    for i,(event,net) in enumerate([('target',.02),('stop',-.01),('expired',0),('open',None),('waiting_entry',None),('unfilled',None),('awaiting_data',None),('data_gap',None)]):insert(str(i),event,net)
    report=charts('2026-11-25','2026-11-25');n=report['totals']
    assert n['forecasts']==8 and n['entered']==4 and n['closed']==3
    assert all(n[k]==1 for k in STATUSES)
    assert n['win_rate']==1/3
    assert report['stocks'][0]['forecasts']==sum(r['forecasts'] for r in report['timeline'])==8
    assert charts('2026-11-25','2026-11-25',status='not_entered')['totals']['win_rate'] is None

def test_complete_history_filters_grouping_and_ist_boundaries():
    for i in range(510):insert(str(i),'target',.01,position='SHORT',qualified=0)
    insert('older','stop',-.01,day='2025-12-31',symbol='TCS',tf='15m')
    insert('excluded','target',.01,symbol='UNWANTED')
    assert charts(period='all')['totals']['forecasts']==511
    filtered=charts('2026-11-25','2026-11-25','AXISBANK','SHORT','5m',qualified=False,group='week')
    assert filtered['totals']['forecasts']==510 and filtered['timeline'][0]['label']=='2026-11-23'
    assert charts('2025-12-31','2025-12-31',group='month')['timeline'][0]['label']=='2025-12-01'
    assert charts('2026-11-25','2026-11-25',qualified=True)['totals']['forecasts']==0
    # A UTC evening belongs to the following IST date.
    stamp=datetime.fromisoformat('2026-11-25T19:00:00+00:00').timestamp()
    with session() as s:s.add(Forecast(id='boundary',symbol='TCS',timeframe='5m',created=stamp,entry_time=stamp+600,end_time=stamp+3600,probability=.5,qualified=0,body='{"plan":{"direction":"LONG"}}'))
    assert charts('2026-11-26','2026-11-26')['totals']['forecasts']==1

def test_api_auth_validation_and_empty_data():
    client=TestClient(app)
    assert client.get('/analytics').status_code==401
    for query in ['date_from=2026-11-26&date_to=2026-11-25','symbol=NOTVALID','timeframe=1m','group=year','status=xyz']:
        assert client.get('/analytics?'+query,headers=AUTH).status_code==422
    r=client.get('/analytics?period=all',headers=AUTH)
    assert r.status_code==200
    assert r.json()['totals']['forecasts']==0 and r.json()['totals']['win_rate'] is None
    assert r.json()['timeline']==r.json()['stocks']==[]
