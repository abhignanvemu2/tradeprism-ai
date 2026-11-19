'use client';
import StocksTable from './StocksTable';
import ForecastTable from './ForecastTable';
import type {Api} from '../hooks/useLiveTable';
type Data=Record<string,any>;
const num=(x:unknown,d=2)=>typeof x==='number'?x.toLocaleString('en-IN',{maximumFractionDigits:d}):'—';
const pct=(x:unknown)=>typeof x==='number'?num(x*100)+'%':'—';
const date=(x:number)=>new Date(x*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'});
export default function ResearchDashboard({data,open,api}:{data:Data|null;api:Api;open:(symbol:string,tf:string)=>void}){
 if(!data)return <section className="panel"><div className="empty-state"><h2>Loading automatic research…</h2><p>The backend records forecasts and outcomes while the launcher is running.</p></div></section>;
 const today=data.today,week=data.previous_week;
 return <>
 <section className="metric-grid"><div className="metric teal"><span>TODAY · PAPER NET WIN RATE</span><strong>{pct(today.net_win_rate)}</strong><small>{today.wins} wins / {today.closed} resolved forecasts after assumed costs</small></div><div className="metric purple"><span>PREVIOUS CALENDAR WEEK</span><strong>{pct(week.net_win_rate)}</strong><small>{week.wins} wins / {week.closed} resolved · {data.previous_week_start} to {data.previous_week_end}</small></div><div className="metric amber"><span>PENDING FORECASTS</span><strong>{data.pending_total}</strong><small>Waiting for future bars; not counted as wins or losses</small></div><div className="metric pink"><span>TODAY · MEAN NET RETURN</span><strong>{pct(today.mean_net_return)}</strong><small>Per resolved forecast; not portfolio profit</small></div></section>
 <section className="panel"><div className="panel-heading"><div><h2>Qualifying research candidates by timeframe</h2><p>Within each timeframe, ranked by selected holdout mean net return, then estimated target-hit probability. Different time horizons are not directly comparable. These are unvalidated research candidates, not approved trading recommendations.</p></div><span className="badge">Updates automatically · {date(data.generated_at)}</span></div>
 {data.candidates.length===0?<div className="empty-state"><h2>No qualifying candidate right now</h2><p>A fresh compatible model must beat its probability baseline, have at least 30 selected holdout trades with positive average return after assumed costs, and meet its probability threshold. The app does not force a “best trade.”</p></div>:<div className="scanner-grid">{data.candidates.map((x:Data)=><button className="market-card" key={x.symbol+x.timeframe} onClick={()=>open(x.symbol,x.timeframe)}><h3>{x.symbol} · {x.timeframe}</h3><strong>{pct(x.probability)}</strong><p>Estimated target-hit probability, conditional on entry filling</p><p>Entry ₹{num(x.plan.entry)} · Stop ₹{num(x.plan.stop)} · Target ₹{num(x.plan.target)}</p><small>Entry window: {date(x.entry_time)} · Holdout mean: {pct(x.holdout_expectancy)} across {x.holdout_trades} trades</small></button>)}</div>}
 </section>
 <StocksTable api={api} open={open}/>
 <ForecastTable api={api} open={open}/>
 </>;
}
