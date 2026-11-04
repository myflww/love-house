/* Love House guided chat connection. Reuses the audited connection APIs and fixed library binding. */
(()=>{
'use strict';
if(typeof MEMORY==='undefined'||!document.getElementById('connectionsPanel'))return;
const remoteHost=window.LoveHouseRemote===true;
const by=id=>document.getElementById(id), make=(tag,cls,text)=>el(tag,cls,text);
const style=document.createElement('style');style.textContent=`
#aiPanel{width:min(440px,calc(100vw - 28px))}.connect-target{padding:12px 14px;border:1px solid var(--line);border-radius:10px;margin:0 0 16px;background:var(--soft)}.connect-target strong{display:block;font-size:14px}.connect-target p{margin:4px 0 0;color:var(--muted);font-size:12px}.connect-primary{width:100%;margin:12px 0}.connect-other{margin-top:16px}.connect-other>summary{font-size:12px;padding:8px 0}.connect-other .connections-list{margin-top:10px}.connect-guide{border:1px solid var(--line);border-radius:12px;padding:14px;margin-top:16px}.connect-guide h3{font-size:14px;color:var(--ink);letter-spacing:0}.connect-steps{list-style:none;padding:0;margin:12px 0}.connect-steps li{display:flex;gap:10px;align-items:flex-start;padding:9px 0;border-bottom:1px solid var(--line);font-size:12px}.connect-step-number{width:22px;height:22px;border-radius:50%;border:1px solid var(--line);display:grid;place-items:center;flex-shrink:0;font:11px ui-monospace,monospace}.connect-steps li[data-done=true] .connect-step-number{background:var(--ink);color:var(--paper)}.connect-steps small{display:block;margin-top:3px}.connect-guide-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}.connect-guide .form-note{line-height:1.7;overflow-wrap:anywhere}.agent-config-preview input{width:100%;max-width:100%;font:12px/1.6 ui-monospace,monospace}.connect-mismatch{margin:10px 0;padding:10px;border:1px solid var(--line);border-radius:8px}.connect-mismatch p{font-size:12px;margin-bottom:7px}.connect-card-actions{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}.connection-card.current-chat{border-color:var(--muted)}#connectionWizardDialog{width:min(560px,calc(100vw - 28px));max-height:calc(100vh - 40px);overflow:auto;padding:25px;border:1px solid var(--line);border-radius:18px;background:var(--paper);color:var(--ink)}#connectionWizardDialog::backdrop{background:rgba(0,0,0,.58)}.wizard-heading{display:flex;justify-content:space-between;gap:15px;align-items:center}.wizard-heading h2{font-size:19px}.wizard-progress{display:flex;gap:8px;margin:20px 0 22px;font-size:11px;color:var(--muted)}.wizard-progress span{flex:1;padding-bottom:8px;border-bottom:2px solid var(--line)}.wizard-progress span[aria-current=step]{color:var(--ink);border-color:var(--ink)}.wizard-choice{display:block;width:100%;text-align:left;border:1px solid var(--line);border-radius:12px;padding:16px;margin:10px 0;background:var(--panel)}.wizard-choice strong{display:block;font-size:15px}.wizard-choice small{display:block;margin-top:5px;line-height:1.7}.wizard-choice[aria-pressed=true]{border-color:var(--ink);background:var(--soft)}.wizard-foot{display:flex;justify-content:space-between;gap:12px;margin-top:22px}.wizard-screen>h3{color:var(--ink);font-size:15px;letter-spacing:0;margin-bottom:12px}.wizard-screen label:not(.inline-check){display:block;margin:12px 0 6px;font-size:12px}.wizard-screen input:not([type=checkbox]),.wizard-screen select{width:100%}.wizard-screen details{border-top:1px solid var(--line);padding-top:10px}.wizard-screen details summary{font-size:12px}.wizard-library-note{font-size:12px;color:var(--muted);margin-top:12px}.connect-status{padding:8px 0;font-size:12px}.connect-restart-note{padding:10px;margin:12px 0;background:var(--soft);border:1px solid var(--line);font-size:12px;line-height:1.7}.agent-copy-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.agent-config-preview textarea{width:100%;min-height:130px;font:12px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace}.wizard-advanced-paths{margin-top:15px}.wizard-advanced-paths summary{font-size:12px;color:var(--muted)}.connect-config-advanced{margin-top:15px;border-top:1px solid var(--line);padding-top:10px}#connectionConfigPanel>h3{font-size:14px;color:var(--ink);letter-spacing:0}#clientKeyRow .ai-compose-actions,#apiBaseRow .ai-compose-actions{flex-wrap:wrap}#clientApiKey{max-width:100%}@media(max-width:640px){#connectionWizardDialog{padding:18px}.wizard-progress{gap:5px}.connect-card-actions .btn{flex-grow:1}}`;
style.textContent+='#agentConnectionConfigPath{width:100%;font:12px/1.6 ui-monospace,monospace}#workbuddyPlanBody{overflow-wrap:anywhere}#rebindConnectionSummary{white-space:pre-line}#rebindConnectionDialog{width:min(540px,calc(100vw - 28px))}';
document.head.append(style);
const panel=by('connectionsPanel');panel.querySelector(':scope>.form-note').textContent='选择运行大肥鱼的程序，再选它的记忆库。';
const target=make('div','connect-target');target.id='connectionTargetSummary';panel.prepend(target);
by('connectTab').textContent='连接';by('activityTab').textContent='存档记录';by('aiPanel').setAttribute('aria-label','连接聊天与记忆');
by('aiPanel').querySelector('.inspector-top strong').textContent='连接运行程序';
by('companionBtn').setAttribute('data-hint-title','连接聊天');by('companionBtn').setAttribute('data-hint-description','把运行大肥鱼的程序接到指定记忆库；可查看接收范围、人格和存档记录。');
const oldNew=by('newConnectionDetails'), content=[...oldNew.children].filter(x=>x.tagName!=='SUMMARY');
const start=make('div','connect-start');start.id='newConnectionDetails';const startButton=make('button','btn primary connect-primary','连接一条大肥鱼');startButton.id='startConnectionWizard';start.append(startButton);oldNew.replaceWith(start);
const dialog=make('dialog','');dialog.id='connectionWizardDialog';dialog.setAttribute('aria-labelledby','connectionWizardTitle');
const header=make('div','wizard-heading'),title=make('h2','','连接运行程序');title.id='connectionWizardTitle';const close=make('button','icon-btn','×');close.id='closeConnectionWizard';close.setAttribute('aria-label','关闭连接向导');header.append(title,close);
const progress=make('div','wizard-progress');progress.setAttribute('aria-label','连接步骤');for(const text of ['1 运行程序','2 记忆库','3 完成连接'])progress.append(make('span','',text));
const screens=[1,2,3].map(n=>{const s=make('section','wizard-screen');s.dataset.step=String(n);return s;});
screens[0].append(make('h3','','大肥鱼由哪个程序运行？'));
let agentProgram='generic';
const choices={};
function connectionChoice(host,name,description,destination){const b=make('button','wizard-choice');b.dataset.host=host;b.append(make('strong','',name),make('small','',description));b.onclick=()=>{agentProgram='generic';by('connectionHost').value=host;connectionHostChanged();if(host!=='api')by('providerKey').value='';go(2);};choices[host]=b;destination.append(b);return b;}
connectionChoice('harness','DeepSeek Harness','一键安装自动存档插件，适合在 Harness 里聊天。',screens[0]).hidden=remoteHost;
const astrbotChoice=make('button','wizard-choice');astrbotChoice.id='connectionAstrBotChoice';astrbotChoice.type='button';astrbotChoice.append(make('strong','','AstrBot'),make('small','','到 AstrBot 的爱之屋插件里填写配置；QQ、网页聊天是它的活动入口。'));astrbotChoice.onclick=()=>{if(MEMORY.busy||writeBusy||S.libraryChanging||S.isDemo||!canManageMemory())return;dialog.close();if(window.LoveHouseSources)window.LoveHouseSources.open();};screens[0].append(astrbotChoice);
const workbuddyChoice=make('button','wizard-choice');workbuddyChoice.id='connectionWorkBuddyChoice';workbuddyChoice.type='button';workbuddyChoice.append(make('strong','','WorkBuddy'),make('small','','生成本机记忆配置，可预览并合并到 WorkBuddy；需要在 WorkBuddy 中信任连接器。'));workbuddyChoice.onclick=()=>{if(MEMORY.busy||writeBusy||S.libraryChanging||S.isDemo||!canManageMemory())return;agentProgram='workbuddy';by('connectionHost').value='agent';connectionHostChanged();by('providerKey').value='';go(2);};screens[0].append(workbuddyChoice);
workbuddyChoice.hidden=remoteHost;
connectionChoice('agent',remoteHost?'有 Agent 能力的聊天窗口':'其他 Agent · 复制记忆连接配置',remoteHost?'生成 HTTPS 记忆连接配置，交给 Agent 自己保存并加载；继续使用这台服务上的同一份存档。':'把 MCP 配置填到运行程序的设置，或交给能修改设置的后台配置助手；仅发到普通 QQ 聊天不会安装。',screens[0]);
const advancedPaths=make('details','wizard-advanced-paths');advancedPaths.append(make('summary','','高级方式：模型 API 转发'));
connectionChoice('api','可选：通过爱之屋转发模型请求','仅当你需要替换聊天软件的模型地址时使用；它与直接连接记忆服务是两种方式。',advancedPaths);advancedPaths.hidden=remoteHost;screens[0].append(advancedPaths);
screens[0].append(make('p','form-note',remoteHost?'爱之屋只连接你选定的 Agent 和记忆库。把 HTTPS 配置交给具有宿主配置能力的 Agent 保存并加载。':'爱之屋只连接你选定的 Agent 和记忆库。复制配置后，需要由具备本机工具配置能力的 Agent 或宿主加载。'));
const fields=make('div','');for(const node of content)fields.append(node);
const pair=(id,destination)=>{const input=by(id)||fields.querySelector('#'+id);if(!input)return;const label=fields.querySelector('label[for="'+id+'"]');if(label)destination.append(label);destination.append(input);};
screens[1].append(make('h3','','它的记忆存到哪个库？'));pair('connectionLibrary',screens[1]);
const newLibLabel=make('label','inline-check'),newLib=make('input','');newLib.type='checkbox';newLib.id='wizardNewLibrary';newLibLabel.append(newLib,document.createTextNode('为另一个 Agent 新建空白记忆库'));screens[1].append(newLibLabel);
const newLibName=make('input','');newLibName.id='wizardLibraryName';newLibName.placeholder='给这个 Agent 的记忆库起个名字';newLibName.maxLength=80;newLibName.setAttribute('aria-label','新记忆库名称');newLibName.hidden=true;screens[1].append(newLibName,make('p','wizard-library-note','选择已有库会延续它的全部可用记忆；新建空白库才会建立独立身份。同一窗口只加载一个库的配置。'));
const hostSelect=fields.querySelector('#connectionHost');const agentOption=make('option','','通用 Agent 记忆连接');agentOption.value='agent';hostSelect.append(agentOption);hostSelect.hidden=true;screens[0].append(hostSelect);const hostLabel=fields.querySelector('label[for=connectionHost]');if(hostLabel)hostLabel.remove();
const previousHostChanged=connectionHostChanged;connectionHostChanged=function(){previousHostChanged();const agent=hostSelect.value==='agent';if(agent)by('connectionScopeMode').value='next_session';by('connectionScopeMode').hidden=false;const label=document.querySelector('label[for=connectionScopeMode]');if(label)label.hidden=false;if(agent)by('connectionScopeRow').hidden=true;updateWindowScope();};hostSelect.onchange=connectionHostChanged;
const apiScreen=make('div','');apiScreen.id='providerFields';const oldProvider=fields.querySelector('#providerFields');
// Move the original input elements, preserving all existing validation and secure-key handlers.
if(oldProvider){while(oldProvider.firstChild)fields.append(oldProvider.firstChild);oldProvider.remove();}
apiScreen.append(make('h3','','高级：模型 API 转发'));for(const id of ['providerPreset','providerModel','providerKey'])pair(id,apiScreen);
apiScreen.querySelector('label[for=providerKey]').textContent='厂商 API Key';apiScreen.querySelector('label[for=providerModel]').textContent='模型名称（与聊天软件一致）';
const apiAdvanced=make('details',''),apiSummary=make('summary','','API 地址与安全保存');apiAdvanced.append(apiSummary);pair('providerBaseUrl',apiAdvanced);const saveControl=fields.querySelector('#providerSaveKey');const saveLabel=saveControl&&saveControl.closest('label');if(saveLabel)apiAdvanced.append(saveLabel);apiScreen.append(apiAdvanced,make('p','form-note','此方式代你转发模型请求，才需要厂商 Key。只想让 Agent 读写记忆，请返回第一步选择“其他 Agent”。'));
const harnessScreen=make('div','');harnessScreen.id='wizardHarness';harnessScreen.append(make('h3','','连接 DeepSeek Harness'),make('p','form-note','会为这个记忆库安装自动存档插件，并先备份原配置。完成后在 Harness 重载插件（或重启一次），再到目标窗口发消息。'));
const harnessPaths=make('details','wizard-advanced-paths');harnessPaths.id='harnessManualPaths';harnessPaths.append(make('summary','','未找到 Harness？指定安装位置'));
for(const [id,label,placeholder] of [['harnessAppPath','Harness 安装目录或程序路径','例如：C:\\Users\\你的名字\\AppData\\Local\\Programs\\DeepSeek Harness\\DeepSeek Harness.exe'],['harnessProfilePath','Harness 配置目录（可选）','默认使用当前用户的 .dsh/profiles/desktop']]){const caption=make('label','',label);caption.htmlFor=id;const input=make('input','');input.id=id;input.placeholder=placeholder;input.autocomplete='off';harnessPaths.append(caption,input);}
harnessScreen.append(harnessPaths);
function harnessPathOptions(){
 const prefix=dialog.open?'harness':'guideHarness';const options={};for(const [id,key] of [[prefix+'AppPath','app_path'],[prefix+'ProfilePath','profile_dir']]){const input=by(id);const value=input&&typeof input.value==='string'?input.value.trim():'';if(value)options[key]=value.replace(/^"([^]*?)"$/,'$1');}return options;
}
const previousDetectHarness=detectHarness;detectHarness=async function(){
 const options=harnessPathOptions();if(!Object.keys(options).length)return previousDetectHarness();
 if(MEMORY.busy)return;MEMORY.busy=true;updateWriteState();
 try{const result=await api('adapters/harness/detect',options,{scope:false});MEMORY.detect=result;by('adapterDetection').textContent=result.message||(result.supported?`已检测到 Harness ${result.version}，可以安装自动存档插件。`:result.detected?`已找到 Harness，但版本 ${result.version||'未知'} 尚未支持。`:'未找到有效的 Harness 安装，请核对程序路径和配置目录。');}
 catch(e){by('adapterDetection').textContent='检测失败：'+e.message;}finally{MEMORY.busy=false;updateWriteState();}
};
const detect=fields.querySelector('#adapterDetection');if(detect)harnessScreen.append(detect);const detectButton=fields.querySelector('#detectHarnessBtn');if(detectButton){detectButton.textContent='重新检测 Harness';harnessScreen.append(detectButton);}
const agentScreen=make('div','');agentScreen.id='wizardAgent';const agentScreenTitle=make('h3','',remoteHost?'生成 HTTPS 记忆连接配置':'生成本机记忆连接配置');agentScreen.append(agentScreenTitle,make('p','form-note','爱之屋会为所选记忆库生成 MCP 配置，无需填写聊天模型的 API Key。整理 AI 的模型与 Key 在“记忆整理”中单独配置。'));
const restartNote=make('p','connect-restart-note','原窗口的稳定会话ID不变时，重启会按原配置重连。更换窗口可在管理连接里重新绑定：记忆保留，旧配置失效后生成新配置。');agentScreen.append(restartNote,make('p','form-note','要每轮自动保存，还需要宿主加载轮次结束钩子；MCP 工具可用本身不等于已经自动记录。普通网页聊天若没有本机工具能力，不能仅靠粘贴文字建立连接。'));
screens[2].append(apiScreen,harnessScreen,agentScreen);
const scopeNotice=make('p','connect-restart-note');scopeNotice.id='windowScopeNotice';const broadLabel=make('label','inline-check'),broadCheck=make('input','');broadCheck.id='allowAllConnectionSessions';broadCheck.type='checkbox';broadLabel.append(broadCheck,document.createTextNode('我明确允许记录这条连接的全部会话，可能包含多个聊天窗口。'));screens[2].append(scopeNotice,broadLabel);
const scopeModeControl=fields.querySelector('#connectionScopeMode')||by('connectionScopeMode');
function updateWindowScope(){const mode=scopeModeControl.value;broadLabel.hidden=mode!=='connection';broadLabel.style.setProperty('display',mode==='connection'?'flex':'none','important');broadCheck.disabled=mode!=='connection';if(mode!=='connection')broadCheck.checked=false;scopeNotice.textContent=mode==='connection'?'记录范围：整条连接。多个窗口若共用此连接，都会进入同一个存档；需要你明确允许。':mode==='specified'?'记录范围：只记录你明确填写的稳定会话ID，其他窗口会被拒绝。':'记录范围：先在目标窗口完成第一轮真实对话，随后固定到这个窗口；其他窗口不写入待发送队列或存档。';if(hostSelect.value==='api'&&mode!=='connection')scopeNotice.textContent+=' API客户端必须上报真实 X-NKB-Session；没有此标识时无法分辨窗口，请使用宿主钩子方式。';}
for(const option of scopeModeControl.options){if(option.value==='connection')option.textContent='此连接全部会话（需明确允许）';if(option.value==='next_session')option.textContent='仅目标窗口（首轮后固定）';if(option.value==='specified')option.textContent='指定窗口 ID（高级）';}scopeModeControl.addEventListener('change',updateWindowScope);

const advanced=make('details',''),advancedTitle=make('summary','','更多选项');advanced.append(advancedTitle);pair('connectionName',advanced);pair('connectionScopeMode',advanced);const scope=fields.querySelector('#connectionScopeRow');if(scope)advanced.append(scope);screens[2].append(advanced);
const create=fields.querySelector('#createConnectionBtn');create.hidden=true;screens[2].append(create);for(const child of [...fields.children])if(!child.matches('label')&&child.id&&!document.getElementById(child.id))screens[2].append(child);
const notice=make('p','form-note');notice.id='connectionWizardNotice';notice.setAttribute('role','status');const foot=make('div','wizard-foot'),back=make('button','btn','上一步'),next=make('button','btn primary','下一步');back.id='connectionWizardBack';next.id='connectionWizardNext';foot.append(back,next);dialog.append(header,progress,...screens,notice,foot);document.body.append(dialog);
let wizardStep=1,creatingLibrary=false,renderKey='';
function sync(){const busy=MEMORY.busy||writeBusy||S.libraryChanging;astrbotChoice.disabled=busy||S.isDemo||!canManageMemory();workbuddyChoice.disabled=busy||S.isDemo||!canManageMemory();astrbotChoice.dataset.hintDescription=S.isDemo?'请先选择或新建个人记忆库；框架示例不接真实输出。':'打开当前存档的AstrBot来源设置，不需要聊天模型Key。';choices.harness.disabled=remoteHost||busy;startButton.disabled=!canManageMemory()||busy;close.disabled=busy;back.disabled=busy;back.hidden=wizardStep===1;next.disabled=busy||!canManageMemory();next.textContent=busy?'处理中…':wizardStep===3?(hostSelect.value==='harness'?'备份配置并连接':hostSelect.value==='agent'?(agentProgram==='workbuddy'?'生成 WorkBuddy 记忆配置':'生成记忆连接配置'):'生成模型转发信息'):'下一步';newLib.disabled=busy;newLibName.disabled=busy;by('connectionLibrary').disabled=busy||newLib.checked;by('connectHarnessNow').disabled=busy||!MEMORY.config||(MEMORY.config.connection&&MEMORY.config.connection.revoked);by('verifyChatConnection').disabled=busy||!MEMORY.config;by('copyAgentSetup').disabled=busy||!isCurrentAgentConfig(MEMORY.config)||!agentPrivatePath(MEMORY.config)||!agentSetupText(MEMORY.config);by('copyAgentMcp').disabled=busy||!isCurrentAgentConfig(MEMORY.config)||!agentPrivatePath(MEMORY.config)||!agentMcpText(MEMORY.config);by('fixConnectionModel').disabled=busy;const cfg=MEMORY.config;if(!isCurrentAgentConfig(cfg)){pathInput.value='';mcpArea.value='';setupArea.value='';workbuddyStatus.textContent='';clearWorkBuddyPlan();workbuddyGuide.open=false;}else if(workbuddyPlan&&!currentConfigRequest(workbuddyPlan.owner,workbuddyPlan.id,workbuddyPlan.version))clearWorkBuddyPlan();workbuddyApply.disabled=busy||!canManageMemory();copyAgentPath.disabled=busy||!isCurrentAgentConfig(cfg)||!agentPrivatePath(cfg);workbuddyNow.disabled=busy||!isCurrentAgentConfig(cfg)||(cfg&&cfg.workbuddy_setup&&cfg.workbuddy_setup.supported)!==true;rebindCancel.disabled=busy;rebindConfirm.disabled=busy;if(rebindDialog.open&&!sameOwner(rebindOwner))closeRebind(false);by('copyClientKey').disabled=busy||(cfg&&cfg.connection&&cfg.connection.revoked)||!(cfg&&cfg.client_api_key)||!((cfg&&cfg.connection&&cfg.connection.provider)||(cfg&&cfg.provider)||{}).credential_ready;}
function go(step){wizardStep=step;updateWindowScope();for(const s of screens)s.hidden=Number(s.dataset.step)!==step;[...progress.children].forEach((x,i)=>{if(i===step-1)x.setAttribute('aria-current','step');else x.removeAttribute('aria-current');});for(const [h,b]of Object.entries(choices))b.setAttribute('aria-pressed',String(h===hostSelect.value&&(h!=='agent'||agentProgram!=='workbuddy')));workbuddyChoice.setAttribute('aria-pressed',String(hostSelect.value==='agent'&&agentProgram==='workbuddy'));agentScreenTitle.textContent=remoteHost?'生成 HTTPS 记忆连接配置':agentProgram==='workbuddy'?'连接 WorkBuddy':'生成本机记忆连接配置';apiScreen.hidden=hostSelect.value!=='api';harnessScreen.hidden=hostSelect.value!=='harness';agentScreen.hidden=hostSelect.value!=='agent';notice.textContent='';sync();if(step===3&&hostSelect.value==='harness')detectHarness().finally(sync);}
async function openWizard(host){if(!canManageMemory()||MEMORY.busy)return;await refreshLibraries();agentProgram=host==='workbuddy'?'workbuddy':'generic';if(host==='workbuddy')host='agent';hostSelect.value=remoteHost?'agent':host||'harness';advancedPaths.open=hostSelect.value==='api';connectionHostChanged();by('connectionLibrary').value=S.isDemo?((MEMORY.libraries.find(x=>!x.is_demo)||{}).id||''):S.libraryId;newLib.checked=false;newLibName.hidden=true;by('connectionName').value='';by('providerKey').value='';go(1);dialog.showModal();(agentProgram==='workbuddy'?workbuddyChoice:choices[hostSelect.value]).focus();}
startButton.onclick=()=>openWizard();close.onclick=()=>{dialog.close();by('providerKey').value='';};dialog.addEventListener('cancel',e=>{if(MEMORY.busy)e.preventDefault();else by('providerKey').value='';});back.onclick=()=>go(wizardStep-1);newLib.onchange=()=>{newLibName.hidden=!newLib.checked;sync();if(newLib.checked)newLibName.focus();};
async function applyHarness(id){const detected=dialog.open?(MEMORY.detect||{}):((MEMORY.config&&MEMORY.config.host_options)||(MEMORY.config&&MEMORY.config.auto_capture&&MEMORY.config.auto_capture.harness&&MEMORY.config.auto_capture.harness.detected)||(MEMORY.config&&MEMORY.config.setup&&MEMORY.config.setup.detected)||{});const args={...(detected.app_path?{app_path:detected.app_path}:{}),...(detected.profile_dir?{profile_dir:detected.profile_dir}:{}),...harnessPathOptions()};const plan=await api('connections/'+encodeURIComponent(id)+'/configure',{...args,apply:false},{scope:false});if(plan.supported===false||(plan.detected&&plan.detected.supported)===false)throw new Error(plan.message||'未检测到受支持的 Harness，请核对安装路径和版本后重试。');const applied=await api('connections/'+encodeURIComponent(id)+'/configure',{...args,apply:true},{scope:false});if(applied.applied!==true)throw new Error(applied.message||'配置尚未应用，请重试。');return applied;}
function connectionPayload({name,host,library_id,session_scope,provider}){
 if(!['harness','agent','api'].includes(host))throw new Error('请选择支持的连接方式。');
 const payload={name,host,library_id,session_scope:session_scope||(host==='api'?'connection':'next_session')};
 if(host==='api'&&provider)payload.provider=provider;
 return payload;
}
next.onclick=async()=>{
 if(MEMORY.busy||!canManageMemory())return;
 if(wizardStep===1){go(2);return;}
 if(wizardStep===2){
  if(newLib.checked){const name=newLibName.value.trim();if(!name){notice.textContent='请先给新记忆库起个名字。';newLibName.focus();return;}MEMORY.busy=true;sync();try{const result=await api('libraries',{name},{scope:false});const id=(result.library&&result.library.id)||result.selected_id;newLib.checked=false;newLibName.hidden=true;await refreshLibraries();by('connectionLibrary').value=id;}catch(e){notice.textContent='创建记忆库失败：'+e.message;return;}finally{MEMORY.busy=false;updateWriteState();sync();}}
  if(!by('connectionLibrary').value){notice.textContent='请选择保存位置。';return;}go(3);return;
 }
 const lib=by('connectionLibrary').value,host=hostSelect.value,scopeMode=by('connectionScopeMode').value,scope=scopeMode==='specified'?by('connectionScope').value.trim():scopeMode;
 let provider;try{if(scope==='connection'&&!broadCheck.checked)throw new Error('请先明确允许记录这条连接的全部会话，或改为单窗口范围。');if(host==='api'){provider=providerPayload('provider');if(!provider.api_key)throw new Error('请填写厂商 API Key，让爱之屋准备可直接使用的接入信息。');}if(!scope)throw new Error('请输入要连接的会话标识。');}catch(e){notice.textContent=e.message;return;}
 MEMORY.busy=true;updateWriteState();sync();let created=null;
 try{
  created=await api('connections',connectionPayload({name:by('connectionName').value.trim()||`${libraryName(lib)} · ${host==='api'?'模型转发':host==='agent'?(agentProgram==='workbuddy'?'WorkBuddy':'Agent 记忆'):'Harness'}`,host,library_id:lib,session_scope:scope,provider}),{scope:false});
  by('providerKey').value='';showConnectionConfig(created);
  if(host==='harness'){notice.textContent='正在备份并连接 Harness…';await applyHarness(created.connection.id);created=await api('connections/'+encodeURIComponent(created.connection.id)+'/config',undefined,{scope:false});}
  dialog.close();MEMORY.busy=false;if(lib!==S.libraryId)await selectMemoryLibrary(lib);showConnectionConfig(created);await refreshConnections();toast(host==='api'?'模型转发入口已准备好；请填回聊天软件。':host==='agent'?'记忆配置已生成；请填到运行程序的 MCP 设置，或交给后台配置助手安装。':'配置已保存；在 Harness 重载插件后，到目标窗口发消息。');
 }catch(e){notice.textContent=e.message;if(created){dialog.close();showConnectionConfig(created);by('connectionGuideNotice').textContent='连接条目已保留：'+e.message;toast('配置尚未完成，请按连接指引继续。',true);}}
 finally{MEMORY.busy=false;updateWriteState();sync();}
};
// Keep complete configuration available, while the primary guide uses human-sized steps.
const configPanel=by('connectionConfigPanel');configPanel.classList.add('connect-guide');
const guideStages=make('ol','connect-steps');guideStages.id='connectionGuideStages';const mismatch=make('div','connect-mismatch');mismatch.id='connectionGuideMismatch';
const guideNotice=make('p','form-note');guideNotice.id='connectionGuideNotice';guideNotice.setAttribute('role','status');
function agentMcpText(cfg){
 if(!cfg||(cfg.connection&&cfg.connection.host)!=='agent'||(cfg.connection&&cfg.connection.revoked))return '';
 let value=cfg.mcp_config;
 if(!value&&typeof cfg.host_config==='string'){try{value=JSON.parse(cfg.host_config);}catch{return '';}}
 return value&&typeof value==='object'&&!Array.isArray(value)&&value.mcpServers&&typeof value.mcpServers==='object'?JSON.stringify(value,null,2):'';
}
function agentSetupText(cfg){
 const config=agentMcpText(cfg);if(!config)return '';
 if(typeof cfg.agent_setup_text==='string'&&cfg.agent_setup_text.trim())return '配置接收方：能修改运行程序设置的后台配置助手；仅有聊天能力的 QQ 或网页窗口不能代装。\n\n'+cfg.agent_setup_text;
 return ['请把以下爱之屋 MCP 记忆服务保存到你的本机 Agent 宿主配置并加载，然后调用 memory_status 确认连接。','无需更换聊天模型，也无需提供模型厂商 API Key。','要每轮自动记录，请检查宿主的轮次结束钩子并安装对应转发配置；若无钩子，只说明工具可用，不要声称已经自动存档。','配置保存一次，下次打开爱之屋与 Agent 宿主会重新发现本机服务。',config].join('\n\n');
}
function agentPrivatePath(cfg){
 if(!cfg||(cfg.connection&&cfg.connection.host)!=='agent'||(cfg.connection&&cfg.connection.revoked))return '';
 const path=cfg.private_path;
 return typeof path==='string'&&path.trim()&&path.length<=8192&&!/[\u0000-\u001f]/.test(path)?path:'';
}
function isCurrentAgentConfig(cfg){
 const c=(cfg&&cfg.connection),latest=c&&MEMORY.connections.find(x=>x.id===c.id);
 return !!c&&c.host==='agent'&&!c.revoked&&!c.registered_source&&!cfg.stale_binding&&c.library_id===S.libraryId&&!S.libraryChanging&&!(Number.isInteger((latest&&latest.binding_revision))&&Number.isInteger(c.binding_revision)&&latest.binding_revision!==c.binding_revision);
}
function connectionPolicy(c){
 const policy=c.session_scope_policy||c.session_scope;
 return policy==='connection'?'any':['fixed','any','next_session'].includes(policy)?policy:policy?'fixed':'next_session';
}
function boundSession(c){
 if(typeof c.bound_session_id==='string'&&c.bound_session_id)return c.bound_session_id;
 const legacy=c.session_scope;
 return legacy&&!['connection','any','fixed','next_session'].includes(legacy)?String(legacy):null;
}
function savedDialogue(c){
 const capture=c.capture||{};
 return Number(capture.complete_dialogues_saved||capture.hook_dialogues_saved||capture.automatic_dialogues_saved||0)>0||['automatic_connected','host_reported'].includes(c.archive_status);
}
function agentConnectionAdvice(c){
 if(c.revoked)return '连接已断开，旧配置不再可用；已存记忆保留。';
 if(c.enabled===false)return '接收已暂停，原存档保留；恢复后再核对新记录。';
 if(c.can_write===false&&!boundSession(c)&&connectionPolicy(c)==='next_session')return '可以查询这份存档，写入等待真实来源绑定。只有宿主真实回调能认领窗口，MCP 手动补录不会认领。请确认运行程序支持回调，再在目标窗口完成一轮对话。';
 if(savedDialogue(c)||c.archive_status==='outputs_only')return '已收到宿主提交的记录；仅在宿主继续上报时保存。一次接收不能证明以后每轮自动记录，请核对最近接收时间与原文。';
 return c.host_online?'记忆工具已连接，请分别核对可读、可写和窗口绑定。WorkBuddy 需要信任自定义连接器并重载；自动存档还需要真实宿主回调。':'配置已生成，等待运行程序加载。WorkBuddy 请先信任自定义连接器；保存文件不等于工具已经加载。';
}
function connectionCapabilities(c){
 if(typeof c.can_read!=='boolean'&&typeof c.can_write!=='boolean')return '';
 return `查询记忆：${c.can_read?'可用':'未就绪'} · 保存记忆：${c.can_write?'可用':c.binding_state==='awaiting_source_turn'?'等待来源绑定':'未就绪'}`;
}
function hookReceiptCaption(c){
 const count=Number((c.capture&&c.capture.hook_event_count)||0);
 return count>0?`已收到 ${count} 次宿主回调；后续记录仍依赖宿主持续上报。`:'MCP 工具连接与自动存档分开核对；未收到回调不代表配置文件丢失。';
}
function connectionConfigPath(cfg){
 if(!cfg||(cfg.connection&&cfg.connection.revoked))return '';
 return typeof cfg.private_path==='string'?cfg.private_path:'';
}
const guideHarnessPaths=harnessPaths.cloneNode(true);guideHarnessPaths.id='guideHarnessManualPaths';for(const input of guideHarnessPaths.querySelectorAll('input'))input.id='guideHarness'+input.id.slice('harness'.length);for(const label of guideHarnessPaths.querySelectorAll('label'))label.htmlFor='guideHarness'+label.htmlFor.slice('harness'.length);
const agentConfigRow=make('section','');agentConfigRow.id='agentMemoryConfigRow';
const agentCopy=make('div','agent-copy-actions'),copyAgent=make('button','btn primary','复制给配置助手'),copyMcp=make('button','btn','复制 MCP 配置');copyAgent.id='copyAgentSetup';copyMcp.id='copyAgentMcp';copyAgent.setAttribute('data-hint-title','复制给配置助手');copyAgent.setAttribute('data-hint-description','把安装说明交给能修改运行程序设置的后台 Agent；普通 QQ 聊天不会完成安装。不会复制模型厂商 Key。');copyMcp.setAttribute('data-hint-title','复制 MCP 配置');copyMcp.setAttribute('data-hint-description','只复制标准 mcpServers JSON，供支持 MCP 的宿主配置页面使用。');agentCopy.append(copyAgent,copyMcp);
const agentPreview=make('details','agent-config-preview');agentPreview.append(make('summary','','查看记忆配置与安装说明'));
const mcpArea=make('textarea',''),setupArea=make('textarea','');mcpArea.id='agentMcpConfig';mcpArea.readOnly=true;mcpArea.setAttribute('aria-label','本机 MCP 记忆连接配置');setupArea.id='agentSetupConfig';setupArea.readOnly=true;setupArea.setAttribute('aria-label','给 Agent 的记忆接入说明');agentPreview.append(mcpArea,setupArea);
const pathRow=make('div','agent-config-preview'),pathLabel=make('label','','实际生成的私有配置路径'),pathInput=make('input',''),copyAgentPath=make('button','btn','复制配置路径');pathInput.id='agentConnectionConfigPath';pathInput.readOnly=true;pathInput.setAttribute('aria-label','实际生成的私有配置完整路径');pathLabel.htmlFor=pathInput.id;copyAgentPath.id='copyAgentConfigPath';copyAgentPath.dataset.hintDescription='复制爱之屋已生成的连接文件路径，只交给选定的本机运行程序。';pathRow.append(pathLabel,pathInput,copyAgentPath);
const workbuddyGuide=make('details','agent-config-preview');workbuddyGuide.id='workbuddyConnectionGuide';const workbuddyStatus=make('p','form-note');workbuddyStatus.id='workbuddyInstallStatus';workbuddyGuide.append(make('summary','','在 WorkBuddy 里连接'),make('p','form-note','把配置交给 WorkBuddy 的后台配置助手，或预览后合并到 WorkBuddy 自定义连接器。随后在 WorkBuddy 中信任连接器，工具未刷新时重载或重启，再调用 memory_status、memory_bootstrap 核对存档。'),make('p','form-note','WorkBuddy 桌面端读取用户 hooks 的能力尚未确认。MCP 工具可读写与每轮自动记录是两项能力；手动上报一次只证明该次记录已收到。'),workbuddyStatus);
agentConfigRow.append(make('p','connect-restart-note','交给谁：能修改运行程序设置的后台配置助手。自己填写时，使用“复制 MCP 配置”，粘贴到该程序的 MCP 设置。'),agentCopy,pathRow,make('p','connect-restart-note','原窗口重启后按原配置连接。更换窗口可在“管理连接”里重新绑定：记忆保留，旧配置失效后换发新配置。'),make('p','form-note',remoteHost?'此配置连接你自己的 HTTPS 记忆服务；只交给你信任的 Agent，配置不会访问其他存档。':'本机配置路径和 127.0.0.1 只属于当前电脑，不能直接搬到云服务器使用。'),workbuddyGuide,agentPreview);
copyAgentPath.onclick=()=>{if(MEMORY.busy||!isCurrentAgentConfig(MEMORY.config))return;const path=agentPrivatePath(MEMORY.config);if(!path)return;pathInput.value=path;copyMemoryText(pathInput.id);};
copyAgent.onclick=()=>{if(MEMORY.busy||!isCurrentAgentConfig(MEMORY.config))return;const text=agentSetupText(MEMORY.config);if(!text){toast('记忆配置尚未生成完整，请刷新接入信息。',true);return;}setupArea.value=text;copyMemoryText('agentSetupConfig');};
copyMcp.onclick=()=>{if(MEMORY.busy||!isCurrentAgentConfig(MEMORY.config))return;const text=agentMcpText(MEMORY.config);if(!text){toast('MCP 配置尚未生成完整，请刷新接入信息。',true);return;}mcpArea.value=text;copyMemoryText('agentMcpConfig');};
const fixModel=make('button','btn','模型与密钥');fixModel.id='fixConnectionModel';fixModel.onclick=()=>{if(MEMORY.config)openProviderEditor(MEMORY.config.connection);};
const guideActions=make('div','connect-guide-actions'),harnessNow=make('button','btn primary','备份配置并连接 Harness'),workbuddyNow=make('button','btn','预览 WorkBuddy 配置'),verify=make('button','btn','检查是否收到对话'),openTarget=make('button','btn','打开保存的记忆库');harnessNow.id='connectHarnessNow';workbuddyNow.id='connectWorkBuddyNow';verify.id='verifyChatConnection';openTarget.id='openConnectionLibrary';guideActions.append(harnessNow,workbuddyNow,verify,openTarget,fixModel);
configPanel.insertBefore(mismatch,configPanel.firstChild);configPanel.insertBefore(guideStages,by('connectionConfigNote'));configPanel.insertBefore(guideNotice,by('connectionConfigNote'));configPanel.insertBefore(guideActions,by('connectionConfigNote'));
const configAdvanced=make('details','connect-config-advanced');configAdvanced.append(make('summary','','高级配置与修改明细'));for(const id of ['configureActions','connectionPlan']){const item=by(id);if(item){const disclosure=item.closest('details');configAdvanced.append(disclosure&&disclosure!==configAdvanced?disclosure:item);}}const fullConfiguration=by('connectionConfig').closest('details');configAdvanced.prepend(fullConfiguration,by('copyConnectionConfig'));
const configTitle=by('connectionConfigTitle'),configNote=by('connectionConfigNote');configPanel.replaceChildren(configTitle,mismatch,agentConfigRow,guideStages,by('apiBaseRow'),by('clientKeyRow'),guideActions,guideNotice,configNote,guideHarnessPaths,configAdvanced);
let workbuddyPlan=null,rebindOwner=null,rebindTarget=null;
const sameOwner=o=>!!o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch;
const ownerNow=()=>({id:S.libraryId,epoch:S.libraryEpoch});
const currentConfigRequest=(owner,id,version)=>sameOwner(owner)&&MEMORY.configVersion===version&&(MEMORY.config&&MEMORY.config.connection&&MEMORY.config.connection.id)===id&&isCurrentAgentConfig(MEMORY.config);
const workbuddyPlanBody=make('div','connect-restart-note');workbuddyPlanBody.id='workbuddyPlanBody';const workbuddyApply=make('button','btn primary','备份并合并到 WorkBuddy');workbuddyApply.id='applyWorkBuddyConfig';workbuddyApply.hidden=true;workbuddyApply.dataset.hintDescription='只合并这条记忆连接，备份原 MCP 文件并回读核对；仍需在 WorkBuddy 中信任和加载。';workbuddyGuide.append(workbuddyPlanBody,workbuddyApply);
function clearWorkBuddyPlan(){workbuddyPlan=null;workbuddyPlanBody.replaceChildren();workbuddyApply.hidden=true;}
function showWorkBuddyPlan(plan,owner,id,version){
 clearWorkBuddyPlan();workbuddyGuide.open=true;
 for(const [label,value]of [['MCP 目标文件',plan.config_path],['本连接私有文件',plan.private_path]])if(typeof value==='string')workbuddyPlanBody.append(make('strong','',label),make('p','',value));
 workbuddyPlanBody.append(make('p','form-note','只合并当前连接，保留其他连接器；先备份，再写入并回读。写入成功后仍需在 WorkBuddy 内信任、加载工具。'));
 if(plan.supported===true&&plan.config_path&&plan.private_path){workbuddyPlan={owner,id,version,plan};workbuddyApply.hidden=false;}else workbuddyPlanBody.append(make('p','form-note',plan.message||'此安装位置暂不支持自动合并，请按完整配置手动安装。'));
}
async function previewWorkBuddy(){
 if(remoteHost||MEMORY.busy||!canManageMemory()||!isCurrentAgentConfig(MEMORY.config))return;
 const owner=ownerNow(),id=MEMORY.config.connection.id,version=MEMORY.configVersion;MEMORY.busy=true;updateWriteState();
 try{const plan=await api('connections/'+encodeURIComponent(id)+'/workbuddy/configure',{apply:false},{scope:false});if(currentConfigRequest(owner,id,version))showWorkBuddyPlan(plan,owner,id,version);}
 catch(e){if(currentConfigRequest(owner,id,version))guideNotice.textContent='WorkBuddy 配置预览失败：'+e.message;}
 finally{MEMORY.busy=false;updateWriteState();}
}
async function applyWorkBuddy(){
 const target=workbuddyPlan;if(remoteHost||!target||MEMORY.busy||!canManageMemory()||!currentConfigRequest(target.owner,target.id,target.version))return;
 MEMORY.busy=true;updateWriteState();workbuddyApply.disabled=true;
 try{const applied=await api('connections/'+encodeURIComponent(target.id)+'/workbuddy/configure',{apply:true},{scope:false});if(!applied.applied||!applied.readback_verified)throw new Error(applied.message||'配置未通过回读核对。');if(!currentConfigRequest(target.owner,target.id,target.version))return;const cfg=await api('connections/'+encodeURIComponent(target.id)+'/config',undefined,{scope:false});if(!currentConfigRequest(target.owner,target.id,target.version))return;cfg.workbuddy_setup=applied;showConnectionConfig(cfg);workbuddyGuide.open=true;guideNotice.textContent='配置已备份、合并并回读核对。请在 WorkBuddy 自定义连接器中信任并加载；工具未出现时重载或重启。未启用未经确认的桌面 Hook。';await refreshConnections();}
 catch(e){if(sameOwner(target.owner))guideNotice.textContent='WorkBuddy 配置未完成：'+e.message;}
 finally{MEMORY.busy=false;workbuddyApply.disabled=false;updateWriteState();}
}
workbuddyNow.onclick=previewWorkBuddy;workbuddyApply.onclick=applyWorkBuddy;
const rebindDialog=make('dialog','portability-dialog');rebindDialog.id='rebindConnectionDialog';rebindDialog.setAttribute('aria-labelledby','rebindConnectionTitle');const rebindTitle=make('h2','','重新绑定到新窗口');rebindTitle.id='rebindConnectionTitle';const rebindSummary=make('p','connect-restart-note');rebindSummary.id='rebindConnectionSummary';const rebindCancel=make('button','btn','取消'),rebindConfirm=make('button','btn primary','换发配置并等待新窗口');rebindCancel.id='cancelConnectionRebind';rebindConfirm.id='confirmConnectionRebind';const rebindActions=make('div','connect-card-actions');rebindActions.append(rebindCancel,rebindConfirm);rebindDialog.append(rebindTitle,rebindSummary,make('p','form-note','历史记忆保持。旧窗口和旧连接配置立即失效；把新配置加载到目标运行程序，再由新窗口的首次真实回调完成绑定。MCP 手动补录不能认领窗口。'),rebindActions);document.body.append(rebindDialog);
function closeRebind(restore=true){const owner=rebindOwner;rebindDialog.close();rebindOwner=null;rebindTarget=null;rebindSummary.textContent='';if(restore&&sameOwner(owner))by('companionBtn').focus();}
function rebindConnection(item){
 if(MEMORY.busy||!canManageMemory()||item.host!=='agent'||item.registered_source||item.revoked)return;
 if(item.library_id!==S.libraryId){toast('请先打开这条连接所属的记忆库，再重新绑定窗口。');return;}
 rebindOwner=ownerNow();rebindTarget={...item};rebindSummary.textContent=`连接：${item.name}\n记忆库：${libraryName(item.library_id)}\n当前窗口：${boundSession(item)||'等待绑定'}`;rebindDialog.showModal();rebindCancel.focus();
}
async function confirmConnectionRebind(){
 const item=rebindTarget,owner=rebindOwner;if(!item||!sameOwner(owner)||MEMORY.busy||!canManageMemory()||item.registered_source)return;
 MEMORY.busy=true;MEMORY.configVersion++;MEMORY.config=null;mcpArea.value='';setupArea.value='';pathInput.value='';clearWorkBuddyPlan();updateWriteState();
 try{const cfg=await api('connections/'+encodeURIComponent(item.id)+'/rebind',{confirm:true,expected_bound_session_id:boundSession(item)},{scope:false});if(!sameOwner(owner))return;if(!cfg.connection||cfg.connection.id!==item.id||cfg.connection.library_id!==item.library_id)throw new Error('新配置归属未通过核对，请刷新连接信息。');MEMORY.connections=MEMORY.connections.map(c=>c.id===item.id?cfg.connection:c);closeRebind(false);showConnectionConfig(cfg);await refreshConnections();if(sameOwner(owner))guideNotice.textContent='已保留记忆并换发配置。旧配置已失效，请将新配置加载到目标运行程序，再等待新窗口真实上报。';}
 catch(e){if(sameOwner(owner)){closeRebind(false);guideNotice.textContent='重新绑定未完成：'+e.message;toast('请刷新这条连接的信息；已有记忆保留。',true);}}
 finally{MEMORY.busy=false;updateWriteState();}
}
rebindCancel.onclick=()=>closeRebind();rebindConfirm.onclick=confirmConnectionRebind;rebindDialog.addEventListener('cancel',event=>{event.preventDefault();if(!MEMORY.busy)closeRebind();});
by('copyApiBase').textContent='复制到 API 地址';by('copyClientKey').textContent='复制到 API Key';by('copyClientKey').setAttribute('data-hint-description','复制本地连接密钥，填进聊天软件的 API Key 一栏；不会复制厂商密钥。');
function refreshGuide(){
 const cfg=MEMORY.config;if(!cfg)return;
 const latest=MEMORY.connections.find(x=>x.id===cfg.connection.id);
 if(Number.isInteger((latest&&latest.binding_revision))&&Number.isInteger(cfg.connection.binding_revision)&&latest.binding_revision!==cfg.connection.binding_revision){cfg.stale_binding=true;cfg.host_config='';cfg.mcp_config=null;cfg.private_path='';cfg.agent_setup_text='';by('connectionConfig').value='';guideNotice.textContent='这条连接已换发配置，旧配置不再可用。请从连接列表重新查看。';sync();return;}
 const c=latest||cfg.connection;cfg.connection=c;const isAPI=c.host==='api',isAgent=c.host==='agent',saved=savedDialogue(c),configured=!!c.configured_at||cfg.configuration_ready;
 by('connectionConfigTitle').textContent=`${c.name} · 记忆存入 ${libraryName(c.library_id)}`;guideStages.replaceChildren();
 const ready=!!(c.provider||cfg.provider||{}).credential_ready;fixModel.hidden=!isAPI;
 let rows;
 if(isAgent){
  const prepared=!!agentMcpText(cfg)&&!!agentPrivatePath(cfg),bound=!!boundSession(c)||connectionPolicy(c)==='any';
  rows=[[prepared,'配置文件已生成',prepared?'复制真实路径或 MCP 配置，交给运行程序的配置助手；不需要模型厂商 Key。':'配置文件未准备完整，请刷新连接信息，按诊断提示重新生成。'],
        [!!c.host_online,'加载工具并核对存档',c.host_online?'记忆工具已响应；请调用 memory_status、memory_bootstrap 核对存档身份。':'保存 MCP 配置后，在 WorkBuddy 中信任连接器，工具未出现时重载或重启。'],
        [bound,'绑定目标窗口',bound?windowScopeCaption(c):'等待目标窗口的真实来源回调。MCP 手动补录不会认领窗口。'],
        [saved||c.archive_status==='outputs_only','核对实际接收',agentConnectionAdvice(c)]];
 }else if(isAPI){rows=[[ready,ready?'模型转发入口已准备好':'先设置转发模型与密钥',ready?'复制下方地址与连接密钥。':'这仅用于高级模型转发，点击“模型与密钥”设置。'],[saved,'填回模型 API 设置','在聊天软件中填写地址和连接密钥，模型名称保持一致。'],[saved,'核对真实对话',saved?'已收到经过此入口的完整对话。':'完成一轮对话后，再核对实际接收记录。']];
 }else{const bound=!!boundSession(c)||connectionPolicy(c)==='any';rows=[[configured,'安装自动存档插件',configured?'配置已安装，原配置已备份。':'点击“备份配置并连接 Harness”。'],[bound||saved,'在目标 Harness 窗口发消息',bound?windowScopeCaption(c):c.host_online?'插件在线，等待目标窗口首次真实上报。':'重载 Harness 插件或重启，再到目标窗口发消息。'],[saved,'核对完整对话',saved?'已收到完整对话，请继续以最近接收时间和原文核对后续上报。':'整轮结束后进入召回；不需要整理模型 Key。']];}
 rows.forEach(([done,label,note],i)=>{const li=make('li','');li.dataset.done=String(done);li.append(make('span','connect-step-number',String(i+1)));const body=make('div','');body.append(make('strong','',label),make('small','',note));li.append(body);guideStages.append(li);});
 mismatch.replaceChildren();mismatch.hidden=c.library_id===S.libraryId;if(!mismatch.hidden)mismatch.append(make('p','',`你正在浏览“${libraryName(S.libraryId)}”，这条连接保存在“${libraryName(c.library_id)}”。`));
 agentConfigRow.hidden=!isAgent;configAdvanced.hidden=isAgent;
 if(isAgent){mcpArea.value=agentMcpText(cfg);setupArea.value=agentSetupText(cfg);pathInput.value=agentPrivatePath(cfg);pathRow.hidden=remoteHost;const wb=cfg.workbuddy_setup;workbuddyStatus.textContent=(wb&&wb.readback_verified)?'MCP 文件已回读匹配：'+wb.config_path+'。仍需在 WorkBuddy 内信任并加载。':(wb&&wb.config_path)?'配置将合并到：'+wb.config_path+'。预览后再确认写入，保留其他连接器。':'尚未获得 WorkBuddy 配置位置，请先预览或按完整 MCP 配置手动安装。';workbuddyGuide.open=agentProgram==='workbuddy'||workbuddyGuide.open;}
 by('apiBaseRow').hidden=!isAPI;by('clientKeyRow').hidden=!isAPI||!cfg.client_api_key;harnessNow.hidden=remoteHost||isAPI||(isAgent?!!(cfg.auto_capture&&cfg.auto_capture.harness&&cfg.auto_capture.harness.configured):configured)||!c.enabled;harnessNow.textContent=isAgent?'安装 Harness 自动上报':'备份配置并连接 Harness';guideHarnessPaths.hidden=remoteHost||isAPI;for(const input of guideHarnessPaths.querySelectorAll('input'))input.disabled=MEMORY.busy;workbuddyNow.hidden=remoteHost||!isAgent||!(cfg.workbuddy_setup&&cfg.workbuddy_setup.supported)||c.revoked||!c.enabled;openTarget.hidden=c.library_id===S.libraryId;
 verify.textContent=isAgent?'检查工具、绑定与记录':'检查是否收到对话';
 by('connectionConfigNote').textContent=isAgent?'查询、写入、窗口绑定和宿主上报分别核对。WorkBuddy 桌面 Hook 支持尚未确认；保存或回读配置文件不会被当作自动存档安装成功。':isAPI?'这是可选的模型请求转发入口；直接连接记忆服务不需要这一项。':'安装后重载 Harness 插件，再完成目标窗口的一轮真实对话。';
 if(c.revoked)guideNotice.textContent='连接已断开，旧配置不再可用；已有记忆保留。';
 else if(c.enabled===false)guideNotice.textContent='连接已暂停，新对话暂不保存。';
 else if(!isAPI&&!isAgent&&cfg.supported===false)guideNotice.textContent='尚未检测到受支持的 Harness。可在下方指定安装位置，再点击安装重试；程序会重新检查版本。';
 else if(isAgent)guideNotice.textContent=agentConnectionAdvice(c);
 else if(!guideNotice.textContent)guideNotice.textContent=saved?'已收到真实对话。':'请在目标窗口完成一轮对话，再核对记录。';
 const legacy=(cfg.setup&&cfg.setup.detected&&cfg.setup.detected.legacy_manual_entries)||(MEMORY.detect&&MEMORY.detect.legacy_manual_entries)||[];if(!isAPI&&!isAgent&&legacy.some(x=>!MEMORY.libraries.some(l=>l.id===(x.target_library_id||'default'))))guideNotice.textContent+=' 旧全局 MCP 工具仍指向已移除存档，不会自动改绑。';
 sync();
}
const oldShow=showConnectionConfig;showConnectionConfig=function(result){if((result&&result.mode)==='registered_source'){if((result.connection&&result.connection.library_id)!==S.libraryId){toast('这是另一份存档的活动来源；请先打开它的记忆库，再查看来源配置。');return;}if(window.LoveHouseSources)window.LoveHouseSources.openForConnection(result.connection.id);return;}oldShow(result);clearWorkBuddyPlan();const paths=result.host_options||(result.auto_capture&&result.auto_capture.harness&&result.auto_capture.harness.detected)||(result.setup&&result.setup.detected)||{};by('guideHarnessAppPath').value=paths.app_path||'';by('guideHarnessProfilePath').value=paths.profile_dir||'';guideNotice.textContent='';refreshGuide();configAdvanced.open=false;agentPreview.open=false;requestAnimationFrame(()=>configPanel.scrollIntoView({block:'start',behavior:'smooth'}));};
const oldButtons=updateMemoryButtons;updateMemoryButtons=function(){oldButtons();sync();};
function action(text,handler,description){const b=make('button','btn',text);b.type='button';if(description)b.setAttribute('data-hint-description',description);b.onclick=handler;return b;}
function registeredSource(c){
 const r=c&&c.registered_source;
 return c&&c.host==='agent'&&r&&typeof r.id==='string'&&r.id.trim()&&r.id.length>0&&r.id.length<=200&&r.library_id===c.library_id&&typeof c.library_id==='string'&&['astrbot','sdk'].includes(r.adapter)&&typeof r.runtime_agent_id==='string'&&r.runtime_agent_id.trim()&&r.runtime_agent_id.length<=200?r:null;
}
function windowScopeCaption(c){
 if(registeredSource(c))return '记录范围：由运行程序里已登记的来源决定';
 if(c.registered_source)return '记录范围：来源身份待核验';
 const policy=connectionPolicy(c),bound=boundSession(c);
 if(policy==='any')return '记录范围：整个连接，可能包含多个窗口';
 if(bound)return '记录范围：仅固定窗口 · '+bound.slice(-8);
 return policy==='fixed'?'记录范围：固定窗口 · 等待来源核对':'记录范围：等待目标窗口首次真实来源上报，然后固定';
}
function connectionCaption(c){
 const source=registeredSource(c);if(source)return source.adapter==='astrbot'?'AstrBot 活动来源':'执行器活动来源';
 if(c.registered_source)return '活动来源（身份待核验）';
 return c.host==='harness'?'Harness 窗口':c.host==='agent'?'通用 Agent 记忆':'高级模型转发';
}
function connectionGuideCaption(c){
 const source=registeredSource(c);
 if(source)return ['automatic_connected','outputs_only','observations_only'].includes(c.archive_status)?'查看来源配置':source.adapter==='astrbot'?'配置 AstrBot 插件':'配置执行器连接器';
 if(c.registered_source)return '刷新连接信息';
 return c.host==='agent'?(c.host_online?'查看记忆配置':'继续连接 Agent'):c.archive_status==='automatic_connected'?'查看接入信息':'继续连接';
}
function connectionState(c){
 if(!c.enabled)return '已暂停';
 if(c.registered_source&&!registeredSource(c))return '来源身份待核验';
 if(c.archive_status==='outputs_only')return '已收到输出';if(c.archive_status==='archive_failed')return '存档失败';
 if(registeredSource(c)){if(c.archive_status==='automatic_connected')return '已收到自动记录';if(c.archive_status==='observations_only')return '已收到观察';return c.host_online?'运行程序在线 · 等待输出':'等待运行程序报送';}
 if(c.archive_status==='observations_only')return '工具观察已保存 · 等待完整对话';
 if(c.host==='agent'){if(savedDialogue(c))return '已收到宿主记录';if(c.can_read===true&&c.can_write===false&&c.binding_state==='awaiting_source_turn')return '可查询 · 写入等待来源绑定';return c.host_online?'记忆工具已连接':c.archive_status==='tools_only'?'已配置 · 等待 Agent 上线':'等待 Agent 加载配置';}
 return c.archive_status==='automatic_connected'?'已收到对话':c.host==='harness'&&c.host_online?'插件在线 · 等待对话':c.configured_at?'等待窗口发消息':'尚未完成连接';
}
renderConnections=function(){
 const current=MEMORY.connections.filter(c=>c.library_id===S.libraryId&&!c.revoked),others=MEMORY.connections.filter(c=>c.library_id!==S.libraryId&&!c.revoked),states=current.filter(c=>c.enabled).map(c=>c.archive_status);
 by('connectionSummary').textContent=states.includes('archive_failed')?'有记录未存档':current.some(c=>c.registered_source&&!registeredSource(c))?'有来源身份待核验':states.includes('host_reported')?'已收到宿主记录 · 持续上报由宿主决定':states.includes('automatic_connected')?'这个记忆库已收到对话':states.includes('outputs_only')?'这个记忆库已收到独立输出':current.some(c=>c.enabled&&registeredSource(c)&&c.host_online)?'运行程序在线 · 等待实际输出':current.some(c=>c.enabled&&c.host==='agent'&&!registeredSource(c)&&!c.registered_source&&c.host_online)?'记忆工具已连接 · 自动存档待验证':current.length?(current.every(c=>!c.enabled)?'这个记忆库的连接已暂停':current.some(c=>registeredSource(c))?'等待运行程序报送实际输出':current.every(c=>c.host==='agent')?'等待 Agent 加载记忆配置':'还有一步，完成窗口连接'):'还没有 Agent 连接到这个记忆库';
 target.replaceChildren(make('strong','',`当前保存位置：${libraryName(S.libraryId)}`),make('p','',current.length?'下面的连接只读写这个记忆库。':'选择连接方式，把指定 Agent 的记忆保存在这里。'));
 const key=JSON.stringify([S.libraryId,MEMORY.connections,MEMORY.libraries.map(l=>[l.id,l.name])]);const box=by('connectionsList');
 if(key!==renderKey){const expanded=(box.querySelector('details')||{}).open;renderKey=key;box.replaceChildren();
  function card(c){const card=make('div','connection-card'),row=make('div','connection-row');row.append(make('strong','',c.name),make('span','connection-state',connectionState(c)));card.append(row,make('p','connection-target',`${connectionCaption(c)} → ${libraryName(c.library_id)}`),make('small','',windowScopeCaption(c)));if(c.capture){card.append(make('small','',`完整对话 ${num(c.capture.complete_dialogues_saved)} 轮 · 独立输出 ${num(c.capture.outputs_saved||0)} 条 · 观察 ${num(c.capture.tool_observations_saved)} 条`));if(c.capture.pending_records)card.append(make('small','',`${num(c.capture.pending_records)} 条正在进入索引`));if(!c.capture.complete_dialogues_saved&&c.capture.raw_events_only)card.append(make('small','', '中间消息已归档；整轮结束后组成可召回的对话，不需要整理模型。'));}if(c.last_received_at)card.append(make('small','',`最近接收 ${date(c.last_received_at)}`));if(c.error)card.append(make('p','form-note',trimText(c.error)));if(c.host==='agent'&&!c.registered_source){const capability=connectionCapabilities(c);if(capability)card.append(make('small','',capability));card.append(make('small','',hookReceiptCaption(c)));if((c.capture&&c.capture.last_hook_at))card.append(make('small','',`最近宿主回调 ${date(c.capture.last_hook_at)}`));}const buttons=make('div','connect-card-actions');const guide=action(connectionGuideCaption(c),()=>loadConnectionConfig(c.id),registeredSource(c)?'查看运行程序的来源配置，并核对已登记的接收范围。':'查看这条连接还差哪一步，并完成窗口接入。');guide.dataset.connectionAction='config';buttons.append(guide);if(c.library_id!==S.libraryId){const open=action('打开它的记忆库',()=>selectMemoryLibrary(c.library_id),'只切换浏览位置，不改变这条连接保存到哪里。');open.dataset.connectionAction='config';buttons.append(open);}const more=make('details','');more.append(make('summary','','管理连接'));const moreButtons=make('div','connect-card-actions');if(c.host==='api'){const edit=action('模型与密钥',()=>openProviderEditor(c));edit.dataset.connectionAction='provider';moreButtons.append(edit);}if(c.host==='agent'&&!c.registered_source&&(boundSession(c)||connectionPolicy(c)==='fixed')){const rebind=action('重新绑定窗口',()=>rebindConnection(c),'保留记忆，旧窗口和旧配置失效后，换发新配置给目标窗口。');rebind.dataset.connectionAction='rebind';moreButtons.append(rebind);}const pause=action(c.enabled?'暂停接收':'恢复接收',()=>setConnectionEnabled(c));pause.dataset.connectionAction='pause';const disconnect=action('断开连接',()=>openDisconnect(c));disconnect.dataset.connectionAction='disconnect';moreButtons.append(pause,disconnect);more.append(moreButtons);card.append(buttons,more);return card;}
  current.forEach(c=>box.append(card(c)));if(!current.length)box.append(make('p','empty','选择连接方式，为你的 Agent 接上这个记忆库。'));if(others.length){const details=make('details','connect-other');details.open=!!expanded;details.append(make('summary','',`其他记忆库的连接 · ${others.length}`));const list=make('div','connections-list');others.forEach(c=>list.append(card(c)));details.append(list);box.append(details);}
 }
 refreshGuide();updateMemoryButtons();
};
harnessNow.onclick=async()=>{if(!canManageMemory()||MEMORY.busy||!MEMORY.config)return;const id=MEMORY.config.connection.id;MEMORY.busy=true;guideNotice.textContent='正在备份并连接 Harness…';updateWriteState();try{await applyHarness(id);const cfg=await api('connections/'+encodeURIComponent(id)+'/config',undefined,{scope:false});showConnectionConfig(cfg);await refreshConnections();guideNotice.textContent='配置已保存。请在 Harness 重载插件或重启一次，再到目标窗口发消息。';}catch(e){guideNotice.textContent='尚未连接：'+e.message;}finally{MEMORY.busy=false;updateWriteState();}};
verify.onclick=async()=>{
 const id=(MEMORY.config&&MEMORY.config.connection&&MEMORY.config.connection.id),version=MEMORY.configVersion,epoch=S.libraryEpoch;if(!id||MEMORY.busy)return;
 await refreshConnections();if(version!==MEMORY.configVersion||epoch!==S.libraryEpoch||(MEMORY.config&&MEMORY.config.connection&&MEMORY.config.connection.id)!==id)return;
 const cfg=MEMORY.config,c=cfg.connection;
 if(c.revoked){guideNotice.textContent='连接已断开，请新建连接。';return;}
 if(!c.enabled){guideNotice.textContent='连接已暂停，请先在管理连接中恢复接收。';return;}
 if(c.host==='agent')guideNotice.textContent=agentConnectionAdvice(c);
 else guideNotice.textContent=c.archive_status==='automatic_connected'?'已收到完整对话，记忆正在保存到“'+libraryName(c.library_id)+'”。':'还没收到完整对话。请回聊天窗口发消息并等 AI 回复；这里不会主动调用付费模型。';
};
openTarget.onclick=()=>{const id=(MEMORY.config&&MEMORY.config.connection&&MEMORY.config.connection.library_id);if(id)selectMemoryLibrary(id);};
by('emptyAction').onclick=()=>{if(S.mode==='error'){location.reload();return;}if(S.nodes.length){resetFilters();return;}if(!canManageMemory()||MEMORY.busy||writeBusy||S.libraryChanging){toast(writeBlockedReason());return;}setPanelOpen('aiPanel',true,{focus:false});memoryTab('connect');openWizard();};
window.LoveHouseConnect={open:openWizard};
renderConnections();
})();
