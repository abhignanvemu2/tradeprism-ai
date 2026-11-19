'use client';
import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
type Counts={rising:number;falling:number;unchanged:number;unavailable:number};
const groups=[['rising','Rising','#29dfbe'],['falling','Falling','#ff6c8c'],['unchanged','Unchanged','#ac91ff'],['unavailable','No price comparison','#687b98']] as const;
export default function MarketOverview({counts}:{counts?:Counts}){
 const host=useRef<HTMLDivElement>(null),update=useRef<((c?:Counts)=>void)|null>(null),latest=useRef(counts);
 const [paused,setPaused]=useState(false),[fallback,setFallback]=useState(false);
 useEffect(()=>{latest.current=counts;update.current?.(counts);},[counts]);
 useEffect(()=>{
  if(!host.current)return;
  const el=host.current,media=window.matchMedia('(prefers-reduced-motion: reduce)');let reduced=media.matches||paused;
  let renderer:THREE.WebGLRenderer;
  try{renderer=new THREE.WebGLRenderer({alpha:true,antialias:true});}catch{setFallback(true);return;}
  setFallback(false);renderer.setPixelRatio(Math.min(window.devicePixelRatio,1.5));renderer.setClearColor(0,0);el.appendChild(renderer.domElement);
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(40,1,.1,40);camera.position.set(5,4.8,9);camera.lookAt(0,1,0);
  const cluster=new THREE.Group();scene.add(cluster);
  scene.add(new THREE.AmbientLight(0xffffff,2));const light=new THREE.DirectionalLight(0xffffff,4);light.position.set(2,6,5);scene.add(light);
  const geometry=new THREE.BoxGeometry(.85,1,.85),materials=groups.map(g=>new THREE.MeshStandardMaterial({color:g[2],metalness:.25,roughness:.35}));
  const bars=materials.map((m,i)=>{const b=new THREE.Mesh(geometry,m);b.position.x=(i-1.5)*1.35;cluster.add(b);return b;});
  const grid=new THREE.GridHelper(8,16,0x475577,0x24324b);scene.add(grid);
  let targets=[.02,.02,.02,.02],frame=0,visible=true,disposed=false,mx=0,my=0;
  const apply=(snap=false)=>{bars.forEach((b,i)=>{b.scale.y=snap?targets[i]:THREE.MathUtils.lerp(b.scale.y,targets[i],.12);b.position.y=b.scale.y/2;});};
  const render=()=>renderer.render(scene,camera);
  const animate=()=>{frame=0;if(disposed||!visible||document.hidden||reduced)return;apply();cluster.rotation.y=THREE.MathUtils.lerp(cluster.rotation.y,mx*.12,.06);cluster.rotation.x=THREE.MathUtils.lerp(cluster.rotation.x,my*.04,.06);render();frame=requestAnimationFrame(animate);};
  const resume=()=>{if(frame)cancelAnimationFrame(frame);frame=0;if(disposed||!visible||document.hidden)return;if(reduced){apply(true);render();}else frame=requestAnimationFrame(animate);};
  update.current=(value)=>{const values=groups.map(g=>value?.[g[0]]||0),max=Math.max(1,...values);targets=values.map(n=>Math.max(.02,n/max*2.7));if(reduced)apply(true);resume();};
  update.current(latest.current);apply(true);
  const resize=new ResizeObserver(()=>{const w=el.clientWidth,h=el.clientHeight;if(w&&h){renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();render();}});resize.observe(el);
  const observer=new IntersectionObserver(entries=>{visible=entries[0].isIntersecting;resume();});observer.observe(el);
  const pointer=(e:PointerEvent)=>{const box=el.getBoundingClientRect();mx=(e.clientX-box.left)/box.width-.5;my=(e.clientY-box.top)/box.height-.5;};
  const motion=()=>{reduced=media.matches||paused;resume();};
  el.addEventListener('pointermove',pointer);media.addEventListener('change',motion);document.addEventListener('visibilitychange',resume);resume();
  return()=>{disposed=true;cancelAnimationFrame(frame);update.current=null;resize.disconnect();observer.disconnect();el.removeEventListener('pointermove',pointer);media.removeEventListener('change',motion);document.removeEventListener('visibilitychange',resume);geometry.dispose();materials.forEach(m=>m.dispose());grid.geometry.dispose();(Array.isArray(grid.material)?grid.material:[grid.material]).forEach(m=>m.dispose());renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();};
 },[paused]);
 return <section className="panel market-overview"><div className="panel-heading"><div><span className="eyebrow">MARKET SNAPSHOT · AUTO-REFRESH</span><h2>See which way stocks are moving</h2><p>All stocks matching the table filters, using last available prices versus previous close. Prices may be stale or the market closed. Heights compare stock counts, not future returns.</p></div><button aria-pressed={paused} onClick={()=>setPaused(!paused)}>{paused?'Enable animation':'Pause animation'}</button></div><div className="market-scene" ref={host} aria-hidden="true"/>{fallback&&<p className="source-note">3D is unavailable on this device. Live counts remain available below.</p>}<div className="breadth-legend">{groups.map(([key,label,color])=><div key={key} style={{borderTopColor:color}}><span>{label}</span><strong>{counts?counts[key].toLocaleString():'—'}</strong></div>)}</div></section>;
}
