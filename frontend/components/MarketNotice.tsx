'use client';
import {useEffect,useState} from 'react';
import type {Api} from '../hooks/useLiveTable';
type Calendar={state:string;title:string;description:string;date:string;verified:boolean;source:string;checked_at:number;special_session?:boolean;sessions:{start:number;end:number}[]};
const clock=(t:number)=>new Date(t*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'});
export default function MarketNotice({api}:{api:Api}){
 const [data,setData]=useState<Calendar|null>(null),[error,setError]=useState('');
 useEffect(()=>{let active=true;let timer:ReturnType<typeof setTimeout>;async function load(){try{const r=await api('/market-calendar');if(active){setData(r);setError('');}}catch(e){if(active){setData(null);setError((e as Error).message);}}finally{if(active)timer=setTimeout(load,60000);}}load();return()=>{active=false;clearTimeout(timer);};},[api]);
 return <section role="status" className={'panel market-notice '+(data?.state||'unknown')}><div><span className="eyebrow">NSE MARKET CALENDAR · IST</span><h2>{error?'Market holiday status unavailable':data?.title||'Checking today’s market calendar…'}</h2><p>{error||data?.description}</p>{data?.sessions.length?<p>{data.special_session?'Special session · ':''}{data.sessions.map(s=>`${clock(s.start)} – ${clock(s.end)}`).join(' / ')} IST · Scheduled session, not a live-feed health check.</p>:null}</div>{data&&<small>{data.date}<br/>{data.verified?'Verified calendar':'Unverified'} · {data.source}<br/>Checked {clock(data.checked_at)} IST</small>}</section>;
}
