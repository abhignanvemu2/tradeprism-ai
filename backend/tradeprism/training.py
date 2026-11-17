"""Additional equity research guards; no claim of corporate-action verification."""
import pandas as pd
from .providers import SECONDS

def research_frame(frame,meta,tf):
    if meta['asset']!='equity':return frame
    if tf not in ('1m','5m','15m'):
        raise ValueError('Indian-stock research currently supports 1m, 5m or 15m only, with all 12 outcome bars inside one session. Select 15m to start.')
    d=frame.copy()
    if d.empty:raise ValueError('Download genuine history first.')
    if (d.open/d.close.shift()-1).abs().gt(.20).any():
        raise ValueError('A price discontinuity above 20% requires corporate-action/data review before training. It will not be silently adjusted.')
    local=pd.to_datetime(d.time,unit='s',utc=True).dt.tz_convert('Asia/Kolkata')
    minutes=local.dt.hour*60+local.dt.minute
    if ((minutes<555)|(minutes>=930)).any():
        raise ValueError('Nonstandard session candles require review before training.')
    d['session']=local.dt.strftime('%Y-%m-%d')
    d.attrs['step']=SECONDS[tf]
    return d
