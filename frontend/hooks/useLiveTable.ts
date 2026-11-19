'use client';
import {useEffect,useState} from 'react';
export type Api=(path:string)=>Promise<any>;
export function useDebounced(value:string){const [valueAfterDelay,setValue]=useState(value);useEffect(()=>{const t=setTimeout(()=>setValue(value),300);return()=>clearTimeout(t);},[value]);return valueAfterDelay;}
export function useLiveTable(api:Api,path:string,interval=5000){
 const [data,setData]=useState<any>(null),[error,setError]=useState('');
 useEffect(()=>{let active=true,pending=false;setData(null);setError('');async function load(){if(pending)return;pending=true;try{const result=await api(path);if(active){setData(result);setError('');}}catch(e){if(active)setError((e as Error).message);}finally{pending=false;}}load();const timer=setInterval(load,interval);return()=>{active=false;clearInterval(timer);};},[api,path,interval]);
 return {data,error};
}
