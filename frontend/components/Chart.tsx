'use client';
import {useEffect,useRef,useState,useCallback} from 'react';
import {createChart,CandlestickSeries,LineSeries,AreaSeries,BarSeries,HistogramSeries,ColorType,type IChartApi,type ISeriesApi,type UTCTimestamp} from 'lightweight-charts';
export type Candle={time:number;open:number;high:number;low:number;close:number;volume:number};
export type Point={time:number;price:number};
export type Drawing={id:string;type:string;a:Point;b:Point;color:string;locked:boolean;hidden:boolean;label?:string};
type Props={candles:Candle[];drawings:Drawing[];onChange:(d:Drawing[])=>void;levels?:{entry:number;stop:number;target:number};showAI:boolean;onLevel:(name:string,price:number)=>void;ema:boolean;type:string};
export default function Chart({candles,drawings,onChange,levels,showAI,onLevel,ema,type}:Props){
 const host=useRef<HTMLDivElement>(null),chart=useRef<IChartApi|null>(null),series=useRef<ISeriesApi<any>|null>(null);
 const [tool,setTool]=useState('cursor'),[anchor,setAnchor]=useState<Point|null>(null),[selected,setSelected]=useState<string|null>(null),[hover,setHover]=useState<Candle|null>(null),[,paint]=useState(0),[size,setSize]=useState({w:900,h:480}),[drag,setDrag]=useState<{id:string;end:'a'|'b'}|null>(null);
 const redraw=useCallback(()=>paint(n=>n+1),[]);
 useEffect(()=>{
  if(!host.current)return;
  const c=createChart(host.current,{autoSize:true,layout:{background:{type:ColorType.Solid,color:'#0b1020'},textColor:'#8e9db8',attributionLogo:true},grid:{vertLines:{color:'#182138'},horzLines:{color:'#182138'}},rightPriceScale:{borderColor:'#27324b',scaleMargins:{top:.12,bottom:.27}},timeScale:{borderColor:'#27324b',timeVisible:true},crosshair:{mode:0}});
  chart.current=c; const S=type==='line'?LineSeries:type==='area'?AreaSeries:type==='bar'?BarSeries:CandlestickSeries;
  const s=c.addSeries(S as typeof CandlestickSeries,{upColor:'#2ed6b4',downColor:'#ff668b',borderVisible:false,wickUpColor:'#2ed6b4',wickDownColor:'#ff668b'});
  series.current=s;
  s.setData(candles.map(x=>type==='line'||type==='area'?{time:x.time as UTCTimestamp,value:x.close}:({...x,time:x.time as UTCTimestamp})) as any);
  const volume=c.addSeries(HistogramSeries,{priceFormat:{type:'volume'},priceScaleId:'volume'});
  volume.priceScale().applyOptions({scaleMargins:{top:.83,bottom:0}});
  volume.setData(candles.map(x=>({time:x.time as UTCTimestamp,value:x.volume,color:x.close>=x.open?'#2ed6b440':'#ff668b40'})));
  if(ema){for(const period of [20,50]){let acc:number|undefined;const values=candles.map(x=>{acc=acc===undefined?x.close:acc+2/(period+1)*(x.close-acc);return {time:x.time as UTCTimestamp,value:acc};});c.addSeries(LineSeries,{color:period===20?'#b59aff':'#ffce70',lineWidth:1,priceLineVisible:false,lastValueVisible:false}).setData(values.slice(period-1));}}
  c.subscribeCrosshairMove(p=>{if(p.time){setHover(candles.find(x=>x.time===Number(p.time))||null);}redraw();});
  c.timeScale().subscribeVisibleLogicalRangeChange(redraw);
  c.timeScale().fitContent();
  const resize=new ResizeObserver(entries=>{const rect=entries[0].contentRect;setSize({w:rect.width,h:rect.height});redraw();});resize.observe(host.current);
  return ()=>{resize.disconnect();c.remove();chart.current=null;series.current=null;};
 },[candles,type,ema,redraw]);
 function point(e:React.PointerEvent<SVGSVGElement>):Point|null{const box=e.currentTarget.getBoundingClientRect();const t=chart.current?.timeScale().coordinateToTime(e.clientX-box.left);const p=series.current?.coordinateToPrice(e.clientY-box.top);return t!=null&&p!=null?{time:Number(t),price:Number(p)}:null;}
 function xy(p:Point){return {x:Number(chart.current?.timeScale().timeToCoordinate(p.time as UTCTimestamp)??-9999),y:Number(series.current?.priceToCoordinate(p.price)??-9999)};}
 function down(e:React.PointerEvent<SVGSVGElement>){if(tool==='cursor')return;const p=point(e);if(!p)return;
  if(!anchor && !['horizontal','vertical','note'].includes(tool)){setAnchor(p);return;}
  let label:string|undefined;if(tool==='note')label=window.prompt('Chart note')||'';
  onChange([...drawings,{id:crypto.randomUUID(),type:tool,a:anchor||p,b:p,color:'#b59aff',locked:false,hidden:false,label}]);setAnchor(null);setTool('cursor');
 }
 function move(e:React.PointerEvent<SVGSVGElement>){if(!drag)return;const p=point(e);if(!p)return;if(drag.id.startsWith('level:')){onLevel(drag.id.slice(6),p.price);return;}onChange(drawings.map(d=>d.id===drag.id?{...d,[drag.end]:p}:d));}
 function handle(e:React.PointerEvent, id:string,end:'a'|'b'){e.stopPropagation();setSelected(id);const d=drawings.find(x=>x.id===id);if(!d?.locked){setDrag({id,end});(e.currentTarget as Element).setPointerCapture(e.pointerId);}}
 const current=drawings.find(x=>x.id===selected);
 return <div className="chart-shell"><div className="drawing-toolbar">{[['cursor','↖'],['trend','╱'],['ray','↗'],['horizontal','━'],['vertical','│'],['rectangle','▭'],['channel','∥'],['fib','≋'],['measure','↔'],['note','T']].map(([t,label])=><button key={t} title={t} aria-label={t} className={tool===t?'active':''} onClick={()=>{setTool(t);setAnchor(null);}}>{label}</button>)}<button title="Fit chart" onClick={()=>chart.current?.timeScale().fitContent()}>⊞</button><button title="Fullscreen" onClick={()=>host.current?.parentElement?.requestFullscreen()}>⛶</button></div>
 <div className="ohlc">{hover?<><b>{new Date(hover.time*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} IST</b><span>O {hover.open.toFixed(2)}</span><span>H {hover.high.toFixed(2)}</span><span>L {hover.low.toFixed(2)}</span><span>C {hover.close.toFixed(2)}</span></>:<span>Crosshair to inspect · scroll to zoom · drag to pan</span>}</div>
 <div className="chart-stage" onPointerMove={redraw}><div className="chart-host" ref={host}/>
 <svg width={size.w} height={size.h} className="drawing-layer" style={{pointerEvents:tool==='cursor'&&!drag?'none':'auto'}} onPointerDown={down} onPointerMove={move} onPointerUp={()=>setDrag(null)}>
 {drawings.filter(d=>!d.hidden).map(d=>{const a=xy(d.a),b=xy(d.b);if(a.x===-9999||b.x===-9999)return null;const common={stroke:d.color,strokeWidth:1.5,fill:'none',style:{pointerEvents:'stroke' as const},onPointerDown:(e:React.PointerEvent)=>{e.stopPropagation();setSelected(d.id);}};return <g key={d.id}>
 {d.type==='horizontal'?<line {...common} x1={0} x2={size.w-60} y1={a.y} y2={a.y}/>:d.type==='vertical'?<line {...common} x1={a.x} x2={a.x} y1={0} y2={size.h-30}/>:d.type==='rectangle'?<rect {...common} x={Math.min(a.x,b.x)} y={Math.min(a.y,b.y)} width={Math.abs(b.x-a.x)} height={Math.abs(b.y-a.y)} fill="#b59aff15"/>:d.type==='fib'?<>{[0,.236,.382,.5,.618,.786,1,1.618].map(r=><g key={r}><line {...common} x1={Math.min(a.x,b.x)} x2={Math.max(a.x,b.x)} y1={a.y+(b.y-a.y)*r} y2={a.y+(b.y-a.y)*r}/><text x={Math.max(a.x,b.x)+4} y={a.y+(b.y-a.y)*r} fill={d.color} fontSize="10">{r} · {(d.a.price+(d.b.price-d.a.price)*r).toFixed(2)}</text></g>)}</>:d.type==='note'?<text x={a.x} y={a.y} fill={d.color} style={{pointerEvents:'all'}} onClick={()=>setSelected(d.id)}>{d.label}</text>:<><line {...common} x1={a.x} y1={a.y} x2={d.type==='ray'?size.w-60:b.x} y2={d.type==='ray'&&b.x!==a.x?a.y+(b.y-a.y)*(size.w-60-a.x)/(b.x-a.x):b.y}/>{d.type==='channel'&&<line {...common} x1={a.x} y1={a.y+40} x2={b.x} y2={b.y+40}/>} {d.type==='measure'&&<text x={b.x} y={b.y-10} fill={d.color} fontSize="12">{((d.b.price/d.a.price-1)*100).toFixed(2)}% · {Math.abs(d.b.time-d.a.time)/3600}h</text>}</>}
 {selected===d.id&&(['a','b'] as const).map(end=>{const pos=end==='a'?a:b;return <circle key={end} cx={pos.x} cy={pos.y} r={6} fill={d.locked?'#6b7280':'#fff'} stroke={d.color} style={{pointerEvents:'all',cursor:d.locked?'not-allowed':'grab'}} onPointerDown={e=>handle(e,d.id,end)}/>;})}</g>;})}
 {showAI&&levels&&Object.entries(levels).map(([name,price])=>{const y=series.current?.priceToCoordinate(price);if(y==null)return null;return <g key={name}><line x1={0} x2={size.w-60} y1={y} y2={y} stroke={name==='stop'?'#ff668b':name==='target'?'#2ed6b4':'#ffce70'} strokeWidth={2} strokeDasharray="6 5" style={{pointerEvents:'stroke',cursor:'ns-resize'}} onPointerDown={e=>handle(e,`level:${name}`,'a')}/><text x={12} y={y-7} fill="#e2e8f0" fontSize="11">USER SCENARIO · {name.toUpperCase()} {price.toFixed(2)}</text></g>;})}
 </svg>{candles.length===0&&<div className="chart-empty"><div className="empty-icon">⌁</div><h2>Your chart starts with real data.</h2><p>Fetch provider history to open this workspace.<br/>No generated candles. No demonstration prices.</p></div>}</div>
 <div className="chart-bottom"><span>{anchor?'Choose the second anchor':tool==='cursor'?'Manual drawings are independent of research levels.':`${tool}: click the chart to place anchors`}</span>{current&&<div className="inline"><button onClick={()=>onChange(drawings.map(d=>d.id===selected?{...d,locked:!d.locked}:d))}>{current.locked?'Unlock':'Lock'}</button><button onClick={()=>onChange(drawings.map(d=>d.id===selected?{...d,hidden:!d.hidden}:d))}>Hide</button><input aria-label="Drawing color" type="color" value={current.color} onChange={e=>onChange(drawings.map(d=>d.id===selected?{...d,color:e.target.value}:d))}/><button onClick={()=>{onChange(drawings.filter(d=>d.id!==selected));setSelected(null);}}>Delete</button></div>}</div>
 </div>;
}
