/* Exercise shipped configuration labels and async save/read actions without a provider. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/memory-organizer-ui.js'),'utf8');
const plain=x=>JSON.parse(JSON.stringify(x));
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function declaration(name){const start=source.indexOf('function '+name+'('),end=source.indexOf('\n}',start);assert(start>=0&&end>=0,name);return source.slice(source.slice(start-6,start)==='async '?start-6:start,end+2);}
function saved(overrides={}){return {library_id:'one',settings:{provider_mode:'separate',provider_id:'separate',enabled:false,base_url:'https://api.deepseek.com',model:'synthetic-model'},provider:{base_url:'https://api.deepseek.com',model:'synthetic-model',credential_ready:true,model_ready:true,key_saved:true},batches:[],...overrides};}
function context(){
 const elements=new Map(),by=id=>{if(!elements.has(id))elements.set(id,{value:'',checked:false,textContent:'',dataset:{},disabled:false,setAttribute(k,v){this[k]=v;}});return elements.get(id);};
 const ctx={URL,window:{},ORGANIZER:{data:null,version:0,dirty:false},S:{mode:'serve',libraryId:'one',libraryEpoch:1,libraryChanging:false},UI:{configOwner:null,configRequestOwner:null,configReadFailed:false},MEMORY:{busy:false,catalogReady:true},writeBusy:false,
  by,apiStatus:by('apiStatus'),apiTitle:by('apiTitle'),apiModel:by('apiModel'),apiCredential:by('apiCredential'),apiVerification:by('apiVerification'),libraryApi:by('libraryApi'),settings:{},num:(x,f=0)=>Number.isFinite(+x)?+x:f,
  libraryName:id=>'Library '+id,organizerSummary:()=> '待整理 0',canWrite:()=>true,updateWriteState(){},toasts:[],toast(message,error){ctx.toasts.push({message,error});},refreshConnections:async()=>{},
  api:async()=>{throw Error('No default transport');},threshold:{value:'20'},cadence:{value:'batch'},batch:{value:'6'},providerPayload:()=>({base_url:'https://api.deepseek.com',model:'synthetic-model',api_key:'SYNTHETIC-SECRET',save_key:true})};
 ctx.context=()=>({id:ctx.S.libraryId,epoch:ctx.S.libraryEpoch});ctx.current=o=>!!o&&o.id===ctx.S.libraryId&&o.epoch===ctx.S.libraryEpoch;
 ctx.UI.configOwner=ctx.context();
 for(const name of ['configurationLabel','renderConfiguration','refreshConfiguration','ensureConfiguration'])ctx[name]=vm.runInNewContext(declaration(name)+';'+name,ctx);
 ctx.refreshOrganizer=ctx.refreshConfiguration;
 ctx.renderOrganizer=data=>{ctx.ORGANIZER.data=data;ctx.UI.configOwner=ctx.context();ctx.renderConfiguration(data);};
 const start=source.indexOf('saveOrganizerSettings=async function('),end=source.indexOf('\nby(\'saveOrganizerSettings\').onclick',start);
 ctx.save=vm.runInNewContext(source.slice(start,end)+';saveOrganizerSettings',ctx);
 by('organizerMode').value='separate';by('organizerCallLimit').value='100';by('organizerCharLimit').value='200000';
 return ctx;
}
test('saved, temporary, missing and incomplete credentials are distinct without claiming network success',()=>{
 const c=context();const configured=c.configurationLabel(saved());assert.equal(configured.state,'saved');assert.match(configured.title,/已配置记忆整理API/);assert.match(configured.model,/DeepSeek · synthetic-model/);assert.match(configured.verification,/尚未确认 API 联网可用/);
 assert.equal(c.configurationLabel(saved({provider:{credential_ready:true,model_ready:true,key_saved:false}})).state,'session_only');
 assert.equal(c.configurationLabel(saved({provider:{credential_ready:false,model_ready:false,key_saved:false}})).state,'credential_missing');
 assert.equal(c.configurationLabel(saved({provider:{credential_ready:true,model_ready:false}})).state,'incomplete');
 assert.equal(c.configurationLabel(saved({settings:{},provider:{}})).state,'not_configured');
 assert.equal(c.configurationLabel(saved({provider:{credential_ready:true}})).state,'incomplete');
 assert.equal(c.configurationLabel(saved({configuration:{configured:true,state:'saved'},provider:{credential_ready:false,model_ready:false}})).state,'credential_missing');
});
test('a failed real API attempt remains visible and cannot be described as verified or ready',()=>{
 const c=context(),data=saved({batches:[{status:'failed',error_code:'provider_authentication',updated:20,error:'UNTRUSTED-SECRET'},{status:'done',updated:10}]});
 c.renderOrganizer(data);assert.equal(c.apiStatus.dataset.state,'call_failed');assert.match(c.apiTitle.textContent,/最近调用失败/);assert.match(c.libraryApi.textContent,/最近调用失败/);assert.match(c.apiVerification.textContent,/密钥被服务拒绝/);assert(!JSON.stringify([c.apiTitle,c.apiModel,c.apiCredential,c.apiVerification,c.libraryApi]).includes('UNTRUSTED-SECRET'));
 data.batches.push({status:'done',updated:30});assert.equal(c.configurationLabel(data).state,'saved');assert.match(c.configurationLabel(data).verification,/尚未确认 API 联网可用/);
});
test('saving updates the confirmed configuration before a subsequent read, even if that read fails',async()=>{
 const c=context(),calls=[];let finishRead;c.ORGANIZER.dirty=true;
 c.api=async(route,body,options)=>{calls.push({route,options:plain(options)});if(route==='organizer/settings')return saved();return new Promise((resolve,reject)=>finishRead=reject);};
 const pending=c.save();await settle();assert.equal(c.apiStatus.dataset.state,'saved');assert.equal(c.ORGANIZER.dirty,false);assert.equal(c.by('organizerProviderKey').value,'');
 finishRead(Error('synthetic read failure'));await pending;assert.equal(c.apiStatus.dataset.state,'saved');assert.match(c.apiVerification.textContent,/最新状态暂时读不到/);assert.match(c.by('organizerNotice').textContent,/配置已保存/);
 assert.deepEqual(calls,[{route:'organizer/settings',options:{libraryId:'one'}},{route:'organizer',options:{libraryId:'one'}}]);assert(!JSON.stringify([c.apiTitle,c.apiModel,c.apiCredential,c.apiVerification,c.libraryApi]).includes('SYNTHETIC-SECRET'));
});
test('a rejected save keeps the previous confirmed state and the draft',async()=>{
 const c=context();c.renderOrganizer({settings:{},provider:{}});c.ORGANIZER.dirty=true;c.api=async()=>{throw Error('synthetic save rejected');};
 await c.save();assert.equal(c.apiStatus.dataset.state,'not_configured');assert.equal(c.ORGANIZER.dirty,true);assert.match(c.by('organizerNotice').textContent,/仍是上次已保存配置/);assert(!c.toasts.some(x=>/配置已保存/.test(x.message)));
});
test('switching libraries discards an old read, including switching away and back with a new epoch',async()=>{
 const c=context();let finish;c.api=()=>new Promise(resolve=>finish=resolve);const pending=c.refreshOrganizer();await settle();
 c.S.libraryId='two';c.S.libraryEpoch++;c.ORGANIZER.version++;c.ORGANIZER.data=null;c.UI.configOwner=null;c.MEMORY.catalogReady=false;c.ensureConfiguration();assert.equal(c.apiStatus.dataset.state,'unknown');assert(!c.apiModel.textContent.includes('synthetic-model'));
 // Suppress the new-library automatic read in this test; the old result cannot paint either library.
 c.S.libraryId='one';c.S.libraryEpoch++;finish(saved());await pending;assert.equal(c.apiStatus.dataset.state,'unknown');assert.equal(c.ORGANIZER.data,null);
});
test('a save finishing after a switch does not alter the next library or clear its key field',async()=>{
 const c=context();c.by('organizerProviderKey').value='CURRENT-DRAFT';c.api=async()=>{c.S.libraryId='two';c.S.libraryEpoch++;c.by('organizerNotice').textContent='NEXT_LIBRARY';return saved();};
 await c.save();assert.equal(c.ORGANIZER.data,null);assert.equal(c.by('organizerNotice').textContent,'NEXT_LIBRARY');assert.equal(c.by('organizerProviderKey').value,'CURRENT-DRAFT');assert.equal(c.toasts.length,0);
});
test('a mismatched backend scope and an initial read failure never mark the API as configured',async()=>{
 const c=context();c.UI.configOwner=null;c.api=async()=>saved({library_id:'other'});await c.refreshOrganizer();assert.equal(c.apiStatus.dataset.state,'unknown');assert.equal(c.ORGANIZER.data,null);
 c.api=async()=>{throw Error('unavailable');};await c.refreshOrganizer();assert.equal(c.apiStatus.dataset.state,'unknown');assert.match(c.apiVerification.textContent,/最新状态暂时读不到/);
});
test('unread configuration cannot save a previous library form into a new library',async()=>{
 const c=context();let calls=0;c.api=async()=>{calls++;return saved();};c.S.libraryEpoch++;await c.save();assert.equal(calls,0);assert.match(c.toasts[0].message,/当前库的整理设置还未读取/);
});
test('library scope invalidates a visible old badge before the next response',()=>{
 const c=context();c.renderOrganizer(saved());c.UI.configRequestOwner=c.context();c.S.libraryChanging=true;c.S.libraryEpoch++;c.ensureConfiguration();assert.equal(c.apiStatus.dataset.state,'unknown');assert.equal(c.apiModel.textContent,'');assert.match(c.libraryApi.textContent,/切换中/);
 c.S.libraryChanging=false;c.S.libraryId='two';c.MEMORY.catalogReady=false;c.ensureConfiguration();assert.equal(c.apiStatus.dataset.state,'unknown');assert.equal(c.by('organizerMiniStatus').textContent,'API状态待确认');
});
