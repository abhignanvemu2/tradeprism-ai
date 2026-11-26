from datetime import datetime
from fastapi.testclient import TestClient
import httpx
from tradeprism.api import app
from tradeprism.market_calendar import IST, describe, market_today, _cache

def stamp(day,time='10:00:00'):return datetime.fromisoformat(day+'T'+time).replace(tzinfo=IST).timestamp()
def timing(day):return {'exchange':'NSE','start_time':stamp(day,'09:15:00')*1000,'end_time':stamp(day,'15:30:00')*1000}

def test_holiday_and_settlement_only():
    day='2026-01-26';h={'date':day,'holiday_type':'TRADING_HOLIDAY','description':'Republic Day','closed_exchanges':['NSE'],'open_exchanges':[]}
    r=describe(day,stamp(day),[h],[])
    assert r['state']=='holiday' and r['description']=='Republic Day'
    h['holiday_type']='SETTLEMENT_HOLIDAY'
    assert describe(day,stamp(day),[h],[timing(day)])['state']=='open'
    h['holiday_type']='TRADING_HOLIDAY';h['closed_exchanges']=['MCX']
    assert describe(day,stamp(day),[h],[])['state']!='holiday'

def test_weekend_and_special_session_override():
    day='2026-11-28'
    assert describe(day,stamp(day),[],[])['state']=='weekend'
    r=describe(day,stamp(day),[],[timing(day)])
    assert r['state']=='open' and r['special_session']
    assert describe(day,stamp(day,'08:00:00'),[],[timing(day)])['state']=='before_open'
    assert describe(day,stamp(day,'15:30:00'),[],[timing(day)])['state']=='closed'

def test_cache_time_transitions_and_new_ist_date(monkeypatch):
    _cache.clear();calls=[]
    def fetch(day):calls.append(day);return [],[timing(day)]
    monkeypatch.setattr('tradeprism.market_calendar._fetch',fetch)
    assert market_today(stamp('2026-11-26','08:00:00'))['state']=='before_open'
    assert market_today(stamp('2026-11-26','10:00:00'))['state']=='open'
    assert calls==['2026-11-26']
    market_today(stamp('2026-11-27','00:01:00'))
    assert calls[-1]=='2026-11-27'
    _cache.clear()

def test_unavailable_calendar_is_never_a_guessed_holiday(monkeypatch):
    _cache.clear()
    def fail(day):raise httpx.ConnectError('test error')
    monkeypatch.setattr('tradeprism.market_calendar._fetch',fail)
    r=market_today(stamp('2026-11-28'))
    assert r['state']=='unknown' and not r['verified']
    client=TestClient(app)
    assert client.get('/market-calendar').status_code==401
    assert client.get('/market-calendar',headers={'Authorization':'Bearer test-alice-key-at-least-24-chars'}).status_code==200
    _cache.clear()
