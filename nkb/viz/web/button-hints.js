/* Love House button help. Self-contained; never reads form values or credentials. */
(() => {
  'use strict';
  const SELECTOR = 'button,[role="button"],[role="tab"],[role="checkbox"],summary,[data-hint-title],[data-hint-description]';
  const HOVER_DELAY = 260;
  const TIP_ID = 'nkb-button-hint';
  const nativeTitles = new WeakMap();
  const hint = (title, description, shortcut) => ({title, description, shortcut});
  const MAP = {
    libraryMenuBtn: hint('切换记忆库', '选择正在查看的 Agent 记忆库；已有连接的保存位置不会随之改变。'),
    startConnectionWizard: hint('连接聊天窗口', '选择聊天软件、记忆库，然后按向导完成连接。'),
    connectionWizardBack: hint('返回上一步', '回到上一个连接步骤，暂不提交当前设置。'),
    connectionWizardNext: hint('继续连接设置', '确认本页选择后继续；最后一步会生成接入信息或安装存档插件。'),
    connectHarnessNow: hint('连接 Harness', '先备份原配置，再安装自动存档插件；收到完整对话后确认存档。'),
    verifyChatConnection: hint('检查连接状态', '检查是否已经收到完整对话；不会发送聊天消息或调用付费模型。'),
    fixConnectionModel: hint('修改模型与密钥', '更新聊天模型的厂商设置，不更换 Agent 的记忆库。'),
    openConnectionLibrary: hint('打开保存记忆的库', '切换到这条连接实际保存记忆的位置，不改变连接归属。'),
    companionBtn: hint('连接对话', '把聊天客户端接入长期记忆，也可以管理人格和查看存档。', 'C'),
    searchBtn: hint('关联召回', '按输入内容查找相关记忆，并查看它们的关联路径。', 'Enter'),
    addBtn: hint('添加记忆', '手动保存一条希望这个 Agent 记住的信息。'),
    importBtn: hint('导入笔记', '选择本地文字文件，预览后把内容存入当前记忆库。'),
    menuBtn: hint('节点列表', '按名称浏览和选择记忆，不必在星云里逐个寻找。', 'N'),
    filterBtn: hint('筛选记忆', '按记忆类型和状态筛选画面中的节点。', 'F'),
    timeBtn: hint('时间预览', '查看记忆随时间淡化的样子；预览不会改写或删除记忆。', 'T'),
    detailBtn: hint('节点详情', '查看选中记忆的完整内容、来源和关联节点。', 'I'),
    settingsBtn: hint('设置', '调整图谱显示、记忆整理，以及备份和恢复。', 'S'),
    viewBtn: hint('切换视图', '在动态神经星云和便于分析的平面图之间切换。'),
    layoutBtn: hint('整理布局', '重新摆放画面中的节点；记忆内容和保存位置不变。'),
    pauseBtn: hint('暂停或继续动效', '暂停星云运动，便于查看节点；后台存档仍按连接设置工作。'),
    themeBtn: hint('切换明暗主题', '在黑色和白色界面之间切换，不影响记忆内容。'),
    fullscreenBtn: hint('切换全屏', '展开画面便于观察星云，再次点击退出全屏。'),
    zoomIn: hint('放大图谱', '拉近星云，查看附近节点和连接。', '+'),
    zoomOut: hint('缩小图谱', '拉远画面，查看更多节点与整体结构。', '−'),
    fitBtn: hint('显示全图', '让当前可见的节点完整显示在画面中。', '0'),
    minimapBtn: hint('缩略导航', '打开小地图，查看目前所在位置并快速移动。', 'M'),
    clearFocus: hint('返回全图', '取消邻居聚焦和召回高亮，重新查看当前图谱。'),
    allTab: hint('所有节点', '浏览当前筛选条件下的全部记忆节点。'),
    recallTab: hint('召回路径', '查看刚才关联召回命中的记忆与连接路径。'),
    resetFilters: hint('重置筛选', '重新显示所有类型和状态的记忆。'),
    previewReset: hint('回到此刻', '退出未来时间预览，恢复当前的真实记忆状态。'),
    emptyAction: hint('开始连接', '选择聊天方式和保存位置，接入之后开始积累真实记忆。'),
    previewNebula: hint('预览星云', '打开独立的只读示例；示例不会成为你的 Agent 记忆。'),
    organizeBtn: hint('记忆整理', '让指定模型整理已经保存的原文，并查看任务与候选记忆。'),
    organizerActivityBtn: hint('查看整理任务', '查看待整理的记录、模型处理结果和需要确认的候选。'),
    backupBtn: hint('备份与恢复', '备份当前库；恢复会建立新库，不覆盖原 Agent。'),
    newLibraryBtn: hint('新建记忆库', '为另一个 Agent 建立独立的空白记忆和人格。'),
    connectTab: hint('连接', '查看哪些聊天正在保存记忆，以及各自保存到哪个库。'),
    personaTab: hint('人格', '导入明确的人格设定，或查看有对话证据的风格变化。'),
    activityTab: hint('存档记录', '检查实际收到的对话和工具事件，确认记忆是否成功保存。'),
    detectHarnessBtn: hint('检测 Harness', '在本机寻找受支持的 DeepSeek Harness，暂不改动它的配置。'),
    createConnectionBtn: hint('创建连接', '为选定的记忆库生成独立接入入口，随后完成客户端配置。'),
    copyConnectionConfig: hint('复制接入配置', '复制当前连接需要的设置；完整配置可能包含本地连接凭证。'),
    copyApiBase: hint('复制本地地址', '把这个地址填到聊天客户端的 API 基础地址中。'),
    copyClientKey: hint('复制本地连接凭证', '把凭证填入聊天客户端，厂商密钥继续由爱之屋安全保管。'),
    planConnectionBtn: hint('预览接入改动', '先查看将如何接入 Harness；这一步不会修改宿主。'),
    applyConnectionBtn: hint('应用接入配置', '备份后只更新爱之屋自己的插件配置，等待首轮真实存档。'),
    saveProvider: hint('保存模型设置', '更新此连接的上游模型；密钥留空会保留已经保存的值。'),
    savePersonaImport: hint('保存人格', '把你明确填写的设定保存为当前 Agent 的人格版本。'),
    reloadPersonaBtn: hint('重新读取人格', '放弃当前未保存的编辑，读取已保存的人格版本。'),
    refreshActivityBtn: hint('刷新存档', '重新检查当前库实际收到的记录，不会调用聊天模型。'),
    previewOrganizer: hint('预览整理范围', '只查看本批原文数量和来源，不调用整理模型。'),
    runOrganizer: hint('立即整理', '将待处理记录交给已启用的整理模型，仍遵守用量预算。'),
    saveOrganizerSettings: hint('保存整理设置', '保存整理模型、处理节奏和预算，不会补写虚构记忆。'),
    createBackup: hint('创建备份', '保存当前库及其原始档案，不包含模型密钥或活动连接。'),
    confirmRestoreBackup: hint('恢复为新库', '从这份备份创建独立的新库，原记忆库与连接保持原样。'),
    confirmCorrectMemory: hint('保存纠正', '新建正确内容并停用旧记忆，保留原话便于追溯。'),
    confirmForgetMemory: hint('真正忘记', '按已确认的范围清理原文、派生记忆和相关旧备份。'),
    confirmDisconnect: hint('断开连接', '让此连接停止接收并使旧凭证失效，已有记忆仍然保留。'),
    previewImport: hint('预览导入', '先检查文件将产生哪些记忆，暂不写入当前库。'),
    confirmImport: hint('确认导入', '将预览中的新内容写入当前记忆库。'),
    saveAdd: hint('保存记忆', '把填写的内容保存到当前记忆库。'),
    confirmLibrary: hint('创建空白库', '创建新的 Agent 记忆身份，不复制示例或其他库的内容。')
  };
  const ACTIONS = {
    config: hint('继续连接', '打开这条连接的具体接入步骤和保存位置。'),
    pause: hint('暂停或恢复接收', '控制是否接收新的对话，已经保存的记忆会保留。'),
    disconnect: hint('断开连接', '停用此入口和凭证，已有记忆不会随之删除。'),
    provider: hint('修改模型', '更换此连接使用的厂商、模型或密钥，不更换 Agent 记忆库。')
  };
  const TEXT = {
    '纠正内容': hint('纠正记忆', '保存新的正确内容，并保留、停用旧原话。'),
    '暂不使用': hint('暂不使用', '保留这条记忆，但停止召回；以后可以恢复。'),
    '恢复使用': hint('恢复使用', '让这条保留的记忆重新参与召回。'),
    '真正忘记': MAP.confirmForgetMemory,
    '聚焦邻居': hint('聚焦邻居', '只查看这条记忆附近的关联节点。'),
    '定位': hint('定位节点', '把这条记忆移到画面中央。'),
    '强化记忆': hint('强化记忆', '明确提高这条记忆的强度，并保存新的强化状态。'),
    '原始记录': hint('查看原始记录', '查看这条记忆实际收到的对话或工具记录。'),
    '预览恢复': hint('预览恢复', '只查看备份信息，确认后才会建立新的记忆库。'),
    '重试整理': hint('重试整理', '重新排队这个批次，不会把失败任务当作已完成。'),
    '查看整理来源': hint('查看整理来源', '打开这个批次的实际原文，不调用模型。'),
    '确认采用': hint('采用候选', '确认候选有可靠来源后，将它保存为记忆。'),
    '拒绝': hint('拒绝候选', '不采用这条候选，原始对话仍然保留。')
  };
  const DISABLED = {
    detailBtn: '先从图谱或节点列表中选择一条记忆。',
    copyClientKey: '连接准备完成后才可复制；若厂商密钥未配置，请先在模型设置中填写。',
    verifyChatConnection: '先选择或创建一条连接，再检查存档状态。',
    applyConnectionBtn: '先生成并检查接入计划，才可以应用。',
    runOrganizer: '先启用整理模型并配置可用凭证；处理中的任务完成后可继续。',
    confirmForgetMemory: '先查看影响范围，并勾选确认后才可以忘记。',
    confirmImport: '先选择文件并完成导入预览。'
  };
  function clean(value, limit = 180) {
    return typeof value === 'string' ? value.replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, limit) : '';
  }
  function textOf(control) {
    // Node buttons can contain the original memory; use its existing short label only.
    if (control.classList?.contains('node-row') || control.classList?.contains('neighbor-row')) {
      return clean(control.getAttribute('aria-label') || control.querySelector?.('.row-label')?.textContent, 80);
    }
    return clean(control.getAttribute('aria-label') || control.textContent, 80);
  }
  function readHint(control) {
    const explicitTitle = clean(control.getAttribute('data-hint-title'), 80);
    const explicitDescription = clean(control.getAttribute('data-hint-description'));
    const label = textOf(control);
    const titleAttr = nativeTitles.get(control) ?? clean(control.getAttribute('title'));
    let base = MAP[control.id] || ACTIONS[control.getAttribute('data-connection-action')];
    if (!base && control.classList?.contains('wizard-choice')) base = control.getAttribute('data-host') === 'harness' ? hint('使用 DeepSeek Harness', '安装宿主自动存档插件，再回到想连接的窗口发消息。') : hint('使用 API 聊天软件', '生成本地地址和连接密钥，填回原来的聊天客户端。');
    if (!base && control.classList?.contains('library-choice')) base = MAP.libraryMenuBtn;
    if (!base && control.classList?.contains('node-row')) base = hint(label || '查看记忆', '打开这条记忆的完整内容、来源和关联。');
    if (!base && control.classList?.contains('neighbor-row')) base = hint(label || '关联记忆', '打开这条关联记忆的完整信息。');
    if (!base && control.getAttribute('data-retry-job')) base = TEXT['重试整理'];
    if (!base) base = Object.entries(TEXT).find(([word]) => label.replace(/^[^\p{L}\p{N}]+/u, '').startsWith(word))?.[1];
    if (!base && /^close|^cancel/i.test(control.id)) base = hint(label || '关闭', '收起当前窗口；没有保存的内容不会自动提交。', 'Esc');
    if (!base && control.tagName === 'SUMMARY') base = hint(label || '更多选项', control.parentElement?.open ? '收起这些选项，保留已经填写的内容。' : '展开更多选项和详细信息。');
    const fallbackTitle = label || clean(titleAttr, 80);
    if (!base && !explicitTitle && !fallbackTitle) return null;
    base ||= hint(fallbackTitle, control.getAttribute('role') === 'tab' ? '切换到这个页面，查看对应的信息和操作。' : '点击执行此操作。');
    const title = explicitTitle || (['pauseBtn', 'themeBtn', 'fullscreenBtn', 'connectionWizardNext'].includes(control.id) ? label : '') || base.title;
    const description = explicitDescription || base.description;
    const shortcut = clean(control.getAttribute('data-hint-shortcut'), 30) || base.shortcut || '';
    const disabled = control.disabled === true || control.getAttribute('aria-disabled') === 'true';
    const nativeReason = clean(titleAttr);
    const reason = disabled ? clean(control.getAttribute('data-hint-disabled')) ||
      (nativeReason && !/^(添加|导入|暂停|继续|布局|全屏|主题|记忆库|节点|筛选|详情|设置)(?:\s*[·(]|$)/.test(nativeReason) && nativeReason !== label ? nativeReason : DISABLED[control.id]) || '当前状态暂不可用，完成前一步后再试。' : '';
    return {title: clean(title, 80), description, shortcut, disabled, reason};
  }
  function init() {
    if (document.getElementById(TIP_ID)) return;
    const style = document.createElement('style');
    style.textContent = `
#nkb-button-hint{position:fixed;z-index:2147483647;max-width:min(300px,calc(100vw - 20px));padding:11px 13px;border:1px solid var(--line,#414141);border-radius:11px;background:var(--paper,#161616);color:var(--ink,#f3f3f3);box-shadow:0 9px 28px #0004;pointer-events:none;white-space:normal;font:12px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;text-align:left;overflow-wrap:anywhere}
#nkb-button-hint[hidden]{display:none!important}#nkb-button-hint strong{display:block;font-size:13px;font-weight:600}#nkb-button-hint p{margin:4px 0 0;color:var(--muted,#bcbcbc)}#nkb-button-hint .hint-reason{color:var(--ink,#f3f3f3);padding-top:5px;border-top:1px solid var(--line,#414141);margin-top:7px}#nkb-button-hint kbd{display:inline-block;font:11px/1.4 ui-monospace,Menlo,monospace;margin-top:7px;padding:2px 5px;border:1px solid var(--line,#414141);border-radius:4px;color:var(--muted,#bcbcbc)}
`;
    document.head.append(style);
    const tip = document.createElement('div');
    tip.id = TIP_ID; tip.hidden = true; tip.setAttribute('role', 'tooltip');
    document.body.append(tip);
    let current = null, timer = null, described = null, keyboard = true;
    function rememberTitle(control) {
      if (control.hasAttribute('title')) {
        nativeTitles.set(control, clean(control.getAttribute('title')));
        control.removeAttribute('title'); // Prevent a second, delayed native tooltip.
      }
    }
    function prepare(root) {
      if (root.nodeType !== 1 && root !== document) return;
      if (root.matches?.(SELECTOR)) rememberTitle(root);
      for (const control of root.querySelectorAll?.(SELECTOR) || []) rememberTitle(control);
    }
    function dropDescription() {
      if (!described) return;
      const ids = (described.getAttribute('aria-describedby') || '').split(/\s+/).filter(id => id && id !== TIP_ID);
      if (ids.length) described.setAttribute('aria-describedby', ids.join(' ')); else described.removeAttribute('aria-describedby');
      described = null;
    }
    function hide() {
      if (timer !== null) clearTimeout(timer);
      timer = null; current = null; tip.hidden = true; dropDescription();
    }
    function position(control) {
      const rect = control.getBoundingClientRect(), box = tip.getBoundingClientRect();
      const width = window.innerWidth || document.documentElement.clientWidth;
      const height = window.innerHeight || document.documentElement.clientHeight;
      let top = rect.bottom + 9;
      if (top + box.height > height - 10) top = rect.top - box.height - 9;
      tip.style.left = Math.round(Math.max(10, Math.min(width - box.width - 10, rect.left + rect.width / 2 - box.width / 2))) + 'px';
      tip.style.top = Math.round(Math.max(10, Math.min(height - box.height - 10, top))) + 'px';
    }
    function show(control) {
      if (!control.isConnected || control.closest('[hidden],[inert]')) return hide();
      const rect = control.getBoundingClientRect();
      if (!rect.width || !rect.height) return hide();
      const info = readHint(control);
      if (!info) return hide();
      tip.replaceChildren();
      const title = document.createElement('strong'); title.textContent = info.title; tip.append(title);
      const description = document.createElement('p'); description.textContent = info.description; tip.append(description);
      if (info.reason) {const reason = document.createElement('p'); reason.className = 'hint-reason'; reason.textContent = info.reason; tip.append(reason);}
      if (info.shortcut) {const key = document.createElement('kbd'); key.textContent = '快捷键 ' + info.shortcut; tip.append(key);}
      const mount = control.closest('dialog[open]') || document.body;
      if (tip.parentElement !== mount) mount.append(tip); // The native dialog top layer must own its tooltip.
      tip.hidden = false; position(control); dropDescription();
      const ids = (control.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
      if (!ids.includes(TIP_ID)) ids.push(TIP_ID);
      control.setAttribute('aria-describedby', ids.join(' ')); described = control;
    }
    function targetOf(event) {
      const element = Number.isFinite(event.clientX) && Number.isFinite(event.clientY) ?
        document.elementFromPoint?.(event.clientX, event.clientY) || event.target : event.target;
      return element?.closest?.(SELECTOR) || null;
    }
    function schedule(control, delay) {
      if (!control) return hide();
      if (current === control) return;
      hide(); rememberTitle(control); current = control;
      timer = setTimeout(() => {timer = null; if (current === control) show(control);}, delay);
    }
    document.addEventListener('pointermove', event => {if (event.pointerType !== 'touch') schedule(targetOf(event), HOVER_DELAY);}, true);
    document.addEventListener('pointerover', event => {if (event.pointerType !== 'touch') schedule(targetOf(event), HOVER_DELAY);}, true);
    document.addEventListener('pointerout', event => {if (!event.relatedTarget?.closest?.(SELECTOR) || event.relatedTarget.closest(SELECTOR) !== current) hide();}, true);
    document.addEventListener('focusin', event => {if (keyboard) schedule(event.target?.closest?.(SELECTOR), 0); else hide();}, true);
    document.addEventListener('focusout', hide, true);
    document.addEventListener('pointerdown', () => {keyboard = false; hide();}, true);
    document.addEventListener('click', hide, true);
    document.addEventListener('keydown', event => {keyboard = true; if (event.key === 'Escape') {if (!tip.hidden || timer !== null) {hide(); event.preventDefault(); event.stopPropagation();}} else schedule(document.activeElement?.closest?.(SELECTOR), 0);}, true);
    document.addEventListener('scroll', hide, true);
    window.addEventListener('resize', hide);
    window.addEventListener('blur', hide);
    document.addEventListener('visibilitychange', () => {if (document.hidden) hide();});
    prepare(document);
    if (typeof MutationObserver !== 'undefined') new MutationObserver(records => {
      let refresh = false;
      for (const record of records) {
        if (record.target === tip || tip.contains(record.target)) continue;
        if (record.type === 'childList') {
          for (const node of record.addedNodes) if (node !== tip) prepare(node);
          if (current && (record.target === current || current.contains(record.target))) refresh = true;
        } else if (record.target?.matches?.(SELECTOR)) {
          rememberTitle(record.target);
          if (record.target === current) refresh = true;
        }
      }
      if (current && (!current.isConnected || current.closest('[hidden],[inert]'))) hide();
      else if (refresh && current && !tip.hidden) show(current);
    }).observe(document.body, {childList:true, subtree:true, attributes:true,
      attributeFilter:['title','aria-label','aria-disabled','aria-pressed','aria-expanded','disabled','hidden','data-hint-title','data-hint-description','data-hint-shortcut','data-hint-disabled']});
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {readHint, MAP, HOVER_DELAY};
  if (typeof document !== 'undefined') {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true}); else init();
  }
})();
