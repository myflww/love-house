const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/connection-ux.js'),'utf8');
function extract(name){const match=source.match(new RegExp('(?:async )?function '+name+'\\([^]*?\\n\\}'));assert(match,`missing actual UI function ${name}`);return match[0];}
const pureNames=['registeredSource','connectionPolicy','boundSession','savedDialogue','connectionCapabilities','hookReceiptCaption','agentPrivatePath'];
function load(name,globals={}){return vm.runInNewContext(pureNames.filter(x=>x!==name).map(extract).join('\n')+'\n'+extract(name)+';'+name,globals);}
const payload=load('connectionPayload'),mcp=load('agentMcpText');
const setupCode=source.match(/function agentMcpText\([^]*?\n\}/)[0]+'\n'+source.match(/function agentSetupText\([^]*?\n\}/)[0]+';agentSetupText';
const setup=vm.runInNewContext(setupCode);
const state=load('connectionState');
const plain=value=>JSON.parse(JSON.stringify(value));
const config={mcpServers:{'love-house-memory':{command:'/Applications/Love House.app/python',args:['--connection-config','/private/memory.json'],env:{PYTHONDONTWRITEBYTECODE:'1'}}}};
test('agent memory connection has no vendor provider payload, even when old model data exists',()=>{
 const provider={get api_key(){throw new Error('must never read vendor key');}};
 assert.deepEqual(plain(payload({name:'My agent',host:'agent',library_id:'lib-a',session_scope:'next_session',provider})),{name:'My agent',host:'agent',library_id:'lib-a',session_scope:'next_session'});
 assert(!('provider' in payload({name:'Harness',host:'harness',library_id:'lib-b',session_scope:'next_session',provider})));
 const vendor={base_url:'https://provider.invalid',model:'custom',api_key:'FAKE-only-advanced'};
 assert.deepEqual(plain(payload({name:'Advanced',host:'api',library_id:'lib-c',session_scope:'connection',provider:vendor})).provider,vendor);
});
test('copy exports only valid MCP config, never the surrounding provider or local client fields',()=>{
 const cfg={connection:{host:'agent'},mcp_config:config,provider:{api_key:'FAKE-VENDOR-NOT-TO-COPY'},client_api_key:'FAKE-OTHER-FIELD'};
 assert.deepEqual(JSON.parse(mcp(cfg)),config);assert(!mcp(cfg).includes('FAKE-VENDOR'));assert(!mcp(cfg).includes('FAKE-OTHER'));
 assert.equal(mcp({...cfg,connection:{host:'api'}}),'');assert.equal(mcp({...cfg,connection:{host:'agent',revoked:true}}),'');
 assert.equal(mcp({connection:{host:'agent'},host_config:'{"base_url":"localhost","api_key":"FAKE"}'}),'');
 assert.deepEqual(JSON.parse(mcp({connection:{host:'agent'},host_config:JSON.stringify(config)})),config);
});
test('agent status never calls MCP tools automatic capture or treats offline restart as lost configuration',()=>{
 assert.equal(state({host:'agent',enabled:true,host_online:true,archive_status:'tools_only'}),'记忆工具已连接');
 assert.equal(state({host:'agent',enabled:true,host_online:false,archive_status:'tools_only'}),'已配置 · 等待 Agent 上线');
 assert.equal(state({host:'agent',enabled:true,host_online:true,archive_status:'automatic_connected'}),'已收到宿主记录');
 assert.equal(state({host:'agent',enabled:false,host_online:true,archive_status:'automatic_connected'}),'已暂停');
 assert.equal(state({host:'api',enabled:true,archive_status:'automatic_connected'}),'已收到对话');
});
test('copy-for-agent fallback explains tool capability, optional hook, and once-saved restart',()=>{
 const cfg={connection:{host:'agent'},mcp_config:config};const text=setup(cfg);
 assert(text.includes('memory_status'));assert(text.includes('轮次结束钩子'));assert(text.includes('配置保存一次'));assert(text.includes('无需提供模型厂商'));
 assert(text.includes(JSON.stringify(config,null,2)));const prepared=setup({...cfg,agent_setup_text:'Fixture setup text'});assert(prepared.endsWith('Fixture setup text'));assert(prepared.includes('能修改运行程序设置'));assert(prepared.includes('QQ'));assert(!prepared.includes('FAKE-VENDOR'));
 assert.equal(setup({connection:{host:'agent'},host_config:'not JSON'}),'');
});

test('single-window scope remains visible and all-session scope requires explicit consent',()=>{const scope=load('windowScopeCaption');assert(scope({session_scope:'next_session'}).includes('目标窗口'));assert(scope({session_scope:'session-one'}).includes('仅固定窗口'));assert(scope({session_scope:'connection'}).includes('多个窗口'));assert(source.includes('allowAllConnectionSessions'));assert(source.includes("scope==='connection'&&!broadCheck.checked"));});

test('Windows can select Harness and busy state is the only platform-independent lock',()=>{
 const controls=new Map();const by=id=>{if(!controls.has(id))controls.set(id,{});return controls.get(id);};
 const choices={harness:{},agent:{},api:{}};
 const ctx={remoteHost:false,androidHost:false,navigator:{platform:'Win32',userAgent:'Windows NT 10.0'},MEMORY:{busy:false,config:null},writeBusy:false,S:{libraryChanging:false},choices,by,canManageMemory:()=>true,wizardStep:1,hostSelect:{value:'harness'},newLib:{checked:false},newLibName:{},startButton:{},close:{},back:{},next:{},agentSetupText:()=>'',agentMcpText:()=>'',connectionConfigPath:()=>'',astrbotChoice:{dataset:{}}};
 Object.assign(ctx,{workbuddyChoice:{},isCurrentAgentConfig:()=>false,agentPrivatePath:()=>'',agentConfigReady:()=>false,pathInput:{},mcpArea:{},setupArea:{},workbuddyStatus:{},clearWorkBuddyPlan(){},workbuddyGuide:{},workbuddyApply:{},copyAgentPath:{},workbuddyNow:{},rebindCancel:{},rebindConfirm:{},rebindDialog:{}});
 const match=source.match(/function sync\([^]*?\nfunction go/);assert(match);vm.runInNewContext(match[0].replace(/\nfunction go$/,'')+';sync();',ctx);
 assert.equal(choices.harness.disabled,false);
 ctx.MEMORY.busy=true;vm.runInNewContext('sync()',ctx);assert.equal(choices.harness.disabled,true);
});

test('manual Harness paths preserve Windows unicode paths and keep wizard/connection values separate',()=>{
 const values={harnessAppPath:'  "D:\\程序\\DeepSeek Harness\\DeepSeek Harness.exe"  ',harnessProfilePath:'  D:\\私人配置  ',guideHarnessAppPath:'E:\\Other Harness',guideHarnessProfilePath:''};
 const ctx={dialog:{open:true},by:id=>({value:values[id]})};const fn=vm.runInNewContext(source.match(/function harnessPathOptions\([^]*?\n\}/)[0]+';harnessPathOptions',ctx);
 assert.deepEqual(plain(fn()),{app_path:'D:\\程序\\DeepSeek Harness\\DeepSeek Harness.exe',profile_dir:'D:\\私人配置'});
 ctx.dialog.open=false;assert.deepEqual(plain(fn()),{app_path:'E:\\Other Harness'});
});

test('the installer plans and applies to the same existing connection and manual paths',async()=>{
 const calls=[];const ctx={dialog:{open:false},MEMORY:{detect:null,config:{host_options:{app_path:'D:\\Harness',profile_dir:'D:\\Profile'}}},harnessPathOptions:()=>({app_path:'E:\\Harness.exe',profile_dir:'E:\\Target Profile'}),api:async(route,body)=>{calls.push({route,body:plain(body)});return body.apply?{applied:true}:{supported:true,detected:{supported:true}};}};
 const fn=vm.runInNewContext(source.match(/async function applyHarness[^\n]+/)[0]+';applyHarness',ctx);await fn('existing-agent');
 assert.equal(calls.length,2);assert(calls.every(c=>c.route==='connections/existing-agent/configure'));
 assert.deepEqual(calls.map(c=>c.body),[{app_path:'E:\\Harness.exe',profile_dir:'E:\\Target Profile',apply:false},{app_path:'E:\\Harness.exe',profile_dir:'E:\\Target Profile',apply:true}]);
 ctx.api=async(route,body)=>{assert.equal(body.apply,false);return {supported:false,message:'unsupported fixture'};};await assert.rejects(fn('existing-agent'),/unsupported fixture/);
});

test('a remote mobile session uses a generic Agent even when an old link requests Harness',async()=>{
 const values=new Map();const by=id=>{if(!values.has(id))values.set(id,{});return values.get(id);};
 const ctx={remoteHost:true,androidHost:false,MEMORY:{busy:false,libraries:[]},canManageMemory:()=>true,refreshLibraries:async()=>{},hostSelect:{value:'harness'},advancedPaths:{},connectionHostChanged:()=>{},by,S:{isDemo:false,libraryId:'same-library'},newLib:{},newLibName:{},go:()=>{},dialog:{showModal:()=>{}},choices:{agent:{focus:()=>{}}}};
 const fn=vm.runInNewContext(source.match(/async function openWizard[^\n]+/)[0]+';openWizard',ctx);await fn('harness');assert.equal(ctx.hostSelect.value,'agent');assert.equal(by('connectionLibrary').value,'same-library');
});

test('Android starts with its phone-local Agent flow instead of a desktop installer',async()=>{
 const values=new Map();const by=id=>{if(!values.has(id))values.set(id,{});return values.get(id);};
 const ctx={remoteHost:false,androidHost:true,MEMORY:{busy:false,libraries:[]},canManageMemory:()=>true,refreshLibraries:async()=>{},hostSelect:{value:'harness'},advancedPaths:{},connectionHostChanged:()=>{},by,S:{isDemo:false,libraryId:'phone-library'},newLib:{},newLibName:{},go:()=>{},dialog:{showModal:()=>{}},choices:{agent:{focus:()=>{}}}};
 const fn=vm.runInNewContext(source.match(/async function openWizard[^\n]+/)[0]+';openWizard',ctx);
 await fn('harness');assert.equal(ctx.hostSelect.value,'agent');assert.equal(by('connectionLibrary').value,'phone-library');
});

test('a complete HTTP MCP connection is copyable without a desktop config file',()=>{
 const ready=vm.runInNewContext(extract('agentPrivatePath')+'\n'+extract('agentMcpText')+'\n'+extract('agentConfigReady')+';agentConfigReady');
 const cfg={connection:{host:'agent'},configuration_ready:true,remote_config:{transport:'streamable-http'},mcp_config:{mcpServers:{phone:{type:'http',url:'http://127.0.0.1:8768/mcp/example'}}}};
 assert.equal(ready(cfg),true);assert.equal(ready({...cfg,configuration_ready:false}),false);
 assert.equal(ready({...cfg,connection:{host:'agent',revoked:true}}),false);
 assert.equal(ready({...cfg,mcp_config:{}}),false);
});


test('binding policy stays stable while the separate bound window controls display and permissions',()=>{
 const scope=load('windowScopeCaption'),capabilities=load('connectionCapabilities');
 const bound={session_scope:'next_session',session_scope_policy:'next_session',bound_session_id:'window-abcdefgh',can_read:true,can_write:true};
 assert(scope(bound).includes('abcdefgh'));assert(!scope(bound).includes('等待'));
 assert(capabilities(bound).includes('保存记忆：可用'));assert(!capabilities(bound).includes('等待来源绑定'));
 const awaiting={...bound,bound_session_id:null,can_write:false,binding_state:'awaiting_source_turn'};
 assert(scope(awaiting).includes('首次真实来源上报'));assert(capabilities(awaiting).includes('保存记忆：等待来源绑定'));
 assert.equal(state({host:'agent',enabled:true,host_online:true,...awaiting}),'可查询 · 写入等待来源绑定');
});

test('single manually reachable hook and legacy automatic state never claim continuous capture',()=>{
 const receipt=load('hookReceiptCaption'),saved=load('savedDialogue');
 const advice=load('agentConnectionAdvice');
 const c={host:'agent',enabled:true,host_online:true,archive_status:'host_reported',capture:{hook_event_count:1,complete_dialogues_saved:1},bound_session_id:'fixed'};
 assert(receipt(c).includes('1 次'));assert(receipt(c).includes('仍依赖宿主'));
 assert(saved(c));assert(advice(c,{}).includes('一次接收不能证明'));
 assert(!state(c).includes('自动'));assert(!state({...c,archive_status:'automatic_connected'}).includes('自动'));
 assert(advice({...c,bound_session_id:null,session_scope_policy:'next_session',can_write:false},{}).includes('MCP 手动补录不会认领'));
});

test('copying a connection path uses only the service supplied actual path',()=>{
 const path=load('connectionConfigPath'),actual='C:\\Users\\fixture\\AppData\\Local\\LoveHouse\\agent-connections\\connection.json';
 assert.equal(path({connection:{host:'agent'},private_path:actual}),actual);
 assert.equal(path({connection:{host:'agent'},mcp_config:config}),'');
 assert.equal(path({connection:{revoked:true},private_path:actual}),'');
});



 test('independent automatic output is reported without claiming it is a complete dialogue',()=>{assert.equal(state({host:'agent',enabled:true,host_online:true,archive_status:'outputs_only'}),'已收到输出');assert.equal(state({host:'agent',enabled:false,host_online:true,archive_status:'outputs_only'}),'已暂停');});


test('registered sources have program labels, configured scope and source-specific actions',()=>{
 const caption=load('connectionCaption'),scope=load('windowScopeCaption'),guide=load('connectionGuideCaption');
 const c={id:'conn-a',host:'agent',library_id:'fish-a',enabled:true,host_online:false,session_scope:'connection',archive_status:'waiting',registered_source:{id:'source-a',adapter:'astrbot',library_id:'fish-a',runtime_agent_id:'fish-runtime'}};
 assert.equal(caption(c),'AstrBot 活动来源');assert.equal(guide(c),'配置 AstrBot 插件');assert(scope(c).includes('已登记'));assert(!scope(c).includes('多个窗口'));assert.equal(state(c),'等待运行程序报送');
 const received={...c,archive_status:'outputs_only'};assert.equal(guide(received),'查看来源配置');assert.equal(state(received),'已收到输出');
 const sdk={...c,registered_source:{...c.registered_source,adapter:'sdk'}};assert.equal(caption(sdk),'执行器活动来源');assert.equal(guide(sdk),'配置执行器连接器');
 const legacy={...c,registered_source:null,host_online:true,archive_status:'tools_only'};assert.equal(caption(legacy),'通用 Agent 记忆');assert(scope(legacy).includes('多个窗口'));assert.equal(state(legacy),'记忆工具已连接');
});

test('metadata from a different archive cannot turn a connection into a verified source',()=>{
 const source=load('registeredSource'),caption=load('connectionCaption'),scope=load('windowScopeCaption'),guide=load('connectionGuideCaption');
 const c={host:'agent',library_id:'fish-a',enabled:true,host_online:true,session_scope:'connection',registered_source:{id:'source-a',adapter:'astrbot',library_id:'fish-b',runtime_agent_id:'runtime-b'}};
 assert.equal(source(c),null);assert(caption(c).includes('身份待核验'));assert(scope(c).includes('身份待核验'));assert(!scope(c).includes('整个连接'));assert.equal(guide(c),'刷新连接信息');assert.equal(state(c),'来源身份待核验');
 for(const bad of [{...c.registered_source,library_id:'fish-a',adapter:'unknown'},{...c.registered_source,library_id:'fish-a',runtime_agent_id:''},{...c.registered_source,library_id:'fish-a',id:''}])assert.equal(source({...c,registered_source:bad}),null);
});

test('scope policy and bound window remain distinct across migration and bound next-session policy',()=>{
 const caption=load('windowScopeCaption');
 assert(caption({session_scope_policy:'next_session',session_scope:'next_session',bound_session_id:'real-window-4826'}).endsWith('dow-4826'));
 assert(caption({session_scope_policy:'fixed',session_scope:'fixed',bound_session_id:'actual-fixed-3333'}).endsWith('xed-3333'));
 assert(caption({session_scope_policy:'fixed',session_scope:'fixed',bound_session_id:null}).includes('等待来源核对'));
 assert(!caption({session_scope:'fixed'}).endsWith('fixed'));
 assert(caption({session_scope_policy:'any',bound_session_id:null}).includes('多个窗口'));
 assert(caption({session_scope:'legacy-window-9999'}).endsWith('dow-9999'));
});

test('read access while waiting for a real source is shown separately from write access',()=>{
 const advice=load('agentConnectionAdvice'),capabilities=load('connectionCapabilities'),receipt=load('hookReceiptCaption');
 const c={host:'agent',enabled:true,host_online:true,can_read:true,can_write:false,binding_state:'awaiting_source_turn',session_scope_policy:'next_session',bound_session_id:null};
 assert.equal(state(c),'可查询 · 写入等待来源绑定');assert(capabilities(c).includes('查询记忆：可用'));assert(capabilities(c).includes('保存记忆：等待来源绑定'));
 assert(advice(c).includes('MCP 手动补录不会认领'));
 const received={...c,can_write:true,bound_session_id:'actual-window',archive_status:'host_reported',capture:{hook_event_count:1,complete_dialogues_saved:1}};
 assert.equal(state(received),'已收到宿主记录');assert(receipt(received).includes('1 次'));assert(receipt(received).includes('仍依赖宿主'));
 assert(advice(received).includes('一次接收不能证明'));assert(!state(received).includes('自动'));
});

test('path copy uses only the generated private path and a rotated config cannot remain copyable',()=>{
 const actual=load('agentPrivatePath');
 const c={id:'conn-a',host:'agent',library_id:'fish-a',binding_revision:2};const path='/Users/example/Library/Application Support/NeuralKnowledge/agent-connections/real.json';
 assert.equal(actual({connection:c,private_path:path}),path);
 assert.equal(actual({connection:c,workbuddy_setup:{private_path:'/invented/fallback'},mcp_config:config}),'');
 assert.equal(actual({connection:{...c,revoked:true},private_path:path}),'');assert.equal(actual({connection:c,private_path:'bad\npath'}),'');
 const env={S:{libraryId:'fish-a',libraryEpoch:2},MEMORY:{connections:[{...c,binding_revision:3}]}};
 const current=load('isCurrentAgentConfig',env);assert.equal(current({connection:c,private_path:path}),false);
 env.MEMORY.connections=[c];assert.equal(current({connection:c,private_path:path}),true);env.S.libraryId='fish-b';assert.equal(current({connection:c,private_path:path}),false);
});

function actualCode(name){const line=source.match(new RegExp('(?:async )?function '+name+'\\([^\\n]*'))?.[0];assert(line,`function ${name}`);return line.endsWith('}')?line:extract(name);}
function asyncFixture(){
 const texts=()=>({value:'',textContent:'',hidden:false,open:false,disabled:false,children:[],replaceChildren(){this.children=[];},append(...x){this.children.push(...x);},showModal(){this.open=true;},close(){this.open=false;},focus(){this.focused=true;}});
 const cfg={connection:{id:'conn-a',name:'泡泡窗口',host:'agent',library_id:'fish-a',enabled:true,binding_revision:1,bound_session_id:'old-window',session_scope_policy:'next_session'},private_path:'/private/current.json',mcp_config:config,workbuddy_setup:{supported:true}};
 const env={remoteHost:false,S:{libraryId:'fish-a',libraryEpoch:1,libraryChanging:false},MEMORY:{busy:false,configVersion:4,config:cfg,connections:[cfg.connection]},canManageMemory:()=>true,updateWriteState(){},apiCalls:[],shown:[],messages:[],workbuddyPlan:null,rebindOwner:null,rebindTarget:null,
  workbuddyPlanBody:texts(),workbuddyGuide:texts(),workbuddyApply:texts(),guideNotice:texts(),rebindDialog:texts(),rebindSummary:texts(),rebindCancel:texts(),mcpArea:{value:'OLD-MCP'},setupArea:{value:'OLD-SETUP'},pathInput:{value:'OLD-PATH'},make:(t,c,s)=>({tagName:t,textContent:s}),libraryName:id=>id,by:()=>({focus(){}}),toast:(...x)=>env.messages.push(x),refreshConnections:async()=>{},showConnectionConfig:cfg=>{env.MEMORY.config=cfg;env.MEMORY.configVersion++;env.shown.push(cfg);}};
 env.api=async(route,body)=>{env.apiCalls.push({route,body});return {supported:true,config_path:'/private/workbuddy/mcp.json',private_path:'/private/current.json'};};
 const arrows=['sameOwner','ownerNow','currentConfigRequest'].map(n=>source.match(new RegExp('const '+n+'=[^\\n]+'))[0]).join('\n');
 vm.createContext(env);vm.runInContext(pureNames.map(extract).join('\n')+'\n'+arrows+'\n'+['isCurrentAgentConfig','clearWorkBuddyPlan','showWorkBuddyPlan','previewWorkBuddy','applyWorkBuddy','closeRebind','rebindConnection','confirmConnectionRebind'].map(actualCode).join('\n'),env);
 return env;
}

test('WorkBuddy preview shows real paths but only an explicit apply performs a backup/merge request',async()=>{
 const c=asyncFixture();await c.previewWorkBuddy();assert.equal(c.apiCalls.length,1);assert.deepEqual(plain(c.apiCalls[0]),{route:'connections/conn-a/workbuddy/configure',body:{apply:false}});assert(c.workbuddyGuide.open);assert.equal(c.workbuddyApply.hidden,false);assert(c.workbuddyPlanBody.children.some(x=>x.textContent==='/private/workbuddy/mcp.json'));
 c.clearWorkBuddyPlan();await c.applyWorkBuddy();assert.equal(c.apiCalls.length,1);assert.equal(c.shown.length,0);
 await c.previewWorkBuddy();c.api=async(route,body)=>{c.apiCalls.push({route,body});if(body)return {applied:true,readback_verified:true,config_path:'/private/workbuddy/mcp.json'};return {connection:{...c.MEMORY.config.connection},private_path:'/private/current.json',mcp_config:config};};
 await c.applyWorkBuddy();assert(c.apiCalls.some(x=>x.body?.apply===true));assert.equal(c.shown.length,1);assert(c.guideNotice.textContent.includes('信任并加载'));assert(c.guideNotice.textContent.includes('未启用未经确认'));
});

test('WorkBuddy refuses unverified readback and discards a late preview after archive changes',async()=>{
 const c=asyncFixture();await c.previewWorkBuddy();c.api=async()=>({applied:true,readback_verified:false});await c.applyWorkBuddy();assert.equal(c.shown.length,0);assert(c.guideNotice.textContent.includes('未完成'));
 const late=asyncFixture();let resolve;late.api=()=>new Promise(r=>resolve=r);const pending=late.previewWorkBuddy();late.S.libraryId='fish-b';late.S.libraryEpoch++;resolve({supported:true,config_path:'/old/private/mcp.json',private_path:'/old/private/token.json'});await pending;assert.equal(late.workbuddyPlan,null);assert.equal(late.workbuddyPlanBody.children.length,0);assert.equal(late.MEMORY.busy,false);
});

test('rebind opens a review without sending an event; cancel never rotates or records anything',()=>{
 const c=asyncFixture();c.rebindConnection(c.MEMORY.connections[0]);assert(c.rebindDialog.open);assert(c.rebindSummary.textContent.includes('old-window'));assert(c.rebindSummary.textContent.includes('fish-a'));assert.equal(c.apiCalls.length,0);c.closeRebind();assert(!c.rebindDialog.open);assert.equal(c.apiCalls.length,0);
 c.rebindConnection({...c.MEMORY.connections[0],registered_source:{id:'source-a'}});assert(!c.rebindDialog.open);c.rebindConnection({...c.MEMORY.connections[0],library_id:'fish-b'});assert(!c.rebindDialog.open);assert.equal(c.apiCalls.length,0);
});

test('confirmed rebind clears old copy data and uses the new generation without changing archive identity',async()=>{
 const c=asyncFixture();c.rebindConnection(c.MEMORY.connections[0]);c.api=async(route,body)=>{assert.equal(c.MEMORY.config,null);assert.equal(c.mcpArea.value,'');assert.equal(c.setupArea.value,'');assert.equal(c.pathInput.value,'');c.apiCalls.push({route,body});return {connection:{id:'conn-a',host:'agent',library_id:'fish-a',binding_revision:2,bound_session_id:null,session_scope_policy:'next_session'},private_path:'/private/generation-2.json',mcp_config:config};};
 await c.confirmConnectionRebind();assert.deepEqual(plain(c.apiCalls),[{route:'connections/conn-a/rebind',body:{confirm:true,expected_bound_session_id:'old-window'}}]);assert.equal(c.shown.length,1);assert.equal(c.MEMORY.config.private_path,'/private/generation-2.json');assert.equal(c.MEMORY.connections[0].binding_revision,2);assert(!c.rebindDialog.open);assert(c.guideNotice.textContent.includes('旧配置已失效'));
});

test('rebind response cannot expose a new private path after switching to a different archive',async()=>{
 const c=asyncFixture();c.rebindConnection(c.MEMORY.connections[0]);let resolve;c.api=()=>new Promise(r=>resolve=r);const pending=c.confirmConnectionRebind();c.S.libraryId='fish-b';c.S.libraryEpoch++;resolve({connection:{id:'conn-a',host:'agent',library_id:'fish-a'},private_path:'/private/new-token.json'});await pending;assert.equal(c.shown.length,0);assert.equal(c.MEMORY.config,null);assert.equal(c.pathInput.value,'');assert.equal(c.MEMORY.busy,false);
});
