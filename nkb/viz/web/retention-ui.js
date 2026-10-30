/* Read and edit one archive's continuous memory rules. Viewing is not recalling. */
(()=>{
'use strict';
const by=id=>document.getElementById(id),panel=by('settings');
if(!panel||typeof S==='undefined'||typeof MEMORY==='undefined'||typeof api!=='function')return;
const make=(tag,cls,text)=>el(tag,cls,text);
const state={owner:null,version:0,data:null,loading:false,busy:false,dirty:false};
const owner=()=>({id:S.libraryId,epoch:S.libraryEpoch});
const current=o=>o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch;
const idle=()=>S.mode==='serve'&&!S.libraryChanging&&!MEMORY.busy&&!writeBusy;
const readonly=()=>S.isDemo||state.data?.is_demo===true;
function button(id,text,hint,action){const b=make('button','btn',text);b.type='button';b.id=id;b.dataset.hintDescription=hint;b.onclick=action;return b;}
const entry=button('memoryRetentionBtn','记忆规律','查看本库怎样持续存档、随时间淡化，并根据有效回忆巩固；不会调用模型。',open);
entry.setAttribute('aria-haspopup','dialog');entry.setAttribute('aria-controls','memoryRetentionDialog');entry.setAttribute('aria-expanded','false');
const maintenance=by('organizeBtn');if(maintenance)maintenance.before(entry);else panel.append(entry);
const dialog=make('dialog','retention-dialog');dialog.id='memoryRetentionDialog';dialog.setAttribute('aria-labelledby','memoryRetentionTitle');
const title=make('h2','','记忆规律');title.id='memoryRetentionTitle';
const close=button('closeMemoryRetention','×','关闭记忆规律；未保存的调整不会应用。',closeDialog);close.className='icon-btn';close.setAttribute('aria-label','关闭记忆规律');
const head=make('div','dialog-title');head.append(title,close);
const identity=make('p','retention-identity');identity.id='memoryRetentionLibrary';
const promise=make('div','retention-principles'),promiseTitle=make('strong','','持续存档'),promiseText=make('p','','不按条数挤掉旧记录，也没有统一到期日。时间和有效回忆共同决定淡化。');promise.append(promiseTitle,promiseText);
const statistics=make('p','retention-statistics');statistics.id='memoryRetentionCounts';
const paceLabel=make('label','','淡化节奏'),pace=make('select');paceLabel.htmlFor='memoryForgettingPace';pace.id='memoryForgettingPace';pace.setAttribute('aria-describedby','memoryForgettingPaceHelp');
for(const [value,text]of [['gentle','平缓'],['balanced','均衡'],['fast','较快']]){const option=make('option','',text);option.value=value;pace.append(option);}
const paceHelp=make('p','form-note','调整淡化的倾向；记录不会因此自动删除。');paceHelp.id='memoryForgettingPaceHelp';
const usageLabel=make('label','retention-usage'),usage=make('input');usage.id='memoryUsageReinforcement';usage.type='checkbox';usageLabel.append(usage,document.createTextNode('有效使用时巩固记忆'));
const usageState=make('p','form-note');usageState.id='memoryRetentionUsage';
const details=make('details'),summary=make('summary','','了解存档与淡化'),explain=make('div','retention-explanation');
explain.append(make('p','','打开、导出或预览资料，不会被算作你再次提及它。真实连接取回资料产生的使用痕迹，会随下次对话入库或本库维护保存时巩固。'),make('p','','同一记忆的有效使用按 24 小时去重，防止反复读取把它刷成永久热门；这不是存放期限。'),make('p','','整理按已启用模型的批次与预算继续处理；排队不会挤掉原始记录。此处只调整记忆规律，不调用模型。'));details.append(summary,explain);
const status=make('p','retention-status');status.id='memoryRetentionStatus';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
const actions=make('div','dialog-actions'),reload=button('reloadMemoryRetention','重新读取','读取本库已保存的规律，替换当前未保存的调整。',refresh),cancel=button('cancelMemoryRetention','关闭','关闭记忆规律，不应用未保存的调整。',closeDialog),save=button('saveMemoryRetention','保存规律','仅保存当前存档的淡化节奏和有效使用开关，不改其他存档、不调用模型。',saveSettings);save.classList.add('primary');actions.append(reload,cancel,save);
dialog.append(head,identity,promise,statistics,paceLabel,pace,paceHelp,usageLabel,usageState,details,status,actions);document.body.append(dialog);
const style=make('style');style.textContent='.retention-dialog{width:min(540px,calc(100vw - 30px));max-height:calc(100vh - 40px);overflow:auto}.retention-dialog p{line-height:1.8}.retention-identity{font-size:12px;color:var(--muted);overflow-wrap:anywhere;margin:8px 0 14px}.retention-principles{padding:13px 15px;border:1px solid var(--line);background:var(--soft)}.retention-principles strong{font-size:14px}.retention-principles p{margin:6px 0 0;font-size:12px}.retention-statistics{font-size:12px;color:var(--muted);margin:13px 0}.retention-dialog .retention-usage{display:flex;gap:10px;align-items:center;margin:18px 0 5px;font-size:13px}.retention-usage input{width:auto;flex:0 0 auto}.retention-dialog details{margin:17px 0;font-size:12px}.retention-dialog summary{cursor:pointer;color:var(--accent)}.retention-explanation p{font-size:12px;color:var(--muted);margin:9px 0}.retention-status{font-size:12px;min-height:20px;overflow-wrap:anywhere}.retention-status[data-error=true]{color:var(--danger)}.retention-dialog .dialog-actions{gap:8px;flex-wrap:wrap}.retention-dialog .dialog-actions .btn{flex:1 1 auto}';document.head.append(style);
function validSettings(data){return data&&data.settings?.mode==='adaptive'&&(data.is_demo===true||S.isDemo||data.count_eviction===false&&data.automatic_deletion===false&&data.node_limit===null)&&['gentle','balanced','fast'].includes(data.settings.forgetting_pace)&&typeof data.settings.usage_reinforcement==='boolean';}
function notice(text,error=false){status.textContent=text;status.dataset.error=String(error);}
function count(value){return Number.isFinite(Number(value))?Math.max(0,Math.floor(Number(value))):0;}
function storageSize(value){const bytes=count(value);if(bytes>=1048576)return (bytes/1048576).toFixed(1)+' MiB';if(bytes>=1024)return (bytes/1024).toFixed(1)+' KiB';return bytes+' B';}
function controls(){entry.disabled=!idle()||state.busy;const writable=idle()&&!state.loading&&!state.busy&&current(state.owner)&&validSettings(state.data)&&!readonly();pace.disabled=usage.disabled=!writable;save.disabled=!writable||!state.dirty;reload.disabled=state.loading||state.busy||!current(state.owner);close.disabled=cancel.disabled=state.busy;save.textContent=state.busy?'保存中…':'保存规律';}
function render(data){if(!validSettings(data))throw new Error('当前服务未提供完整的连续记忆规律，请更新或稍后重试。');state.data=data;state.dirty=false;promiseTitle.textContent=readonly()?'独立示例':'持续存档';promiseText.textContent=readonly()?'个人存档采用持续归档；当前是独立示例，只读展示。':'不按条数挤掉旧记录，也没有统一到期日。时间和有效回忆共同决定淡化。';pace.value=data.settings.forgetting_pace;usage.checked=data.settings.usage_reinforcement;const states=data.states||{};statistics.textContent=`共 ${count(data.node_count)} 条记录 · 清晰 ${count(states.active)} · 淡化 ${count(states.fading)} · 休眠 ${count(states.dormant)}`+(count(states.forgotten)?` · 暂不可用 ${count(states.forgotten)}`:'')+(data.storage&&Number.isFinite(data.storage.bytes)?` · ${storageSize(data.storage.bytes)}`:'');const pending=count(data.usage?.pending);usageState.textContent=data.usage?.available===false?'使用痕迹暂不可读取，原文保存不受影响。':pending?`${pending} 条使用痕迹待下次对话入库或本库维护保存时巩固。`:'没有待巩固的使用痕迹。';identity.textContent=`${libraryName(state.owner.id)}${readonly()?' · 示例，只读':''}`;notice(readonly()?'示例仅供查看；个人存档可单独调整规律。':'已读取本库规律。淡化只改变记忆的显著程度。');controls();}
async function refresh(){if(!current(state.owner)||state.busy)return;const o=state.owner,v=++state.version;state.loading=true;state.data=null;state.dirty=false;notice('正在读取本库记忆规律…');controls();try{const data=await api('retention',undefined,{libraryId:o.id});if(!current(o)||v!==state.version||!dialog.open)return;render(data);}catch(e){if(current(o)&&v===state.version&&dialog.open)notice('暂时无法读取：'+e.message,true);}finally{if(v===state.version){state.loading=false;controls();}}}
function open(){if(!idle()||state.busy)return;state.owner=owner();state.data=null;state.dirty=false;state.version++;identity.textContent=libraryName(state.owner.id);statistics.textContent='';usageState.textContent='';entry.setAttribute('aria-expanded','true');dialog.showModal();refresh();}
function closeDialog(){if(state.busy)return;state.version++;state.loading=false;state.data=null;state.dirty=false;dialog.close();entry.setAttribute('aria-expanded','false');controls();entry.focus();}
function changed(){if(readonly()||state.busy||state.loading)return;state.dirty=true;notice('调整尚未保存，只会应用到这个存档。');controls();}
pace.onchange=usage.onchange=changed;
async function saveSettings(){if(save.disabled||!idle()||!current(state.owner)||readonly()||!state.dirty||!validSettings(state.data))return;const o=state.owner,v=++state.version,body={forgetting_pace:pace.value,usage_reinforcement:usage.checked};if(!['gentle','balanced','fast'].includes(body.forgetting_pace))return;state.busy=true;MEMORY.busy=true;writeBusy=true;if(typeof invalidateRecall==='function')invalidateRecall();if(typeof updateWriteState==='function')updateWriteState();notice('正在保存本库规律…');controls();try{const data=await api('retention/settings',body,{libraryId:o.id});if(!current(o)||v!==state.version||!dialog.open)return;render(data);notice('已保存。本库持续存档；调整不会自动删除旧记录。');if(typeof toast==='function')toast('记忆规律已保存。');}catch(e){if(current(o)&&v===state.version&&dialog.open)notice('未能确认保存结果：'+e.message+'。请重试，或重新读取已保存的规律。',true);}finally{state.busy=false;MEMORY.busy=false;writeBusy=false;if(typeof updateWriteState==='function')updateWriteState();controls();}}
dialog.addEventListener('cancel',event=>{if(state.busy)event.preventDefault();else{state.version++;state.loading=false;state.data=null;state.dirty=false;entry.setAttribute('aria-expanded','false');}});
const previous=updateMemoryButtons;updateMemoryButtons=function(...args){previous(...args);if(dialog.open&&state.owner&&!current(state.owner)){state.version++;state.loading=false;state.data=null;state.dirty=false;dialog.close();entry.setAttribute('aria-expanded','false');}controls();};
window.LoveHouseRetention={open,refresh};controls();
})();
