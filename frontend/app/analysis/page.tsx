import {redirect} from 'next/navigation';
export default async function Page({searchParams}:{searchParams:Promise<{symbol?:string}>}){
 const {symbol}=await searchParams;
 redirect('/?view=Analysis'+(typeof symbol==='string'?'&symbol='+encodeURIComponent(symbol):''));
}
