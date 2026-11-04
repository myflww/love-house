import assert from 'node:assert/strict';
import test from 'node:test';
import {performance} from 'node:perf_hooks';
import * as THREE from '../../nkb/viz/art/node_modules/three/build/three.module.js';
globalThis.window={};
const {NeuralArt}=await import('../../nkb/viz/art/neural-art.js');
const {enhanceNeuralArt}=await import('../../nkb/viz/art/neural-fibers.js');
const Fibers=enhanceNeuralArt(NeuralArt);
function sampleGraph(count){
 const nodes=Array.from({length:count},(_,i)=>({id:'n'+i,label:'Memory '+i,kind:'episode',tags:['group'+i%6],state:'active',recalls:i%130,effective_salience:.6,x:Math.cos(i*2.399)*Math.sqrt(i)*22,y:Math.sin(i*2.399)*Math.sqrt(i)*22}));
 const edges=[];for(let i=1;i<count;i++){edges.push({source:'n'+(i-1),target:'n'+i,effective_w:(i%10)/10});if(i>3)edges.push({source:'n'+(i-3),target:'n'+i,effective_w:.8});}
 return{nodes,edges};
}
function makeArt(){
 const art=Object.create(Fibers.prototype);
 Object.assign(art,{W:1000,H:700,nodes:[],edges:[],root:new THREE.Group(),scratch:new THREE.Vector3(),lastPosition:[],curves:[],linesByKey:new Map(),shared:{uDpr:{value:1},uLight:{value:0},uTime:{value:0},uScale:{value:1}},maxPointDevice:256,depthScale:250,flatMix:0,motionTime:0,lastWall:null});
 art.camera=new THREE.OrthographicCamera(-500,500,350,-350,.1,5000);art.camera.position.set(-180,100,1200);art.camera.lookAt(0,0,0);art.camera.updateProjectionMatrix();art.camera.updateMatrixWorld(true);
 art.controls={enabled:true,target:new THREE.Vector3(),update(){},dispose(){}};
 art.renderer={renders:0,render(){this.renders++;},dispose(){},setPixelRatio(){},setSize(){}};
 art.canvas={dataset:{}};
 for(const name of ['pointMaterial','glowMaterial','lineMaterial','cloudMaterial','pulseMaterial'])art[name]=new THREE.ShaderMaterial({uniforms:name==='pulseMaterial'?{uColor1:{value:new THREE.Color()},uColor2:{value:new THREE.Color()}}:{}});
 art.particleTexture=new THREE.Texture();return art;
}
function state(graph,extra={}){return{...graph,art:true,W:1000,H:700,cam:{x:500,y:350,k:1},visible:graph.nodes,visibleSet:new Set(graph.nodes.map(n=>n.id)),adj:new Map(graph.nodes.map(n=>[n.id,graph.edges.filter(e=>e.source===n.id||e.target===n.id).map(e=>({id:e.source===n.id?e.target:e.source}))])),active:new Map(),lit:new Map(),...extra};}
function near(a,b,tolerance=1e-4){assert.ok(Math.abs(a-b)<=tolerance,`${a} != ${b}`);}

test('0/1/2 cells retain exactly the real edges and empty graphs invent no geometry',()=>{
 for(const count of [0,1,2]){const graph=sampleGraph(count),art=makeArt(),s=state(graph);art.setGraph(graph.nodes,graph.edges);art.updateStyle(s);art.updatePositions();
  assert.equal(art.nodes.length,count);assert.equal(art.visibleFiberEdges,graph.edges.length);
  assert.equal(art.lineGeometry.attributes.position.count,graph.edges.length*art.segmentCount*art.strands*6);
  if(!count){assert.equal(art.cloudGeometry.attributes.position.count,0);assert.equal(art.projectedBounds([],s),null);}art.dispose();
 }
});

test('every fibre endpoint equals its displayed neuron throughout layout morphs',()=>{
 const graph=sampleGraph(12),art=makeArt(),s=state(graph);art.setGraph(graph.nodes,graph.edges);
 for(const mix of [0,.25,.75,1]){art.flatMix=mix;art.motionTime=2;art.updateStyle(s);art.updatePositions();
  for(const e of graph.edges)for(const [t,id]of [[0,e.source],[1,e.target]]){const n=art.byId.get(id).n,p=art.displayPosition(n),c=art.curve(e,t);near(c[0],p.x);near(c[1],-p.y);near(c[2],art.nodeDepth(n));}
  if(mix===1)for(const z of art.lineGeometry.attributes.position.array.filter((_,i)=>i%3===2))near(z,0);
 }
});

test('render uses one mode projection, theme, real edges and frozen animation time',()=>{
 const graph=sampleGraph(30),art=makeArt(),s=state(graph),before=JSON.stringify(graph);
 globalThis.document={hidden:false,documentElement:{dataset:{theme:'dark'}}};
 art.render(s,1000);art.render(s,1100);const moving=art.motionTime;assert.ok(moving>0);assert.equal(art.shared.uLight.value,0);
 const initial=art.lineGeometry.attributes.position.array.slice();art.render(s,1200);assert.notDeepEqual(art.lineGeometry.attributes.position.array,initial);
 s.paused=true;art.render(s,1300);const frozen=art.motionTime,still=art.lineGeometry.attributes.position.array.slice();art.render(s,4000);assert.equal(art.motionTime,frozen);assert.deepEqual(art.lineGeometry.attributes.position.array,still);
 globalThis.document.documentElement.dataset.theme='light';s.graphMode='flat';
 for(let t=4100;t<7000;t+=100)art.render(s,t);
 assert.equal(art.shared.uLight.value,1);assert.equal(art.lastMode,'flat');assert.equal(art.flatMix,1);assert.equal(art.visibleFiberEdges,graph.edges.length);assert.equal(art.controls.enabled,false);
 assert.equal(JSON.stringify(graph),before);assert.equal(art.canvas.dataset.fiberEdges,String(graph.edges.length));
 delete globalThis.document;art.dispose();
});

test('filtering hides only edges with hidden endpoints; association widths are real attributes',()=>{
 const graph=sampleGraph(5),art=makeArt(),s=state(graph);art.setGraph(graph.nodes,graph.edges);art.updateStyle(s);
 const full=art.visibleFiberEdges;s.visibleSet.delete('n2');art.updateStyle(s);
 assert.equal(art.visibleFiberEdges,graph.edges.filter(e=>e.source!=='n2'&&e.target!=='n2').length);assert.ok(art.visibleFiberEdges<full);
 const widths=art.lineGeometry.attributes.aWidth.array;assert.ok(Math.max(...widths)>Math.min(...widths));
});

test('flat camera positioning survives subsequent renders and rapid mode reversals preserve orbit',()=>{
 const graph=sampleGraph(8),art=makeArt(),s=state(graph,{paused:true});art.setGraph(graph.nodes,graph.edges);
 const original=art.camera.position.clone();s.graphMode='flat';
 for(let now=0;now<3000;now+=100)art.advanceView(s,now);
 assert.equal(art.flatMix,1);art.panCamera(60,25);const panned=art.camera.position.clone();art.advanceView(s,3100);assert.deepEqual(art.camera.position,panned);
 art.centerNode(graph.nodes[3],s);const located=art.camera.position.clone();art.advanceView(s,3200);assert.deepEqual(art.camera.position,located);
 art.resetView();art.advanceView(s,3250);assert.deepEqual(art.camera.position,new THREE.Vector3(0,0,1200));
 s.graphMode='nebula';art.advanceView(s,3300);s.graphMode='flat';art.advanceView(s,3400);assert.deepEqual(art.orbitSnapshot.position,original);
 s.graphMode='nebula';for(let now=3500;now<7000;now+=100)art.advanceView(s,now);assert.equal(art.flatMix,0);assert.deepEqual(art.camera.position,original);art.dispose();
});

test('fit can prepare a newly loaded flat library before its first render',()=>{
 const a=sampleGraph(8),b=sampleGraph(3),art=makeArt();art.setGraph(a.nodes,a.edges);art.flatMix=1;
 for(const n of b.nodes){n.x=1e7;n.y=1e7;}
 const s=state(b,{graphMode:'flat'});const box=art.projectedBounds(b.nodes,s);assert.ok(box&&box.count===3);assert.equal(art.nodes,b.nodes);
 for(const n of b.nodes)assert.ok(Math.abs(art.displayPosition(n).x)<300);art.dispose();
});

test('large graph geometry is budgeted without dropping edges, and cleans all geometry',()=>{
 const graph=sampleGraph(2000),art=makeArt(),s=state(graph);const original=JSON.stringify(graph);
 const start=performance.now();art.setGraph(graph.nodes,graph.edges);art.updateStyle(s);art.updatePositions();const buildMs=performance.now()-start;
 const frames=[];for(let i=0;i<6;i++){const start=performance.now();art.motionTime=i*.033;art.updateStyle(s);art.updatePositions();art.updateNebula(s);frames.push(performance.now()-start);}
 assert.equal(art.visibleFiberEdges,graph.edges.length);assert.ok(graph.edges.length*(art.segmentCount+1)*art.strands<65000);assert.equal(JSON.stringify(graph),original);
 for(const name of ['position','aTangent','aWidth','aAlpha'])assert.ok(art.lineGeometry.attributes[name].array.every(Number.isFinite));
 let disposed=0;art.lineGeometry.addEventListener('dispose',()=>disposed++);art.dispose();assert.equal(disposed,1);assert.equal(art.root.children.length,0);
 console.log(JSON.stringify({nodes:graph.nodes.length,edges:graph.edges.length,segments:art.segmentCount,buildMs:+buildMs.toFixed(1),cpuFrameMeanMs:+(frames.reduce((a,b)=>a+b,0)/frames.length).toFixed(1),cpuFrameMaxMs:+Math.max(...frames).toFixed(1),note:'CPU geometry only; browser/native FPS requires separate validation'}));
});
