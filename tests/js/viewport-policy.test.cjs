/* Physical invariants for the adaptive graph camera; no browser, model or private data. */
const test=require('node:test');
const assert=require('node:assert/strict');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const modulePromise=import(pathToFileURL(path.join(__dirname,'../../nkb/viz/art/viewport-policy.js')).href);
function contains(plan,raw){
 const f=plan.frame,tolerance=1e-5*Math.max(1,f.width,f.height);
 const corners=[[raw.x,raw.y],[raw.x+raw.w,raw.y],[raw.x,raw.y+raw.h],[raw.x+raw.w,raw.y+raw.h]];
 for(const [wx,wy] of corners){
  const x=wx*plan.k+plan.x,y=wy*plan.k+plan.y;
  assert.ok(x>=f.x-tolerance&&x<=f.x+f.width+tolerance,`x=${x} outside ${f.x}..${f.x+f.width}`);
  assert.ok(y>=f.y-tolerance&&y<=f.y+f.height+tolerance,`y=${y} outside ${f.y}..${f.y+f.height}`);
 }
}

test('empty library is a finite neutral camera without imaginary memory content',async()=>{
 const {planViewport,nodeCountPolicy}=await modulePromise;
 const p=planViewport(null,{x:150,y:45,width:900,height:600},0);
 assert.equal(p.empty,true);assert.equal(p.scale,1);assert.equal(p.content.width,0);assert.equal(p.content.height,0);
 assert.equal(nodeCountPolicy(0).labelBudget,0);assert.equal(nodeCountPolicy(0).targetReadableCoreDiameter,0);
 assert.ok(Number.isFinite(p.x)&&Number.isFinite(p.y));
});

test('few memories have readable cores and all labels while dense graphs become an overview',async()=>{
 const {nodeCountPolicy}=await modulePromise;
 const viewport={width:1280,height:720},counts=[1,3,12,72,225,1000];
 const policies=counts.map(n=>nodeCountPolicy(n,viewport));
 assert.ok(policies[0].targetReadableCoreDiameter>=16&&policies[0].targetReadableCoreDiameter<=22);
 assert.ok(policies[3].targetReadableCoreDiameter>=7&&policies[3].targetReadableCoreDiameter<=11);
 assert.ok(policies[4].targetReadableCoreDiameter>=4&&policies[4].targetReadableCoreDiameter<=7);
 assert.ok(policies[5].targetReadableCoreDiameter>=2&&policies[5].targetReadableCoreDiameter<=4);
 assert.deepEqual(policies.slice(0,3).map(p=>p.labelBudget),[1,3,12]);
 assert.ok(policies[5].labelBudget<policies[3].labelBudget);
 for(let i=1;i<policies.length;i++)assert.ok(policies[i].targetReadableCoreDiameter<policies[i-1].targetReadableCoreDiameter);
 assert.ok(policies[0].maxAutoScale>=5&&policies[0].maxAutoScale<=6);
});

test('adding memories never pushes the camera closer for the same spatial extent',async()=>{
 const {planViewport}=await modulePromise;
 for(const extent of [36,100,600,1800]){
  const bounds={x:-extent/2,y:-extent/2,w:extent,h:extent},viewport={width:1000,height:650};
  let previous=Infinity;
  for(const n of [1,3,12,72,225,1000]){
   const p=planViewport(bounds,viewport,n);
   assert.ok(p.k<=previous+1e-9,`${n} has larger auto zoom ${p.k} than ${previous}`);
   contains(p,bounds);previous=p.k;
  }
 }
});

test('all nodes fit real offset and panel-reduced rectangles for sparse and large libraries',async()=>{
 const {planViewport}=await modulePromise;
 const viewport={left:282,top:68,width:658,height:572};
 for(const n of [1,3,12,72,225,1000]){
  const span=Math.max(36,Math.sqrt(n)*48),b={x:-span*.4,y:-span*.8,w:span*1.1,h:span*.7};
  const p=planViewport(b,viewport,n);
  assert.equal(p.valid,true);assert.equal(p.fullyVisible,true);contains(p,b);
  assert.ok(p.frame.x>=viewport.left&&p.frame.y>=viewport.top);
  assert.ok(p.frame.x+p.frame.width<=viewport.left+viewport.width);
  assert.ok(p.frame.y+p.frame.height<=viewport.top+viewport.height);
 }
});

test('a distant memory is retained even when it needs zoom below the manual floor',async()=>{
 const {planViewport,fitScale}=await modulePromise;
 const b={x:-100,y:-100,w:200000,h:40000},v={width:900,height:600};
 const p=planViewport(b,v,73,{minScale:.025});
 assert.equal(p.fullyVisible,true);assert.equal(p.minScaleRelaxed,true);assert.ok(p.k<.025);contains(p,b);
 assert.equal(p.scale,fitScale(b,v,{count:73,minScale:.025}));
});

test('zero spans center safely, narrow/tall windows reserve space and huge coordinates stay finite',async()=>{
 const {planViewport,nodeCountPolicy}=await modulePromise;
 for(const viewport of [{width:180,height:900},{width:1400,height:130},{x:12,y:9,width:3,height:2}]){
  const b={x:50,y:-80,w:0,h:0},p=planViewport(b,viewport,1);
  assert.equal(p.fullyVisible,true);assert.ok(p.k>0);contains(p,b);
  for(const key of ['x','y','k'])assert.ok(Number.isFinite(p[key]));
 }
 const large={x:-1e12,y:2e12,w:4e12,h:9e12};
 const p=planViewport(large,{x:200,y:50,width:800,height:600},1000);
 assert.equal(p.fullyVisible,true);contains(p,large);
 const small=nodeCountPolicy(72,{width:220,height:220});
 const big=nodeCountPolicy(72,{width:1280,height:720});
 assert.ok(small.labelBudget<big.labelBudget);assert.ok(small.targetReadableCoreDiameter<=big.targetReadableCoreDiameter);
});

test('invalid inputs do not propagate NaN or claim a bad frame is valid',async()=>{
 const {planViewport,nodeCountPolicy}=await modulePromise;
 for(const bad of [null,{}, {x:NaN,y:0,w:100,h:100},{x:0,y:Infinity,w:1,h:1},{x:1e308,y:0,w:1e308,h:1}]){
  const p=planViewport(bad,{width:0,height:-10},72);
  assert.equal(p.valid,false);assert.equal(p.fullyVisible,false);
  for(const key of ['x','y','k'])assert.ok(Number.isFinite(p[key]));
 }
 const p=planViewport({minX:30,minY:40,maxX:-10,maxY:-20},{width:600,height:400},3);
 assert.equal(p.valid,true);contains(p,{x:-10,y:-20,w:40,h:60});
 for(const n of [-1,NaN,Infinity,'72'])assert.equal(nodeCountPolicy(n).count,0);
});

test('component packing removes fixed empty rings without overlapping isolated memory centers',async()=>{
 const {nodeCountPolicy,planViewport}=await modulePromise;
 // Reproduce the fixed former placement and its policy replacement. No physics is
 // required to prove the old hard-coded ring caused sparse-world scale inflation.
 function isolated(n,policy){
  const result=[];let outer=0;
  const mainR=policy?policy.minMainRadius:90;
  const radius=policy?policy.minComponentRadius:45;
  for(let ci=0;ci<n;ci++){
   const ring=ci?mainR+(policy?policy.componentGap:120)+radius+Math.sqrt(outer)*(policy?policy.componentSpacing:52):0;
   const theta=ci*2.399963229728653;result.push({x:Math.cos(theta)*ring,y:Math.sin(theta)*ring});
   if(ci)outer++;
  }
  return result;
 }
 for(const n of [3,72]){
  const policy=nodeCountPolicy(n,{width:1280,height:720}),old=isolated(n),packed=isolated(n,policy);
  const maxRadius=points=>Math.max(...points.map(p=>Math.hypot(p.x,p.y)));
  assert.ok(maxRadius(packed)<maxRadius(old)*(n===3?.35:.55),`${n} did not compact the large empty orbital rings`);
  const xs=packed.map(p=>p.x),ys=packed.map(p=>p.y),b={x:Math.min(...xs),y:Math.min(...ys),w:Math.max(...xs)-Math.min(...xs),h:Math.max(...ys)-Math.min(...ys)};
  const view=planViewport(b,{width:1280,height:720},n);
  let minSeparation=Infinity;
  for(let i=0;i<packed.length;i++)for(let j=i+1;j<packed.length;j++)minSeparation=Math.min(minSeparation,Math.hypot(packed[i].x-packed[j].x,packed[i].y-packed[j].y)*view.k);
  assert.ok(minSeparation>policy.targetReadableCoreDiameter*1.5,`${n} cores overlap after compaction`);
 }
});
