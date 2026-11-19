import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi.testclient import TestClient
from tradeprism.api import app
from tradeprism.db import session, Instrument, LiveQuote, Forecast, ForecastResult, Job, now
from tradeprism.tables import stock_table, activity_table

HEADERS={'Authorization':'Bearer test-alice-key-at-least-24-chars'}

def stock(symbol,name,price=None,cp=100):
    with session() as s:
        s.add(Instrument(symbol=symbol,body=json.dumps({'name':name,'segment':'NSE_EQ','instrument_key':'NSE_EQ|'+symbol})))
        if price is not None:s.add(LiveQuote(symbol=symbol,price=price,previous_close=cp,trade_time=now(),received=now()))

def forecast(symbol,key,net,event='target',tf='15m',event_time=None):
    with session() as s:
        s.add(Forecast(id=key,symbol=symbol,timeframe=tf,created=now()-3600,entry_time=now()-3000,end_time=now(),probability=.7,qualified=0,body='{}'))
        if event!='pending':s.add(ForecastResult(id=key,resolved_at=now(),event_time=event_time if event_time is not None else now(),event=event,net_return=net,body='{}'))


def test_global_sort_before_pagination_and_no_results_are_null():
    stock('AAA','First company',90);stock('ZZZ','Last company',110);stock('EMPTY','No forecasts')
    forecast('AAA','loss',-.01,'stop');forecast('ZZZ','win',.02)
    result=stock_table(limit=1)
    assert result['total']==3 and result['records'][0]['symbol']=='ZZZ'
    assert stock_table(offset=2,limit=1)['records'][0]['win_rate'] is None
    assert result['breadth']['rising']==1 and result['breadth']['falling']==1 and result['breadth']['unavailable']==1
    assert stock_table(sort='change',direction='asc')['records'][0]['symbol']=='AAA'


def test_search_matches_company_and_symbol_case_insensitively_and_escapes_wildcards():
    stock('M&M','Mahindra and Mahindra',100);stock('PERCENT','100% Works');stock('OTHER','Something else')
    assert stock_table(search=' mahINDRA ')['total']==1
    assert stock_table(search='m&m')['records'][0]['symbol']=='M&M'
    assert stock_table(search='%')['total']==1
    assert stock_table(search='_')['total']==0
    assert stock_table(search='missing')['records']==[]


def test_win_denominator_excludes_unfilled_pending_and_missing_data():
    stock('TEST','Example')
    forecast('TEST','win',.02);forecast('TEST','loss',-.01,'stop');forecast('TEST','flat',0,'expired')
    forecast('TEST','unfilled',None,'unfilled');forecast('TEST','gap',None,'data_gap');forecast('TEST','pending',None,'pending')
    forecast('TEST','other-timeframe',.03,tf='1m')
    row=stock_table()['records'][0]
    assert row['closed']==3 and row['wins']==1 and row['losses']==1 and row['pending']==1
    assert abs(row['win_rate']-1/3)<1e-10
    assert stock_table(minimum=30)['total']==0
    assert stock_table(timeframe='1m')['records'][0]['win_rate']==1


def test_today_filter_uses_ist_outcome_date_not_issue_date():
    stock('TEST','Example')
    midnight=datetime.now(ZoneInfo('Asia/Kolkata')).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
    forecast('TEST','yesterday',.02,event_time=midnight-1)
    forecast('TEST','today',-.02,'stop',event_time=midnight+1)
    row=stock_table(period='today')['records'][0]
    assert row['closed']==1 and row['win_rate']==0
    assert stock_table()['records'][0]['closed']==2


def test_all_activity_records_are_accessible_and_ties_are_stable():
    with session() as s:
        for i in range(251):s.add(Job(id=f'job-{i:04}',symbol='TEST',timeframe='15m',kind='train',status='completed',created=100,updated=100,detail='Test only'))
    seen=[]
    for offset in range(0,251,25):
        page=activity_table(offset=offset,limit=25)
        assert page['total']==251
        seen.extend(r['id'] for r in page['records'])
    assert len(seen)==len(set(seen))==251 and seen==sorted(seen)
    assert activity_table(state='failed')['total']==0


def test_endpoints_require_auth_and_validate_sort_and_page_limits():
    client=TestClient(app)
    for path in ('/stocks','/activity'):assert client.get(path).status_code==401
    for path in ('/stocks?sort=invalid','/stocks?limit=10000','/activity?offset=-1','/activity?state=invalid'):
        assert client.get(path,headers=HEADERS).status_code==422
    assert client.get('/stocks?search=none',headers=HEADERS).json()['total']==0
