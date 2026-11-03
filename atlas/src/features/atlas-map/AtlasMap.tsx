import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Activity, Boxes, Brain, Cloud, Cpu, Database, FolderKanban, FolderOpen, Globe, Locate, Search, Wrench, X } from "lucide-react";
import { memo, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Emblem } from "@/components/Emblem";
import { Badge, Button, ErrorNote, Input, Segmented, Spinner, StatusPill, Switch, type Tone } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, permissionLabel, relativeTime, titleCase } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Graph, GraphNode } from "@/lib/schemas";
import { useUi } from "@/state/ui";
import { layout } from "./layout";

const statusTone: Record<string, Tone> = { ok: "ok", warning: "warn", error: "err", idle: "neutral", disabled: "neutral", active: "accent" };

const kindIcon: Record<string, typeof Cloud> = {
  provider: Cloud,
  model: Cpu,
  group: Boxes,
  tool: Wrench,
  integration: Globe,
  memory: Brain,
  storage: Database,
  project: FolderKanban,
  task: Activity,
};

type AtlasNodeData = { g: GraphNode; dimmed: boolean; matched: boolean };

const AtlasNode = memo(function AtlasNode({ data, selected }: NodeProps<Node<AtlasNodeData>>) {
  const g = data.g;
  if (g.kind === "core") {
    return (
      <div className={cn("grid size-36 place-items-center rounded-full border border-line-3 bg-bg-2 shadow-3", g.active && "shadow-[var(--glow-accent)]", data.dimmed && "opacity-40")}>
        <Handle type="target" position={Position.Top} className="!opacity-0" />
        <Handle type="source" position={Position.Bottom} className="!opacity-0" />
        <div className="flex flex-col items-center">
          <Emblem size={58} animated={g.active} />
          <p className="mt-1 font-display text-xs font-semibold tracking-[0.2em]">ATLAS CORE</p>
          <p className="text-[0.625rem] text-text-3">{g.status_label}</p>
        </div>
      </div>
    );
  }
  const Icon = kindIcon[g.kind] ?? FolderOpen;
  const tone = statusTone[g.status] ?? "neutral";
  return (
    <div
      className={cn(
        "w-[188px] rounded-md border bg-bg-2 px-3 py-2 shadow-2 transition-[opacity,box-shadow,border-color] duration-[var(--dur-med)]",
        selected ? "border-accent shadow-[var(--glow-accent)]" : "border-line-2",
        g.active && "border-accent shadow-[var(--glow-accent)]",
        g.status === "disabled" && "opacity-60",
        data.dimmed && "opacity-25",
        data.matched && "ring-2 ring-[color:var(--warn)]",
      )}
    >
      <Handle type="target" position={Position.Top} className="!opacity-0" />
      <Handle type="source" position={Position.Bottom} className="!opacity-0" />
      <div className="flex items-center gap-2">
        <Icon className={cn("size-4 shrink-0", g.kind === "tool" || g.kind === "group" ? "text-accent" : g.kind === "provider" ? "text-info" : "text-accent-teal")} aria-hidden />
        <p className="truncate text-xs font-semibold text-text-1">{g.label}</p>
      </div>
      <div className="mt-1 flex items-center gap-1.5">
        <StatusPill tone={tone} label={g.status_label.length > 26 ? `${g.status_label.slice(0, 25)}…` : g.status_label} pulse={g.active} />
      </div>
      {g.permission && g.permission !== "read_only" && (
        <Badge tone={g.permission === "local_write" ? "warn" : "err"} className="mt-1">
          {permissionLabel[g.permission]}
        </Badge>
      )}
    </div>
  );
});

const nodeTypes = { atlas: AtlasNode };

type KindFilter = "all" | "ai" | "tools" | "data" | "tasks";
const KIND_GROUPS: Record<KindFilter, string[] | null> = {
  all: null,
  ai: ["core", "provider", "model"],
  tools: ["core", "group", "tool", "integration"],
  data: ["core", "memory", "storage", "project"],
  tasks: ["core", "task", "tool", "group"],
};
type StatusFilter = "all" | "attention" | "active";

function Inspector({ g, graph, onClose }: { g: GraphNode; graph: Graph; onClose: () => void }) {
  const ui = useUi();
  const neighbors = graph.edges
    .filter((e) => e.source === g.id || e.target === g.id)
    .map((e) => ({ e, other: graph.nodes.find((n) => n.id === (e.source === g.id ? e.target : e.source)) }))
    .filter((x) => x.other);
  const d = g.details;
  const toolId = typeof d.tool_id === "string" ? d.tool_id : null;
  const [enabled, setEnabled] = useState(g.status !== "disabled");
  useEffect(() => setEnabled(g.status !== "disabled"), [g.status]);

  return (
    <aside aria-label="Node details" className="flex h-full w-[22rem] shrink-0 flex-col border-l border-line-1 bg-bg-2/95 anim-fade">
      <div className="flex items-start gap-2 border-b border-line-1 px-4 py-3">
        <div className="min-w-0 flex-1">
          <p className="text-[0.6875rem] uppercase tracking-wider text-text-3">{titleCase(g.kind)}</p>
          <h2 className="truncate font-display text-md font-semibold">{g.label}</h2>
          <div className="mt-1"><StatusPill tone={statusTone[g.status] ?? "neutral"} label={g.status_label} pulse={g.active} /></div>
        </div>
        <button onClick={onClose} aria-label="Close details" className="rounded-sm p-1 text-text-3 hover:bg-bg-3 hover:text-text-1"><X className="size-4" /></button>
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm">
        {typeof d.description === "string" && <p className="text-text-2">{d.description}</p>}
        <div className="flex flex-wrap gap-1.5">
          {g.permission && <Badge tone={g.permission === "read_only" ? "ok" : g.permission === "local_write" ? "warn" : "err"}>{permissionLabel[g.permission]}</Badge>}
          {g.capabilities.map((c) => <Badge key={c}>{c}</Badge>)}
        </div>
        <dl className="grid grid-cols-[8rem_1fr] gap-x-2 gap-y-1.5 text-xs">
          {Object.entries(d)
            .filter(([k, v]) => k !== "description" && v !== null && v !== "" && !(Array.isArray(v) && v.length === 0))
            .map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="text-text-3">{titleCase(k)}</dt>
                <dd className="break-all text-text-1">
                  {k.endsWith("_at") && typeof v === "string" ? relativeTime(v) : typeof v === "object" ? JSON.stringify(v) : String(v)}
                </dd>
              </div>
            ))}
        </dl>
        <div className="flex flex-wrap gap-2">
          {g.kind === "tool" && toolId && (
            <label className="flex items-center gap-2 text-xs text-text-2">
              <Switch
                checked={enabled}
                label={`Enable ${g.label}`}
                onChange={async (v) => {
                  setEnabled(v);
                  try {
                    await api.setToolEnabled(toolId, v);
                  } catch (e) {
                    setEnabled(!v);
                    toast.error(e instanceof AtlasError ? e.message : String(e));
                  }
                }}
              />
              Enabled
            </label>
          )}
          {(g.kind === "provider" || g.kind === "model" || g.kind === "integration" || (g.kind === "tool" && g.status === "warning")) && (
            <Button size="sm" variant="subtle" onClick={() => ui.navigate("integrations")}>Open setup</Button>
          )}
          {g.kind === "task" && typeof d.task_id === "string" && <Button size="sm" variant="subtle" onClick={() => ui.openTask(d.task_id as string)}>Open in Mission Control</Button>}
          {g.kind === "memory" && <Button size="sm" variant="subtle" onClick={() => ui.navigate("memory")}>Browse memory</Button>}
          {g.kind === "project" && <Button size="sm" variant="subtle" onClick={() => ui.navigate("projects")}>Open projects</Button>}
          {g.id === "workspace" && <Button size="sm" variant="subtle" onClick={() => ui.navigate("files")}>Open files</Button>}
        </div>
        {neighbors.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-semibold text-text-2">Connections</p>
            <ul className="space-y-1 text-xs">
              {neighbors.map(({ e, other }) => (
                <li key={e.id} className="flex items-center gap-2">
                  <span className={cn("size-1.5 rounded-full", e.active ? "bg-accent anim-pulse" : "bg-line-3")} aria-hidden />
                  <span className="text-text-3">{e.kind.replace(/_/g, " ")}</span>
                  <span className="truncate text-text-1">{other!.label}</span>
                  {e.active && <span className="ml-auto text-accent">active</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </aside>
  );
}

function MapCanvas() {
  const graph = useAtlasQuery("graph", api.graph, ["registry", "providers", "tasks", "memory", "projects", "settings", "approvals"]);
  const focus = useUi((s) => s.focusMapNode);
  const [selected, setSelected] = useState<string | null>(focus);
  const [kind, setKind] = useState<KindFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const [listView, setListView] = useState(false);
  const flow = useReactFlow();

  const positioned = useMemo(() => (graph.data ? layout(graph.data) : []), [graph.data]);
  const q = query.trim().toLowerCase();

  const visibleIds = useMemo(() => {
    const allowedKinds = KIND_GROUPS[kind];
    return new Set(
      positioned
        .map((p) => p.node)
        .filter((n) => !allowedKinds || allowedKinds.includes(n.kind))
        .filter((n) => n.kind === "core" || status === "all" || (status === "active" ? n.active : ["warning", "error"].includes(n.status)))
        .map((n) => n.id),
    );
  }, [positioned, kind, status]);

  const neighborIds = useMemo(() => {
    if (!selected || !graph.data) return null;
    const s = new Set([selected]);
    for (const e of graph.data.edges) {
      if (e.source === selected) s.add(e.target);
      if (e.target === selected) s.add(e.source);
    }
    return s;
  }, [selected, graph.data]);

  const nodes: Node<AtlasNodeData>[] = useMemo(
    () =>
      positioned
        .filter((p) => visibleIds.has(p.node.id))
        .map((p) => ({
          id: p.node.id,
          type: "atlas",
          position: { x: p.x - (p.node.kind === "core" ? 72 : 94), y: p.y - (p.node.kind === "core" ? 72 : 28) },
          data: {
            g: p.node,
            dimmed: Boolean(neighborIds && !neighborIds.has(p.node.id)),
            matched: Boolean(q && p.node.label.toLowerCase().includes(q)),
          },
          selected: p.node.id === selected,
          ariaLabel: `${p.node.kind} ${p.node.label}: ${p.node.status_label}`,
        })),
    [positioned, visibleIds, neighborIds, selected, q],
  );

  const edges: Edge[] = useMemo(
    () =>
      (graph.data?.edges ?? [])
        .filter((e) => visibleIds.has(e.source) && visibleIds.has(e.target))
        .map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          className: e.active ? "active" : undefined,
          style: {
            stroke: e.active ? "var(--accent)" : "var(--line-3)",
            strokeWidth: e.active ? 2 : 1,
            opacity: neighborIds ? (neighborIds.has(e.source) && neighborIds.has(e.target) ? 0.95 : 0.08) : e.active ? 1 : e.kind === "uses" || e.kind === "requires" ? 0.25 : 0.55,
          },
          type: "straight",
        })),
    [graph.data, visibleIds, neighborIds],
  );

  useEffect(() => {
    if (focus) setSelected(focus);
  }, [focus]);

  // Center on a node chosen from elsewhere (palette, onboarding).
  useEffect(() => {
    if (!focus || !nodes.length) return;
    const n = nodes.find((x) => x.id === focus);
    if (n) void flow.setCenter(n.position.x + 94, n.position.y + 28, { zoom: 1.1, duration: 400 });
  }, [focus, nodes.length, flow, nodes]);

  const fitMatches = () => {
    const ids = nodes.filter((n) => n.data.matched).map((n) => ({ id: n.id }));
    if (ids.length) void flow.fitView({ nodes: ids, duration: 400, padding: 0.4 });
    else toast("No nodes match that search");
  };

  const sel = graph.data?.nodes.find((n) => n.id === selected);
  const activeCount = graph.data?.edges.filter((e) => e.active).length ?? 0;

  if (graph.error) return <div className="p-8"><ErrorNote message={graph.error.message} onRetry={graph.reload} /></div>;
  if (!graph.data) return <div className="grid h-full place-items-center"><Spinner label="Loading the Atlas Map" /></div>;

  return (
    <div className="flex h-full">
      <div className="relative min-w-0 flex-1">
        <div className="absolute left-4 right-4 top-4 z-10 flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" aria-hidden />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fitMatches()}
              placeholder="Search the map"
              aria-label="Search the map"
              className="w-56 bg-bg-2/95 pl-8 shadow-2"
            />
          </div>
          <div className="shadow-2"><Segmented label="Show" value={kind} onChange={setKind} options={[{ value: "all", label: "Everything" }, { value: "ai", label: "AI" }, { value: "tools", label: "Tools" }, { value: "data", label: "Data" }, { value: "tasks", label: "Tasks" }]} /></div>
          <div className="shadow-2"><Segmented label="Status" value={status} onChange={setStatus} options={[{ value: "all", label: "Any status" }, { value: "attention", label: "Needs attention" }, { value: "active", label: "Active now" }]} /></div>
          <div className="ml-auto flex items-center gap-2">
            {activeCount > 0 && <span className="rounded-md bg-accent-soft px-2 py-1 text-xs text-accent-strong"><span className="anim-pulse">●</span> {activeCount} live {activeCount === 1 ? "path" : "paths"}</span>}
            <Button size="sm" onClick={() => setListView((v) => !v)} aria-pressed={listView}>{listView ? "Hide list" : "List view"}</Button>
            <Button size="sm" icon={<Locate className="size-3.5" aria-hidden />} onClick={() => { setSelected(null); setQuery(""); setKind("all"); setStatus("all"); void flow.fitView({ duration: 400, padding: 0.15 }); }}>Reset</Button>
          </div>
        </div>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, n) => setSelected(n.id)}
          onPaneClick={() => setSelected(null)}
          fitView
          fitViewOptions={{ padding: 0.15 }}
          minZoom={0.15}
          maxZoom={2}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          onlyRenderVisibleElements={nodes.length > 150}
          proOptions={{ hideAttribution: true }}
          aria-label="Atlas Map"
        >
          <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="var(--line-2)" />
          <Controls showInteractive={false} position="bottom-left" />
          <MiniMap
            pannable
            zoomable
            position="bottom-right"
            bgColor="var(--bg-2)"
            nodeColor={(n) => ((n.data as AtlasNodeData).g.active ? "var(--accent)" : "var(--line-3)")}
            maskColor="rgb(4 7 13 / 0.55)"
            ariaLabel="Map overview"
          />
        </ReactFlow>
        {listView && (
          <div className="absolute bottom-4 left-4 top-16 z-10 w-80 overflow-y-auto rounded-lg border border-line-2 bg-bg-2/95 p-2 shadow-3">
            <ul aria-label="All map nodes">
              {nodes.map((n) => (
                <li key={n.id}>
                  <button onClick={() => setSelected(n.id)} className={cn("flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-xs", selected === n.id ? "bg-bg-4" : "hover:bg-bg-3")}>
                    <span className="w-16 shrink-0 text-text-3">{n.data.g.kind}</span>
                    <span className="truncate text-text-1">{n.data.g.label}</span>
                    <span className="ml-auto shrink-0 text-text-3">{n.data.g.status_label.slice(0, 18)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="absolute bottom-4 left-1/2 z-10 -translate-x-1/2 rounded-md bg-bg-2/90 px-2 py-1 text-[0.6875rem] text-text-3">
          {graph.data.nodes.length} nodes · generated from live state {relativeTime(graph.data.generated_at)}
        </p>
      </div>
      {sel && <Inspector g={sel} graph={graph.data} onClose={() => setSelected(null)} />}
    </div>
  );
}

export function AtlasMapPage() {
  return (
    <ReactFlowProvider>
      <MapCanvas />
    </ReactFlowProvider>
  );
}
