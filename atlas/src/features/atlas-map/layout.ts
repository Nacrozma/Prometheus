import type { Graph, GraphNode } from "@/lib/schemas";

export interface Positioned {
  node: GraphNode;
  x: number;
  y: number;
}

const rad = (deg: number) => (deg * Math.PI) / 180;
const at = (r: number, deg: number) => ({ x: r * Math.cos(rad(deg)), y: r * Math.sin(rad(deg)) });

function spread(count: number, from: number, to: number): number[] {
  if (count <= 0) return [];
  if (count === 1) return [(from + to) / 2];
  const step = (to - from) / (count - 1);
  return Array.from({ length: count }, (_, i) => from + i * step);
}

/**
 * Deterministic radial layout. Angles in degrees, 0 = east, clockwise (screen y grows down).
 * Sectors: providers top, tasks right, tool groups bottom, memory/storage/projects left.
 * Children (models, tools) fan out at a larger radius around their parent.
 */
export function layout(graph: Graph): Positioned[] {
  const out: Positioned[] = [];
  const byId = new Map(graph.nodes.map((n) => [n.id, n]));
  const childrenOf = (id: string, kind: string) =>
    graph.edges.filter((e) => e.source === id && byId.get(e.target)?.kind === kind).map((e) => byId.get(e.target)!);

  const core = graph.nodes.find((n) => n.kind === "core");
  if (core) out.push({ node: core, x: 0, y: 0 });

  const placeRing = (nodes: GraphNode[], from: number, to: number, r: number, childKind?: string, childR = r + 250, childSpan = 0) => {
    const angles = spread(nodes.length, from, to);
    const span = childSpan || (nodes.length ? Math.abs(to - from) / Math.max(nodes.length, 1) : 0);
    nodes.forEach((n, i) => {
      const a = angles[i]!;
      out.push({ node: n, ...at(r, a) });
      if (childKind) {
        const kids = childrenOf(n.id, childKind);
        const kidAngles = spread(kids.length, a - span * 0.45, a + span * 0.45);
        kids.forEach((k, j) => {
          // Alternate radii for dense fans so cards do not overlap.
          const rr = childR + (kids.length > 4 ? (j % 2) * 120 : 0);
          out.push({ node: k, ...at(rr, kidAngles[j]!) });
        });
      }
    });
  };

  const providers = graph.nodes.filter((n) => n.kind === "provider");
  const groups = graph.nodes.filter((n) => n.kind === "group");
  const tasks = graph.nodes.filter((n) => n.kind === "task");
  const left = graph.nodes.filter((n) => ["memory", "storage", "project"].includes(n.kind));
  const siblings = graph.nodes.filter((n) => n.kind === "sibling");
  const missions = graph.nodes.filter((n) => n.kind === "mission");
  const forge = graph.nodes.filter((n) => n.kind === "forge_project");

  placeRing(providers, 225, 315, 340, "model", 600);
  placeRing(groups, 40, 140, 420, "tool", 760);
  placeRing(tasks, -35, 35, 520);
  placeRing(left, 150, 210, 520);
  // Siblings sit below the core, apart from Atlas's own parts; missions between them and the core.
  placeRing(siblings, 80, 100, 700);
  placeRing(missions, 60, 120, 380);
  placeRing(forge, 215, 235, 560);

  // Integrations sit beyond the tools that require them.
  const placed = new Map(out.map((p) => [p.node.id, p]));
  graph.nodes
    .filter((n) => n.kind === "integration")
    .forEach((n, i) => {
      const requiring = graph.edges.filter((e) => e.target === n.id).map((e) => placed.get(e.source)).filter(Boolean) as Positioned[];
      if (requiring.length) {
        const p = requiring[0]!;
        const len = Math.hypot(p.x, p.y) || 1;
        out.push({ node: n, x: (p.x / len) * (len + 280), y: (p.y / len) * (len + 280) });
      } else {
        out.push({ node: n, ...at(900, 90 + i * 12) });
      }
    });

  // Anything not yet placed (future node kinds) goes on an outer ring rather than disappearing.
  const done = new Set(out.map((p) => p.node.id));
  const rest = graph.nodes.filter((n) => !done.has(n.id));
  spread(rest.length, 0, 330).forEach((a, i) => out.push({ node: rest[i]!, ...at(1100, a) }));
  return relax(out);
}

/** Card footprint used for overlap checks (node width 188, height ~64, plus margin). */
const W = 210;
const H = 84;
const CORE = 170;

/**
 * Push overlapping cards apart. Deterministic (fixed iteration order), keeps the core fixed,
 * and preserves the overall radial arrangement.
 */
export function relax(items: Positioned[], iterations = 60): Positioned[] {
  const pts = items.map((p) => ({ ...p }));
  for (let it = 0; it < iterations; it++) {
    let moved = false;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const a = pts[i]!;
        const b = pts[j]!;
        const wa = a.node.kind === "core" ? CORE : W;
        const wb = b.node.kind === "core" ? CORE : W;
        const ha = a.node.kind === "core" ? CORE : H;
        const hb = b.node.kind === "core" ? CORE : H;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const ox = (wa + wb) / 2 - Math.abs(dx);
        const oy = (ha + hb) / 2 - Math.abs(dy);
        if (ox <= 0 || oy <= 0) continue;
        moved = true;
        // Resolve along the axis of least overlap; split the move unless one side is the core.
        const aFixed = a.node.kind === "core";
        const bFixed = b.node.kind === "core";
        const share = aFixed ? 0 : bFixed ? 1 : 0.5;
        if (ox < oy) {
          const push = (ox + 1) * Math.sign(dx || (j % 2 ? 1 : -1));
          a.x -= push * share;
          b.x += push * (1 - share);
        } else {
          const push = (oy + 1) * Math.sign(dy || (j % 2 ? 1 : -1));
          a.y -= push * share;
          b.y += push * (1 - share);
        }
      }
    }
    if (!moved) break;
  }
  return pts;
}
