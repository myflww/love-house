const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/connection-ux.js'),'utf8');
function load(name){const match=source.match(new RegExp('function '+name+'\\([^]*?\\n\\}'));assert(match,`missing actual UI function ${name}`);return vm.runInNewContext(match[0]+';'+name);}
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
 assert.equal(state({host:'agent',enabled:true,host_online:true,archive_status:'automatic_connected'}),'已收到自动存档');
 assert.equal(state({host:'agent',enabled:false,host_online:true,archive_status:'automatic_connected'}),'已暂停');
 assert.equal(state({host:'api',enabled:true,archive_status:'automatic_connected'}),'已收到对话');
});
test('copy-for-agent fallback explains tool capability, optional hook, and once-saved restart',()=>{
 const cfg={connection:{host:'agent'},mcp_config:config};const text=setup(cfg);
 assert(text.includes('memory_status'));assert(text.includes('轮次结束钩子'));assert(text.includes('配置保存一次'));assert(text.includes('无需提供模型厂商'));
 assert(text.includes(JSON.stringify(config,null,2)));assert.equal(setup({...cfg,agent_setup_text:'Fixture setup text'}),'Fixture setup text');
 assert.equal(setup({connection:{host:'agent'},host_config:'not JSON'}),'');
});

test('single-window scope remains visible and all-session scope requires explicit consent',()=>{const scope=load('windowScopeCaption');assert(scope({session_scope:'next_session'}).includes('目标窗口'));assert(scope({session_scope:'session-one'}).includes('仅固定窗口'));assert(scope({session_scope:'connection'}).includes('多个窗口'));assert(source.includes('allowAllConnectionSessions'));assert(source.includes("scope==='connection'&&!broadCheck.checked"));});

test('Windows can select Harness and busy state is the only platform-independent lock',()=>{
 const controls=new Map();const by=id=>{if(!controls.has(id))controls.set(id,{});return controls.get(id);};
 const choices={harness:{},agent:{},api:{}};
 const ctx={remoteHost:false,navigator:{platform:'Win32',userAgent:'Windows NT 10.0'},MEMORY:{busy:false,config:null},writeBusy:false,S:{libraryChanging:false},choices,by,canManageMemory:()=>true,wizardStep:1,hostSelect:{value:'harness'},newLib:{checked:false},newLibName:{},startButton:{},close:{},back:{},next:{},agentSetupText:()=>'',agentMcpText:()=>''};
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
