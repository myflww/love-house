const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Execute the actual UI functions and registered handlers. Mocks supply only the
// canvas/renderer/DOM boundary; graph mode and camera behavior stays in index.html.
const source = fs.readFileSync(path.join(__dirname, '../../nkb/viz/web/index.html'), 'utf8');
const dynamics = import('../../nkb/viz/art/synapse-dynamics.js');

function bodyEnd(start) {
  let depth = 0, quote = '', line = false, block = false;
  for (let i = start; i < source.length; i++) {
    const c = source[i], next = source[i + 1];
    if (line) { if (c === '\n') line = false; continue; }
    if (block) { if (c === '*' && next === '/') { block = false; i++; } continue; }
    if (quote) { if (c === '\\') { i++; continue; } if (c === quote) quote = ''; continue; }
    if (c === '/' && next === '/') { line = true; i++; continue; }
    if (c === '/' && next === '*') { block = true; i++; continue; }
    if (c === '"' || c === "'" || c === '`') { quote = c; continue; }
    if (c === '{') depth++;
    if (c === '}' && --depth === 0) return i + 1;
  }
  throw new Error('Unclosed actual UI function');
}
function actualFunction(name) {
  const start = source.indexOf('function ' + name + '(');
  assert.ok(start >= 0, 'Missing actual UI function ' + name);
  const open = source.indexOf('{', start);
  return source.slice(start, bodyEnd(open));
}
function actualHandler(marker) {
  const start = source.indexOf(marker);
  assert.ok(start >= 0, 'Missing actual UI handler ' + marker);
  const open = source.indexOf('{', start);
  const end = bodyEnd(open);
  return source.slice(start, end) + (marker.includes('addEventListener') ? ');' : ';');
}
function canvasMock() {
  const listeners = new Map();
  return { dataset: {}, style: {}, listeners, classList: { add() {}, remove() {} },
    setPointerCapture() {}, addEventListener(name, fn) { listeners.set(name, fn); },
    getBoundingClientRect() { return { left: 10, top: 20, width: 240, height: 140 }; } };
}
async function harness() {
  const module = await dynamics;
  const elements = new Map();
  const $ = id => {
    id = id.replace(/^#/, '');
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, { hidden: false, attributes: {}, textContent: '',
        classList: { toggle(name, on) { if (on) classes.add(name); else classes.delete(name); }, contains(name) { return classes.has(name); } },
        setAttribute(k, v) { this.attributes[k] = v; } });
    }
    return elements.get(id);
  };
  const nodes = [
    { id: 'one', x: 10000, y: -9000, recalls: 4, state: 'active', tags: ['生活'] },
    { id: 'two', x: -7000, y: 6000, recalls: 80, state: 'active', tags: ['成长'] },
  ];
  const edges = [{ source: 'one', target: 'two', effective_w: .76 }];
  const S = { nodes, edges, byId: new Map(nodes.map(n => [n.id, n])), visible: nodes,
    visibleSet: new Set(nodes.map(n => n.id)), selected: 'one', query: '雨天', focus: 'one',
    result: { query: '雨天', trail: [['one', 'two', .76, 1]] }, active: new Map([['one', { at: 1 }]]),
    lit: new Map([['one|two', .76]]), kinds: new Set(['episode']), states: new Set(['active']),
    adj: new Map([['one', [{ id: 'two' }]], ['two', [{ id: 'one' }]]]),
    cam: { x: 400, y: 300, k: 1.25 }, W: 800, H: 600, dpr: 1, art: true, graphMode: 'nebula',
    paused: true, sim: 0, raf: 0, pulseUntil: 0, libraryId: 'personal', libraryEpoch: 7,
    view: { mode: 'manual', target: { x: 1, y: 1, k: 1 }, dirty: false, lastFitAt: 8, lastAnimationAt: 9 },
  };
  const calls = { frames: 0, draws: 0, fits: [], pans: [], centers: [], writes: 0 };
  const cv = canvasMock(), mini = canvasMock();
  const mc = new Proxy({}, { get: (target, name) => name in target ? target[name] : () => {} });
  const c = { S, $, cv, mini, mc, document: { hidden: false, getElementById: id => $(id), documentElement: { dataset: { theme: 'light' } } },
    window: { NKBArt: module }, artRenderer: { isTransitioning: () => false, setEnabled() {} },
    graphViews: new Map(), fallbackNodes: null, fallbackEdges: null, fallbackTargets: new Map(),
    graphMotionTime: 0, lastFrameAt: 0, performance: { now: () => 100 },
    matchMedia: () => ({ matches: false }),
    updateViewBadge() {}, renderPause() {}, toast() {}, state: n => n.state,
    radius: () => 4, clamp: (v, a, b) => Math.max(a, Math.min(b, v)),
    manualView(reason) { S.view.mode = 'manual'; S.view.target = null; S.view.dirty = false; S.view.reason = reason; },
    requestAutoFit(reason) { calls.fits.push(reason); if (S.view.mode === 'auto') S.view.dirty = true; },
    requestAnimationFrame() { return ++calls.frames; }, advanceAutoView() { return false; }, physics() { S.sim--; },
    draw() { calls.draws++; }, localPoint: e => ({ x: e.clientX - 10, y: e.clientY - 20 }),
    select(id) { S.selected = id; },
    localStorage: { setItem() { calls.writes++; } },
  };
  vm.createContext(c);
  const start = source.indexOf('/* Graph view state:');
  const end = source.indexOf('/* End graph view state. */', start);
  assert.ok(start >= 0 && end > start);
  const code = source.slice(start, end)
    + '\n' + ['locate', 'nodeAt', 'drawMini', 'schedule', 'frame', 'initArt', 'zoom'].map(actualFunction).join('\n')
    + '\n' + source.slice(source.indexOf('const pointers=new Map();let drag=null,pinch=null;'), source.indexOf('function pointerEnd('))
    + '\n' + actualFunction('pointerEnd')
    + '\n' + source.slice(source.indexOf("cv.addEventListener('pointerup'"), source.indexOf("mini.addEventListener('pointerdown'"))
    + '\n' + actualHandler("mini.addEventListener('pointerdown'")
    + '\n' + actualHandler("$('#themeBtn').onclick=")
    + '\n' + actualHandler("$('#viewBtn').onclick=");
  vm.runInContext(code, c, { filename: 'actual-graph-view-functions.js' });
  return { c, S, calls, $, module };
}

function businessSnapshot(S) {
  return { selected: S.selected, query: S.query, focus: S.focus, result: S.result, active: S.active,
    lit: S.lit, nodes: S.nodes, edges: S.edges, byId: S.byId, kinds: S.kinds, states: S.states,
    libraryId: S.libraryId, libraryEpoch: S.libraryEpoch, data: JSON.stringify([S.nodes, S.edges]) };
}
function assertBusinessPreserved(S, before) {
  for (const name of Object.keys(before).filter(n => n !== 'data')) assert.equal(S[name], before[name], name);
  assert.equal(JSON.stringify([S.nodes, S.edges]), before.data);
}

test('real mode switching preserves the library, recall trail, query, focus and actual graph data', async () => {
  const { c, S, calls, $ } = await harness(), before = businessSnapshot(S);
  const originalCamera = { ...S.cam };
  c.switchGraphMode('flat');
  assert.equal(S.graphMode, 'flat'); assert.equal(S.view.mode, 'auto'); assert.equal(S.view.dirty, true);
  assert.equal(S.view.target, null); assert.equal(c.document.documentElement.dataset.theme, 'light');
  assert.equal($('viewBtn').attributes['aria-label'], '切换动态星云');
  assertBusinessPreserved(S, before);
  Object.assign(S.cam, { x: 250, y: 450, k: 3 }); S.view.mode = 'manual';
  c.switchGraphMode('nebula');
  assert.deepEqual(S.cam, originalCamera); assert.equal(S.view.mode, 'manual');
  c.switchGraphMode('flat');
  assert.deepEqual(S.cam, { x: 250, y: 450, k: 3 }); assert.equal(S.view.mode, 'manual');
  assertBusinessPreserved(S, before); assert.equal(calls.writes, 0);
});

test('requesting the current mode is a no-op and renderer fallback cannot toggle back to a broken view', async () => {
  const { c, S, calls, $ } = await harness();
  const before = businessSnapshot(S); c.switchGraphMode('nebula');
  assert.equal(calls.frames, 0); assert.equal(c.graphViews.size, 0);
  c.useGraphFallback(); $('viewBtn').onclick();
  assert.equal(S.art, false); assert.equal(S.graphMode, 'flat'); assert.equal($('viewBtn').disabled, true);
  assert.equal(S.view.mode, 'auto'); assert.equal(S.view.target, null); assert.equal(S.view.dirty, true);
  assertBusinessPreserved(S, before);
});

test('both missing WebGL and constructor failure enter a visible fit-ready flat fallback', async () => {
  for (const constructor of [undefined, class { constructor() { throw new Error('No WebGL'); } }]) {
    const { c, S, $ } = await harness(), before = businessSnapshot(S);
    c.window.NKBArt = constructor ? { ...c.window.NKBArt, NeuralArt: constructor } : {};
    c.initArt();
    assert.equal(S.art, false); assert.equal(S.graphMode, 'flat'); assert.equal(S.view.dirty, true);
    assert.equal(S.view.mode, 'auto'); assert.equal(S.view.target, null); assert.equal($('viewBtn').disabled, true);
    assertBusinessPreserved(S, before);
  }
});

test('fallback locate and picking use displayed gravity coordinates without changing stored positions', async () => {
  const { c, S } = await harness(), before = businessSnapshot(S);
  S.art = false; S.graphMode = 'flat';
  const n = S.nodes[0], displayed = c.graphDisplayPosition(n);
  assert.notEqual(displayed.x, n.x);
  c.locate(n);
  const projected = c.projectGraphNode(n);
  assert.equal(projected.x, S.W / 2); assert.equal(projected.y, S.H / 2);
  assert.equal(c.nodeAt(projected), n);
  assert.equal(c.nodeAt({ x: n.x * S.cam.k + S.cam.x, y: n.y * S.cam.k + S.cam.y }), null);
  assertBusinessPreserved(S, before);
});

test('flat dragging over a neuron pans the view and never edits its position or recalls', async () => {
  for (const webgl of [false, true]) {
    const { c, S, calls } = await harness(), before = businessSnapshot(S);
    S.art = webgl; S.graphMode = 'flat';
    const targets = c.window.NKBArt.gravityTargets(S.nodes, S.edges);
    c.artRenderer = { displayPosition: n => targets.get(n.id), syncTransform() {}, radiusOnScreen: () => 4,
      projectNode(n) { const p = targets.get(n.id); return { x: p.x * S.cam.k + S.cam.x, y: p.y * S.cam.k + S.cam.y }; },
      panCamera(x, y) { calls.pans.push([x, y]); } };
    const p = c.projectGraphNode(S.nodes[0]), originalCam = { ...S.cam };
    c.cv.listeners.get('pointerdown')({ clientX: p.x + 10, clientY: p.y + 20, pointerId: 1, pointerType: 'mouse', button: 0 });
    c.cv.listeners.get('pointermove')({ clientX: p.x + 46, clientY: p.y + 44, pointerId: 1 });
    assert.equal(S.view.mode, 'manual');
    if (webgl) assert.deepEqual(calls.pans, [[-36, -24]]);
    else { assert.equal(S.cam.x, originalCam.x + 36); assert.equal(S.cam.y, originalCam.y + 24); }
    assertBusinessPreserved(S, before);
  }
});

test('actual host pointer releases select only a clicked node and never select after drag or lost capture', async () => {
  const { c, S } = await harness();
  c.artRenderer = {syncTransform() {}, radiusOnScreen: () => 4,
    projectNode: n => n.id === 'one' ? {x:120,y:90} : {x:300,y:210}};
  S.selected = null;
  const event = (x, y, extra = {}) => ({clientX:x+10,clientY:y+20,pointerId:1,pointerType:'mouse',button:0,...extra});
  const emit = (name, value) => c.cv.listeners.get(name)(value);
  // Hovering or clicking empty space does not select a node (the renderer
  // therefore keeps its automatic yaw active).
  emit('pointerdown',event(600,450));emit('pointerup',event(600,450));assert.equal(S.selected,null);
  emit('pointerdown',event(120,90));emit('pointerup',event(120,90));assert.equal(S.selected,'one');
  S.selected=null;
  emit('pointerdown',event(120,90));emit('pointermove',event(180,130));emit('pointerup',event(180,130));
  assert.equal(S.selected,null);
  emit('pointerdown',event(120,90,{shiftKey:true}));emit('lostpointercapture',event(120,90));
  emit('pointerup',event(120,90));assert.equal(S.selected,null,'lost capture must cancel, not click/select');
  emit('pointerdown',event(300,210));emit('pointerup',event(300,210));assert.equal(S.selected,'two');
});

test('host wheel and two-touch gestures retain screen zoom while nebula drags never use host panning', async () => {
  const {c,S,calls}=await harness();
  let captures=0,restores=0;
  c.artRenderer={syncTransform(){},radiusOnScreen:()=>4,projectNode:()=>({x:-1000,y:-1000}),
    captureScreenPoint(){captures++;return {x:1,y:2};},restoreScreenPoint(){restores++;},
    panCamera(x,y){calls.pans.push([x,y]);}};
  let prevented=false;const originalZoom=S.cam.k;
  c.cv.listeners.get('wheel')({clientX:310,clientY:220,deltaY:-100,deltaMode:0,preventDefault(){prevented=true;}});
  assert.ok(prevented);assert.ok(S.cam.k>originalZoom);assert.equal(captures,1);assert.equal(restores,1);
  const event=(id,x,y)=>({pointerId:id,pointerType:'touch',button:0,clientX:x+10,clientY:y+20});
  c.cv.listeners.get('pointerdown')(event(1,200,150));
  c.cv.listeners.get('pointerdown')(event(2,400,150));const beforePinch=S.cam.k;
  c.cv.listeners.get('pointermove')(event(2,500,180));assert.ok(S.cam.k>beforePinch);
  assert.equal(calls.pans.length,0,'nebula pan/rotate belongs to OrbitControls, two-touch zoom belongs to host');
  c.cv.listeners.get('pointercancel')(event(2,500,180));
});

test('minimap click recenters the displayed node in both WebGL and canvas modes', async () => {
  for (const webgl of [false, true]) {
    const { c, S, calls } = await harness(), before = businessSnapshot(S);
    S.art = webgl; S.graphMode = 'flat';
    if (webgl) c.artRenderer = { projectNode: n => n.id === 'one' ? { x: 150, y: 120 } : { x: 620, y: 470 }, panCamera: (x, y) => calls.pans.push([x, y]) };
    c.drawMini(true);
    const p = c.projectGraphNode(S.nodes[0]), m = S.mini;
    c.mini.listeners.get('pointerdown')({ clientX: p.x * m.k + m.ox + 10, clientY: p.y * m.k + m.oy + 20 });
    if (webgl) { assert.ok(Math.abs(calls.pans[0][0] - (p.x - S.W / 2)) < 1e-8); assert.ok(Math.abs(calls.pans[0][1] - (p.y - S.H / 2)) < 1e-8); }
    else { const result = c.projectGraphNode(S.nodes[0]); assert.ok(Math.abs(result.x - S.W / 2) < 1e-8); assert.ok(Math.abs(result.y - S.H / 2) < 1e-8); }
    assertBusinessPreserved(S, before);
  }
});

test('paused view morphs continue scheduling while recall animation time stays frozen', async () => {
  const { c, S, calls } = await harness();
  S.paused = true; c.graphMotionTime = 12; c.artRenderer.isTransitioning = () => true;
  c.frame(100); assert.equal(calls.draws, 1); assert.equal(calls.frames, 1); assert.equal(c.graphMotionTime, 12);
  c.artRenderer.isTransitioning = () => false; S.view.dirty = false;
  c.frame(200); assert.equal(calls.frames, 1); assert.equal(c.graphMotionTime, 12);
});

test('canvas animation pauses, hidden documents stop work, and empty paused graphs do not spin', async () => {
  const { c, S, calls } = await harness();
  S.art = false; S.paused = false; c.frame(100); c.frame(200);
  assert.ok(c.graphMotionTime > 0); const frozen = c.graphMotionTime;
  S.paused = true; S.view.dirty = false; const frames = calls.frames; c.frame(300);
  assert.equal(c.graphMotionTime, frozen); assert.equal(calls.frames, frames);
  c.document.hidden = true; const draws = calls.draws; c.frame(400);
  assert.equal(calls.draws, draws); assert.equal(calls.frames, frames);
  c.document.hidden = false; S.visible = []; S.nodes = []; S.edges = []; S.view.dirty = true; c.frame(500);
  assert.equal(calls.frames, frames);
});

test('theme changes are independent of graph mode and preserve all business state', async () => {
  const { c, S, calls, $ } = await harness(), before = businessSnapshot(S);
  $('themeBtn').onclick(); assert.equal(c.document.documentElement.dataset.theme, 'dark');
  assert.equal(S.graphMode, 'nebula'); assert.equal(calls.writes, 1);
  let appearanceCalls = 0;
  c.window.LoveHouseAppearance = { setTheme(theme, remember) { appearanceCalls++; assert.equal(remember, true); c.document.documentElement.dataset.theme = theme; } };
  c.switchGraphMode('flat'); $('themeBtn').onclick();
  assert.equal(c.document.documentElement.dataset.theme, 'light'); assert.equal(S.graphMode, 'flat');
  assert.equal(appearanceCalls, 1); assertBusinessPreserved(S, before);
});
