import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(new URL('../../nkb/viz/web/remote-mobile.js',import.meta.url),'utf8');
const {mcpText,captureCaption,bindingCaption,captureDiagnostics,rebindPayload}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const plain=value=>JSON.parse(JSON.stringify(value));
test('mobile exports an authenticated HTTPS MCP endpoint without local command paths',()=>{
 const mcp={mcpServers:{memory:{url:'https://memory.example/mcp/fixture',headers:{Authorization:'Bearer FAKE-MEMORY-CONNECTION'}}}};
 assert.deepEqual(JSON.parse(mcpText({mcp_config:mcp})),mcp);
 for(const url of ['http://127.0.0.1/mcp/fixture','https://'+'user'+':'+'pass'+'@memory.example/mcp/x','https://memory.example/mcp/x?token=FAKE','https://memory.example/mcp/x#secret'])assert.equal(mcpText({mcp_config:{mcpServers:{memory:{url}}}}),'');
 assert.equal(mcpText({mcp_config:{mcpServers:{memory:{command:'C:\\LoveHouse\\bridge.exe',args:[],url:'https://memory.example'}}}}),'');
});
test('mobile distinguishes generated config, tool heartbeat and an actual saved host turn',()=>{
 assert.equal(captureCaption({enabled:true,host_online:false})[0],'等待 Agent 加载配置');
 assert.equal(captureCaption({enabled:true,host_online:true,archive_status:'tools_only'})[0],'记忆工具已连接');
 assert.equal(captureCaption({enabled:true,host_online:true,archive_status:'automatic_connected',capture:{automatic_dialogues_saved:2}})[0],'已收到宿主记录');
 assert.notEqual(captureCaption({enabled:true,host_online:true,archive_status:'automatic_connected',capture:{automatic_dialogues_saved:0}})[0],'已收到宿主记录');
 assert.equal(captureCaption({enabled:false,host_online:true,archive_status:'automatic_connected',capture:{automatic_dialogues_saved:2}})[0],'记录已暂停');
 assert.equal(captureCaption({revoked:true})[0],'连接已断开');
});


test('mobile presents one hook as received data and binding as a separate capability',()=>{
 const connection={library_id:'same-fish',host:'agent',enabled:true,host_online:true,session_scope_policy:'next_session',session_scope:'next_session',bound_session_id:'window-abcdefgh',can_read:true,can_write:true,archive_status:'host_reported',capture:{hook_event_count:1,complete_dialogues_saved:1,last_hook_at:1793428800}};
 assert(bindingCaption(connection).includes('abcdefgh'));assert(!bindingCaption(connection).includes('等待'));
 assert(captureDiagnostics(connection).includes('1 次'));assert(captureDiagnostics(connection).includes('可读 / 可写'));
 const [title,detail]=captureCaption(connection);assert(!title.includes('自动'));assert(detail.includes('不能证明'));
 const rebound={...connection,bound_session_id:null,can_write:false};assert.equal(captureCaption(rebound)[0],'等待目标窗口绑定');assert(captureCaption(rebound)[1].includes('MCP 手动补录不会认领窗口'));
 assert.deepEqual(plain(rebindPayload(connection)),{confirm:true,expected_bound_session_id:'window-abcdefgh'});
 assert.deepEqual(plain(rebindPayload(rebound)),{confirm:true,expected_bound_session_id:null});
});


test('mobile rebind button sends authenticated CSRF mutation, keeps the library and replaces the copied credential',async()=>{
 const elements=new Map(),calls=[];
 const get=id=>{if(!elements.has(id))elements.set(id,{value:'',hidden:false,children:[],appendChild(x){this.children.push(x);},removeChild(x){this.children.splice(this.children.indexOf(x),1);},get firstChild(){return this.children[0];},scrollIntoView(){},focus(){},select(){},closest(){return {open:false};}});return elements.get(id);};
 let rebound=false,approve=false;
 const original={id:'mobile-connection',name:'Window',library_id:'same-fish',host:'agent',enabled:true,bound_session_id:'old-window',can_read:true,can_write:true,session_scope_policy:'next_session'};
 const connection=()=>({...original,...(rebound?{bound_session_id:null,can_write:false}:{} )});
 const bundle=()=>({connection:connection(),mcp_config:{mcpServers:{memory:{url:'https://memory.example/mcp/mobile-connection',headers:{Authorization:rebound?'Bearer NEW-CONNECTION':'Bearer OLD-CONNECTION'}}}}});
 const ctx={URL,document:{getElementById:get,hidden:false},location:{origin:'https://memory.example'},window:{confirm:()=>approve},setInterval:()=>0,clearInterval(){},Option:function(text,value){this.text=text;this.value=value;},fetch:async(url,options)=>{
  calls.push([url,plain(options)]);let data;
  if(url.endsWith('/health'))data={version:'fixture'};
  else if(url.endsWith('/admin/session'))data={csrf_token:'FAKE-CSRF'};
  else if(url.endsWith('/admin/libraries'))data={libraries:[{id:'same-fish',name:'Same fish'}],selected_id:'same-fish'};
  else if(url.endsWith('/admin/connections'))data={connections:[connection()]};
  else if(url.endsWith('/config'))data=bundle();
  else if(url.endsWith('/rebind')){rebound=true;data=bundle();}
  else throw new Error('Unexpected UI request '+url);
  return {ok:true,json:async()=>data};
 }};
 vm.runInNewContext(source.replace(/export \{[^]*?\};/,''),ctx);
 const flush=async()=>{for(let i=0;i<50;i++)await Promise.resolve();};
 await flush();get('connectionSelect').value=original.id;get('connectionSelect').onchange();await flush();
 assert(get('mcpConfig').value.includes('OLD-CONNECTION'));assert.equal(get('rebindConnection').hidden,false);
 get('rebindConnection').onclick();await flush();assert(!calls.some(c=>c[0].endsWith('/rebind')));
 approve=true;get('rebindConnection').onclick();await flush();
 const mutation=calls.find(c=>c[0].endsWith('/rebind'));assert(mutation);
 assert.equal(mutation[1].method,'POST');assert.equal(mutation[1].credentials,'same-origin');assert.equal(mutation[1].headers['X-LoveHouse-CSRF'],'FAKE-CSRF');
 assert.deepEqual(JSON.parse(mutation[1].body),{confirm:true,expected_bound_session_id:'old-window'});
 assert(get('connectionTarget').textContent.includes('same-fish'));assert(get('mcpConfig').value.includes('NEW-CONNECTION'));assert(!get('mcpConfig').value.includes('OLD-CONNECTION'));
 assert.equal(get('rebindConnection').hidden,true);assert(get('notice').textContent.includes('原记忆保留'));
});
