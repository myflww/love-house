/* Same-origin mobile management. Credentials never enter URLs or browser storage. */
const $=id=>document.getElementById(id);
let csrf='',busy=false,current=null,connections=[],timer=null;
const note=text=>{$('notice').textContent=text;};
function replaceContents(element,...children){while(element.firstChild)element.removeChild(element.firstChild);for(const child of children)element.appendChild(child);}
function controls(){for(const id of ['loginButton','createConnection','refreshConnections','checkConnection','logout'])$(id).disabled=busy;for(const id of ['copyAgent','copyMcp'])$(id).disabled=busy||!current||(current.connection&&current.connection.revoked);for(const id of ['connectionSelect','librarySelect','connectionName','adminToken'])$(id).disabled=busy;}
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
 const capture=connection.capture||{},count=Number(capture.automatic_dialogues_saved||0);
 if(connection.archive_status==='automatic_connected'&&count>0)return ['已验证收到自动记录',`已保存 ${count} 轮完整对话。继续使用原配置即可。`];
 if(connection.archive_status==='archive_failed')return ['记录尚未完成','服务报告存档失败，请打开完整记忆界面查看状态；不要重新创建身份。'];
 return connection.host_online?['记忆工具已连接','尚未验证自动记录。请让 Agent 配置宿主的轮次结束回调，再完成一轮真实对话。']:['等待 Agent 加载配置','让有工具或宿主配置能力的 Agent 保存并加载配置，然后调用 memory_status 核对。'];
}
function renderCapture(connection){const [title,detail]=captureCaption(connection);$('captureState').textContent=title;$('captureDetails').textContent=detail;}
function showConfig(bundle){
 const text=mcpText(bundle);if(!text)throw new Error('服务没有返回可用的 HTTPS MCP 配置，请更新记忆服务。');
 current=bundle;$('configPanel').hidden=false;$('configHeading').textContent=bundle.connection.name||'让 Agent 保存并加载';
 $('connectionTarget').textContent='固定存档：'+bundle.connection.library_id+' · '+(bundle.connection.session_scope==='next_session'?'首轮完整对话后固定目标窗口':'仅当前连接绑定的窗口');
 $('mcpConfig').value=text;$('agentSetup').value=bundle.agent_setup_text||['请把以下 HTTPS MCP 配置保存到你的宿主设置并加载，调用 memory_status 与 memory_bootstrap 核对身份和存档。','不需要聊天模型 API Key。自动记录需要宿主的真实轮次结束回调；工具连通不代表已经自动存档。',text].join('\n\n');
 $('hookConfig').value=JSON.stringify(bundle.hook_config||{},null,2);renderCapture(bundle.connection);controls();
}
async function refresh(){
 const result=await api('admin/connections');connections=result.connections||[];const selected=current&&current.connection&&current.connection.id;
 replaceContents($('connectionSelect'),new Option('选择连接，或在下面创建',''),...connections.filter(c=>!c.revoked&&c.host==='agent').map(c=>new Option(c.name+' · '+c.library_id,c.id)));
 if(selected){$('connectionSelect').value=selected;const latest=connections.find(c=>c.id===selected);if(latest){current.connection=latest;renderCapture(latest);}}
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
 $('logout').onclick=()=>operation(async()=>{await api('admin/logout',{});clearInterval(timer);csrf='';current=null;connections=[];for(const id of ['agentSetup','mcpConfig','hookConfig'])$(id).value='';$('workspace').hidden=true;$('configPanel').hidden=true;$('loginPanel').hidden=false;note('已退出服务管理。已交给 Agent 的连接凭据仍由对应连接管理。');});
 api('health').then(data=>{$('version').textContent=data.version||'0.8 记忆服务';return api('admin/session').then(session=>{csrf=session.csrf_token||'';return openWorkspace();});}).catch(()=>{});controls();
}
export {mcpText,captureCaption};
