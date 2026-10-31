const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/connection-ux.js'),'utf8');
function load(name){const match=source.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));assert(match,`missing actual UI function ${name}`);const dependency=name==='registeredSource'?'':source.match(/function registeredSource\([^]*?\n\}/)[0]+'\n';return vm.runInNewContext(dependency+match[0]+';'+name);}
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
 const ctx={remoteHost:false,navigator:{platform:'Win32',userAgent:'Windows NT 10.0'},MEMORY:{busy:false,config:null},writeBusy:false,S:{libraryChanging:false},choices,by,canManageMemory:()=>true,wizardStep:1,hostSelect:{value:'harness'},newLib:{checked:false},newLibName:{},startButton:{},close:{},back:{},next:{},agentSetupText:()=>'',agentMcpText:()=>'',connectionConfigPath:()=>'',astrbotChoice:{dataset:{}}};
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
 const ctx={remoteHost:true,MEMORY:{busy:false,libraries:[]},canManageMemory:()=>true,refreshLibraries:async()=>{},hostSelect:{value:'harness'},advancedPaths:{},connectionHostChanged:()=>{},by,S:{isDemo:false,libraryId:'same-library'},newLib:{},newLibName:{},go:()=>{},dialog:{showModal:()=>{}},choices:{agent:{focus:()=>{}}}};
 const fn=vm.runInNewContext(source.match(/async function openWizard[^\n]+/)[0]+';openWizard',ctx);await fn('harness');assert.equal(ctx.hostSelect.value,'agent');assert.equal(by('connectionLibrary').value,'same-library');
});


test('binding policy stays stable while the separate bound window controls display and permissions',()=>{
 const scope=load('windowScopeCaption'),capabilities=load('connectionCapabilities');
 const bound={session_scope:'next_session',session_scope_policy:'next_session',bound_session_id:'window-abcdefgh',can_read:true,can_write:true};
 assert(scope(bound).includes('abcdefgh'));assert(!scope(bound).includes('等待'));
 assert(capabilities(bound).includes('可写'));assert(!capabilities(bound).includes('绑定后'));
 const awaiting={...bound,bound_session_id:null,can_write:false};
 assert(scope(awaiting).includes('首次来源上报'));assert(capabilities(awaiting).includes('绑定后可写'));
 assert.equal(state({host:'agent',enabled:true,host_online:true,...awaiting}),'工具已连接 · 等待窗口绑定');
});

test('single manually reachable hook and legacy automatic state never claim continuous capture',()=>{
 const receipt=load('hookReceiptCaption'),saved=load('savedDialogue');
 const advice=vm.runInNewContext(source.match(/function savedDialogue\([^]*?\n\}/)[0]+'\n'+source.match(/function agentConnectionAdvice\([^]*?\n\}/)[0]+';agentConnectionAdvice');
 const c={host:'agent',enabled:true,host_online:true,archive_status:'host_reported',capture:{hook_event_count:1,complete_dialogues_saved:1},bound_session_id:'fixed'};
 assert(receipt(c).includes('1 次'));assert(receipt(c).includes('仅在宿主调用'));
 assert(saved(c));assert(advice(c,{}).includes('不能保证'));
 assert(!state(c).includes('自动'));assert(!state({...c,archive_status:'automatic_connected'}).includes('自动'));
 assert(advice({...c,bound_session_id:null,session_scope_policy:'next_session',can_write:false},{}).includes('MCP 手动补录不会认领窗口'));
});

test('copying a connection path uses only the service supplied actual path',()=>{
 const path=load('connectionConfigPath'),actual='C:\\Users\\fixture\\AppData\\Local\\LoveHouse\\agent-connections\\connection.json';
 assert.equal(path({connection:{host:'agent'},private_path:actual}),actual);
 assert.equal(path({connection:{host:'agent'},mcp_config:config}),'');
 assert.equal(path({connection:{revoked:true},private_path:actual}),'');
});

test('rebind confirmation preserves expected window, rotates through the exact connection API and does not run on cancel',async()=>{
 const calls=[],messages=[],item={id:'target/id',name:'Original',library_id:'fish-a',host:'agent',bound_session_id:'original-window'};
 const ctx={S:{libraryEpoch:2},MEMORY:{busy:false},canManageMemory:()=>true,window:{confirm:()=>false},updateWriteState(){},api:async(...args)=>{calls.push(plain(args));return {connection:{...item,bound_session_id:null},private_path:'NEW'};},showConnectionConfig:r=>messages.push(r),refreshConnections:async()=>{},toast:(...args)=>messages.push(args)};
 const fn=vm.runInNewContext(source.match(/async function rebindConnection\([^]*?\n\}/)[0]+';rebindConnection',ctx);
 await fn(item);assert.deepEqual(calls,[]);
 ctx.window.confirm=()=>true;await fn({...item,host:'harness'});assert.deepEqual(calls,[]);await fn({...item,host:'api'});assert.deepEqual(calls,[]);await fn(item);assert.equal(calls.length,1);
 assert.deepEqual(calls[0],['connections/target%2Fid/rebind',{confirm:true,expected_bound_session_id:'original-window'},{scope:false}]);
 assert.equal(ctx.MEMORY.busy,false);assert.equal(messages[0].connection.library_id,'fish-a');
 ctx.window.confirm=()=>{ctx.S.libraryEpoch++;return true;};await fn(item);assert.equal(calls.length,1);
});

test('WorkBuddy install verifies its plan and readback before claiming config installation',async()=>{
 const code=source.match(/workbuddyNow\.onclick=async\(\)=>\{[^]*?\n\};/)[0],calls=[],notices=[];
 const ctx={remoteHost:false,canManageMemory:()=>true,MEMORY:{busy:false,config:{connection:{id:'conn-fixture'}}},S:{libraryEpoch:1},workbuddyNow:{},guideNotice:{textContent:''},updateWriteState(){},refreshConnections:async()=>{},showConnectionConfig:r=>notices.push(r),api:async(route,body)=>{calls.push([route,body]);return body?.apply===false?{supported:true}:body?.apply===true?{applied:true,readback_verified:true}:{connection:{id:'conn-fixture'}};}};
 vm.runInNewContext(code,ctx);await ctx.workbuddyNow.onclick();
 assert.deepEqual(calls.slice(0,2).map(c=>plain(c)),[['connections/conn-fixture/workbuddy/configure',{apply:false}],['connections/conn-fixture/workbuddy/configure',{apply:true}]]);
 assert(ctx.guideNotice.textContent.includes('信任'));assert(ctx.guideNotice.textContent.includes('未启用自动上报'));
 calls.length=0;ctx.api=async(route,body)=>{calls.push([route,body]);return {supported:true,applied:true,readback_verified:false};};await ctx.workbuddyNow.onclick();
 assert(ctx.guideNotice.textContent.includes('未完成'));assert.equal(notices.length,1);
});

 test('independent automatic output is reported without claiming it is a complete dialogue',()=>{assert.equal(state({host:'agent',enabled:true,host_online:true,archive_status:'outputs_only'}),'已收到自动输出');assert.equal(state({host:'agent',enabled:false,host_online:true,archive_status:'outputs_only'}),'已暂停');});


test('registered sources have program labels, configured scope and source-specific actions',()=>{
 const caption=load('connectionCaption'),scope=load('windowScopeCaption'),guide=load('connectionGuideCaption');
 const c={id:'conn-a',host:'agent',library_id:'fish-a',enabled:true,host_online:false,session_scope:'connection',archive_status:'waiting',registered_source:{id:'source-a',adapter:'astrbot',library_id:'fish-a',runtime_agent_id:'fish-runtime'}};
 assert.equal(caption(c),'AstrBot 活动来源');assert.equal(guide(c),'配置 AstrBot 插件');assert(scope(c).includes('已登记'));assert(!scope(c).includes('多个窗口'));assert.equal(state(c),'等待运行程序报送');
 const received={...c,archive_status:'outputs_only'};assert.equal(guide(received),'查看来源配置');assert.equal(state(received),'已收到自动输出');
 const sdk={...c,registered_source:{...c.registered_source,adapter:'sdk'}};assert.equal(caption(sdk),'执行器活动来源');assert.equal(guide(sdk),'配置执行器连接器');
 const legacy={...c,registered_source:null,host_online:true,archive_status:'tools_only'};assert.equal(caption(legacy),'通用 Agent 记忆');assert(scope(legacy).includes('多个窗口'));assert.equal(state(legacy),'记忆工具已连接');
});

test('metadata from a different archive cannot turn a connection into a verified source',()=>{
 const source=load('registeredSource'),caption=load('connectionCaption'),scope=load('windowScopeCaption'),guide=load('connectionGuideCaption');
 const c={host:'agent',library_id:'fish-a',enabled:true,host_online:true,session_scope:'connection',registered_source:{id:'source-a',adapter:'astrbot',library_id:'fish-b',runtime_agent_id:'runtime-b'}};
 assert.equal(source(c),null);assert(caption(c).includes('身份待核验'));assert(scope(c).includes('身份待核验'));assert(!scope(c).includes('整个连接'));assert.equal(guide(c),'刷新连接信息');assert.equal(state(c),'来源身份待核验');
 for(const bad of [{...c.registered_source,library_id:'fish-a',adapter:'unknown'},{...c.registered_source,library_id:'fish-a',runtime_agent_id:''},{...c.registered_source,library_id:'fish-a',id:''}])assert.equal(source({...c,registered_source:bad}),null);
});
