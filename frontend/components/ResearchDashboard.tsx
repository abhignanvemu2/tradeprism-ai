'use client';
import MarketNotice from './MarketNotice';
import StocksTable from './StocksTable';
import ForecastTable from './ForecastTable';
import DailySummary from './DailySummary';
import type {Api} from '../hooks/useLiveTable';
export default function ResearchDashboard({open,api}:{api:Api;open:(symbol:string,tf:string)=>void}){
 return <><MarketNotice api={api}/><DailySummary api={api}/><StocksTable api={api} open={open}/><ForecastTable api={api} open={open}/></>;
}
