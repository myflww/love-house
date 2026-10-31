/* Execute the shipped read-only experience UI with an inert DOM and transport. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/experience-ui.js'),'utf8');
const plain=x=>JSON.parse(JSON.stringify(x));
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.events={};this.style={};this.disabled=false;this.hidden=false;this.open=false;this.textContent='';const classes=new Set();this.classList={add:name=>classes.add(name),contains:name=>classes.has(name)};}
 append(...nodes){for(const node of nodes){this.children.push(node);if(node instanceof Element)node.parentElement=this;}}
 before(node){const list=this.parentElement.children;list.splice(list.indexOf(this),0,node);node.parentElement=this.parentElement;}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 setAttribute(name,value){this.attributes[name]=String(value);}
 addEventListener(name,fn){this.events[name]=fn;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 querySelectorAll(selector){return selector==='button'?all(this).filter(e=>e.tagName==='BUTTON'):[];}
 click(){if(!this.disabled)return this.onclick?.();}
 set innerHTML(value){throw Error('Untrusted memory must never become HTML');}
}
const all=root=>[root,...(root.children||[]).flatMap(child=>child&&typeof child==='object'?all(child):[])];
const words=root=>all(root).map(e=>e.textContent||'').join('\n');
const ref=(quote,role='tool',extra={})=>({id:'source-'+role,role,quote,basis:role==='assistant'?'agent_self_report':role==='user'?'user_statement':'tool_report',...extra});
function entry(extra={}){return {id:'episode-one',label:'legacy technical label',event_at:1700000000,recorded_at:1700001000,
 episode:{schema:'love-house-experience/v1',library_id:'fish-a',what:ref('在网页里找到了一份海边天气资料。'),reason:null,outcome:null,participants:[],places:[],status:'unknown',...extra}};}
function packet(extra={}){return {agent_id:'fish-a',entries:[entry()],total:1,more:false,source_records:42,unavailable_experiences:0,read_only:true,will_call_model:false,...extra};}
async function flush(){await Promise.resolve();await Promise.resolve();await Promise.resolve();}
function context({api,demo=false,mode='serve'}={}){
 const body=new Element('body'),head=new Element('head'),library=new Element('aside'),newLibrary=new Element('button'),organizer=new Element('aside'),actions=new Element('div'),preview=new Element('button');library.id='libraryPanel';newLibrary.id='newLibraryBtn';preview.id='previewOrganizer';library.append(newLibrary);actions.append(preview);organizer.append(actions);body.append(library,organizer);
 const S={mode,isDemo:demo,libraryChanging:false,libraryId:'fish-a',libraryEpoch:4,memoryDisplay:'memories',byId:new Map([['episode-one',{}],['source-tool',{}]])},MEMORY={busy:false},calls=[],selections=[],panels=[],messages=[],presentation=[];
 const get=id=>[...all(body),...all(head)].find(e=>e.id===id);
 const ctx={S,MEMORY,writeBusy:false,Date,document:{body,head,getElementById:get,createTextNode:text=>({textContent:text})},
  el:(tag,cls,text)=>{const e=new Element(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;},
  libraryName:id=>id==='fish-a'?'鲸鱼娘':'另一份存档',updateMemoryButtons(){},
  api:async(...args)=>{calls.push(plain(args));return api?api(...args):packet();},
  select:(...args)=>selections.push(args),setPanelOpen:(...args)=>panels.push(args),toast:(...args)=>messages.push(args),window:{LoveHouseMemoryPresentation:{set(value){presentation.push(value);S.memoryDisplay=value?'all':'memories';}}}};
 vm.runInNewContext(source,ctx);
 async function open(){get('experienceLibraryBtn').click();await flush();}
 return {ctx,S,MEMORY,get,body,head,calls,selections,panels,messages,presentation,open};
}

test('opens one explicit archive read-only and displays actual event with unknown reason/result',async()=>{
 const c=context();await c.open();assert.deepEqual(c.calls,[['experiences?limit=30',null,{libraryId:'fish-a'}]]);
 assert.equal(c.get('experienceTimelineDialog').open,true);assert.equal(c.get('experienceLibraryBtn').attributes['aria-expanded'],'true');
 const text=words(c.get('experienceTimelineList'));assert(text.includes('在网页里找到了一份海边天气资料。'));
 assert(text.includes('未提供明确原因'));assert(text.includes('未提供可核对的结果'));assert(!text.includes('legacy technical label'));
 assert.equal(c.get('experienceTimelineStatus').dataset.error,'false');assert.equal(c.selections.length,0);
});

test('counterparty statements and assistant-reported outcomes never look like verified Agent success',async()=>{
 const ep=entry({what:ref('我今天去海边看了日落。','user',{basis:'platform_participant_statement'}),reason:ref('我想看看海边的景色。','user',{basis:'platform_participant_statement'}),outcome:ref('我说自己做完了。','assistant'),status:'reported'});
 const c=context({api:async()=>packet({entries:[ep]})});await c.open();const text=words(c.get('experienceTimelineList'));
 assert(text.includes('听到的事情'));assert(text.includes('对方原话'));assert(text.includes('助手自述'));assert(text.includes('结果待核对'));
 assert(!text.includes('来源报告成功'));assert(!text.includes('主人原话'));
});

test('unknown historical time stays unknown while record time is separately labeled',async()=>{
 const ep=entry();ep.event_at=null;const c=context({api:async()=>packet({entries:[ep]})});await c.open();const text=words(c.get('experienceTimelineList'));
 assert(text.includes('发生时间未提供'));assert(text.includes('存入：'));assert(!text.includes('刚刚'));
});

test('empty organized list explains raw material instead of pretending there is no memory',async()=>{
 const c=context({api:async()=>packet({entries:[],total:0,source_records:12500})});await c.open();
 assert(words(c.get('experienceTimelineList')).includes('原始资料 12500 条已保存，经历尚待整理'));
 assert(!words(c.body).includes('没有记忆'));assert.equal(c.calls.length,1);
});

test('untrusted quote markup is displayed through text, never executed or inserted as HTML',async()=>{
 const payload='<img src=x onerror=STEAL_MEMORY()>真实原话';const ep=entry({what:ref(payload)});
 const c=context({api:async()=>packet({entries:[ep]})});await c.open();assert(words(c.get('experienceTimelineList')).includes(payload));
 assert.equal(c.ctx.STEAL_MEMORY,undefined);assert.equal(c.calls.length,1);
});

test('a mismatched identity or unproven read-only response fails closed',async()=>{
 for(const extra of [{agent_id:'other'}, {read_only:false},{will_call_model:true}]){
  const c=context({api:async()=>packet({...extra,entries:[entry({what:ref('DO_NOT_LEAK')})]})});await c.open();
  assert.equal(c.get('experienceTimelineStatus').dataset.error,'true');assert(!words(c.get('experienceTimelineList')).includes('DO_NOT_LEAK'));
 }
});

test('switching archive discards an in-flight reply and clears already visible old memory',async()=>{
 let resolve;const c=context({api:()=>new Promise(r=>resolve=r)});await c.open();c.S.libraryId='other';c.S.libraryEpoch++;
 c.ctx.updateMemoryButtons();resolve(packet());await flush();assert.equal(c.get('experienceTimelineDialog').open,false);assert.equal(c.get('experienceTimelineList').children.length,0);
 assert.deepEqual(c.calls,[['experiences?limit=30',null,{libraryId:'fish-a'}]]);
});

test('overlapping refresh and close ignore stale responses without leaving hidden old quotes',async()=>{
 const waiting=[];const c=context({api:()=>new Promise(r=>waiting.push(r))});await c.open();c.ctx.window.LoveHouseExperiences.refresh();
 waiting[1](packet({entries:[entry({what:ref('newest material')})]}));await flush();
 waiting[0](packet({entries:[entry({what:ref('stale material')})]}));await flush();assert(words(c.get('experienceTimelineList')).includes('newest material'));assert(!words(c.get('experienceTimelineList')).includes('stale material'));
 c.ctx.window.LoveHouseExperiences.refresh();c.get('closeExperienceTimeline').click();waiting[2](packet());await flush();assert.equal(c.get('experienceTimelineList').children.length,0);
});

test('more grows only the view budget to one hundred; all extra records remain in the archive',async()=>{
 const c=context({api:async()=>packet({more:true,total:250})});await c.open();
 for(let n=0;n<3;n++){await c.get('moreExperienceTimeline').click();await flush();}
 assert.deepEqual(c.calls.map(c=>c[0]),['experiences?limit=30','experiences?limit=60','experiences?limit=90','experiences?limit=100']);
 assert.equal(c.get('moreExperienceTimeline').hidden,true);assert(c.get('experienceTimelineStatus').textContent.includes('其余仍在存档'));
 c.get('experienceAllNodesBtn').click();assert.equal(c.panels.at(-1)[0],'sidebar');assert.equal(c.calls.length,4);
});

test('locate and evidence open the same verified memory with distinct camera behavior',async()=>{
 const c=context();await c.open();c.get('locateExperience-0').click();assert.deepEqual(c.selections,[['episode-one',true]]);
 await c.open();c.get('evidenceExperience-0').click();assert.deepEqual(c.selections.at(-1),['source-tool',false]);assert.equal(c.get('experienceTimelineDialog').open,false);assert.deepEqual(c.presentation,[true]);
 await c.open();c.S.libraryEpoch++;c.get('locateExperience-0').click();assert.equal(c.selections.length,2);
});

test('organize and source navigation never run a model, and the demo stays read-only',async()=>{
 const c=context();await c.open();c.get('continueExperienceOrganization').click();assert.equal(c.panels.at(-1)[0],'organizerPanel');assert.equal(c.calls.length,1);
 await c.open();let sources=0;c.ctx.window.LoveHouseSources={open(){sources++;}};c.get('experienceSourcesBtn').click();assert.equal(sources,1);assert.equal(c.calls.length,2);
 const demo=context({demo:true});await demo.open();assert(demo.get('experienceTimelineIdentity').textContent.includes('独立示例'));assert.equal(demo.get('continueExperienceOrganization').disabled,true);
 demo.get('continueExperienceOrganization').click();assert.equal(demo.panels.length,0);assert.equal(demo.calls.length,1);
});

test('network failure and rejected entries remain explicit, without false empty-memory claims',async()=>{
 const c=context({api:async()=>{throw Error('fake unavailable');}});await c.open();assert(c.get('experienceTimelineStatus').textContent.includes('暂时无法读取'));assert(!c.get('experienceTimelineStatus').textContent.includes('0 条'));
 const invalid=entry({library_id:'other'});const other=context({api:async()=>packet({entries:[invalid],unavailable_experiences:2})});await other.open();assert(other.get('experienceTimelineStatus').textContent.includes('3 条经历的依据暂不可用'));
 const embedded=context({mode:'embedded'});await embedded.open();assert.equal(embedded.calls.length,0);
});

test('showing raw tool evidence only changes presentation, never stored memory or model calls',async()=>{
 const c=context();await c.open();const toggle=c.get('experienceShowRawTools');assert.equal(toggle.checked,false);toggle.checked=true;toggle.onchange();assert.equal(c.S.memoryDisplay,'all');assert.deepEqual(c.presentation,[true]);assert.equal(c.calls.length,1);toggle.checked=false;toggle.onchange();assert.equal(c.S.memoryDisplay,'memories');assert.equal(c.calls.length,1);
});
