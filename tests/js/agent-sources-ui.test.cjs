/* Actual source-management component with inert DOM and scoped local transport. */
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/agent-sources-ui.js'),'utf8');
const plain=x=>JSON.parse(JSON.stringify(x));
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.attributes={};this.events={};this.disabled=false;this.hidden=false;this.open=false;this.checked=false;this.textContent='';this.value='';const classes=new Set();this.classList={add:n=>classes.add(n),contains:n=>classes.has(n)};}
 append(...nodes){for(const n of nodes){this.children.push(n);if(n instanceof Element)n.parent=this;}}
 before(node){const list=this.parent.children;list.splice(list.indexOf(this),0,node);node.parent=this.parent;}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 setAttribute(k,v){this.attributes[k]=String(v);}
 addEventListener(k,v){this.events[k]=v;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 focus(){this.focused=true;}
 select(){this.selected=true;}
 click(){if(!this.disabled)return this.onclick?.();}
}
const all=root=>[root,...root.children.flatMap(x=>x instanceof Element?all(x):[])];
async function flush(){for(let i=0;i<8;i++)await Promise.resolve();}
function fishSource(extra={}){return {id:'source-a',library_id:'fish-a',agent_id:'fish-a',name:'QQ和网页宿主',adapter:'sdk',runtime_agent_id:'runtime-a',enabled:true,revoked:false,capture:{complete_dialogues_saved:2,tool_observations_saved:3},...extra};}
function listing(extra={}){return {agent_id:'fish-a',library_id:'fish-a',sources:[fishSource()],legacy_connections:[],read_only:true,...extra};}
function descriptor(extra={}){return {source:fishSource(),private_path:'/srv/love-house/agent-sources/source-a.json',config_ready:true,model_api_key_required:false,same_machine_config:true,...extra};}
function context({api,mode='serve',demo=false,clipboard}={}){
 const body=new Element('body'),head=new Element('head'),library=new Element('div'),inherit=new Element('button');library.id='libraryPanel';inherit.id='inheritLibraryBtn';library.append(inherit);body.append(library);
 const S={mode,isDemo:demo,libraryChanging:false,libraryId:'fish-a',libraryEpoch:2},MEMORY={busy:false},calls=[],messages=[],harness=[],panels=[];
 const get=id=>[...all(body),...all(head)].find(e=>e.id===id);
 const ctx={S,MEMORY,writeBusy:false,document:{body,head,getElementById:get,createTextNode:text=>({textContent:text})},
 el:(tag,cls,text)=>{const e=new Element(tag);e.className=cls||'';if(text!==undefined)e.textContent=text;return e;},
 api:async(...args)=>{calls.push(plain(args));return api?api(...args):listing();},
 setPanelOpen:(...args)=>panels.push(args),updateMemoryButtons(){},updateWriteState(){ctx.updateMemoryButtons();},libraryName:()=>S.libraryId,toast:x=>messages.push(x),
 navigator:{clipboard:{writeText:clipboard||(async()=>{})}},window:{confirm:()=>true,LoveHouseConnect:{open:x=>harness.push(x)}}};
 vm.runInNewContext(source,ctx);
 async function open(){get('agentSourcesBtn').click();await flush();}
 function form(consent=false){get('agentSourceName').value='AstrBot主宿主';get('agentSourceRuntime').value='stable-runtime-fish';get('agentSourceAdapter').value='astrbot';get('agentSourceConsent').checked=consent;get('agentSourceConsent').onchange();}
 return {ctx,S,MEMORY,calls,messages,get,body,head,harness,panels,open,form};
}

test('source view reads one fixed identity and never claims full coverage or enumerates another library',async()=>{
 const c=context();await c.open();assert.deepEqual(c.calls,[['agent/sources',null,{libraryId:'fish-a'}]]);
 const words=all(c.body).map(x=>x.textContent).join('\n');assert(words.includes('配置就绪不代表所有软件已覆盖'));
 assert(words.includes('整理经历另行核验')); assert(words.includes('未适配的活动不会自动出现'));assert(!words.includes('已覆盖全部'));
});

test('creating a source needs explicit same-fish consent and sends no model key or token',async()=>{
 const c=context({api:async(route,body)=>body?descriptor():listing()});await c.open();c.form(false);
 await c.get('createAgentSource').click();assert.equal(c.calls.length,1);assert.equal(c.get('createAgentSource').disabled,true);
 c.form(true);await c.get('createAgentSource').click();await flush();
 const call=c.calls.find(x=>x[0]==='agent/sources'&&x[1]);assert.deepEqual(call,['agent/sources',{name:'AstrBot主宿主',adapter:'astrbot',runtime_agent_id:'stable-runtime-fish',platforms:['*']},{libraryId:'fish-a'}]);
 assert.equal(c.get('agentSourceConfigPath').value,descriptor().private_path);assert.equal(c.get('agentSourceConsent').checked,false);
 assert(!/api_key|token|mcpServers/i.test(JSON.stringify(call)));assert.equal(c.MEMORY.busy,false);assert.equal(c.ctx.writeBusy,false);
});

test('the path is explicitly same-machine configuration, not an MCP bundle or portable cloud path',async()=>{
 const c=context({api:async(route,body)=>body?descriptor():listing()});await c.open();c.form(true);await c.get('createAgentSource').click();await flush();
 const words=all(c.body).map(x=>x.textContent).join('\n');assert(words.includes('云服务器需在服务器上生成配置'));
 assert(words.includes('不能直接搬用 Mac 的路径'));assert(words.includes('SDK 连接器'));
 const inputs=all(c.body).filter(x=>x.tagName==='INPUT');assert(!inputs.some(x=>/key|token/i.test(x.id||'')));
 assert(!c.get('agentSourceConfigPath').value.includes('mcpServers'));
});

test('mismatched top-level identity is not displayed',async()=>{
 const c=context({api:async()=>listing({agent_id:'different',sources:[fishSource({name:'OTHER_FISH_NAME'})]})});await c.open();
 assert(!all(c.body).some(x=>x.textContent==='OTHER_FISH_NAME'));assert(c.get('agentSourcesStatus').textContent.includes('身份不一致'));
});

test('a source nested under the wrong owner is not displayed or actionable',async()=>{
 const c=context({api:async()=>listing({sources:[fishSource({library_id:'different',agent_id:'different',name:'WRONG_OWNER_SOURCE'})]})});await c.open();
 assert(!all(c.body).some(x=>x.textContent==='WRONG_OWNER_SOURCE'));assert.equal(c.get('source-config-source-a'),undefined);
});

test('a late library response is discarded after the selected fish changes',async()=>{
 let resolve;const c=context({api:()=>new Promise(r=>resolve=r)});c.get('agentSourcesBtn').click();
 c.S.libraryId='fish-b';c.S.libraryEpoch++;c.ctx.updateMemoryButtons();resolve(listing({sources:[fishSource({name:'STALE_SOURCE'})]}));await flush();
 assert.equal(c.get('agentSourcesDialog').open,false);assert(!all(c.body).some(x=>x.textContent==='STALE_SOURCE'));
});

test('pausing one source uses its exact ID and does not disconnect other sources',async()=>{
 const c=context({api:async(route,body)=>body?{source:fishSource({enabled:false})}:listing({sources:[fishSource(),fishSource({id:'source-b',name:'另一个来源'})]})});await c.open();
 await c.get('source-pause-source-a').click();await flush();
 const mutations=c.calls.filter(x=>x[1]);assert.deepEqual(mutations,[['agent/sources/source-a/enabled',{enabled:false},{libraryId:'fish-a'}]]);
 assert(!mutations.some(x=>x[0].includes('source-b')));assert.equal(c.MEMORY.busy,false);
});

test('a mismatched configuration response cannot expose another source private path',async()=>{
 const c=context({api:async(route,body)=>body?descriptor({source:fishSource({library_id:'wrong',agent_id:'wrong'}),private_path:'/private/OTHER_AGENT_CONFIG'}):listing()});await c.open();
 await c.get('source-config-source-a').click();await flush();assert.equal(c.get('agentSourceConfigPath').value,'');
});

test('source creation error retains the form without claiming a saved credential',async()=>{
 const c=context({api:async(route,body)=>{if(body)throw Error('synthetic write failure');return listing();}});await c.open();c.form(true);
 await c.get('createAgentSource').click();await flush();assert.equal(c.get('agentSourceConfigPath').value,'');assert.equal(c.get('agentSourceConsent').checked,true);
 assert(c.get('agentSourcesStatus').textContent.includes('未能确认'));assert.equal(c.ctx.writeBusy,false);
});

test('old Harness flow remains a separate verified window connection',async()=>{
 const c=context();await c.open();c.get('addHarnessSource').click();assert.deepEqual(c.harness,['harness']);assert.equal(c.get('agentSourcesDialog').open,false);
});

test('clipboard failure cannot select a newer source configuration that was not the copied target',async()=>{
 let rejectClipboard;
 const second=fishSource({id:'source-b',name:'第二来源'});
 const c=context({clipboard:()=>new Promise((resolve,reject)=>rejectClipboard=reject),api:async(route,body)=>{
  if(!body)return listing({sources:[fishSource(),second]});
  if(route.includes('source-b'))return descriptor({source:second,private_path:'/srv/love-house/agent-sources/source-b.json'});
  return descriptor();
 }});
 await c.open();await c.get('source-config-source-a').click();await flush();
 const pending=c.get('copyAgentSourcePath').click();await c.get('source-config-source-b').click();await flush();
 rejectClipboard(Error('synthetic permission denied'));await pending;
 assert.notEqual(c.get('agentSourceConfigPath').selected,true);
 assert(!c.messages.some(x=>x.includes('已选中')));
});


test('new source uses a stable default identity for the selected fish without requiring advanced input',async()=>{
 const c=context({api:async(route,body)=>body?descriptor():listing()});await c.open();
 assert.equal(c.get('agentSourceRuntime').value,'lovehouse_fish-a');assert.equal(c.get('agentSourceIdentityAdvanced').open,false);
 assert(c.get('agentSourceName').value.includes('fish-a'));c.get('agentSourceAdapter').value='astrbot';
 c.get('agentSourceConsent').checked=true;c.get('agentSourceConsent').onchange();await c.get('createAgentSource').click();await flush();
 assert.equal(c.calls.find(x=>x[1])?.[1].runtime_agent_id,'lovehouse_fish-a');
 c.S.libraryId='fish-b';c.S.libraryEpoch++;c.ctx.updateMemoryButtons();await c.open();
 assert.equal(c.get('agentSourceRuntime').value,'lovehouse_fish-b');assert(c.get('agentSourceName').value.includes('fish-b'));assert(!c.get('agentSourceName').value.includes('fish-a'));
});

test('output-only receipts and returned material are separate, truthful source states',async()=>{
 const c=context({api:async()=>listing({sources:[fishSource({capture:{complete_dialogues_saved:0,tool_observations_saved:0,outputs_saved:4},archive_status:'outputs_only',last_recall:{at:1700000000,organized_count:2,source_count:1,other_count:0}})]})});await c.open();
 const words=all(c.body).map(x=>x.textContent).join('\n');assert(words.includes('已收到真实输出'));assert(words.includes('独立输出 4 条'));assert(words.includes('完整对话 0 轮'));assert(words.includes('整理记忆 2 条、原始资料 1 条'));assert(words.includes('不证明模型已经采用'));
});

test('configuration-only source does not claim that capture or organized recall has been verified',async()=>{
 const c=context({api:async()=>listing({sources:[fishSource({capture:{},config_ready:true,host_online:true})]})});await c.open();
 const words=all(c.body).map(x=>x.textContent).join('\n');assert(words.includes('配置就绪 · 等待运行程序'));assert(!words.includes('已收到真实输出'));assert(words.includes('尚未核验召回来源'));
});

test('switching requested configuration clears previous private path and bound identity on a bad response',async()=>{
 let n=0;const c=context({api:async(route,body)=>{if(!body)return listing();return ++n===1?descriptor():descriptor({source:fishSource({library_id:'wrong',agent_id:'wrong'}),private_path:'/private/WRONG'});}});await c.open();
 await c.get('source-config-source-a').click();await flush();assert.equal(c.get('agentSourceBoundIdentity').value,'runtime-a');
 await c.get('source-config-source-a').click();await flush();assert.equal(c.get('agentSourceConfigPath').value,'');assert.equal(c.get('agentSourceBoundIdentity').value,'');assert(c.get('agentSourcesStatus').textContent.includes('未能确认'));
});

test('opening a registered connection uses its source configuration under the selected library',async()=>{
 const s=fishSource({connection_id:'conn-a'}),c=context({api:async(route,body)=>body?descriptor({source:s}):listing({sources:[s]})});
 await c.ctx.window.LoveHouseSources.openForConnection('conn-a');
 assert(c.get('agentSourcesDialog').open);assert.equal(c.get('agentSourceConfigPath').value,descriptor().private_path);assert.deepEqual(c.calls.filter(x=>x[1]),[['agent/sources/source-a/config',{},{libraryId:'fish-a'}]]);
});

test('a registered source from another library cannot be opened by a stale connection response',async()=>{
 let resolve;const c=context({api:()=>new Promise(r=>resolve=r)});const pending=c.ctx.window.LoveHouseSources.openForConnection('conn-a');
 c.S.libraryId='fish-b';c.S.libraryEpoch++;c.ctx.updateMemoryButtons();resolve(listing({sources:[fishSource({connection_id:'conn-a'})]}));await pending;
 assert(!c.get('agentSourcesDialog').open);assert.equal(c.get('agentSourceConfigPath').value,'');assert.equal(c.calls.length,1);
});


test('overlapping same-library configuration requests cannot reopen an older source after the latest selection',async()=>{
 const pending=[];const second=fishSource({id:'source-b',connection_id:'conn-b'});let reads=0;
 const current=listing({sources:[fishSource({connection_id:'conn-a'}),second]});
 const c=context({api:async(route,body)=>{if(body)return descriptor({source:second});if(++reads<=2)return new Promise(r=>pending.push(r));return current;}});
 const first=c.ctx.window.LoveHouseSources.openForConnection('conn-a');const latest=c.ctx.window.LoveHouseSources.openForConnection('conn-b');
 pending[1](current);await latest;pending[0](current);await first;
 assert.deepEqual(c.calls.filter(x=>x[1]).map(x=>x[0]),['agent/sources/source-b/config']);
});

test('source organizer button opens this archive read-only controls without invoking a model',async()=>{
 const c=context();await c.open();c.get('source-organizer-source-a').click();assert.deepEqual(c.panels,[['organizerPanel',true]]);assert.equal(c.calls.length,1);assert(!c.get('agentSourcesDialog').open);
});
