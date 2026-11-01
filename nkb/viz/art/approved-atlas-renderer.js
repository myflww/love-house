/* Host adapter for the approved Canvas atlas. Three.js supplies only camera
 * mathematics and orbit input; this class never constructs a WebGL renderer.
 * Canonical memory records, IDs, edges and recall counters remain read-only.
 */
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {ApprovedAtlasPainter} from './approved-atlas-painter.js';
import {approvedGravityTargets,approvedNebulaTargets,approvedCategoryKeys} from './approved-atlas-data.js';

const finite=(v,f=0)=>typeof v==='number'&&Number.isFinite(v)?v:f;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const lerp=(a,b,t)=>a+(b-a)*t;
const TAU=Math.PI*2;
const LIFE={active:1,fading:.66,dormant:.28,forgotten:.08};
const KIND_NAMES={concept:'概念',fact:'事实',episode:'经历',preference:'偏好',source:'来源',doc:'文档',question:'问题',answer:'回答',commitment:'承诺',reflection:'反思'};
function hash(value){let h=2166136261;for(const c of String(value))h=Math.imul(h^c.charCodeAt(0),16777619);return(h>>>0)/4294967296;}
function category(n){
 if(typeof n.category==='string'&&n.category.trim())return n.category.trim();
 const tags=Array.isArray(n.tags)?n.tags.filter(t=>typeof t==='string'&&t.trim()).map(t=>t.trim()).sort():[];
 return tags[0]||n.kind||'未分类';
}

/** Preserve the host's projection API while replacing its GL drawing entirely.
 * Base is used only for established camera mathematics, never construction,
 * render, shaders, meshes, buffers, or geometry allocation.
 */
export function createApprovedAtlasRenderer(Base){
 return class ApprovedAtlasRenderer{
  constructor(canvas,controlsCanvas){
   const ctx=canvas?.getContext?.('2d',{alpha:true});
   if(!ctx)throw new Error('Canvas 2D atlas context unavailable');
   this.canvas=canvas;this.ctx=ctx;this.controlsCanvas=controlsCanvas||canvas;
   this.camera=new THREE.OrthographicCamera(-1,1,1,-1,.1,5000);
   this.camera.position.set(-180,100,1200);this.camera.lookAt(0,0,0);
   this.controls=new OrbitControls(this.camera,this.controlsCanvas);
   this.controls.enableDamping=false;this.controls.enableZoom=false;this.controls.enablePan=true;
   this.controls.screenSpacePanning=true;this.controls.minPolarAngle=.15;this.controls.maxPolarAngle=Math.PI-.15;this.controls.rotateSpeed=.55;
   this.controls.addEventListener('change',()=>this.onChange?.());
   this.root=new THREE.Group();this.scratch=new THREE.Vector3();this.maxPointDevice=256;
   this.shared={uDpr:{value:1},uScale:{value:1},uTime:{value:0},uLight:{value:0}};
   this.W=0;this.H=0;this.dpr=1;this.depthScale=100;this.nodes=[];this.edges=[];this.byId=new Map();
   this.flatTargets=new Map();this.nebulaTargets=new Map();this.degrees=new Map();this.hubs=new Set();this.categories=[];
   this.flatMix=0;this.motionTime=0;this.lastWall=null;this.lastMode='nebula';this.enabled=true;this.disposed=false;
   this.orbitSnapshot=null;this.flatSnapshot=null;this.viewState=null;this.painter=new ApprovedAtlasPainter();
  }

  resize(w,h,dpr=1){
   this.W=Math.max(1,finite(w,1));this.H=Math.max(1,finite(h,1));this.dpr=clamp(finite(dpr,1),.5,3);
   this.canvas.width=Math.round(this.W*this.dpr);this.canvas.height=Math.round(this.H*this.dpr);
   this.camera.left=-this.W/2;this.camera.right=this.W/2;this.camera.top=this.H/2;this.camera.bottom=-this.H/2;this.camera.updateProjectionMatrix();
   this.shared.uDpr.value=this.dpr;
  }

  setGraph(nodes=[],edges=[]){
   if(this.graphReady&&nodes===this.nodes&&edges===this.edges)return;
   this.nodes=nodes;this.edges=edges;this.byId=new Map(nodes.map((n,i)=>[n.id,{n,i}]));
   this.depthScale=Math.min(460,Math.max(100,Math.sqrt(nodes.length)*19));
   this.flatTargets=approvedGravityTargets(nodes,edges);this.nebulaTargets=approvedNebulaTargets(nodes,edges);
   const neighbors=new Map(nodes.map(n=>[n.id,new Set()]));
   for(const e of edges){if(e.source===e.target||!neighbors.has(e.source)||!neighbors.has(e.target))continue;neighbors.get(e.source).add(e.target);neighbors.get(e.target).add(e.source);}
   this.degrees=new Map([...neighbors].map(([id,ids])=>[id,ids.size]));
   const mean=[...this.degrees.values()].reduce((a,b)=>a+b,0)/Math.max(1,nodes.length);
   this.hubs=new Set([...this.degrees].filter(([,degree])=>degree>=5&&degree>=mean*1.8).map(([id])=>id));
   this.categories=approvedCategoryKeys(nodes);
   this.painter.setGraph(nodes,edges);this.graphReady=true;
  }

  displayPosition(n){const source=this.nebulaTargets.get(n.id)||{x:finite(n.x),y:finite(n.y)},target=this.flatTargets.get(n.id)||source;return{x:lerp(source.x,target.x,this.flatMix),y:lerp(source.y,target.y,this.flatMix)};}
  nodeDepth(n){const source=this.nebulaTargets.get(n.id),z=source?source.z:(hash(String(n.id)+'z')-.5)*this.depthScale;return z*(1-this.flatMix);}
  projectNode(n){const p=this.displayPosition(n);return this.projectLocal(this.scratch.set(p.x,-p.y,this.nodeDepth(n)));}
  projectLocal(value){const p=value?.isVector3?value:new THREE.Vector3(finite(value?.x),finite(value?.y),finite(value?.z));return Base.prototype.projectLocal.call(this,p);}
  syncTransform(s){return Base.prototype.syncTransform.call(this,s);}
  projectedBounds(nodes,s,options){
   if(s.nodes)this.setGraph(s.nodes,s.edges||[]);
   this.viewState=s;
   const box=Base.prototype.projectedBounds.call(this,nodes,s,options);
   // The original planar guide includes category labels beyond its outer ring.
   // Include that existing visual envelope in auto-fit, without adding graph data.
   if(box&&this.flatMix>.05&&nodes.length>=3){
    const center=this.projectLocal({x:0,y:0,z:0});
    // The host's existing coverage/padding already reserves the remaining outer
    // guide/label space. Keep this envelope centered without applying it twice.
    const r=Math.max(90,Math.sqrt(this.nodes.length)*23)*Math.abs(s.cam.k)*.82;
    const rx=Math.max(r,center.x-box.minX,box.maxX-center.x),ry=Math.max(r,center.y-box.minY,box.maxY-center.y);
    box.minX=center.x-rx;box.maxX=center.x+rx;
    box.minY=center.y-ry;box.maxY=center.y+ry;
    box.width=box.maxX-box.minX;box.height=box.maxY-box.minY;
    box.centerX=(box.minX+box.maxX)/2;box.centerY=(box.minY+box.maxY)/2;
   }
   return box;
  }
  screenDeltaToTranslation(dx,dy){return Base.prototype.screenDeltaToTranslation.call(this,dx,dy);}
  panCamera(dx,dy){return Base.prototype.panCamera.call(this,dx,dy);}
  centerNode(n,s){return Base.prototype.centerNode.call(this,n,s);}
  captureScreenPoint(x,y,s){return Base.prototype.captureScreenPoint.call(this,x,y,s);}
  restoreScreenPoint(point,x,y,s){return Base.prototype.restoreScreenPoint.call(this,point,x,y,s);}

  nodeMetrics(n,s=this.viewState||{}){
   const visible=s.visibleSet,known=this.byId.has(n.id);
   if(!known||(visible&&!visible.has(n.id)))return{radius:0,hub:false,alpha:0};
   const count=visible?.size??s.visible?.length??this.nodes.length,hub=this.hubs.has(n.id);
   const zoom=clamp(Math.pow(Math.max(.001,finite(s.cam?.k,1)),.26),.45,1.8);
   // Original approved sizes: hub radius 4.8, leaf radius 1.7..3.0.
   // Sparse libraries retain the host's explicit readable-core floor.
   let diameter=count<=12?10:2*(hub?4.8:1.7+hash(String(n.id)+':approved-size')*1.3);
   diameter=clamp(diameter*zoom,.8,count<=12?30:hub?28:9);
   const alpha=(LIFE[n.state]??1)*(n.meta?.memory_disabled ? .18 : 1);
   return{radius:diameter/2,hub,alpha};
  }
  readableCoreDiameter(n,s){return this.nodeMetrics(n,s).radius*2;}
  radiusOnScreen(n,s){const m=this.nodeMetrics(n,s);return m.alpha>0?m.radius*1.1+1.5:0;}
  pointSizeLimit(){return this.maxPointDevice/Math.max(.1,this.shared.uDpr.value);}

  advanceView(s,now){
   const mode=s.graphMode==='flat'?'flat':'nebula',goal=mode==='flat'?1:0,previous=this.flatMix;
   const dt=this.lastWall==null?0:clamp((finite(now)-this.lastWall)/1000,0,.1);this.lastWall=finite(now);
   if(!s.paused&&!globalThis.document?.hidden)this.motionTime+=dt;
   const reduced=!!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
   this.flatMix=reduced?goal:lerp(this.flatMix,goal,1-Math.exp(-dt*5.8));
   if(Math.abs(this.flatMix-goal)<.0002)this.flatMix=goal;
   if(mode==='flat'&&this.lastMode!=='flat'&&!this.orbitSnapshot)this.orbitSnapshot={position:this.camera.position.clone(),target:this.controls.target.clone()};
   if(mode==='nebula'&&this.lastMode==='flat'&&previous===1)this.flatSnapshot={position:this.camera.position.clone(),target:this.controls.target.clone()};
   if(this.orbitSnapshot&&(this.flatMix!==previous||mode!==this.lastMode)){
    const orbit=this.orbitSnapshot,flat=this.flatSnapshot||{position:new THREE.Vector3(0,0,1200),target:new THREE.Vector3()};
    this.camera.position.copy(orbit.position).lerp(flat.position,this.flatMix);this.controls.target.copy(orbit.target).lerp(flat.target,this.flatMix);
    this.camera.lookAt(this.controls.target);this.camera.updateMatrixWorld(true);
   }
   if(mode==='nebula'&&this.flatMix===0&&this.orbitSnapshot){
    this.camera.position.copy(this.orbitSnapshot.position);this.controls.target.copy(this.orbitSnapshot.target);this.camera.lookAt(this.controls.target);this.camera.updateMatrixWorld(true);
    this.orbitSnapshot=null;this.flatSnapshot=null;
   }
   this.lastMode=mode;this.controls.enabled=this.enabled&&s.art!==false&&mode==='nebula'&&this.flatMix===0;
  }
  isTransitioning(){return Math.abs(this.flatMix-(this.lastMode==='flat'?1:0))>.0002;}
  resetView(){
   if(this.lastMode==='flat'){
    this.controls.target.set(0,0,0);this.camera.position.set(0,0,1200);this.camera.zoom=1;this.camera.lookAt(this.controls.target);this.camera.updateProjectionMatrix();this.controls.update();this.camera.updateMatrixWorld(true);
    this.flatSnapshot={position:this.camera.position.clone(),target:this.controls.target.clone()};
   }else{Base.prototype.resetView.call(this);this.orbitSnapshot=null;this.flatSnapshot=null;}
  }
  setEnabled(enabled){this.enabled=!!enabled;this.controls.enabled=this.enabled&&this.lastMode==='nebula'&&this.flatMix===0;}

  painterView(s){
   return{W:this.W,H:this.H,light:globalThis.document?.documentElement?.dataset.theme==='light',time:this.motionTime,zoom:s.cam.k,flatMix:this.flatMix,paused:!!s.paused,
    selected:s.selected,hover:s.hover,nodes:this.nodes,edges:this.edges,visibleSet:s.visibleSet||new Set(this.nodes.map(n=>n.id)),
    active:s.active||new Map(),lit:s.lit||new Map(),result:s.result,
    graphScale:Math.max(90,Math.sqrt(this.nodes.length)*23),
    categories:this.categories.map(key=>({key,label:KIND_NAMES[key]||key,count:this.nodes.filter(n=>category(n)===key&&(!s.visibleSet||s.visibleSet.has(n.id))).length})),
    projectNode:n=>this.projectNode(n),projectLocal:p=>this.projectLocal(p),displayPosition:n=>this.displayPosition(n),nodeDepth:n=>this.nodeDepth(n),nodeMetrics:n=>this.nodeMetrics(n,s)};
  }

  render(s,now){
   if(this.disposed)return;
   this.setGraph(s.nodes,s.edges);if(!this.W||!this.H)return;this.viewState=s;
   this.advanceView(s,now);this.controls.update();this.syncTransform(s);
   const light=globalThis.document?.documentElement?.dataset.theme==='light';
   this.shared.uLight.value=light?1:0;this.shared.uScale.value=s.cam.k;this.shared.uTime.value=this.motionTime;
   this.ctx.setTransform(this.dpr,0,0,this.dpr,0,0);this.ctx.clearRect(0,0,this.W,this.H);
   const visibleSet=s.visibleSet||new Set(this.nodes.map(n=>n.id));
   const view=this.painterView(s);
   const painted=this.painter.paint(this.ctx,view);
   this.visibleFiberEdges=this.edges.filter(e=>this.byId.has(e.source)&&this.byId.has(e.target)&&visibleSet.has(e.source)&&visibleSet.has(e.target)).length;
   const diagnostic=this.canvas.dataset;
   if(diagnostic){diagnostic.fiberEdges=String(this.edges.length);diagnostic.visibleFiberEdges=String(this.visibleFiberEdges);diagnostic.graphMode=this.lastMode;diagnostic.flatMix=this.flatMix.toFixed(4);diagnostic.motionTime=this.motionTime.toFixed(3);diagnostic.particleCount=String(painted?.particleCount??this.painter.particleCount??0);diagnostic.painter='approved-canvas';}
  }

  drawPlaneGuide(ctx,s){
   if(this.flatMix<.05||this.nodes.length<3||(s.visibleSet&&s.visibleSet.size<3))return;
   this.painter.drawGuide?.(ctx,this.painterView(s));
  }

  dispose(){
   if(this.disposed)return;this.disposed=true;this.painter.dispose();this.controls.dispose();this.root.clear();
   this.nodes=[];this.edges=[];this.byId.clear();this.flatTargets.clear();this.nebulaTargets.clear();this.degrees.clear();this.hubs.clear();this.categories=[];this.viewState=null;
  }
 };
}
