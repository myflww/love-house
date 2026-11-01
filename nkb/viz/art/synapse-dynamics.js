/* Pure geometry/style policy shared by the planar canvas and Three.js renderer.
 * No DOM, randomness, storage, network, mutation, or generated graph data.
 * width is a CSS-pixel intent; amplitude and gravity targets use graph world units.
 * Renderers own visibility, selection emphasis, camera scaling, and animation time.
 */

const TAU = Math.PI * 2;
const LOG_RECALL_CEILING = Math.log1p(256);
const LIFE = Object.freeze({ active: 1, fading: .66, dormant: .28, forgotten: .06 });
const clamp = (n, lo, hi) => Math.max(lo, Math.min(hi, n));
const finite = (n, fallback = 0) => typeof n === 'number' && Number.isFinite(n) ? n : fallback;
const unit = (n, fallback = 0) => clamp(finite(n, fallback), 0, 1);
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;

/** Cumulative recall activity, NOT recalls/month or an inferred time frequency.
 * A fixed log scale avoids changing one edge when unrelated graph nodes arrive.
 * Zero recalls is exactly zero; 256+ cumulative recalls saturate at one.
 */
export function recallActivity(node = {}) {
  return unit(Math.log1p(Math.max(0, finite(node?.recalls))) / LOG_RECALL_CEILING);
}

function associationOf(edge) {
  // effective_w = 0 is meaningful and must never fall through to w.
  return unit(finite(edge?.effective_w, finite(edge?.w, .2)));
}

function lifecycle(value) {
  const level = LIFE[value?.state];
  return typeof level === 'number' ? level : 1;
}

/** Actual edge association is primary; cumulative recall activity is secondary.
 * The less-used endpoint dominates activity, so a busy hub cannot make a never-
 * recalled neighbour appear busy. Each endpoint still contributes monotonically.
 * Lifecycle affects presentation without rewriting the actual association value.
 */
export function synapseMetrics(edge = {}, nodeA = {}, nodeB = {}) {
  const association = associationOf(edge);
  const a = recallActivity(nodeA), b = recallActivity(nodeB);
  const activity = .65 * Math.min(a, b) + .175 * (a + b);
  const life = Math.min(lifecycle(edge), lifecycle(nodeA), lifecycle(nodeB), edge?.active === false ? .28 : 1);
  const stability = unit((association * .84 + activity * .16) * (.3 + life * .7));
  return {
    association,
    activity,
    stability,
    width: .42 + (.14 + Math.pow(association, 1.6) * 2.7 + activity * .42) * Math.pow(life, .65),
    alpha: (.035 + Math.pow(association, 1.15) * .48 + activity * .15) * life,
    amplitude: 1.6 + Math.pow(1 - stability, 1.65) * 38,
    speed: .23 + (1 - stability) * .8,
  };
}

function hash(value) {
  const text = typeof value === 'string' ? value : typeof value === 'number' ? String(finite(value)) : '0';
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return (h >>> 0) / 4294967296;
}

function point(value, fallback = { x: 0, y: 0, z: 0 }) {
  return Array.isArray(value) || ArrayBuffer.isView(value)
    ? { x: finite(value[0], fallback.x), y: finite(value[1], fallback.y), z: finite(value[2], fallback.z) }
    : { x: finite(value?.x, fallback.x), y: finite(value?.y, fallback.y), z: finite(value?.z, fallback.z) };
}

/** Sample a soft three-dimensional fibre. Plain objects, Three.Vector3 values,
 * arrays and typed tuples are accepted; a fresh plain {x,y,z} is returned.
 * Endpoints stay exactly anchored for every time/seed/strand. Coincident points
 * stay coincident. The endpoint envelope caps bends for very short connections.
 * Freeze the supplied time to pause; no internal clock or mutable cache exists.
 */
export function sampleSynapse(start, end, t, metrics = {}, time = 0, seed = 0, strand = 0) {
  const a = point(start), b = point(end, a), u = unit(t);
  if (u === 0) return a;
  if (u === 1) return b;
  const scale = Math.max(Math.abs(a.x), Math.abs(a.y), Math.abs(a.z), Math.abs(b.x), Math.abs(b.y), Math.abs(b.z), 1);
  const dx = b.x / scale - a.x / scale, dy = b.y / scale - a.y / scale, dz = b.z / scale - a.z / scale;
  const length = Math.hypot(dx, dy, dz);
  if (!length) return a;
  const ex = dx / length, ey = dy / length, ez = dz / length;
  const xy = Math.hypot(ex, ey);
  const nx = xy > 1e-10 ? -ey / xy : 1;
  const ny = xy > 1e-10 ? ex / xy : 0;
  const nz = 0;
  const bx = -ez * ny, by = ez * nx, bz = ex * ny - ey * nx;
  const amplitude = Math.min(clamp(finite(metrics?.amplitude, 12), 0, 1000), length * scale * .22);
  const speed = clamp(finite(metrics?.speed, .5), 0, 4);
  const clock = clamp(finite(time), -1e9, 1e9) * speed;
  const phase = hash(seed) * TAU;
  const strandOffset = clamp(finite(strand), -8, 8);
  const envelope = Math.pow(Math.sin(Math.PI * u), 1.2);
  const wave = Math.sin(u * TAU * 1.1 + clock + phase) * .65
    + Math.sin(u * TAU * 2.3 - clock * .63 + phase * 1.7) * .35;
  const bend = (wave + Math.sin(phase * 3) * .28 + strandOffset * .13) * amplitude * envelope;
  const depth = Math.sin(u * TAU * .8 - clock * .47 + phase * 1.3) * amplitude * envelope * .32;
  const base = { x: a.x * (1 - u) + b.x * u, y: a.y * (1 - u) + b.y * u, z: a.z * (1 - u) + b.z * u };
  return {
    x: finite(base.x + nx * bend + bx * depth, base.x),
    y: finite(base.y + ny * bend + by * depth, base.y),
    z: finite(base.z + nz * bend + bz * depth, base.z),
  };
}

function stableId(node) {
  const id = node?.id;
  return typeof id === 'string' || typeof id === 'number' && Number.isFinite(id) ? id : undefined;
}

function idKey(id) {
  return `${typeof id}:${String(id)}`;
}

function categoryOf(node) {
  if (typeof node?.category === 'string' && node.category.trim()) return node.category.trim();
  const tags = Array.isArray(node?.tags)
    ? node.tags.filter(t => typeof t === 'string' && t.trim()).map(t => t.trim()).sort(compare)
    : [];
  if (tags.length) return tags[0];
  return typeof node?.kind === 'string' && node.kind.trim() ? node.kind.trim() : '未分类';
}

/** Deterministic radial gravity targets in existing graph WORLD units.
 * Radius grows as max(90, sqrt(N)*23), around (0,0); renderers should use their
 * existing viewport policy to fit. More cumulative recalls always pull the same
 * node inward. Category / canonical tag / kind choose stable angular sectors.
 * Real weighted degree adds at most 7% inward pull. Original typed IDs are kept
 * as Map keys, no IDs/edges are invented, and input nodes/edges are never changed.
 * Sorting by stable IDs makes results independent of input array/edge order.
 */
export function gravityTargets(nodes = [], edges = []) {
  const byId = new Map();
  for (const node of Array.isArray(nodes) ? nodes : []) {
    const id = stableId(node);
    if (id !== undefined && !byId.has(id)) byId.set(id, node);
  }
  const targets = new Map();
  if (!byId.size) return targets;
  const sorted = [...byId].sort(([a], [b]) => compare(idKey(a), idKey(b)));
  if (sorted.length === 1) {
    targets.set(sorted[0][0], { x: 0, y: 0 });
    return targets;
  }
  const degree = new Map(sorted.map(([id]) => [id, 0]));
  // Sort contributions too: floating-point summation must not depend on edge order.
  const contributions = (Array.isArray(edges) ? edges : []).map(edge => ({
    a: edge?.source, b: edge?.target, weight: associationOf(edge),
  })).filter(e => e.a !== e.b && byId.has(e.a) && byId.has(e.b)).sort((a, b) =>
    compare(idKey(a.a), idKey(b.a)) || compare(idKey(a.b), idKey(b.b)) || a.weight - b.weight);
  for (const edge of contributions) {
    degree.set(edge.a, degree.get(edge.a) + edge.weight);
    degree.set(edge.b, degree.get(edge.b) + edge.weight);
  }
  let maxDegree = 1;
  for (const value of degree.values()) maxDegree = Math.max(maxDegree, value);
  const sectors = new Map();
  for (const [id, node] of sorted) {
    const category = categoryOf(node);
    if (!sectors.has(category)) sectors.set(category, []);
    sectors.get(category).push([id, node]);
  }
  const categories = [...sectors.keys()].sort(compare);
  const maxRadius = Math.max(90, Math.sqrt(sorted.length) * 23);
  categories.forEach((category, sector) => {
    const members = sectors.get(category), span = TAU / categories.length;
    members.forEach(([id, node], index) => {
      const local = (index + .5) / members.length - .5;
      const angle = -Math.PI / 2 + sector * span + local * span * (categories.length === 1 ? .98 : .78);
      const activity = recallActivity(node);
      // A stable radial offset avoids merging similarly active memories into a
      // single dense arc. For each fixed ID, more recalls still pull inward.
      const radialJitter = .78 + hash(`${idKey(id)}:radius`) * .44;
      const topologyPull = 1 - .07 * degree.get(id) / maxDegree;
      const radius = maxRadius * (.16 + .78 * Math.pow(1 - activity, .85)) * radialJitter * topologyPull;
      targets.set(id, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius });
    });
  });
  return targets;
}
