/* Local navigation for authorized source records. No provider calls or behavior proposals. */
(() => {
  'use strict';
  const by=id=>document.getElementById(id),panel=by('organizerPanel');
  if(!panel||typeof S==='undefined'||typeof MEMORY==='undefined'||typeof api!=='function')return;
  const make=(tag,cls,text)=>el(tag,cls,text),owner=()=>({id:S.libraryId,epoch:S.libraryEpoch});
  const current=o=>!!o&&o.id===S.libraryId&&o.epoch===S.libraryEpoch;
  const idle=()=>S.mode==='serve'&&!S.libraryChanging&&!MEMORY.busy&&!writeBusy;
  const manage=()=>typeof canManageMemory==='function'?canManageMemory():typeof canWrite==='function'&&canWrite();
  const state={owner:null,serial:0,loading:false,busy:false,data:null,dirty:false,needsRefresh:false,cursor:null,paged:false};
  function button(id,label,hint,action){const b=make('button','btn',label);b.id=id;b.type='button';b.dataset.hintDescription=hint;b.onclick=()=>action(b);return b;}
  const section=make('details','idle-review-section');section.id='idleReviewSection';
  section.append(make('summary','','空闲整理'));
  const intro=make('p','form-note','维护当前获准原文的目录、角色和同一会话的前后文，帮助大肥鱼快速找到原话。不调用模型；摘要仍由上方记忆整理处理。默认关闭。');
  const identity=make('p','idle-review-identity');identity.id='idleReviewLibrary';
  const enabledLabel=make('label','inline-check'),enabled=make('input');enabled.id='idleReviewEnabled';enabled.type='checkbox';enabledLabel.append(enabled,document.createTextNode('空闲时自动整理'));
  const cadence=make('p','form-note');cadence.id='idleReviewCadence';
  const advanced=make('details','idle-review-advanced');advanced.id='idleReviewAdvanced';advanced.append(make('summary','','高级整理设置'));
  const secondsLabel=make('label','','空闲后开始（秒）'),seconds=make('input');seconds.id='idleReviewIdleSeconds';seconds.type='number';seconds.min='30';seconds.max='86400';seconds.step='1';secondsLabel.htmlFor=seconds.id;
  const batchLabel=make('label','','每次写入来源数'),batch=make('input');batch.id='idleReviewBatchSize';batch.type='number';batch.min='1';batch.max='12';batch.step='1';batchLabel.htmlFor=batch.id;
  advanced.append(secondsLabel,seconds,batchLabel,batch,make('p','form-note','来源会连续分批索引；对话恢复时让出，未完成的下次继续。这是写入分片，不限制记忆数量。'));
  const settingsActions=make('div','idle-review-actions'),save=button('saveIdleReviewSettings','保存整理设置','仅保存本库的目录维护开关与调度设置，不调用模型。',saveSettings);settingsActions.append(save);
  const counts=make('dl','idle-review-counts');counts.id='idleReviewCounts';
  const status=make('p','idle-review-status');status.id='idleReviewStatus';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
  const actions=make('div','idle-review-actions'),preview=button('previewIdleReview','只读预览','读取获准原文数量、目录进度和旧版记录，不调用模型、开启后台或强化记忆。',trigger=>read(true,'',false,trigger)),run=button('runIdleReview','维护原文目录','为当前获准原文补齐本地目录，不调用模型、不改写记忆；任务完成前持续分批处理。',start);run.classList.add('primary');actions.append(preview,run);
  const directory=make('div','idle-review-directory');directory.id='idleReviewDirectory';
  const legacy=make('details','idle-review-legacy');legacy.id='legacyIdleReviewArchive';legacy.append(make('summary','','旧版回顾记录'));
  const proposals=make('div','idle-review-proposals');proposals.id='idleReviewProposals';
  const pagination=make('div','idle-review-actions'),pageInfo=make('p','form-note'),more=button('moreIdleReviewProposals','更多旧版记录','读取当前库下一页旧版记录，不调用模型。',trigger=>read(false,'',true,trigger));pageInfo.id='idleReviewPageInfo';more.hidden=true;pagination.append(pageInfo,more);
  const boundary=make('p','form-note','目录只导航当前获准的原始经历，不代表已完成模型摘要或加载整个记忆库。尚无目录时，大肥鱼仍可用 memory_list / memory_read 读取现有记忆。旧版建议只留历史，可拒绝或撤回，不再新增采纳。');
  legacy.append(proposals,pagination);
  section.append(intro,identity,enabledLabel,cadence,advanced,settingsActions,counts,actions,status,directory,boundary,legacy);
  by('organizerSettings').after(section);
  const style=make('style');style.textContent=`.idle-review-section{margin:18px 0;padding:13px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);min-width:0}.idle-review-section>summary{font-size:14px;color:var(--ink);font-weight:600;cursor:pointer}.idle-review-section .inline-check{font-size:13px;line-height:1.8;gap:8px;align-items:center}.idle-review-section .inline-check input{width:auto;flex:0 0 auto}.idle-review-identity{font-size:12px;color:var(--muted);overflow-wrap:anywhere}.idle-review-counts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px;margin:15px 0}.idle-review-counts>div{background:var(--soft);border:1px solid var(--line);padding:9px 5px;text-align:center;min-width:0}.idle-review-counts dt{font-size:11px;color:var(--muted)}.idle-review-counts dd{font-size:18px;margin:4px 0 0}.idle-review-actions{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.idle-review-actions .btn{font-size:12px;min-height:36px;white-space:normal}.idle-review-status{font-size:12px;line-height:1.8;overflow-wrap:anywhere;white-space:pre-wrap}.idle-review-status[data-error=true]{color:var(--danger)}.idle-review-advanced,.idle-review-boundary{margin:14px 0;font-size:12px}.idle-review-advanced summary,.idle-review-boundary summary{cursor:pointer}.idle-review-advanced input{max-width:100%;min-width:0}.idle-review-proposal{border:1px solid var(--line);background:var(--soft);padding:11px 12px;margin:12px 0;min-width:0;overflow-wrap:anywhere}.idle-review-proposal>summary{font-size:13px;line-height:1.8;cursor:pointer}.idle-review-proposal p,.idle-review-proposal li{font-size:12px;line-height:1.85;white-space:pre-wrap}.idle-review-proposal ul{padding-left:18px}.idle-review-proposal pre{font-size:11px;max-height:190px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}.idle-review-proposal small{font-size:11px;color:var(--muted);display:block;margin:7px 0}.idle-review-proposal .idle-review-source{border:0;background:none;padding:3px 0;font:inherit;font-size:12px;text-align:left;color:var(--accent);white-space:normal;overflow-wrap:anywhere}@media(max-width:420px){.idle-review-counts{gap:4px}.idle-review-counts dt{font-size:10px}.idle-review-actions>.btn{flex:1 1 125px}}`;document.head.append(style);
  const validId=v=>typeof v==='string'&&v.length>0&&v.length<=200;
  const validCount=v=>Number.isSafeInteger(v)&&v>=0;
  function active(o,serial){return section.open&&!panel.hidden&&current(o)&&serial===state.serial;}
  function actionFocus(trigger,fallback=preview){
    if(!trigger)return null;const focused=document.activeElement;
    if(focused&&focused!==trigger&&focused!==document.body&&focused!==document.documentElement)return null;
    const ticket={owner:owner(),trigger,fallback,moved:false};
    const onFocus=event=>{if(event.target!==trigger&&event.target!==document.body&&event.target!==document.documentElement)ticket.moved=true;};
    const onPointer=event=>{if(event.target!==trigger&&!trigger.contains?.(event.target))ticket.moved=true;};
    document.addEventListener('focusin',onFocus,true);document.addEventListener('pointerdown',onPointer,true);
    ticket.release=()=>{document.removeEventListener('focusin',onFocus,true);document.removeEventListener('pointerdown',onPointer,true);};return ticket;
  }
  function restoreActionFocus(ticket){
    if(!ticket)return;ticket.release();const focused=document.activeElement;
    if(ticket.moved||!current(ticket.owner)||!section.open||panel.hidden||focused&&focused!==ticket.trigger&&focused!==document.body&&focused!==document.documentElement)return;
    const target=[ticket.trigger,ticket.fallback,preview].find(node=>node&&!node.disabled&&!node.hidden&&node.isConnected!==false&&node.getClientRects().length);
    target?.focus({preventScroll:true});
  }
  function notice(message,error=false){status.textContent=message+(state.dirty&&message&&!message.includes('尚未保存')?' 整理设置尚未保存。':'');status.dataset.error=String(error);}
  function controls(){
    const scoped=current(state.owner),available=section.open&&!panel.hidden&&idle()&&scoped&&!state.loading&&!state.busy,write=available&&manage()&&!S.isDemo&&!state.data?.is_demo&&!state.needsRefresh;
    preview.disabled=!section.open||panel.hidden||!idle()||state.loading||state.busy;
    more.disabled=preview.disabled||!state.cursor;
    enabled.disabled=seconds.disabled=batch.disabled=!write||!state.data;
    save.disabled=!write||!state.data||!state.dirty;
    run.disabled=!write||!state.data||state.data.running===true||state.dirty;
    for(const b of [...proposals.querySelectorAll('button'),...directory.querySelectorAll('button')]){b.disabled=!available||b.dataset.write==='true'&&(!write||state.data?.running===true);if(b.dataset.write==='true')b.title=state.data?.running===true?'目录正在维护，完成后可处理旧版记录。':'';}
  }
  function reset(){state.serial++;state.owner=null;state.loading=false;state.data=null;state.dirty=false;state.needsRefresh=false;state.cursor=null;state.paged=false;enabled.checked=false;seconds.value='';batch.value='';counts.replaceChildren();proposals.replaceChildren();directory.replaceChildren();pageInfo.textContent='';more.hidden=true;identity.textContent='';cadence.textContent='';notice('');section.open=false;controls();}
  function validate(value,o){
    const data=value?.idle_review||value;
    if(!data||data.schema!=='love-house-idle-review/v1'||data.library_id!==o.id||typeof data.running!=='boolean'||!data.profile||typeof data.profile.enabled!=='boolean'||!Number.isSafeInteger(data.profile.idle_seconds)||data.profile.idle_seconds<1||!Number.isSafeInteger(data.profile.batch_size)||data.profile.batch_size<1||!data.counts||!['eligible','pending','processed','proposals'].every(key=>validCount(data.counts[key]))||!Array.isArray(data.proposals)||data.mode!=='organization'||data.model_called!==false||!Array.isArray(data.directory_entries))throw Error('目录状态与当前记忆库不一致，请重新读取');
    for(const p of data.proposals)if(!validId(p.id)||!['reflection','simulation','strategy_candidate'].includes(p.type)||typeof p.status!=='string'||p.is_user_fact!==false||p.is_real_experience!==false||p.effectiveness!=='unverified'||p.automatic_activation!==false||typeof p.can_accept!=='boolean'||p.can_accept!==false)throw Error('提案缺少来源类型或效果边界，暂不展示');
    for(const entry of data.directory_entries)if(!validId(entry.id)||typeof entry.label!=='string'||entry.read_tool!=='memory_read'||entry.read_arguments?.memory_id!==entry.id||!Array.isArray(entry.roles))throw Error('原文目录缺少可追溯标识，暂不展示');
    if(data.next_cursor!==undefined&&data.next_cursor!==null&&(typeof data.next_cursor!=='string'||!data.next_cursor||data.next_cursor.length>2048))throw Error('提案分页标识无效，请重新预览');
    return data;
  }
  function minutes(value){return value%60===0?`${value/60} 分钟`:`${value} 秒`;}
  function render(data,append=false){
    if(append){const seen=new Set(state.data?.proposals.map(p=>p.id));data={...data,proposals:[...(state.data?.proposals||[]),...data.proposals.filter(p=>!seen.has(p.id))]};}
    state.data=data;state.needsRefresh=false;state.cursor=data.next_cursor||null;state.paged=append;identity.textContent='当前库 · '+(typeof libraryName==='function'?libraryName(state.owner.id):state.owner.id);
    if(!state.dirty){enabled.checked=data.profile.enabled;seconds.value=String(data.profile.idle_seconds);batch.value=String(data.profile.batch_size);}
    cadence.textContent=`${data.profile.enabled?'自动整理已开启':'自动整理已关闭'} · 空闲 ${minutes(data.profile.idle_seconds)} 后开始。改变开关后需保存。`;
    counts.replaceChildren();for(const [key,label]of [['eligible','获准原文'],['pending','待建目录'],['processed','目录就绪'],['proposals','旧版记录']]){const row=make('div');row.append(make('dt','',label),make('dd','',String(data.counts[key])));counts.append(row);}
    directory.replaceChildren();directory.append(make('p','form-note',data.directory_entries.length?'可用原文目录 · 目录预览最多 25 条。完整目录供大肥鱼按页读取。':'原文目录尚未就绪；现有记忆仍可正常检索和读取。'));
    for(const entry of data.directory_entries){const row=make('div','idle-review-proposal'),roles={user:'用户',assistant:'助手',tool:'工具',unknown:'未注明'};row.append(make('p','',entry.label||'原始记录'),make('small','',entry.roles.map(role=>roles[role]||role).join(' / ')+(entry.revision?.state==='historical'?' · 历史说法':'')),button('viewIdleDirectory-'+entry.id,'查看原条目','只查看当前库的原始记录，不强化记忆。',()=>locate(entry.id)));directory.append(row);}
    const opened=new Set([...proposals.querySelectorAll('details')].filter(n=>n.open&&n.dataset.proposalId).map(n=>n.dataset.proposalId));proposals.replaceChildren();
    for(const p of data.proposals)proposal(p,opened.has(p.id));
    if(!data.proposals.length)proposals.append(make('p','form-note','没有旧版回顾记录。新的空闲整理只维护目录，不生成建议。'));
    more.hidden=!state.cursor;pageInfo.textContent=state.cursor||state.paged?`已显示 ${data.proposals.length}/${data.counts.proposals} 条旧版记录。${state.paged?'只读预览可更新列表。':''}`:'';
    controls();
  }
  function evidenceText(ref){if(typeof ref==='string')return ref;if(!ref||typeof ref!=='object')return '';return [ref.title||ref.label,ref.quote||ref.text||ref.excerpt,ref.source_id||ref.id].filter(v=>typeof v==='string').join(' · ');}
  function proposal(p,open){
    const card=make('details','idle-review-proposal');card.dataset.proposalId=p.id;card.open=open;
    const types={reflection:'反思',simulation:'模拟练习',strategy_candidate:'策略候选'},statuses={pending:'待审阅',proposed:'待审阅',accepted:'已采纳',rejected:'已拒绝',rolled_back:'已撤回',invalidated:'来源已失效'};
    card.append(make('summary','',`${typeof p.title==='string'?p.title:types[p.type]} · ${statuses[p.status]||'待核对'}`),make('small','',`${types[p.type]} · 旧版派生材料 · 不是用户事实或真实经历`),make('p','',typeof p.text==='string'?p.text:''));
    const evidence=make('details');evidence.append(make('summary','','查看来源证据'));const refs=Array.isArray(p.evidence)?p.evidence:[];
    if(refs.length){const list=make('ul');for(const ref of refs){const row=make('li','',evidenceText(ref)||'来源引用');const id=typeof ref==='string'?ref:ref.source_id||ref.id;if(validId(id)){const view=button('viewIdleReviewSource-'+p.id+'-'+id,'查看原条目','只在当前库查看仍有效的来源条目，不强化记忆。',()=>locate(id));view.className='idle-review-source';row.append(view);}list.append(row);}evidence.append(list);}else evidence.append(make('p','','来源证据暂未提供；不能据此确认结论。'));card.append(evidence);
    if(p.replay&&typeof p.replay==='object'){const replay=make('details');replay.append(make('summary','','查看检索与边界核验'),make('p','','核验只检查记忆选择与授权边界，实际模型效果尚未验证。'));const pre=make('pre');pre.textContent=JSON.stringify(p.replay,null,2);replay.append(pre);card.append(replay);}
    const actions=make('div','idle-review-actions');
    if(['pending','proposed'].includes(p.status))actions.append(actionButton(p,'reject','拒绝提案'));
    if(p.type==='reflection'&&p.status==='accepted')actions.append(actionButton(p,'rollback','撤回已采纳反思'));
    if(actions.children.length)card.append(actions);proposals.append(card);
  }
  function actionButton(p,action,label){const b=button('idleReview-'+action+'-'+p.id,label,action==='rollback'?'只停用这条已采纳反思，不恢复被遗忘的原文。':'仅处理这条当前库提案；不会自动采用其他候选。',trigger=>mutateProposal(p,action,trigger));b.dataset.write='true';return b;}
  function locate(id){if(!current(state.owner))return;const node=S.byId?.get(id);if(!node||node.meta?.memory_disabled||node.meta?.forgotten||node.state==='forgotten'){notice('这条来源已失效或未载入当前图谱，请刷新后查看。',true);return;}if(typeof setPanelOpen==='function')setPanelOpen('organizerPanel',false,{restore:false});if(typeof select==='function')select(id,true);}
  for(const input of [enabled,seconds,batch]){input.onchange=()=>{state.dirty=true;notice('整理设置尚未保存。');controls();};if(input!==enabled)input.oninput=input.onchange;}
  async function read(previewOnly=false,success='',append=false,trigger=null,focusTicket=null){
    if(!section.open||panel.hidden||!idle()||state.loading||state.busy||append&&!state.cursor){restoreActionFocus(focusTicket);return;}const ticket=focusTicket||actionFocus(trigger),o=owner(),serial=++state.serial,cursor=append?state.cursor:null;let resetPage=false;state.owner=o;state.loading=true;notice(previewOnly?'正在只读预览，不调用模型…':append?'正在读取更多提案…':'正在读取目录状态…');controls();
    try{const route=previewOnly?'idle-review/preview':'idle-review'+(cursor?'?cursor='+encodeURIComponent(cursor):'');const value=await api(route,previewOnly?{}:undefined,{libraryId:o.id});if(!active(o,serial))return;const data=validate(value,o);if(previewOnly&&(data.read_only!==true||data.model_called!==false))throw Error('预览缺少只读与未调用模型的回执');render(data,append);notice(success||(data.last_error?.message?'上次目录维护未完成：'+data.last_error.message:data.running?'正在维护原文目录；可关闭面板，剩余索引会连续分批处理。':previewOnly?'预览完成；未调用模型、未开启后台或强化记忆。':'已读取本库目录状态。'),!!data.last_error);}
    catch(error){if(active(o,serial)){if(!append){state.data=null;proposals.replaceChildren();directory.replaceChildren();counts.replaceChildren();pageInfo.textContent='';more.hidden=true;state.cursor=null;}else if(/分页|游标|cursor/i.test(error.message)){resetPage=true;state.cursor=null;}notice('读取未完成：'+error.message,true);}}
    finally{if(current(o)&&serial===state.serial){state.loading=false;controls();if(resetPage&&section.open&&!panel.hidden){await read(false,'提案列表已变化，已重新读取第一页。',false,null,ticket);return;}}restoreActionFocus(ticket);}
  }
  function writable(){return section.open&&!panel.hidden&&current(state.owner)&&idle()&&!state.loading&&!state.busy&&state.data&&!state.needsRefresh&&manage()&&!S.isDemo&&!state.data.is_demo;}
  async function write(route,body,success,decision=null,trigger=null,fallback=preview){
    if(!writable())return;const ticket=actionFocus(trigger,fallback),o={...state.owner},serial=++state.serial;state.busy=true;MEMORY.busy=true;notice('正在提交本库操作…');controls();if(typeof updateWriteState==='function')updateWriteState();let acknowledged=false;
    try{const value=await api(route,body,{libraryId:o.id});if(!active(o,serial))return;let data;
      if(route==='idle-review/settings'){data=validate(value,o);acknowledged=true;}
      else{if(value?.library_id!==o.id)throw Error('操作回执不属于当前记忆库');if(value.status==='busy'){notice('本库已有目录任务正在处理，请稍后只读预览状态。',true);return;}
        if(route==='idle-review/run'){if(value.queued!==true||value.status!=='queued')throw Error('目录维护尚未确认排队');}
        else if(!decision||value.proposal_id!==decision.id||value.status!=={reject:'rejected',rollback:'rolled_back'}[decision.action])throw Error('提案操作回执与所选条目不一致');
        acknowledged=true;data=validate(await api('idle-review',undefined,{libraryId:o.id}),o);if(!active(o,serial))return;
      }
      if(route==='idle-review/settings')state.dirty=false;render(data);notice(data.last_error?.message?success+'；目录尚未完成：'+data.last_error.message:success,!!data.last_error);
    }
    catch(error){if(active(o,serial)){state.needsRefresh=true;notice((acknowledged?'操作已确认，状态读取失败；请只读预览后继续：':'操作未确认，请只读预览后再决定是否重试：')+error.message,true);}}
    finally{state.busy=false;MEMORY.busy=false;if(current(o)&&serial===state.serial)controls();if(typeof updateWriteState==='function')updateWriteState();restoreActionFocus(ticket);}
  }
  async function saveSettings(trigger){if(!writable())return;const idleSeconds=Number(seconds.value),batchSize=Number(batch.value);if(!Number.isSafeInteger(idleSeconds)||idleSeconds<30||idleSeconds>86400||!Number.isSafeInteger(batchSize)||batchSize<1||batchSize>12){notice('空闲时间请填 30–86400 秒，每次写入来源数请填 1–12 的整数；剩余来源会继续处理。',true);return;}return write('idle-review/settings',{enabled:enabled.checked,idle_seconds:idleSeconds,batch_size:batchSize},enabled.checked?'整理设置已保存，空闲时将维护本地目录，不调用模型。':'整理设置已保存，自动整理已关闭。',null,trigger,enabled);}
  async function start(trigger){if(!writable()||state.data.running||state.dirty)return;return write('idle-review/run',{},'已提交原文目录维护；连续分批索引，不调用模型、不改写原话。',null,trigger);}
  async function mutateProposal(p,action,trigger){if(!writable()||state.data.running||!state.data.proposals.some(item=>item.id===p.id&&item.status===p.status)||!['reject','rollback'].includes(action))return;if(action==='rollback'&&(p.type!=='reflection'||p.status!=='accepted'))return;return write('idle-review/proposals/'+encodeURIComponent(p.id)+'/'+action,{},action==='reject'?'已拒绝这条提案。':'已停用这条已采纳反思；不会恢复被遗忘的原文。',{id:p.id,action},trigger);}
  section.addEventListener('toggle',()=>{if(section.open){if(!current(state.owner))state.dirty=false;read();}else{state.serial++;state.loading=false;controls();}});
  if(typeof setPanelOpen==='function'){const previous=setPanelOpen;setPanelOpen=function(id,open,...args){const value=previous(id,open,...args);if(id==='organizerPanel'&&!open){state.serial++;state.loading=false;controls();}return value;};}
  if(typeof updateMemoryButtons==='function'){const previous=updateMemoryButtons;updateMemoryButtons=function(...args){previous(...args);if(state.owner&&!current(state.owner))reset();controls();};}
  if(typeof refreshOrganizer==='function'){const previous=refreshOrganizer;refreshOrganizer=async function(...args){const value=await previous(...args);if(section.open&&!panel.hidden&&!state.dirty&&!state.busy&&!state.paged)await read();return value;};}
  window.LoveHouseIdleReview={refresh:()=>read(),reset};
  controls();
})();
