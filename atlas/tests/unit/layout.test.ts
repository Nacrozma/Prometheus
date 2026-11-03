import { describe, expect, it } from "vitest";
import { layout } from "@/features/atlas-map/layout";
import type { Graph, GraphNode } from "@/lib/schemas";

const node = (id: string, kind: string): GraphNode => ({
  id,
  label: id,
  kind,
  status: "ok",
  status_label: "ok",
  category: kind,
  permission: null,
  capabilities: [],
  details: {},
  active: false,
});

function graph(): Graph {
  const nodes: GraphNode[] = [node("core", "core")];
  const edges: Graph["edges"] = [];
  const add = (id: string, kind: string, parent: string) => {
    nodes.push(node(id, kind));
    edges.push({ id: `${parent}->${id}`, source: parent, target: id, kind: "x", active: false });
  };
  for (let p = 0; p < 3; p++) {
    add(`provider:${p}`, "provider", "core");
    for (let m = 0; m < 5; m++) add(`model:${p}:${m}`, "model", `provider:${p}`);
  }
  for (let g = 0; g < 8; g++) {
    add(`group:${g}`, "group", "core");
    for (let t = 0; t < 3; t++) add(`tool:${g}.${t}`, "tool", `group:${g}`);
  }
  for (let t = 0; t < 6; t++) add(`task:${t}`, "task", "core");
  for (const id of ["memory", "storage", "workspace"]) add(id, id === "memory" ? "memory" : "storage", "core");
  for (let p = 0; p < 4; p++) add(`project:${p}`, "project", "core");
  return { nodes, edges, generated_at: "" };
}

describe("map layout", () => {
  it("places every node exactly once", () => {
    const g = graph();
    const placed = layout(g);
    expect(placed).toHaveLength(g.nodes.length);
    expect(new Set(placed.map((p) => p.node.id)).size).toBe(g.nodes.length);
  });

  it("produces no overlapping cards for a realistic graph", () => {
    const placed = layout(graph());
    const overlaps: string[] = [];
    for (let i = 0; i < placed.length; i++)
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i]!;
        const b = placed[j]!;
        const w = (a.node.kind === "core" ? 150 : 188) / 2 + (b.node.kind === "core" ? 150 : 188) / 2;
        const h = (a.node.kind === "core" ? 150 : 60) / 2 + (b.node.kind === "core" ? 150 : 60) / 2;
        if (Math.abs(a.x - b.x) < w && Math.abs(a.y - b.y) < h) overlaps.push(`${a.node.id}/${b.node.id}`);
      }
    expect(overlaps).toEqual([]);
  });

  it("keeps the core at the centre and is deterministic", () => {
    const a = layout(graph());
    const b = layout(graph());
    expect(a.find((p) => p.node.id === "core")).toMatchObject({ x: 0, y: 0 });
    expect(a).toEqual(b);
  });
});
