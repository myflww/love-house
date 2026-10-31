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
 assert.equal(state({host:'agent',enabled:true,host_online:true,archive_status:'automatic_connected'}),'已收到自动存档');
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
