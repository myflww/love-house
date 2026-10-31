/* A small, read-only guide: give configuration to the program that runs the fish. */
(()=>{
'use strict';
if(typeof S==='undefined'||!document.getElementById('connectionsPanel'))return;
const by=id=>document.getElementById(id),make=(tag,cls,text)=>el(tag,cls,text);
const routes={
 harness:{name:'DeepSeek Harness',recipient:'Harness 的连接器／插件设置',place:'使用专用连接向导。若由助手代装，把安装说明交给能修改 Harness 设置的后台配置助手。',proof:'插件加载后完成一轮真实对话；爱之屋出现“已收到自动记录”，才验证了这一条记录通路。',key:'连接记忆不需要模型厂商 Key。',limit:'旧的目标窗口范围保持。其他窗口或独立执行器需要明确登记。'},
 astrbot:{name:'AstrBot',recipient:'AstrBot 的爱之屋插件设置',place:'先导出并安装实验插件，再把来源配置文件路径填入插件。QQ 的 SnowLuma、NapCat 或官方接口仍由 AstrBot 配置。',proof:'插件已启用、目标来源已登记，实际产生一条输出后，再核对爱之屋的接收记录。',key:'记忆来源配置不是聊天模型 API Key。',limit:'QQ 官方接口／WebChat 已做首轮实测；SnowLuma、NapCat、云端及其他版本仍需对应验收。'},
 agent:{name:'其他程序（MCP）',recipient:'运行程序的工具连接设置（MCP）',place:'自己填写时使用“复制 MCP 配置”。让助手代装时使用“复制给配置助手”，交给能修改该程序设置的后台 Agent。',proof:'工具在线表示能查、写记忆；自动记录还要运行程序的输出采集连接器。请核对真实输出回执。',key:'生成记忆连接配置不需要厂商 Key。',limit:'只有聊天能力的 QQ 或网页窗口无法替你安装。单独复制文字不等于程序已经加载配置。'},
 key:{name:'整理模型 Key',recipient:'爱之屋自己的“记忆整理”设置',place:'填写你选定的整理模型地址、名称和 Key，再按预算启用。聊天模型继续使用原程序已有设置。',proof:'“整理批次完成”只表示资料已处理；候选需要核对，只有实际生成的可用记忆才能进入整理记忆召回。',key:'这份 Key 只让爱之屋整理已收到的资料。',limit:'它不会自动连接 QQ、Harness 或收集其他软件。'}
};
const state={owner:null,route:'harness',returnId:null};
const owner=()=>({id:S.libraryId,epoch:S.libraryEpoch}),current=o=>!!o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch;
const d=make('dialog','portability-dialog connection-help-dialog');d.id='connectionHelpDialog';d.setAttribute('aria-labelledby','connectionHelpTitle');
const head=make('div','dialog-title'),title=make('h2','','配置应该交给谁？'),close=make('button','icon-btn','×');title.id='connectionHelpTitle';close.id='closeConnectionHelp';close.type='button';close.setAttribute('aria-label','关闭连接说明');head.append(title,close);
const identity=make('p','portability-identity');identity.id='connectionHelpIdentity';
const lead=make('p','form-note','选择实际运行大肥鱼的程序，再按它的设置入口连接。');
const tabs=make('div','connection-help-tabs');tabs.setAttribute('aria-label','选择说明');const choices={};
const body=make('section');body.id='connectionHelpBody';body.setAttribute('aria-live','polite');
function show(route){state.route=routes[route]?route:'harness';const r=routes[state.route];for(const [key,b]of Object.entries(choices))b.setAttribute('aria-pressed',String(key===state.route));body.replaceChildren();for(const [label,text]of [['交给谁',r.recipient],['填在哪里',r.place],['怎样验证',r.proof]]){const row=make('div','connection-help-row');row.append(make('strong','',label),make('p','',text));body.append(row);}body.append(make('p','connection-help-key',r.key));const more=make('details');more.append(make('summary','','适用范围'),make('p','form-note',r.limit));body.append(more);}
for(const [route,r]of Object.entries(routes)){const b=make('button','btn',r.name);b.type='button';b.id='connectionHelpRoute-'+route;b.onclick=()=>show(route);choices[route]=b;tabs.append(b);}
const scope=make('details','connection-help-scope');scope.id='connectionHelpDeployment';scope.append(make('summary','','本机与云服务器怎么区分？'),make('p','form-note','配置文件路径只属于生成它的那台机器。鱼运行在云服务器或容器中时，应在对应服务器部署爱之屋服务、生成配置，并让运行程序能访问该文件与服务；Mac 本机路径和 127.0.0.1 不能原样搬过去。'));
const legend=make('details','connection-help-scope');legend.id='connectionHelpStages';legend.append(make('summary','','连接、保存、整理和召回有什么区别？'));for(const text of ['配置就绪：文件或代码已生成，等待运行程序加载。','收到输出：某条实际资料已经进入当前存档。','整理完成：资料已处理；仍可能是候选，不等于每条都形成了记忆。','最近返回资料：只说明传回了哪些整理记忆或原始资料，不证明模型已经采用，也不是全库目录。'])legend.append(make('p','form-note',text));
const privacy=make('p','form-note','配置包含对应存档的访问权限，只交给你选定的运行程序，不公开转发。');
d.append(head,identity,lead,tabs,body,scope,legend,privacy);document.body.append(d);
function dismiss(restore=true){const id=state.returnId,o=state.owner;d.close();identity.textContent='';state.owner=null;state.returnId=null;scope.open=false;legend.open=false;if(restore&&current(o)){const target=by(id);if(target&&!target.disabled)target.focus();}}
function open(route='harness',returnId=null){if(S.libraryChanging)return;state.owner=owner();state.returnId=returnId;identity.textContent=libraryName(S.libraryId)+' · 当前说明不改变连接';scope.open=false;legend.open=false;show(route);d.showModal();close.focus();}
close.onclick=()=>dismiss();d.addEventListener('cancel',event=>{event.preventDefault();dismiss();});
function entry(id,text,route,parent,before=null){if(!parent)return;const b=make('button','btn connection-help-entry',text);b.type='button';b.id=id;b.dataset.hintDescription='查看配置交给谁、填在哪里和真实接通标准；不调用模型或改变设置。';b.onclick=()=>open(route,id);if(before)parent.insertBefore(b,before);else parent.append(b);}
entry('showConnectionHelp','怎么连接？','harness',by('connectionsPanel'),by('newConnectionDetails'));
entry('connectionWizardHelp','配置交给谁？','harness',by('connectionWizardDialog')?.querySelector('.wizard-heading'),by('closeConnectionWizard'));
entry('agentSourcesHelp','AstrBot 配置填在哪里？','astrbot',by('agentSourcesDialog'),by('agentSourcesList'));
entry('organizerKeyHelp','整理 Key 做什么？','key',by('organizerPanel')?.querySelector('.ai-compose-actions'));
const css=make('style');css.textContent='.connection-help-dialog{width:min(620px,calc(100vw - 28px));max-height:calc(100vh - 40px);overflow:auto}.connection-help-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.connection-help-tabs button[aria-pressed=true]{background:var(--soft);border-color:var(--ink)}.connection-help-row{padding:10px 0;border-bottom:1px solid var(--line)}.connection-help-row strong{font-size:12px;color:var(--muted)}.connection-help-row p{font-size:13px;line-height:1.8;margin:6px 0}.connection-help-key{padding:10px;background:var(--soft);font-size:12px;line-height:1.7}.connection-help-scope{margin:15px 0}.connection-help-dialog summary{cursor:pointer;font-size:12px}.connection-help-entry{font-size:12px;margin:6px 0}.wizard-heading{flex-wrap:wrap}.wizard-heading .connection-help-entry{margin-left:auto}';document.head.append(css);
const previous=updateMemoryButtons;updateMemoryButtons=function(...args){previous(...args);if(d.open&&!current(state.owner))dismiss(false);};
window.LoveHouseConnectionHelp={open,dismiss};
})();
