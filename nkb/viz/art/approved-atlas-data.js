/* Approved demo layout, extracted verbatim. Only real-data indexing and world
 * scale conversion live outside the original function. No graph records mutate.
 * Source SHA256 dd31e23f5834b83bdf0c1b881bf2302852747d927834b326a9014fc2b9740090.
 */
import {recallActivity} from './synapse-dynamics.js';
function flatPosition(n){
    const g=n.group, local=n.id%15;
    const angle=-Math.PI*.5+g*Math.PI/3+(local===0?0:(local-7.5)*.048);
    const radius=.135+Math.pow(1-n.freq/110,.85)*.78+(local===0?-.035:0);
    return [Math.cos(angle)*radius,Math.sin(angle)*radius,0];
  }

function groupOf(n){return n.category||(Array.isArray(n.tags)?n.tags.filter(t=>typeof t==='string').slice().sort()[0]:null)||n.kind||'未分类';}
const APPROVED_GROUP_ORDER=['日常与陪伴','创作与灵感','计划与成长','情绪与感受','偏好与习惯','远方与回忆'];
export function approvedCategoryKeys(nodes=[]){const keys=[...new Set(nodes.map(groupOf))];return keys.sort((a,b)=>{const x=APPROVED_GROUP_ORDER.indexOf(a),y=APPROVED_GROUP_ORDER.indexOf(b);return(x<0?6:x)-(y<0?6:y)||String(a).localeCompare(String(b));});}
export function approvedGravityTargets(nodes=[],edges=[]){
 const groups=new Map(),degrees=new Map(nodes.map(n=>[n.id,0])),stableIds=nodes.map(n=>n.id).sort((a,b)=>String(a).localeCompare(String(b)));
 if(nodes.length===1)return new Map([[nodes[0].id,{x:0,y:0}]]);
 for(const e of edges)if(degrees.has(e.source)&&degrees.has(e.target)&&e.source!==e.target){degrees.set(e.source,degrees.get(e.source)+1);degrees.set(e.target,degrees.get(e.target)+1);}
 for(const n of nodes){const g=groupOf(n);if(!groups.has(g))groups.set(g,[]);groups.get(g).push(n);}
 const keys=approvedCategoryKeys(nodes),out=new Map(),scale=Math.max(90,Math.sqrt(nodes.length)*23);
 keys.forEach((key,g)=>{const members=groups.get(key).slice().sort((a,b)=>degrees.get(b.id)-degrees.get(a.id)||String(a.id).localeCompare(String(b.id)));
 members.forEach((n,j)=>{const local=j===0?0:members.length<=2?7:1+(j-1)*13/(members.length-2);
 const adapted={group:nodes.length<=12?stableIds.indexOf(n.id)*6/nodes.length:g*6/Math.max(1,keys.length),id:nodes.length<=12?0:g*15+local,freq:recallActivity(n)*100};
 const p=flatPosition(adapted);out.set(n.id,{x:p[0]*scale,y:p[1]*scale});});});return out;
}
export {flatPosition as approvedFlatPosition};

// Original demo group anchors and original per-member position statements.
// Real category membership and stable IDs supply only the input indices/seeds.
const APPROVED_ANCHORS=[[-.06,.02,.16],[-.55,-.33,-.12],[.53,-.32,.04],[.47,.39,-.16],[-.49,.39,.06],[.02,-.64,-.2]];
function approvedMemberPosition(j,group,g,random){
      const a=j*2.399963+group*.6, r=.115+random()*.155;
      const p = j===0 ? g.pos.slice() : [g.pos[0]+Math.cos(a)*r,g.pos[1]+Math.sin(a)*r*.83,g.pos[2]+(random()-.5)*.34];
 return p;
}
export function approvedNebulaTargets(nodes=[],edges=[]){
 const grouped=new Map(),degree=new Map(nodes.map(n=>[n.id,0]));
 for(const e of edges)if(degree.has(e.source)&&degree.has(e.target)){degree.set(e.source,degree.get(e.source)+1);degree.set(e.target,degree.get(e.target)+1);}
 for(const n of nodes){const key=groupOf(n);if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(n);}
 const out=new Map(),scale=Math.max(90,Math.sqrt(nodes.length)*23);
 if(nodes.length===1)return new Map([[nodes[0].id,{x:0,y:0,z:0}]]);
 approvedCategoryKeys(nodes).forEach((key,group)=>{
  const members=grouped.get(key).slice().sort((a,b)=>degree.get(b.id)-degree.get(a.id)||String(a.id).localeCompare(String(b.id)));
  const anchor=APPROVED_ANCHORS[group%APPROVED_ANCHORS.length];
  members.forEach((n,j)=>{let seed=2166136261;for(const c of String(n.id))seed=Math.imul(seed^c.charCodeAt(0),16777619);const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};
   const p=approvedMemberPosition(j,group,{pos:anchor},random);out.set(n.id,{x:p[0]*scale,y:p[1]*scale,z:p[2]*scale});
  });
 });return out;
}
