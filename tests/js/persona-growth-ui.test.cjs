/* Exercise the actual persona UI component with inert model/storage boundaries. */
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/persona-growth-ui.js'),'utf8');
const organizer=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/memory-organizer-ui.js'),'utf8');
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.events={};this.className='';this.textContent='';this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.open=false;this.classList={add:(...names)=>{this.className+=' '+names.join(' ');},contains:name=>this.className.split(' ').includes(name),toggle:()=>{}};}
 get nextElementSibling(){if(!this.parentElement)return null;const items=this.parentElement.children.filter(n=>n instanceof Element);return items[items.indexOf(this)+1]||null;}
 append(...nodes){for(const node of nodes){if(node instanceof Element){if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(n=>n!==node);node.parentElement=this;}this.children.push(node);}}
 before(...nodes){const p=this.parentElement,at=p.children.indexOf(this);p.children.splice(at,0,...nodes);nodes.forEach(n=>n.parentElement=p);}
 after(...nodes){const p=this.parentElement,at=p.children.indexOf(this);p.children.splice(at+1,0,...nodes);nodes.forEach(n=>n.parentElement=p);}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 setAttribute(key,value){this.attributes[key]=String(value);}
 querySelector(selector){return all(this).find(n=>matches(n,selector));}
 querySelectorAll(selector){return all(this).filter(n=>matches(n,selector));}
 addEventListener(key,fn){this.events[key]=fn;}
 focus(){this.focused=true;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 click(){if(!this.disabled)return this.onclick?.();}
 set innerHTML(value){throw Error('Persona material must be rendered as text, never HTML');}
}
const all=root=>[root,...root.children.flatMap(n=>n instanceof Element?all(n):[])];
const words=root=>all(root).map(n=>n.textContent).join('\n');
function matches(e,s){if(s==='summary')return e.tagName==='SUMMARY';if(s==='label[for=personaText]')return e.tagName==='LABEL'&&e.htmlFor==='personaText';if(s==='[data-persona-trait-remove]')return e.dataset.personaTraitRemove!==undefined;return s[0]==='#'&&e.id===s.slice(1);}
const plain=x=>JSON.parse(JSON.stringify(x));
function fixture(){
 const body=new Element('body'),head=new Element('head'),get=id=>[...all(body),...all(head)].find(n=>n.id===id);
 const make=(tag,cls,text)=>{const e=new Element(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;};
 const add=(id,tag='div',parent=body)=>{const e=make(tag);e.id=id;parent.append(e);return e;};
 const persona=add('personaPanel'),org=add('organizerPanel');add('personaRevision','p',persona);const label=make('label');label.htmlFor='personaText';persona.append(label);add('personaText','textarea',persona);add('personaEnabled','input',persona);add('personaLearning','input',persona);const manualActions=add('personaManualActions','div',persona);manualActions.className='persona-review';add('savePersonaImport','button',manualActions);add('reloadPersonaBtn','button',manualActions);const manualNote=add('personaManualLegacyNote','p',persona);manualNote.className='form-note';manualNote.textContent='也可在 Harness 对话里用人格工具设置。';add('personaLearned','div',persona);
 add('organizerState','p',org);add('organizerCounts','div',org);const settings=add('organizerSettings','details',org);settings.append(make('summary'));for(const id of ['organizerProviderKey','organizerMode','organizerConnection','saveOrganizerSettings','organizerSeparate','organizerConnectionRow'])add(id,id==='saveOrganizerSettings'?'button':'input',settings);
 get('organizerMode').value='separate';get('organizerProviderKey').type='password';
 const S={mode:'serve',libraryId:'fish-a',libraryEpoch:3,isDemo:false,libraryChanging:false,byId:new Map([['raw-1',{}],['raw-2',{}]])};
 const MEMORY={busy:false,persona:null,personaDirty:false},ORGANIZER={data:null,dirty:false},requests=[],saves=[],panels=[],messages=[];
 const c={S,MEMORY,ORGANIZER,writeBusy:false,window:{},document:{body,head,events:{},addEventListener(name,fn){this.events[name]=fn;},getElementById:get,querySelector:s=>[...all(body),...all(head)].find(n=>matches(n,s))},el:make,
  canManageMemory:()=>true,libraryName:id=>id==='fish-a'?'泡泡':'另一条鱼',select:(id)=>{c.selected=id;},toast:text=>messages.push(text),
  setPanelOpen:(id,open)=>panels.push({id,open}),memoryTab:tab=>{c.tab=tab;},organizerModeChanged(){},
  updateMemoryButtons(){},updateMaintenanceButtons(){},updateWriteState(){c.updateMemoryButtons();c.updateMaintenanceButtons();},
  renderPersona:data=>{MEMORY.persona=data;get('personaEnabled').checked=data.enabled;get('personaLearning').checked=data.learning_enabled;if(!MEMORY.personaDirty)get('personaText').value=data.manual||'';},
  renderOrganizer:data=>{ORGANIZER.data=data;},refreshOrganizer:async()=>{},refreshPersona:async()=>{},
  saveOrganizerSettings:async options=>saves.push(plain(options)),api:async(route,data,options)=>{requests.push({route,data:plain(data),options:plain(options)});throw Error('No default model or storage activity');}};
 vm.runInNewContext(source,c);return {c,S,MEMORY,ORGANIZER,get,body,requests,saves,panels,messages};
}
function ready(library='fish-a'){return {library_id:library,will_call_model:false,status:'ready',selected_records:6,eligible_records:120,coverage:'sampled',persona_enabled:true,learning_enabled:true,model_ready:true,credential_ready:true,organizer_enabled:true};}

test('opening and rendering persona keeps backend opt-out/manual text and makes no model request',()=>{
 const f=fixture();assert(f.get('personaEnabled').disabled);assert(f.get('personaLearning').disabled);f.c.renderPersona({revision:9,enabled:false,learning_enabled:false,manual:'明确设定原文',formed_traits:[]});
 assert.equal(f.get('personaEnabled').checked,false);assert.equal(f.get('personaLearning').checked,false);assert.equal(f.get('personaText').value,'明确设定原文');assert(words(f.get('personaGrowthStatus')).includes('人格已关闭'));assert.deepEqual(f.requests,[]);
 f.c.renderPersona({revision:0,enabled:true,learning_enabled:true,manual:'',formed_traits:[]});assert(words(f.get('personaGrowthStatus')).includes('空白人格'));assert.equal(f.get('personaText').value,'');assert(!words(f.get('personaFormedTraits')).includes('温柔'));assert.deepEqual(f.requests,[]);
});

test('formed persona is primary and an empty optional manual editor stays folded unless the user opens it',()=>{
 const f=fixture(),panel=f.get('personaPanel'),manual=f.get('personaManualSettings');
 f.c.renderPersona({revision:0,enabled:true,learning_enabled:true,manual:'',formed_traits:[]});
 assert.equal(manual.open,false);assert(panel.children.indexOf(f.get('personaFormedTraits'))<panel.children.indexOf(manual));
 assert.equal(f.get('personaText').parentElement,manual);assert.equal(f.get('personaManualActions').parentElement,manual);assert.equal(f.get('personaManualLegacyNote').parentElement,manual);
 assert.equal(f.get('savePersonaImport').parentElement,f.get('personaManualActions'));assert.equal(f.get('reloadPersonaBtn').parentElement,f.get('personaManualActions'));
 manual.open=true;f.c.renderPersona({revision:1,enabled:true,learning_enabled:true,manual:'',formed_traits:[]});assert.equal(manual.open,true);
 f.S.libraryId='fish-b';f.S.libraryEpoch++;f.c.updateMemoryButtons();assert.equal(manual.open,false);assert.deepEqual(f.requests,[]);
});

test('existing manual settings open initially; user disclosure and unsaved draft revision are preserved',()=>{
 const f=fixture(),manual=f.get('personaManualSettings');
 f.c.renderPersona({revision:7,enabled:true,learning_enabled:true,manual:'固定设定',formed_traits:[]});assert(manual.open);assert.equal(f.get('personaText').value,'固定设定');
 manual.open=false;f.c.renderPersona({revision:8,enabled:true,learning_enabled:true,manual:'固定设定',formed_traits:[]});assert.equal(manual.open,false);
 manual.open=true;f.get('personaText').value='尚未保存的草稿';f.MEMORY.personaDirty=true;f.MEMORY.personaDraftRevision=8;
 f.c.renderPersona({revision:9,enabled:true,learning_enabled:true,manual:'后台旧设定',formed_traits:[]});assert.equal(manual.open,true);assert.equal(f.get('personaText').value,'尚未保存的草稿');assert.equal(f.MEMORY.personaDraftRevision,8);
});

test('API recommendation explains optional AI use, and save-enable is a separate explicit action',async()=>{
 const f=fixture();for(const id of ['personaApiRecommendation','organizerApiRecommendation'])assert(words(f.get(id)).includes('强烈建议'));
 const text=words(f.get('organizerApiPurpose'));for(const fragment of ['手动人格','原文保存','预算','费用','不是聊天窗口'])assert(text.includes(fragment));
 assert.deepEqual(f.saves,[]);await f.get('saveAndEnableOrganizer').click();assert.deepEqual(f.saves,[{enable:true}]);
 f.c.renderOrganizer({settings:{enabled:true},provider:{credential_ready:true,model_ready:true}});assert(words(f.get('personaApiRecommendation')).includes('已配置'));assert(words(f.get('personaApiRecommendationStatus')).includes('逐步形成'));
 f.c.renderOrganizer({settings:{enabled:false},provider:{credential_ready:true,model_ready:true}});assert(words(f.get('organizerApiRecommendationStatus')).includes('自动整理尚未开启'));
});

test('quick action previews scope only; a distinct confirmation starts exactly one bounded persona request',async()=>{
 const f=fixture();f.c.api=async(route,data,options)=>{f.requests.push({route,data:plain(data),options:plain(options)});if(route==='persona/organize-preview')return ready();if(route==='persona/organize')return {library_id:'fish-a',status:'queued',max_model_requests:1};throw Error('Unexpected '+route);};
 await f.c.window.LoveHousePersonaGrowth.openQuick();assert(f.get('personaFormationDialog').open);assert.equal(f.requests.length,1);assert.equal(f.requests[0].route,'persona/organize-preview');assert.deepEqual(f.requests[0].options,{libraryId:'fish-a'});assert(words(f.get('personaFormationCoverage')).includes('未覆盖全部历史'));assert.equal(f.get('confirmPersonaFormation').disabled,false);
 await f.get('confirmPersonaFormation').click();assert.equal(f.requests.length,2);assert.deepEqual(f.requests[1],{route:'persona/organize',data:{confirm:true,max_records:60},options:{libraryId:'fish-a'}});assert(!f.get('personaFormationDialog').open);assert.equal(f.tab,undefined);assert.equal(f.c.tab,'persona');assert.equal(f.MEMORY.busy,false);assert.equal(f.c.writeBusy,false);
});

test('missing API routes to setup without starting a job; settings navigation never enables saved opt-out',async()=>{
 const f=fixture();f.c.api=async()=>({...ready(),model_ready:false,credential_ready:false,status:'model_not_configured'});
 await f.c.window.LoveHousePersonaGrowth.openQuick();assert(f.get('confirmPersonaFormation').disabled);assert(!f.get('configurePersonaFormationAPI').hidden);assert(words(f.get('personaFormationStatus')).includes('强烈建议'));
 await f.get('configurePersonaFormationAPI').click();assert(!f.get('personaFormationDialog').open);assert(f.panels.some(p=>p.id==='organizerPanel'));assert(f.get('organizerSettings').open);assert(f.get('organizerProviderKey').focused);assert.deepEqual(f.saves,[]);
 for(const key of ['persona_enabled','learning_enabled']){f.c.api=async()=>({...ready(),[key]:false});await f.c.window.LoveHousePersonaGrowth.openQuick();assert(f.get('confirmPersonaFormation').disabled);assert(!f.get('openPersonaLearningSettings').hidden);await f.get('openPersonaLearningSettings').click();assert.deepEqual(f.saves,[]);assert.equal(f.MEMORY.persona,null);}
});

test('insufficient evidence and spent budget do not invent a persona or enlarge a budget',async()=>{
 const f=fixture();for(const data of [{...ready(),selected_records:1,eligible_records:1},{...ready(),status:'budget_limited'}]){f.c.api=async()=>data;await f.c.window.LoveHousePersonaGrowth.openQuick();assert(f.get('confirmPersonaFormation').disabled);assert(!words(f.get('personaFormationStatus')).includes('已完成'));await f.get('closePersonaFormation').click();}
 assert.equal(f.get('personaText').value,'');assert.deepEqual(f.saves,[]);
});

test('late read-only preview from another library cannot confirm or retarget a persona job',async()=>{
 const f=fixture();let resolve;f.c.api=()=>new Promise(r=>resolve=r);const pending=f.c.window.LoveHousePersonaGrowth.openQuick();assert(f.get('quickOrganizePersona').disabled);
 f.S.libraryId='fish-b';f.S.libraryEpoch++;f.c.renderPersona({revision:0,enabled:false,learning_enabled:false,formed_traits:[]});assert(!f.get('personaFormationDialog').open);resolve(ready());await pending;assert(f.get('confirmPersonaFormation').disabled);assert.equal(f.MEMORY.busy,false);
});

test('import completion is library-scoped and only offers a next step without model activity',async()=>{
 const f=fixture();const hook=f.c.window.LoveHousePersonaGrowth.afterImport;hook({library_id:'fish-b',added:80});assert(f.get('personaImportPrompt').hidden);
 hook({library_id:'fish-a',added:80});assert(!f.get('personaImportPrompt').hidden);assert.deepEqual(f.requests,[]);assert.deepEqual(f.saves,[]);
 f.S.libraryEpoch++;f.c.updateMemoryButtons();assert(f.get('personaImportPrompt').hidden);
});

test('learned traits remain separate from manual persona and use plain cited text with scoped removal',async()=>{
 const f=fixture(),trait={id:'persona_trait_fixture',dimension:'speaking_style',value:'<script>不是可执行内容</script>',evidence:[{id:'raw-1',role:'assistant',quote:'第一轮 AI 原话'},{id:'raw-2',role:'assistant',quote:'第二轮 AI 原话'}]};
 f.c.renderPersona({revision:12,enabled:true,learning_enabled:true,manual:'手动人格优先',formed_traits:[trait]});assert.equal(f.get('personaText').value,'手动人格优先');assert(words(f.get('personaFormedTraits')).includes(trait.value));assert(words(f.get('personaFormedTraits')).includes('第二轮 AI 原话'));
 f.c.api=async(route,data,options)=>{f.requests.push({route,data:plain(data),options:plain(options)});return {};};await f.get('removePersonaTrait-persona_trait_fixture').click();assert.deepEqual(f.requests,[{route:'persona/traits/persona_trait_fixture/remove',data:{expected_revision:12},options:{libraryId:'fish-a'}}]);assert.equal(f.get('personaText').value,'手动人格优先');
 const stale=f.get('removePersonaTrait-persona_trait_fixture');f.S.libraryId='fish-b';f.S.libraryEpoch++;f.c.updateMemoryButtons();await stale.click();assert.equal(f.requests.length,1);assert.equal(f.get('personaFormedTraits').children.length,0);
});

test('a preview response must identify this library and prove it will not call a model',async()=>{
 const f=fixture();for(const data of [{...ready(),library_id:'fish-b'},{...ready(),will_call_model:true}]){f.c.api=async()=>data;await f.c.window.LoveHousePersonaGrowth.openQuick();assert(f.get('confirmPersonaFormation').disabled);assert(words(f.get('personaFormationStatus')).includes('只读预览'));await f.get('closePersonaFormation').click();}
});

test('normal save honors its checkbox while the explicit save-enable action sends enabled true without increasing budgets',async()=>{
 const f=fixture(),values={organizerTriggerCount:'20',organizerCadence:'batch',organizerBatchSize:'6',organizerCallLimit:'6',organizerCharLimit:'12000',organizerConnection:'',organizerMode:'separate',organizerProviderKey:'FAKE-LOCAL'},requests=[];
 for(const [id,value]of Object.entries(values)){if(!f.get(id)){const e=new Element('input');e.id=id;f.body.append(e);}f.get(id).value=value;}const checkbox=new Element('input');checkbox.id='organizerEnabled';checkbox.checked=false;f.body.append(checkbox);const notice=new Element('p');notice.id='organizerNotice';f.body.append(notice);
 const c=f.c;Object.assign(c,{UI:{busy:false},context:()=>({id:c.S.libraryId,epoch:c.S.libraryEpoch}),current:o=>o.id===c.S.libraryId&&o.epoch===c.S.libraryEpoch,by:f.get,threshold:f.get('organizerTriggerCount'),cadence:f.get('organizerCadence'),batch:f.get('organizerBatchSize'),num:n=>Number(n),canWrite:()=>true,providerPayload:()=>({base_url:'https://provider.example',model:'fixture',api_key:'FAKE-LOCAL'}),api:async(route,body)=>{requests.push({route,body:plain(body)});return {};}});
 const code=organizer.match(/saveOrganizerSettings=async function\(options=\{\}\)\{[\s\S]*?\n\};/)[0];vm.runInNewContext(code,c);
 await c.saveOrganizerSettings();await c.saveOrganizerSettings({enable:true});assert.equal(requests[0].body.enabled,false);assert.equal(requests[1].body.enabled,true);for(const request of requests){assert.equal(request.body.daily_call_limit,6);assert.equal(request.body.daily_char_limit,12000);assert.equal(request.body.auto_trigger_count,20);}assert.equal(checkbox.checked,false);
});

test('partial persona feedback uses applied counts and fixed reasons without displaying raw rejected model material',()=>{
 const f=fixture();f.c.renderPersona({revision:0,enabled:true,learning_enabled:true,manual:'',formed_traits:[]});
 f.c.renderOrganizer({status:{library_id:'fish-a',jobs:[{id:'job-1',persona_result:{status:'partial',accepted_count:9,applied_count:1,rejected_count:2,reasons:{schema:2,'FAKE_PRIVATE_MODEL_REASON':8},text:'FAKE_PRIVATE_MODEL_TEXT'}}]}});
 const text=words(f.get('personaFormationOutcome'));assert(!f.get('personaFormationOutcome').hidden);assert(text.includes('采纳 1 条'));assert(text.includes('2 条未采纳'));assert(!text.includes('采纳 9 条'));assert(text.includes('返回格式不符合要求'));assert(!text.includes('FAKE_PRIVATE'));assert.equal(f.get('personaText').value,'');assert(!words(f.get('personaFormedTraits')).includes('已完成'));
});

test('invalid, empty and skipped persona results never present as a completed personality',()=>{
 const f=fixture();for(const [status,phrase]of [['invalid','未形成人格结果'],['empty','没有补写人格'],['skipped','本批未修改人格']]){
  f.c.renderOrganizer({status:{jobs:[{persona_result:{status,accepted_count:0,applied_count:0,rejected_count:3,reasons:{evidence_count:3},reason:'learning_disabled'}}]}});
  const text=words(f.get('organizerPersonaOutcome'));assert(text.includes(phrase));assert(!text.includes('已完成人格'));assert(!text.includes('形成 3 条'));
 }
 f.S.libraryId='fish-b';f.S.libraryEpoch++;f.c.updateMemoryButtons();assert(f.get('personaFormationOutcome').hidden);assert.equal(f.get('personaFormationOutcome').textContent,'');
});

test('a newly queued persona job does not borrow an older successful result while still pending',async()=>{
 const f=fixture();f.c.api=async route=>route==='persona/organize-preview'?ready():{library_id:'fish-a',status:'queued',job_id:'new-job'};
 await f.c.window.LoveHousePersonaGrowth.openQuick();await f.get('confirmPersonaFormation').click();
 f.c.renderOrganizer({status:{jobs:[{id:'new-job',status:'running'},{id:'old-job',persona_result:{status:'formed',accepted_count:3,applied_count:3,rejected_count:0,reasons:{}}}]}});
 assert(f.get('personaFormationOutcome').hidden);assert(!f.get('personaFormationOutcome').textContent.includes('采纳 3 条'));
});
