import './globals.css';
import type { Metadata } from 'next';
export const metadata:Metadata={title:'TradePrism AI | Market research workspace',description:'Real market observations, reproducible research and manual chart analysis.'};
export default function Layout({children}:{children:React.ReactNode}) {return <html lang="en"><body>{children}</body></html>;}
