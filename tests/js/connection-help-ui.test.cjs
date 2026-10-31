/* Run the shipped help component; it must explain routes without changing connections. */
const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const help=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/connection-help-ui.js'),'utf8');
const wizard=fs.readFileSync(path.join(__dirname,'../../nkb/viz/web/connection-ux.js'),'utf8');
class Element{
 constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.attributes={};this.dataset={};this.events={};this.textContent='';this.disabled=false;this.open=false;this.hidden=false;this.value='';}
 append(...nodes){for(const n of nodes){this.children.push(n);if(n instanceof Element)n.parentElement=this;}}
 insertBefore(node,before){if(!this.children.includes(before))throw Error('not a child');this.children.splice(this.children.indexOf(before),0,node);node.parentElement=this;}
 replaceChildren(...nodes){this.children=[];this.append(...nodes);}
 querySelector(selector){return all(this).find(e=>selector[0]==='.'?e.className?.split(' ').includes(selector.slice(1)):e.id===selector.slice(1));}
 setAttribute(k,v){this.attributes[k]=String(v);}
 addEventListener(k,v){this.events[k]=v;}
 showModal(){this.open=true;}
 close(){this.open=false;}
 focus(){this.focused=true;}
 click(){if(!this.disabled)return this.onclick?.();}
 set innerHTML(value){throw Error('Guide content must use text nodes');}
}
const all=r=>[r,...r.children.flatMap(x=>x instanceof Element?all(x):[])];
const words=r=>all(r).map(e=>e.textContent).join('\n');
function fixture(){
 const body=new Element('body'),head=new Element('head');
 const el=(t,c,s)=>{const e=new Element(t);e.className=c||'';if(s!==undefined)e.textContent=s;return e;};
 function add(id,parent=body,cls=''){const e=el('div',cls);e.id=id;parent.append(e);return e;}
 const panel=add('connectionsPanel');add('newConnectionDetails',panel);const modal=add('connectionWizardDialog'),heading=add('wizard-heading',modal,'wizard-heading');add('closeConnectionWizard',heading);
 const sources=add('agentSourcesDialog');add('agentSourcesList',sources);const organizer=add('organizerPanel');add('organizerActions',organizer,'ai-compose-actions');
 const get=id=>[...all(body),...all(head)].find(e=>e.id===id);
 const S={libraryId:'fish-a',libraryEpoch:1,libraryChanging:false},calls=[];
 const context={S,el,libraryName:id=>id==='fish-a'?'泡泡':'另一条鱼',document:{body,head,getElementById:get},updateMemoryButtons(){},window:{},api(){calls.push('unexpected');throw Error('help must not request a model or connection mutation');}};
 vm.runInNewContext(help,context);return {get,S,context,body,calls};
}

test('route selection shows the correct installation destination without generating or sending configuration',()=>{
 const c=fixture();c.get('showConnectionHelp').click();assert(c.get('connectionHelpDialog').open);assert(words(c.get('connectionHelpBody')).includes('Harness 的连接器'));
 c.get('connectionHelpRoute-astrbot').click();const text=words(c.get('connectionHelpBody'));assert(text.includes('AstrBot 的爱之屋插件设置'));assert(text.includes('配置文件路径'));assert(text.includes('QQ 官方接口'));assert(!text.includes('MCP 设置'));
 c.get('connectionHelpRoute-agent').click();const other=words(c.get('connectionHelpBody'));assert(other.includes('能修改该程序设置'));assert(other.includes('输出采集连接器'));assert(!other.includes('Harness 的连接器'));assert.deepEqual(c.calls,[]);
});

test('organizer key help cannot be mistaken for a connection or completed capture',()=>{
 const c=fixture();c.get('organizerKeyHelp').click();const text=words(c.get('connectionHelpBody'));assert(text.includes('爱之屋自己的'));assert(text.includes('已收到的资料'));assert(text.includes('不会自动连接'));assert.equal(c.get('connectionHelpRoute-key').attributes['aria-pressed'],'true');assert.deepEqual(c.calls,[]);
});

test('closing or Escape returns focus and resets expanded help, without touching the source dialog',()=>{
 const c=fixture();c.get('agentSourcesDialog').showModal();c.get('agentSourcesHelp').click();c.get('connectionHelpDeployment').open=true;c.get('connectionHelpStages').open=true;
 c.get('closeConnectionHelp').click();assert(!c.get('connectionHelpDialog').open);assert(c.get('agentSourcesDialog').open);assert(c.get('agentSourcesHelp').focused);assert(!c.get('connectionHelpDeployment').open);
 c.get('agentSourcesHelp').focused=false;c.get('agentSourcesHelp').click();let prevented=false;c.get('connectionHelpDialog').events.cancel({preventDefault(){prevented=true;}});assert(prevented);assert(!c.get('connectionHelpDialog').open);assert(c.get('agentSourcesHelp').focused);assert.deepEqual(c.calls,[]);
});

test('changing the selected fish closes old explanation and does not restore focus into a stale flow',()=>{
 const c=fixture();c.get('showConnectionHelp').click();c.S.libraryId='fish-b';c.S.libraryEpoch++;c.context.updateMemoryButtons();assert(!c.get('connectionHelpDialog').open);assert.equal(c.get('connectionHelpIdentity').textContent,'');assert.notEqual(c.get('showConnectionHelp').focused,true);
 c.get('showConnectionHelp').click();assert(c.get('connectionHelpIdentity').textContent.includes('另一条鱼'));
});

test('help refuses to open while a library switch is in progress',()=>{const c=fixture();c.S.libraryChanging=true;c.get('showConnectionHelp').click();assert(!c.get('connectionHelpDialog').open);assert.deepEqual(c.calls,[]);});

test('AstrBot wizard choice enters source configuration instead of creating a legacy MCP connection',()=>{
 const snippet=wizard.match(/const astrbotChoice=[\s\S]*?screens\[0\]\.append\(astrbotChoice\);/)[0];
 for(const flag of ['ready','busy','demo','changing']){
  const screen=new Element('div'),dialog=new Element('dialog');dialog.open=true;let opened=0;
  const MEMORY={busy:flag==='busy'},S={isDemo:flag==='demo',libraryChanging:flag==='changing'};
  const make=(t,c,s)=>{const e=new Element(t);e.className=c||'';if(s!==undefined)e.textContent=s;return e;};
  const c={screens:[screen],dialog,make,MEMORY,S,writeBusy:false,canManageMemory:()=>true,window:{LoveHouseSources:{open(){opened++;}}}};vm.runInNewContext(snippet,c);screen.children[0].click();
  assert.equal(opened,flag==='ready'?1:0);assert.equal(dialog.open,flag!=='ready');
 }
});

test('registered source descriptors bypass legacy MCP controls and respect the selected archive',()=>{
 const snippet=wizard.match(/const oldShow=showConnectionConfig;showConnectionConfig=function\(result\)\{[^\n]+/)[0];
 const routed=[],messages=[];let legacy=0;const ctx={showConnectionConfig(){legacy++;},S:{libraryId:'fish-a'},toast:x=>messages.push(x),window:{LoveHouseSources:{openForConnection:id=>routed.push(id)}}};
 vm.runInNewContext(snippet,ctx);
 ctx.showConnectionConfig({mode:'registered_source',connection:{id:'conn-a',library_id:'fish-a'}});assert.deepEqual(routed,['conn-a']);assert.equal(legacy,0);
 ctx.showConnectionConfig({mode:'registered_source',connection:{id:'conn-b',library_id:'fish-b'}});assert.deepEqual(routed,['conn-a']);assert.equal(legacy,0);assert(messages[0].includes('另一份存档'));
});

test('actual registered source cards do not present themselves as MCP or all-window capture',()=>{
 const body=new Element('body'),get=id=>all(body).find(e=>e.id===id),make=(t,c,s)=>{const e=new Element(t);e.className=c||'';if(s!==undefined)e.textContent=s;return e;};
 for(const id of ['connectionSummary','connectionsList']){const e=make('div');e.id=id;body.append(e);}const target=make('div');body.append(target);
 const source={id:'conn-a',name:'已登记的程序',host:'agent',library_id:'fish-a',enabled:true,host_online:false,session_scope:'connection',archive_status:'waiting',registered_source:{id:'source-a',adapter:'astrbot',library_id:'fish-a',runtime_agent_id:'runtime-a'}};
 const calls=[],context={S:{libraryId:'fish-a'},MEMORY:{connections:[source],libraries:[{id:'fish-a',name:'泡泡'}]},renderKey:'',target,by:get,make,libraryName:id=>id,num:x=>String(x||0),date:String,trimText:String,loadConnectionConfig:id=>calls.push(id),selectMemoryLibrary(){},openProviderEditor(){},setConnectionEnabled(){},openDisconnect(){},refreshGuide(){},updateMemoryButtons(){}};
 const helpers=['registeredSource','windowScopeCaption','connectionCaption','connectionGuideCaption','connectionState','action'].map(name=>wizard.match(new RegExp('function '+name+'\\([^]*?\\n\\}'))?.[0]||wizard.match(new RegExp('function '+name+'\\([^\\n]+'))[0]).join('\n');
 const render=wizard.match(/renderConnections=function\(\)\{[\s\S]*?\n\};/)[0];vm.runInNewContext(helpers+'\n'+render,context);context.renderConnections();
 let text=words(get('connectionsList'));assert(text.includes('AstrBot 活动来源'));assert(text.includes('已登记'));assert(text.includes('配置 AstrBot 插件'));for(const forbidden of ['通用 Agent 记忆','多个窗口','继续连接 Agent','记忆工具已连接'])assert(!text.includes(forbidden));
 const guide=all(get('connectionsList')).find(e=>e.dataset.connectionAction==='config');guide.click();assert.deepEqual(calls,['conn-a']);
 source.archive_status='outputs_only';source.capture={outputs_saved:2,complete_dialogues_saved:0};context.renderConnections();text=words(get('connectionsList'));assert(text.includes('查看来源配置'));assert(text.includes('独立输出 2 条'));assert(!text.includes('多个窗口'));assert(get('connectionSummary').textContent.includes('独立输出'));
});
