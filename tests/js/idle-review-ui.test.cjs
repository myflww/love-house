/* Execute the shipped disclosure and its library-scoped handlers without a browser. */
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/idle-review-ui.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/index.html'),'utf8'),apiSource=html.split('\n').find(line=>line.startsWith('async function api('));
const copy=x=>JSON.parse(JSON.stringify(x)),all=n=>[n,...(n.children||[]).flatMap(all)],words=n=>all(n).map(n=>n.textContent||'').join('\n');
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.events={};this.attrs={};this.dataset={};this.className='';this.id='';this._text='';this.open=false;this.hidden=false;this._disabled=false;this.checked=false;this.value='';this.classList={add:(...names)=>{this.className=[this.className,...names].filter(Boolean).join(' ');}};}
 get disabled(){return this._disabled;}
 set disabled(value){this._disabled=!!value;if(value&&this.ownerDocument?.activeElement===this)this.ownerDocument.activeElement=this.ownerDocument.body;}
 get isConnected(){let n=this;while(n.parentElement)n=n.parentElement;return !!this.ownerDocument&&(n===this.ownerDocument.body||n===this.ownerDocument.head);}
 getClientRects(){return this.hidden||!this.isConnected?[]:[{}];}
 get textContent(){return this._text;}
 set textContent(value){this._text=String(value);this.children=[];}
 remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
 append(...nodes){for(let n of nodes){if(typeof n==='string')n={textContent:n};n.remove?.();n.parentElement=this;for(const child of all(n))child.ownerDocument=this.ownerDocument;this.children.push(n);}}
 after(...nodes){const p=this.parentElement;if(!p)return;let at=p.children.indexOf(this)+1;for(const n of nodes){n.remove?.();n.parentElement=p;for(const child of all(n))child.ownerDocument=p.ownerDocument;p.children.splice(at++,0,n);}}
 replaceChildren(...nodes){for(const n of this.children)n.parentElement=null;this.children=[];this._text='';this.append(...nodes);}
 setAttribute(key,value){this.attrs[key]=String(value);}
 addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
 async emit(type,event={}){for(const fn of this.events[type]||[])await fn(event);}
 click(){if(!this.disabled){this.focus();return this.onclick?.();}}
 focus(){if(this.disabled)return;this.focused=true;if(this.ownerDocument){this.ownerDocument.activeElement=this;this.ownerDocument.dispatch('focusin',{target:this});}}
 querySelectorAll(selector){return all(this).slice(1).filter(n=>n.tagName&&selector.split(',').some(p=>p.startsWith('.')?n.className.split(' ').includes(p.slice(1)):n.tagName===p.toUpperCase()));}
 set innerHTML(_value){throw Error('source data must be text');}
}
const flush=async()=>{for(let n=0;n<20;n++)await Promise.resolve();};
function proposal(extra={}){return {id:'reflection-a',type:'reflection',title:'先核对再回答',text:'不同来源有冲突时先询问。',evidence:[{id:'source-a',role:'user',quote:'请先确认这是哪个窗口'}],status:'pending',can_accept:false,legacy:true,effectiveness:'unverified',is_user_fact:false,is_real_experience:false,automatic_activation:false,replay:{effectiveness:'unverified',independent_evaluation:false,checks:{evidence_current:true}},...extra};}
function dto(extra={}){return {schema:'love-house-idle-review/v1',library_id:'a',profile:{enabled:false,idle_seconds:300,batch_size:6},mode:'organization',directory_entries:[{id:'source-a',label:'原文目录标题',roles:['user','assistant'],read_tool:'memory_read',read_arguments:{memory_id:'source-a'}}],counts:{eligible:5,pending:3,processed:2,proposals:1},running:false,last_error:null,read_only:true,model_called:false,proposals:[proposal()],...extra};}
function environment({transport,demo=false,management=true,realApi=false}={}){
 const body=new Element('body'),head=new Element('head'),panel=new Element('aside'),settings=new Element('details');panel.id='organizerPanel';settings.id='organizerSettings';panel.append(settings);body.append(panel);
 const get=id=>[...all(body),...all(head)].find(n=>n.id===id),S={libraryId:'a',libraryEpoch:1,mode:'serve',libraryChanging:false,isDemo:demo,byId:new Map([['source-a',{id:'source-a',label:'当前库来源'}]])};
 const calls=[],selections=[],context={S,MEMORY:{busy:false},writeBusy:false,document:{body,head,getElementById:get,createTextNode:text=>({textContent:String(text)})},window:{},el:(tag,cls,text)=>{const n=new Element(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;},libraryName:id=>'记忆库 '+id,canManageMemory:()=>management&&!demo,updateMemoryButtons(){},updateWriteState(){context.updateMemoryButtons();},refreshOrganizer:async()=>null,setPanelOpen:(_id,open)=>{panel.hidden=!open;},select:(...args)=>selections.push(args),api:async(...args)=>{calls.push(copy(args));return transport?transport(...args):dto();}};
 const document=context.document;Object.assign(document,{activeElement:body,events:{},addEventListener(type,fn){(this.events[type]??=[]).push(fn);},removeEventListener(type,fn){this.events[type]=(this.events[type]||[]).filter(listener=>listener!==fn);},dispatch(type,event){for(const listener of this.events[type]||[])listener(event);}});for(const n of [...all(body),...all(head)])n.ownerDocument=document;
 const network=[];context.safeStatusMessage=value=>String(value);context.fetch=async(url,options)=>{const method=options.method||'GET',body=options.body===undefined?undefined:JSON.parse(options.body);network.push({url,method,body,library:options.headers['X-NKB-Library']});return {ok:true,status:200,json:async()=>transport?transport(url.slice(5),body):dto()};};
 vm.createContext(context);if(realApi)vm.runInContext(apiSource,context);vm.runInContext(source,context);
 async function open(){get('idleReviewSection').open=true;await get('idleReviewSection').emit('toggle');await flush();}
 return {get,S,context,calls,network,selections,open,words:id=>words(get(id))};
}

test('one default-closed organizer disclosure has no second key, limits or automatic model invocation',async()=>{
 const e=environment();assert.equal(e.get('idleReviewSection').open,false);assert.equal(e.get('idleReviewSection').parentElement.id,'organizerPanel');assert.equal(e.calls.length,0);assert.equal(e.get('idleReviewAdvanced').open,false);
 await e.open();assert.deepEqual(e.calls,[['idle-review',null,{libraryId:'a'}]]);assert.equal(e.get('idleReviewEnabled').checked,false);assert(e.words('idleReviewCadence').includes('5 分钟'));assert(e.words('idleReviewCounts').includes('待建目录'));assert.equal(e.get('saveIdleReviewSettings').disabled,true);assert.equal(e.get('runIdleReview').disabled,false);
 assert.equal(all(e.get('idleReviewSection')).filter(n=>n.type==='password').length,0);assert(!all(e.get('idleReviewSection')).some(n=>/daily|budget|limit/i.test(n.id)));assert(e.words('idleReviewAdvanced').includes('连续分批索引'));
 await e.get('previewIdleReview').click();assert.deepEqual(e.calls[1],['idle-review/preview',{}, {libraryId:'a'}]);assert(e.words('idleReviewStatus').includes('未调用模型'));assert.equal(e.get('idleReviewEnabled').checked,false);
});

test('the real page api helper issues GET status without JSON null and explicit POST preview/run',async()=>{
 let queued=false;const e=environment({realApi:true,transport:async route=>{if(route==='idle-review/run'){queued=true;return {queued:true,status:'queued',library_id:'a'};}return dto({running:queued});}});await e.open();assert.deepEqual(e.network,[{url:'/api/idle-review',method:'GET',body:undefined,library:'a'}]);await e.get('previewIdleReview').click();assert.deepEqual(e.network[1],{url:'/api/idle-review/preview',method:'POST',body:{},library:'a'});await e.get('runIdleReview').click();assert.deepEqual(e.network[2],{url:'/api/idle-review/run',method:'POST',body:{},library:'a'});assert.deepEqual(e.network[3],{url:'/api/idle-review',method:'GET',body:undefined,library:'a'});assert.equal(e.get('idleReviewEnabled').checked,false);
});

test('enabling is an explicit save with library identity; editing blocks run and polling preserves drafts',async()=>{
 let saved;const e=environment({transport:async(route,body)=>{if(route.endsWith('/settings')){saved=body;return dto({profile:body});}return dto();}});await e.open();const enabled=e.get('idleReviewEnabled');enabled.checked=true;enabled.onchange();assert.equal(e.calls.length,1);assert.equal(e.get('runIdleReview').disabled,true);assert.equal(e.get('saveIdleReviewSettings').disabled,false);
 await e.context.refreshOrganizer();assert.equal(e.calls.length,1);assert.equal(enabled.checked,true);
 e.get('idleReviewIdleSeconds').value='600';e.get('idleReviewBatchSize').value='12';await e.get('saveIdleReviewSettings').click();assert.deepEqual(copy(saved),{enabled:true,idle_seconds:600,batch_size:12});assert.deepEqual(e.calls[1][2],{libraryId:'a'});assert(e.words('idleReviewStatus').includes('已保存'));assert.equal(e.get('runIdleReview').disabled,false);assert.equal(e.context.MEMORY.busy,false);
 e.get('idleReviewBatchSize').value='0';e.get('idleReviewBatchSize').oninput();await e.get('saveIdleReviewSettings').click();assert.equal(e.calls.length,2);assert.equal(e.get('idleReviewStatus').dataset.error,'true');
});

test('explicit run queues background work, then only reads status; automatic opt-in remains off',async()=>{
 let queued=false;const e=environment({transport:async(route)=>{if(route==='idle-review/run'){queued=true;return {library_id:'a',queued:true,status:'queued'};}return dto({running:queued});}});await e.open();await e.get('runIdleReview').click();assert.deepEqual(e.calls,[['idle-review',null,{libraryId:'a'}],['idle-review/run',{}, {libraryId:'a'}],['idle-review',null,{libraryId:'a'}]]);assert.equal(e.get('idleReviewEnabled').checked,false);assert.equal(e.get('runIdleReview').disabled,true);assert(e.words('idleReviewStatus').includes('原文目录维护'));
 await e.context.refreshOrganizer();assert.equal(e.calls.filter(c=>c[0]==='idle-review/run').length,1);assert.equal(e.calls.at(-1)[0],'idle-review');
});

test('reject is explicit and a busy receipt never claims success',async()=>{
 const e=environment({transport:async(route)=>route.includes('/reject')?{library_id:'a',proposal_id:'reflection-a',status:'busy'}:dto()});await e.open();await e.get('idleReview-reject-reflection-a').click();assert.equal(e.get('idleReviewStatus').dataset.error,'true');assert(e.words('idleReviewStatus').includes('已有目录任务'));assert(!e.words('idleReviewStatus').includes('已拒绝'));assert.equal(e.calls.length,2);
});

test('late responses after library switch, same-id epoch change or close cannot leak sources',async()=>{
 for(const change of [e=>{e.S.libraryId='b';e.S.libraryEpoch++;e.context.updateMemoryButtons();},e=>{e.S.libraryEpoch++;e.context.updateMemoryButtons();},async e=>{e.get('idleReviewSection').open=false;await e.get('idleReviewSection').emit('toggle');}]){let resolve;const e=environment({transport:()=>new Promise(r=>resolve=r)});await e.open();await change(e);resolve(dto());await flush();assert.equal(e.get('idleReviewProposals').children.length,0);assert.equal(e.get('idleReviewSection').open,false);assert.equal(e.get('runIdleReview').disabled,true);}
});

test('invalid library, type boundaries or unknown schema never expose proposals; demo and management gates forbid mutation',async()=>{
 for(const bad of [dto({library_id:'other'}),dto({schema:'unknown'}),dto({proposals:[proposal({type:'simulation',can_accept:true})]}),dto({proposals:[proposal({is_user_fact:true})]})]){const e=environment({transport:async()=>bad});await e.open();assert.equal(e.get('idleReviewStatus').dataset.error,'true');assert.equal(e.get('idleReviewProposals').children.length,0);assert.equal(e.get('runIdleReview').disabled,true);}
 for(const options of [{demo:true},{management:false}]){const e=environment(options);await e.open();assert.equal(e.get('idleReviewEnabled').disabled,true);assert.equal(e.get('runIdleReview').disabled,true);assert.equal(e.get('idleReview-reject-reflection-a').disabled,true);assert.equal(e.get('previewIdleReview').disabled,false);await e.get('runIdleReview').onclick();await e.get('idleReview-reject-reflection-a').onclick();assert.equal(e.calls.length,1);}
});

test('persistent failure and empty backlog remain honest, source deletion is visible rather than navigation',async()=>{
 const e=environment({transport:async()=>dto({last_error:{code:'provider_authentication',message:'请检查整理 API 的凭证'}})});await e.open();assert.equal(e.get('idleReviewStatus').dataset.error,'true');assert(e.words('idleReviewStatus').includes('请检查整理 API'));e.S.byId.clear();e.get('viewIdleReviewSource-reflection-a-source-a').click();assert.equal(e.selections.length,0);assert(e.words('idleReviewStatus').includes('已失效或未载入'));
 const empty=environment({transport:async()=>dto({proposals:[],counts:{eligible:0,pending:0,processed:0,proposals:0}})});await empty.open();assert(empty.words('idleReviewProposals').includes('没有旧版回顾记录'));assert.equal(empty.get('runIdleReview').disabled,false);
});

test('preview requires an actual read-only no-model receipt; unknown mutation receipts require a fresh preview',async()=>{
 const unproven=environment({transport:async(route)=>dto(route.endsWith('/preview')?{model_called:true}:{})});await unproven.open();await unproven.get('previewIdleReview').click();assert.equal(unproven.get('idleReviewStatus').dataset.error,'true');assert(unproven.words('idleReviewStatus').includes('目录状态与当前记忆库不一致'));assert.equal(unproven.get('idleReviewProposals').children.length,0);
 const mismatch=environment({transport:async(route)=>route.endsWith('/reject')?{library_id:'other',proposal_id:'reflection-a',status:'rejected'}:dto()});await mismatch.open();await mismatch.get('idleReview-reject-reflection-a').click();assert.equal(mismatch.get('idleReviewStatus').dataset.error,'true');assert(mismatch.words('idleReviewStatus').includes('操作未确认'));assert.equal(mismatch.get('runIdleReview').disabled,true);assert.equal(mismatch.calls.length,2);
});

test('proposal review preserves unsaved settings; pending writes are exclusive and late acknowledgements stay out of a new library',async()=>{
 let status='pending';const draft=environment({transport:async(route)=>{if(route.endsWith('/reject')){status='rejected';return {library_id:'a',proposal_id:'reflection-a',status};}return dto({proposals:[proposal({status})]});}});await draft.open();draft.get('idleReviewEnabled').checked=true;draft.get('idleReviewEnabled').onchange();await draft.get('idleReview-reject-reflection-a').click();assert.equal(draft.get('idleReviewEnabled').checked,true);assert.equal(draft.get('saveIdleReviewSettings').disabled,false);assert.equal(draft.get('runIdleReview').disabled,true);assert(draft.words('idleReviewStatus').includes('尚未保存'));assert.equal(draft.calls.filter(c=>c[0].endsWith('/settings')).length,0);
 let resolve;const late=environment({transport:async(route)=>route.endsWith('/reject')?new Promise(r=>resolve=r):dto()});await late.open();const pending=late.get('idleReview-reject-reflection-a').click();await flush();assert.equal(late.get('previewIdleReview').disabled,true);assert.equal(late.get('runIdleReview').disabled,true);assert.equal(late.context.MEMORY.busy,true);late.S.libraryId='new';late.S.libraryEpoch++;late.context.updateMemoryButtons();resolve({library_id:'a',proposal_id:'reflection-a',status:'rejected'});await pending;assert.equal(late.get('idleReviewSection').open,false);assert.equal(late.get('idleReviewProposals').children.length,0);assert(!late.words('idleReviewStatus').includes('已采纳'));assert.equal(late.context.MEMORY.busy,false);
});

test('proposal pages are library-scoped GETs, append without duplicates, preserve disclosure and resist automatic resets',async()=>{
 const counts={eligible:5,pending:0,processed:5,proposals:3};const e=environment({realApi:true,transport:async route=>{const page=route.includes('cursor=page-two')?2:route.includes('cursor=page-three')?3:1;return dto({counts,total:3,next_cursor:page===1?'page-two':page===2?'page-three':null,proposals:[proposal({id:'p'+page})]});}});await e.open();assert.equal(e.get('moreIdleReviewProposals').hidden,false);const first=e.get('idleReviewProposals').querySelectorAll('details').find(n=>n.dataset.proposalId==='p1');first.open=true;await e.get('moreIdleReviewProposals').click();assert.equal(e.network[1].method,'GET');assert.equal(e.network[1].body,undefined);assert.equal(e.network[1].url,'/api/idle-review?cursor=page-two');assert(e.get('idleReview-reject-p1')&&e.get('idleReview-reject-p2'));assert.equal(e.get('idleReviewProposals').querySelectorAll('details').find(n=>n.dataset.proposalId==='p1').open,true);assert(e.words('idleReviewPageInfo').includes('2/3'));
 await e.context.refreshOrganizer();assert.equal(e.network.length,2);await e.get('moreIdleReviewProposals').click();assert(e.get('idleReview-reject-p3'));assert.equal(e.get('moreIdleReviewProposals').hidden,true);assert(e.words('idleReviewPageInfo').includes('3/3'));assert.equal(e.network.filter(c=>c.method==='POST').length,0);await e.get('previewIdleReview').click();assert.equal(e.get('idleReview-reject-p2'),undefined);assert.equal(e.get('moreIdleReviewProposals').hidden,false);
});

test('a changed cursor reloads one first page; a network failure keeps already read proposals and exposes retry',async()=>{
 let fail='cursor';const e=environment({transport:async route=>{if(route.includes('?cursor=')){if(fail==='cursor')throw Error('回顾分页已变化，请重新加载第一页');throw Error('网络暂时断开');}return dto({next_cursor:'old-page',counts:{eligible:5,pending:0,processed:5,proposals:30}});}});await e.open();await e.get('moreIdleReviewProposals').click();assert.equal(e.calls.length,3);assert.equal(e.calls.at(-1)[0],'idle-review');assert(e.words('idleReviewStatus').includes('已重新读取第一页'));assert(e.get('idleReview-reject-reflection-a'));fail='network';await e.get('moreIdleReviewProposals').click();assert.equal(e.calls.length,4);assert(e.words('idleReviewStatus').includes('网络暂时断开'));assert(e.get('idleReview-reject-reflection-a'));assert.equal(e.get('moreIdleReviewProposals').disabled,false);
});

test('closing the organizer invalidates in-flight status and cannot launch a hidden review',async()=>{
 let resolve;const e=environment({transport:()=>new Promise(r=>resolve=r)});await e.open();e.context.setPanelOpen('organizerPanel',false);resolve(dto());await flush();assert.equal(e.get('idleReviewProposals').children.length,0);assert.equal(e.get('runIdleReview').disabled,true);await e.get('runIdleReview').onclick();assert.equal(e.calls.length,1);
});

test('explicit preview restores focus after disabled blur on success or failure, releasing its listeners',async()=>{
 for(const fail of [false,true]){let resolve,reject;const e=environment({transport:async route=>route.endsWith('/preview')?new Promise((done,error)=>{resolve=done;reject=error;}):dto()});await e.open();const button=e.get('previewIdleReview'),pending=button.click();await flush();assert.equal(e.context.document.activeElement,e.context.document.body);if(fail)reject(Error('读取中断'));else resolve(dto());await pending;assert.equal(e.context.document.activeElement,button);assert.equal(button.disabled,false);assert.equal((e.context.document.events.focusin||[]).length,0);assert.equal((e.context.document.events.pointerdown||[]).length,0);}
});

test('explicit action never steals focus after user navigation, including focus moved away and then back to body',async()=>{
 for(const movedBack of [false,true]){let resolve;const e=environment({transport:async route=>route.endsWith('/preview')?new Promise(done=>resolve=done):dto()});await e.open();const outside=new Element('button');e.context.document.body.append(outside);const pending=e.get('previewIdleReview').click();outside.focus();if(movedBack)e.context.document.activeElement=e.context.document.body;resolve(dto());await pending;assert.equal(e.context.document.activeElement,movedBack?e.context.document.body:outside);}
 let resolve;const clicked=environment({transport:async route=>route.endsWith('/preview')?new Promise(done=>resolve=done):dto()});await clicked.open();const pending=clicked.get('previewIdleReview').click();clicked.context.document.dispatch('pointerdown',{target:clicked.get('organizerSettings')});resolve(dto());await pending;assert.equal(clicked.context.document.activeElement,clicked.context.document.body);
});

test('completed writes and last page use a visible continuation when their original button is disabled or removed',async()=>{
 let profile={enabled:false,idle_seconds:300,batch_size:6};const settings=environment({transport:async(route,body)=>{if(route.endsWith('/settings'))profile=body;return dto({profile});}});await settings.open();settings.get('idleReviewEnabled').checked=true;settings.get('idleReviewEnabled').onchange();await settings.get('saveIdleReviewSettings').click();assert.equal(settings.get('saveIdleReviewSettings').disabled,true);assert.equal(settings.context.document.activeElement,settings.get('idleReviewEnabled'));
 let queued=false;const run=environment({transport:async route=>{if(route.endsWith('/run')){queued=true;return {queued:true,status:'queued',library_id:'a'};}return dto({running:queued});}});await run.open();await run.get('runIdleReview').click();assert.equal(run.get('runIdleReview').disabled,true);assert.equal(run.context.document.activeElement,run.get('previewIdleReview'));
 const page=environment({transport:async route=>dto({next_cursor:route.includes('?cursor=')?null:'next'})});await page.open();await page.get('moreIdleReviewProposals').click();assert.equal(page.get('moreIdleReviewProposals').hidden,true);assert.equal(page.context.document.activeElement,page.get('previewIdleReview'));
});

test('polling never requests focus, and library change or closed panel cancels explicit return',async()=>{
 const poll=environment();await poll.open();const outside=new Element('button');poll.context.document.body.append(outside);outside.focus();await poll.context.refreshOrganizer();assert.equal(poll.context.document.activeElement,outside);assert.equal((poll.context.document.events.focusin||[]).length,0);
 for(const close of [false,true]){let resolve;const e=environment({transport:async route=>route.endsWith('/preview')?new Promise(done=>resolve=done):dto()});await e.open();const pending=e.get('previewIdleReview').click();if(close)e.context.setPanelOpen('organizerPanel',false);else{e.S.libraryEpoch++;e.context.updateMemoryButtons();}resolve(dto());await pending;assert.equal(e.context.document.activeElement,e.context.document.body);assert.equal((e.context.document.events.focusin||[]).length,0);}
});


test('directory is primary and legacy archive stays folded without any adoption control',async()=>{
 const e=environment();await e.open();assert.equal(e.get('legacyIdleReviewArchive').open,false);assert(e.words('idleReviewSection').includes('空闲整理'));assert(e.words('idleReviewSection').includes('摘要仍由上方记忆整理处理'));assert(e.words('idleReviewDirectory').includes('原文目录标题'));assert.equal(e.get('idleReview-accept-reflection-a'),undefined);assert(e.get('idleReview-reject-reflection-a'));await e.get('viewIdleDirectory-source-a').click();assert.deepEqual(e.selections,[['source-a',true]]);assert.equal(e.calls.length,1);
});

test('legacy accepted material can only be withdrawn and preserves explicit receipt checks',async()=>{
 let status='accepted';const e=environment({transport:async route=>{if(route.endsWith('/rollback')){status='rolled_back';return {library_id:'a',proposal_id:'reflection-a',status};}return dto({proposals:[proposal({status})]});}});await e.open();assert(e.get('idleReview-rollback-reflection-a'));assert.equal(e.get('idleReview-accept-reflection-a'),undefined);await e.get('idleReview-rollback-reflection-a').click();assert.equal(status,'rolled_back');assert(e.words('idleReviewStatus').includes('不会恢复被遗忘的原文'));assert.equal(e.get('idleReview-rollback-reflection-a'),undefined);assert.equal(e.get('previewIdleReview').focused,true);
});

test('acknowledged rejection followed by failed refresh requires a fresh preview before another write',async()=>{
 let rejected=false,failed=true;const e=environment({transport:async route=>{if(route.endsWith('/reject')){rejected=true;return {library_id:'a',proposal_id:'reflection-a',status:'rejected'};}if(rejected&&failed)throw Error('读取中断');return dto({proposals:[proposal({status:rejected?'rejected':'pending'})]});}});await e.open();await e.get('idleReview-reject-reflection-a').click();assert(e.words('idleReviewStatus').includes('操作已确认'));assert.equal(e.get('runIdleReview').disabled,true);assert.equal(e.get('previewIdleReview').disabled,false);failed=false;await e.get('previewIdleReview').click();assert.equal(e.get('idleReview-reject-reflection-a'),undefined);assert.equal(e.calls.filter(c=>c[0].endsWith('/reject')).length,1);
});

test('model-calling legacy status or forged directory identity cannot masquerade as local organization',async()=>{
 for(const invalid of [dto({mode:'reflection'}),dto({model_called:true}),dto({directory_entries:[{id:'source-a',label:'title',roles:['user'],read_tool:'memory_read',read_arguments:{memory_id:'foreign'}}]})]){const e=environment({transport:async()=>invalid});await e.open();assert.equal(e.get('idleReviewStatus').dataset.error,'true');assert.equal(e.get('idleReviewDirectory').children.length,0);assert.equal(e.get('runIdleReview').disabled,true);}
});
