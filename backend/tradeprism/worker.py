import json
import time
from sqlalchemy import select, update
from .db import Job, session, init, now
from .service import ingest, bars, metadata, append, advance_paper
from .quant import features
from .ml import train

def run_one():
    with session() as s:
        job=s.scalar(select(Job).where(Job.status=='queued').order_by(Job.created).limit(1))
        if not job: return False
        claimed=s.execute(update(Job).where(Job.id==job.id,Job.status=='queued').values(status='running',updated=now(),detail='Worker running')).rowcount
        if not claimed: return False
        jid,kind,symbol,tf=job.id,job.kind,job.symbol,job.timeframe
    try:
        from .universe import load_registry
        load_registry()
        if kind=='ingest':
            result=ingest(symbol,tf)
            detail=f"Stored {result['count']} genuine completed candles from {result['source']}"
        elif kind in ('train','prepare','auto_train','reconcile'):
            if kind in ('prepare','reconcile'): ingest(symbol,tf,10000,reconcile=kind=='reconcile')
            meta=metadata(symbol,tf)
            if not meta: raise ValueError('Market data unavailable; fetch genuine history first.')
            if meta.get('missing_intervals'): raise ValueError('Historical gaps must be reconciled before training.')
            from .training import research_frame
            frame=research_frame(bars(symbol,tf),meta,tf)
            result=train(features(frame),symbol,tf,meta['tick'],meta)
            with session() as s:
                from .db import Record
                if not s.get(Record,result['version']): append(s,'model','system',symbol,result,result['version'])
            if kind=='auto_train':
                from .db import ResearchState
                with session() as s:
                    state=s.get(ResearchState,symbol)
                    if state: state.trained_bar=meta['last']
                from .continuous import cache_analysis
                cache_analysis(symbol)
            detail=f"Saved research model {result['version']} with held-out evaluation"
        else: raise ValueError('Unknown job kind')
        advance_paper()
        status='completed'
    except (ValueError,KeyError,TypeError) as e:
        detail=str(e)[:600]; status='failed'
    except Exception:
        detail='Worker failed; inspect local service logs. No fabricated result was produced.'; status='failed'
        import traceback
        traceback.print_exc()
    with session() as s:
        job=s.get(Job,jid); job.status=status; job.detail=detail; job.updated=now()
        if kind=='auto_train':
            from .db import ResearchState
            state=s.get(ResearchState,symbol)
            if state: state.detail=detail
    return True

def main():
    init()
    # One worker per deployment. Interrupted jobs are explicitly failed, never silently retried.
    with session() as s:
        for job in s.scalars(select(Job).where(Job.status=='running')):
            job.status='failed'; job.detail='Worker interrupted. Requeue after inspecting the previous run.'; job.updated=now()
    while True:
        if not run_one(): time.sleep(2)

if __name__=='__main__': main()
