/* Actual Canvas lifecycle/projection adapter. No GPU, RAF, model or real data. */
import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from '../../nkb/viz/art/node_modules/three/build/three.module.js';
globalThis.window={};
globalThis.document={hidden:false,documentElement:{dataset:{theme:'dark'}}};
globalThis.matchMedia=()=>({matches:false});
const {NeuralArt}=await import('../../nkb/viz/art/neural-art.js');
const {createApprovedAtlasRenderer}=await import('../../nkb/viz/art/approved-atlas-renderer.js');
class NeverConstructed extends NeuralArt{
 constructor(){throw new Error('The approved Canvas adapter must not construct Base/WebGL');}
 render(){throw new Error('The approved Canvas adapter must not call Base render');}
}
const Renderer=createApprovedAtlasRenderer(NeverConstructed);

function surface(context=true){
 const calls=[],handlers=new Map(),doc={addEventListener(){},removeEventListener(){}};
 const gradient={addColorStop(){}};
 const ctx=new Proxy({calls,measureText:text=>({width:String(text).length*7}),createRadialGradient:()=>gradient,createLinearGradient:()=>gradient},
  {get(target,key){return key in target?target[key]:(...args)=>{if(calls.length<1500)calls.push([key,...args]);};}});
 const canvas={dataset:{},style:{},clientWidth:1000,clientHeight:700,ownerDocument:doc,
  getRootNode:()=>doc,getBoundingClientRect:()=>({left:0,top:0,width:1000,height:700}),
  addEventListener(type,fn){handlers.set(type,fn);},removeEventListener(type){handlers.delete(type);},
  getContext(type){assert.equal(type,'2d','must not acquire WebGL');return context?ctx:null;}};
 return{canvas,ctx,calls,handlers};
}
function graph(count){
 const nodes=Array.from({length:count},(_,i)=>({id:'n'+i,label:'Synthetic '+i,kind:'episode',tags:['topic'+i%3],state:'active',recalls:i%90,salience:.6,
  x:Math.cos(i*2.4)*Math.sqrt(i)*20,y:Math.sin(i*2.4)*Math.sqrt(i)*20}));
 const edges=nodes.slice(1).map((n,i)=>({source:'n0',target:n.id,effective_w:.2+(i%8)*.1}));return{nodes,edges};
}
function state(g,extra={}){return{...g,W:1000,H:700,art:true,graphMode:'nebula',cam:{x:500,y:350,k:1},visible:g.nodes,visibleSet:new Set(g.nodes.map(n=>n.id)),adj:new Map(),active:new Map(),lit:new Map(),...extra};}
function art(){const env=surface(),renderer=new Renderer(env.canvas,env.canvas);renderer.resize(1000,700,2);return{...env,renderer};}
function near(a,b,tolerance=1e-5){assert.ok(Math.abs(a-b)<=tolerance,`${a} != ${b}`);}

test('constructs a standalone 2D adapter with all host APIs and no Base/WebGL/RAF',()=>{
 const old=globalThis.requestAnimationFrame;globalThis.requestAnimationFrame=()=>{throw new Error('adapter cannot own RAF');};
 const {renderer:r,canvas}=art();
 try{
  for(const name of ['resize','setGraph','render','projectNode','displayPosition','nodeDepth','projectLocal','projectedBounds','syncTransform','screenDeltaToTranslation','panCamera','centerNode','captureScreenPoint','restoreScreenPoint','resetView','setEnabled','dispose','isTransitioning','drawPlaneGuide','readableCoreDiameter','radiusOnScreen'])assert.equal(typeof r[name],'function',name);
  assert.equal(canvas.width,2000);assert.equal(canvas.height,1400);assert.equal(r.renderer,undefined);
  const g=graph(2);r.render(state(g),1000);assert.equal(canvas.dataset.painter,'approved-canvas');
 }finally{r.dispose();globalThis.requestAnimationFrame=old;}
 assert.throws(()=>new Renderer(surface(false).canvas),/2D atlas context unavailable/);
});

test('empty and sparse data keep exactly the real graph and bounded readable cores',()=>{
 for(const count of [0,1,2,12]){
  const {renderer:r,canvas}=art(),g=graph(count),s=state(g),before=JSON.stringify(g);r.render(s,1000);
  assert.equal(r.nodes,g.nodes);assert.equal(r.edges,g.edges);assert.equal(canvas.dataset.fiberEdges,String(g.edges.length));
  if(!count){assert.equal(r.projectedBounds([],s),null);assert.equal(canvas.dataset.particleCount,'0');}
  for(const n of g.nodes){assert.ok(r.readableCoreDiameter(n,s)>=9);assert.ok(r.radiusOnScreen(n,s)>=r.readableCoreDiameter(n,s)/2);}
  assert.equal(JSON.stringify(g),before);r.dispose();
 }
});

test('real topology separates dense hubs and leaves without making every cell large',()=>{
 for(const count of [90,225]){
  const {renderer:r}=art(),g=graph(count),s=state(g);r.setGraph(g.nodes,g.edges);
  const hub=r.nodeMetrics(g.nodes[0],s),leaf=r.nodeMetrics(g.nodes[1],s);
  assert.equal(hub.hub,true);assert.equal(leaf.hub,false);
  near(hub.radius,4.8);assert.ok(leaf.radius>=1.7&&leaf.radius<=3);assert.ok(hub.radius>leaf.radius);
  const differentSalience={...g.nodes[1],salience:0,effective_salience:1};near(r.nodeMetrics(differentSalience,s).radius,leaf.radius);
  const closer={...s,cam:{...s.cam,k:2}};assert.ok(r.readableCoreDiameter(g.nodes[1],closer)>leaf.radius*2);
  const hidden={...s,visibleSet:new Set()};assert.equal(r.readableCoreDiameter(g.nodes[0],hidden),0);assert.equal(r.radiusOnScreen(g.nodes[0],hidden),0);
  r.dispose();
 }
});

test('camera projection, screen-anchor zoom and centering use the displayed coordinates',()=>{
 const {renderer:r}=art(),g=graph(8),s=state(g);r.setGraph(g.nodes,g.edges);r.flatMix=1;r.lastMode='flat';r.resetView();
 r.syncTransform(s);const n=g.nodes[3],display=r.displayPosition(n),p=r.projectNode(n);
 near(p.x,display.x+500);near(p.y,display.y+350);near(r.nodeDepth(n),0);
 const anchor=r.captureScreenPoint(p.x,p.y,s),zoom={...s,cam:{...s.cam,k:2}};
 r.restoreScreenPoint(anchor,p.x,p.y,zoom);const held=r.projectLocal(anchor);near(held.x,p.x);near(held.y,p.y);
 r.centerNode(n,zoom);const centered=r.projectNode(n);near(centered.x,500);near(centered.y,350);
 const shift=r.screenDeltaToTranslation(25,-12);r.syncTransform(zoom);const before=r.projectNode(n);
 r.syncTransform({...zoom,cam:{...zoom.cam,x:zoom.cam.x+shift.x,y:zoom.cam.y+shift.y}});const after=r.projectNode(n);near(after.x-before.x,25);near(after.y-before.y,-12);
 r.dispose();
});

test('pause freezes decorative time while morphs complete and rapid reversals preserve orbit',()=>{
 const {renderer:r,canvas}=art(),g=graph(8),s=state(g),before=JSON.stringify(g);
 r.render(s,1000);r.render(s,1100);const moving=r.motionTime;assert.ok(moving>0);
 s.paused=true;r.render(s,1200);r.render(s,2500);assert.equal(r.motionTime,moving);
 const orbit=r.camera.position.clone();s.graphMode='flat';
 for(let t=2600;t<5600;t+=100)r.render(s,t);
 assert.equal(r.flatMix,1);assert.equal(r.isTransitioning(),false);assert.equal(r.controls.enabled,false);
 r.panCamera(30,15);const panned=r.camera.position.clone();r.render(s,5700);assert.deepEqual(r.camera.position,panned);
 s.graphMode='nebula';r.render(s,5800);s.graphMode='flat';r.render(s,5900);assert.deepEqual(r.orbitSnapshot.position,orbit);
 s.graphMode='nebula';for(let t=6000;t<9000;t+=100)r.render(s,t);
 assert.equal(r.flatMix,0);assert.deepEqual(r.camera.position,orbit);assert.equal(r.motionTime,moving);
 assert.equal(canvas.dataset.motionTime,moving.toFixed(3));assert.equal(JSON.stringify(g),before);r.dispose();
});

test('theme, reduced motion, filtering and pre-render fit need no graph mutation',()=>{
 const {renderer:r,canvas}=art(),g=graph(12),s=state(g),before=JSON.stringify(g);
 globalThis.document.documentElement.dataset.theme='light';globalThis.matchMedia=()=>({matches:true});s.graphMode='flat';r.render(s,1000);
 assert.equal(r.flatMix,1);assert.equal(r.shared.uLight.value,1);assert.equal(canvas.dataset.graphMode,'flat');
 s.visibleSet.delete('n2');r.render(s,1100);assert.equal(canvas.dataset.visibleFiberEdges,String(g.edges.length-1));
 const next=graph(3);for(const n of next.nodes){n.x=1e8;n.y=-1e8;}
 const nextState=state(next,{graphMode:'flat'}),box=r.projectedBounds(next.nodes,nextState);assert.equal(r.nodes,next.nodes);assert.equal(box.count,3);
 for(const n of next.nodes)assert.ok(Math.abs(r.displayPosition(n).x)<300);
 assert.equal(JSON.stringify(g),before);r.dispose();
 globalThis.document.documentElement.dataset.theme='dark';globalThis.matchMedia=()=>({matches:false});
});

test('guide delegates to the approved painter and disposal releases input/data once',()=>{
 const {renderer:r,ctx,handlers}=art(),g=graph(8),s=state(g);r.setGraph(g.nodes,g.edges);r.flatMix=1;
 let guides=0,disposals=0;r.painter.drawGuide=(actual,view)=>{assert.equal(actual,ctx);assert.equal(view.nodes,g.nodes);guides++;};
 r.drawPlaneGuide(ctx,s);assert.equal(guides,1);r.drawPlaneGuide(ctx,{...s,visibleSet:new Set(['n0'])});assert.equal(guides,1);
 const dispose=r.painter.dispose.bind(r.painter);r.painter.dispose=()=>{disposals++;dispose();};
 assert.ok(handlers.size>0);r.dispose();r.dispose();assert.equal(disposals,1);assert.equal(handlers.size,0);assert.equal(r.nodes.length,0);assert.equal(r.byId.size,0);
});

test('approved flat data adapter is stable under graph reordering and keeps real IDs immutable',()=>{
 for(const count of [0,1,2,12,90]){
  const {renderer:r}=art(),g=graph(count),before=JSON.stringify(g);r.setGraph(g.nodes,g.edges);
  const targets=new Map(r.flatTargets);r.setGraph(g.nodes.slice().reverse(),g.edges.slice().reverse());
  assert.equal(r.flatTargets.size,count);
  for(const n of g.nodes){assert.deepEqual(r.flatTargets.get(n.id),targets.get(n.id));assert.ok(Number.isFinite(r.flatTargets.get(n.id).x));}
  assert.equal(JSON.stringify(g),before);r.dispose();
 }
});

test('both approved layouts ignore native physics coordinates without writing to real memories',()=>{
 const {renderer:r}=art(),g=graph(90),s=state(g);r.setGraph(g.nodes,g.edges);r.syncTransform(s);
 const displayed=new Map();
 for(const mix of [0,.5,1]){r.flatMix=mix;displayed.set(mix,g.nodes.map(n=>({...r.displayPosition(n),z:r.nodeDepth(n)})));}
 // Simulate the host's existing force simulation, outside the renderer.
 for(const n of g.nodes){n.x+=1e6;n.y-=2e6;}
 const afterPhysics=JSON.stringify(g);r.setGraph(g.nodes,g.edges);
 for(const mix of [0,.5,1]){r.flatMix=mix;assert.deepEqual(g.nodes.map(n=>({...r.displayPosition(n),z:r.nodeDepth(n)})),displayed.get(mix));}
 const refreshed={nodes:g.nodes.map(n=>({...n})),edges:g.edges.map(e=>({...e}))};r.setGraph(refreshed.nodes,refreshed.edges);
 for(const mix of [0,.5,1]){r.flatMix=mix;assert.deepEqual(refreshed.nodes.map(n=>({...r.displayPosition(n),z:r.nodeDepth(n)})),displayed.get(mix));}
 assert.equal(JSON.stringify(g),afterPhysics);assert.equal(JSON.stringify(refreshed),afterPhysics);r.dispose();assert.equal(r.nebulaTargets.size,0);
});
