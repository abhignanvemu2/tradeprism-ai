import numpy as np
from tradeprism.ml import train, infer, wilson, stats
from tradeprism.quant import features
from test_quant import frame

def test_training_calibration_artifact_and_inference(tmp_path,monkeypatch):
    # Synthetic examples belong only to this isolated pipeline test.
    monkeypatch.setattr('tradeprism.ml.DATA',tmp_path)
    rng=np.random.default_rng(42)
    rows=[{'index':i,'label_end':i+12,'time':i*3600.,'x':rng.normal(size=9),'label':i%2,'event':'target' if i%2 else 'stop','net_return':.02 if i%2 else -.01,'bars':3} for i in range(50,990)]
    monkeypatch.setattr('tradeprism.ml.dataset',lambda *args:(rows,20))
    f=features(frame(1000))
    report=train(f,'TEST','1h',.01,{'source':'isolated test fixture'})
    assert report['partition_counts'][0]>400
    assert report['partition_dates'][0][1]+12*3600<report['partition_dates'][1][0]
    assert (tmp_path/'models'/report['version']/'model.joblib').exists()
    predicted=infer(f,report)
    assert 0<=predicted['probability']<=1
    assert train(f,'TEST','1h',.01,{})['version']==report['version']

def test_uncertainty_and_sequential_trade_denominator():
    low,high=wilson(7,10)
    assert low<.7<high
    sample=[{'index':i,'bars':3,'time':i,'label':1,'event':'target','net_return':.01} for i in range(10)]
    assert stats(sample)['trades']==3
