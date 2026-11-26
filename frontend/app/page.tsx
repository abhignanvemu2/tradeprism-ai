import {Suspense} from 'react';
import TradingApp from '../components/TradingApp';
export default function Page(){return <Suspense fallback={<p>Opening TradePrism…</p>}><TradingApp/></Suspense>;}
