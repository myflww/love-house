/* Execute the shipped workspace and the actual correction submit handler. */
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/memory-workspace.js'),'utf8');
const html=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/index.html'),'utf8');
const correctionCode=html.slice(html.indexOf('function openMemoryCorrection('),html.indexOf('function confirmationList('));
const copy=x=>JSON.parse(JSON.stringify(x));
const all=n=>[n,...(n.children||[]).flatMap(all)],words=n=>all(n).map(n=>n.textContent||'').join('\n');
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attrs={};this.dataset={};this.events={};this.style={};this.disabled=false;this.hidden=false;this.open=false;this.value='';this.checked=false;this._text='';this.className='';this.id='';this.classList={add:(...names)=>{this.className=[...new Set([...this.className.split(' '),...names])].join(' ');},contains:n=>this.className.split(' ').includes(n)};}
 get textContent(){return this._text;}
 set textContent(value){this._text=String(value);this.children=[];}
 remove(){if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(n=>n!==this);this.parentElement=null;}
 append(...nodes){for(let node of nodes){if(typeof node==='string')node={textContent:node};node.remove?.();node.parentElement=this;this.children.push(node);}}
 prepend(...nodes){for(const n of [...nodes].reverse()){n.remove?.();n.parentElement=this;this.children.unshift(n);}}
 before(...nodes){const p=this.parentElement;if(!p)return;for(const n of nodes){n.remove?.();n.parentElement=p;p.children.splice(p.children.indexOf(this),0,n);}}
 after(...nodes){const p=this.parentElement;if(!p)return;let at=p.children.indexOf(this)+1;for(const n of nodes){n.remove?.();n.parentElement=p;p.children.splice(at++,0,n);}}
 replaceChildren(...nodes){for(const n of this.children)n.parentElement=null;this.children=[];this._text='';this.append(...nodes);}
 setAttribute(key,value){this.attrs[key]=String(value);}
 getAttribute(key){return this.attrs[key]??null;}
 addEventListener(type,fn){(this.events[type]??=[]).push(fn);}
 async emit(type,event={}){event.preventDefault??=()=>{};for(const fn of this.events[type]||[])await fn(event);}
 click(){if(!this.disabled)return this.onclick?.();}
 showModal(){this.open=true;}
 close(){this.open=false;}
 focus(){this.focused=true;}
 querySelectorAll(selector){return all(this).slice(1).filter(n=>n.tagName&&selector.split(',').some(part=>part.startsWith('.')?n.className.split(' ').includes(part.slice(1)):n.tagName===part.toUpperCase()));}
 querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
 set innerHTML(_value){throw Error('untrusted content must use text');}
}
const flush=async()=>{for(let n=0;n<15;n++)await Promise.resolve();};
function timeline(extra={}){return {schema:'love-house-memory-timeline/v1',library_id:'a',entries:[],correction_candidates:[],total:0,next_cursor:null,view:'open',read_only:true,will_call_model:false,...extra};}
function proposal(extra={}){return {id:'candidate-a',source_id:'source-a',source_text:'我现在不喝咖啡了',recorded_at:1700000000,candidates:[{id:'old',title:'饮品偏好',text:'喜欢咖啡'}],actor_scope:'direct_capture',requires_identity_confirmation:false,target_selection_required:true,requires_explicit_confirmation:true,auto_applied:false,read_only:true,...extra};}
function connection(extra={}){return {id:'connection-a',name:'明确连接的窗口',scope:{library_id:'a',window_id:'window-a',policy:'window-a',binding_revision:0},enabled:true,stages:[{id:'provided',label:'提供记忆',state:'complete',detail:'已提供资料，不证明模型采用'}],recent_delivery:{id:'delivery-a',session_id:'window-a',at:1700000000,items:[{id:'old',label:'饮品偏好',kind:'preference'}]},delivery_record_available:true,model_adoption_verified:false,...extra};}
function connections(extra={}){return {schema:'love-house-memory-experience/v1',library:{id:'a',name:'鱼的记忆',is_demo:false},connections:[connection()],read_only:true,model_calls:0,scope_changed:false,...extra};}
function verification(extra={}){return {read_only:true,will_call_model:false,model_adoption_verified:false,previous_excluded:true,replacement_included:true,disabled_material_excluded:true,selection_verified:true,...extra};}
function environment({transport,demo=false}={}){
 const body=new Element('body'),head=new Element('head');const make=(tag,id,parent,cls='',text='')=>{const n=new Element(tag);n.id=id;n.className=cls;if(text)n.textContent=text;parent.append(n);return n;};
 const dialog=make('dialog','experienceTimelineDialog',body);for(const id of ['experienceIntro','experienceTimelineStatus','experienceTimelineList','experienceTechnical','experienceControls'])make('div',id,dialog);
 make('div','newConnectionDetails',body);make('div','detail',body);const correction=make('dialog','correctMemoryDialog',body),form=make('form','correctMemoryForm',correction);make('input','correctMemoryLabel',form);make('textarea','correctMemoryText',form);
 const get=id=>[...all(body),...all(head)].find(n=>n.id===id),events=[];
 const S={libraryId:'a',libraryEpoch:1,mode:'serve',isDemo:demo,libraryChanging:false,selected:'old',byId:new Map([['old',{id:'old',kind:'preference',label:'饮品偏好',text:'喜欢咖啡'}],['source-a',{id:'source-a',kind:'episode'}],['new',{id:'new',kind:'preference',label:'饮品偏好',text:'现在喝茶'}]])};
 const calls=[],messages=[],selections=[],context={S,MEMORY:{busy:false},MAINTENANCE:{correct:null},writeBusy:false,document:{body,head,getElementById:get,createTextNode:text=>({textContent:String(text)})},window:{LoveHouseExperiences:{subscribe(fn){events.push(fn);},open(){dialog.open=true;for(const fn of events)fn({kind:'open',scope:{id:S.libraryId,epoch:S.libraryEpoch},open:true});},close(){dialog.open=false;for(const fn of events)fn({kind:'close',open:false});}}},el:(tag,cls,text)=>{const n=new Element(tag);n.className=cls||'';if(text!==undefined)n.textContent=text;return n;},libraryName:id=>'库 '+id,updateMemoryButtons(){},renderDetail(){get('detail').replaceChildren();},canWrite:()=>!demo,api:async(...args)=>{calls.push(copy(args));return transport?transport(...args):args[0]==='memory/experience'?connections():timeline();},invalidateRecall(){},updateWriteState(){context.updateMemoryButtons();},resetBrowseAfterWrite(){},reload:async()=>true,select:(id,...args)=>{S.selected=id;selections.push([id,...args]);context.renderDetail();},toast:(...args)=>messages.push(args)};
 context.$=selector=>get(selector.slice(1));vm.createContext(context);vm.runInContext(correctionCode,context);vm.runInContext(source,context);
 async function open(tab){context.window.LoveHouseMemoryWorkspace.open(tab);await flush();}
 return {context,S,get,calls,messages,selections,open,close:()=>context.window.LoveHouseExperiences.close(),words:id=>words(get(id))};
}

test('one existing dialog gains tabs; navigation performs scoped read requests and no writes',async()=>{
 const e=environment();await e.open('connections');assert.deepEqual(e.calls,[['memory/experience',null,{libraryId:'a'}]]);assert(e.words('memoryWorkspaceList').includes('明确连接的窗口'));assert(e.words('memoryWorkspacePanel').includes('不证明模型采用'));assert.equal(e.get('experienceTimelineList').hidden,true);
 const details=e.get('memoryWorkspaceList').querySelectorAll('details');assert.equal(details.length,2);assert(details.every(detail=>detail.open===false));assert.equal((e.words('memoryWorkspacePanel').match(/不证明模型采用/g)||[]).length,1);
 e.get('memoryWorkspaceTab-experiences').click();assert.equal(e.get('experienceTimelineList').hidden,false);assert.equal(e.get('memoryWorkspacePanel').hidden,true);assert.equal(e.calls.length,1);
});

test('provided titles open the actual node while a now-disabled item remains visible as an explicit error',async()=>{
 const e=environment();await e.open('connections');e.get('viewProvided-connection-a-old').click();assert.deepEqual(e.selections,[['old',true]]);assert.equal(e.get('experienceTimelineDialog').open,false);
 const unavailable=environment();await unavailable.open('connections');unavailable.S.byId.get('old').meta={memory_disabled:true};unavailable.get('viewProvided-connection-a-old').click();assert.equal(unavailable.selections.length,0);assert.equal(unavailable.get('experienceTimelineDialog').open,true);assert(unavailable.words('memoryWorkspaceStatus').includes('这条资料已停用'));assert.equal(unavailable.calls.length,1);
});

test('cross-library responses, unproven reads and late closed replies never expose memory',async()=>{
 for(const result of [connections({library:{id:'foreign'}}),connections({model_calls:1}),connections({connections:[connection({scope:{library_id:'foreign'}})]})]){const e=environment({transport:async()=>result});await e.open('connections');assert.equal(e.get('memoryWorkspaceStatus').dataset.error,'true');assert(!e.words('memoryWorkspaceList').includes('明确连接的窗口'));}
 let resolve;const e=environment({transport:()=>new Promise(r=>resolve=r)});await e.open('connections');e.S.libraryId='b';e.S.libraryEpoch++;e.context.updateMemoryButtons();resolve(connections());await flush();assert.equal(e.get('memoryWorkspaceList').children.length,0);
 const closed=environment({transport:()=>new Promise(r=>resolve=r)});await closed.open('connections');closed.close();resolve(connections());await flush();assert.equal(closed.get('memoryWorkspaceList').children.length,0);
});

test('zero hits and unavailable delivery records remain local, honest states',async()=>{
 const e=environment({transport:async()=>connections({connections:[connection({recent_delivery:null,delivery_record_available:false,stages:[{id:'provided',label:'提供记忆',state:'empty',detail:'取回完成，没有匹配'}]})]})});await e.open('connections');assert(e.words('memoryWorkspaceList').includes('本次未找到记忆'));assert(e.words('memoryWorkspaceList').includes('最近提供条目暂时无法读取'));assert(e.words('memoryWorkspaceList').includes('明确连接的窗口'));assert.equal(e.get('memoryWorkspaceStatus').dataset.error,'false');
});

test('organization queue, running and retry stages have distinct labels without claiming pending is running',async()=>{
 for(const [state,label]of [['queued','待整理'],['running','整理中'],['retry','等待重试'],['pending','待整理']]){const e=environment({transport:async()=>connections({connections:[connection({stages:[{id:'organized',label:'整理',state,detail:'原文已保留'}]})]})});await e.open('connections');assert(e.words('memoryWorkspaceList').includes(label));assert(!e.words('memoryWorkspaceList').includes('处理中'));}
});

test('helpfulness is an explicit management action, rejection stays visible and never enables reinforcement',async()=>{
 const e=environment({transport:async(route,body)=>{if(!body)return connections();throw Error('已关闭记忆使用强化');}});await e.open('connections');assert.equal(e.calls.length,1);await e.get('confirmHelpful-connection-a-old').click();await flush();assert.deepEqual(e.calls[1],['memory/feedback',{connection_id:'connection-a',delivery_id:'delivery-a',session_id:'window-a',ids:['old'],kind:'confirmed'},{libraryId:'a'}]);assert(e.words('memoryWorkspaceStatus').includes('已关闭记忆使用强化'));assert.equal(e.get('confirmHelpful-connection-a-old').textContent,'有帮助');assert.equal(e.get('confirmHelpful-connection-a-old').disabled,false);
 const accepted=environment({transport:async(_route,body)=>body?{accepted:true,kind:'confirmed',library_id:'a',connection_id:'connection-a'}:connections()});await accepted.open('connections');await accepted.get('confirmHelpful-connection-a-old').click();assert.equal(accepted.get('confirmHelpful-connection-a-old').textContent,'已确认有帮助');assert.equal(accepted.get('confirmHelpful-connection-a-old').disabled,true);
});

test('commitments complete or reopen only by click and preserve closed-history pagination',async()=>{
 let complete=false;const row={id:'promise',title:'面试约定',text:'面试后聊结果',kind:'commitment',status:'open',recorded_at:1700000000};
 const e=environment({transport:async(route,body)=>{if(body){complete=true;return {id:'promise',status:body.status,will_send_message:false,basis:'explicit_user_action'};}return timeline({entries:complete?[]:[row],total:complete?0:2,next_cursor:complete?null:'page-two'});}});await e.open('commitments');assert.equal(e.calls.length,1);assert.equal(e.get('moreMemoryWorkspace').hidden,false);await e.get('moreMemoryWorkspace').click();await flush();assert(e.calls[1][0].includes('cursor=page-two'));await e.get('completeCommitment-promise').click();await flush();assert.deepEqual(e.calls.find(c=>c[1]),['commitments/promise/status',{status:'done'},{libraryId:'a'}]);assert(e.words('memoryWorkspaceList').includes('当前没有待跟进'));assert.equal(e.get('moreMemoryWorkspace').hidden,true);assert.equal(e.get('memoryCommitmentFilter').focused,true);assert(e.words('memoryWorkspaceStatus').includes('已标记完成'));
});

test('correction source is data, no target is auto-selected and no write occurs before user editing',async()=>{
 const quote='<img onerror=STEAL()>我现在不喝咖啡了';const e=environment({transport:async()=>timeline({view:'corrections',correction_candidates:[proposal({source_text:quote})]})});await e.open('corrections');assert(e.words('memoryWorkspaceList').includes(quote));assert.equal(e.get('reviewCorrection-candidate-a').disabled,true);const target=e.get('correctionTarget-candidate-a');target.value='old';target.onchange();assert.equal(e.get('reviewCorrection-candidate-a').disabled,false);e.get('reviewCorrection-candidate-a').click();assert.equal(e.get('correctMemoryDialog').open,true);assert.equal(e.get('correctMemoryText').value,'');assert(e.get('correctMemoryNotice').textContent.includes(quote));assert.equal(e.calls.length,1);assert.equal(e.context.MAINTENANCE.correct.source_id,'source-a');assert.equal(e.context.STEAL,undefined);
});

test('a platform statement needs explicit self-claim and a manually searched same-library target',async()=>{
 const e=environment({transport:async()=>timeline({view:'corrections',correction_candidates:[proposal({actor_scope:'external_participant',requires_identity_confirmation:true,candidates:[]})]})});await e.open('corrections');assert(e.words('memoryWorkspaceList').includes('来源发言待核对'));assert.equal(e.get('correctionTarget-candidate-a').disabled,true);assert.equal(e.get('reviewCorrection-candidate-a').disabled,true);
 const claim=e.get('claimCorrectionSource-candidate-a');claim.checked=true;claim.onchange();const query=e.get('manualCorrectionQuery-candidate-a');query.value='咖啡';query.oninput();const target=e.get('correctionTarget-candidate-a');assert(target.children.some(o=>o.value==='old'));target.value='old';target.onchange();e.get('reviewCorrection-candidate-a').click();assert.equal(e.context.MAINTENANCE.correct.source_confirmed_as_self,true);assert.equal(e.get('correctMemoryText').value,'');assert.equal(e.calls.length,1);
});

test('the actual save handler independently verifies with the old topic and displays scope and selection',async()=>{
 const e=environment({transport:async(route,body)=>route.endsWith('/correct')?{id:'new',previous_id:'old',saved:true,change_scope:{library_id:'a',disabled_count:3}}:verification()});e.context.openMemoryCorrection('old');e.get('correctMemoryText').value='现在喝茶';await e.get('correctMemoryForm').emit('submit');assert.deepEqual(e.calls,[['memories/old/correct',{text:'现在喝茶'},{libraryId:'a'}],['memories/new/verify',{previous_id:'old',query:'饮品偏好'},{libraryId:'a'}]]);assert(e.words('memoryCorrectionReceipt').includes('3 条旧资料已停用'));assert(e.words('memoryCorrectionReceipt').includes('更正内容已被本次召回选中'));assert(e.words('memoryCorrectionReceipt').includes('不证明模型采用'));assert.equal(e.get('correctMemoryDialog').open,false);
});

test('a failed independent check is a saved correction, retrying never saves it again',async()=>{
 let fail=true;const e=environment({transport:async route=>{if(route.endsWith('/correct'))return {id:'new',previous_id:'old',saved:true,change_scope:{library_id:'a',disabled_count:1}};if(fail)throw Error('暂时无法核验');return verification();}});e.context.openMemoryCorrection('old');e.get('correctMemoryText').value='现在喝茶';await e.get('correctMemoryForm').emit('submit');assert(e.words('memoryCorrectionReceipt').includes('独立核验未完成'));assert(e.messages.at(-1)[0].includes('更正已保存'));fail=false;await e.get('verifyLatestCorrection').click();await flush();assert.equal(e.calls.filter(c=>c[0].endsWith('/correct')).length,1);assert(e.words('memoryCorrectionReceipt').includes('更正内容已被本次召回选中'));
});

test('the save handler ignores a stale owner and distinguishes graph-refresh failure from verification',async()=>{
 let resolve;const e=environment({transport:()=>new Promise(r=>resolve=r)});e.context.openMemoryCorrection('old');const save=e.get('correctMemoryForm').emit('submit');e.S.libraryId='b';e.S.libraryEpoch++;resolve({id:'new',previous_id:'old',saved:true,change_scope:{library_id:'a'}});await save;assert.equal(e.calls.length,1);assert.equal(e.selections.length,0);assert.equal(e.get('memoryCorrectionReceipt'),undefined);
 const refresh=environment({transport:async route=>route.endsWith('/correct')?{id:'new',previous_id:'old',saved:true,change_scope:{library_id:'a',disabled_count:1}}:verification()});refresh.context.reload=async()=>{throw Error('fake graph');};refresh.context.openMemoryCorrection('old');await refresh.get('correctMemoryForm').emit('submit');assert(refresh.words('memoryCorrectionReceipt').includes('图谱刷新失败'));assert(refresh.words('memoryCorrectionReceipt').includes('更正内容已被本次召回选中'));assert(refresh.messages.at(-1)[0].includes('图谱刷新失败'));
});

test('contradictory verification cannot become success, and demo actions cannot write',async()=>{
 const e=environment({transport:async route=>route.endsWith('/correct')?{id:'new',previous_id:'old',saved:true,change_scope:{library_id:'a',disabled_count:1}}:verification({replacement_included:false,selection_verified:true})});e.context.openMemoryCorrection('old');await e.get('correctMemoryForm').emit('submit');assert(e.words('memoryCorrectionReceipt').includes('独立核验未完成'));assert(!e.messages.at(-1)[0].includes('独立核验已选中'));
 const demo=environment({demo:true});await demo.open('connections');demo.get('confirmHelpful-connection-a-old').click();assert.equal(demo.calls.length,1);
});

test('correction receipts show a recorded time and project later disable, supersession, forgetting or absence as stale history',()=>{
 for(const change of [n=>{n.meta={memory_disabled:true};},n=>{n.superseded_by='later';},n=>{n.meta={forgotten:true};},n=>{n.state='forgotten';},n=>{n.valid_to=1;},(_n,e)=>{e.S.byId.delete('new');}]){const e=environment();e.S.selected='new';e.context.window.LoveHouseMemoryWorkspace.showCorrectionResult({owner:{id:'a',epoch:1},id:'new',previous_id:'old',query:'饮品偏好',verification:verification(),pending:false});assert(e.words('memoryCorrectionVerifiedAt').includes('核验记录时间（本机）'));assert(!e.words('memoryCorrectionVerifiedAt').includes('时间未提供'));assert(e.words('memoryCorrectionVerifiedAt').includes('当次检索'));assert.equal(e.get('memoryCorrectionVerificationState'),undefined);change(e.S.byId.get('new'),e);e.context.renderDetail();assert(e.words('memoryCorrectionVerificationState').includes('状态已变化，请重新核验'));assert.equal(e.get('memoryCorrectionReceipt').dataset.error,'true');assert.equal(e.get('memoryCorrectionVerificationHistory').open,false);assert.equal(e.get('memoryCorrectionReceipt').querySelectorAll('ul')[0].parentElement,e.get('memoryCorrectionVerificationHistory'));assert.equal(e.get('verifyLatestCorrection').disabled,false);assert.equal(e.calls.length,0);}
});

test('reactivating a changed node does not revive an old success; explicit read-only verification replaces stale history',async()=>{
 const e=environment({transport:async()=>verification({replacement_included:false,selection_verified:false})});e.S.selected='new';e.context.window.LoveHouseMemoryWorkspace.showCorrectionResult({owner:{id:'a',epoch:1},id:'new',previous_id:'old',query:'饮品偏好',verification:verification(),pending:false});e.S.byId.get('new').meta={memory_disabled:true};e.context.renderDetail();e.S.byId.get('new').meta.memory_disabled=false;e.context.renderDetail();assert(e.get('memoryCorrectionVerificationState'));assert.equal(e.calls.length,0);e.S.byId.get('new').meta.memory_disabled=true;await e.get('verifyLatestCorrection').click();assert.deepEqual(e.calls,[['memories/new/verify',{previous_id:'old',query:'饮品偏好'},{libraryId:'a'}]]);assert.equal(e.get('memoryCorrectionVerificationState'),undefined);assert.equal(e.get('memoryCorrectionVerificationHistory'),undefined);assert(e.words('memoryCorrectionReceipt').includes('更正内容未被本次问题选中'));assert(e.words('memoryCorrectionReceipt').includes('核验不会恢复使用'));assert.equal(e.S.byId.get('new').meta.memory_disabled,true);assert.equal(e.get('memoryCorrectionReceipt').dataset.error,'true');assert(e.get('memoryCorrectionVerifiedAt'));
});

test('a lifecycle change during read-only verification cannot be shown as a current successful selection',async()=>{
 let resolve;const e=environment({transport:()=>new Promise(done=>resolve=done)});e.S.selected='new';e.context.window.LoveHouseMemoryWorkspace.showCorrectionResult({owner:{id:'a',epoch:1},id:'new',previous_id:'old',query:'饮品偏好',verification:verification(),pending:false});const pending=e.get('verifyLatestCorrection').click();e.S.byId.get('new').meta={memory_disabled:true};resolve(verification());await pending;assert(e.words('memoryCorrectionVerificationState').includes('状态已变化，请重新核验'));assert.equal(e.get('memoryCorrectionVerificationHistory').open,false);assert.equal(e.get('memoryCorrectionReceipt').dataset.error,'true');assert.equal(e.calls.length,1);
});
