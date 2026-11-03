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
 const calls=[],handlers=new Map(),documentHandlers=new Map(),windowHandlers=new Map(),capture=new WeakMap();
 const target=map=>({addEventListener(type,fn,options){if(!map.has(type))map.set(type,new Set());map.get(type).add(fn);capture.set(fn,options===true||options?.capture===true);},
  removeEventListener(type,fn){map.get(type)?.delete(fn);if(!map.get(type)?.size)map.delete(type);}});
 const doc={...target(documentHandlers),get hidden(){return globalThis.document.hidden;},defaultView:target(windowHandlers)};
 const gradient={addColorStop(){}};
 const ctx=new Proxy({calls,measureText:text=>({width:String(text).length*7}),createRadialGradient:()=>gradient,createLinearGradient:()=>gradient},
  {get(target,key){return key in target?target[key]:(...args)=>{if(calls.length<1500)calls.push([key,...args]);};}});
 const canvas={dataset:{},style:{},clientWidth:1000,clientHeight:700,ownerDocument:doc,setPointerCapture(){},releasePointerCapture(){},
  getRootNode:()=>doc,getBoundingClientRect:()=>({left:0,top:0,width:1000,height:700}),
  ...target(handlers),
  getContext(type){assert.equal(type,'2d','must not acquire WebGL');return context?ctx:null;}};
 const emit=(type,event={})=>{const payload={pointerId:event.pointerId??1,pointerType:event.pointerType??'mouse',clientX:500,clientY:350,pageX:500,pageY:350,button:0,buttons:type==='pointerup'?0:1,ctrlKey:false,metaKey:false,shiftKey:false,preventDefault(){},...event};for(const fn of [...handlers.get(type)||[]].sort((a,b)=>Number(capture.get(b))-Number(capture.get(a))))fn(payload);};
 canvas.dispatchEvent=event=>{emit(event.type,event);return true;};
 const emitDocument=type=>{for(const fn of [...documentHandlers.get(type)||[]])fn({});};
 const emitWindow=type=>{for(const fn of [...windowHandlers.get(type)||[]])fn({});};
 return{canvas,ctx,calls,handlers,documentHandlers,windowHandlers,emit,emitDocument,emitWindow};
}
function graph(count){
 const nodes=Array.from({length:count},(_,i)=>({id:'n'+i,label:'Synthetic '+i,kind:'episode',tags:['topic'+i%3],state:'active',recalls:i%90,salience:.6,
  x:Math.cos(i*2.4)*Math.sqrt(i)*20,y:Math.sin(i*2.4)*Math.sqrt(i)*20}));
 const edges=nodes.slice(1).map((n,i)=>({source:'n0',target:n.id,effective_w:.2+(i%8)*.1}));return{nodes,edges};
}
function state(g,extra={}){return{...g,W:1000,H:700,art:true,graphMode:'nebula',cam:{x:500,y:350,k:1},visible:g.nodes,visibleSet:new Set(g.nodes.map(n=>n.id)),adj:new Map(),active:new Map(),lit:new Map(),...extra};}
function art(){const env=surface(),renderer=new Renderer(env.canvas,env.canvas);renderer.resize(1000,700,2);return{...env,renderer};}
function near(a,b,tolerance=1e-5){assert.ok(Math.abs(a-b)<=tolerance,`${a} != ${b}`);}
function vectorNear(a,b){assert.ok(a.distanceTo(b)<1e-8,`${JSON.stringify(a)} != ${JSON.stringify(b)}`);}

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
 assert.equal(r.flatMix,0);vectorNear(r.camera.position,orbit);assert.equal(r.motionTime,moving);
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

test('idle nebula yaw slowly carries foreground right to left without modifying memory or displayed layout',()=>{
 const {renderer:r,canvas}=art(),g=graph(12),s=state(g),before=JSON.stringify(g);
 r.camera.position.set(0,0,1200);r.controls.target.set(0,0,0);r.controls.update();
 r.render(s,1000);const point={x:0,y:0,z:100},start=r.projectLocal(point),target=r.controls.target.clone();
 const layout=g.nodes.map(n=>({...r.displayPosition(n),z:r.nodeDepth(n)})),distance=r.camera.position.distanceTo(target);
 r.render(s,2000);const end=r.projectLocal(point);
 near(r.autoRotateYaw,.035);assert.ok(end.x<start.x-3,'near-side foreground must drift left');near(end.y,start.y);
 near(r.camera.position.distanceTo(target),distance);assert.deepEqual(r.controls.target,target);
 assert.deepEqual(g.nodes.map(n=>({...r.displayPosition(n),z:r.nodeDepth(n)})),layout);assert.equal(JSON.stringify(g),before);
 assert.equal(canvas.dataset.autoRotate,'true');assert.equal(canvas.dataset.autoRotateReason,'rotating');assert.equal(canvas.dataset.autoRotateYaw,'0.035000');r.dispose();
});

test('automatic yaw uses elapsed active seconds at low and high frame rates',()=>{
 const results=[];
 for(const fps of [1,30,60,144]){
  const {renderer:r}=art(),s=state(graph(1));
  for(let frame=0;frame<=fps*4;frame++)r.advanceView(s,1000+frame*1000/fps);
  near(r.autoRotateYaw,.14);results.push(r.camera.position.clone());r.dispose();
 }
 for(const position of results)assert.ok(position.distanceTo(results[0])<1e-8);
});

test('hovering anywhere on the input canvas never stops automatic yaw',()=>{
 const {renderer:r,canvas,emit}=art(),s=state(graph(2));r.render(s,1000);r.render(s,1100);
 const yaw=r.autoRotateYaw;emit('pointerenter',{clientX:1,clientY:1});
 r.render(s,1200);r.render(s,1300);near(r.autoRotateYaw,yaw+.007);
 assert.equal(canvas.dataset.autoRotate,'true');assert.equal(canvas.dataset.autoRotateReason,'rotating');assert.equal(canvas.dataset.autoRotateHovered,'true');
 emit('pointerleave');r.render(s,1400);near(r.autoRotateYaw,yaw+.0105);
 emit('pointermove',{clientX:20,clientY:20});r.render(s,1500);near(r.autoRotateYaw,yaw+.014);
 r.dispose();
});

test('captured touch interaction stays in control outside the canvas and cancel or lost capture releases it',()=>{
 const {renderer:r,canvas,emit}=art(),s=state(graph(2));r.render(s,1000);r.render(s,1100);
 // Isolate host pointer handlers: a capture owner need not be OrbitControls.
 r.controls.enabled=false;
 emit('pointerdown',{pointerType:'touch'});emit('pointerleave',{pointerType:'touch'});r.render(s,1200);
 const yaw=r.autoRotateYaw;assert.equal(canvas.dataset.autoRotateInteracting,'true');assert.equal(canvas.dataset.autoRotateReason,'interaction');
 // User orbit input changes the camera while automatic rotation is suspended.
 r.camera.position.applyAxisAngle(new THREE.Vector3(0,1,0),.2);r.controls.update();const manual=r.camera.position.clone();
 r.render(s,3000);near(r.autoRotateYaw,yaw);assert.ok(r.camera.position.distanceTo(manual)<1e-8);
 emit('lostpointercapture',{pointerType:'touch'});r.render(s,5000);near(r.autoRotateYaw,yaw);r.render(s,5100);near(r.autoRotateYaw,yaw+.0035);
 r.controls.enabled=false;emit('pointerdown',{pointerId:2,pointerType:'touch'});r.render(s,5200);emit('pointercancel',{pointerId:2,pointerType:'touch'});
 r.render(s,7000);r.render(s,7100);near(r.autoRotateYaw,yaw+.007);r.dispose();
});

test('pause, hidden, reduced motion, flat mode and disable stop yaw without catch-up on return',()=>{
 const {renderer:r,canvas,emitDocument}=art(),s=state(graph(4));r.render(s,1000);r.render(s,1100);
 let time=1100;
 const stopped=(stop,resume,reason)=>{
  const yaw=r.autoRotateYaw;stop();r.render(s,time+=100);r.render(s,time+=30000);
  near(r.autoRotateYaw,yaw);assert.equal(canvas.dataset.autoRotateReason,reason);
  resume();r.render(s,time+=30000);near(r.autoRotateYaw,yaw);r.render(s,time+=100);near(r.autoRotateYaw,yaw+.0035);
 };
 try{
  stopped(()=>s.paused=true,()=>s.paused=false,'paused');
  stopped(()=>{globalThis.document.hidden=true;emitDocument('visibilitychange');},()=>{globalThis.document.hidden=false;emitDocument('visibilitychange');},'hidden');
  stopped(()=>globalThis.matchMedia=()=>({matches:true}),()=>globalThis.matchMedia=()=>({matches:false}),'reduced-motion');
  stopped(()=>r.setEnabled(false),()=>r.setEnabled(true),'disabled');
  stopped(()=>s.art=false,()=>s.art=true,'disabled');
  const yaw=r.autoRotateYaw;s.graphMode='flat';for(let i=0;i<40;i++)r.render(s,time+=100);
  near(r.autoRotateYaw,yaw);assert.equal(r.flatMix,1);assert.equal(canvas.dataset.autoRotateReason,'flat');
  s.graphMode='nebula';while(r.flatMix!==0)r.render(s,time+=100);near(r.autoRotateYaw,yaw);
  r.render(s,time+=100);near(r.autoRotateYaw,yaw+.0035);
 }finally{globalThis.document.hidden=false;globalThis.matchMedia=()=>({matches:false});r.dispose();}
});

test('separate artwork and input surfaces resume after blur without making hover a pause',()=>{
 const input=surface(),output=surface(),r=new Renderer(output.canvas,input.canvas),s=state(graph(1));r.resize(1000,700);
 r.render(s,1000);r.render(s,1100);input.emit('pointerenter');r.render(s,1200);const yaw=r.autoRotateYaw;
 assert.equal(output.canvas.dataset.autoRotateReason,'rotating');assert.equal(input.canvas.dataset.autoRotateReason,undefined);
 input.emitWindow('blur');r.render(s,60000);near(r.autoRotateYaw,yaw);r.render(s,60100);near(r.autoRotateYaw,yaw+.0035);
 // Restoring focus under a stationary mouse does not pause the nebula.
 input.canvas.matches=selector=>selector===':hover';input.emitWindow('focus');r.render(s,60200);
 near(r.autoRotateYaw,yaw+.0035);assert.equal(output.canvas.dataset.autoRotateReason,'rotating');
 input.emit('pointerleave');r.render(s,60300);r.render(s,60400);near(r.autoRotateYaw,yaw+.0105);
 assert.ok(input.handlers.get('pointerdown').size>=2,'rotation must retain OrbitControls input listeners');
 r.dispose();assert.equal(input.handlers.size,0);assert.equal(input.documentHandlers.size,0);assert.equal(input.windowHandlers.size,0);
});

test('actual mouse and pen drags rotate while only Shift-left-drag pans',()=>{
 for(const [pointerType,modifiers,pan] of [['mouse',{},false],['pen',{},false],
  ['mouse',{shiftKey:true},true],['mouse',{ctrlKey:true},false],['mouse',{metaKey:true},false],
  ['mouse',{shiftKey:true,ctrlKey:true},true]]){
  const {renderer:r,emit}=art(),s=state(graph(12)),before=JSON.stringify(s.nodes);
  r.render(s,1000);const target=r.controls.target.clone(),offset=r.camera.position.clone().sub(target);
  emit('pointerdown',{pointerType,...modifiers});
  emit('pointermove',{pointerType,clientX:580,clientY:390,...modifiers});
  emit('pointerup',{pointerType,clientX:580,clientY:390,...modifiers});
  const nextOffset=r.camera.position.clone().sub(r.controls.target);
  if(pan){assert.ok(r.controls.target.distanceTo(target)>20);vectorNear(offset,nextOffset);}
  else{vectorNear(r.controls.target,target);assert.ok(offset.distanceTo(nextOffset)>20);}
  assert.equal(JSON.stringify(s.nodes),before);r.dispose();
 }
});

test('lost capture, cancellation, blur and hidden windows cannot leave a sticky Shift-pan gesture',()=>{
 for(const interrupt of ['lostpointercapture','pointercancel','blur','hidden']){
  const {renderer:r,emit,emitWindow,emitDocument}=art(),s=state(graph(12));r.render(s,1000);
  emit('pointerdown',{shiftKey:true});emit('pointermove',{clientX:560,clientY:375,shiftKey:true});
  if(interrupt==='blur')emitWindow('blur');
  else if(interrupt==='hidden'){globalThis.document.hidden=true;emitDocument('visibilitychange');globalThis.document.hidden=false;emitDocument('visibilitychange');}
  else emit(interrupt);
  const target=r.controls.target.clone(),offset=r.camera.position.clone().sub(target);
  // Same mouse pointer ID, no intervening pointerup and no Shift key.
  emit('pointerdown',{clientX:560,clientY:375});emit('pointermove',{clientX:620,clientY:400});
  vectorNear(r.controls.target,target);assert.ok(r.camera.position.clone().sub(target).distanceTo(offset)>20,interrupt);
  emit('pointerup');assert.equal(r.activePointers.size,0);r.dispose();
 }
});

test('one touch rotates while the host retains sole ownership of two-finger pinch and pan',()=>{
 const {renderer:r,emit}=art(),s=state(graph(8));r.render(s,1000);
 const target=r.controls.target.clone(),start=r.camera.position.clone();
 emit('pointerdown',{pointerType:'touch',pageX:400,pageY:300});
 emit('pointermove',{pointerType:'touch',pageX:450,pageY:325});
 assert.ok(r.camera.position.distanceTo(start)>20);vectorNear(r.controls.target,target);
 emit('pointerdown',{pointerId:2,pointerType:'touch',pageX:600,pageY:300});
 const camera=r.camera.position.clone();
 emit('pointermove',{pointerId:2,pointerType:'touch',pageX:660,pageY:350});
 vectorNear(r.camera.position,camera);vectorNear(r.controls.target,target);
 emit('pointercancel',{pointerId:2,pointerType:'touch'});emit('pointercancel',{pointerType:'touch'});r.dispose();
});

test('only a selected node or explicit pause keeps yaw stopped after input ends',()=>{
 const {renderer:r,canvas,emit}=art(),s=state(graph(4));r.render(s,1000);r.render(s,1100);
 // Hover and a completed empty-space click never latch an automatic pause.
 emit('pointerenter');emit('pointerdown');emit('pointerup');r.render(s,1200);
 const afterClick=r.autoRotateYaw;r.render(s,1300);near(r.autoRotateYaw,afterClick+.0035);
 emit('pointerdown');emit('pointermove',{clientX:560,clientY:390});r.render(s,1400);
 const duringDrag=r.autoRotateYaw;r.render(s,1500);near(r.autoRotateYaw,duringDrag);assert.equal(canvas.dataset.autoRotateReason,'interaction');
 emit('pointerup');r.render(s,1600);r.render(s,1700);near(r.autoRotateYaw,duringDrag+.0035);
 s.selected='n1';r.render(s,1800);const selectedYaw=r.autoRotateYaw,selectedCamera=r.camera.position.clone();
 r.render(s,2400);near(r.autoRotateYaw,selectedYaw);vectorNear(r.camera.position,selectedCamera);assert.equal(canvas.dataset.autoRotateReason,'selected');
 s.selected=null;r.render(s,2500);r.render(s,2600);near(r.autoRotateYaw,selectedYaw+.0035);
 s.paused=true;r.render(s,2700);r.render(s,3000);near(r.autoRotateYaw,selectedYaw+.0035);assert.equal(canvas.dataset.autoRotateReason,'paused');
 r.dispose();
});
