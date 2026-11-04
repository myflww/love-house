import test from 'node:test';
import assert from 'node:assert/strict';
import { gravityTargets, recallActivity, sampleSynapse, synapseMetrics } from '../../nkb/viz/art/synapse-dynamics.js';

const fields = ['association', 'activity', 'stability', 'width', 'alpha', 'amplitude', 'speed'];
const distance = (a, b = { x: 0, y: 0, z: 0 }) => Math.hypot(a.x - b.x, a.y - b.y, (a.z ?? 0) - (b.z ?? 0));
const deepFreeze = value => {
  if (value && typeof value === 'object') {
    Object.freeze(value);
    for (const child of Object.values(value)) deepFreeze(child);
  }
  return value;
};

test('effective weight takes precedence, including a real zero, and invalid values fall back safely', () => {
  assert.equal(synapseMetrics({ effective_w: 0, w: 1 }).association, 0);
  assert.equal(synapseMetrics({ effective_w: NaN, w: .73 }).association, .73);
  assert.equal(synapseMetrics({ effective_w: Infinity, w: .6 }).association, .6);
  assert.equal(synapseMetrics({ w: -2 }).association, 0);
  assert.equal(synapseMetrics({ w: 9 }).association, 1);
  for (const args of [[null, null, null], [{ w: NaN }, { recalls: NaN }, { recalls: Infinity }], [{ effective_w: -Infinity }, { recalls: -9 }, {}], [{ state: 'constructor' }, { state: 'toString' }, { state: '__proto__' }]]) {
    const m = synapseMetrics(...args);
    for (const field of fields) assert.ok(Number.isFinite(m[field]), field);
    assert.ok(m.width > 0 && m.alpha >= 0 && m.alpha <= 1);
  }
});

test('association independently makes connections thicker, more visible and steadier', () => {
  let previous;
  for (let i = 0; i <= 100; i++) {
    const m = synapseMetrics({ effective_w: i / 100 }, { recalls: 10 }, { recalls: 36 });
    if (previous) {
      for (const key of ['width', 'alpha', 'stability']) assert.ok(m[key] > previous[key], key);
      for (const key of ['amplitude', 'speed']) assert.ok(m[key] < previous[key], key);
      assert.equal(m.activity, previous.activity);
    }
    previous = m;
  }
});

test('cumulative recalls independently reinforce a connection, even beside an unused endpoint', () => {
  assert.equal(recallActivity({ recalls: 0 }), 0);
  assert.equal(recallActivity({ recalls: -10 }), 0);
  assert.equal(recallActivity({ recalls: 256 }), 1);
  assert.equal(recallActivity({ recalls: 1e100 }), 1);
  assert.ok(recallActivity({ recalls: 4 }) < recallActivity({ recalls: 40 }));
  for (const neighbour of [0, 10, 256]) {
    let previous;
    for (const count of [0, 1, 4, 16, 64, 256]) {
      const m = synapseMetrics({ w: .5 }, { recalls: count }, { recalls: neighbour });
      if (previous) {
        for (const key of ['activity', 'width', 'alpha', 'stability']) assert.ok(m[key] > previous[key], key);
        for (const key of ['amplitude', 'speed']) assert.ok(m[key] < previous[key], key);
        assert.equal(m.association, previous.association);
      }
      previous = m;
    }
  }
  assert.ok(synapseMetrics({ w: .6 }, { recalls: 0 }, { recalls: 256 }).activity < .2);
  assert.ok(synapseMetrics({ w: .9 }).stability > synapseMetrics({ w: .2 }, { recalls: 256 }, { recalls: 256 }).stability);
});

test('each lifecycle state gently loosens and fades presentation without falsifying association', () => {
  for (const position of ['edge', 'a', 'b']) {
    let previous;
    for (const state of ['active', 'fading', 'dormant', 'forgotten']) {
      const edge = { w: .8 }, a = { recalls: 64 }, b = { recalls: 64 };
      (position === 'edge' ? edge : position === 'a' ? a : b).state = state;
      const m = synapseMetrics(edge, a, b);
      assert.equal(m.association, .8);
      if (previous) {
        for (const key of ['width', 'alpha', 'stability']) assert.ok(m[key] < previous[key], key);
        for (const key of ['amplitude', 'speed']) assert.ok(m[key] > previous[key], key);
      }
      previous = m;
    }
  }
  assert.ok(synapseMetrics({ w: .8, active: false }).alpha < synapseMetrics({ w: .8 }).alpha);
});

test('sampling anchors both endpoints exactly across time, seed, strand and dimensionality', () => {
  const a = { x: -15.5, y: 33, z: 12 }, b = { x: 155, y: -43, z: -20 };
  const m = synapseMetrics({ w: .2 });
  for (const time of [-100, 0, .3, 500]) for (const strand of [-2, 0, 3]) {
    assert.deepEqual(sampleSynapse(a, b, 0, m, time, 'edge-a', strand), a);
    assert.deepEqual(sampleSynapse(a, b, 1, m, time, 'edge-a', strand), b);
  }
  assert.deepEqual(sampleSynapse([1, 2], [9, 8], -1, m), { x: 1, y: 2, z: 0 });
  assert.deepEqual(sampleSynapse(new Float32Array([1, 2, 3]), [9, 8, 7], 2, m), { x: 9, y: 8, z: 7 });
});

test('weaker synapses move more; freezing time freezes geometry and seeds remain deterministic', () => {
  const a = { x: 0, y: 0, z: 0 }, b = { x: 400, y: 100, z: 10 };
  const weak = synapseMetrics({ w: .08 }, { recalls: 0 }, { recalls: 0 });
  const strong = synapseMetrics({ w: .95 }, { recalls: 128 }, { recalls: 128 });
  let weakTravel = 0, strongTravel = 0;
  let wp = sampleSynapse(a, b, .47, weak, 0, 'same-edge');
  let sp = sampleSynapse(a, b, .47, strong, 0, 'same-edge');
  for (let i = 1; i <= 100; i++) {
    const wn = sampleSynapse(a, b, .47, weak, i / 10, 'same-edge');
    const sn = sampleSynapse(a, b, .47, strong, i / 10, 'same-edge');
    weakTravel += distance(wn, wp); strongTravel += distance(sn, sp); wp = wn; sp = sn;
  }
  assert.ok(weakTravel > strongTravel * 5);
  assert.deepEqual(sampleSynapse(a, b, .4, weak, 2, 'seed'), sampleSynapse(a, b, .4, weak, 2, 'seed'));
  assert.notDeepEqual(sampleSynapse(a, b, .4, weak, 2, 'seed'), sampleSynapse(a, b, .4, weak, 2, 'different'));
});

test('coincident, vertical, microscopic and malformed inputs cannot produce invalid geometry', () => {
  const metrics = { amplitude: NaN, speed: Infinity };
  const pairs = [
    [{ x: 2, y: 3, z: 4 }, { x: 2, y: 3, z: 4 }],
    [[0, 0, 0], [0, 0, 100]],
    [[0, 0, 0], [1e-200, 0, 0]],
    [[-1e308, 1e308, 0], [1e308, -1e308, 0]],
    [null, { x: NaN, y: Infinity, z: -Infinity }],
  ];
  for (const [a, b] of pairs) for (const t of [NaN, -1, 0, .5, 1, 2]) {
    const p = sampleSynapse(a, b, t, metrics, NaN, 'robust', Infinity);
    for (const field of ['x', 'y', 'z']) assert.ok(Number.isFinite(p[field]), `${field}: ${p[field]}`);
  }
  assert.deepEqual(sampleSynapse([2, 3, 4], [2, 3, 4], .5, metrics, 100), { x: 2, y: 3, z: 4 });
});

test('gravity preserves stable typed IDs, rejects absent IDs and handles empty/single graphs', () => {
  assert.equal(gravityTargets().size, 0);
  assert.equal(gravityTargets(null, null).size, 0);
  assert.deepEqual(gravityTargets([{ id: 'solo', recalls: 500 }]), new Map([['solo', { x: 0, y: 0 }]]));
  const targets = gravityTargets([{ id: 0 }, { id: '0' }, {}, null, { id: NaN }]);
  assert.equal(targets.size, 2);
  assert.ok(targets.has(0)); assert.ok(targets.has('0'));
});

test('gravity is deterministic across node/edge/tag order and never mutates frozen input', () => {
  const nodes = deepFreeze([
    { id: 'a', tags: ['伴侣', '生活'], recalls: 3, x: 100, y: 22 },
    { id: 'b', category: '成长', recalls: 32 },
    { id: 'c', tags: ['生活', '伴侣'], recalls: 2 },
    { id: 'd', kind: 'event', recalls: 0 },
  ]);
  const edges = deepFreeze([
    { source: 'a', target: 'b', effective_w: .7 },
    { source: 'c', target: 'a', w: .2 },
    { source: 'b', target: 'c', w: .9 },
    { source: 'absent', target: 'a', w: 1 },
  ]);
  const before = JSON.stringify({ nodes, edges });
  const expected = gravityTargets(nodes, edges);
  assert.deepEqual(gravityTargets([...nodes].reverse(), [...edges].reverse()), expected);
  assert.deepEqual(gravityTargets(nodes.map(n => ({ ...n, tags: n.tags?.slice().reverse() })), edges), expected);
  assert.equal(JSON.stringify({ nodes, edges }), before);
  for (const p of expected.values()) assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y));
});

test('a node moves progressively toward the gravity center with cumulative recalls', () => {
  const edge = { source: 'selected', target: 'other', w: .7 };
  let previous = Infinity;
  for (const recalls of [0, 1, 4, 16, 64, 256]) {
    const targets = gravityTargets([{ id: 'selected', tags: ['生活'], recalls }, { id: 'other', tags: ['生活'], recalls: 20 }], [edge]);
    const radius = distance(targets.get('selected'));
    assert.ok(radius < previous, `radius ${radius} should be < ${previous}`);
    previous = radius;
  }
});
