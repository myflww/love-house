/* Exercise the actual independent policy component using inert DOM/local transport. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/retention-ui.js'),'utf8');
const plain=x=>JSON.parse(JSON.stringify(x));

class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.events={};this.disabled=false;this.open=false;this.checked=false;this.textContent='';this.value='';this.style={};const classes=new Set();this.classList={toggle:(n,on)=>on?classes.add(n):classes.delete(n),add:n=>classes.add(n),contains:n=>classes.has(n)};}
 append(...nodes){for(const node of nodes){this.children.push(node);if(node instanceof Element)node.parent=this;}}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 before(node){const list=this.parent.children;list.splice(list.indexOf(this),0,node);node.parent=this.parent;}
 setAttribute(name,value){this.attributes[name]=String(value);}
 addEventListener(name,fn){this.events[name]=fn;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 focus(){this.focused=true;}
 click(){if(!this.disabled)return this.onclick?.();}
}
const all=root=>[root,...root.children.flatMap(child=>child instanceof Element?all(child):[])];
async function flush(){await Promise.resolve();await Promise.resolve();await Promise.resolve();}
function policy(extra={}){return {settings:{mode:'adaptive',forgetting_pace:'balanced',usage_reinforcement:true},node_count:12540,
 states:{active:10000,fading:2200,dormant:340,forgotten:0},usage:{pending:3,available:true},count_eviction:false,
 automatic_deletion:false,node_limit:null,is_demo:false,storage:{engine:'json',bytes:3145728},...extra};}
function context({api,mode='serve',demo=false}={}){
 const body=new Element('body'),head=new Element('head'),settings=new Element('div'),organize=new Element('button');settings.id='settings';organize.id='organizeBtn';settings.append(organize);body.append(settings);
 const S={mode,isDemo:demo,libraryChanging:false,libraryId:'archive-a',libraryEpoch:2},MEMORY={busy:false},calls=[],messages=[],events=[];
 const get=id=>[...all(body),...all(head)].find(e=>e.id===id);
 const ctx={S,MEMORY,writeBusy:false,document:{body,head,getElementById:get,createTextNode:text=>({textContent:text})},
  el:(tag,cls,text)=>{const e=new Element(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;},
  libraryName:id=>id==='archive-a'?'鲸鱼娘':'另一份存档',updateMemoryButtons:()=>events.push('sync'),
  updateWriteState(){events.push('writes');ctx.updateMemoryButtons();},invalidateRecall:()=>events.push('invalidate'),
  api:async(...args)=>{calls.push(plain(args));return api?api(...args):policy();},toast:message=>messages.push(message),window:{}};
 vm.runInNewContext(source,ctx);
 async function open(){get('memoryRetentionBtn').click();await flush();}
 function edit(pace='gentle',usage=false){get('memoryForgettingPace').value=pace;get('memoryUsageReinforcement').checked=usage;get('memoryForgettingPace').onchange();}
 return {ctx,S,MEMORY,calls,messages,events,get,body,open,edit};
}

test('opening the rules only reads one explicit library and never invokes use, organize or model endpoints',async()=>{
 const c=context();assert.equal(c.calls.length,0);await c.open();
 assert.deepEqual(c.calls,[['retention',null,{libraryId:'archive-a'}]]);
 assert.equal(c.get('memoryRetentionDialog').open,true);
 assert.equal(c.get('memoryForgettingPace').value,'balanced');assert.equal(c.get('memoryUsageReinforcement').checked,true);
 assert.equal(c.get('saveMemoryRetention').disabled,true);assert.equal(c.get('memoryRetentionBtn').attributes['aria-expanded'],'true');
 assert(c.get('memoryRetentionCounts').textContent.includes('12540'));assert(c.get('memoryRetentionCounts').textContent.includes('3.0 MiB'));
 assert(!c.get('memoryRetentionCounts').textContent.includes('%'));assert(!c.events.includes('invalidate'));
 assert(c.get('memoryRetentionUsage').textContent.includes('3 条使用痕迹'));
});

test('three continuous paces and a reinforcement switch are the only editable fields; no deadline input exists',async()=>{
 const c=context();await c.open();const inputs=all(c.body).filter(e=>['INPUT','SELECT'].includes(e.tagName));
 assert.deepEqual(inputs.map(e=>e.id).sort(),['memoryForgettingPace','memoryUsageReinforcement']);
 const paces=c.get('memoryForgettingPace').children.filter(e=>e.tagName==='OPTION');assert.deepEqual(paces.map(e=>e.value),['gentle','balanced','fast']);
 const words=all(c.body).map(e=>e.textContent).join('\n');assert(words.includes('没有统一到期日'));assert(words.includes('不是存放期限'));assert(!/\b(?:7|30|200)\s*天/.test(words));
 c.edit();assert.equal(c.get('saveMemoryRetention').disabled,false);assert(c.get('memoryRetentionStatus').textContent.includes('尚未保存'));assert.equal(c.calls.length,1);
});

test('save fixes its request to the original library, coalesces clicks, and releases write guards after success',async()=>{
 let resolveSave;
 const c=context({api:(route,body)=>route==='retention/settings'?new Promise(resolve=>resolveSave=resolve):Promise.resolve(policy())});
 await c.open();c.edit('fast',false);const saving=c.get('saveMemoryRetention').click();
 assert.equal(c.ctx.writeBusy,true);assert.equal(c.MEMORY.busy,true);assert.equal(c.get('saveMemoryRetention').disabled,true);assert.equal(c.get('closeMemoryRetention').disabled,true);
 await c.get('saveMemoryRetention').onclick();assert.equal(c.calls.filter(x=>x[0]==='retention/settings').length,1);
 assert.deepEqual(c.calls[1],['retention/settings',{forgetting_pace:'fast',usage_reinforcement:false},{libraryId:'archive-a'}]);
 resolveSave(policy({settings:{mode:'adaptive',forgetting_pace:'fast',usage_reinforcement:false}}));await saving;
 assert.equal(c.ctx.writeBusy,false);assert.equal(c.MEMORY.busy,false);assert.equal(c.get('saveMemoryRetention').disabled,true);
 assert(c.get('memoryRetentionStatus').textContent.includes('已保存'));assert.equal(c.messages.length,1);
});

test('a read failure shows retry information and never enables saving unknown rules',async()=>{
 const c=context({api:async()=>{throw Error('请求暂时限流，请稍后重试');}});await c.open();
 assert(c.get('memoryRetentionStatus').textContent.includes('限流'));assert.equal(c.get('memoryRetentionStatus').dataset.error,'true');
 assert.equal(c.get('saveMemoryRetention').disabled,true);assert.equal(c.get('reloadMemoryRetention').disabled,false);assert.equal(c.ctx.writeBusy,false);
 c.ctx.api=async()=>policy();await c.get('reloadMemoryRetention').click();assert.equal(c.get('memoryRetentionStatus').dataset.error,'false');assert.equal(c.get('memoryForgettingPace').disabled,false);
});

test('failed save preserves the draft, reports uncertainty honestly and clears all busy locks',async()=>{
 const c=context({api:async route=>{if(route==='retention/settings')throw Error('无法确认本地保存');return policy();}});await c.open();c.edit('gentle',false);
 await c.get('saveMemoryRetention').click();
 assert.equal(c.get('memoryForgettingPace').value,'gentle');assert.equal(c.get('memoryUsageReinforcement').checked,false);
 assert(c.get('memoryRetentionStatus').textContent.includes('未能确认保存结果'));assert(c.get('memoryRetentionStatus').textContent.includes('重新读取'));
 assert.equal(c.get('saveMemoryRetention').disabled,false);assert.equal(c.ctx.writeBusy,false);assert.equal(c.MEMORY.busy,false);assert.equal(c.messages.length,0);
});

test('switching libraries drops a late read response and cannot save settings into the new identity',async()=>{
 let resolveRead;const c=context({api:()=>new Promise(resolve=>resolveRead=resolve)});c.get('memoryRetentionBtn').click();
 c.S.libraryId='archive-b';c.S.libraryEpoch++;c.ctx.updateMemoryButtons();assert.equal(c.get('memoryRetentionDialog').open,false);
 resolveRead(policy());await flush();assert.equal(c.get('memoryRetentionCounts').textContent,'');
 c.edit();await c.get('saveMemoryRetention').onclick();assert.equal(c.calls.length,1);assert.equal(c.messages.length,0);
});

test('a switch before repaint prevents save; a switch during save never paints the old result into another library',async()=>{
 let resolveSave;
 const c=context({api:route=>route==='retention/settings'?new Promise(resolve=>resolveSave=resolve):Promise.resolve(policy())});await c.open();c.edit();
 c.S.libraryEpoch++;await c.get('saveMemoryRetention').onclick();assert.equal(c.calls.length,1);
 c.S.libraryEpoch--;const saving=c.get('saveMemoryRetention').click();c.S.libraryId='archive-b';c.S.libraryEpoch++;c.ctx.updateMemoryButtons();
 resolveSave(policy({settings:{mode:'adaptive',forgetting_pace:'gentle',usage_reinforcement:false}}));await saving;
 assert.equal(c.get('memoryRetentionDialog').open,false);assert.equal(c.messages.length,0);assert.equal(c.ctx.writeBusy,false);assert.equal(c.MEMORY.busy,false);
});

test('overlapping refresh replies and closing a dialog cannot revive stale policy data',async()=>{
 const pending=[];const c=context({api:()=>new Promise(resolve=>pending.push(resolve))});c.get('memoryRetentionBtn').click();
 c.ctx.window.LoveHouseRetention.refresh();assert.equal(pending.length,2);
 pending[1](policy({settings:{mode:'adaptive',forgetting_pace:'gentle',usage_reinforcement:false}}));await flush();
 pending[0](policy());await flush();assert.equal(c.get('memoryForgettingPace').value,'gentle');
 c.ctx.window.LoveHouseRetention.refresh();c.get('closeMemoryRetention').click();pending[2](policy());await flush();
 assert.equal(c.get('memoryRetentionDialog').open,false);assert.equal(c.get('memoryRetentionBtn').attributes['aria-expanded'],'false');assert.equal(c.messages.length,0);
});

test('demo rules are viewable but read-only and offline/busy modes never call management APIs',async()=>{
 const demo=context({demo:true,api:async()=>policy({is_demo:true,count_eviction:true,automatic_deletion:true,node_limit:10000})});await demo.open();
 assert.equal(demo.calls.length,1);assert(demo.get('memoryRetentionLibrary').textContent.includes('只读'));
 assert(all(demo.body).some(e=>e.textContent==='个人存档采用持续归档；当前是独立示例，只读展示。'));
 assert.equal(demo.get('memoryForgettingPace').disabled,true);assert.equal(demo.get('memoryUsageReinforcement').disabled,true);
 demo.edit();await demo.get('saveMemoryRetention').onclick();assert.equal(demo.calls.length,1);
 for(const mutate of [c=>c.S.mode='embedded',c=>c.S.libraryChanging=true,c=>c.MEMORY.busy=true,c=>c.ctx.writeBusy=true]){
  const c=context();mutate(c);c.ctx.updateMemoryButtons();c.get('memoryRetentionBtn').onclick();await flush();assert.equal(c.calls.length,0);
 }
});

test('malformed or count-evicting backend policy is not silently labeled as safe or made editable',async()=>{
 for(const extra of [{count_eviction:true},{automatic_deletion:true},{node_limit:10000},{settings:{mode:'fixed',forgetting_pace:'balanced',usage_reinforcement:true}}]){
  const c=context({api:async()=>policy(extra)});await c.open();assert(c.get('memoryRetentionStatus').textContent.includes('未提供完整'));
  assert.equal(c.get('saveMemoryRetention').disabled,true);assert.equal(c.get('memoryForgettingPace').disabled,true);
 }
});

function detailContext(extra={}){
 const node={id:'synthetic',label:'合成记忆',kind:'episode',tags:[],text:'完整合成原文',meta:{},created:1,reinforced:1,
             recalls:0,connection_count:0,degree:0,half_life:60,recovery_days_left:null,state:'dormant',recoverable:true,...extra};
 const detail=new Element('div'),label=new Element('p'),foot=new Element('p'),elements={'#detail':detail,'#inspectorLabel':label,'#detailFoot':foot};
 const make=(tag,cls,text)=>{const e=new Element(tag);e.className=cls;if(text!==undefined)e.textContent=text;return e;};
 const ctx={S:{selected:node.id,byId:new Map([[node.id,node]]),mode:'serve',days:0,adj:new Map(),config:{recovery_days:200}},
  MEMORY:{busy:false},$:key=>elements[key],el:make,state:n=>n.state,stateLabel:()=> '休眠',anchor:()=>false,sal:()=>.3,num:v=>Number(v||0),
  memoryIsEnabled:()=>true,canWrite:()=>true,writeBlockedReason:()=>'',date:v=>'DATE-'+v,
  fact:(box,key,value)=>box.append(make('dt','',key),make('dd','',value)),renderContextSnippets(){},api(){throw Error('Viewing details is not memory use');}};
 const html=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/index.html'),'utf8'),start=html.indexOf('function renderDetail()'),end=html.indexOf('\nfunction ',start+10);
 assert(start>=0&&end>start);vm.runInNewContext(html.slice(start,end)+';renderDetail();',ctx);
 const facts=all(detail).find(e=>e.className==='facts'),pairs=[];for(let i=0;i<facts.children.length;i+=2)pairs.push([facts.children[i].textContent,facts.children[i+1].textContent]);
 return {detail,pairs,node};
}

test('adaptive details show continuous fading and recoverable original text without the legacy half-life/deadline',()=>{
 const c=detailContext({retention_mode:'adaptive',strength_model:'practice_power_law_approximation/v1'});
 assert(c.pairs.some(([k,v])=>k==='淡化规律'&&v==='自适应淡化，无统一到期日'));
 assert(c.pairs.some(([k,v])=>k==='休眠记忆'&&v==='原文保留，可按线索回忆'));
 assert(!c.pairs.some(([k])=>k==='半衰期'||k==='恢复窗口'));
});

test('legacy CLI/offline examples retain their actual half-life and recovery-window details',()=>{
 const c=detailContext({retention_mode:'legacy'});
 assert(c.pairs.some(([k,v])=>k==='半衰期'&&v==='60 天'));
 assert(c.pairs.some(([k,v])=>k==='恢复窗口'&&v==='恢复窗口 200 天'));
 assert(!c.pairs.some(([k])=>k==='淡化规律'));
});

test('an unavailable adaptive fact explains validity rather than claiming an expired calendar recovery window',()=>{
 const c=detailContext({retention_mode:'adaptive',recoverable:false});
 const reinforce=all(c.detail).find(e=>e.textContent==='强化记忆');assert.equal(reinforce.disabled,true);
 assert(reinforce.title.includes('失效'));assert(!reinforce.title.includes('恢复窗口'));
 assert(c.pairs.some(([k,v])=>k==='休眠记忆'&&v.includes('停用、失效或尚未发生')));
});

test('unavailable usage bookkeeping is not described as a known empty queue',async()=>{const c=context({api:async()=>policy({usage:{pending:0,available:false}})});await c.open();assert(c.get('memoryRetentionUsage').textContent.includes('暂不可读取'));assert(!c.get('memoryRetentionUsage').textContent.includes('没有待'));});
