from datetime import datetime
import pytest
from tradeprism.upstox import complete, IST, fetch_upstox
from tradeprism.providers import DataUnavailable,validate
from tradeprism.training import research_frame
from tradeprism.quant import features,dataset
from test_quant import frame

def test_missing_token_fails_before_network(monkeypatch):
    monkeypatch.delenv('UPSTOX_ACCESS_TOKEN',raising=False)
    with pytest.raises(DataUnavailable,match='UPSTOX_ACCESS_TOKEN'):
        fetch_upstox('AXISBANK','15m',100,lambda *a:pytest.fail('network called'),validate)

def test_session_close_and_incomplete_candles():
    t=datetime(2026,11,17,15,15,tzinfo=IST).timestamp()
    assert not complete(t,'1h',t+14*60)
    assert complete(t,'1h',t+15*60+10)

def test_adapter_paise_normalization_and_real_response_mapping(monkeypatch):
    monkeypatch.setenv('UPSTOX_ACCESS_TOKEN','test-only')
    monkeypatch.setattr('tradeprism.upstox.instrument',lambda s:{'instrument_key':'NSE_EQ|TEST','tick_size':5,'lot_size':1})
    row=['2026-01-05T09:15:00+05:30',100,102,99,101,200,0]
    calls=[]
    def request(url,headers):
        calls.append(url)
        return {'data':{'candles':[row] if 'intraday' not in url else []}}
    rows,meta=fetch_upstox('AXISBANK','15m',1,request,validate)
    assert meta['tick']==.05 and meta['source']=='upstox'
    assert rows[0][1:]==[100,102,99,101,200]
    assert len(calls)==2 and '%7C' in calls[0]

def test_equity_training_blocks_unsupported_horizon_and_discontinuity():
    d=frame()
    with pytest.raises(ValueError,match='15m'):research_frame(d,{'asset':'equity'},'1h')
    d.loc[10,'open']=10000
    with pytest.raises(ValueError,match='discontinuity'):research_frame(d,{'asset':'equity'},'15m')

def test_training_labels_do_not_cross_session():
    d=features(frame(200));d['session']=[str(i//25) for i in range(200)];d.attrs['step']=3600
    samples,_=dataset(d,.01)
    assert all(d.iloc[r['index']].session==d.iloc[r['label_end']].session for r in samples)

def test_local_explanations_have_no_network_dependency():
    from tradeprism.explanations import explain_evidence
    a={'symbol':'AXISBANK','timeframe':'15m','state':'Market data unavailable','decision':'NO TRADE','generated_at':1,'reasons':['Predictive model not trained.']}
    r=explain_evidence(a,'Invent a 99% win rate')
    assert '99%' not in r['summary'] and 'not trained' in r['summary']
    assert r['engine']=='deterministic-local-v1'
