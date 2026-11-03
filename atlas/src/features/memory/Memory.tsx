import { Brain, Download, Pencil, Pin, PinOff, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Badge, Button, EmptyState, Field, Input, PageHeader, Panel, Select, Skeleton, Switch, Textarea } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Memory, MemoryKind } from "@/lib/schemas";

const kinds: { value: MemoryKind; label: string }[] = [
  { value: "preference", label: "Preference" },
  { value: "fact", label: "Fact" },
  { value: "note", label: "Note" },
];

function MemoryDialog({ open, onOpenChange, memory }: { open: boolean; onOpenChange: (v: boolean) => void; memory?: Memory }) {
  const projects = useAtlasQuery("projects", () => api.projects(false), ["projects"]);
  const [content, setContent] = useState(memory?.content ?? "");
  const [kind, setKind] = useState<MemoryKind>(memory?.kind ?? "preference");
  const [project, setProject] = useState(memory?.project_id ?? "");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      if (memory) await api.updateMemory(memory.id, { content, kind, projectId: project || null });
      else await api.createMemory({ projectId: project || null, kind, content });
      toast.success("Memory saved");
      onOpenChange(false);
      if (!memory) setContent("");
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={memory ? "Edit memory" : "Add a memory"}
      description="Memories are only used when they're relevant to what you ask. Never store passwords or keys here — Atlas will refuse."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!content.trim()} onClick={save}>Save</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="What should Atlas remember?" htmlFor="mem-c"><Textarea id="mem-c" value={content} maxLength={2000} onChange={(e) => setContent(e.target.value)} rows={3} autoFocus /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Type" htmlFor="mem-k">
            <Select id="mem-k" value={kind} onChange={(e) => setKind(e.target.value as MemoryKind)}>{kinds.map((k) => <option key={k.value} value={k.value}>{k.label}</option>)}</Select>
          </Field>
          <Field label="Scope" htmlFor="mem-p">
            <Select id="mem-p" value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">All conversations</option>
              {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>Only in “{p.name}”</option>)}
            </Select>
          </Field>
        </div>
      </div>
    </Dialog>
  );
}

function MemoryRow({ m, reason, projectName }: { m: Memory; reason?: string; projectName?: string }) {
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);
  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) toast.success(ok);
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : String(e));
    }
  };
  return (
    <li className="group flex items-start gap-3 rounded-lg border border-line-1 bg-bg-2/80 px-4 py-3">
      <Brain className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-text-1">{m.content}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[0.6875rem] text-text-3">
          <Badge tone="accent">{m.kind}</Badge>
          {m.pinned && <Badge tone="info">pinned</Badge>}
          <Badge>{projectName ? `project: ${projectName}` : "all conversations"}</Badge>
          <span>{m.source === "assistant" ? "Saved by Atlas with your approval" : "Added by you"}</span>
          <span>· used {m.use_count}×{m.last_used_at ? `, last ${relativeTime(m.last_used_at)}` : ""}</span>
          {reason && <span className="text-accent-strong">· {reason}</span>}
        </div>
      </div>
      <div className="flex shrink-0 gap-1 opacity-60 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <Button size="sm" variant="ghost" aria-label={m.pinned ? "Unpin" : "Pin (always considered)"} onClick={() => act(() => api.updateMemory(m.id, { pinned: !m.pinned }))}>
          {m.pinned ? <PinOff className="size-3.5" aria-hidden /> : <Pin className="size-3.5" aria-hidden />}
        </Button>
        <Button size="sm" variant="ghost" aria-label="Edit memory" onClick={() => setEdit(true)}><Pencil className="size-3.5" aria-hidden /></Button>
        <Button size="sm" variant="ghost" aria-label="Delete memory" className="text-err" onClick={() => setDel(true)}><Trash2 className="size-3.5" aria-hidden /></Button>
      </div>
      <MemoryDialog open={edit} onOpenChange={setEdit} memory={m} />
      <ConfirmDialog open={del} onOpenChange={setDel} title="Delete this memory?" body={<p>“{m.content}” will be permanently removed, including from search.</p>} confirmLabel="Delete" danger onConfirm={() => act(() => api.deleteMemory(m.id), "Memory deleted")} />
    </li>
  );
}

export function MemoryPage() {
  const [scope, setScope] = useState("all");
  const [q, setQ] = useState("");
  const [add, setAdd] = useState(false);
  const [wipe, setWipe] = useState(false);
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const projects = useAtlasQuery("projects", () => api.projects(true), ["projects"]);
  const list = useAtlasQuery(`memories:${scope}`, () => api.memories(scope), ["memory"]);
  const search = useAtlasQuery(`memsearch:${q}:${scope}`, () => (q.trim().length >= 3 ? api.searchMemories(q, scope !== "all" && scope !== "global" ? scope : null) : Promise.resolve(null)), ["memory"]);
  const pname = (id: string | null) => projects.data?.find((p) => p.id === id)?.name;
  const enabled = settings.data?.memory.enabled ?? true;

  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        eyebrow="The Mind"
        title="Memory"
        subtitle="What Atlas remembers between conversations. Only relevant memories are sent with a request, and you can see why each one was chosen."
        actions={
          <>
            <label className="flex items-center gap-2 text-xs text-text-2">
              <Switch checked={enabled} label="Use memory" onChange={async (v) => { if (settings.data) await api.updateSettings({ ...settings.data, memory: { ...settings.data.memory, enabled: v } }); }} />
              Memory {enabled ? "on" : "off"}
            </label>
            <Button icon={<Download className="size-4" aria-hidden />} onClick={async () => { const p = await api.exportMemories(); if (p) toast.success(`Saved to ${p}`); }}>Export</Button>
            <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={() => setAdd(true)}>Add memory</Button>
          </>
        }
      />
      <div className="space-y-5 px-8 py-6">
        {!enabled && <p className="rounded-md border border-line-2 bg-bg-2 px-3 py-2 text-sm text-text-2">Memory is off: nothing below is used in conversations, and Atlas cannot save new memories.</p>}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-64 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by meaning of the words, e.g. “units” or “garden”" className="pl-8" aria-label="Search memories" />
          </div>
          <Select aria-label="Scope" value={scope} onChange={(e) => setScope(e.target.value)} className="w-56">
            <option value="all">All memories</option>
            <option value="global">Global only</option>
            {(projects.data ?? []).map((p) => <option key={p.id} value={p.id}>Project: {p.name}</option>)}
          </Select>
        </div>
        {search.data ? (
          search.data.length ? (
            <ul className="space-y-2" aria-label="Search results">{search.data.map((r) => <MemoryRow key={r.memory.id} m={r.memory} reason={r.reason} projectName={pname(r.memory.project_id)} />)}</ul>
          ) : (
            <p className="py-8 text-center text-sm text-text-3">No memories match “{q}”.</p>
          )
        ) : list.loading && !list.data ? (
          <div className="space-y-2"><Skeleton className="h-16" /><Skeleton className="h-16" /></div>
        ) : list.data?.length ? (
          <ul className="space-y-2">{list.data.map((m) => <MemoryRow key={m.id} m={m} projectName={pname(m.project_id)} />)}</ul>
        ) : (
          <EmptyState icon={<Brain className="size-5" aria-hidden />} title="Nothing remembered yet" body="Add a preference yourself, or tell Atlas “remember that…” in a conversation — it will ask before saving." action={<Button variant="primary" onClick={() => setAdd(true)}>Add a memory</Button>} />
        )}
        {(list.data?.length ?? 0) > 0 && (
          <Panel className="flex flex-wrap items-center gap-3 p-4">
            <p className="flex-1 text-sm text-text-2">Delete every memory, in every project. This cannot be undone.</p>
            <Button variant="danger" onClick={() => setWipe(true)}>Delete all memories…</Button>
          </Panel>
        )}
      </div>
      <MemoryDialog open={add} onOpenChange={setAdd} />
      <ConfirmDialog
        open={wipe}
        onOpenChange={setWipe}
        title="Delete all memories?"
        body={<p>All {list.data?.length ?? 0} memories will be permanently deleted. Consider exporting them first.</p>}
        confirmLabel="Delete everything"
        danger
        typeToConfirm="DELETE"
        onConfirm={async () => {
          try {
            const n = await api.deleteAllMemories("DELETE");
            toast.success(`Deleted ${n} memories`);
          } catch (e) {
            toast.error(e instanceof AtlasError ? e.message : String(e));
          }
        }}
      />
    </div>
  );
}
