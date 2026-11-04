import { createStore } from './store.js';
import { memoryServiceUrl } from './service-link.js';

const $ = (id) => document.getElementById(id);
const store = createStore();
const state = { ready: false, selected: null, libraries: [], memories: [], query: '', filter: 'all', view: 'memory', detail: null, editingLibrary: null };
const platform = () => String(window.LoveHousePlatform || (window.LoveHouseNative ? 'android' : 'web')).toLowerCase();
const nativeSaves = new Map();
let toastTimer, searchTimer, refreshSequence = 0, installPrompt = null;
const MAX_IMPORT = 32 * 1024 * 1024;

function replaceContents(element, ...children) {
  while (element.firstChild) element.removeChild(element.firstChild);
  for (const child of children) element.appendChild(child);
}

function readableError(error, fallback = '操作没有完成，请重试。') {
  return error && typeof error.message === 'string' && error.message.length < 400 ? error.message : fallback;
}

function toast(message, duration = 4500) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, duration);
}

function libraryName() {
  const library = state.libraries.find((entry) => entry.id === state.selected);
  return library ? library.name : '我的记忆库';
}

function timeValue(memory) {
  const value = memory.updatedAt != null ? memory.updatedAt : memory.createdAt != null ? memory.createdAt : ((memory.updated != null ? memory.updated : memory.created || 0) * 1000);
  const parsed = typeof value === 'string' ? Date.parse(value) : Number(value);
  return Number.isFinite(parsed) && parsed > 0 && parsed <= 8640000000000000 ? parsed : 0;
}

function dateLabel(memory, complete = false) {
  const timestamp = timeValue(memory);
  if (!timestamp) return '时间未记录';
  try { return new Intl.DateTimeFormat('zh-CN', complete ? { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' } : { month: '2-digit', day: '2-digit' }).format(timestamp); }
  catch { return new Date(timestamp).toISOString().slice(0, 10); }
}

function tagsOf(memory) {
  return Array.isArray(memory.tags) ? memory.tags.filter((tag) => typeof tag === 'string') : [];
}

function titleOf(memory) { return memory.title || String(memory.text || '').split('\n')[0].slice(0, 45) || '未命名的记忆'; }

function tagElement(label, status = false) {
  const span = document.createElement('span');
  span.className = status ? 'tag status-tag' : 'tag';
  span.textContent = label;
  return span;
}

function matchingMemories() {
  const needle = state.query.trim().normalize('NFKC').toLocaleLowerCase();
  return state.memories.filter((memory) => {
    if (state.filter === 'dialogue' && !memory.assistant) return false;
    if (state.filter === 'tagged' && !tagsOf(memory).length) return false;
    if (!needle) return true;
    return [memory.title, memory.text, memory.assistant, ...tagsOf(memory)].filter(Boolean).join('\n').normalize('NFKC').toLocaleLowerCase().includes(needle);
  }).sort((a, b) => timeValue(b) - timeValue(a));
}

function renderMemories() {
  const rows = matchingMemories();
  $('memoryCount').textContent = state.memories.length + ' 条';
  replaceContents($('memoryList'));
  $('memoryList').setAttribute('aria-busy', 'false');
  const fragment = document.createDocumentFragment();
  // Keep very large desktop imports responsive. The full set remains saved,
  // searchable and exportable; a narrower search can find any imported item.
  for (const memory of rows.slice(0, 250)) {
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'memory-card';
    card.dataset.memoryId = memory.id;
    const heading = document.createElement('h3');
    heading.textContent = titleOf(memory);
    const preview = document.createElement('p');
    preview.className = 'memory-preview';
    preview.textContent = String(memory.text || '').slice(0, 400);
    const footer = document.createElement('div');
    footer.className = 'memory-card-footer';
    const tags = document.createElement('div');
    tags.className = 'tag-list';
    for (const tag of tagsOf(memory).slice(0, 3)) tags.append(tagElement('#' + tag));
    if (memory.status === 'disabled') tags.append(tagElement('已停用', true));
    else if (memory.status === 'historical') tags.append(tagElement('历史记录', true));
    if (memory.assistant) tags.append(tagElement('有回复'));
    const time = document.createElement('time');
    time.textContent = dateLabel(memory);
    const timestamp = timeValue(memory);
    if (timestamp) time.dateTime = new Date(timestamp).toISOString();
    footer.append(tags, time);
    card.append(heading, preview, footer);
    card.addEventListener('click', () => showDetail(memory.id));
    fragment.append(card);
  }
  if (rows.length > 250) {
    const more = document.createElement('p');
    more.className = 'fine-print';
    more.textContent = '已显示最近 250 条。所有记忆都已保留，请输入关键词查找更多内容。';
    fragment.append(more);
  }
  $('memoryList').append(fragment);
  $('emptyState').hidden = rows.length > 0 || !state.ready;
  const filtered = Boolean(state.query || state.filter !== 'all');
  $('emptyTitle').textContent = filtered ? '没有找到这段记忆' : '这里还没有记忆';
  $('emptyText').textContent = filtered ? '试试另一个词，或切换回“全部”。' : '写下第一段原话，或从电脑导入一个记忆库。';
  $('emptyAdd').hidden = filtered;
  $('emptyImport').hidden = filtered;
}

async function refresh() {
  const sequence = ++refreshSequence;
  const libraries = await store.listLibraries();
  if (sequence !== refreshSequence) return;
  state.libraries = libraries;
  if (!libraries.some((library) => library.id === state.selected)) {
    const chosen = libraries.find((library) => library.selected) || libraries[0];
    state.selected = chosen ? chosen.id : null;
  }
  if (!state.selected) throw new Error('本地记忆库没有准备好，请重新打开。');
  const memories = await store.listMemories(state.selected, {});
  if (sequence !== refreshSequence) return;
  state.memories = memories;
  replaceContents($('librarySelect'), ...libraries.map((library) => {
    const option = document.createElement('option');
    option.value = library.id;
    const sameName = libraries.filter((other) => other.name === library.name).length > 1;
    option.textContent = library.name + (sameName ? ' · ' + String(library.id).slice(-6) : '');
    option.selected = library.id === state.selected;
    return option;
  }));
  $('exportLibraryName').textContent = libraryName();
  $('exportStatus').textContent = '';
  renderMemories();
  renderMap();
}

function showDialog(id) {
  const dialog = $(id);
  if (!dialog.open) dialog.showModal();
}

function closeDialog(id) { if ($(id).open) $(id).close(); }

function showView(view) {
  if (!['memory', 'map', 'backup', 'settings', 'connect'].includes(view)) return;
  state.view = view;
  for (const section of document.querySelectorAll('.view')) section.hidden = section.id !== 'view-' + view;
  for (const button of document.querySelectorAll('[data-view]')) {
    const active = button.dataset.view === view;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  }
  if (view === 'map') renderMap();
  window.scrollTo({ top: 0, behavior: 'auto' });
}

function showEditor(memory = null) {
  if (!state.ready) return;
  state.editingLibrary = state.selected;
  $('editorHeading').textContent = memory ? '编辑这段记忆' : '记下一段原话';
  $('memoryId').value = memory ? memory.id : '';
  $('memoryTitle').value = memory ? memory.title : '';
  $('memoryText').value = memory ? memory.text : '';
  $('memoryAssistant').value = memory ? memory.assistant || '' : '';
  $('memoryTags').value = tagsOf(memory || {}).join('，');
  $('editorError').hidden = true;
  closeDialog('detailDialog');
  showDialog('memoryDialog');
}

function showDetail(id) {
  const memory = state.memories.find((entry) => entry.id === id);
  if (!memory) { toast('这段记忆已经不存在，请重新选择。'); return; }
  state.detail = memory;
  $('detailTitle').textContent = titleOf(memory);
  $('detailMeta').textContent = libraryName() + ' · ' + dateLabel(memory, true);
  $('detailText').textContent = memory.text || '';
  $('detailAssistantBlock').hidden = !memory.assistant;
  $('detailAssistant').textContent = memory.assistant || '';
  replaceContents($('detailTags'), ...tagsOf(memory).map((tag) => tagElement('#' + tag)));
  $('detailStatus').hidden = memory.status !== 'disabled' && memory.status !== 'historical';
  $('detailStatus').textContent = memory.status === 'disabled' ? '这是一条已停用的记忆，仍保留原文供查看与备份。' : '这是一条历史记录，导入时保留了原有状态。';
  showDialog('detailDialog');
}

function setButtonBusy(button, busy) { button.disabled = busy; button.setAttribute('aria-busy', String(busy)); }

$('memoryForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.ready || $('saveMemory').disabled) return;
  if (!$('memoryText').value.trim()) { $('memoryText').focus(); return; }
  setButtonBusy($('saveMemory'), true);
  $('editorError').hidden = true;
  try {
    const id = $('memoryId').value;
    const generatedTitle = $('memoryText').value.trim().split('\n')[0].slice(0, 100).replace(/[\ud800-\udbff]$/, '');
    const memory = { title: $('memoryTitle').value.trim() || generatedTitle, text: $('memoryText').value, assistant: $('memoryAssistant').value, tags: $('memoryTags').value.split(/[,，\n]/).map((tag) => tag.trim()).filter(Boolean) };
    if (id) memory.id = id;
    await store.saveMemory(state.editingLibrary, memory);
    closeDialog('memoryDialog');
    state.query = ''; $('searchInput').value = ''; state.filter = 'all'; updateFilterButtons();
    await refresh();
    showView('memory');
    toast('已保存到当前设备。');
  } catch (error) { $('editorError').textContent = readableError(error, '保存未完成，请保留原文后重试。'); $('editorError').hidden = false; }
  finally { setButtonBusy($('saveMemory'), false); }
});

$('libraryForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.ready || $('createLibrary').disabled) return;
  setButtonBusy($('createLibrary'), true); $('libraryError').hidden = true;
  try {
    const library = await store.createLibrary($('libraryName').value);
    await store.selectLibrary(library.id);
    state.selected = library.id; state.query = ''; $('searchInput').value = '';
    closeDialog('libraryDialog'); await refresh(); showView('memory'); toast('新的记忆库已准备好。');
  } catch (error) { $('libraryError').textContent = readableError(error); $('libraryError').hidden = false; }
  finally { setButtonBusy($('createLibrary'), false); }
});

$('librarySelect').addEventListener('change', async () => {
  const old = state.selected;
  $('librarySelect').disabled = true;
  try { await store.selectLibrary($('librarySelect').value); state.selected = $('librarySelect').value; state.query = ''; $('searchInput').value = ''; state.filter = 'all'; updateFilterButtons(); await refresh(); toast('已切换到“' + libraryName() + '”。'); }
  catch (error) { state.selected = old; $('librarySelect').value = old; toast(readableError(error)); }
  finally { $('librarySelect').disabled = false; }
});

$('newLibrary').addEventListener('click', () => { $('libraryName').value = ''; $('libraryError').hidden = true; showDialog('libraryDialog'); });
for (const id of ['newMemory', 'emptyAdd']) $(id).addEventListener('click', () => showEditor());
for (const button of document.querySelectorAll('[data-close]')) button.addEventListener('click', () => closeDialog(button.dataset.close));
for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => showView(button.dataset.view));
$('editMemory').addEventListener('click', () => { if (state.detail) showEditor(state.detail); });
$('deleteMemory').addEventListener('click', () => { if (state.detail) showDialog('confirmDialog'); });
$('cancelDelete').addEventListener('click', () => closeDialog('confirmDialog'));
$('confirmDelete').addEventListener('click', async () => {
  if (!state.detail || $('confirmDelete').disabled) return;
  setButtonBusy($('confirmDelete'), true);
  try { await store.deleteMemory(state.selected, state.detail.id); state.detail = null; closeDialog('confirmDialog'); closeDialog('detailDialog'); await refresh(); toast('已从当前记忆库删除。'); }
  catch (error) { toast(readableError(error)); }
  finally { setButtonBusy($('confirmDelete'), false); }
});

function updateFilterButtons() {
  for (const button of document.querySelectorAll('[data-filter]')) {
    const active = button.dataset.filter === state.filter;
    button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
  }
}
for (const button of document.querySelectorAll('[data-filter]')) button.addEventListener('click', () => { state.filter = button.dataset.filter; updateFilterButtons(); renderMemories(); });
$('searchInput').addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.query = $('searchInput').value; renderMemories(); }, 120); });
$('searchForm').addEventListener('submit', (event) => { event.preventDefault(); clearTimeout(searchTimer); state.query = $('searchInput').value; renderMemories(); $('searchInput').blur(); });

function nativeSaveResult(event) {
  const result = event && event.detail;
  if (!result || typeof result.requestId !== 'string') return;
  const pending = nativeSaves.get(result.requestId);
  if (!pending) return;
  clearTimeout(pending.timer); nativeSaves.delete(result.requestId);
  if (result.saved === true) pending.resolve({ saved: true });
  else if (result.cancelled === true) pending.resolve({ cancelled: true });
  else pending.reject(new Error(typeof result.error === 'string' && result.error.length < 300 ? result.error : '文件没有保存，请重试并选择保存位置。'));
}
window.addEventListener('lovehouse-save-result', nativeSaveResult);

async function saveFile(filename, mime, content) {
  if (platform() === 'android' && window.LoveHouseNative && typeof window.LoveHouseNative.saveFile === 'function') {
    return new Promise((resolve, reject) => {
      const requestId = 'save-' + (window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : Date.now() + '-' + Math.random().toString(36).slice(2));
      const timer = setTimeout(() => { nativeSaves.delete(requestId); reject(new Error('尚未收到文件保存确认，请确认系统保存窗口是否完成。记忆仍保存在本机。')); }, 180000);
      nativeSaves.set(requestId, { resolve, reject, timer });
      try { window.LoveHouseNative.saveFile(requestId, filename, mime, content); }
      catch { clearTimeout(timer); nativeSaves.delete(requestId); reject(new Error('无法打开系统保存窗口，请重试。')); }
    });
  }
  const blob = new Blob([content], { type: mime });
  const file = typeof File === 'function' ? new File([blob], filename, { type: mime }) : null;
  let canShareFile = false;
  const mobileSharing = /Android|iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  try { canShareFile = !!(mobileSharing && file && navigator.share && navigator.canShare && navigator.canShare({ files: [file] })); } catch { /* Unsupported browser share implementations can still download a Blob. */ }
  if (canShareFile) {
    try { await navigator.share({ files: [file], title: '爱之屋 · ' + libraryName() }); return { shared: true }; }
    catch (error) { if (error && error.name === 'AbortError') return { cancelled: true }; }
  }
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url; anchor.download = filename; anchor.hidden = true;
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
  return { downloadStarted: true };
}

function filenameFor(extension, name) {
  const safe = name.replace(/[\\/:*?"<>|\u0000-\u001f]/g, '-').replace(/[. ]+$/g, '').slice(0, 60).replace(/[\ud800-\udbff]$/, '') || '记忆库';
  return '爱之屋-' + safe + '-' + new Date().toISOString().slice(0, 10) + '.' + extension;
}

async function exportMemory(format) {
  if (!state.ready) return;
  const button = $(format === 'json' ? 'exportJson' : 'exportMarkdown');
  if (button.disabled) return;
  const exportLibraryId = state.selected, exportLibraryName = libraryName(), exportMemories = state.memories.slice();
  setButtonBusy(button, true); $('exportStatus').textContent = '';
  try {
    let content, mime;
    if (format === 'json') { content = JSON.stringify(await store.exportLibrary(exportLibraryId), null, 2); mime = 'application/json'; }
    else {
      const sections = ['# ' + exportLibraryName, '', '爱之屋移动版阅读文件。完整恢复和迁移请使用 JSON 导出。', ''];
      for (const memory of exportMemories) {
        sections.push('## ' + titleOf(memory), '', dateLabel(memory, true), '', String(memory.text || ''), '');
        if (memory.assistant) sections.push('### 对方的回复', '', String(memory.assistant), '');
        if (tagsOf(memory).length) sections.push('标签：' + tagsOf(memory).join('、'), '');
        if (memory.status !== 'active') sections.push('状态：' + (memory.status === 'disabled' ? '已停用' : '历史记录'), '');
      }
      content = sections.join('\n'); mime = 'text/markdown';
    }
    const result = await saveFile(filenameFor(format === 'json' ? 'json' : 'md', exportLibraryName), mime, content);
    const message = result.saved ? '文件已保存到你选择的位置。' : result.cancelled ? '已取消，文件未保存。' : result.shared ? '文件已交给系统分享，请确认已存入“文件”或你选择的位置。' : '已发起文件下载，请确认下载列表或“文件”中已保存。';
    $('exportStatus').textContent = message; toast(message, 6000);
  } catch (error) { $('exportStatus').textContent = readableError(error, '导出没有完成，记忆仍保存在本机。'); toast($('exportStatus').textContent, 7000); }
  finally { setButtonBusy(button, false); }
}
$('exportJson').addEventListener('click', () => exportMemory('json'));
$('exportMarkdown').addEventListener('click', () => exportMemory('markdown'));

for (const id of ['chooseImport', 'emptyImport']) $(id).addEventListener('click', () => { if (state.ready) $('importFile').click(); });
function readImportFile(file) {
  if (typeof file.text === 'function') return file.text();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error('无法读取所选文件，请重新选择。'));
    reader.onabort = () => reject(new Error('文件读取已取消，没有导入内容。'));
    reader.readAsText(file, 'UTF-8');
  });
}
$('importFile').addEventListener('change', async () => {
  const file = $('importFile').files && $('importFile').files[0];
  if (!file) return;
  $('chooseImport').disabled = true; $('importResult').hidden = true;
  try {
    if (file.size > MAX_IMPORT) throw new Error('文件超过 32 MiB，请先在桌面版按单库导出。');
    const result = await store.importLibrary(await readImportFile(file));
    const library = result.library || result;
    await store.selectLibrary(library.id); state.selected = library.id; state.query = ''; $('searchInput').value = ''; state.filter = 'all'; updateFilterButtons();
    await refresh();
    $('importResult').textContent = '已导入为独立记忆库“' + library.name + '”。未覆盖原库，也没有启用任何连接。' + (Array.isArray(result.warnings) && result.warnings.length ? '\n' + result.warnings.slice(0, 5).join('\n') : '');
    $('importResult').hidden = false;
    showView('backup'); toast('导入完成，原有记忆库保持独立。');
  } catch (error) { $('importResult').textContent = readableError(error, '文件未导入，请确认这是爱之屋的 JSON 分享文件。'); $('importResult').hidden = false; showView('backup'); }
  finally { $('chooseImport').disabled = !state.ready; $('importFile').value = ''; }
});

const svgNS = 'http://www.w3.org/2000/svg';
let mapTransform = { x: 0, y: 0, zoom: 1 }, showLabels = false, mapDrag = null;
const pointers = new Map();
function svgElement(name, attributes = {}) { const element = document.createElementNS(svgNS, name); for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value)); return element; }
function applyMapTransform() { $('mapWorld').setAttribute('transform', `translate(${mapTransform.x} ${mapTransform.y}) translate(180 210) scale(${mapTransform.zoom}) translate(-180 -210)`); }
function setZoom(value) { mapTransform.zoom = Math.min(3, Math.max(.5, value)); applyMapTransform(); }

function renderMap() {
  const memories = state.memories.slice().sort((a, b) => timeValue(b) - timeValue(a)).slice(0, 80);
  const world = $('mapWorld'); replaceContents(world);
  $('mapEmpty').hidden = memories.length > 0;
  $('mapCount').textContent = memories.length + ' 颗星' + (state.memories.length > 80 ? ' / 共 ' + state.memories.length + ' 条' : '');
  const positions = memories.map((memory, index) => {
    const angle = index * 2.399963229728653;
    const radius = memories.length === 1 ? 0 : Math.sqrt((index + .6) / memories.length) * 138;
    return { x: 180 + Math.cos(angle) * radius, y: 210 + Math.sin(angle) * radius * 1.12, memory };
  });
  let edgeCount = 0;
  for (let i = 0; i < positions.length; i++) for (let j = i + 1; j < positions.length && edgeCount < 160; j++) {
    if (!tagsOf(positions[i].memory).some((tag) => tagsOf(positions[j].memory).includes(tag))) continue;
    world.append(svgElement('line', { x1: positions[i].x, y1: positions[i].y, x2: positions[j].x, y2: positions[j].y, stroke: '#ba96ad', 'stroke-width': '.7', opacity: '.32' }));
    edgeCount++;
  }
  for (const position of positions) {
    const node = svgElement('g', { 'data-node': position.memory.id, tabindex: '0', role: 'button', 'aria-label': '查看记忆：' + titleOf(position.memory) });
    node.append(svgElement('circle', { cx: position.x, cy: position.y, r: 17, fill: 'url(#starGlow)' }));
    node.append(svgElement('circle', { cx: position.x, cy: position.y, r: 26, fill: 'transparent' }));
    node.append(svgElement('circle', { cx: position.x, cy: position.y, r: 3.5, fill: position.memory.status === 'disabled' ? '#877880' : '#ffcadf', stroke: '#fff4f8', 'stroke-width': '.8' }));
    const title = svgElement('title'); title.textContent = titleOf(position.memory); node.append(title);
    if (showLabels) { const label = svgElement('text', { x: position.x, y: position.y + 19, 'text-anchor': 'middle' }); label.textContent = titleOf(position.memory).slice(0, 9); node.append(label); }
    node.addEventListener('click', () => { if (!mapDrag || !mapDrag.moved) showDetail(position.memory.id); });
    node.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showDetail(position.memory.id); } });
    world.append(node);
  }
  applyMapTransform();
}

$('mapLabels').addEventListener('click', () => { showLabels = !showLabels; $('mapLabels').setAttribute('aria-pressed', String(showLabels)); $('mapLabels').textContent = showLabels ? '隐藏名称' : '显示名称'; renderMap(); });
$('mapZoomIn').addEventListener('click', () => setZoom(mapTransform.zoom * 1.2));
$('mapZoomOut').addEventListener('click', () => setZoom(mapTransform.zoom / 1.2));
$('mapReset').addEventListener('click', () => { mapTransform = { x: 0, y: 0, zoom: 1 }; applyMapTransform(); });
$('memoryMap').addEventListener('pointerdown', (event) => {
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  $('memoryMap').setPointerCapture(event.pointerId);
  const points = [...pointers.values()];
  const node = event.target.closest && event.target.closest('[data-node]');
  mapDrag = { x: event.clientX, y: event.clientY, tx: mapTransform.x, ty: mapTransform.y, zoom: mapTransform.zoom, moved: false, nodeId: node ? node.dataset.node : null, distance: points.length > 1 ? Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y) : 0 };
});
$('memoryMap').addEventListener('pointermove', (event) => {
  if (!pointers.has(event.pointerId) || !mapDrag) return;
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  const points = [...pointers.values()];
  if (points.length > 1 && mapDrag.distance > 0) {
    const distance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
    setZoom(mapDrag.zoom * distance / mapDrag.distance); mapDrag.moved = true;
  } else {
    const dx = event.clientX - mapDrag.x, dy = event.clientY - mapDrag.y;
    if (Math.hypot(dx, dy) > 5) mapDrag.moved = true;
    const rect = $('memoryMap').getBoundingClientRect();
    mapTransform.x = mapDrag.tx + dx * 360 / rect.width;
    mapTransform.y = mapDrag.ty + dy * 420 / rect.height;
    applyMapTransform();
  }
});
for (const type of ['pointerup', 'pointercancel']) $('memoryMap').addEventListener(type, (event) => {
  pointers.delete(event.pointerId);
  if (type === 'pointerup' && !pointers.size && mapDrag && !mapDrag.moved && mapDrag.nodeId) showDetail(mapDrag.nodeId);
  if (!pointers.size) setTimeout(() => { mapDrag = null; }, 0);
});
$('memoryMap').addEventListener('wheel', (event) => { event.preventDefault(); setZoom(mapTransform.zoom * (event.deltaY > 0 ? .9 : 1.1)); }, { passive: false });

window.addEventListener('beforeinstallprompt', (event) => { event.preventDefault(); installPrompt = event; if (platform() !== 'android') $('installApp').hidden = false; });
$('installApp').addEventListener('click', async () => {
  if (!installPrompt) return;
  try { await installPrompt.prompt(); const choice = await installPrompt.userChoice; if (choice.outcome === 'accepted') toast('已提交安装，请从主屏幕图标打开爱之屋。'); }
  catch { toast('请使用浏览器菜单中的“安装应用 / 添加到主屏幕”。'); }
  installPrompt = null; $('installApp').hidden = true;
});
window.addEventListener('appinstalled', () => { $('installApp').hidden = true; toast('主屏幕应用已准备好。'); });
$('retryStorage').addEventListener('click', () => location.reload());

// The native shell can ask the page to dismiss a sheet before exiting. It
// receives only a handled/not-handled signal, never memory contents.
window.LoveHouseBack = () => {
  const dialogs = [...document.querySelectorAll('dialog[open]')];
  if (dialogs.length) { dialogs[dialogs.length - 1].close(); return true; }
  if (state.view !== 'memory') { showView('memory'); return true; }
  return false;
};
window.LoveHouseMobile = { summary: () => ({ ready: state.ready, libraries: state.libraries.length, memories: state.memories.length, platform: platform(), storage: state.ready ? 'indexeddb' : 'unavailable' }) };

function platformGuidance() {
  if (platform() === 'android') {
    $('dataRetention').textContent = 'APK 的记忆保存在这台手机的应用私有空间。卸载或清除应用数据会删除存档，请先导出 JSON；同一签名的覆盖升级会保留数据。';
    $('installText').textContent = '你正在使用 Android APK。记忆无需电脑常开，也不会自动传到桌面。需要跨设备迁移时，请用 JSON 导出与导入。';
  } else if (/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) {
    $('installText').textContent = '使用 Safari 打开此页面，点击分享，再选“添加到主屏幕”。之后从主屏幕的爱之屋图标打开。这是可安装网页版，不是需要 Apple 签名的 IPA。';
    $('dataRetention').textContent = '记忆保存在这台设备的浏览器 / 主屏幕应用空间。清除网站数据、移除应用或系统回收存储可能导致丢失，请定期导出 JSON；不同打开方式的数据可能独立。';
  }
}

async function start() {
  platformGuidance();
  try {
    const initialized = await store.init();
    state.selected = initialized ? initialized.selectedLibraryId || initialized.selectedId || initialized.selected_id || null : null;
    let libraries = await store.listLibraries();
    if (!libraries.length) { const library = await store.createLibrary('我的记忆库'); state.selected = library.id; await store.selectLibrary(library.id); }
    state.ready = true;
    await refresh();
    for (const id of ['newLibrary', 'newMemory', 'librarySelect', 'exportJson', 'exportMarkdown', 'chooseImport']) $(id).disabled = false;
    $('storageMode').textContent = 'IndexedDB · 当前设备';
    document.documentElement.dataset.appReady = 'true';
  } catch (error) {
    state.ready = false; $('storageError').hidden = false;
    $('storageErrorText').textContent = readableError(error, '当前环境不能打开本地数据库。请退出隐私浏览模式，或在正常浏览器中重新打开。');
    $('storageMode').textContent = '不可用 · 尚未保存任何新记忆';
    $('memoryList').setAttribute('aria-busy', 'false');
    document.documentElement.dataset.appReady = 'false';
  }
}

window.LoveHouseReady = start();
window.LoveHouseApp = { store, ready: window.LoveHouseReady, refresh };

// Service navigation carries only an origin. Authentication happens on the selected service.
$('homeConnectAgent').addEventListener('click',()=>showView('connect'));
$('memoryServiceAddress').addEventListener('input',()=>{
 const link=$('openMemoryService');
 try{const url=memoryServiceUrl($('memoryServiceAddress').value.trim());link.href=url;link.classList.remove('disabled-link');link.setAttribute('aria-disabled','false');$('memoryServiceError').textContent='在这台服务上选择存档并复制给 Agent。管理凭据只在服务自己的页面填写。';}
 catch(error){link.removeAttribute('href');link.classList.add('disabled-link');link.setAttribute('aria-disabled','true');$('memoryServiceError').textContent=error.message;}
});
$('openMemoryService').addEventListener('click',event=>{if($('openMemoryService').getAttribute('aria-disabled')==='true')event.preventDefault();});
