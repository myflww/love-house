/* Scoped human controls for strict organization, sourced JSON context and recording aliases. */
(()=>{
'use strict';
if(typeof ORGANIZER==='undefined'||!document.getElementById('organizerPanel'))return;
const by=id=>document.getElementById(id),make=(tag,cls,text)=>el(tag,cls,text);
const UI={busy:false,machineBusy:false,version:0,owner:null,machineVersion:0,machineOwner:null,machineEpoch:null,machineJSON:'',duplicates:null};
const style=document.createElement('style');style.textContent=`
.memory-trigger-note{padding:12px;border:1px solid var(--line);background:var(--soft);margin:10px 0}.memory-trigger-note strong{display:block}.memory-trigger-note p{margin:5px 0 0;font-size:12px;line-height:1.7}.memory-more-actions{display:flex;flex-wrap:wrap;gap:7px;margin:10px 0}.memory-extra-dialog{width:min(720px,calc(100vw - 30px));max-height:calc(100vh - 40px);overflow:auto}.memory-extra-dialog .dialog-title{display:flex;align-items:center;justify-content:space-between;gap:12px}.memory-extra-dialog .dialog-title h2{font-size:20px}.memory-extra-dialog label{display:block;margin:12px 0 6px}.memory-extra-dialog input:not([type=checkbox]),.memory-extra-dialog select{width:100%}.memory-extra-dialog .inline-check{display:flex;align-items:flex-start;gap:8px}.memory-extra-dialog .inline-check input{width:auto;flex-shrink:0}.memory-extra-dialog .detail-json{max-height:340px;overflow:auto;white-space:pre-wrap}.memory-json-record,.duplicate-review-group{padding:13px;border:1px solid var(--line);margin:12px 0;background:var(--panel)}.memory-json-record h3,.duplicate-review-group h3{font-size:14px;color:var(--ink);letter-spacing:0}.memory-json-record p,.duplicate-review-group p{font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0}.duplicate-channel{font-size:12px;color:var(--muted)}.duplicate-review-group .source-rows{margin:10px 0}.duplicate-review-group .source-rows>div{padding:10px 0;border-bottom:1px solid var(--line)}.memory-extra-dialog .status-note{margin:10px 0;font-size:12px;color:var(--muted)}.memory-json-actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}`;
document.head.append(style);
function button(text,id,description){const b=make('button','btn',text);b.type='button';if(id)b.id=id;if(description)b.dataset.hintDescription=description;return b;}
function context(){return {id:S.libraryId,epoch:S.libraryEpoch};}
function current(c){return !!c&&c.id===S.libraryId&&c.epoch===S.libraryEpoch;}
function safeNotice(target,message,error=false){target.textContent=message;target.classList.toggle('error',error);}
const settings=by('organizerSettings'),cadence=by('organizerCadence'),batch=by('organizerBatchSize');
const thresholdLabel=make('label','','累计多少条后自动整理');thresholdLabel.htmlFor='organizerTriggerCount';
const threshold=make('input','');threshold.id='organizerTriggerCount';threshold.type='number';threshold.min='0';threshold.max='500';threshold.step='1';threshold.required=true;threshold.value='20';
const thresholdNote=make('p','form-note');thresholdNote.id='organizerTriggerHelp';threshold.setAttribute('aria-describedby',thresholdNote.id);
settings.insertBefore(thresholdLabel,batch.previousElementSibling);settings.insertBefore(threshold,batch.previousElementSibling);settings.insertBefore(thresholdNote,batch.previousElementSibling);
const execution=make('details',''),executionSummary=make('summary','','执行批次与用量预算');execution.append(executionSummary);
const batchLabel=settings.querySelector('label[for=organizerBatchSize]');batchLabel.textContent='每次调用最多处理几条';execution.append(batchLabel,batch);
const budget=by('organizerCallLimit').closest('.form-row');execution.append(budget,make('p','form-note','累计阈值决定何时开始；每批与字符预算决定如何分次处理。达到阈值后，会分批处理完本轮已经积累的原文。'));
settings.insertBefore(execution,by('saveOrganizerSettings'));
cadence.options[0].textContent='累计原文后整理';cadence.options[1].textContent='每轮完整对话后';
const triggerBox=make('div','memory-trigger-note');triggerBox.id='organizerTriggerState';triggerBox.setAttribute('role','status');by('organizerCounts').after(triggerBox);
const topNote=by('runOrganizer').closest('.ai-compose-actions').nextElementSibling;if(topNote?.classList.contains('form-note'))topNote.textContent='预览不会调用模型。明确有证据的内容可整理，冲突与人格变化先等你确认。';
function modeNote(){const n=Number(threshold.value),session=cadence.value==='session';thresholdLabel.hidden=threshold.hidden=session;thresholdNote.textContent=session?'每轮完整对话可触发一批；调用与字符预算照常限制。':n===0?'0 为旧兼容模式：不足一批时，等约30秒也可整理。填1–500即可严格等到N条。':`累计到 ${Number.isInteger(n)&&n>0?n:'N'} 条才自动开始，不会因为等待时间较长而提前调用模型。`;
 if(ORGANIZER.dirty)thresholdNote.textContent+=' 修改后请保存才生效。';}
function renderTrigger(data){const settings=data.settings||{},status=data.status||{},t=status.trigger||{};triggerBox.replaceChildren();let title,note;
 if(!settings.enabled){title='自动整理未启用';note='原始对话仍可保存。设置整理模型并保存启用后，才会按规则调用。';}
 else if(t.draining){title=`本轮正在整理 · 剩余 ${num(t.remaining)} 条`;note='这次已经达到触发条件，会在预算内分批继续；后来新到的记录等待下一轮。';}
 else if(t.mode==='strict'||settings.auto_trigger_count>0&&settings.cadence!=='session'){const n=num(t.threshold,settings.auto_trigger_count),pending=num(t.pending);title=pending>=n?`已达到 ${n} 条触发条件`:`再存 ${Math.max(0,n-pending)} 条后自动整理`;note=`当前待整理 ${pending} 条 · 累计阈值 ${n} 条。你也可以点击“立即整理”，不足阈值时主动处理。`;}
 else if(settings.cadence==='session'){title='每轮完整对话后整理';note='只使用已保存的完整记录，失败或中断原文不会冒充完整经历。';}
 else {title='旧兼容模式 · 按批次节奏';note='不足一批时等待约30秒也会处理；如需严格累计，请把触发数量改成1–500。';}
 if(num(status.calls_24h)>=num(settings.daily_call_limit,Infinity)||num(status.chars_24h)>=num(settings.daily_char_limit,Infinity))note+=' 当前预算已用完，后续会等预算恢复；原文仍保留。';
 triggerBox.append(make('strong','',title),make('p','',note));const aliases=num(status.counts?.done_alias);if(aliases)triggerBox.append(make('p','',`${aliases} 条已确认的重复来源没有再次送给模型，原文仍可查看。`));}
const originalRender=renderOrganizer;
renderOrganizer=function(data){originalRender(data);if(!ORGANIZER.dirty){const s=data.settings||{},fresh=!s.enabled&&!s.provider_id&&!s.model;threshold.value=String(fresh?20:num(s.auto_trigger_count));}modeNote();renderTrigger(data);updateControls();};
threshold.addEventListener('input',()=>{ORGANIZER.dirty=true;modeNote();});cadence.addEventListener('change',modeNote);
saveOrganizerSettings=async function(){
 if(!canWrite()||MEMORY.busy||UI.busy)return;const owner=context();const trigger=Number(threshold.value);
 if(!threshold.value.trim()||!Number.isInteger(trigger)||trigger<0||trigger>500){toast('累计阈值请填0–500的整数；0保留旧兼容节奏。',true);return;}
 const body={enabled:by('organizerEnabled').checked,provider_mode:by('organizerMode').value,connection_id:by('organizerConnection').value||null,
  cadence:cadence.value,auto_trigger_count:trigger,batch_size:num(batch.value),daily_call_limit:num(by('organizerCallLimit').value),daily_char_limit:num(by('organizerCharLimit').value)};
 if(!Number.isInteger(body.batch_size)||body.batch_size<1||body.batch_size>12||!Number.isInteger(body.daily_call_limit)||body.daily_call_limit<1||body.daily_call_limit>1000||!Number.isInteger(body.daily_char_limit)||body.daily_char_limit<3000||body.daily_char_limit>2000000){toast('每批1–12条，每日1–1000次，字符预算3000–2000000。',true);return;}
 if(body.provider_mode==='separate'){try{Object.assign(body,providerPayload('organizerProvider'));}catch(e){toast(e.message,true);return;}}
 else if(body.enabled&&!body.connection_id){toast('请选择当前库的模型连接，或设置独立整理模型。');return;}
 MEMORY.busy=true;writeBusy=true;updateWriteState();let acknowledged=false;
 try{const result=await api('organizer/settings',body);acknowledged=true;if(!current(owner))return;by('organizerProviderKey').value='';ORGANIZER.dirty=false;await refreshOrganizer();if(!current(owner))return;by('organizerNotice').textContent=result.warning||'';toast('整理设置已保存；只按当前规则和预算运行。');}
 catch(e){if(!e.staleLibrary)toast(acknowledged?'设置已保存，状态读取未确认；请刷新整理面板。':'保存未确认：'+e.message,true);}
 finally{MEMORY.busy=false;writeBusy=false;updateWriteState();}
};
by('saveOrganizerSettings').onclick=saveOrganizerSettings;
const originalPreview=showOrganizerPreview;showOrganizerPreview=function(data){originalPreview(data);const t=data.trigger;if(t){const text=t.mode==='strict'?`自动触发需累计 ${t.threshold} 条；当前 ${t.pending} 条${t.draining?'，本轮正在分批处理':t.eligible?'，已达条件':'，还没有到自动调用条件'}。点击立即整理可以主动处理。`:t.mode==='session'?'当前按完整轮次整理。':'当前为旧兼容批次节奏。';by('organizerPreviewContent').prepend(make('p','form-note',text));}if(data.aliased_count)by('organizerPreviewContent').prepend(make('p','form-note',`${data.aliased_count} 条确认重复的来源会保留，但不会再次送模型。`));};

const extras=make('div','memory-more-actions'),machineOpen=button('AI记忆格式预览','openMachineMemoryPreview','只读查看当前记忆库会怎样给AI提供JSON材料，不调用模型。'),duplicateOpen=button('重复来源审阅','openDuplicateRecordings','比较自动与手动存档的原文；明确同一轮后可折叠显示，原文不删除。');extras.append(machineOpen,duplicateOpen);by('organizerCounts').before(extras);
const settingsLinks=by('organizeBtn').parentElement;const duplicateLink=button('重复来源','duplicateRecordingSettingsBtn','检查同一轮对话的不同采集来源，不删除原文。');settingsLinks.append(duplicateLink);
function dialogShell(id,titleText,closeId){const dialog=make('dialog','memory-extra-dialog');dialog.id=id;const header=make('div','dialog-title'),title=make('h2','',titleText),close=button('×',closeId);title.id=id+'Title';dialog.setAttribute('aria-labelledby',title.id);close.className='icon-btn';close.setAttribute('aria-label','关闭'+titleText);header.append(title,close);dialog.append(header);document.body.append(dialog);return {dialog,close};}
const machine=dialogShell('machineMemoryPreviewDialog','AI记忆格式 · 只读预览','closeMachineMemoryPreview');
const machineIntro=make('p','form-note','这是带来源的机器JSON材料，不是模型权重或隐藏语言。人类界面仍保留中文原文；这里不会改写、删除记忆或调用模型。');
const queryLabel=make('label','','想预览什么话题？'),query=make('input','');query.id='machineMemoryQuery';query.maxLength=2000;query.placeholder='例如：我的饮品偏好、最近约定';queryLabel.htmlFor=query.id;
const machineRead=button('读取本次记忆材料','readMachineMemoryPreview','只在本地读取当前库，按话题和预算选择材料，不调用模型。'),machineStatus=make('p','status-note'),machineRecords=make('div',''),machineDetails=make('details',''),machinePre=make('pre','detail-json'),machineCopy=button('复制机器JSON','copyMachineMemoryJSON','复制本次有来源的JSON数据；不会复制模型API密钥。');
machinePre.tabIndex=0;machineDetails.append(make('summary','','查看完整机器JSON'),machinePre);machine.dialog.append(machineIntro,queryLabel,query,machineRead,machineStatus,machineRecords,machineDetails,machineCopy);
function clearMachine(){UI.machineVersion++;UI.machineBusy=false;UI.machineJSON='';machinePre.textContent='';machineRecords.replaceChildren();machineStatus.textContent='';machineCopy.disabled=true;}
function openMachine(){if(S.mode!=='serve'||S.libraryChanging)return;clearMachine();UI.machineOwner=S.libraryId;UI.machineEpoch=S.libraryEpoch;machine.dialog.querySelector('h2').textContent=`${libraryName(S.libraryId)} · AI记忆格式`;machine.dialog.showModal();query.focus();updateControls();}
machineOpen.onclick=openMachine;machine.close.onclick=()=>{machine.dialog.close();clearMachine();};machine.dialog.addEventListener('cancel',clearMachine);
machineRead.onclick=async()=>{if(S.mode!=='serve'||S.libraryChanging||UI.busy||UI.machineBusy)return;const owner=context(),version=++UI.machineVersion;UI.machineBusy=true;UI.machineOwner=owner.id;UI.machineEpoch=owner.epoch;UI.machineJSON='';machinePre.textContent='';machineRecords.replaceChildren();safeNotice(machineStatus,'读取当前库的材料…');updateControls();
 try{const result=await api('memory/context',{query:query.value.trim()||'重要记忆 偏好 约定'});if(!current(owner)||version!==UI.machineVersion||!machine.dialog.open)return;const packet=result.memory_context;
  if(result.read_only!==true||!packet||packet.schema!=='love-house-memory-context/v1'||!Array.isArray(packet.records))throw new Error('服务没有返回可验证的只读机器上下文');
  UI.machineJSON=JSON.stringify(packet,null,2);machinePre.textContent=UI.machineJSON;const counts=packet.records.length;safeNotice(machineStatus,`${counts} 条材料 · ${Array.isArray(packet.relations)?packet.relations.length:0} 条关联 · 未调用模型${packet.truncation?.truncated?' · 已按上下文预算选择，原库没有丢失内容':''}`);
  const layers={fact:'事实',preference:'偏好',experience:'经历',commitment:'约定',persona:'人格',dialogue:'历史对话',observation:'工具观察',agent_statement:'助手原话',suggestion:'代理建议'};
  for(const record of packet.records.slice(0,6)){const card=make('div','memory-json-record');const humanTitle=String(record.display?.title||layers[record.layer]||'记忆材料').replace(/^(fact|preference|experience|commitment|persona)\s*·\s*/i,'').replace(/\s+/g,' ');card.append(make('h3','',humanTitle.length>56?humanTitle.slice(0,56)+'…':humanTitle),make('small','',`${layers[record.layer]||'材料'} · ${record.interpretation==='current_memory'?'当前记忆':record.interpretation==='historical_evidence'?'历史证据':'尚需核对'}`));const value=typeof record.value==='string'?record.value:JSON.stringify(record.value);card.append(make('p','',value.length>280?value.slice(0,280)+'…（界面摘录）':value));const sources=record.source?.evidence||[];card.append(make('small','',`${sources.length} 个本次来源引用`));const sourceId=record.id&&S.byId.has(String(record.id))?String(record.id):sources.find(ref=>ref.id&&S.byId.has(String(ref.id)))?.id;if(sourceId){const source=button('查看中文原文');source.onclick=()=>{if(!current(owner))return;machine.dialog.close();clearMachine();select(String(sourceId),true);};card.append(source);}machineRecords.append(card);}
  if(counts>6)machineRecords.append(make('p','form-note',`这里只展示前6条说明，完整的本次材料可按需展开JSON查看。`));if(!counts)machineRecords.append(make('p','empty','当前话题没有可用材料；不会编造或借用其他Agent的记忆。'));
 }catch(e){if(current(owner)&&version===UI.machineVersion&&!e.staleLibrary)safeNotice(machineStatus,'预览未完成：'+e.message,true);}
 finally{if(version===UI.machineVersion)UI.machineBusy=false;updateControls();}
};
machineCopy.onclick=async()=>{if(!UI.machineJSON||UI.machineOwner!==S.libraryId||UI.machineEpoch!==S.libraryEpoch)return;try{await navigator.clipboard.writeText(UI.machineJSON);toast('本次机器JSON已复制。');}catch{machineDetails.open=true;const selection=getSelection(),range=document.createRange();range.selectNodeContents(machinePre);selection.removeAllRanges();selection.addRange(range);toast('已选中JSON，按 ⌘C 复制。');}};

const duplicate=dialogShell('duplicateRecordingDialog','重复来源审阅','closeDuplicateRecordings');
const duplicateIntro=make('p','form-note','同一轮对话可能被自动和手动各存一次。明确重复只折叠显示，双方原文和出处仍在；不同时间的相同话题不会因为字面相同而自动合并。'),duplicateStats=make('p','status-note'),duplicateActions=make('div','memory-json-actions'),duplicateRefresh=button('刷新来源','refreshDuplicateRecordings'),duplicateReconcile=button('检查明确重复','reconcileDuplicateRecordings','本地核对完整对话与来源，只有证据充分才折叠；不删除原文，不调用模型。'),duplicateStatus=make('p','status-note'),duplicateGroups=make('div','');duplicateActions.append(duplicateRefresh,duplicateReconcile);duplicate.dialog.append(duplicateIntro,duplicateStats,duplicateActions,duplicateStatus,duplicateGroups);
function closeDuplicates(){UI.version++;UI.duplicates=null;duplicate.dialog.close();duplicateGroups.replaceChildren();}
duplicate.close.onclick=()=>{if(!UI.busy)closeDuplicates();};duplicate.dialog.addEventListener('cancel',e=>{if(UI.busy)e.preventDefault();else {UI.version++;UI.duplicates=null;duplicateGroups.replaceChildren();}});
async function refreshDuplicates(){if(S.mode!=='serve'||S.libraryChanging)return;const owner=context(),version=++UI.version;UI.owner=owner;safeNotice(duplicateStatus,'读取本库来源…');try{const data=await api('duplicates');if(!current(owner)||version!==UI.version||!duplicate.dialog.open)return;UI.duplicates=data;renderDuplicates(data,owner);safeNotice(duplicateStatus,S.isDemo?'示例只读；原文与记录来源不会被修改。':'只有你确认是同一轮时，才把待核对记录折叠显示。');}catch(e){if(current(owner)&&version===UI.version&&!e.staleLibrary)safeNotice(duplicateStatus,'读取未完成：'+e.message,true);}finally{updateControls();}}
async function openDuplicates(){if(S.mode!=='serve'||S.libraryChanging)return;duplicate.dialog.querySelector('h2').textContent=`${libraryName(S.libraryId)} · 重复来源`;duplicate.dialog.showModal();await refreshDuplicates();}
duplicateOpen.onclick=openDuplicates;duplicateLink.onclick=openDuplicates;duplicateRefresh.onclick=refreshDuplicates;
async function mutateDuplicates(action,payload){if(!canWrite()||MEMORY.busy||UI.busy||!current(UI.owner))return;const owner=context();MEMORY.busy=true;writeBusy=true;UI.busy=true;updateWriteState();let acknowledged=false;
 try{const result=await api('duplicates/'+action,payload);acknowledged=true;if(!current(owner))return;if(result.raw_deleted!==undefined&&result.raw_deleted!==0)throw new Error('服务返回的原文保留状态异常，请停止操作并检查');safeNotice(duplicateStatus,action==='separate'?'已取消显示归并，原文没有删除。':'来源显示已更新，原文与出处保留。');await reload({guard:()=>current(owner)});if(current(owner))await refreshDuplicates();toast(action==='separate'?'已取消显示归并。':'重复来源已处理，原文保留。');}
 catch(e){if(current(owner)&&!e.staleLibrary)safeNotice(duplicateStatus,acknowledged?'操作已提交，但界面读取未确认；请刷新后查看。':'操作未确认：'+e.message,true);}
 finally{MEMORY.busy=false;writeBusy=false;UI.busy=false;updateWriteState();}
}
duplicateReconcile.onclick=()=>mutateDuplicates('reconcile',{});
function renderDuplicates(data,owner){duplicateGroups.replaceChildren();const groups=Array.isArray(data.groups)?data.groups:[],merged=Array.isArray(data.merged_groups)?data.merged_groups:[];duplicateStats.textContent=`${num(data.confirmed_alias_count)} 条确认重复来源 · ${groups.length} 组待核对`;
 for(const [index,group]of groups.entries()){const records=Array.isArray(group.records)?group.records:[],ids=records.map(r=>String(r.id));if(ids.length<2)continue;const card=make('section','duplicate-review-group');card.append(make('h3','',`待核对来源 ${index+1} · ${records.length} 条记录`),make('p','form-note',group.reason||'请核对是否是同一轮对话的不同采集来源。'));const rows=make('div','source-rows');
  for(const record of records){const row=make('div',''),channel={manual:'手动记录',passive:'自动存档',unknown:'来源待确认'}[record.channel]||record.origin||'记录';row.append(make('strong','duplicate-channel',`${channel} · ${date(record.recorded_at)}`),make('p','',`我说的：${record.user_excerpt||'无摘录'}`),make('p','',`AI回复：${record.assistant_excerpt||'无摘录'}`),make('small','','以上是摘录，完整原文保留在原记录。'));if(S.byId.has(String(record.id))){const source=button('查看完整对话');source.onclick=()=>{if(!current(owner))return;closeDuplicates();select(String(record.id),true);};row.append(source);}rows.append(row);}card.append(rows);
  if(num(group.additional_count)>0)card.append(make('p','form-note',`还有 ${num(group.additional_count)} 条相关记录未列出；本次只确认上面显示的这些来源。`));
  const label=make('label','','主要显示哪条？'),choose=make('select','');choose.id='duplicatePrimary-'+index;label.htmlFor=choose.id;for(const record of records){const option=make('option','',`${record.channel==='passive'?'自动':'手动/其他'} · ${date(record.recorded_at)} · ${String(record.label||'对话').slice(0,45)}`);option.value=String(record.id);choose.append(option);}choose.value=ids.includes(group.canonical_id)?group.canonical_id:ids[0];card.append(label,choose);
  const consentLabel=make('label','inline-check'),consent=make('input','');consent.type='checkbox';consentLabel.append(consent,document.createTextNode('我确认上面这些来源是同一轮对话，而非不同时间的重复聊天。'));const confirm=button('确认同轮并折叠');confirm.classList.add('duplicate-write');confirm.dataset.requiresConsent='true';confirm.disabled=true;consent.onchange=updateControls;confirm._consent=consent;confirm.onclick=()=>{if(!consent.checked||!current(owner))return;const canonical=choose.value;mutateDuplicates('confirm',{canonical_id:canonical,alias_ids:ids.filter(id=>id!==canonical),expected:group.expected});};card.append(consentLabel,confirm);duplicateGroups.append(card);
 }
 if(!groups.length)duplicateGroups.append(make('p','empty','当前没有需要确认的重复组。'));
 if(merged.length){duplicateGroups.append(make('h3','section-label','已折叠显示的来源'));for(const group of merged){const card=make('div','duplicate-review-group');card.append(make('strong','',S.byId.get(String(group.canonical_id))?.label||'一组对话来源'),make('p','form-note',`${Array.isArray(group.alias_ids)?group.alias_ids.length:0} 条重复来源与主记录一起保留。`));const separate=button('取消显示归并');separate.classList.add('duplicate-write');separate.onclick=()=>{if(current(owner))mutateDuplicates('separate',{node_id:group.canonical_id,expected:group.expected});};card.append(separate);duplicateGroups.append(card);}}
 updateControls();
}
function updateControls(){const writable=canWrite()&&!MEMORY.busy&&!UI.busy;threshold.disabled=!writable||cadence.value==='session';machineOpen.disabled=S.mode!=='serve'||S.libraryChanging;duplicateOpen.disabled=duplicateLink.disabled=S.mode!=='serve'||S.libraryChanging;machineRead.disabled=UI.busy||UI.machineBusy||S.libraryChanging;machineCopy.disabled=!UI.machineJSON||UI.machineOwner!==S.libraryId||UI.machineEpoch!==S.libraryEpoch;duplicateRefresh.disabled=UI.busy||S.libraryChanging;duplicateReconcile.disabled=!writable;duplicate.close.disabled=UI.busy;for(const b of duplicateGroups.querySelectorAll('.duplicate-write'))b.disabled=!writable||(b.dataset.requiresConsent==='true'&&!b._consent?.checked);
 if(machine.dialog.open&&(UI.machineOwner!==S.libraryId||UI.machineEpoch!==S.libraryEpoch)){machine.dialog.close();clearMachine();}
 if(duplicate.dialog.open&&UI.owner&&!current(UI.owner)){closeDuplicates();}
}
const originalMaintenance=updateMaintenanceButtons;updateMaintenanceButtons=function(){originalMaintenance();updateControls();};
modeNote();updateControls();
})();
