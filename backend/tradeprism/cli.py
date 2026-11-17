"""Explicit local research commands; same settings/storage as the worker."""
import argparse
import json
from .db import init, session, Record
from .service import ingest, metadata, bars, append, advance_paper
from .quant import features
from .ml import train
from .providers import REGISTRY, SECONDS

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['ingest','train'])
    parser.add_argument('symbol',choices=REGISTRY)
    parser.add_argument('--timeframe',choices=SECONDS,default='1h')
    parser.add_argument('--count',type=int,default=1800)
    args=parser.parse_args()
    init()
    if not 100<=args.count<=20000: parser.error('count must be 100–20000')
    if args.action=='ingest':
        result=ingest(args.symbol,args.timeframe,args.count)
        advance_paper()
    else:
        meta=metadata(args.symbol,args.timeframe)
        if not meta: parser.error('Fetch genuine history first')
        if meta.get('missing_intervals'): parser.error('Reconcile gaps/corporate actions before training')
        from .training import research_frame
        frame=research_frame(bars(args.symbol,args.timeframe),meta,args.timeframe)
        result=train(features(frame),args.symbol,args.timeframe,meta['tick'],meta)
        with session() as s:
            if not s.get(Record,result['version']): append(s,'model','system',args.symbol,result,result['version'])
    print(json.dumps(result,indent=2,allow_nan=False))

if __name__=='__main__': main()
