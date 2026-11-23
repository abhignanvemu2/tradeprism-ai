import math
import numpy as np
import pandas as pd
import pytest
from tradeprism.quant import features, risk, outcome, FEATURES, dataset
from tradeprism.providers import validate, DataUnavailable

def frame(n=100):
    rng=np.random.default_rng(19)
    close=100+np.cumsum(rng.normal(0,.5,n))
    return pd.DataFrame({'time':np.arange(n)*3600,'open':close,'high':close+1,'low':close-1,'close':close,'volume':rng.uniform(10,100,n)})

def test_costs_lots_fx_and_notional():
    r=risk(100,95,110,'LONG',10000,1,.05,1,10,80)
    assert r['quantity']%1==0
    assert r['estimated_loss']<=100
    assert r['quantity']*100*80<=10000
    assert r['reward_risk']==2
    assert r['net_reward_risk']<2
    assert r['probability'] is None

def test_short_and_tick_rounding():
    r=risk(100.01,105.01,90.01,'SHORT',10000,1,.05,1,0)
    assert r['entry']==100 and r['quantity']==20
    assert r['estimated_loss']==100 and r['estimated_profit']==200

@pytest.mark.parametrize('args',[(100,110,120,'LONG',1000,1,.01,1),(100,90,110,'SHORT',1000,1,.01,1),(100,99.999,110,'LONG',1000,1,1,1),(100,95,110,'LONG',1000,0,.01,1),(math.nan,95,110,'LONG',1000,1,.01,1)])
def test_reject_invalid_risk(args):
    with pytest.raises(ValueError):risk(*args)

def test_feature_prefix_does_not_see_future():
    d=frame(160)
    before=features(d.iloc[:100])[FEATURES].iloc[-1]
    d.loc[100:,'close']=10000
    after=features(d)[FEATURES].iloc[99]
    np.testing.assert_allclose(before,after)

def test_same_bar_stop_wins_and_gap_entry_uses_open():
    p={'entry':100,'stop':95,'target':110}
    assert outcome(pd.DataFrame([{'open':99,'low':94,'high':112,'close':105}]),p)['event']=='stop'
    result=outcome(pd.DataFrame([{'open':102,'low':99,'high':112,'close':105}]),p)
    assert result['event']=='target' and result['net_return']<.08

def test_expiry_is_failure_with_actual_pnl():
    result=outcome(pd.DataFrame([{'open':99,'low':98,'high':105,'close':103}]),{'entry':100,'stop':95,'target':110})
    assert result['event']=='expired' and result['label']==0 and 0<result['net_return']<.03

def test_stop_gap_is_adverse():
    bars=pd.DataFrame([{'open':99,'low':98,'high':101,'close':100},{'open':90,'low':89,'high':94,'close':92}])
    assert outcome(bars,{'entry':100,'stop':95,'target':110})['exit']==90

def test_data_validation_deduplicates_and_rejects_conflicts():
    a=[1,100,110,90,105,100]
    assert validate([a,a],3)==[a]
    with pytest.raises(DataUnavailable):validate([a,[1,100,110,90,106,100]],3)
    with pytest.raises(DataUnavailable):validate([[1,100,90,110,105,100]],3)
    with pytest.raises(DataUnavailable):validate([[1,100,110,90,float('inf'),100]],3)

def test_labels_do_not_extend_beyond_available_data():
    examples,_=dataset(features(frame(200)),.01)
    assert all(x['label_end']<200 for x in examples)
