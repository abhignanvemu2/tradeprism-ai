import hashlib
import json
import os
import platform
from pathlib import Path
import joblib
import numpy as np
import sklearn
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, log_loss
from .quant import FEATURES, HORIZON, VERSION, dataset
from .db import DATA, now

def wilson(wins, n):
    if n==0: return None
    z=1.96; p=wins/n; den=1+z*z/n
    center=(p+z*z/(2*n))/den
    spread=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [float(center-spread),float(center+spread)]

def stats(rows):
    selected=[]; busy_until=-1
    for r in rows:
        if r['index']<=busy_until: continue
        selected.append(r); busy_until=r['index']+r['bars']
    returns=np.array([r['net_return'] for r in selected])
    n=len(returns)
    if not n: return {'trades':0,'win_rate':None,'win_rate_95ci':None,'net_expectancy':None}
    curve=np.r_[1,np.cumprod(1+returns)]
    draw=curve/np.maximum.accumulate(curve)-1
    gains=returns[returns>0]; losses=returns[returns<=0]
    return {'trades':n,'win_rate':float((returns>0).mean()),'win_rate_95ci':wilson(int((returns>0).sum()),n),'net_expectancy':float(returns.mean()),'average_win':float(gains.mean()) if len(gains) else 0,'average_loss':float(losses.mean()) if len(losses) else 0,'profit_factor':float(gains.sum()/-losses.sum()) if losses.sum()<0 else None,'max_drawdown':float(-draw.min()),'expired':sum(x['event']=='expired' for x in selected),'target_hits':sum(x['label'] for x in selected),'start':selected[0]['time'],'end':selected[-1]['time'],'equity_curve':curve.tolist(),'assumptions':'Sequential non-overlapping trades, full-notional returns, 15 bps per side; research curve, not account returns.'}

def train(frame, symbol, tf, tick, provenance):
    digest=hashlib.sha256((frame[['time','open','high','low','close','volume']].to_json()+VERSION+str(tick)).encode()).hexdigest()
    version=f'{symbol}-{tf}-{digest[:16]}'
    folder=DATA/'models'/version
    if (folder/'report.json').exists():
        return json.loads((folder/'report.json').read_text())
    examples, unfilled=dataset(frame,tick)
    if len(examples)<300:
        raise ValueError(f'Insufficient evidence: {len(examples)} filled examples; at least 300 required. Fetch more real history.')
    n=len(frame); boundaries=[int(n*.55),int(n*.70),int(n*.85)]
    a,b,c=boundaries
    parts=[[r for r in examples if lo<=r['index'] and r['label_end']<hi] for lo,hi in [(0,a),(a,b),(b,c),(c,n)]]
    if any(len(p)<30 or len(set(r['label'] for r in p))<2 for p in parts):
        raise ValueError('Insufficient evidence: each purged chronological partition needs 30 filled examples and both outcomes.')
    arrays=lambda p:(np.vstack([r['x'] for r in p]),np.array([r['label'] for r in p]))
    xt,yt=arrays(parts[0]); xv,yv=arrays(parts[1]); xc,yc=arrays(parts[2]); xe,ye=arrays(parts[3])
    candidates={'logistic':make_pipeline(StandardScaler(),LogisticRegression(max_iter=1500,random_state=17)), 'boosted_trees':HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=8,l2_regularization=3,random_state=17)}
    scores={}
    for name,model in candidates.items():
        model.fit(xt,yt)
        scores[name]=float(brier_score_loss(yv,model.predict_proba(xv)[:,1]))
    winner=min(scores,key=scores.get); model=candidates[winner]
    transform=lambda p:np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1)
    calibrator=LogisticRegression(C=1,random_state=17).fit(transform(model.predict_proba(xc)[:,1]),yc)
    predict=lambda x:calibrator.predict_proba(transform(model.predict_proba(x)[:,1]))[:,1]
    # Model selection and calibration have finished before touching final labels.
    probabilities=predict(xe)
    picked=[r for r,p in zip(parts[3],probabilities) if p>=.60]
    metrics=stats(picked)
    bins=[]
    for low in np.arange(0,1,.1):
        mask=(probabilities>=low)&(probabilities<low+.1)
        if mask.any(): bins.append({'low':float(low),'count':int(mask.sum()),'predicted':float(probabilities[mask].mean()),'observed':float(ye[mask].mean())})
    report={'version':version,'strategy':VERSION,'features':FEATURES,'data_hash':digest,'trained_at':now(),'symbol':symbol,'timeframe':tf,'model':winner,'python':platform.python_version(),'sklearn':sklearn.__version__,'target':'TP at 3 ATR before SL at 1.5 ATR within 12 bars, conditional on next-bar stop-entry fill; expiry is failure. Gap above entry is unfilled. Long only.','threshold':.60,'cost_bps_per_side':15,'split':'55% training / 15% model selection / 15% sigmoid calibration / 15% final test; purge full 12-bar label horizon at each boundary','partition_counts':[len(p) for p in parts],'partition_dates':[[p[0]['time'],p[-1]['time']] for p in parts],'unfilled_examples':unfilled,'validation_brier':scores,'test_brier':float(brier_score_loss(ye,probabilities)),'baseline_test_brier':float(brier_score_loss(ye,np.repeat(yt.mean(),len(ye)))),'test_log_loss':float(log_loss(ye,probabilities)),'calibration':bins,'selected_test':metrics,'baseline_all_setups':stats(parts[3]),'provenance':provenance,'status':'research only','limitations':['Not walk-forward validated; final holdout is single-run per dataset hash.','Changing the dataset can overlap previous final test periods: no independence claim across retrains.','No spread history, queue position, funding, borrow or corporate-action reconciliation.','No point-in-time market universe; single-instrument evaluation.','Probability is conditional on the documented entry and fixed barriers; manual edits invalidate it.','Live execution alignment and drift validation are pending; no actionable AI recommendations.']}
    folder.mkdir(parents=True,exist_ok=True)
    temp=folder/'model.tmp'
    joblib.dump({'model':model,'calibrator':calibrator,'report':report},temp)
    os.replace(temp,folder/'model.joblib')
    (folder/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False))
    return report

def infer(frame, report):
    if now()-report['trained_at']>30*86400:
        return {'state':'Model expired; retraining and validation required','probability':None}
    x=frame.iloc[-1][FEATURES].to_numpy(dtype=float)
    if not np.isfinite(x).all():
        return {'state':'Insufficient feature history','probability':None}
    version=report['version']
    if Path(version).name!=version: raise ValueError('Invalid model version')
    # Artifacts are generated only by our worker. Never accept uploaded pickle/joblib files.
    saved=joblib.load(DATA/'models'/version/'model.joblib')
    p=float(saved['model'].predict_proba(x.reshape(1,-1))[0,1]); p=np.clip(p,1e-6,1-1e-6)
    calibrated=float(saved['calibrator'].predict_proba([[np.log(p/(1-p))]])[0,1])
    return {'state':'Research inference; not approved for actionable signals','probability':calibrated,'target':report['target'],'version':version}
