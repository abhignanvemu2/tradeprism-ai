'use client';
import {useMemo,useState} from 'react';
import Pagination from './Pagination';

type Instrument={symbol:string;name?:string;venue?:string};
type Props={instruments:Instrument[];symbol:string;favorites:string[];ready:boolean;pending:string|null;toggle:(symbol:string)=>void;open:(symbol:string)=>void;favoritesOnly?:boolean};
export default function StockPicker({instruments,symbol,favorites,ready,pending,toggle,open,favoritesOnly=false}:Props){
 const [query,setQuery]=useState(''),[offset,setOffset]=useState(0),[limit,setLimit]=useState(25);
 const [expanded,setExpanded]=useState(false);
 const favoriteSet=useMemo(()=>new Set(favorites),[favorites]);
 const rows=useMemo(()=>{
  const bySymbol=new Map(instruments.map(i=>[i.symbol,i]));
  const source=favoritesOnly?favorites.map(s=>bySymbol.get(s)||{symbol:s,name:'Currently unavailable'}):instruments;
  const q=query.trim().toLocaleLowerCase();
  return source.filter(i=>!q||[i.symbol,i.name,i.venue].some(v=>v?.toLocaleLowerCase().includes(q)))
   .sort((a,b)=>a.symbol.localeCompare(b.symbol));
 },[instruments,favorites,favoritesOnly,query]);
 const visible=favoritesOnly||expanded;
 return <section className={favoritesOnly?'panel stock-picker':'stock-picker'}>
  <div className="panel-heading"><div><h2>{favoritesOnly?'Favorite stocks':'Find a stock'}</h2>
   <p>{favoritesOnly?'Your starred stocks, saved to your account. Open any stock in Workspace.':'Search every discovered stock by symbol, company name, or exchange.'}</p></div>
   {!favoritesOnly&&<button aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>{expanded?'Close search':'Browse stocks'}</button>}
  </div>
  <div className="stock-search-row">
   <label>Search stocks<input type="search" placeholder="Try AXISBANK, Reliance, or BSE" value={query} onFocus={()=>setExpanded(true)} onChange={e=>{setQuery(e.target.value);setOffset(0);setExpanded(true);}} onKeyDown={e=>{if(e.key==='Escape')setExpanded(false);if(e.key==='Enter'&&!favoritesOnly&&rows.length===1){open(rows[0].symbol);setExpanded(false);}}}/></label>
   {!favoritesOnly&&<><strong>Selected: {symbol}</strong><button disabled={!ready||pending!==null} aria-pressed={favoriteSet.has(symbol)} onClick={()=>toggle(symbol)}>{favoriteSet.has(symbol)?'★ Remove favorite':'☆ Add to favorites'}</button></>}
  </div>
  {visible&&<>{favoritesOnly&&!ready?<p role="status">Loading favorites…</p>:<>
   <p role="status">{rows.length.toLocaleString()} matching stocks</p>
   {!rows.length?<p>{query?'No stocks match this search.':favoritesOnly?'No favorites yet. Search in Workspace and click a star to save a stock.':'The stock universe is still loading.'}</p>:<div className="table-wrap"><table><thead><tr><th>Favorite</th><th>Stock</th><th>Company</th><th>Exchange</th><th>Chart</th></tr></thead><tbody>{rows.slice(offset,offset+limit).map(i=><tr key={i.symbol}>
    <td><button className={favoriteSet.has(i.symbol)?'favorite-star starred':'favorite-star'} disabled={!ready||pending!==null} aria-label={(favoriteSet.has(i.symbol)?'Remove ':'Add ')+i.symbol+(favoriteSet.has(i.symbol)?' from favorites':' to favorites')} aria-pressed={favoriteSet.has(i.symbol)} onClick={()=>toggle(i.symbol)}>{pending===i.symbol?'…':favoriteSet.has(i.symbol)?'★':'☆'}</button></td>
    <td>{i.symbol}</td><td>{i.name||'—'}</td><td>{i.venue||'—'}</td><td><button disabled={!instruments.some(x=>x.symbol===i.symbol)} onClick={()=>{open(i.symbol);setExpanded(false);}}>Open chart</button></td>
   </tr>)}</tbody></table></div>}
   <Pagination offset={offset} limit={limit} total={rows.length} onOffset={setOffset} onLimit={setLimit}/>
  </>}</>}
 </section>;
}
