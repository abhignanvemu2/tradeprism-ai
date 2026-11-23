import TradingApp from '../../../components/TradingApp';
export default async function StockPage({params}:{params:Promise<{symbol:string}>}){const {symbol}=await params;return <TradingApp key={symbol} initialSymbol={symbol}/>;}
