/* Read original statements and later changes without deciding their truth. */
(() => {
  'use strict';
  if (typeof S === 'undefined' || typeof api !== 'function' || typeof renderDetail !== 'function') return;
  const by = id => document.getElementById(id);
  const make = (tag, cls, text) => el(tag, cls, text);
  const state = {owner:null, id:null, serial:0, busy:false, loading:false, cursor:null, plan:null, origin:null, retryAppend:false};
  const current = o => !!o && o.id === S.libraryId && o.epoch === S.libraryEpoch;
  const scope = () => ({id:S.libraryId, epoch:S.libraryEpoch});
  const date = value => typeof value === 'number' ? new Date(value*1000).toLocaleString('zh-CN') : '时间未提供';
  function button(id, text, action) {
    const node=make('button','btn',text); node.id=id; node.type='button'; node.onclick=action; return node;
  }
  const dialog=make('dialog','memory-history-dialog'); dialog.id='memoryHistoryDialog';
  dialog.setAttribute('aria-labelledby','memoryHistoryTitle');
  const head=make('div','dialog-title'), title=make('h2','','原话与后续变化'); title.id='memoryHistoryTitle';
  const close=button('closeMemoryHistory','关闭',()=>finish()); head.append(title,close);
  const intro=make('p','form-note','这里保留当时的说法和后来的补充。时间与来源帮助理解经历，不表示爱之屋判定哪句话为真。');
  const status=make('p','form-note'); status.id='memoryHistoryStatus'; status.setAttribute('role','status');
  const list=make('div'); list.id='memoryHistoryList';
  const more=button('moreMemoryHistory','继续查看历史',()=>load(true)); more.hidden=true;
  const retry=button('retryMemoryHistory','重试读取',()=>load(state.retryAppend)); retry.hidden=true;
  const legacy=make('details','memory-history-legacy'); legacy.id='legacyHistoryRestore'; legacy.hidden=true;
  legacy.append(make('summary','','旧版历史恢复'),make('p','form-note','旧版曾把更正与手动停用共用一个标记，无法安全替你决定。查看范围后可明确恢复旧版更正历史；原有删除和明确停用继续生效。'));
  const preview=button('previewLegacyHistoryRestore','查看恢复范围',previewRestore);
  const plan=make('div'); plan.id='legacyHistoryRestorePlan';
  const label=make('label','inline-check'), confirm=make('input'); confirm.type='checkbox'; confirm.id='confirmLegacyHistoryRestore';
  label.append(confirm,make('span','','我确认恢复以上旧版历史的可读状态'));
  const restore=button('restoreLegacyHistory','恢复历史可读',restoreHistory); restore.disabled=true;
  confirm.onchange=()=>controls(); legacy.append(preview,plan,label,restore);
  dialog.append(head,intro,status,list,more,retry,legacy); document.body.append(dialog);
  const style=make('style'); style.textContent=`.memory-history-dialog{width:min(700px,calc(100vw - 28px));max-height:calc(100dvh - 28px);overflow:auto}.memory-history-dialog>.dialog-title{position:sticky;top:-1px;background:var(--panel);z-index:1;padding:8px 0;border-bottom:1px solid var(--line)}.memory-history-entry{border:1px solid var(--line);padding:13px 15px;margin:12px 0;background:var(--soft);overflow-wrap:anywhere}.memory-history-entry h3{font-size:14px;line-height:1.8;margin:0 0 5px}.memory-history-entry p{font-size:13px;line-height:1.9;white-space:pre-wrap}.memory-history-entry small{font-size:11px;color:var(--muted);display:block;line-height:1.9}.memory-history-legacy{border-top:1px solid var(--line);margin-top:18px;padding-top:13px}.memory-history-legacy>summary{cursor:pointer;color:var(--accent);font-size:13px}.memory-history-legacy .btn{margin:9px 8px 9px 0}.memory-history-dialog .inline-check{font-size:12px;line-height:1.9;display:flex;align-items:center;gap:8px}.memory-history-dialog .inline-check input{width:auto}.memory-history-open{margin:10px 0;font-size:12px}.memory-history-state{border-left:3px solid var(--accent);padding:8px 12px;background:var(--soft);font-size:12px;line-height:1.9}`; document.head.append(style);
  function notice(message,error=false) {status.textContent=message; status.dataset.error=String(error);}
  function valid(o,serial) {return dialog.open && current(o) && state.serial===serial;}
  function controls() {
    const locked=state.busy || state.loading || !current(state.owner);
    close.disabled=state.busy; more.disabled=preview.disabled=retry.disabled=locked;
    confirm.disabled=locked || !state.plan;
    restore.disabled=locked || !state.plan || !confirm.checked || S.isDemo || !canWrite();
  }
  function clear() {
    state.serial++; state.owner=null; state.id=null; state.cursor=null; state.plan=null;
    state.loading=false;state.origin=null;state.retryAppend=false;
    confirm.checked=false; list.replaceChildren(); plan.replaceChildren(); legacy.hidden=true;
    more.hidden=retry.hidden=true; notice('');
  }
  function finish() {
    if(state.busy)return;
    const o=state.owner,target=state.origin?.isConnected?state.origin:by('viewMemoryVersions');
    dialog.close(); clear();
    if(current(o)&&target&&!target.hidden)target.focus({preventScroll:true});
  }
  async function open(id,origin) {
    if(S.mode!=='serve'||S.libraryChanging||MEMORY.busy||writeBusy)return;
    clear(); state.owner=scope(); state.id=id; state.origin=origin;
    dialog.showModal(); close.focus(); controls(); await load(false);
  }
  async function load(append=false) {
    if(!dialog.open || !current(state.owner) || state.busy || append&&!state.cursor)return;
    const o={...state.owner}, id=state.id, serial=++state.serial;
    state.loading=true;retry.hidden=true;controls();notice('正在读取原话与变化…');
    try {
      const data=await api('memories/'+encodeURIComponent(id)+'/versions'+(append?'?cursor='+encodeURIComponent(state.cursor):''),undefined,{libraryId:o.id});
      if(!valid(o,serial))return;
      if(data.schema!=='love-house-memory-versions/v1'||data.library_id!==o.id||data.id!==id||data.read_only!==true||data.will_call_model!==false||data.world_truth_assessed!==false||!Array.isArray(data.entries))throw Error('历史回执与当前库不一致');
      if(!append)list.replaceChildren();
      for(const entry of data.entries) {
        const row=make('article','memory-history-entry');
        if(entry.available!==true) {
          row.append(make('h3','','这段资料当前不可读取'),make('p','','它可能已被明确停用、忘记或超出可读范围。不会通过历史查看绕过这些设置。'));
        } else {
          row.append(make('h3','',entry.label||'原始说法'));
          row.append(make('small','',(entry.revision?.state==='historical'?'当时的说法':'后续／当前记录')+' · '+({user:'用户',assistant:'助手',tool:'工具',mixed:'多种角色'}[entry.role]||entry.role||'来源角色未提供')+' · 记录于 '+date(entry.recorded_at)));
          row.append(make('p','',entry.text||''));
          const refs=make('details'); refs.append(make('summary','','来源与时间'),make('p','','原始时间：'+date(entry.source_time?.at??entry.source_time)+'\n来源：'+(entry.source_ids||[]).join('、'))); row.append(refs);
        }
        list.append(row);
      }
      if(!list.children.length)list.append(make('p','form-note','没有可展示的历史记录。'));
      state.cursor=data.next_cursor||null; more.hidden=!state.cursor;
      legacy.hidden=!data.legacy_history_requires_confirmation;
      notice('已读取相关说法。原话、时间与后续变化分别保留。');
      return true;
    } catch(error) {if(valid(o,serial)){state.retryAppend=append;retry.hidden=false;notice('读取未完成：'+error.message,true);}return false;}
    finally {if(valid(o,serial)){state.loading=false;controls();}}
  }
  async function previewRestore() {
    if(!current(state.owner)||state.busy||!dialog.open)return;
    const o={...state.owner},serial=++state.serial;
    state.plan=null;confirm.checked=false;plan.replaceChildren();controls();notice('正在读取恢复范围…');
    try {
      const data=await api('memories/'+encodeURIComponent(state.id)+'/history-restore-preview',{}, {libraryId:o.id});
      if(!valid(o,serial))return;
      if(data.library_id!==o.id||data.id!==state.id||data.read_only!==true||!Array.isArray(data.entries)||typeof data.expected_revision!=='string')throw Error('恢复范围与当前库不一致');
      state.plan=data;
      for(const entry of data.entries)plan.append(make('p','form-note',entry.label||entry.id));
      plan.append(make('p','form-note',`${data.node_count} 条历史，${data.source_count} 条引用来源。恢复历史可读，不把旧说法当作当前说法。`));
      notice(data.node_count?'请核对恢复范围，确认后才修改。':'当前没有需要恢复的旧版历史。');
    } catch(error) {if(valid(o,serial))notice('预览未完成：'+error.message,true);}
    finally {if(valid(o,serial))controls();}
  }
  async function restoreHistory() {
    if(!state.plan||!confirm.checked||state.busy||!current(state.owner)||!dialog.open||S.isDemo||!canWrite())return;
    const o={...state.owner},serial=++state.serial,body={confirm:true,expected_revision:state.plan.expected_revision};
    state.busy=true;MEMORY.busy=true;writeBusy=true;controls();updateWriteState();let saved=false,confirmed=false,message='',failed=false;
    try {
      const result=await api('memories/'+encodeURIComponent(state.id)+'/history-restore',body,{libraryId:o.id});
      saved=true;if(!valid(o,serial))return;
      if(result.id!==state.id||result.library_id!==o.id||result.restored!==true||result.current_memory_restored!==false||result.world_truth_assessed!==false)throw Error('恢复结果需要重新核对');
      confirmed=true;
      state.plan=null;confirm.checked=false;plan.replaceChildren();
      await reload({guard:()=>current(o)});
      message='旧版历史已恢复可读；当前说法和明确停用设置保持。';
    } catch(error) {failed=true;message=(confirmed?'历史恢复已保存，图谱刷新未完成：':saved?'操作可能已保存，请重新查看历史：':'恢复未完成：')+error.message;}
    finally {
      state.busy=false;MEMORY.busy=false;writeBusy=false;updateWriteState();
      if(valid(o,serial)){
        // Every new attempt needs a newly inspected scope. A failed or
        // ambiguous receipt must not leave an old checked plan ready to resend.
        state.plan=null;confirm.checked=false;plan.replaceChildren();controls();
        if(confirmed){
          const next=state.serial+1,loaded=await load(false);
          if(valid(o,next))notice(message+(loaded?'':'；历史列表暂未刷新，可重试读取。'),failed||!loaded);
        }else notice(message,true);
        if(current(o)&&dialog.open)close.focus();
      }
    }
  }
  dialog.addEventListener('cancel',event=>{if(state.busy)event.preventDefault();});
  dialog.addEventListener('close',()=>{if(!state.busy){const o=state.owner,target=state.origin?.isConnected?state.origin:by('viewMemoryVersions');clear();if(current(o)&&target&&!target.hidden)target.focus({preventScroll:true});}});
  const original=renderDetail;
  renderDetail=function(...args) {
    original(...args);if(S.mode!=='serve'||!S.selected||!by('detail'))return;
    by('viewMemoryVersions')?.remove();
    const entry=button('viewMemoryVersions','原话与后续变化',()=>open(S.selected,entry)); entry.classList.add('memory-history-open');
    by('detail').append(entry);
    const node=S.byId.get(S.selected);
    if(node?.superseded_by||node?.meta?.memory_revision?.status==='historical') {
      const note=make('p','memory-history-state','这是一段历史说法，后面还有新的记录。可以查看前后变化；明确停用与真正忘记仍然生效。');
      by('detail').prepend(note);
    }
  };
  if(typeof updateMemoryButtons==='function') {
    const old=updateMemoryButtons;
    updateMemoryButtons=function(...args){old(...args);if(state.owner&&!current(state.owner)){if(dialog.open)dialog.close();clear();}controls();};
  }
  window.LoveHouseMemoryHistory={open,close:finish};
})();
