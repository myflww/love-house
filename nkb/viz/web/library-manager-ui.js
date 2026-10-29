/* Reversible library removal. This component never purges raw files or credentials. */
(()=>{
'use strict';
if(typeof MEMORY==='undefined'||typeof renderLibraries!=='function'||!document.getElementById('libraryList'))return;
const by=id=>document.getElementById(id),make=(tag,cls,text)=>el(tag,cls,text);
const state={preview:null,previewVersion:0,trashVersion:0,loadingTrash:false,restoring:false};
const style=document.createElement('style');style.textContent=`
.library-manage-row{display:flex;align-items:center;gap:8px;margin:3px 0}.library-manage-row .library-choice{flex:1 1 auto;min-width:0;width:0}.library-delete-button{flex:0 0 auto;min-width:46px;min-height:30px;padding:4px 7px!important;font-size:12px!important;color:var(--danger,#944b42)!important}.library-trash-entry{width:100%;margin-top:9px;justify-content:center}.library-trash-row{padding:14px 0;border-bottom:1px solid var(--line);display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center}.library-trash-row strong{font-size:14px;overflow-wrap:anywhere}.library-trash-row small{display:block;line-height:1.7;margin-top:3px;color:var(--muted)}#libraryDeleteDialog,#libraryTrashDialog{width:min(520px,calc(100vw - 30px));max-height:calc(100vh - 38px);overflow:auto}.library-trash-heading{display:flex;justify-content:space-between;align-items:center;gap:12px}.library-delete-facts{display:grid;grid-template-columns:100px minmax(0,1fr);gap:9px 12px;margin:18px 0;font-size:13px}.library-delete-facts dt{color:var(--muted)}.library-delete-facts dd{margin:0;overflow-wrap:anywhere}.library-trash-actions{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:16px}.library-trash-notice{margin-top:12px;line-height:1.75}.library-trash-empty{padding:20px 0;color:var(--muted)}
`;document.head.append(style);
function button(id,text,description,handler){const b=make('button','btn',text);b.type='button';if(id)b.id=id;b.setAttribute('data-hint-description',description);b.onclick=handler;return b;}
const deleteDialog=make('dialog','');deleteDialog.id='libraryDeleteDialog';deleteDialog.setAttribute('aria-labelledby','libraryDeleteTitle');
const deleteHeader=make('div','dialog-title'),deleteTitle=make('h2','','删除记忆库');deleteTitle.id='libraryDeleteTitle';const deleteClose=button('closeLibraryDelete','×','关闭删除预览；不会修改记忆库。',closeDelete);deleteClose.className='icon-btn';deleteClose.setAttribute('aria-label','关闭删除记忆库预览');deleteHeader.append(deleteTitle,deleteClose);
const preview=make('div','');preview.id='libraryDeletePreview';const deleteNote=make('p','form-note','将停止这个库的聊天接收，并移入回收站。已经保存的原文和记忆会保留，之后可以恢复。');
const deleteStatus=make('p','form-note');deleteStatus.id='libraryDeleteNotice';deleteStatus.setAttribute('role','status');
const deleteActions=make('div','dialog-actions'),deleteCancel=button('cancelLibraryDelete','取消','保留记忆库，关闭本次预览。',closeDelete),deleteConfirm=button('confirmLibraryDelete','确认移入回收站','断开这个库的接收连接并移入回收站；不会永久删除原文。',confirmDelete);deleteConfirm.classList.add('primary');deleteActions.append(deleteCancel,deleteConfirm);deleteDialog.append(deleteHeader,preview,deleteNote,deleteStatus,deleteActions);
const trashDialog=make('dialog','');trashDialog.id='libraryTrashDialog';trashDialog.setAttribute('aria-labelledby','libraryTrashTitle');const trashHeader=make('div','library-trash-heading'),trashTitle=make('h2','','记忆库回收站');trashTitle.id='libraryTrashTitle';const trashClose=button('closeLibraryTrash','×','关闭回收站，已经移入的记忆库仍会保留。',closeTrash);trashClose.className='icon-btn';trashClose.setAttribute('aria-label','关闭记忆库回收站');trashHeader.append(trashTitle,trashClose);
const trashList=make('div','');trashList.id='libraryTrashList';const trashNotice=make('p','form-note library-trash-notice');trashNotice.id='libraryTrashNotice';trashNotice.setAttribute('role','status');const trashActions=make('div','library-trash-actions'),trashRefresh=button('refreshLibraryTrash','刷新列表','重新读取回收站，不会调用模型。',loadTrash),trashDone=button('doneLibraryTrash','完成','关闭回收站。',closeTrash);trashActions.append(trashRefresh,trashDone);trashDialog.append(trashHeader,make('p','form-note','恢复后会打开原来的记忆库。聊天连接和自动整理保持停止，接入后再继续记录。'),trashList,trashNotice,trashActions);
document.body.append(deleteDialog,trashDialog);
const trashEntry=button('openLibraryTrash','回收站','查看移入回收站的记忆库；可以恢复，也包括示例库。',openTrash);trashEntry.classList.add('library-trash-entry');by('newLibraryBtn').after(trashEntry);
function busy(){return !!(MEMORY.busy||writeBusy||S.libraryChanging);}
function canManage(){return canManageMemory()&&!busy()&&MEMORY.catalogReady;}
function sync(){
 const blocked=!canManage();trashEntry.disabled=blocked;deleteConfirm.disabled=blocked||!state.preview?.ready;
 for(const b of document.querySelectorAll('#libraryList [data-delete-library]'))b.disabled=blocked;
 for(const b of document.querySelectorAll('#libraryTrashList [data-restore-library]'))b.disabled=blocked||b.dataset.restorable==='false';
 trashRefresh.disabled=blocked||state.loadingTrash;for(const b of [deleteClose,deleteCancel,trashClose,trashDone])b.disabled=busy();
}
function mutationBusy(value){MEMORY.busy=value;writeBusy=value;updateWriteState();sync();}
function closeDelete(){if(busy())return;state.previewVersion++;state.preview=null;deleteDialog.close();sync();}
function closeTrash(){if(busy())return;state.trashVersion++;state.loadingTrash=false;trashDialog.close();sync();}
deleteDialog.addEventListener('cancel',e=>{if(busy())e.preventDefault();else{state.previewVersion++;state.preview=null;}});
trashDialog.addEventListener('cancel',e=>{if(busy())e.preventDefault();else{state.trashVersion++;state.loadingTrash=false;}});
function addFact(box,key,value){box.append(make('dt','',key),make('dd','',String(value??'—')));}
async function previewDelete(id){
 if(!canManage())return;const version=++state.previewVersion;state.preview={id,ready:false};preview.replaceChildren(make('p','form-note','读取影响范围…'));deleteStatus.textContent='';deleteConfirm.textContent='确认移入回收站';deleteDialog.showModal();sync();deleteCancel.focus();
 try{const result=await api('libraries/'+encodeURIComponent(id)+'/delete-preview',{}, {scope:false});if(version!==state.previewVersion||state.preview?.id!==id||!deleteDialog.open)return;const item=result.library||{},facts=make('dl','library-delete-facts');addFact(facts,'记忆库',item.name||libraryName(id));addFact(facts,'已保存节点',item.node_count==null?'暂不可读':`${num(item.node_count)} 条`);addFact(facts,'停止接收连接',`${num(result.connections_to_disconnect)} 个`);addFact(facts,'类型',item.is_demo?'只读效果示例':'独立 Agent 记忆库');addFact(facts,'恢复方式','回收站中恢复');preview.replaceChildren(facts);deleteNote.textContent=item.is_demo?'示例也可以移入回收站。预览原文件会保留，重新启动不会自动加回来；需要时可恢复。':'将停止这个库的聊天接收，并移入回收站。已经保存的原文和记忆会保留，之后可以恢复。';state.preview.ready=true;sync();}
 catch(e){if(version!==state.previewVersion)return;deleteStatus.textContent='暂时无法预览：'+e.message;}
}
async function confirmDelete(){
 const target=state.preview;if(!canManage()||!target?.ready||!deleteDialog.open)return;const id=target.id,oldCurrent=S.libraryId,wasCurrent=id===oldCurrent;let acknowledged=false;
 if(wasCurrent)savePersonaDraft();mutationBusy(true);deleteStatus.textContent='正在停止接收并移入回收站…';
 try{
  const result=await api('libraries/'+encodeURIComponent(id)+'/delete',{confirm:true},{scope:false});acknowledged=true;state.previewVersion++;state.preview=null;deleteDialog.close();
  // Keep an unsaved persona draft under its original identity, never the fallback.
  if(wasCurrent){MEMORY.personaDirty=false;MEMORY.personaDraftRevision=null;}
  if(MEMORY.config?.connection?.library_id===id){MEMORY.config=null;MEMORY.configVersion++;by('connectionConfig').value='';by('connectionConfigPanel').hidden=true;by('clientApiKey').value='';}
  await refreshLibraries();if(!MEMORY.catalogReady)throw new Error('记忆库列表暂不可读取');
  const fallback=String(result.selected_id||result.default_id||'');mutationBusy(false);
  if(wasCurrent||!MEMORY.libraries.some(x=>x.id===oldCurrent)){if(!fallback)throw new Error('未读到当前可用库，请刷新页面');await selectMemoryLibrary(fallback,{alreadySelected:true});}
  await refreshConnections();const warnings=Array.isArray(result.warnings)?result.warnings.filter(x=>typeof x==='string'):[];toast(warnings.length?'已移入回收站。'+warnings.join(' '):'已移入回收站；原文和记忆保留，可从回收站恢复。',!!warnings.length);
 }catch(e){deleteStatus.textContent=(acknowledged?'已移入回收站，但界面更新失败。':'移入回收站失败：')+e.message;toast(acknowledged?'记忆库已移入回收站；请重新打开库列表，不必重复删除。':'移入回收站失败：'+e.message,true);}
 finally{mutationBusy(false);renderLibraries();}
}
async function openTrash(){if(!canManage())return;trashDialog.showModal();trashNotice.textContent='';await loadTrash();trashDone.focus();}
async function loadTrash(){
 if(S.mode!=='serve'||busy()||state.loadingTrash)return;const version=++state.trashVersion;state.loadingTrash=true;trashList.replaceChildren(make('p','library-trash-empty','读取回收站…'));sync();
 try{const result=await api('libraries/trash',undefined,{scope:false});if(version!==state.trashVersion||!trashDialog.open)return;trashList.replaceChildren();const items=Array.isArray(result.libraries)?result.libraries:[];for(const item of items){const row=make('div','library-trash-row'),body=make('div','');body.append(make('strong','',item.name||'记忆库'),make('small','',item.is_demo?'只读示例':`${num(item.node_count)} 条已保存节点`));if(item.deleted_at)body.append(make('small','',`移入时间 ${date(item.deleted_at)}`));const restore=button('', '恢复并打开','恢复原来的记忆库；不会重新启用旧聊天连接。',()=>restoreLibrary(String(item.id)));restore.dataset.restoreLibrary=String(item.id);restore.dataset.restorable=String(item.restorable!==false);if(item.restorable===false)body.append(make('small','', '原文件暂不可用，请先找回文件或备份。'));row.append(body,restore);trashList.append(row);}if(!items.length)trashList.append(make('p','library-trash-empty','回收站是空的。'));
 }catch(e){if(version===state.trashVersion)trashList.replaceChildren(make('p','form-note','回收站读取失败：'+e.message));}
 finally{if(version===state.trashVersion){state.loadingTrash=false;sync();}}
}
async function restoreLibrary(id){
 if(!canManage()||!trashDialog.open)return;let acknowledged=false;savePersonaDraft();mutationBusy(true);trashNotice.textContent='正在恢复记忆库…';
 try{const result=await api('libraries/'+encodeURIComponent(id)+'/restore',{confirm:true},{scope:false});acknowledged=true;await refreshLibraries();if(!MEMORY.catalogReady)throw new Error('记忆库列表暂不可读取');const target=String(result.library?.id||result.selected_id||id);mutationBusy(false);trashDialog.close();await selectMemoryLibrary(target,{alreadySelected:true});toast(result.library?.is_demo?'示例库已恢复并打开，仍是独立只读预览。':'记忆库已恢复并打开；聊天接收与自动整理需要重新启用。');}
 catch(e){trashNotice.textContent=(acknowledged?'记忆库已经恢复，但界面更新失败。':'恢复失败：')+e.message;toast(acknowledged?'记忆库已经恢复；请刷新列表查看，不必重复恢复。':'恢复失败：'+e.message,true);}
 finally{mutationBusy(false);renderLibraries();}
}
const originalRender=renderLibraries;renderLibraries=function(...args){originalRender(...args);const order=[...MEMORY.libraries.filter(x=>!x.is_demo),...MEMORY.libraries.filter(x=>x.is_demo)];const choices=[...by('libraryList').querySelectorAll('.library-choice')];choices.forEach((choice,index)=>{const item=order[index];if(!item)return;const row=make('div','library-manage-row'),remove=button('', '删除','查看影响范围后，将这个记忆库移入可恢复的回收站。',()=>previewDelete(String(item.id)));remove.classList.add('library-delete-button');remove.dataset.deleteLibrary=String(item.id);remove.setAttribute('aria-label','删除记忆库：'+item.name);remove.setAttribute('data-hint-title',item.is_demo?'删除示例库':'删除记忆库');choice.replaceWith(row);row.append(choice,remove);});sync();};
const originalButtons=updateMemoryButtons;updateMemoryButtons=function(...args){originalButtons(...args);sync();};
// Public surface only exposes UI entry points, never raw records or credentials.
window.LoveHouseLibraries={openTrash,previewDelete};
renderLibraries();
})();
