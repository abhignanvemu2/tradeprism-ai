import {Suspense} from 'react';
import TradingApp from '../../../components/TradingApp';
export default async function StockPage({params}:{params:Promise<{symbol:string}>}){const {symbol}=await params;return <Suspense fallback={<p>Opening stock…</p>}><TradingApp key={symbol} initialSymbol={symbol}/></Suspense>;}
