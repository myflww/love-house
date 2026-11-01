/* Love House neural fibres. This enhancement preserves the original graph,
 * viewport, picking and licensing contracts. Geometry is derived exclusively
 * from real graph edges; visual layout never changes canonical node positions.
 */
import * as THREE from 'three';
import {synapseMetrics,sampleSynapse,gravityTargets,recallActivity} from './synapse-dynamics.js';

const finite=(v,f=0)=>Number.isFinite(Number(v))?Number(v):f;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const lerp=(a,b,t)=>a+(b-a)*t;
const edgeKey=(a,b)=>a<b?a+'|'+b:b+'|'+a;
function seedOf(value){let h=2166136261;for(const c of String(value))h=Math.imul(h^c.charCodeAt(0),16777619);return h>>>0;}
const ribbonVertex=`
attribute vec3 aTangent; attribute float aSide; attribute float aWidth;
attribute float aAlpha; varying float vAlpha; varying float vSide;
uniform vec2 uViewport;
void main(){
 vec4 p=projectionMatrix*modelViewMatrix*vec4(position,1.);
 vec4 q=projectionMatrix*modelViewMatrix*vec4(position+aTangent,1.);
 vec2 delta=(q.xy/max(abs(q.w),.0001)-p.xy/max(abs(p.w),.0001))*uViewport;
 vec2 normal=length(delta)>.00001?normalize(vec2(-delta.y,delta.x)):vec2(0.,1.);
 p.xy+=normal*aSide*aWidth/max(uViewport,vec2(1.))*p.w;
 gl_Position=p;vAlpha=aAlpha;vSide=aSide;
}`;
const ribbonFragment=`
precision highp float; varying float vAlpha; varying float vSide; uniform float uLight;
void main(){float feather=1.-smoothstep(.62,1.,abs(vSide));
 gl_FragColor=vec4(mix(vec3(.95),vec3(.045),uLight),vAlpha*feather);}
`;

/** Drop-in subclass factory. Use enhanceNeuralArt(NeuralArt) at the existing
 * bundle registration point; no duplicate canvas, scene or animation loop.
 * The enhanced renderer accepts S.graphMode='nebula'|'flat' (default nebula).
 * isTransitioning() tells the host when a user-requested morph needs more frames.
 */
export function enhanceNeuralArt(Base){
 return class NeuralFibers extends Base{
  constructor(...args){super(...args);this.flatMix=0;this.motionTime=0;this.lastWall=null;this.flatTargets=new Map();this.lastMode='nebula';}

  setGraph(nodes,edges){
   if(this.nodes===nodes&&this.edges===edges&&this.fiberGeometryReady)return;
   super.setGraph(nodes,edges);
   this.flatTargets=gravityTargets(nodes,edges);
   this.flatMix=finite(this.flatMix);this.motionTime=finite(this.motionTime);
   this.segmentCount=Math.max(4,Math.min(nodes.length>1500?8:nodes.length>600?12:24,Math.floor(50000/Math.max(1,edges.length*(nodes.length<=300&&edges.length<=1200?2:1)))));
   this.strands=nodes.length<=300&&edges.length<=1200?2:1;
   this.root.remove(this.lines);this.lineGeometry.dispose();
   if(!this.fiberMaterial){
    this.fiberViewport={value:new THREE.Vector2(Math.max(1,this.W||1),Math.max(1,this.H||1))};
    this.fiberMaterial=new THREE.ShaderMaterial({vertexShader:ribbonVertex,fragmentShader:ribbonFragment,
      uniforms:{...this.shared,uViewport:this.fiberViewport},transparent:true,depthTest:false,depthWrite:false,side:THREE.DoubleSide});
   }
   const count=edges.length*this.segmentCount*this.strands*6,g=new THREE.BufferGeometry();
   for(const [name,size]of [['position',3],['aTangent',3],['aSide',1],['aWidth',1],['aAlpha',1]])g.setAttribute(name,new THREE.BufferAttribute(new Float32Array(count*size),size).setUsage(THREE.DynamicDrawUsage));
   this.lineGeometry=g;this.lines=new THREE.Mesh(g,this.fiberMaterial);this.lines.frustumCulled=false;this.lines.renderOrder=-2;this.root.add(this.lines);
   this.edgeSeeds=edges.map(e=>seedOf(edgeKey(e.source,e.target)));
   this.edgeMetrics=edges.map(e=>synapseMetrics(e,this.byId.get(e.source)?.n,this.byId.get(e.target)?.n));
   this.fiberGeometryReady=true;this.lastGeometryStamp='';this.lastMode=this.lastMode||'nebula';
  }

  resize(w,h,dpr){super.resize(w,h,dpr);this.fiberViewport?.value.set(Math.max(1,w),Math.max(1,h));}

  displayPosition(n){
   const target=this.flatTargets?.get(n.id),f=finite(this.flatMix);
   return {x:target?lerp(finite(n.x),target.x,f):finite(n.x),y:target?lerp(finite(n.y),target.y,f):finite(n.y)};
  }
  nodeDepth(n){return super.nodeDepth(n)*(1-finite(this.flatMix));}
  projectNode(n){const p=this.displayPosition(n);return this.projectLocal(this.scratch.set(p.x,-p.y,this.nodeDepth(n)));}
  projectedBounds(nodes,s,options){if(s.nodes&&this.nodes!==s.nodes)this.setGraph(s.nodes,s.edges||[]);return super.projectedBounds(nodes,s,options);}

  curve(e,t,strand=0){
   const a=this.byId.get(e.source)?.n,b=this.byId.get(e.target)?.n;if(!a||!b)return[0,0,0];
   const p=this.displayPosition(a),q=this.displayPosition(b),metrics=synapseMetrics(e,a,b);
   // Plane links keep a living, subtle bend while their depth is precisely zero.
   const point=sampleSynapse({x:p.x,y:-p.y,z:this.nodeDepth(a)},{x:q.x,y:-q.y,z:this.nodeDepth(b)},t,metrics,this.motionTime||0,seedOf(edgeKey(e.source,e.target)),strand);
   const baseZ=lerp(this.nodeDepth(a),this.nodeDepth(b),clamp(finite(t),0,1));
   return[point.x,point.y,baseZ+(point.z-baseZ)*(1-finite(this.flatMix))];
  }

  advanceView(s,now){
   const mode=s.graphMode==='flat'?'flat':'nebula',goal=mode==='flat'?1:0,previousMix=finite(this.flatMix);
   const dt=this.lastWall==null?0:clamp((now-this.lastWall)/1000,0,.1);this.lastWall=now;
   if(!s.paused&&!globalThis.document?.hidden)this.motionTime=finite(this.motionTime)+dt;
   const reduced=globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
   this.flatMix=reduced?goal:lerp(finite(this.flatMix),goal,1-Math.exp(-dt*5.8));
   if(Math.abs(this.flatMix-goal)<.0002)this.flatMix=goal;
   if(mode==='flat'&&this.lastMode!=='flat'&&!this.orbitSnapshot)this.orbitSnapshot={position:this.camera.position.clone(),target:this.controls.target.clone()};
   if(mode==='nebula'&&this.lastMode==='flat'&&previousMix===1)this.flatSnapshot={position:this.camera.position.clone(),target:this.controls.target.clone()};
   if(this.orbitSnapshot&&(this.flatMix!==previousMix||mode!==this.lastMode)){
    const f=this.flatMix,snapshot=this.orbitSnapshot,flat=this.flatSnapshot||{position:new THREE.Vector3(0,0,1200),target:new THREE.Vector3()};
    this.camera.position.copy(snapshot.position).lerp(flat.position,f);
    this.controls.target.copy(snapshot.target).lerp(flat.target,f);
    this.camera.lookAt(this.controls.target);this.camera.updateMatrixWorld(true);
   }
   if(mode==='nebula'&&this.flatMix===0&&this.orbitSnapshot){
    this.camera.position.copy(this.orbitSnapshot.position);this.controls.target.copy(this.orbitSnapshot.target);this.camera.lookAt(this.controls.target);this.camera.updateMatrixWorld(true);this.orbitSnapshot=null;this.flatSnapshot=null;
   }
   this.lastMode=mode;this.controls.enabled=!!s.art&&mode==='nebula'&&this.flatMix===0;
  }
  isTransitioning(){return Math.abs(finite(this.flatMix)-(this.lastMode==='flat'?1:0))>.0002;}
  resetView(){
   if(this.lastMode==='flat'){
    this.controls.target.set(0,0,0);this.camera.position.set(0,0,1200);this.camera.zoom=1;this.camera.lookAt(this.controls.target);this.camera.updateProjectionMatrix();this.camera.updateMatrixWorld(true);this.controls.update();
    this.flatSnapshot={position:this.camera.position.clone(),target:this.controls.target.clone()};
   }else{super.resetView();this.orbitSnapshot=null;this.flatSnapshot=null;}
  }

  drawPlaneGuide(ctx,s){
   const opacity=finite(this.flatMix);if(opacity<.05||this.nodes.length<3)return;
   const light=globalThis.document?.documentElement?.dataset.theme==='light';
   const ink=light?'20,20,20':'238,238,238',radius=Math.max(90,Math.sqrt(this.nodes.length)*23);
   ctx.save();ctx.lineWidth=.7;ctx.font='11px -apple-system,"PingFang SC",sans-serif';
   for(const ratio of [.24,.5,.76,1]){
    ctx.beginPath();for(let j=0;j<=80;j++){
     const angle=j/80*Math.PI*2,p=this.projectLocal(new THREE.Vector3(Math.cos(angle)*radius*ratio,Math.sin(angle)*radius*ratio,0));
     if(!j)ctx.moveTo(p.x,p.y);else ctx.lineTo(p.x,p.y);
    }
    ctx.strokeStyle=`rgba(${ink},${opacity*.085})`;ctx.stroke();
   }
   const center=this.projectLocal(new THREE.Vector3());
   if(center.x>60&&center.x<this.W-60&&center.y>60&&center.y<this.H-60){ctx.fillStyle=`rgba(${ink},${opacity*.45})`;ctx.textAlign='center';ctx.fillText('累计调用活跃度 · 内圈更常被想起',center.x,center.y+18);}
   ctx.restore();
  }

  updatePositions(){
   if(!this.nodeGeometry)return;
   const positions=this.nodeGeometry.attributes.position.array;
   for(let i=0;i<this.nodes.length;i++){const n=this.nodes[i],p=this.displayPosition(n);positions.set([p.x,-p.y,this.nodeDepth(n)],i*3);}
   this.nodeGeometry.attributes.position.needsUpdate=true;
   const g=this.lineGeometry.attributes,p=g.position.array,tangent=g.aTangent.array,side=g.aSide.array;
   let vertex=0;
   for(let ei=0;ei<this.edges.length;ei++){
    const e=this.edges[ei],a=this.byId.get(e.source)?.n,b=this.byId.get(e.target)?.n;
    if(!a||!b){vertex+=this.segmentCount*this.strands*6;continue;}
    const aa=this.displayPosition(a),bb=this.displayPosition(b),start={x:aa.x,y:-aa.y,z:this.nodeDepth(a)},end={x:bb.x,y:-bb.y,z:this.nodeDepth(b)};
    const metrics=this.edgeMetrics[ei],seed=this.edgeSeeds[ei];
    for(let strand=0;strand<this.strands;strand++){
     const points=[];
     for(let j=0;j<=this.segmentCount;j++){
      const point=sampleSynapse(start,end,j/this.segmentCount,metrics,this.motionTime,seed,strand);
      const baseZ=lerp(start.z,end.z,j/this.segmentCount);
      points.push([point.x,point.y,baseZ+(point.z-baseZ)*(1-finite(this.flatMix))]);
     }
     for(let j=0;j<this.segmentCount;j++){
      const prev=points[Math.max(0,j-1)],next=points[Math.min(this.segmentCount,j+1)],after=points[Math.min(this.segmentCount,j+2)];
      const ta=next.map((v,k)=>v-prev[k]),tb=after.map((v,k)=>v-points[j][k]);
      for(const [ix,sign]of [[j,-1],[j,1],[j+1,-1],[j,1],[j+1,1],[j+1,-1]]){
       p.set(points[ix],vertex*3);tangent.set(ix===j?ta:tb,vertex*3);side[vertex]=sign;vertex++;
      }
     }
    }
   }
   for(const name of ['position','aTangent','aSide'])g[name].needsUpdate=true;
  }

  updateStyle(s){
   super.updateStyle(s);
   if(!this.fiberGeometryReady)return;
   const widths=this.lineGeometry.attributes.aWidth.array,alphas=this.lineGeometry.attributes.aAlpha.array;
   const chosen=s.selected||s.hover;let index=0;
   const zoom=clamp(Math.pow(Math.max(.001,finite(s.cam?.k,1)),.24),.5,2.3),dense=this.edges.length>2500?.72:1;
   this.edgeMetrics=this.edges.map(e=>synapseMetrics(e,this.byId.get(e.source)?.n,this.byId.get(e.target)?.n));
   this.visibleFiberEdges=0;
   for(let ei=0;ei<this.edges.length;ei++){
    const e=this.edges[ei],metrics=this.edgeMetrics[ei],key=edgeKey(e.source,e.target);
    const visible=!!s.visibleSet?.has(e.source)&&!!s.visibleSet?.has(e.target),lit=!!s.lit?.has(key);
    if(visible)this.visibleFiberEdges++;
    const incident=e.source===chosen||e.target===chosen;
    let alpha=visible?metrics.alpha*(incident?1.25:1):0;
    if(chosen&&!incident)alpha*=.2;
    if(s.active?.size&&!lit)alpha*=.3;
    if(lit&&visible)alpha=Math.max(.64,alpha);
    for(let strand=0;strand<this.strands;strand++)for(let j=0;j<this.segmentCount;j++){
     const taper=.6+.4*Math.sin((j+.5)/this.segmentCount*Math.PI);
     for(let k=0;k<6;k++){
      widths[index]=metrics.width*zoom*dense*taper*(strand===0?1:.35)*(incident?1.1:1);
      alphas[index]=alpha*(strand===0?1:.32);index++;
     }
    }
   }
   this.lineGeometry.attributes.aWidth.needsUpdate=true;this.lineGeometry.attributes.aAlpha.needsUpdate=true;
  }

  updateNebula(s){
   // Keep the upstream density/point-size budget and local dust envelope. Only
   // translate centers to the current visual layout, never change real nodes.
   super.updateNebula(s);
   const p=this.cloudGeometry.attributes.position.array,a=this.cloudGeometry.attributes.aAlpha.array;
   for(let ni=0;ni<this.nodes.length;ni++){
    const n=this.nodes[ni],display=this.displayPosition(n),dx=display.x-finite(n.x),dy=-(display.y-finite(n.y));
    for(let j=0;j<this.nebulaPer;j++){const i=ni*this.nebulaPer+j;p[i*3]+=dx;p[i*3+1]+=dy;a[i]*=1-finite(this.flatMix)*.82;}
   }
   this.cloudGeometry.attributes.position.needsUpdate=true;this.cloudGeometry.attributes.aAlpha.needsUpdate=true;
  }

  render(s,now){
   this.setGraph(s.nodes,s.edges);if(!this.W||!this.H)return;
   this.advanceView(s,now);
   this.shared.uTime.value=this.motionTime;
   const light=globalThis.document?.documentElement?.dataset.theme==='light';
   this.shared.uLight.value=light?1:0;this.shared.uScale.value=s.cam.k;
   this.fiberViewport.value.set(this.W,this.H);
   this.controls.update();this.syncTransform(s);this.updateStyle(s);this.updatePositions();this.updateNebula(s);
   this.updatePulses(s,this.motionTime);
   this.pulseMaterial.blending=light?THREE.NormalBlending:THREE.AdditiveBlending;
   this.pulseMaterial.uniforms.uColor1?.value.set(light?0x101010:0xdddddd);
   this.pulseMaterial.uniforms.uColor2?.value.set(light?0x050505:0xffffff);
   this.renderer.render(this.scene,this.camera);
   this.canvas.dataset.fiberEdges=String(this.edges.length);this.canvas.dataset.visibleFiberEdges=String(this.visibleFiberEdges);
   this.canvas.dataset.graphMode=this.lastMode;this.canvas.dataset.flatMix=this.flatMix.toFixed(4);
   this.canvas.dataset.motionTime=this.motionTime.toFixed(3);
  }

  dispose(){super.dispose();this.fiberMaterial?.dispose();this.flatTargets?.clear();this.edgeMetrics=[];this.edgeSeeds=[];}
 };
}

export {synapseMetrics,sampleSynapse,gravityTargets,recallActivity,ribbonVertex,ribbonFragment};
