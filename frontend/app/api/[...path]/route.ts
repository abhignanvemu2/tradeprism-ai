import { NextRequest } from 'next/server';
export const dynamic = 'force-dynamic';
async function proxy(request:NextRequest, context:{params:Promise<{path:string[]}>}) {
  const {path}=await context.params;
  if(path.some(p=>!p || p==='..' || /[^a-zA-Z0-9_.-]/.test(p))) return Response.json({detail:'Invalid path'},{status:400});
  const root=process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  const content=request.method==='GET'?undefined:await request.text();
  if(content && content.length>110000) return Response.json({detail:'Request too large'},{status:413});
  try {
    const r=await fetch(`${root}/${path.join('/')}${request.nextUrl.search}`,{method:request.method,headers:{'Content-Type':'application/json','Authorization':request.headers.get('Authorization')||''},body:content,cache:'no-store',signal:AbortSignal.timeout(55000)});
    return new Response(await r.text(),{status:r.status,headers:{'Content-Type':'application/json','Cache-Control':'no-store'}});
  } catch { return Response.json({detail:'Analysis service unavailable. Start the backend and worker.'},{status:503}); }
}
export {proxy as GET,proxy as POST,proxy as PUT};
