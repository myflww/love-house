/* Literal reuse of the approved isolated atlas, not a replacement art design.
 * Original source and every reused function are SHA-256 recorded in
 * docs/APPROVED-ATLAS-PROVENANCE.json; the unexecuted source fixture is in tests/fixtures.
 * The lexical bridge changes data/projection and suppresses duplicate host labels;
 * all nine drawing/style function bodies below are byte-for-byte source copies.
 */
import {synapseMetrics,recallActivity} from './synapse-dynamics.js';
const NativeMath=globalThis.Math;
const finite=(v,f=0)=>typeof v==='number'&&Number.isFinite(v)?v:f;
const clamp=(v,a,b)=>NativeMath.max(a,NativeMath.min(b,v));
const mix=(a,b,t)=>a+(b-a)*t;
const keyOf=(a,b)=>String(a)<String(b)?String(a)+'|'+String(b):String(b)+'|'+String(a);
function seeded(value){let seed=2166136261;for(const c of String(value))seed=NativeMath.imul(seed^c.charCodeAt(0),16777619);return()=>{seed=(NativeMath.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};}

function createApprovedDrawing(){
 let ctx,bg='#08090b',nodes=[],edges=[],dust=[],pulses=[],groups=[];
 let view=null,phase='',nodeOpacity=1,particleCount=0,totalClouds=0,lastResult=null;
 let sourceNodes=null,sourceEdges=null,byId=new Map(),allEdges=[],allDust=[],hubSignature='';
 let state={time:0,zoom:1,flat:0,selected:-1,hover:-1,focus:false,query:'',paused:false,width:1,height:1,scale:1,panX:0,panY:0};
 // drawEdges has the only Math.ceil in the verbatim block. Bound its decorative
 // sheath count to the remaining 18k frame budget without changing real edges.
 const Math=Object.create(NativeMath);
 Math.ceil=value=>NativeMath.min(NativeMath.ceil(value),NativeMath.max(0,18000-particleCount));
 const rgba=alpha=>`rgba(${view?.light?'20,23,27':'242,242,239'},${clamp(alpha*(phase==='nodes'?nodeOpacity:1),0,1)})`;
 const project=p=>{const q=view.projectLocal({x:p[0]*state.graphScale,y:-p[1]*state.graphScale,z:p[2]*state.graphScale});return{...q,ratio:NativeMath.max(.01,finite(q.ratio,1)),z:finite(q.z,finite(q.depth))};};
 const isVisible=id=>!view.visibleSet||view.visibleSet.has(id);

 function setGraph(realNodes=[],realEdges=[]){
  if(sourceNodes===realNodes&&sourceEdges===realEdges)return;
  sourceNodes=Array.isArray(realNodes)?realNodes:[];sourceEdges=Array.isArray(realEdges)?realEdges:[];
  byId=new Map(sourceNodes.map((n,i)=>[n.id,i]));
  nodes=sourceNodes.map((real,id)=>({id,real,name:String(real.label||real.name||real.id),group:0,hub:false,size:1,strength:1,baseStrength:1,freq:0,phase:seeded(String(real.id)+':phase')()*NativeMath.PI*2,current:[0,0,0],_screen:{x:0,y:0,z:0,ratio:1},opacity:1,
   get screen(){if(phase==='nodes')nodeOpacity=this.opacity;return this._screen;}}));
  Object.defineProperty(nodes,Symbol.iterator,{value:function*(){for(let i=0;i<this.length;i++)if(!view||isVisible(this[i].real.id))yield this[i];}});
  allEdges=sourceEdges.filter(e=>byId.has(e.source)&&byId.has(e.target)).map(real=>{const random=seeded(keyOf(real.source,real.target));return{a:byId.get(real.source),b:byId.get(real.target),real,strength:0,phase:random()*NativeMath.PI*2,bend:(random()-.5)*1.4};});
  allDust=[];hubSignature='';pulses=[];lastResult=null;totalClouds=0;
 }
 function rebuildDust(){
  const signature=nodes.map(n=>Number(n.hub)).join('');if(signature===hubSignature)return;
  hubSignature=signature;allDust=[];
  const desired=nodes.reduce((sum,n)=>sum+(n.hub?950:38),0),factor=NativeMath.min(1,14000/NativeMath.max(1,desired));
  for(let i=0;i<nodes.length;i++){
   const n=nodes[i],random=seeded(String(n.real.id)+':approved-dust'),count=NativeMath.floor((n.hub?950:38)*factor);
   const normal=()=>NativeMath.sqrt(-2*NativeMath.log(NativeMath.max(.00001,random())))*NativeMath.cos(2*NativeMath.PI*random());
   for(let j=0;j<count;j++){
    const a=random()*NativeMath.PI*2,r=NativeMath.pow(random(),1.25)*(n.hub?.27:.06),curl=a+r*22;
    allDust.push({node:i,offset:[NativeMath.cos(curl)*r*1.25,NativeMath.sin(curl)*r*.61,normal()*r*.48],phase:random()*6.28,size:.3+random()*.8,_alpha:.1+random()*.37,get alpha(){return this._alpha*nodes[this.node].opacity;}});
   }
  }totalClouds=allDust.length;
 }
 function prepare(realContext,nextView){
  view=nextView;setGraph(view.nodes||sourceNodes||[],view.edges||sourceEdges||[]);
  const zoom=clamp(finite(view.zoom,1),.03,18),graphScale=NativeMath.max(.001,finite(view.graphScale,NativeMath.max(90,NativeMath.sqrt(nodes.length)*23)));
  const center=view.projectLocal({x:0,y:0,z:0});
  state={...state,time:finite(view.time),zoom,flat:clamp(finite(view.flatMix),0,1),graphScale,scale:graphScale*zoom,
   selected:byId.get(view.selected)??-1,hover:byId.get(view.hover)??-1,focus:false,query:'',paused:!!view.paused,
   width:NativeMath.max(1,finite(view.W,1)),height:NativeMath.max(1,finite(view.H,1)),panX:finite(center.x)-finite(view.W,1)*.5,panY:finite(center.y)-finite(view.H,1)*.54};
  bg=view.light?'#f6f6f3':'#08090b';nodeOpacity=1;
  let maxDegree=0;const degree=new Map(nodes.map(n=>[n.real.id,0]));
  for(const e of allEdges){degree.set(e.real.source,degree.get(e.real.source)+1);degree.set(e.real.target,degree.get(e.real.target)+1);}
  for(const d of degree.values())maxDegree=NativeMath.max(maxDegree,d);
  for(let i=0;i<nodes.length;i++){
   const n=nodes[i],real=n.real,m=view.nodeMetrics?.(real)||{},p=view.projectNode(real),display=view.displayPosition(real);
   n.hub=m.hub??degree.get(real.id)>=NativeMath.max(4,maxDegree*.55);
   n.opacity=clamp(finite(m.alpha,1),0,1);if(view.active?.size&&!view.active.has(real.id))n.opacity*=.42;
   n._screen={x:finite(p.x),y:finite(p.y),z:finite(p.z,finite(p.depth)),ratio:NativeMath.max(.01,finite(p.ratio,1))};
   n.size=NativeMath.max(.2,finite(m.radius,n.hub?4.8:2.2))/(n._screen.ratio*zoom);
   n.current=[finite(display.x)/graphScale,finite(display.y)/graphScale,finite(view.nodeDepth?.(real))/graphScale];
   n.freq=recallActivity(real)*100;n.strength=n.baseStrength=1;
  }
  // The approved demo starts with its central real memory visually emphasized.
  // Map that styling default to an actual hub, without selecting or recalling it
  // in the host application. An explicit host selection always wins.
  if(state.selected<0&&nodes.length>12){
   let best=-1,bestDegree=-1;
   for(const n of nodes)if(n.hub&&isVisible(n.real.id)&&degree.get(n.real.id)>bestDegree){best=n.id;bestDegree=degree.get(n.real.id);}
   state.selected=best;
  }
  for(const e of allEdges)e.strength=synapseMetrics(e.real,nodes[e.a].real,nodes[e.b].real).association;
  edges=allEdges.filter(e=>isVisible(e.real.source)&&isVisible(e.real.target));
  rebuildDust();dust=allDust.filter(d=>isVisible(nodes[d.node].real.id));
  const categories=Array.isArray(view.categories)?view.categories:[];
  groups=categories.map(g=>({name:String(g.name||g.label||g.key||'未分类')}));
  if(!groups.length)groups=[...new Set(sourceNodes.map(n=>Array.isArray(n.tags)&&n.tags.length?String(n.tags[0]):String(n.kind||'记忆')))].sort().map(name=>({name}));
  // Host owns the names/inspector. Suppress only the original node-label text
  // and its .8-opacity background; node shapes and guide text remain verbatim.
  ctx=new Proxy(realContext,{get(target,key){
   if(key==='fillText')return(...args)=>{if(phase!=='nodes')target.fillText(...args);};
   if(key==='fillRect')return(...args)=>{if(phase==='nodes'&&target.globalAlpha===.8&&target.fillStyle===bg)return;if(phase==='cloud'||phase==='edges'){if(particleCount>=18000)return;particleCount++;}target.fillRect(...args);};
   if(key==='arc')return(...args)=>{if(phase==='edges'){if(particleCount>=18000)return;particleCount++;}target.arc(...args);};
   const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;
  },set(target,key,value){Reflect.set(target,key,value,target);return true;}});
 }
function edgeStyle(e) {
    const a=nodes[e.a],b=nodes[e.b];
    // User changes tune incident links; intrinsic association remains distinct per edge.
    const tuningA=a.strength/a.baseStrength,tuningB=b.strength/b.baseStrength;
    const association=clamp(e.strength*tuningA*tuningB,0,1);
    const frequency=Math.sqrt(a.freq*b.freq)/100;
    const stability=association*.78+frequency*.22;
    return {association,frequency,stability,width:.28+association*association*2.15+frequency*.55,alpha:.075+association*.39+frequency*.13,amplitude:2.2+Math.pow(1-stability,1.65)*43,speed:.36+(1-stability)*.9};
  }

function curveFor(e,s){
    const a=nodes[e.a].screen,b=nodes[e.b].screen;
    const dx=b.x-a.x,dy=b.y-a.y,len=Math.max(1,Math.hypot(dx,dy));
      const amplitude=s.amplitude*state.zoom*(.78+state.flat*.22);
    const wave=Math.sin(state.time*s.speed+e.phase)*amplitude;
    const offset=e.bend*Math.min(len*.33,80)*mix(1,.35,state.flat);
    const nx=-dy/len,ny=dx/len;
    return {a,b,c:{x:a.x+dx*.33+nx*(wave+offset),y:a.y+dy*.33+ny*(wave+offset)},d:{x:a.x+dx*.68-nx*(wave*.63-offset),y:a.y+dy*.68-ny*(wave*.63-offset)}};
  }

function pointAt(c,t){const u=1-t;return{x:u*u*u*c.a.x+3*u*u*t*c.c.x+3*u*t*t*c.d.x+t*t*t*c.b.x,y:u*u*u*c.a.y+3*u*u*t*c.c.y+3*u*t*t*c.d.y+t*t*t*c.b.y};}

function path(c,offset=0){ctx.beginPath();ctx.moveTo(c.a.x,c.a.y);ctx.bezierCurveTo(c.c.x+offset,c.c.y-offset,c.d.x+offset,c.d.y-offset,c.b.x,c.b.y);}

function drawFlatGuide(){
    if(state.flat<.01)return;
    ctx.save();const a=state.flat;
    const center={x:state.width*.5+state.panX,y:state.height*.54+state.panY};
    const r=state.scale;
    [.27,.47,.67,.87].forEach((radius,i)=>{
      ctx.beginPath();ctx.arc(center.x,center.y,r*radius,0,Math.PI*2);ctx.strokeStyle=rgba(a*.075);ctx.lineWidth=1;ctx.stroke();
      ctx.fillStyle=rgba(a*.38);ctx.font='9px -apple-system, sans-serif';ctx.textAlign='left';ctx.fillText(['高频 · 内圈','经常想起','偶尔想起','遥远 · 外圈'][i],center.x+9,center.y-radius*r-5);
    });
    groups.forEach((g,i)=>{
      const angle=-Math.PI/2+i*Math.PI/3;
      const x=center.x+Math.cos(angle)*r*1.02,y=center.y+Math.sin(angle)*r*1.02;
      ctx.font='10px -apple-system, sans-serif';ctx.textAlign='center';ctx.fillStyle=rgba(a*.55);ctx.fillText(g.name,x,y);
      ctx.save();ctx.setLineDash([2,7]);ctx.strokeStyle=rgba(a*.055);ctx.beginPath();ctx.moveTo(center.x,center.y);ctx.lineTo(center.x+Math.cos(angle+Math.PI/6)*r*.93,center.y+Math.sin(angle+Math.PI/6)*r*.93);ctx.stroke();ctx.restore();
    });
    ctx.restore();
  }

function drawCloud(related){
    const flatDim=1-state.flat*.88;
    for(const d of dust){
      const n=nodes[d.node],p=n.current;
      const swirl=state.time*.035+d.phase;
      const cos=Math.cos(swirl)*.013, sn=Math.sin(swirl)*.013;
      const collapse=mix(1,.25,state.flat);
      const pp=project([p[0]+(d.offset[0]+cos)*collapse,p[1]+(d.offset[1]+sn)*collapse,p[2]+d.offset[2]*collapse]);
      let alpha=d.alpha*flatDim;
      if(state.focus&&!related.has(n.id))alpha*=.075;
      if(state.query&&!n.name.includes(state.query)&&!groups[n.group].name.includes(state.query))alpha*=.18;
      ctx.fillStyle=rgba(alpha);const r=d.size*pp.ratio*state.zoom;
      ctx.fillRect(pp.x,pp.y,r,r);
    }
  }

function drawEdges(related){
    const selected=state.selected;
    for(const e of edges){
      const s=edgeStyle(e),incident=e.a===selected||e.b===selected,c=curveFor(e,s);e.curve=c;
      let alpha=s.alpha*(incident?1.24:.6);
      if(state.focus&&!incident)alpha*=.065;
      if(state.query&&!nodes[e.a].name.includes(state.query)&&!nodes[e.b].name.includes(state.query)&&!groups[nodes[e.a].group].name.includes(state.query)&&!groups[nodes[e.b].group].name.includes(state.query))alpha*=.14;
      // A soft outer sheath and multiple fine fibers keep strong synapses organic.
      if(incident&&s.association>.65){path(c);ctx.lineWidth=s.width*state.zoom*5;ctx.strokeStyle=rgba(alpha*.04);ctx.stroke();}
      path(c);ctx.lineWidth=s.width*state.zoom*(incident?1:.7);ctx.strokeStyle=rgba(alpha);ctx.stroke();
      if(s.association>.69){for(const off of [-2.7,-1.3,1.3,2.7]){path(c,off*state.zoom);ctx.lineWidth=.3*state.zoom;ctx.strokeStyle=rgba(alpha*.26);ctx.stroke();}}
      // Small flowing filaments form a visible point-cloud sheath, derived only
      // from real demo edges. These are decoration, never additional memories.
      if(state.flat<.98){
        const len=Math.hypot(c.b.x-c.a.x,c.b.y-c.a.y),count=Math.ceil(len*.24);
        for(let j=0;j<count;j++){
          const t=(j/count+state.time*.006*(1+s.frequency)+e.phase*.07)%1;
          const p=pointAt(c,t),q=pointAt(c,Math.min(.999,t+.01));
          const dx=q.x-p.x,dy=q.y-p.y,l=Math.max(.001,Math.hypot(dx,dy));
          const spread=Math.sin(t*Math.PI)*(1.5+s.association*4.7)*state.zoom;
          const noise=Math.sin(j*91.73+e.phase)*spread;
          ctx.fillStyle=rgba(alpha*(1-state.flat)*(.17+Math.sin(j*7.3)**2*.4));
          ctx.fillRect(p.x-dy/l*noise,p.y+dx/l*noise,.65*state.zoom,.65*state.zoom);
        }
      }
      if(!state.paused){
        const period=mix(18,5,s.frequency),t=(state.time/period+e.phase)%1;
        if(t<.88){const p=pointAt(c,t/.88);const brightness=alpha*.72*Math.sin(t/.88*Math.PI);ctx.beginPath();ctx.arc(p.x,p.y,(incident?1.4:.7)*state.zoom,0,Math.PI*2);ctx.fillStyle=rgba(brightness);ctx.fill();}
      }
    }
  }

function drawNodes(related){
    const placed=[],labels=[];
    for(const n of [...nodes].sort((a,b)=>b.screen.z-a.screen.z)){
      const p=n.screen, selected=n.id===state.selected, hover=n.id===state.hover;
      let alpha=n.hub?.88:.48;
      if(state.focus&&!related.has(n.id))alpha*=.1;
      if(state.query&&!n.name.includes(state.query)&&!groups[n.group].name.includes(state.query))alpha*=.16;
      const breathing=1+Math.sin(state.time*.7+n.phase)*.07;
      const size=n.size*p.ratio*state.zoom*breathing;
      const glow=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,size*7);
      glow.addColorStop(0,rgba(alpha*.2));glow.addColorStop(.26,rgba(alpha*.045));glow.addColorStop(1,rgba(0));
      ctx.fillStyle=glow;ctx.fillRect(p.x-size*7,p.y-size*7,size*14,size*14);
      ctx.beginPath();ctx.arc(p.x,p.y,selected?size*1.1:size,0,Math.PI*2);ctx.fillStyle=rgba(alpha);ctx.fill();
      if(n.hub){ctx.beginPath();ctx.arc(p.x,p.y,size*2.15,0,Math.PI*2);ctx.lineWidth=.5;ctx.strokeStyle=rgba(alpha*.28);ctx.stroke();}
      if(selected||hover){ctx.save();ctx.translate(p.x,p.y);ctx.rotate(state.time*.08);ctx.setLineDash([14,9,4,9]);ctx.beginPath();ctx.arc(0,0,size+13,0,Math.PI*2);ctx.strokeStyle=rgba(.65);ctx.lineWidth=.7;ctx.stroke();ctx.restore();}
      // Labels are collision-checked, with the selected memory always taking priority.
      if(n.hub||selected||hover||(state.flat>.9&&related.has(n.id))||(state.query&&n.name.includes(state.query))){
        labels.push({n,p,selected,hover,alpha,size});
      }
    }
    labels.sort((a,b)=>(b.selected*10+b.hover*5+b.n.hub)-(a.selected*10+a.hover*5+a.n.hub));
    for(const {n,p,selected,hover,alpha,size} of labels){
        const text=n.name,fs=selected?12:n.hub?11:9;
        ctx.font=`${fs}px -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif`;
        const tw=ctx.measureText(text).width, tx=p.x+size+11, ty=p.y-7;
        const bounds={x:tx-4,y:ty-11,w:tw+8,h:selected?34:19};
        if(tx+tw>state.width-30||tx<8||ty<175||ty>state.height-125)continue;
        if(placed.some(b=>bounds.x<b.x+b.w&&bounds.x+bounds.w>b.x&&bounds.y<b.y+b.h&&bounds.y+bounds.h>b.y))continue;
        placed.push(bounds);ctx.fillStyle=bg;ctx.globalAlpha=.8;ctx.fillRect(bounds.x,bounds.y,bounds.w,bounds.h);ctx.globalAlpha=1;
        ctx.fillStyle=rgba(selected?1:alpha*.85);ctx.textAlign='left';ctx.fillText(text,tx,ty+2);
        if(selected){ctx.fillStyle=rgba(.4);ctx.font='8px -apple-system,sans-serif';ctx.fillText(`M—${String(n.id+1).padStart(3,'0')}  /  ${n.freq} 次调用`,tx,ty+17);}
    }
  }

function drawPulses(){
    pulses.forEach(p=>{
      const elapsed=state.time-p.start;
      const n=nodes[p.node],q=n.screen;
      if(elapsed<2.1){const radius=elapsed*52*state.zoom;ctx.beginPath();ctx.arc(q.x,q.y,radius,0,Math.PI*2);ctx.strokeStyle=rgba((1-elapsed/2.1)*.32);ctx.lineWidth=1;ctx.stroke();}
      edges.forEach(e=>{
        if(e.a!==p.node&&e.b!==p.node)return;
        const duration=1.25+(1-edgeStyle(e).association)*1.4,t=elapsed/duration;
        if(t<0||t>1||!e.curve)return;
        const c=e.curve,at=e.a===p.node?t:1-t,pos=pointAt(c,at);
        path(c);ctx.lineWidth=edgeStyle(e).width*1.35*state.zoom;ctx.strokeStyle=rgba(Math.sin(t*Math.PI)*.36);ctx.stroke();
        const glow=ctx.createRadialGradient(pos.x,pos.y,0,pos.x,pos.y,13*state.zoom);glow.addColorStop(0,rgba(.7));glow.addColorStop(.22,rgba(.2));glow.addColorStop(1,rgba(0));ctx.fillStyle=glow;ctx.fillRect(pos.x-13*state.zoom,pos.y-13*state.zoom,26*state.zoom,26*state.zoom);ctx.fillStyle=rgba(.98);ctx.beginPath();ctx.arc(pos.x,pos.y,2.2*state.zoom,0,Math.PI*2);ctx.fill();
      });
    });
    while(pulses.length&&state.time-pulses[0].start>4)pulses.shift();
  }

 function paint(realContext,nextView){
  prepare(realContext,nextView);particleCount=0;realContext.save();
  const related=new Set([state.selected,...edges.filter(e=>e.a===state.selected||e.b===state.selected).map(e=>e.a===state.selected?e.b:e.a)]);
  try{
   phase='cloud';drawCloud(related);
   phase='edges';drawEdges(related);
   phase='nodes';drawNodes(related);nodeOpacity=1;
   // Original pulse renderer is fed ONLY a newly observed, real recall result.
   // Its edge iterator is restricted to that result's actual lit trail edges.
   const trail=Array.isArray(view.result?.trail)?view.result.trail:[];
   if(view.result!==lastResult){
    lastResult=view.result;pulses=[];const seen=new Set();
    for(const t of trail){const from=Array.isArray(t)?t[0]:t.from,to=Array.isArray(t)?t[1]:t.to,key=keyOf(from,to),index=byId.get(from);
     if(index!==undefined&&view.lit?.has(key)&&isVisible(from)&&isVisible(to)&&!seen.has(index)){seen.add(index);pulses.push({node:index,start:state.time});}}
   }
   const realEdges=edges,trailKeys=new Set(trail.map(t=>keyOf(Array.isArray(t)?t[0]:t.from,Array.isArray(t)?t[1]:t.to)));
   edges=realEdges.filter(e=>view.lit?.has(keyOf(e.real.source,e.real.target))&&trailKeys.has(keyOf(e.real.source,e.real.target)));
   phase='pulses';drawPulses();edges=realEdges;
  }finally{phase='';nodeOpacity=1;realContext.restore();}
  return{particleCount,visibleFiberEdges:edges.length,cloudParticleCount:totalClouds};
 }
 function drawGuide(realContext,nextView){prepare(realContext,nextView);if(nodes.length<3||nodes.filter(n=>isVisible(n.real.id)).length<3)return;realContext.save();try{phase='guide';drawFlatGuide();}finally{phase='';realContext.restore();}}
 function dispose(){sourceNodes=sourceEdges=null;nodes=[];edges=[];allEdges=[];dust=[];allDust=[];pulses=[];groups=[];byId.clear();hubSignature='';lastResult=null;particleCount=totalClouds=0;ctx=null;view=null;}
 return{setGraph,paint,drawGuide,dispose};
}

export class ApprovedAtlasPainter{
 constructor(){this.drawing=createApprovedDrawing();this.particleCount=0;this.visibleFiberEdges=0;this.cloudParticleCount=0;}
 setGraph(nodes,edges){this.drawing.setGraph(nodes,edges);}
 paint(ctx,view){const result=this.drawing.paint(ctx,view);Object.assign(this,result);return result;}
 drawGuide(ctx,view){return this.drawing.drawGuide(ctx,view);}
 dispose(){this.drawing.dispose();this.particleCount=this.visibleFiberEdges=this.cloudParticleCount=0;}
}
