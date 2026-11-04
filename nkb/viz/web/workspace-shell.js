/* A compact, labelled shell over the existing actions. No new permissions or writes. */
(() => {
  'use strict';
  const by = id => document.getElementById(id);
  if (!by('app') || !by('settings') || by('workspaceDisplayMenu')) return;
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const header = document.querySelector('#app > header');
  const actions = header?.querySelector('.head-actions');
  if (!header || !actions) return;
  document.documentElement.dataset.workspace = 'guided';
  const style = make('style');
  style.id = 'workspace-shell-style';
  style.textContent = `
html[data-workspace=guided] #app>header{height:auto;min-height:82px;display:grid;grid-template-columns:minmax(145px,205px) minmax(150px,1fr) auto auto;grid-template-areas:'identity search nav add';align-items:center;gap:16px;padding:14px 20px;position:relative}
html[data-workspace=guided] #app>header>.brand{grid-area:identity;min-width:0;gap:4px;max-width:100%}
html[data-workspace=guided] .house-brand{margin-right:8px;flex-shrink:0;font-size:14px}
html[data-workspace=guided] .house-brand img{width:25px;height:25px}
html[data-workspace=guided] .organizer-library-identity{min-width:0;max-width:100%}
html[data-workspace=guided] .library-switch{max-width:135px;width:100%;min-width:0;font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:6px 2px}
html[data-workspace=guided] #app>header>.search{grid-area:search;min-width:0;width:100%;max-width:none;order:initial}
html[data-workspace=guided] #app>header>.search input{min-width:0;height:42px}
html[data-workspace=guided] #app>header>.head-actions{grid-area:nav;display:flex;gap:6px;margin:0;overflow:visible;padding:0;align-items:center}
html[data-workspace=guided] #app>header>.workspace-add-trigger{grid-area:add;min-height:40px}
html[data-workspace=guided] :is(.workspace-nav,.workspace-tool).pixel-icon-only{font-size:13px!important;line-height:1.5!important;display:inline-flex;align-items:center;justify-content:center;gap:6px;overflow:visible;width:auto;min-width:0;height:auto;min-height:38px;padding:7px 9px!important;border-width:4px;background-image:none;border-image-source:var(--house-secondary-image);border-image-slice:140 fill;border-image-width:4px;white-space:nowrap}
html[data-workspace=guided] .workspace-nav::before{width:18px;height:18px;flex-shrink:0}
html[data-workspace=guided] #organizeBtn #organizerMiniStatus{display:none}
html[data-workspace=guided] #organizeBtn{margin:0;min-height:38px;padding:7px 9px}
html[data-workspace=guided] :is(.workspace-nav,.workspace-add-trigger)[aria-expanded=true]{background-color:var(--accent-soft);color:var(--accent);box-shadow:2px 2px 0 #b7838b}
html[data-workspace=guided] .workspace-popover{position:fixed;z-index:32;right:18px;top:calc(var(--workspace-header-height,82px) + 8px);width:310px;max-width:calc(100vw - 28px);max-height:calc(100dvh - var(--workspace-header-height,82px) - 24px);overflow:auto;padding:16px;background:var(--panel);border:2px solid var(--line);border-radius:4px;box-shadow:var(--shadow)}
html[data-workspace=guided] .workspace-popover h2{font-size:15px;line-height:1.5;letter-spacing:0}
html[data-workspace=guided] .workspace-popover .dialog-title{margin:0 0 12px;gap:12px}
html[data-workspace=guided] .workspace-tool-list{display:grid;gap:7px}
html[data-workspace=guided] .workspace-tool-list>.btn{width:100%;min-height:40px;text-align:left;justify-content:flex-start;font-size:13px;white-space:normal;overflow-wrap:anywhere}
html[data-workspace=guided] .workspace-popover .setting-row{display:block;margin:16px 0 3px}
html[data-workspace=guided] .workspace-popover .setting-row>span{display:block;margin-bottom:7px}
html[data-workspace=guided] .workspace-popover select{width:100%;max-width:100%}
html[data-workspace=guided] .workspace-menu-note{font-size:12px;line-height:1.75;color:var(--muted);margin:10px 0 0}
html[data-workspace=guided] #settings{width:330px;max-width:calc(100vw - 28px);max-height:calc(100% - 24px);overflow:auto;right:16px;top:12px;padding:18px}
html[data-workspace=guided] #settings .maintenance-links{display:grid;gap:8px;margin-bottom:12px}
html[data-workspace=guided] #settings .maintenance-links>.btn{text-align:left;width:100%;white-space:normal;overflow-wrap:anywhere}
html[data-workspace=guided] #settings>details{border-top:1px solid var(--line);padding-top:12px;margin-top:14px}
html[data-workspace=guided] #settings>details>summary{font-size:12px;padding:3px 0}
html[data-workspace=guided] :is(.floating-panel,.companion-scroll,dialog){min-width:0;overscroll-behavior:contain;overflow-x:hidden}
html[data-workspace=guided] :is(.companion-scroll,dialog) :is(input,select,textarea){max-width:100%;min-width:0;box-sizing:border-box}
html[data-workspace=guided] :is(.form-note,.connection-state,.persona-growth-status,.organizer-api-status,.connect-target,.portability-notice){overflow-wrap:anywhere;word-break:normal}
html[data-workspace=guided] #connectionWizardDialog{width:min(620px,calc(100vw - 28px));max-height:calc(100dvh - 28px);overflow:auto;padding:20px 22px 0}
html[data-workspace=guided] #connectionWizardDialog .wizard-heading{margin-bottom:10px}
html[data-workspace=guided] #connectionWizardDialog .wizard-progress{margin:10px 0 14px;font-size:12px}
html[data-workspace=guided] #connectionWizardDialog .wizard-choice{padding:11px 13px;min-height:0;margin:8px 0}
html[data-workspace=guided] #connectionWizardDialog .wizard-choice strong{font-size:14px}
html[data-workspace=guided] #connectionWizardDialog .wizard-choice small{font-size:12px;line-height:1.65;margin-top:3px}
html[data-workspace=guided] #connectionWizardDialog .wizard-screen>h3{font-size:14px;margin:8px 0 10px}
html[data-workspace=guided] #connectionWizardDialog .wizard-foot{position:sticky;bottom:0;z-index:2;background:var(--paper);border-top:1px solid var(--line);padding:13px 0 16px;margin-top:16px;isolation:isolate}
html[data-workspace=guided] #connectionWizardDialog .wizard-foot .btn{min-height:42px}
html[data-workspace=guided] #connectionsPanel>.form-note{display:none}
html[data-workspace=guided] .connect-target{padding:12px 14px;margin-bottom:10px}
html[data-workspace=guided] .connect-primary{margin:10px 0 14px}
html[data-workspace=guided] #personaApiRecommendation,html[data-workspace=guided] #organizerApiRecommendation{display:none}
html[data-workspace=guided] #organizerApiPurpose{font-size:12px;line-height:1.75}
html[data-workspace=guided] #saveOrganizerSettings{display:block;width:100%;margin-top:16px;min-height:42px}
html[data-workspace=guided] #saveAndEnableOrganizer{display:none!important}
html[data-workspace=guided] .workspace-save-help{font-size:12px;line-height:1.75;color:var(--muted);margin:9px 0 0}
html[data-workspace=guided] #organizerPanel .memory-more-actions{display:flex;flex-wrap:wrap;gap:8px}
html[data-workspace=guided] #organizerPanel .companion-scroll{scroll-padding-top:15px}
html[data-workspace=guided] #organizerPanel #organizerSettings{margin-bottom:18px}
html[data-workspace=guided] #detail .detail-actions{margin-bottom:12px;gap:8px}
html[data-workspace=guided] #detail .detail-actions>.btn{min-height:38px;font-size:12px;padding:8px 11px}
html[data-workspace=guided] #detail :is(.workspace-detail-advanced,.workspace-detail-danger){border-top:1px solid var(--line);padding-top:13px;margin:14px 0}
html[data-workspace=guided] #detail :is(.workspace-detail-advanced,.workspace-detail-danger)>summary{font-size:12px;line-height:1.7}
html[data-workspace=guided] #detail .workspace-detail-danger>summary,html[data-workspace=guided] #detail .workspace-detail-danger .btn{color:var(--danger)}
html[data-workspace=guided] .workspace-detail-note{font-size:12px;line-height:1.8;color:var(--muted);margin:10px 0}
@media(max-width:1160px){html[data-workspace=guided] #app>header{grid-template-columns:minmax(130px,185px) minmax(130px,1fr) auto auto;gap:9px;padding:12px 14px}html[data-workspace=guided] .house-brand{font-size:0;margin-right:6px}html[data-workspace=guided] .library-switch{max-width:140px}html[data-workspace=guided] #app>header>.head-actions{gap:4px}html[data-workspace=guided] .workspace-nav::before{display:none}html[data-workspace=guided] .workspace-nav.pixel-icon-only{padding:7px 8px!important}}
@media(max-width:820px){html[data-workspace=guided] #app>header{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:'identity add' 'search search' 'nav nav';gap:10px 12px;padding:12px 14px;min-height:0}html[data-workspace=guided] #app>header>.brand{width:100%;max-width:100%}html[data-workspace=guided] .house-brand{font-size:14px;display:inline-flex;margin-right:9px}html[data-workspace=guided] .library-switch{max-width:210px}html[data-workspace=guided] #app>header>.head-actions{width:100%;display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px}html[data-workspace=guided] .head-actions>.btn,html[data-workspace=guided] .head-actions>.workspace-nav.pixel-icon-only{width:100%;min-width:0;padding:6px 4px!important;justify-content:center;font-size:13px!important}html[data-workspace=guided] #app>header>.search{width:100%;margin:0}html[data-workspace=guided] #app>header>.search input{height:39px;min-height:39px}html[data-workspace=guided] .workspace-popover{right:14px}html[data-workspace=guided] #organizerPanel{width:calc(100% - 20px);max-width:440px}html[data-workspace=guided] #connectionWizardDialog{padding:16px 16px 0}html[data-workspace=guided] #connectionWizardDialog .wizard-heading h2{font-size:18px}html[data-workspace=guided] #connectionWizardDialog .wizard-progress{font-size:11px;gap:6px}}
@media(max-width:390px){html[data-workspace=guided] .house-brand{font-size:0;margin-right:7px}html[data-workspace=guided] .library-switch{max-width:160px}html[data-workspace=guided] #app>header{padding:10px 12px;gap:8px}html[data-workspace=guided] #app>header>.head-actions{gap:4px}html[data-workspace=guided] .workspace-add-trigger{font-size:12px;padding:7px 9px!important}}
`;
  document.head.append(style);

  const descriptors = [];
  function label(button, text, cls = 'workspace-nav') {
    if (!button) return;
    button.classList.add('btn', cls);
    button.classList.remove('icon-btn');
    descriptors.push({button, text});
  }
  function refreshLabels() {
    for (const {button, text} of descriptors) {
      const value = typeof text === 'function' ? text(button) : text;
      if (button.id === 'organizeBtn') {
        for (const node of [...button.childNodes]) if (node.nodeType === 3) node.remove();
        let title = button.querySelector('.workspace-button-label');
        if (!title) { title = make('span', 'workspace-button-label'); button.prepend(title); }
        if (title.textContent !== value) title.textContent = value;
      } else if (button.textContent !== value) button.textContent = value;
    }
  }
  for (const [id, name] of [['menuBtn','记忆'], ['companionBtn','连接'], ['organizeBtn','整理'], ['settingsBtn','更多']]) {
    const button = by(id);
    if (!button) continue;
    label(button, name);
    button.setAttribute('aria-label', name);
    button.setAttribute('data-hint-title', name);
    button.setAttribute('data-hint-description', {menuBtn:'浏览当前记忆库，或按话题找回相关记忆。',companionBtn:'管理已授权的窗口、人格和真实存档记录。',organizeBtn:'查看整理进度、候选和本库模型设置。',settingsBtn:'管理备份、记忆规律、更新和高级选项。'}[id]);
  }

  const popovers = [];
  function shell(id, title, triggerId, triggerLabel) {
    const trigger = make('button', 'btn workspace-nav', triggerLabel);
    trigger.id = triggerId; trigger.type = 'button';
    trigger.setAttribute('aria-expanded', 'false'); trigger.setAttribute('aria-controls', id);
    const panel = make('section', 'workspace-popover'); panel.id = id; panel.hidden = true;
    panel.setAttribute('aria-label', title);
    const heading = make('div','dialog-title'), name = make('h2','',title), close = make('button','btn','关闭');
    close.type='button'; close.setAttribute('aria-label','关闭'+title);
    const list = make('div','workspace-tool-list');
    heading.append(name,close); panel.append(heading,list); document.body.append(panel);
    const item={trigger,panel,list}; popovers.push(item);
    trigger.onclick=()=>{
      const open=panel.hidden; closeMenus(false);
      if(open){
        if(typeof PANELS!=='undefined'&&typeof setPanelOpen==='function')for(const key of Object.keys(PANELS))setPanelOpen(key,false,{restore:false});
        panel.hidden=false; trigger.setAttribute('aria-expanded','true');
        const first=panel.querySelector('button:not([disabled])'); first?.focus();
      }
    };
    close.onclick=()=>closeMenus(true);
    return item;
  }
  function closeMenus(restore) {
    for(const item of popovers){if(!item.panel.hidden){item.panel.hidden=true;item.trigger.setAttribute('aria-expanded','false');if(restore)item.trigger.focus();}}
  }
  const display=shell('workspaceDisplayMenu','显示与浏览','workspaceDisplayButton','显示');
  const add=shell('workspaceAddMenu','添加或导入记忆','workspaceAddButton','添加');
  const dialogReturns=new Map();
  add.trigger.classList.add('primary','workspace-add-trigger'); add.trigger.classList.remove('workspace-nav');
  add.trigger.setAttribute('aria-label','添加或导入记忆');
  const stateLabel = button => button.getAttribute('aria-label') || '切换显示';
  for(const [id,name]of [['viewBtn',stateLabel],['filterBtn','筛选记忆'],['timeBtn','淡化预览（只读）'],['detailBtn','当前记忆详情'],['layoutBtn','重新排列画面'],['pauseBtn',stateLabel],['themeBtn',stateLabel],['fullscreenBtn',stateLabel]]){
    const button=by(id);if(!button)continue;label(button,name,'workspace-tool');display.list.append(button);
    if(['filterBtn','timeBtn','detailBtn'].includes(id))button.addEventListener('click',()=>closeMenus(false));
  }
  const labelRow=by('labels')?.closest('.setting-row');if(labelRow)display.panel.append(labelRow);
  if(by('timeBtn')){by('timeBtn').setAttribute('aria-label','淡化预览（只读）');by('timeBtn').dataset.hintTitle='淡化预览 · 只读';by('timeBtn').dataset.hintDescription='预览未来记忆强度如何淡化，不是经历时间线，不会改写或删除记忆。';}
  const timeTitle=by('timePanel')?.querySelector('.timeline-title strong');if(timeTitle)timeTitle.textContent='淡化预览 · 只读';
  display.panel.append(make('p','workspace-menu-note','这些操作只改变浏览方式；画面布局和筛选不会删除记忆。'));
  for(const [id,name]of [['addBtn','手动添加一条记忆'],['importBtn','导入笔记文件'],['dialogueImportBtn','导入聊天记录'],['importMemoryShareBtn','导入完整存档为新库']]){
    const button=by(id);if(!button)continue;label(button,name,'workspace-tool');add.list.append(button);
    const dialogId={addBtn:'addDialog',importBtn:'importDialog',dialogueImportBtn:'dialogueImportDialog',importMemoryShareBtn:'memoryShareImportDialog'}[id];
    button.addEventListener('click',()=>{if(!add.panel.hidden)dialogReturns.set(dialogId,add.trigger);},true);
    button.addEventListener('click',()=>closeMenus(false));
  }
  add.panel.append(make('p','workspace-menu-note','每种导入都会先展示目标与预览；完整存档会创建独立新库。'));
  for(const id of ['menuBtn','companionBtn','organizeBtn'])if(by(id))actions.append(by(id));
  actions.append(display.trigger,by('settingsBtn'));header.append(add.trigger);
  actions.setAttribute('aria-label','主要功能');actions.setAttribute('role','navigation');

  const settings=by('settings');settings.querySelector('.setting-title strong').textContent='更多';
  for(const id of ['addDialog','importDialog','dialogueImportDialog','memoryShareImportDialog'])by(id)?.addEventListener('close',()=>{
    const trigger=dialogReturns.get(id);dialogReturns.delete(id);
    if(trigger&&!document.querySelector('dialog[open]'))trigger.focus();
  });
  if(typeof setPanelOpen==='function'){
    const previousSetPanelOpen=setPanelOpen;
    setPanelOpen=function(id,open,options={}){
      const wasOpen=by(id)?.hidden===false;previousSetPanelOpen(id,open,options);
      if(!open&&wasOpen&&options.restore!==false&&['filterPanel','timePanel','inspector'].includes(id)&&display.panel.hidden)display.trigger.focus();
    };
  }
  const advanced=make('details');advanced.id='workspaceRecallAdvanced';advanced.append(make('summary','','高级召回设置'));
  for(const id of ['steps','damping','learn']){const row=by(id)?.closest('.setting-row');if(row)advanced.append(row);}
  if(by('learningNote'))advanced.append(by('learningNote'));settings.append(advanced);
  const about=make('details');about.id='workspaceGraphAbout';about.append(make('summary','','图谱与资源说明'));
  for(const note of [...settings.querySelectorAll(':scope>.settings-note')])about.append(note);
  if(about.children.length>1)settings.append(about);
  const apiBadge=by('organizerLibraryApiStatus');
  if(apiBadge){const tools=settings.querySelector('.maintenance-links');apiBadge.classList.add('btn');apiBadge.style.width='100%';tools?.append(apiBadge);}

  const start=by('startConnectionWizard');if(start)start.textContent='连接一个聊天窗口';
  const heading=by('connectionWizardDialog')?.querySelector('.wizard-screen h3');if(heading)heading.textContent='你在哪个程序中聊天？';
  const purpose=by('organizerApiPurpose');if(purpose)purpose.textContent='整理模型把已保存的原文归纳为长期记忆与人格资料。上下文与输出默认使用模型最高能力；费用由所选服务计收。保存原文、检索、导出和手动人格无需整理模型。';
  const save=by('saveOrganizerSettings');if(save){save.classList.add('primary');const help=make('p','workspace-save-help','勾选“启用自动整理”后保存，才会按本库设置开始处理；关闭后保存会停止后续自动整理。');help.id='workspaceOrganizerSaveHelp';save.after(help);}
  if(by('saveAndEnableOrganizer'))by('saveAndEnableOrganizer').hidden=true;
  for(const id of ['personaOrganizerSettings','personaApiRecommendationConfigure','organizerApiRecommendationConfigure','organizerLibraryApiStatus']){
    by(id)?.addEventListener('click',()=>{queueMicrotask(()=>{const panel=by('organizerPanel'),scroll=panel?.querySelector('.companion-scroll');if(panel?.hidden)return;if(scroll)scroll.scrollTop=0;const title=panel.querySelector('.inspector-top strong');if(title){title.tabIndex=-1;title.focus({preventScroll:true});}});});
  }
  const newMemoryAdvanced=make('details');newMemoryAdvanced.id='workspaceMemoryAdvanced';newMemoryAdvanced.append(make('summary','','更多信息（可选）'));
  for(const id of ['newImpact','newSession','newEventAt','newTags']){
    const control=by(id);if(!control)continue;const row=control.closest('.form-row');
    if(row&&row.parentElement===by('addForm'))newMemoryAdvanced.append(row);
    else {const label=by('addForm')?.querySelector('label[for='+id+']');if(label)newMemoryAdvanced.append(label);newMemoryAdvanced.append(control);}
  }
  if(by('newMemoryAdvancedNote'))newMemoryAdvanced.append(by('newMemoryAdvancedNote'));
  const important=by('newImportant')?.closest('label');if(important)important.before(newMemoryAdvanced);else by('addForm')?.querySelector('.dialog-actions')?.before(newMemoryAdvanced);
  function arrangeDetailActions(expanded={}) {
    const detail=by('detail'),row=detail?.querySelector('.detail-actions');
    if(!row||detail.querySelector('.workspace-detail-advanced'))return;
    const advanced=make('details','workspace-detail-advanced'),extra=make('div','detail-actions');
    advanced.append(make('summary','','更多操作'),make('p','workspace-detail-note','纠正会保留原话与更正关系；直接编辑会覆盖此条内容。手动强化只调整记忆强度。'),extra);
    const danger=make('details','workspace-detail-danger'),dangerActions=make('div','detail-actions');
    danger.append(make('summary','','删除与隐私'),make('p','workspace-detail-note','暂不使用可以恢复。永久忘记会先展示原文与派生资料的影响范围，再由你确认。'),dangerActions);
    const lifecycle=detail.querySelector('.lifecycle-actions');
    for(const button of [...row.querySelectorAll('button'),...(lifecycle?.querySelectorAll('button')||[])]){
      const name=button.textContent.replace(/^[^\p{L}\p{N}]+/u,'').trim();
      if(/真正忘记|永久忘记/.test(name))dangerActions.append(button);
      else if(/纠正|暂不使用|恢复使用/.test(name))row.append(button);
      else {if(/编辑记忆/.test(name)){button.textContent='编辑原条目';button.dataset.hintDescription='直接覆盖这条内容；如需保留更正前后关系，请使用“纠正内容”。';}extra.append(button);}
    }
    if(lifecycle&&!lifecycle.children.length)lifecycle.remove();row.hidden=!row.children.length;
    row.after(advanced,danger);advanced.hidden=!extra.children.length;danger.hidden=!dangerActions.children.length;
    advanced.open=!!expanded.advanced;danger.open=!!expanded.danger;
  }
  if(typeof renderDetail==='function'){
    const previousRenderDetail=renderDetail,ownerKey=()=>typeof S==='undefined'?'':String(S.libraryId)+':'+String(S.libraryEpoch)+':'+String(S.selected);let detailOwner=ownerKey();
    renderDetail=function(...args){
      const owner=ownerKey();
      const detail=by('detail'),expanded=detailOwner===owner?{advanced:detail?.querySelector('.workspace-detail-advanced')?.open,danger:detail?.querySelector('.workspace-detail-danger')?.open}:{};
      previousRenderDetail(...args);detailOwner=owner;arrangeDetailActions(expanded);
    };
    arrangeDetailActions();
  }
  // Tabs stay useful in context. Repeated top-level entries now live in one labelled menu.
  for(const node of [by('menuBtn'),by('companionBtn'),by('organizeBtn'),by('settingsBtn')])node?.addEventListener('click',()=>closeMenus(false));
  document.addEventListener('pointerdown',event=>{if(!popovers.some(p=>p.panel.contains(event.target)||p.trigger.contains(event.target)))closeMenus(false);});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&popovers.some(p=>!p.panel.hidden)){event.preventDefault();event.stopPropagation();closeMenus(true);}},true);
  function measure(){document.documentElement.style.setProperty('--workspace-header-height',Math.ceil(header.getBoundingClientRect().height)+'px');}
  window.addEventListener('resize',()=>{measure();closeMenus(popovers.some(p=>p.panel.contains(document.activeElement)));});
  const observer=new MutationObserver(()=>{refreshLabels();measure();});
  observer.observe(header,{subtree:true,childList:true,attributes:true,attributeFilter:['aria-label']});
  observer.observe(display.list,{subtree:true,childList:true,attributes:true,attributeFilter:['aria-label']});
  refreshLabels();measure();
  window.LoveHouseWorkspace={closeMenus,refresh:refreshLabels};
})();
