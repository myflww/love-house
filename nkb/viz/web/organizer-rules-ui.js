/* Read the exact versioned guide automatically attached to organizer requests. */
(()=>{
'use strict';
const by=id=>document.getElementById(id);if(typeof S==='undefined'||!by('previewOrganizer'))return;
const make=(tag,cls,text)=>el(tag,cls,text);
let owner=null,serial=0;
const current=o=>o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch;
const button=make('button','btn','整理准则');button.id='organizerRulesBtn';button.type='button';button.dataset.hintDescription='查看整理模型每批会收到的规则与程序限制，不调用模型、不发送记忆。';by('previewOrganizer').parentElement.append(button);
const d=make('dialog','portability-dialog');d.id='organizerRulesDialog';d.setAttribute('aria-labelledby','organizerRulesTitle');
const head=make('div','dialog-title'),title=make('h2','','AI 整理准则'),close=make('button','icon-btn','×');title.id='organizerRulesTitle';close.type='button';close.setAttribute('aria-label','关闭整理准则');close.dataset.hintDescription='关闭规则说明，不改变任何整理设置。';head.append(title,close);
const note=make('p','form-note','启用你配置的整理模型后，每批请求都会附加这些规则。模型提出整理结果，程序继续校验来源、权限与结构。查看此页不会调用模型。');
const status=make('p','portability-notice');status.id='organizerRulesStatus';status.setAttribute('role','status');
const summary=make('ul');summary.id='organizerRulesSummary';summary.style.cssText='font-size:13px;line-height:1.9;padding-left:21px';
const detail=make('details'),label=make('summary','','查看完整模型引导'),guide=make('pre','detail-json');guide.id='organizerFullGuide';guide.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.8;max-height:300px;overflow:auto';detail.append(label,guide);d.append(head,note,status,summary,detail);document.body.append(d);
async function open(){if(S.mode!=='serve'||S.libraryChanging)return;owner={id:S.libraryId,epoch:S.libraryEpoch};const o=owner,v=++serial;guide.textContent='';summary.replaceChildren();status.textContent='正在读取本库存档的整理规则…';detail.open=false;d.showModal();try{const result=await api('organizer/rules',undefined,{libraryId:o.id});if(!current(o)||v!==serial||!d.open)return;if(result.read_only!==true||result.will_call_model!==false||typeof result.guidance!=='string')throw new Error('无法确认规则为只读展示');status.textContent=`${libraryName(o.id)} · 规则 ${result.version||'当前版本'} · 原文保留，模型没有删除权限`;for(const item of result.summary||[]){if(typeof item==='string')summary.append(make('li','',item));}guide.textContent=result.guidance;}catch(e){if(current(o)&&v===serial&&d.open)status.textContent='规则暂时无法读取：'+e.message;}}
function dismiss(){serial++;guide.textContent='';summary.replaceChildren();d.close();}
button.onclick=open;close.onclick=dismiss;d.addEventListener('cancel',()=>{serial++;guide.textContent='';summary.replaceChildren();});
const previous=updateMemoryButtons;updateMemoryButtons=function(...args){previous(...args);button.disabled=S.mode!=='serve'||S.libraryChanging;if(d.open&&!current(owner))dismiss();};
window.LoveHouseOrganizerRules={open};
})();
