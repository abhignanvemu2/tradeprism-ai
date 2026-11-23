import json
from sqlalchemy import select
from tradeprism.db import session, Instrument, ResearchState, Job, LiveQuote, Candle, now
from tradeprism.continuous import schedule_training, collect_one, HORIZON, STEP
from tradeprism.live import decode, window, save_quotes
from tradeprism.proto.MarketDataFeed_pb2 import FeedResponse


def seed(symbol='AXISBANK',last=100000):
    with session() as s:
        s.add(Instrument(symbol=symbol,body=json.dumps({'instrument_key':'NSE_EQ|'+symbol,'segment':'NSE_EQ','name':symbol})))
        s.add(ResearchState(symbol=symbol,last_bar=last))


def test_scheduling_deduplicates_and_requires_new_outcomes():
    seed()
    schedule_training(); schedule_training()
    with session() as s:
        jobs=list(s.scalars(select(Job))); assert len(jobs)==1
        assert jobs[0].kind=='auto_train'
        jobs[0].status='failed'
    schedule_training()
    with session() as s:
        assert len(list(s.scalars(select(Job))))==1
        s.get(ResearchState,'AXISBANK').last_bar+=HORIZON*STEP
        for i in range(1,HORIZON+1):
            s.add(Candle(symbol='AXISBANK',timeframe='15m',time=100000+i*STEP,open=100,high=101,low=99,close=100,volume=1,source='test',fetched_at=now()))
    schedule_training()
    with session() as s: assert len(list(s.scalars(select(Job))))==2


def test_queue_bound_and_retired_symbol_exclusion():
    for i in range(25): seed(__import__('tradeprism.scope',fromlist=['SYMBOLS']).SYMBOLS[i])
    with session() as s: s.add(ResearchState(symbol='RETIRED',last_bar=100000))
    schedule_training()
    with session() as s:
        jobs=list(s.scalars(select(Job)))
        assert len(jobs)==20
        assert all(j.symbol!='RETIRED' for j in jobs)


def test_rotation_never_exceeds_provider_limit_and_covers_overflow():
    keys=[str(i) for i in range(7500)]
    first=window(keys,0); second=window(keys,5000)
    assert len(first)==len(second)==5000
    assert len(set(first))==len(first)
    assert set(first+second)==set(keys)
    assert window(['a','b'],0)==['a','b']


def test_decode_real_wire_format_and_reject_future_invalid_unknown():
    msg=FeedResponse(); stamp=now()
    q=msg.feeds['NSE_EQ|TEST'].ltpc
    q.ltp=123; q.cp=120; q.ltt=int(stamp*1000)
    msg.feeds['UNKNOWN'].ltpc.CopyFrom(q)
    msg.marketInfo.segmentStatus['NSE_EQ']=2
    result,segments=decode(msg.SerializeToString(),{'NSE_EQ|TEST':'AXISBANK'},stamp)
    assert list(result)==['AXISBANK'] and result['AXISBANK']['price']==123
    assert segments['NSE_EQ']==2
    q.ltt=int((stamp+120)*1000)
    assert decode(msg.SerializeToString(),{'NSE_EQ|TEST':'AXISBANK'},stamp)[0]=={}
    q.ltt=int(stamp*1000); q.ltp=float('nan')
    assert decode(msg.SerializeToString(),{'NSE_EQ|TEST':'AXISBANK'},stamp)[0]=={}


def test_out_of_order_ticks_never_rewind_last_trade():
    save_quotes({'AXISBANK':{'price':100,'previous_close':99,'trade_time':100,'received':101}})
    save_quotes({'AXISBANK':{'price':90,'previous_close':99,'trade_time':99,'received':102}})
    with session() as s: assert s.get(LiveQuote,'AXISBANK').price==100


def test_collector_alternates_bootstrap_and_refresh(monkeypatch):
    import tradeprism.continuous as c
    seed('HDFCBANK',last=now()-900); seed('ICICIBANK',last=0)
    monkeypatch.setattr(c,'_COLLECTION_TURN',0)
    calls=[]
    def ingest(symbol,tf,count):
        calls.append((symbol,count)); return {'last':now()-900}
    monkeypatch.setattr(c,'ingest',ingest)
    monkeypatch.setattr(c,'cache_analysis',lambda s:None)
    collect_one(); collect_one()
    assert calls[0][0]=='HDFCBANK' and calls[1]==('ICICIBANK',10000)


def test_stock_table_replaces_scanner_with_auth_and_freshness():
    from fastapi.testclient import TestClient
    from tradeprism.api import app
    seed('AXISBANK');seed('HDFCBANK')
    save_quotes({'AXISBANK':{'price':100,'previous_close':99,'trade_time':1,'received':now()}})
    client=TestClient(app);headers={'Authorization':'Bearer test-alice-key-at-least-24-chars'}
    assert client.get('/monitor').status_code==401
    assert client.get('/scanner',headers=headers).status_code==404
    r=client.get('/stocks?limit=1&search=BANK',headers=headers).json()
    assert r['total']==2 and len(r['records'])==1
    assert r['records'][0]['quote_fresh'] is False
    assert client.get('/stocks?limit=1000',headers=headers).status_code==422


def test_elapsed_weekend_does_not_count_as_new_training_bars():
    seed()
    schedule_training()
    with session() as s:
        s.scalar(select(Job)).status='completed'
        s.get(ResearchState,'AXISBANK').last_bar+=3*86400
    schedule_training()
    with session() as s: assert len(list(s.scalars(select(Job))))==1


def test_provider_revision_requires_explicit_reconciliation_and_preserves_old_values(monkeypatch):
    from tradeprism.service import ingest, bars, records
    import tradeprism.service as svc
    meta={'source':'upstox','symbol':'AXISBANK','timeframe':'15m','fetched_at':now()}
    original=[[1000,100,102,99,101,10]]
    monkeypatch.setattr(svc,'fetch',lambda *args:(original,dict(meta)))
    ingest('AXISBANK','15m')
    revised=[[1000,100,102,99,101.5,11]]
    monkeypatch.setattr(svc,'fetch',lambda *args:(revised,dict(meta)))
    import pytest
    with pytest.raises(ValueError,match='close, volume changed'): ingest('AXISBANK','15m')
    assert bars('AXISBANK','15m').iloc[0].close==101
    result=ingest('AXISBANK','15m',reconcile=True)
    assert result['reconciled_at']>0
    assert bars('AXISBANK','15m').iloc[0].close==101.5
    archived=records('data_revision')[0]['revisions'][0]
    assert archived['before']['close']==101 and archived['after']['close']==101.5
    # A later ordinary fetch must retain the invalidation watermark.
    assert ingest('AXISBANK','15m')['reconciled_at']==result['reconciled_at']


def test_reconciliation_rejects_partial_history(monkeypatch):
    import pytest
    import tradeprism.service as svc
    meta={'source':'upstox','symbol':'AXISBANK','timeframe':'15m','fetched_at':now()}
    monkeypatch.setattr(svc,'fetch',lambda *args:([[1000,100,102,99,101,10],[1900,101,103,100,102,11]],dict(meta)))
    svc.ingest('AXISBANK','15m')
    monkeypatch.setattr(svc,'fetch',lambda *args:([[1900,101,103,100,102.5,11]],dict(meta)))
    with pytest.raises(ValueError,match='partial history'): svc.ingest('AXISBANK','15m',reconcile=True)
    assert svc.bars('AXISBANK','15m').iloc[-1].close==102


def test_nonstandard_stock_group_is_visible_but_not_intraday_trained():
    import pytest
    from tradeprism.training import research_frame
    with pytest.raises(ValueError,match='settlement/session review'):
        research_frame(None,{'asset':'equity','stock_group':'XT'},'15m')
