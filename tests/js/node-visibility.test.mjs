import assert from 'node:assert/strict';
import test from 'node:test';
import * as THREE from '../../nkb/viz/art/node_modules/three/build/three.module.js';
globalThis.window={};
const {NeuralArt,nodeVisualMetrics,nodeScreenDiameter,BREATH_AMPLITUDE}=await import('../../nkb/viz/art/neural-art.js');
const sample={id:'visible-memory',kind:'episode',state:'active',salience:.55,degree:0,x:0,y:0};
const state=(nodes,k=1)=>({W:1280,H:720,cam:{x:640,y:360,k},nodes,visible:nodes,visibleSet:new Set(nodes.map(n=>n.id)),adj:new Map(),active:new Map(),lit:new Map()});
function bareArt(nodes=[]){
 const art=Object.create(NeuralArt.prototype);
 Object.assign(art,{W:1280,H:720,nodes:[],edges:[],root:new THREE.Group(),scratch:new THREE.Vector3(),lastPosition:[],curves:[],linesByKey:new Map(),shared:{uDpr:{value:2}},maxPointDevice:512,depthScale:250});
 art.camera=new THREE.OrthographicCamera(-640,640,360,-360,.1,5000);art.camera.position.set(-180,100,1200);art.camera.lookAt(0,0,0);art.camera.updateProjectionMatrix();art.camera.updateMatrixWorld(true);
 for(const name of ['pointMaterial','glowMaterial','lineMaterial','cloudMaterial','pulseMaterial'])art[name]=new THREE.ShaderMaterial();
 if(nodes.length)art.setGraph(nodes,[]);
 return art;
}
function near(a,b,tolerance=1e-6){assert.ok(Math.abs(a-b)<=tolerance,`${a} differs from ${b}`);}

test('sparse cells have a readable solid core while dense overviews stay light',()=>{
 const s=state([sample]);
 const ranges=[[1,17,21],[12,13,18],[72,8,11],[225,4,7],[1000,2,3.5]];
 let previous=Infinity;
 for(const [count,low,high]of ranges){const m=nodeVisualMetrics(sample,s,count);assert.ok(m.readableCoreDiameter>=low&&m.readableCoreDiameter<=high,`${count}: ${m.readableCoreDiameter}`);assert.ok(m.readableCoreDiameter<previous);previous=m.readableCoreDiameter;}
});

test('real zoom visibly enlarges cells and selection is emphasized without giant bubbles',()=>{
 const far=state([sample],.4),nearState=state([sample],4);
 assert.ok(nodeScreenDiameter(sample,nearState,72)>nodeScreenDiameter(sample,far,72)*2);
 const normal=nodeVisualMetrics(sample,state([sample]),72);
 const selected=nodeVisualMetrics(sample,{...state([sample]),selected:sample.id},72);
 const hover=nodeVisualMetrics(sample,{...state([sample]),hover:sample.id},72);
 assert.ok(selected.diameter>hover.diameter&&hover.diameter>normal.diameter);
 assert.ok(nodeScreenDiameter(sample,{...nearState,cam:{...nearState.cam,k:1e8}},1)<=48);
 for(const k of [NaN,Infinity,-1,0]){const m=nodeVisualMetrics(sample,state([sample],k),72);assert.ok(Number.isFinite(m.diameter)&&m.diameter>0);}
});

test('GPU size, picking envelope and device point limits use the same CSS diameter',()=>{
 const nodes=[sample],s={...state(nodes,10),selected:sample.id};
 const art=bareArt(nodes);art.maxPointDevice=64;art.updateStyle(s);
 const actual=art.nodeGeometry.attributes.aSize.array[0];
 near(art.radiusOnScreen(sample,s),actual*(1+BREATH_AMPLITUDE)/2,2e-6);
 assert.ok(actual*art.shared.uDpr.value*(1+BREATH_AMPLITUDE)<=64.00001);
 const cpu=nodeVisualMetrics(sample,s,1,undefined,art.pointSizeLimit());near(cpu.diameter,actual,2e-6);
 const hidden={...s,visible:[],visibleSet:new Set()};art.updateStyle(hidden);assert.equal(art.nodeGeometry.attributes.aAlpha.array[0],0);assert.equal(art.radiusOnScreen(sample,hidden),0);
});

test('empty graphs generate no neurons, nebula or invented edge',()=>{
 const art=bareArt();art.setGraph([],[]);
 assert.equal(art.nodeGeometry.attributes.position.count,0);assert.equal(art.cloudGeometry.attributes.position.count,0);assert.equal(art.lineGeometry.attributes.position.count,0);
 assert.equal(art.projectedBounds([],state([])),null);
});

test('nearby single-cell dust remains local even after extreme close zoom',()=>{
 const art=bareArt([sample]);
 for(const k of [.08,1,18]){const s=state([sample],k);art.syncTransform(s);art.updateStyle(s);art.updateNebula(s);
  const positions=art.cloudGeometry.attributes.position.array,drift=art.cloudGeometry.attributes.aDrift.array,center=art.projectNode(sample);const limit=nodeVisualMetrics(sample,s,1).nebulaRadius;
  for(let i=0;i<positions.length;i+=3){const projected=art.projectLocal(new THREE.Vector3(...positions.slice(i,i+3)));assert.ok(Math.hypot(projected.x-center.x,projected.y-center.y)<=limit+.001);for(let axis=0;axis<3;axis++)assert.ok(drift[i+axis]*k<=.851);}
 }
});

test('projected bounds and centering respect real orthographic orbit and depth',()=>{
 const nodes=[{...sample,id:'left',x:-140,y:70},{...sample,id:'right',x:190,y:-80}];
 const art=bareArt(nodes),s=state(nodes,1.7);
 for(const position of [[-180,100,1200],[700,360,850],[-550,-200,1100]]){
  art.camera.position.set(...position);art.camera.lookAt(0,0,0);art.camera.updateMatrixWorld(true);art.camera.zoom=1.3;art.camera.updateProjectionMatrix();
  const box=art.projectedBounds(nodes,s);assert.equal(box.count,2);
  for(const n of nodes){const p=art.projectNode(n),r=art.radiusOnScreen(n,s);assert.ok(p.x-r>=box.minX-1e-8&&p.x+r<=box.maxX+1e-8);assert.ok(p.y-r>=box.minY-1e-8&&p.y+r<=box.maxY+1e-8);}
  const before=art.projectNode(nodes[0]),delta=art.screenDeltaToTranslation(85,-42);assert.ok(delta);
  const translated={...s,cam:{...s.cam,x:s.cam.x+delta.x,y:s.cam.y+delta.y}};art.syncTransform(translated);const after=art.projectNode(nodes[0]);near(after.x-before.x,85);near(after.y-before.y,-42);
 }
 art.camera.position.set(1200,0,0);art.camera.lookAt(0,0,0);art.camera.updateMatrixWorld(true);assert.equal(art.screenDeltaToTranslation(10,10),null);
});
