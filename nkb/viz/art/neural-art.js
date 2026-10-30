/* Neural KB art renderer. Uses only exported graph nodes, real edges and actual recall trails. */
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {createWaveSpline,threadVertex,threadFragment,brainSurface} from './digital-brain-adapted.js';
import {nodeCountPolicy,viewportPolicy} from './viewport-policy.js';
const TAU=Math.PI*2;
const KIND=Object.fromEntries(['concept','fact','episode','preference','source','doc','question','answer','commitment','reflection'].map(k=>[k,[.92,.92,.92]]));
function hash(s){let h=2166136261;for(const c of String(s)){h^=c.charCodeAt(0);h=Math.imul(h,16777619);}return(h>>>0)/4294967296;}
function clamp(v,a,b){return Math.max(a,Math.min(b,v));}
// aSize is the FINAL CSS-pixel diameter. The old shader almost ignored camera
// scale and capped the entire Gaussian at 10px (its bright core was only ~3px).
// Keep one CPU size calculation for rendering, picking and label clearance.
const POINT_CORE_RADIUS=.4;
const BREATH_AMPLITUDE=.05;
function finite(value,fallback){const v=Number(value);return Number.isFinite(v)?v:fallback;}
function visibleCount(s,fallback=0){return Math.max(0,Math.floor(finite(s.visibleSet?.size??s.visible?.length,fallback)));}
function nodeVisualMetrics(n,s={},count=visibleCount(s,1),policy,pointLimit=Infinity){
 if(!n||count<=0)return{diameter:0,radius:0,readableCoreDiameter:0,nebulaRadius:0};
 const width=Math.max(1,finite(s.W,1280)),height=Math.max(1,finite(s.H,720));
 policy=policy||nodeCountPolicy(count,{width,height});
 const target=finite(policy.targetReadableCoreDiameter,finite(policy.targetNodeDiameter,9));
 const sal=clamp(finite(n.effective_salience??n.salience,.5),0,1),degree=Math.max(0,finite(n.degree,0));
 const selected=n.id===s.selected,hover=n.id===s.hover;
 const importance=.88+sal*.22+Math.min(.13,Math.sqrt(degree)*.025)+((n.is_anchor || n.anchor) ? .08 : 0);
 const zoom=clamp(Math.pow(Math.max(.001,finite(s.cam?.k,1)),.42),.42,2.4);
 const emphasis=selected?1.22:hover?1.10:1;
 const maximum=Math.max(.1,Math.min((count<=120?48:count<=600?40:32)*(selected?1.18:1),pointLimit));
 const minimum=Math.min(maximum,count<=12?22:count<=120?12:count<=600?7:4.5);
 const diameter=clamp(target/POINT_CORE_RADIUS*importance*zoom*emphasis,minimum,maximum);
 return{diameter,radius:diameter*(1+BREATH_AMPLITUDE)/2,
        readableCoreDiameter:diameter*POINT_CORE_RADIUS,
        nebulaRadius:clamp(diameter*.67,8,32)};
}
function nodeScreenDiameter(n,s,count,policy,pointLimit){return nodeVisualMetrics(n,s,count,policy,pointLimit).diameter;}
function nodeDepthScale(count){return Math.min(460,Math.max(100,Math.sqrt(Math.max(0,count))*19));}
const pointVertex=`attribute float aSize;attribute float aAlpha;attribute float aPhase;attribute vec3 aColor;varying float vAlpha;varying float vPhase;uniform float uScale;uniform float uDpr;uniform float uTime;uniform float uGlow;uniform float uPointLimit;void main(){vAlpha=aAlpha;vPhase=aPhase;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);float breathe=1.+sin(uTime*.55+aPhase)*${BREATH_AMPLITUDE};gl_PointSize=min(max(aSize,0.)*uDpr*uGlow*breathe,uPointLimit);}`;
const pointFragment=`precision highp float;varying float vAlpha;varying float vPhase;uniform float uTime;uniform float uLight;void main(){vec2 uv=gl_PointCoord*2.-1.;float r=length(uv);if(r>1.)discard;float nucleus=1.-smoothstep(.30,.50,r);float angle=atan(uv.y,uv.x);float membrane=.55+.018*sin(angle*5.+vPhase);float rim=(1.-smoothstep(.012,.045,abs(r-membrane)))*.12;float aura=exp(-r*r*4.5)*.09;float alpha=min(.98,nucleus*.91+rim+aura)*vAlpha;vec3 color=mix(vec3(.97),vec3(.055),uLight);gl_FragColor=vec4(color,alpha);}`;
const glowFragment=`precision highp float;varying float vAlpha;varying float vPhase;uniform float uTime;uniform float uLight;void main(){float d=length(gl_PointCoord*2.-1.);if(d>1.)discard;float haze=exp(-d*d*10.)*.055*sqrt(max(vAlpha,0.));gl_FragColor=vec4(vec3(.92),haze*(1.-uLight));}`;
const lineVertex=`attribute vec3 aColor;attribute float aAlpha;varying float vAlpha;varying float vZ;void main(){vAlpha=aAlpha;vZ=position.z;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`;
const lineFragment=`precision highp float;varying float vAlpha;varying float vZ;uniform float uTime;uniform float uLight;void main(){float shimmer=.90+.10*sin(vZ*.05+uTime*.25);vec3 col=mix(vec3(.83),vec3(.12),uLight);gl_FragColor=vec4(col,vAlpha*shimmer);}`;
const cloudVertex=`attribute float aSize;attribute float aAlpha;attribute float aPhase;attribute vec3 aDrift;varying float vAlpha;uniform float uTime;uniform float uDpr;uniform float uScale;void main(){float t=uTime*.11;vec3 p=position+vec3(sin(t+aPhase),cos(t*.73+aPhase*1.7),sin(t*.57+aPhase*.9))*aDrift;gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.);vAlpha=aAlpha*(.68+.32*sin(uTime*.48+aPhase));gl_PointSize=clamp(aSize*pow(max(uScale,.1),.12),.7,2.4)*uDpr;}`;
const cloudFragment=`precision highp float;varying float vAlpha;uniform float uLight;void main(){float r=length(gl_PointCoord*2.-1.);if(r>1.)discard;float alpha=exp(-r*r*5.)*vAlpha;gl_FragColor=vec4(mix(vec3(.93),vec3(.08),uLight),alpha);}`;
const pulseVertex=`attribute float aSize; attribute float aAlpha; varying float vAlpha; uniform float uDpr; void main(){vAlpha=aAlpha;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);gl_PointSize=aSize*uDpr;}`;
const pulseFragment=`precision highp float;varying float vAlpha;uniform float uLight;void main(){float r=length(gl_PointCoord*2.-1.);if(r>1.)discard;float a=exp(-r*r*9.);vec3 c=mix(vec3(.94,.92,1.),vec3(.32,.27,.42),uLight);gl_FragColor=vec4(c,a*vAlpha);}`;
function shader(vertexShader,fragmentShader,uniforms,blend=THREE.NormalBlending){return new THREE.ShaderMaterial({vertexShader,fragmentShader,uniforms,transparent:true,depthWrite:false,depthTest:false,blending:blend});}
class NeuralArt{
 constructor(canvas,controlsCanvas){this.canvas=canvas;this.renderer=new THREE.WebGLRenderer({canvas,alpha:true,antialias:true,powerPreference:'low-power'});this.renderer.setClearColor(0,0);const gl=this.renderer.getContext();this.maxPointDevice=finite(gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE)?.[1],256);this.renderer.setPixelRatio(Math.min(2.5,devicePixelRatio||1));this.scene=new THREE.Scene();this.camera=new THREE.OrthographicCamera(-1,1,1,-1,.1,5000);this.camera.position.set(-180,100,1200);this.camera.lookAt(0,0,0);this.controls=new OrbitControls(this.camera,controlsCanvas||canvas);this.controls.enableDamping=false;this.controls.enableZoom=false;this.controls.enablePan=true;this.controls.screenSpacePanning=true;this.controls.minPolarAngle=.15;this.controls.maxPolarAngle=Math.PI-.15;this.controls.rotateSpeed=.55;this.controls.addEventListener('change',()=>this.onChange?.());this.depthScale=250;this.scratch=new THREE.Vector3();this.curves=[];this.root=new THREE.Group();this.scene.add(this.root);this.nodes=[];this.edges=[];this.byId=new Map();this.linesByKey=new Map();this.shared={uScale:{value:1},uDpr:{value:1},uTime:{value:0},uGlow:{value:1},uLight:{value:0},uPointLimit:{value:this.maxPointDevice}};this.pointMaterial=shader(pointVertex,pointFragment,this.shared);this.glowMaterial=shader(pointVertex,glowFragment,{...this.shared,uGlow:{value:2.6}},THREE.AdditiveBlending);this.lineMaterial=shader(lineVertex,lineFragment,this.shared);this.cloudMaterial=shader(cloudVertex,cloudFragment,this.shared);const texSize=48,texData=new Uint8Array(texSize*texSize*4);for(let y=0;y<texSize;y++)for(let x=0;x<texSize;x++){const d=Math.hypot((x+.5)/texSize-.5,(y+.5)/texSize-.5),a=Math.round(Math.exp(-d*d*44)*255),ix=(y*texSize+x)*4;texData[ix]=a;texData[ix+1]=a;texData[ix+2]=a;texData[ix+3]=255;}this.particleTexture=new THREE.DataTexture(texData,texSize,texSize,THREE.RGBAFormat);this.particleTexture.needsUpdate=true;this.pulseMaterial=shader(threadVertex,threadFragment,{...this.shared,uSize:{value:28},uColor1:{value:new THREE.Color(0xdddddd)},uColor2:{value:new THREE.Color(0xffffff)},uTexture:{value:this.particleTexture}},THREE.AdditiveBlending);this.signature='';this.lastPosition=[];this.lastStyle='';this.pausedAt=0;this.canvas.addEventListener('webglcontextlost',event=>{event.preventDefault();this.onFailure?.('图形环境已暂停，已切换为分析视图。');});}
 resize(w,h,dpr){this.W=w;this.H=h;this.renderer.setPixelRatio(Math.min(2.5,dpr));this.renderer.setSize(w,h,false);this.camera.left=-w/2;this.camera.right=w/2;this.camera.top=h/2;this.camera.bottom=-h/2;this.camera.updateProjectionMatrix();this.shared.uDpr.value=Math.min(2.5,dpr);}
 clearGraph(){for(const obj of [...this.root.children]){this.root.remove(obj);obj.geometry?.dispose();}}
 setGraph(nodes,edges){if(this.nodes===nodes&&this.edges===edges)return;this.clearGraph();this.nodes=nodes;this.edges=edges;this.byId=new Map(nodes.map((n,i)=>[n.id,{n,i}]));this.lastPosition=[];this.curves=[];this.linesByKey.clear();this.depthScale=nodeDepthScale(nodes.length);const N=nodes.length,positions=new Float32Array(N*3),sizes=new Float32Array(N),alpha=new Float32Array(N),phases=new Float32Array(N),colors=new Float32Array(N*3);for(let i=0;i<N;i++){const n=nodes[i],c=KIND[n.kind]||KIND.concept;positions[i*3+2]=this.nodeDepth(n);sizes[i]=10;alpha[i]=1;phases[i]=hash(n.id)*TAU;colors.set(c,i*3);}this.nodeGeometry=new THREE.BufferGeometry();this.nodeGeometry.setAttribute('position',new THREE.BufferAttribute(positions,3));this.nodeGeometry.setAttribute('aSize',new THREE.BufferAttribute(sizes,1));this.nodeGeometry.setAttribute('aAlpha',new THREE.BufferAttribute(alpha,1));this.nodeGeometry.setAttribute('aPhase',new THREE.BufferAttribute(phases,1));this.nodeGeometry.setAttribute('aColor',new THREE.BufferAttribute(colors,3));this.glowPoints=new THREE.Points(this.nodeGeometry,this.glowMaterial);this.nodePoints=new THREE.Points(this.nodeGeometry,this.pointMaterial);this.glowPoints.frustumCulled=false;this.nodePoints.frustumCulled=false;this.root.add(this.glowPoints,this.nodePoints);this.createNebula();const segments=N>1500?8:N>600?16:32,strands=N>1500?1:2;this.segmentCount=segments;this.strands=strands;const verts=edges.length*segments*2*strands,lp=new Float32Array(verts*3),lc=new Float32Array(verts*3),la=new Float32Array(verts);for(let i=0;i<edges.length;i++){const e=edges[i],a=this.byId.get(e.source)?.n,b=this.byId.get(e.target)?.n;if(!a||!b)continue;const key=e.source<e.target?e.source+'|'+e.target:e.target+'|'+e.source;this.linesByKey.set(key,i);const c1=KIND[a.kind]||KIND.concept,c2=KIND[b.kind]||KIND.concept;for(let j=0;j<segments*2*strands;j++){const ix=(i*segments*2*strands+j);lc.set(c1.map((v,k)=>(v+c2[k])*.5),ix*3);la[ix]=.13;}}this.lineGeometry=new THREE.BufferGeometry();this.lineGeometry.setAttribute('position',new THREE.BufferAttribute(lp,3));this.lineGeometry.setAttribute('aColor',new THREE.BufferAttribute(lc,3));this.lineGeometry.setAttribute('aAlpha',new THREE.BufferAttribute(la,1));this.lines=new THREE.LineSegments(this.lineGeometry,this.lineMaterial);this.lines.frustumCulled=false;this.lines.renderOrder=-2;this.glowPoints.renderOrder=-1;this.root.add(this.lines);this.pulseCount=Math.min(360,Math.max(48,edges.length));this.pulseGeometry=new THREE.BufferGeometry();this.pulseGeometry.setAttribute('position',new THREE.BufferAttribute(new Float32Array(this.pulseCount*3),3));this.pulseGeometry.setAttribute('aSize',new THREE.BufferAttribute(new Float32Array(this.pulseCount),1));this.pulseGeometry.setAttribute('aAlpha',new THREE.BufferAttribute(new Float32Array(this.pulseCount),1));this.pulseGeometry.setAttribute('aProgress',new THREE.BufferAttribute(new Float32Array(this.pulseCount),1));this.pulseGeometry.setAttribute('aSpeed',new THREE.BufferAttribute(Float32Array.from({length:this.pulseCount},(_,i)=>.8+hash(i)*.4),1));this.pulseGeometry.setAttribute('aRandom',new THREE.BufferAttribute(Float32Array.from({length:this.pulseCount},(_,i)=>hash('pulse'+i)),1));this.pulses=new THREE.Points(this.pulseGeometry,this.pulseMaterial);this.pulses.frustumCulled=false;this.pulses.renderOrder=3;this.root.add(this.pulses);this.lastStyle='';}
 createNebula(){
  const count=this.nodes.length,per=count>1500?9:count>600?14:count>120?28:40,total=count*per;
  this.nebulaPer=per;this.cloudCenters=new Float32Array(total*3);
  const positions=new Float32Array(total*3),drift=new Float32Array(total*3),size=new Float32Array(total),alpha=new Float32Array(total),phase=new Float32Array(total);
  for(let ni=0;ni<count;ni++){const n=this.nodes[ni];for(let j=0;j<per;j++){
   const i=ni*per+j,key=n.id+':dust:'+j,u=hash(key+'u'),v=hash(key+'v'),r=Math.pow(hash(key+'r'),.65),theta=u*TAU,z=v*2-1,xy=Math.sqrt(1-z*z);
   this.cloudCenters.set([Math.cos(theta)*xy*r,Math.sin(theta)*xy*r,z*r],i*3);
   drift.set([.25+hash(key+'dx')*.6,.25+hash(key+'dy')*.6,.25+hash(key+'dz')*.6],i*3);
   size[i]=.8+hash(key+'size')*1.4;alpha[i]=0;phase[i]=hash(key+'phase')*TAU;
  }}
  this.cloudDrift=drift.slice();
  this.cloudGeometry=new THREE.BufferGeometry();for(const [name,array,itemSize]of [['position',positions,3],['aDrift',drift,3],['aSize',size,1],['aAlpha',alpha,1],['aPhase',phase,1]])this.cloudGeometry.setAttribute(name,new THREE.BufferAttribute(array,itemSize));
  this.nebula=new THREE.Points(this.cloudGeometry,this.cloudMaterial);this.nebula.frustumCulled=false;this.nebula.renderOrder=-3;this.root.add(this.nebula);
 }
 updateNebula(s){
  const p=this.cloudGeometry.attributes.position.array,a=this.cloudGeometry.attributes.aAlpha.array,drift=this.cloudGeometry.attributes.aDrift.array,nodeAlpha=this.nodeGeometry.attributes.aAlpha.array;
  const count=visibleCount(s,this.nodes.length),policy=nodeCountPolicy(Math.max(1,count),{width:s.W||this.W||1280,height:s.H||this.H||720});
  const scale=Math.max(.001,Math.abs(finite(s.cam?.k,1)));
  for(let ni=0;ni<this.nodes.length;ni++){const n=this.nodes[ni],z=this.nodeDepth(n),metrics=nodeVisualMetrics(n,s,count,policy,this.pointSizeLimit()),spread=metrics.nebulaRadius/scale;for(let j=0;j<this.nebulaPer;j++){const i=ni*this.nebulaPer+j,base=i*3;
   // Local dust belongs to this real cell, not a new graph node. Keep its screen
   // footprint bounded when a single memory is inspected very close up.
   p[base]=n.x+this.cloudCenters[base]*spread;p[base+1]=-n.y+this.cloudCenters[base+1]*spread;p[base+2]=z+this.cloudCenters[base+2]*spread;
   for(let axis=0;axis<3;axis++)drift[base+axis]=this.cloudDrift[base+axis]/scale;
   a[i]=Math.sqrt(Math.max(nodeAlpha[ni],0))*(count<=120?.48:.34);
  }}this.cloudGeometry.attributes.position.needsUpdate=true;this.cloudGeometry.attributes.aAlpha.needsUpdate=true;this.cloudGeometry.attributes.aDrift.needsUpdate=true;
 }
 pointSizeLimit(){return finite(this.maxPointDevice,256)/(Math.max(.1,finite(this.shared?.uDpr?.value,1))*(1+BREATH_AMPLITUDE));}
 radiusOnScreen(n,s){return nodeVisualMetrics(n,s,visibleCount(s,this.nodes.length),undefined,this.pointSizeLimit()).radius;}
 readableCoreDiameter(n,s){return nodeVisualMetrics(n,s,visibleCount(s,this.nodes.length),undefined,this.pointSizeLimit()).readableCoreDiameter;}
 nodeDepth(n){return(hash(n.id+'z')-.5)*this.depthScale;}
 buildSpline(e,strand=0){const a=this.byId.get(e.source)?.n,b=this.byId.get(e.target)?.n;if(!a||!b)return null;const start=new THREE.Vector3(a.x,-a.y,this.nodeDepth(a)),end=new THREE.Vector3(b.x,-b.y,this.nodeDepth(b)),length=start.distanceTo(end);return createWaveSpline(start,end,hash(e.source+'phase')*TAU,hash(e.target+'phase2')*TAU,Math.min(35,length*.13),2.6+hash(e.source+e.target)*1.6,strand);}
 curve(e,t,strand=0){const key=e.source+'>'+e.target+':'+strand;let data=this.curves[key];if(!data){data=this.buildSpline(e,strand);this.curves[key]=data;}if(!data)return[0,0,0];const p=data.curve.getPoint(t);return[p.x,p.y,p.z];}
 syncTransform(s){this.root.position.set(s.cam.x-this.W/2,this.H/2-s.cam.y,0);this.root.scale.set(s.cam.k,s.cam.k,s.cam.k);this.root.updateMatrixWorld(true);this.camera.updateMatrixWorld(true);}
 projectNode(n){return this.projectLocal(this.scratch.set(n.x,-n.y,this.nodeDepth(n)));}
 projectLocal(local){const p=local.clone().applyMatrix4(this.root.matrixWorld).project(this.camera);return{x:(p.x+1)*this.W/2,y:(1-p.y)*this.H/2,depth:p.z};}
 projectedBounds(nodes,s,{includeRadius=true}={}){
  if(!nodes?.length)return null;
  // Fit can run before setGraph's first render. Use the impending full graph's
  // depth range, not the previous library's or a focused subset's range.
  this.depthScale=nodeDepthScale(s.nodes?.length??(this.nodes.length||nodes.length));
  this.syncTransform(s);
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity,count=0;
  for(const n of nodes){if(!Number.isFinite(n.x)||!Number.isFinite(n.y))continue;const p=this.projectNode(n);if(!Number.isFinite(p.x)||!Number.isFinite(p.y))continue;const r=includeRadius?this.radiusOnScreen(n,s):0;minX=Math.min(minX,p.x-r);minY=Math.min(minY,p.y-r);maxX=Math.max(maxX,p.x+r);maxY=Math.max(maxY,p.y+r);count++;}
  return count?{minX,minY,maxX,maxY,width:maxX-minX,height:maxY-minY,centerX:(minX+maxX)/2,centerY:(minY+maxY)/2,count}:null;
 }
 screenDeltaToTranslation(dx,dy){
  if(!Number.isFinite(dx)||!Number.isFinite(dy))return null;
  this.camera.updateMatrixWorld(true);
  const right=new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld,0),up=new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld,1),zoom=this.camera.zoom;
  const a=right.x*zoom,b=-right.y*zoom,c=-up.x*zoom,d=up.y*zoom,det=a*d-b*c;
  if(!Number.isFinite(det)||Math.abs(det)<1e-4)return null;
  const x=(d*dx-b*dy)/det,y=(-c*dx+a*dy)/det;
  return Number.isFinite(x)&&Number.isFinite(y)?{x,y}:null;
 }
 panCamera(dx,dy){const right=new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld,0),up=new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld,1),delta=right.multiplyScalar(dx).addScaledVector(up,-dy);this.camera.position.add(delta);this.controls.target.add(delta);this.controls.update();this.camera.updateMatrixWorld(true);}
 centerNode(n,s){this.syncTransform(s);const p=this.projectNode(n);this.panCamera(p.x-this.W/2,p.y-this.H/2);}
 captureScreenPoint(x,y,s){this.syncTransform(s);const p=new THREE.Vector3(x/this.W*2-1,1-y/this.H*2,0).unproject(this.camera);return this.root.worldToLocal(p);}
 restoreScreenPoint(point,x,y,s){this.syncTransform(s);const p=this.projectLocal(point);this.panCamera(p.x-x,p.y-y);}
 resetView(){this.controls.target.set(0,0,0);this.camera.position.set(-180,100,1200);this.camera.zoom=1;this.camera.lookAt(this.controls.target);this.camera.updateProjectionMatrix();this.controls.update();}
 setEnabled(enabled){this.controls.enabled=enabled;}

 updatePositions(){let changed=this.lastPosition.length!==this.nodes.length*2;const p=this.nodeGeometry.attributes.position.array;for(let i=0;i<this.nodes.length;i++){const n=this.nodes[i];if(this.lastPosition[i*2]!==n.x||this.lastPosition[i*2+1]!==n.y)changed=true;this.lastPosition[i*2]=n.x;this.lastPosition[i*2+1]=n.y;p[i*3]=n.x;p[i*3+1]=-n.y;}if(!changed)return;this.curves=[];this.nodeGeometry.attributes.position.needsUpdate=true;const points=this.lineGeometry.attributes.position.array;let offset=0;for(const e of this.edges)for(let strand=0;strand<this.strands;strand++)for(let j=0;j<this.segmentCount;j++){points.set(this.curve(e,j/this.segmentCount,strand),offset);offset+=3;points.set(this.curve(e,(j+1)/this.segmentCount,strand),offset);offset+=3;}this.lineGeometry.attributes.position.needsUpdate=true;}
 updateStyle(s){const chosen=s.selected||s.hover,near=chosen?new Set([chosen,...(s.adj.get(chosen)||[]).map(x=>x.id)]):null;const a=this.nodeGeometry.attributes.aAlpha.array,size=this.nodeGeometry.attributes.aSize.array,c=this.nodeGeometry.attributes.aColor.array,count=visibleCount(s,this.nodes.length),policy=nodeCountPolicy(Math.max(1,count),{width:s.W||this.W||1280,height:s.H||this.H||720});for(let i=0;i<this.nodes.length;i++){const n=this.nodes[i],st=n.state||'active',active=s.active.has(n.id),anchor=!!(n.is_anchor||n.anchor);let opacity=st==='forgotten'?.10:st==='dormant'?.28:st==='fading'?.65:1;if(!s.visibleSet.has(n.id))opacity=0;if(near&&!near.has(n.id))opacity*=.18;if(s.active.size&&!active)opacity*=.27;size[i]=nodeScreenDiameter(n,s,count,policy,this.pointSizeLimit());a[i]=opacity;const col=KIND[n.kind]||KIND.concept;c.set(col,i*3);}this.nodeGeometry.attributes.aSize.needsUpdate=true;this.nodeGeometry.attributes.aAlpha.needsUpdate=true;this.nodeGeometry.attributes.aColor.needsUpdate=true;const la=this.lineGeometry.attributes.aAlpha.array;let ix=0;for(const e of this.edges){const lit=s.lit.has(e.source<e.target?e.source+'|'+e.target:e.target+'|'+e.source);let alpha=.035+clamp(Number(e.effective_w??e.w??.2),0,1)*.16;if(!s.visibleSet.has(e.source)||!s.visibleSet.has(e.target))alpha=0;if(e.active===false)alpha*=.28;if(chosen&&e.source!==chosen&&e.target!==chosen)alpha*=.15;if(s.active.size&&!lit)alpha*=.2;if(lit&&s.visibleSet.has(e.source)&&s.visibleSet.has(e.target))alpha=.5;for(let j=0;j<this.segmentCount*2*this.strands;j++)la[ix++]=alpha;}this.lineGeometry.attributes.aAlpha.needsUpdate=true;}
 updatePulses(s,time){const p=this.pulseGeometry.attributes.position.array,a=this.pulseGeometry.attributes.aAlpha.array,z=this.pulseGeometry.attributes.aSize.array,progress=this.pulseGeometry.attributes.aProgress.array;a.fill(0);let i=0;const trail=s.result?.trail||[];for(const t of trail){if(i>=this.pulseCount)break;const from=String(Array.isArray(t)?t[0]:t.from),to=String(Array.isArray(t)?t[1]:t.to),key=from<to?from+'|'+to:to+'|'+from;const edgeIndex=this.linesByKey.get(key);if(edgeIndex===undefined||!s.lit.has(key)||!s.visibleSet.has(from)||!s.visibleSet.has(to))continue;const e=this.edges[edgeIndex],step=Number(Array.isArray(t)?t[3]:t.step)||1,phase=((time*.20*(.8+hash(key)*.4)+hash(key)-step*.13)%1+1)%1;const forward=e.source===from?phase:1-phase;const v=this.curve(e,forward);p.set(v,i*3);a[i]=Math.sin(phase*Math.PI)*.95;z[i]=.7;progress[i]=phase;i++;if(i<this.pulseCount){const tail=clamp(phase-.04,0,1);p.set(this.curve(e,e.source===from?tail:1-tail),i*3);a[i]=Math.sin(tail*Math.PI)*.32;z[i]=1.1;progress[i]=tail;i++;}}this.pulseGeometry.attributes.position.needsUpdate=true;this.pulseGeometry.attributes.aAlpha.needsUpdate=true;this.pulseGeometry.attributes.aSize.needsUpdate=true;this.pulseGeometry.attributes.aProgress.needsUpdate=true;}
 render(s,now){this.setGraph(s.nodes,s.edges);if(!this.W||!this.H)return;const time=s.paused?(this.pausedAt||0):now/1000;if(!s.paused)this.pausedAt=time;this.shared.uTime.value=time;this.shared.uLight.value=0;this.shared.uScale.value=s.cam.k;this.controls.enabled=s.art;this.controls.update();this.syncTransform(s);this.updatePositions();this.updateStyle(s);this.updateNebula(s);this.updatePulses(s,time);this.pulseMaterial.blending=this.shared.uLight.value?THREE.NormalBlending:THREE.AdditiveBlending;this.renderer.render(this.scene,this.camera);}
 dispose(){this.clearGraph();this.pointMaterial.dispose();this.glowMaterial.dispose();this.lineMaterial.dispose();this.cloudMaterial.dispose();this.pulseMaterial.dispose();this.particleTexture.dispose();this.controls.dispose();this.renderer.dispose();}
}
export {NeuralArt,nodeVisualMetrics,nodeScreenDiameter,POINT_CORE_RADIUS,BREATH_AMPLITUDE,pointVertex,pointFragment};
window.NKBArt={NeuralArt,viewportPolicy,version:'2.1.0',upstream:'SahilK-027/Digital-Brain@366cf81',three:THREE.REVISION};
