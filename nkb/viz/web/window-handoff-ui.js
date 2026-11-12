/* A deliberate copy of one bounded archive excerpt. It never configures a host. */
(()=>{
'use strict';
if(typeof MEMORY==='undefined'||!document.getElementById('libraryPanel'))return;
const make=(tag,cls,text)=>el(tag,cls,text),by=id=>document.getElementById(id);
let owner=null,serial=0,result=null,busy=false;
const current=o=>o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch;
const available=()=>S.mode==='serve'&&!S.isDemo&&!S.libraryChanging&&!MEMORY.busy&&!writeBusy;
const entry=make('button','btn','复制新窗口记忆包');entry.id='windowHandoffBtn';entry.type='button';entry.dataset.hintDescription='选择小、中、大三档，预览后复制当前存档的记忆资料。粘贴不会自动连接或记录对话。';
by('inheritLibraryBtn').after(entry);
const d=make('dialog','portability-dialog');d.id='windowHandoffDialog';
const head=make('div','dialog-title'),title=make('h2','','给新窗口的记忆包'),close=make('button','icon-btn','×');close.type='button';close.setAttribute('aria-label','关闭记忆包');close.dataset.hintDescription='关闭预览，不改变当前存档。';head.append(title,close);
const note=make('p','form-note','选择大小后生成资料。完整原句、说话者和证据状态会保留；不会调用模型。新窗口持续自动存档仍需要连接本库。');
const sizes=make('div','portability-actions');sizes.setAttribute('role','group');sizes.setAttribute('aria-label','记忆包大小');
let selected='M';const buttons=[];for(const [size,label] of [['S','小 · 4千字'],['M','中 · 1.2万字'],['L','大 · 2.8万字']]){const b=make('button','btn',label);b.type='button';b.dataset.hintDescription='最多'+label.split(' · ')[1]+'符；整条资料放不下时会跳过，并标明未包含的数量。';b.onclick=()=>{selected=size;refresh();};buttons.push([size,b]);sizes.append(b);}
const status=make('p','portability-notice');status.id='windowHandoffStatus';status.setAttribute('role','status');
const text=make('textarea');text.id='windowHandoffText';text.readOnly=true;text.rows=12;text.setAttribute('aria-label','当前存档记忆包预览');text.style.cssText='width:100%;resize:vertical;max-height:45vh;font:12px/1.8 ui-monospace,monospace;white-space:pre-wrap;';
const consentLabel=make('label','inline-check'),consent=make('input');consent.type='checkbox';consent.id='windowHandoffConsent';consentLabel.append(consent,document.createTextNode('我已查看内容，愿意把这份个人记忆资料粘贴给目标窗口。'));
const actions=make('div','portability-actions'),copy=make('button','btn primary','复制记忆包'),connect=make('button','btn','连接新窗口');copy.type=connect.type='button';copy.id='copyWindowHandoff';copy.dataset.hintDescription='复制已经预览的摘录，不会自动建立记忆连接。';connect.dataset.hintDescription='打开连接向导，持续读取和记录这个存档。';actions.append(copy,connect);d.append(head,note,sizes,status,text,consentLabel,actions);document.body.append(d);
function controls(){entry.disabled=!available();copy.disabled=busy||!current(owner)||!result||!consent.checked;connect.disabled=busy||!current(owner);for(const [size,b]of buttons){b.setAttribute('aria-pressed',String(size===selected));b.classList.toggle('primary',size===selected);}}
async function refresh(){const o=owner,v=++serial;result=null;consent.checked=false;text.value='';busy=true;status.textContent='正在生成当前存档的只读摘录…';controls();try{const data=await api('memory/handoff',{profile:selected},{libraryId:o.id});if(!current(o)||v!==serial||!d.open)return;result=data;text.value=data.text;status.textContent=`${data.identity.library_name} · ${data.included_memories}/${data.total_memories} 条 · ${data.chars} 字符。`+(data.all_memory_loaded?'本次可用内容均已包含。':'这是一份摘录，其余记忆可在连接后按目录读取。');if(Object.values(data.redactions||{}).some(Number))status.textContent+=' 已隐藏可识别密钥或本机路径，请继续检查。';}catch(e){if(current(o)&&v===serial)status.textContent='生成未完成：'+e.message;}finally{if(v===serial){busy=false;controls();}}}
entry.onclick=()=>{if(!available())return;owner={id:S.libraryId,epoch:S.libraryEpoch};d.showModal();refresh();};
close.onclick=()=>{serial++;busy=false;result=null;text.value='';d.close();};d.addEventListener('cancel',()=>{serial++;busy=false;result=null;text.value='';});
consent.onchange=controls;
copy.onclick=async()=>{if(copy.disabled||!result||!current(owner))return;const o=owner,v=serial,sourceText=result.text;const stillApproved=()=>current(o)&&serial===v&&d.open&&consent.checked&&result?.text===sourceText;try{await navigator.clipboard.writeText(sourceText);if(stillApproved())toast('记忆资料已复制；持续存档请连接这个库。');}catch{if(!stillApproved())return;text.value=sourceText;text.focus();text.select();if(document.execCommand('copy'))toast('记忆资料已复制。');else toast('已选中资料，请按 ⌘C 或 Ctrl+C 复制。');}};
connect.onclick=()=>{if(!current(owner))return;d.close();window.LoveHousePortability?.openInheritance();};
const previous=updateMemoryButtons;updateMemoryButtons=function(...args){previous(...args);if(d.open&&!current(owner)){serial++;busy=false;result=null;text.value='';d.close();}controls();};
window.LoveHouseHandoff={open:()=>entry.click()};controls();
})();
