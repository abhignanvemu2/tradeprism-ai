'use client';
import {useState} from 'react';
import Pagination from './Pagination';
import {Api,useLiveTable} from '../hooks/useLiveTable';
export default function ForecastTable({api,open}:{api:Api;open:(s:string,t:string)=>void}){
 const [offset,setOffset]=useState(0),[limit,setLimit]=useState(25);
 const {data,error}=useLiveTable(api,`/forecasts?offset=${offset}&limit=${limit}`);
 return <section className="panel"><div className="panel-heading"><div><h2>All recorded forecasts</h2><p>Complete paginated history. Open Evidence to inspect the frozen prediction and outcome candles.</p></div></div>{error&&<p className="error" role="alert">{error}</p>}{!data?<p className="source-note">Loading forecasts…</p>:<><div className="table-wrap"><table><thead><tr><th>Stock</th><th>Issued · IST</th><th>Estimated target hit</th><th>Entry / stop / target</th><th>Outcome</th><th>Net return</th><th>Evidence</th></tr></thead><tbody>{data.records.map((r:any)=><tr key={r.id}><td><button onClick={()=>open(r.symbol,r.timeframe)}>{r.symbol} · {r.timeframe}</button></td><td>{new Date(r.issued_at*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})}</td><td>{(r.probability*100).toFixed(2)}%</td><td>{r.forecast.plan.entry} / {r.forecast.plan.stop} / {r.forecast.plan.target}</td><td>{r.outcome?.event||'pending'}</td><td>{r.net_return==null?'—':(r.net_return*100).toFixed(2)+'%'}</td><td><details><summary>Evidence</summary><pre className="record-evidence">{JSON.stringify(r,null,2)}</pre></details></td></tr>)}</tbody></table>{!data.records.length&&<p className="source-note">No forecasts recorded yet.</p>}</div><Pagination offset={offset} limit={limit} total={data.total} onOffset={setOffset} onLimit={setLimit}/></>}</section>;
}
