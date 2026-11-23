'use client';
import {useEffect,useState} from 'react';
export const istToday=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export function useTradingDate(){const [today,setToday]=useState(istToday);useEffect(()=>{const id=setInterval(()=>setToday(istToday()),10000);return()=>clearInterval(id);},[]);return today;}
