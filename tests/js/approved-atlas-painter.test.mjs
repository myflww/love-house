import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {ApprovedAtlasPainter} from '../../nkb/viz/art/approved-atlas-painter.js';
const LOCKED_SOURCE_SHA='dd31e23f5834b83bdf0c1b881bf2302852747d927834b326a9014fc2b9740090';
const FUNCTION_HASHES={
  "edgeStyle": "83b6181efac49ff6e82d5ceffa401db15b099b180745c71cc373b2e7c7d0b3e6",
  "curveFor": "29501ea6e9683870fbda4128eab736cb495395c882d91473b1ab2db385236dae",
  "pointAt": "3848fe4f2a6da4b41849e7c5b172726eb41c5ab7ffad4a7bfb45bc4f903f94c5",
  "path": "c07dd364f60704d05542b1f8f7839c8d0bf4d45f26a904c20c8c0d0f7f33ef3c",
  "drawFlatGuide": "0c2aa57b02892b1b0845e3b9339354ecccf69946eabedae9bca1d95a7453e855",
  "drawCloud": "6ce3ebf73953bb100400c330fbc0f7f3c6e5803ae93f6bc617362007101c9849",
  "drawEdges": "8674d5e870681456ec995a7e9d5f154a457222b27a3054e6e337d0f21978707f",
  "drawNodes": "1e594e4a782e39023026e0afad478a9068d8045623e61e86b99ee3bfaacfeae3",
  "drawPulses": "cdeb3f608c6f13bc7635e2cf9a6c502dd2406d8d9f32cc793d2b6a485c1a9165"
};

const painterSource=readFileSync(new URL('../../nkb/viz/art/approved-atlas-painter.js',import.meta.url),'utf8');
function functionBlock(source,name){
 const start=source.indexOf('function '+name+'(');assert.ok(start>=0,name);let depth=0,quote='',escape=false,line=false,block=false;
 for(let i=source.indexOf('{',start);i<source.length;i++){
  const c=source[i],next=source[i+1];
  if(line){if(c==='\n')line=false;continue;}
  if(block){if(c==='*'&&next==='/'){block=false;i++;}continue;}
  if(quote){if(escape)escape=false;else if(c==='\\')escape=true;else if(c===quote)quote='';continue;}
  if(c==='/'&&next==='/'){line=true;i++;continue;}if(c==='/'&&next==='*'){block=true;i++;continue;}
  if(c==='"'||c==="'"||c==='`'){quote=c;continue;}
  if(c==='{')depth++;else if(c==='}'&&--depth===0)return source.slice(start,i+1);
 }throw Error('Unclosed '+name);
}
function fixture90x225(){
 const nodes=[],edges=[],seen=new Set();
 const add=(a,b,w)=>{const key=a<b?a+'|'+b:b+'|'+a;if(a===b||seen.has(key))return;seen.add(key);edges.push({source:'m'+a,target:'m'+b,effective_w:w,state:'active'});};
 for(let group=0;group<6;group++)for(let i=0;i<15;i++){
  const angle=group*Math.PI/3-Math.PI/2,core=group===0?0:150;
  const cx=Math.cos(angle)*core,cy=Math.sin(angle)*core,local=i*2.399963;
  nodes.push({id:'m'+nodes.length,label:`记忆${group}-${i}`,kind:'episode',tags:['记忆簇'+group],recalls:i===0?86-group*8:(i*7+group)%65,
   state:'active',x:cx+(i?Math.cos(local)*45:0),y:cy+(i?Math.sin(local)*36:0)});
 }
 for(let g=0;g<6;g++)for(let i=1;i<15;i++){add(g*15,g*15+i,.3+(i%7)*.09);if(i>1)add(g*15+i-1,g*15+i,.2+(i%6)*.08);}
 for(let g=1;g<6;g++)add(0,g*15,.95-g*.025);
 for(let a=0;a<90&&edges.length<225;a++)for(let b=a+1;b<90&&edges.length<225;b++)if(Math.floor(a/15)!==Math.floor(b/15))add(a,b,.17+((a+b)%6)*.035);
 assert.equal(nodes.length,90);assert.equal(edges.length,225);return{nodes,edges};
}
function strictContext(){
 const operations=[],curves=[],stack=[];let move=null;
 const record=(name,args)=>{for(const x of args)assert.ok(Number.isFinite(x),`${name} non-finite coordinate ${x}`);operations.push([name,...args]);};
 const ctx={globalAlpha:1,fillStyle:'',strokeStyle:'',lineWidth:1,
  save(){stack.push([this.globalAlpha,this.fillStyle,this.strokeStyle,this.lineWidth]);operations.push(['save']);},
  restore(){const p=stack.pop();assert.ok(p,'balanced context');[this.globalAlpha,this.fillStyle,this.strokeStyle,this.lineWidth]=p;operations.push(['restore']);},
  beginPath(){operations.push(['begin']);},moveTo(...p){record('move',p);move=p;},lineTo(...p){record('line',p);},
  bezierCurveTo(...p){record('curve',p);curves.push({start:move?.slice(),end:p.slice(-2)});},
  stroke(){operations.push(['stroke',this.strokeStyle,this.lineWidth]);},fill(){operations.push(['fill',typeof this.fillStyle==='string'?this.fillStyle:'gradient']);},
  fillRect(...p){record('rect',p);},arc(...p){record('arc',p);assert.ok(p[2]>=0);},translate(...p){record('translate',p);},rotate(...p){record('rotate',p);},
  setLineDash(p){record('dash',p);},measureText(t){return{width:String(t).length*8};},fillText(...p){operations.push(['text',...p]);},
  createRadialGradient(...p){record('gradient',p);return{addColorStop(offset,color){assert.ok(Number.isFinite(offset));operations.push(['stop',offset,color]);}};},
 };
 return{ctx,operations,curves,stack};
}
function viewOf(graph){
 const degree=new Map(graph.nodes.map(n=>[n.id,0]));for(const e of graph.edges){degree.set(e.source,degree.get(e.source)+1);degree.set(e.target,degree.get(e.target)+1);}
 const view={W:1000,H:800,light:false,time:.5,zoom:1,flatMix:0,paused:false,selected:null,hover:null,...graph,
  visibleSet:new Set(graph.nodes.map(n=>n.id)),active:new Map(),lit:new Map(),result:null,graphScale:Math.max(90,Math.sqrt(graph.nodes.length)*23),
  categories:Array.from({length:6},(_,i)=>({label:'记忆簇'+i})),
  projectNode:n=>({x:n.x+500,y:n.y+400,depth:0}),
  projectLocal:p=>({x:p.x+500,y:400-p.y,depth:0}),
  displayPosition:n=>n,nodeDepth:()=>0,
  nodeMetrics:n=>({hub:degree.get(n.id)>=10,radius:graph.nodes.length<=12?4.5:degree.get(n.id)>=10?4.8:2.2,alpha:1}),
 };return view;
}
function frozenGraph(value){Object.freeze(value.nodes);Object.freeze(value.edges);for(const n of value.nodes){Object.freeze(n.tags);Object.freeze(n);}for(const e of value.edges)Object.freeze(e);return Object.freeze(value);}

test('all nine approved drawing/style blocks are literal source copies with locked SHA-256',()=>{
 const sha=source=>createHash('sha256').update(source).digest('hex');
 for(const[name,hash]of Object.entries(FUNCTION_HASHES))assert.equal(sha(functionBlock(painterSource,name)),hash,name);
 const source=readFileSync(new URL('../fixtures/approved-neural-atlas-demo.source.txt',import.meta.url));
 assert.equal(source.length,29023);assert.equal(sha(source),LOCKED_SOURCE_SHA);
 for(const name of Object.keys(FUNCTION_HASHES))assert.equal(functionBlock(painterSource,name),functionBlock(source.toString('utf8'),name),name+' is byte-for-byte original');
});

test('0/1/2 real memories create no invented edges and all drawn coordinates remain finite',()=>{
 for(const count of[0,1,2]){
  const graph={nodes:Array.from({length:count},(_,i)=>({id:'s'+i,x:i*60,y:0,recalls:0,tags:[]})),edges:count===2?[{source:'s0',target:'s1',effective_w:.8}]:[]};
  const painter=new ApprovedAtlasPainter(),view=viewOf(graph),{ctx,operations,curves,stack}=strictContext(),before=JSON.stringify(graph);
  painter.setGraph(graph.nodes,graph.edges);const result=painter.paint(ctx,view);painter.drawGuide(ctx,{...view,flatMix:1});
  assert.equal(result.visibleFiberEdges,graph.edges.length);assert.ok(result.particleCount<=18000);assert.equal(stack.length,0);assert.equal(JSON.stringify(graph),before);
  if(!count){assert.equal(result.particleCount,0);assert.equal(operations.filter(o=>['rect','arc','curve'].includes(o[0])).length,0);}
  if(count<2)assert.equal(curves.length,0);
  if(count===2)for(const curve of curves){assert.deepEqual(curve.start,[500,400]);assert.deepEqual(curve.end,[560,400]);}
  painter.dispose();assert.equal(painter.particleCount,0);
 }
});

test('90 nodes /225 actual edges retain identity, original950/38 clouds and budget in both themes/modes',()=>{
 const graph=frozenGraph(fixture90x225()),before=JSON.stringify(graph),painter=new ApprovedAtlasPainter(),view=viewOf(graph);
 painter.setGraph(graph.nodes,graph.edges);
 for(const flatMix of[0,.5,1])for(const light of[false,true]){
  const{ctx,operations,curves,stack}=strictContext();Object.assign(view,{flatMix,light});const result=painter.paint(ctx,view);
  assert.equal(result.visibleFiberEdges,225);assert.ok(result.particleCount>0&&result.particleCount<=18000);assert.equal(result.cloudParticleCount,8892);
  assert.ok(curves.length>=225);assert.equal(stack.length,0);assert.equal(JSON.stringify(graph),before);
  const actualPairs=new Set(graph.edges.map(e=>{const a=view.projectNode(graph.nodes.find(n=>n.id===e.source)),b=view.projectNode(graph.nodes.find(n=>n.id===e.target));return JSON.stringify([[a.x,a.y],[b.x,b.y]]);}));
  for(const c of curves)assert.ok(actualPairs.has(JSON.stringify([c.start,c.end])),'Every rendered strand anchors a real edge');
  assert.equal(operations.filter(o=>o[0]==='text').length,0,'Host owns node labels');
 }
 painter.dispose();
});

test('visibility filters actual endpoints and reused painter clears a newly loaded graph',()=>{
 const graph=fixture90x225(),painter=new ApprovedAtlasPainter(),view=viewOf(graph);view.visibleSet.delete('m0');
 const{ctx}=strictContext();const result=painter.paint(ctx,view);
 assert.equal(result.visibleFiberEdges,graph.edges.filter(e=>e.source!=='m0'&&e.target!=='m0').length);
 const empty={nodes:[],edges:[]};assert.equal(painter.paint(ctx,viewOf(empty)).particleCount,0);assert.equal(painter.visibleFiberEdges,0);
 painter.dispose();
});

test('same supplied animation time reproduces the exact approved draw operations',()=>{
 const graph=fixture90x225(),view=viewOf(graph),painter=new ApprovedAtlasPainter();view.paused=true;
 const first=strictContext(),second=strictContext();painter.paint(first.ctx,view);painter.paint(second.ctx,view);
 assert.deepEqual(second.operations,first.operations);view.time+=1;const next=strictContext();painter.paint(next.ctx,view);assert.notDeepEqual(next.operations,first.operations);
 painter.dispose();
});

test('explicit pulses require an actual newly observed result trail and matching lit edge',()=>{
 const graph={nodes:[{id:'a',x:0,y:0,recalls:1,tags:[]},{id:'b',x:80,y:0,recalls:2,tags:[]}],edges:[{source:'a',target:'b',effective_w:.8}]};
 const painter=new ApprovedAtlasPainter(),view=viewOf(graph),pulseGlows=ops=>ops.filter(o=>o[0]==='gradient'&&o[6]===13).length;
 const plain=strictContext();view.lit.set('a|b',.8);painter.paint(plain.ctx,view);assert.equal(pulseGlows(plain.operations),0);
 const foreign=strictContext();view.result={trail:[['missing','b',.8,1]]};painter.paint(foreign.ctx,view);assert.equal(pulseGlows(foreign.operations),0);
 const real=strictContext();view.result={trail:[['a','b',.8,1]]};painter.paint(real.ctx,view);assert.equal(pulseGlows(real.operations),1);
 view.time+=5;const expired=strictContext();painter.paint(expired.ctx,view);assert.equal(pulseGlows(expired.operations),0);
 view.result={trail:[['a','b',.8,1]]};view.lit.clear();const unlit=strictContext();painter.paint(unlit.ctx,view);assert.equal(pulseGlows(unlit.operations),0);
 painter.dispose();
});
