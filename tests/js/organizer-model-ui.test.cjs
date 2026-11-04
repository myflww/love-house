/* Execute the shipped model component and its actual organizer save hook. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/organizer-model-ui.js'),'utf8');
const saveSource=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/memory-organizer-ui.js'),'utf8');
const plain=value=>JSON.parse(JSON.stringify(value));
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return{promise,resolve,reject};};

function harness(){
 const elements=new Map();
 class Element{
  constructor(tag,text=''){this.tagName=tag.toUpperCase();this.textContent=text;this.children=[];this.parentElement=null;this.dataset={};this.listeners=new Map();this.disabled=false;this._value='';}
  set id(value){this._id=value;elements.set(value,this);}get id(){return this._id;}
  get options(){return this.children.filter(c=>c.tagName==='OPTION');}
  set value(value){this._value=String(value);}get value(){return this._value;}
  get previousElementSibling(){const list=this.parentElement?.children||[];return list[list.indexOf(this)-1]||null;}
  setAttribute(key,value){this[key]=value;}
  append(...items){for(const item of items){if(item.parentElement)item.parentElement.children.splice(item.parentElement.children.indexOf(item),1);item.parentElement=this;this.children.push(item);}if(this.tagName==='SELECT'&&!this._value)this._value=this.options[0]?.value||'';}
  insertBefore(item,anchor){assert.equal(anchor.parentElement,this,'insertion anchor must belong to settings');if(item.parentElement)item.parentElement.children.splice(item.parentElement.children.indexOf(item),1);item.parentElement=this;this.children.splice(this.children.indexOf(anchor),0,item);}
  after(item){const parent=this.parentElement,index=parent.children.indexOf(this);item.parentElement=parent;parent.children.splice(index+1,0,item);}
  replaceChildren(...items){for(const item of this.children)item.parentElement=null;this.children=[];this._value='';this.append(...items);}
  addEventListener(type,fn){if(!this.listeners.has(type))this.listeners.set(type,[]);this.listeners.get(type).push(fn);}
  emit(type){for(const fn of this.listeners.get(type)||[])fn({target:this});}
 }
 const el=(tag,cls,text)=>new Element(tag,text),by=id=>elements.get(id);
 const settings=el('details');settings.id='organizerSettings';
 for(const [id,tag,value] of [['organizerMode','select','separate'],['organizerConnection','select',''],
  ['organizerProviderBaseUrl','input','https://gateway.invalid/v1'],['organizerProviderModel','input','manual-model'],
  ['organizerProviderKey','input',''],['organizerCadence','select','batch'],['organizerBatchSize','input','6'],
  ['organizerEnabled','input',''],['organizerNotice','p',''],['saveOrganizerSettings','button','']]){
  const label=el('label');label.htmlFor=id;const input=el(tag);input.id=id;input.value=value;settings.append(label,input);
 }
 const c={document:{getElementById:by},window:{},el,Array,Number,JSON,
  S:{mode:'serve',libraryId:'one',libraryEpoch:1,libraryChanging:false},ORGANIZER:{dirty:false,version:0,data:null},
  resetLibraryView(){c.ORGANIZER.dirty=false;},
  renderOrganizer(data){c.ORGANIZER.data=data;if(!c.ORGANIZER.dirty){const p=data.settings||{};for(const [id,key] of [['organizerMode','provider_mode'],['organizerConnection','connection_id'],['organizerProviderBaseUrl','base_url'],['organizerProviderModel','model']])if(p[key]!==undefined)by(id).value=p[key];}},
  calls:[],api:async(route,body,options)=>{c.calls.push({route,body:plain(body),options:plain(options||{})});return c.reply(route,body,options);},
  reply:async()=>({library_id:'one',models:[]})};
 vm.createContext(c);vm.runInContext(source,c,{filename:'actual-organizer-model-ui.js'});
 const profile=(changes={})=>({library_id:c.S.libraryId,settings:{provider_mode:'separate',connection_id:'',
  base_url:'https://gateway.invalid/v1',model:'manual-model',reasoning_effort:'auto',context_window:0,max_output_tokens:0,...changes}});
 c.renderOrganizer(profile());
 const values=id=>by(id).options.map(o=>o.value);
 return{c,by,values,profile,settings};
}

test('automatic limits serialize as zero and unknown providers retain usable generic effort options',()=>{
 const {c,by,values}=harness();
 assert.deepEqual(plain(c.window.LoveHouseOrganizerModels.settingsPayload()),{reasoning_effort:'auto',context_window:0,max_output_tokens:0,max_input_chars:0});
 assert.equal(by('organizerContextWindow').value,'');assert.equal(by('organizerMaxOutputTokens').value,'');
 assert.deepEqual(values('organizerReasoningEffort'),['auto','none','low','medium','high','xhigh','max']);
 assert.match(by('organizerModelCapabilities').textContent,/由服务决定/);assert.match(by('organizerModelCapabilities').textContent,/需.*服务支持/);
 by('organizerReasoningEffort').value='high';by('organizerReasoningEffort').emit('input');
 assert.equal(c.window.LoveHouseOrganizerModels.settingsPayload().reasoning_effort,'high');assert.equal(c.ORGANIZER.dirty,true);
});

test('actual discovery renders the model datalist, provider limits and supported effort choices',async()=>{
 const {c,by,values}=harness();
 c.reply=async()=>({library_id:'one',selected_model:'manual-model',models:[{id:'manual-model',name:'模型甲',context_window:128000,max_output_tokens:32000,effort:{supported_levels:['low','high']}},{id:'other-model',name:'模型乙'}]});
 await by('organizerReadModels').onclick();
 assert.deepEqual(values('organizerAvailableModels'),['manual-model','other-model']);
 assert.equal(by('organizerAvailableModels').options[0].textContent,'模型甲');
 assert.deepEqual(values('organizerReasoningEffort'),['auto','none','low','high']);
 assert.match(by('organizerModelCapabilities').textContent,/128,000/);assert.match(by('organizerModelCapabilities').textContent,/32,000/);
 assert.equal(c.calls.length,1);assert.equal(c.calls[0].route,'organizer/models');assert.deepEqual(c.calls[0].options,{libraryId:'one'});
 by('organizerProviderModel').value='other-model';by('organizerProviderModel').emit('input');
 assert.match(by('organizerModelCapabilities').textContent,/由服务决定/);assert(values('organizerReasoningEffort').includes('medium'));
});

test('connection discovery uses its actual selected model, ignoring the hidden separate-model input',async()=>{
 const {c,by,values,profile}=harness();
 c.renderOrganizer(profile({provider_mode:'connection',connection_id:'connection-A',model:'hidden-stale-model'}));
 by('organizerProviderKey').value='DO-NOT-SEND-HIDDEN-KEY';
 c.reply=async()=>({library_id:'one',selected_model:'actual-connected-model',models:[
  {id:'hidden-stale-model',context_window:8192,effort:{supported_levels:['low']}},
  {id:'actual-connected-model',context_window:1048576,effort:{supported_levels:['high','max']}}]});
 await by('organizerReadModels').onclick();
 assert.match(by('organizerModelCapabilities').textContent,/1,048,576/);
 assert.deepEqual(values('organizerReasoningEffort'),['auto','none','high','max']);
 assert.equal(c.calls[0].body.connection_id,'connection-A');assert.equal(c.calls[0].body.api_key,undefined);assert.equal(c.calls[0].body.base_url,undefined);
});

test('positive custom token counts save exactly and blank values restore automatic maximum',()=>{
 const {c,by}=harness();
 by('organizerContextWindow').value='1048576';by('organizerMaxOutputTokens').value='32768';by('organizerReasoningEffort').value='medium';
 assert.deepEqual(plain(c.window.LoveHouseOrganizerModels.settingsPayload()),{reasoning_effort:'medium',context_window:1048576,max_output_tokens:32768,max_input_chars:0});
 for(const value of ['0','-1','1.5','NaN','Infinity','9007199254740992']){
  by('organizerContextWindow').value=value;assert.throws(()=>c.window.LoveHouseOrganizerModels.settingsPayload(),/正整数/);
 }
 by('organizerContextWindow').value='';by('organizerMaxOutputTokens').value='';assert.equal(c.window.LoveHouseOrganizerModels.settingsPayload().context_window,0);
});

test('saved custom effort survives unavailable discovery while known unsupported choices reset to auto',()=>{
 const {c,by,values,profile}=harness();
 c.renderOrganizer(profile({reasoning_effort:'provider_special',context_window:200000,max_output_tokens:50000}));
 assert.equal(by('organizerReasoningEffort').value,'provider_special');assert(values('organizerReasoningEffort').includes('provider_special'));
 c.renderOrganizer({...profile({reasoning_effort:'provider_special'}),model_capabilities:{effort:{supported_levels:['low','high']}}});
 assert.deepEqual(values('organizerReasoningEffort'),['auto','none','low','high']);assert.equal(by('organizerReasoningEffort').value,'auto');
});

test('library switches and away/back epochs clear old model controls and ignore late discovery',async()=>{
 const {c,by,values,profile}=harness(),request=deferred();c.reply=()=>request.promise;
 const pending=by('organizerReadModels').onclick();
 c.S.libraryId='two';c.S.libraryEpoch++;c.resetLibraryView();c.renderOrganizer({...profile({model:'second-model'}),library_id:'two'});
 assert.deepEqual(values('organizerAvailableModels'),[]);assert.equal(by('organizerContextWindow').value,'');
 c.S.libraryId='one';c.S.libraryEpoch++;c.resetLibraryView();c.renderOrganizer(profile());
 request.resolve({library_id:'one',models:[{id:'OLD-LIBRARY-MODEL',context_window:99999}]});await pending;
 assert.deepEqual(values('organizerAvailableModels'),[]);assert(!by('organizerModelCapabilities').textContent.includes('99,999'));
});

test('changing the API, connection or credential invalidates in-flight responses without exposing keys',async()=>{
 for(const [id,value,event] of [['organizerProviderBaseUrl','https://new.invalid/v1','input'],['organizerConnection','new-connection','change'],['organizerProviderKey','NEW-SYNTHETIC-KEY','input']]){
  const {c,by,values}=harness(),request=deferred();c.reply=()=>request.promise;const pending=by('organizerReadModels').onclick();
  by(id).value=value;by(id).emit(event);
  request.resolve({library_id:'one',models:[{id:'OLD-ENDPOINT-MODEL',context_window:99999}]});await pending;
  assert.deepEqual(values('organizerAvailableModels'),[]);assert(!by('organizerModelCapabilities').textContent.includes('99,999'));
  assert(!by('organizerModelCapabilities').textContent.includes('NEW-SYNTHETIC-KEY'));assert.equal(by('organizerReadModels').disabled,false);
 }
});

test('mismatched-library responses cannot paint capabilities and discovery failures keep manual choices',async()=>{
 const {c,by,values}=harness();c.reply=async()=>({library_id:'other',models:[{id:'FOREIGN',context_window:99999}]});
 await by('organizerReadModels').onclick();assert.deepEqual(values('organizerAvailableModels'),[]);assert.match(by('organizerModelCapabilities').textContent,/不属于当前库/);
 c.reply=async()=>{throw Error('synthetic offline');};await by('organizerReadModels').onclick();
 assert.match(by('organizerModelCapabilities').textContent,/仍可手动填写/);assert(values('organizerReasoningEffort').includes('high'));assert.equal(by('organizerReadModels').disabled,false);
});

test('discovery errors cannot echo a credential entered in the password field',async()=>{
 const {c,by}=harness(),secret='SYNTHETIC-UNSAVED-SECRET';by('organizerProviderKey').value=secret;
 c.reply=async()=>{throw Error('synthetic failure '+secret);};await by('organizerReadModels').onclick();
 assert(!by('organizerModelCapabilities').textContent.includes(secret));assert.match(by('organizerModelCapabilities').textContent,/密钥已隐藏/);
});

test('actual save hook submits selected settings and clears the API key without rendering it',async()=>{
 const {c,by,profile}=harness(),secret='SYNTHETIC-KEY-NOT-A-REAL-SECRET';
 Object.assign(c,{by,canWrite:()=>true,MEMORY:{busy:false},UI:{busy:false,configOwner:{id:'one',epoch:1}},
  context:()=>({id:c.S.libraryId,epoch:c.S.libraryEpoch}),current:o=>o.id===c.S.libraryId&&o.epoch===c.S.libraryEpoch,
  threshold:{value:'20'},cadence:{value:'batch'},batch:{value:'6'},num:Number,writeBusy:false,
  providerPayload:()=>({base_url:by('organizerProviderBaseUrl').value,model:by('organizerProviderModel').value,api_key:by('organizerProviderKey').value,save_key:true}),
  updateWriteState(){},toast(){},refreshOrganizer:async()=>true});
 by('organizerProviderKey').value=secret;by('organizerContextWindow').value='200000';by('organizerMaxOutputTokens').value='50000';by('organizerReasoningEffort').value='high';
 c.reply=async(route,body)=>({...profile(body),provider:{model:body.model,credential_ready:true}});
 const start=saveSource.indexOf('saveOrganizerSettings=async function('),end=saveSource.indexOf("\nby('saveOrganizerSettings').onclick",start);
 const save=vm.runInContext(saveSource.slice(start,end)+';saveOrganizerSettings',c);await save();
 assert.equal(c.calls.length,1);const body=c.calls[0].body;
 assert.equal(body.api_key,secret);assert.equal(body.context_window,200000);assert.equal(body.max_output_tokens,50000);assert.equal(body.reasoning_effort,'high');assert.equal(body.max_input_chars,0);
 assert.equal(by('organizerProviderKey').value,'');assert(!by('organizerModelCapabilities').textContent.includes(secret));
 assert.equal(c.ORGANIZER.dirty,false);
});
