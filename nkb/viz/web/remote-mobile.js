/* Same-origin mobile management. Credentials never enter URLs or browser storage. */
const $=id=>document.getElementById(id);
let csrf='',busy=false,current=null,connections=[],timer=null;
const note=text=>{$('notice').textContent=text;};
function replaceContents(element,...children){while(element.firstChild)element.removeChild(element.firstChild);for(const child of children)element.appendChild(child);}
function controls(){for(const id of ['loginButton','createConnection','refreshConnections','checkConnection','logout'])$(id).disabled=busy;for(const id of ['copyAgent','copyMcp'])$(id).disabled=busy||!current||(current.connection&&current.connection.revoked);$('rebindConnection').disabled=busy||!current||current.connection.revoked||!current.connection.bound_session_id;for(const id of ['connectionSelect','librarySelect','connectionName','adminToken'])$(id).disabled=busy;}
async function api(path,body){
 const headers={};if(body!==undefined){headers['Content-Type']='application/json';if(csrf)headers['X-LoveHouse-CSRF']=csrf;}
 const response=await fetch('/api/remote/'+path,{method:body===undefined?'GET':'POST',headers,credentials:'same-origin',cache:'no-store',redirect:'error',...(body===undefined?{}:{body:JSON.stringify(body)})});
 let data;try{data=await response.json();}catch{throw new Error('服务返回的数据无法读取。');}
 if(!response.ok){const message=typeof data.error==='string'?data.error:(data.error&&data.error.message);throw new Error(message&&message.length<240?message:response.status===401?'请重新打开服务管理。':'连接没有完成，请检查服务状态。');}return data;
}
function mcpText(bundle){
 const config=bundle&&(bundle.mcp_config||(bundle.remote_config&&bundle.remote_config.mcp_config));
 if(!config||!config.mcpServers||typeof config.mcpServers!=='object')return '';
 for(const server of Object.values(config.mcpServers)){if(!server||typeof server.url!=='string'||server.command||server.args)return '';try{const url=new URL(server.url);if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash)return '';}catch{return '';}}
 return JSON.stringify(config,null,2);
}
function captureCaption(connection){
 if(connection.revoked)return ['连接已断开','原来的记忆仍然保留。需要继续时，为目标窗口创建新连接。'];
 if(connection.enabled===false)return ['记录已暂停','在完整记忆界面恢复接收后，才会继续保存新记录。'];
 if(connection.archive_status==='archive_failed')return ['记录尚未完成','服务报告存档失败，请打开完整记忆界面查看状态；不要重新创建身份。'];
 if(connection.can_write===false&&!connection.bound_session_id&&(connection.session_scope_policy||connection.session_scope)==='next_session')return ['等待目标窗口绑定','等待首次真实来源上报。绑定只能由来源适配器发起；MCP 手动补录不会认领窗口。请先确认宿主支持真实轮次回调，再在目标窗口完成对话。'];
 const capture=connection.capture||{},count=Number(capture.complete_dialogues_saved||capture.hook_dialogues_saved||capture.automatic_dialogues_saved||0);
 if(count>0||connection.archive_status==='host_reported')return ['已收到宿主记录',`历史完整对话 ${count} 轮。仅在宿主调用时记录；已收到事件不能证明后续每轮持续上报。请核对原文与最近接收时间。`];
 return connection.host_online?['记忆工具已连接','工具连通不代表每轮记录。需由宿主真实的轮次回调提交；WorkBuddy 请在自定义连接器中信任并重启，桌面 hooks 支持尚未确认。']:['等待 Agent 加载配置','让有工具或宿主配置能力的 Agent 保存并加载配置，然后调用 memory_status 核对。WorkBuddy 需信任连接器并重启。'];
}
function bindingCaption(connection){
 const policy=connection.session_scope_policy||connection.session_scope;
 if(policy==='any'||policy==='connection')return '整条连接 · 可能包含多个窗口';
 if(connection.bound_session_id)return '仅固定窗口 · '+String(connection.bound_session_id).slice(-8);
 return '等待首次来源上报绑定目标窗口';
}
function captureDiagnostics(connection){
 const capture=connection.capture||{},count=Number(capture.hook_event_count||0);let text=`历史 Hook 接收 ${count} 次`;
 if(capture.last_hook_at){const time=new Date(Number(capture.last_hook_at)*1000);if(!Number.isNaN(time.getTime()))text+=' · 最近 '+time.toLocaleString('zh-CN');}
 if(typeof connection.can_read==='boolean'&&typeof connection.can_write==='boolean')text+=' · '+(connection.can_read?'可读':'暂不可读')+' / '+(connection.can_write?'可写':connection.enabled!==false&&!connection.revoked&&!connection.bound_session_id&&(connection.session_scope_policy||connection.session_scope)==='next_session'?'绑定后可写':'暂不可写');
 return text;
}
function rebindPayload(connection){return {confirm:true,expected_bound_session_id:connection.bound_session_id||null};}
function renderCapture(connection){const [title,detail]=captureCaption(connection);$('captureState').textContent=title;$('captureDetails').textContent=detail;$('captureDiagnostics').textContent=captureDiagnostics(connection);$('connectionTarget').textContent='固定存档：'+connection.library_id+' · '+bindingCaption(connection);$('rebindConnection').hidden=!connection.bound_session_id||!!connection.revoked;}
function showConfig(bundle){
 const text=mcpText(bundle);if(!text)throw new Error('服务没有返回可用的 HTTPS MCP 配置，请更新记忆服务。');
 current=bundle;$('configPanel').hidden=false;$('configHeading').textContent=bundle.connection.name||'让 Agent 保存并加载';
 $('mcpConfig').value=text;$('agentSetup').value=bundle.agent_setup_text||['请把以下 HTTPS MCP 配置保存到你的宿主设置并加载，调用 memory_status 与 memory_bootstrap 核对身份和存档。','不需要聊天模型 API Key。自动记录需要宿主的真实轮次结束回调；工具连通不代表已经自动存档。',text].join('\n\n');
 $('hookConfig').value=JSON.stringify(bundle.hook_config||{},null,2);renderCapture(bundle.connection);controls();
}
async function refresh(){
 const result=await api('admin/connections');connections=result.connections||[];const selected=current&&current.connection&&current.connection.id;
 replaceContents($('connectionSelect'),new Option('选择连接，或在下面创建',''),...connections.filter(c=>!c.revoked&&c.host==='agent').map(c=>new Option(c.name+' · '+c.library_id,c.id)));
 if(selected){$('connectionSelect').value=selected;const latest=connections.find(c=>c.id===selected);if(latest){current.connection=latest;renderCapture(latest);controls();}}
}
async function openWorkspace(){
 const libraries=await api('admin/libraries');replaceContents($('librarySelect'),...(libraries.libraries||[]).filter(l=>!l.is_demo).map(l=>new Option(l.name,l.id)));
 if(libraries.selected_id)$('librarySelect').value=libraries.selected_id;await refresh();$('loginPanel').hidden=true;$('workspace').hidden=false;
 clearInterval(timer);timer=setInterval(()=>{if(!document.hidden&&!busy&&current)refresh().catch(()=>{});},15000);
}
async function operation(action){if(busy)return;busy=true;controls();note('');try{await action();}catch(error){note(error.message||'操作未完成。');}finally{busy=false;controls();}}
async function copy(id){const value=$(id).value;if(!value)return;try{await navigator.clipboard.writeText(value);note('已复制。交给你信任的 Agent 保存、加载并检查。');}catch{$(id).closest('details').open=true;$(id).focus();$(id).select();note('配置已选中，请使用系统复制。');}}
if(typeof document!=='undefined'){
 $('serviceOrigin').textContent=location.origin;
 if(typeof structuredClone!=='function'||typeof Object.hasOwn!=='function')$('browserNote').hidden=false;
 $('loginForm').onsubmit=event=>{event.preventDefault();operation(async()=>{const result=await api('admin/login',{admin_token:$('adminToken').value});$('adminToken').value='';csrf=result.csrf_token||'';await openWorkspace();note('请选择原连接，或为一个聊天窗口生成配置。');});};
 $('connectionForm').onsubmit=event=>{event.preventDefault();operation(async()=>{const result=await api('admin/connections',{name:$('connectionName').value.trim()||'手机 Agent 连接',library_id:$('librarySelect').value,session_scope:'next_session'});showConfig(result);await refresh();note('配置已生成；复制给 Agent 保存并加载。');$('configPanel').scrollIntoView({behavior:'smooth',block:'start'});});};
 $('connectionSelect').onchange=()=>{const id=$('connectionSelect').value;if(!id)return;operation(async()=>showConfig(await api('admin/connections/'+encodeURIComponent(id)+'/config')));};
 $('refreshConnections').onclick=()=>operation(refresh);$('checkConnection').onclick=()=>operation(async()=>{await refresh();note('已读取真实连接与存档状态。');});
 $('copyAgent').onclick=()=>copy('agentSetup');$('copyMcp').onclick=()=>copy('mcpConfig');
 $('rebindConnection').onclick=()=>{if(!current||busy)return;const connection=current.connection;if(!window.confirm('重新绑定到新窗口？原记忆保留；旧凭据失效。请先停用旧窗口配置，再把换发的 MCP 和 Hook 配置安装到目标窗口。'))return;operation(async()=>{const result=await api('admin/connections/'+encodeURIComponent(connection.id)+'/rebind',rebindPayload(connection));if(result.connection?.id!==connection.id||result.connection.library_id!==connection.library_id)throw new Error('连接已申请换发，但服务返回的身份不一致；请重新打开原连接检查。');showConfig(result);await refresh();note('已换发配置，原记忆保留。请停用旧窗口配置，把新配置安装到目标窗口后再绑定；未重新创建 Agent 身份。');});};
 $('logout').onclick=()=>operation(async()=>{await api('admin/logout',{});clearInterval(timer);csrf='';current=null;connections=[];for(const id of ['agentSetup','mcpConfig','hookConfig'])$(id).value='';$('workspace').hidden=true;$('configPanel').hidden=true;$('loginPanel').hidden=false;note('已退出服务管理。已交给 Agent 的连接凭据仍由对应连接管理。');});
 api('health').then(data=>{$('version').textContent=data.version||'0.8 记忆服务';return api('admin/session').then(session=>{csrf=session.csrf_token||'';return openWorkspace();});}).catch(()=>{});controls();
}
export {mcpText,captureCaption,bindingCaption,captureDiagnostics,rebindPayload};
