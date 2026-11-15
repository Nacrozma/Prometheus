import { Archive, Brain, CheckCircle2, Download, Pencil, Pin, PinOff, Plus, Replace, RotateCcw, Search, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Badge, Button, EmptyState, Field, Input, PageHeader, Panel, Select, Skeleton, Switch, Textarea } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, relativeTime } from "@/lib/format";
import { useUi } from "@/state/ui";
import { useAtlasQuery } from "@/lib/query";
import type { Memory, MemoryKind } from "@/lib/schemas";

const kinds: { value: MemoryKind; label: string }[] = [
  { value: "preference", label: "Preference" },
  { value: "fact", label: "Fact" },
  { value: "note", label: "Note" },
];

/** Before saving: what Atlas already remembers that says the same thing, or might conflict. */
function SimilarWarning({ content, projectId, except }: { content: string; projectId: string | null; except: string | null }) {
  const [debounced, setDebounced] = useState(content);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(content), 300);
    return () => clearTimeout(t);
  }, [content]);
  const q = debounced.trim();
  const sim = useAtlasQuery(`memsimilar:${projectId}:${except}:${q}`, () => (q.length >= 10 ? api.memorySimilar(q, projectId, except) : Promise.resolve([])), ["memory"]);
  const first = sim.data?.[0];
  if (!first) return null;
  return (
    <p className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-text-1" data-memory-similar={first.relation}>
      {first.relation === "duplicate" ? "Atlas already remembers this: " : "This may conflict with what Atlas remembers: "}“{first.memory.content}”.
      {first.relation === "related" && " If this is the newer version, use Replace on that memory instead, so only the new one is used."}
    </p>
  );
}

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
        <SimilarWarning content={content} projectId={project || null} except={memory?.id ?? null} />
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

const STATUS: Record<Memory["status"], { label: string; tone: "warn" | "neutral" | "info" } | null> = {
  active: null,
  needs_review: { label: "Needs review", tone: "warn" },
  outdated: { label: "Outdated: not used", tone: "neutral" },
  superseded: { label: "Replaced: not used", tone: "neutral" },
};

const HISTORY_LABEL: Record<string, string> = {
  created: "Saved",
  edited: "Corrected",
  confirmed: "Confirmed still true",
  marked_outdated: "Marked outdated",
  superseded: "Replaced by a newer memory",
  restored: "Restored",
  review_due: "Due for review (not confirmed for a long time)",
};

function History({ id }: { id: string }) {
  const h = useAtlasQuery(`memhistory:${id}`, () => api.memoryHistory(id), ["memory"]);
  if (!h.data) return <Skeleton className="mt-2 h-10" />;
  return (
    <ol className="mt-2 space-y-1 border-l border-line-2 pl-3 text-xs text-text-2" aria-label="Memory history" data-memory-history>
      {h.data.map((e, i) => (
        <li key={i}>
          <span className="text-text-1">{HISTORY_LABEL[e.action] ?? e.action}</span> · {relativeTime(e.ts)} · {e.actor === "assistant" ? "by Atlas (approved by you)" : e.actor === "atlas" ? "automatically" : "by you"}
          {e.action === "edited" && e.old_content && <span className="block text-text-3">was: “{e.old_content}”</span>}
        </li>
      ))}
    </ol>
  );
}

function ReplaceDialog({ m, open, onOpenChange }: { m: Memory; open: boolean; onOpenChange: (v: boolean) => void }) {
  const [content, setContent] = useState(m.content);
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Replace with a newer version"
      description="The current memory stays in Memory, marked as replaced, and is no longer used. The new one is used from now on."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={!content.trim() || content.trim() === m.content}
            onClick={async () => {
              setBusy(true);
              try {
                await api.replaceMemory(m.id, content);
                toast.success("Memory replaced");
                onOpenChange(false);
              } catch (e) {
                toast.error(e instanceof AtlasError ? e.message : String(e));
              } finally {
                setBusy(false);
              }
            }}
          >
            Replace
          </Button>
        </>
      }
    >
      <Field label="New version" htmlFor={`rep-${m.id}`}>
        <Textarea id={`rep-${m.id}`} value={content} maxLength={2000} rows={3} onChange={(e) => setContent(e.target.value)} autoFocus />
      </Field>
    </Dialog>
  );
}

function MemoryRow({ m, reason, projectName }: { m: Memory; reason?: string; projectName?: string }) {
  const [edit, setEdit] = useState(false);
  const [del, setDel] = useState(false);
  const [replace, setReplace] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const ui = useUi();
  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) toast.success(ok);
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : String(e));
    }
  };
  const status = STATUS[m.status];
  const inactive = m.status === "outdated" || m.status === "superseded";
  return (
    <li className={cn("group flex items-start gap-3 rounded-lg border border-line-1 bg-bg-2/80 px-4 py-3", inactive && "opacity-70")} data-memory={m.content} data-memory-status={m.status}>
      <Brain className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className={cn("text-sm text-text-1", inactive && "line-through decoration-text-3")}>{m.content}</p>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[0.6875rem] text-text-3">
          {status && <Badge tone={status.tone}>{status.label}</Badge>}
          <Badge tone="accent">{m.kind}</Badge>
          {m.pinned && <Badge tone="info">pinned</Badge>}
          <Badge>{projectName ? `project: ${projectName}` : "all conversations"}</Badge>
          <span>{m.source === "assistant" ? "Suggested by Atlas, approved by you" : "Added by you"}</span>
          {m.confirmed_at && <span>· confirmed {relativeTime(m.confirmed_at)}</span>}
          <span>· used {m.use_count}×{m.last_used_at ? `, last ${relativeTime(m.last_used_at)}` : ""}</span>
          {m.conversation_id && (
            <button type="button" className="text-accent hover:underline" onClick={() => ui.openConversation(m.conversation_id)}>
              · from a conversation
            </button>
          )}
          {reason && <span className="text-accent-strong">· {reason}</span>}
          <button type="button" className="hover:text-text-1" aria-expanded={showHistory} onClick={() => setShowHistory((v) => !v)}>
            · history
          </button>
        </div>
        {m.status === "needs_review" && <p className="mt-1 text-xs text-warn">Not confirmed for a long time. Atlas still uses it but says it may be out of date. Is it still true?</p>}
        {showHistory && <History id={m.id} />}
      </div>
      <div className="flex shrink-0 flex-wrap justify-end gap-1 opacity-70 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {inactive ? (
          <Button size="sm" variant="ghost" aria-label={`Restore memory: ${m.content}`} onClick={() => act(() => api.restoreMemory(m.id), "Restored")}><RotateCcw className="size-3.5" aria-hidden /></Button>
        ) : (
          <>
            <Button size="sm" variant="ghost" aria-label={`Still true: ${m.content}`} onClick={() => act(() => api.confirmMemory(m.id), "Confirmed")}><CheckCircle2 className="size-3.5" aria-hidden /></Button>
            <Button size="sm" variant="ghost" aria-label={`Replace memory: ${m.content}`} onClick={() => setReplace(true)}><Replace className="size-3.5" aria-hidden /></Button>
            <Button size="sm" variant="ghost" aria-label={`Mark outdated: ${m.content}`} onClick={() => act(() => api.markMemoryOutdated(m.id), "Marked outdated: Atlas will not use it")}><Archive className="size-3.5" aria-hidden /></Button>
            <Button size="sm" variant="ghost" aria-label={m.pinned ? "Unpin" : "Pin (always considered)"} onClick={() => act(() => api.updateMemory(m.id, { pinned: !m.pinned }))}>
              {m.pinned ? <PinOff className="size-3.5" aria-hidden /> : <Pin className="size-3.5" aria-hidden />}
            </Button>
            <Button size="sm" variant="ghost" aria-label={`Edit memory: ${m.content}`} onClick={() => setEdit(true)}><Pencil className="size-3.5" aria-hidden /></Button>
          </>
        )}
        <Button size="sm" variant="ghost" aria-label={`Delete memory: ${m.content}`} className="text-err" onClick={() => setDel(true)}><Trash2 className="size-3.5" aria-hidden /></Button>
      </div>
      <MemoryDialog open={edit} onOpenChange={setEdit} memory={m} />
      <ReplaceDialog m={m} open={replace} onOpenChange={setReplace} />
      <ConfirmDialog
        open={del}
        onOpenChange={setDel}
        title="Delete this memory?"
        body={<p>“{m.content}” is removed from Memory, from search and from its history, and is never used again. The activity log keeps only the fact that a memory was deleted, never its text. Database backups made before today still contain it until you delete them.</p>}
        confirmLabel="Delete"
        danger
        onConfirm={() => act(() => api.deleteMemory(m.id), "Memory deleted")}
      />
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
  const [status, setStatus] = useState<"all" | "needs_review" | "active" | "inactive">("all");
  const all = list.data ?? [];
  const counts = {
    active: all.filter((m) => m.status === "active").length,
    needs_review: all.filter((m) => m.status === "needs_review").length,
    inactive: all.filter((m) => m.status === "outdated" || m.status === "superseded").length,
    atlas: all.filter((m) => m.source === "assistant").length,
  };
  const shown = all.filter((m) => status === "all" || (status === "inactive" ? m.status === "outdated" || m.status === "superseded" : m.status === status));
  const proposals = settings.data?.memory.atlas_may_propose ?? true;

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
        <div className="grid gap-3 sm:grid-cols-4" data-memory-overview>
          {(
            [
              ["In use", counts.active, "active"],
              ["Needs review", counts.needs_review, "needs_review"],
              ["Outdated or replaced", counts.inactive, "inactive"],
              ["Suggested by Atlas", counts.atlas, "all"],
            ] as const
          ).map(([label, n, key]) => (
            <button key={label} type="button" onClick={() => setStatus(key)} className={cn("rounded-lg border border-line-2 bg-bg-2/70 px-4 py-3 text-left hover:border-accent/50", status === key && key !== "all" && "border-accent/60")}>
              <p className="text-xs text-text-3">{label}</p>
              <p className="mt-1 font-display text-lg font-semibold">{n}</p>
            </button>
          ))}
        </div>
        <Panel className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 text-sm">
          <label className="flex items-center gap-2">
            <Switch checked={proposals} label="Memory suggestions from Atlas" onChange={async (v) => { if (settings.data) await api.updateSettings({ ...settings.data, memory: { ...settings.data.memory, atlas_may_propose: v } }); }} />
            Atlas may suggest memories
          </label>
          <p className="min-w-64 flex-1 text-xs text-text-3">
            Atlas never saves anything on its own: each suggestion asks you first. Memory holds short things worth remembering about you and your work; your documents live in the Knowledge Vault and are never turned into memories.
          </p>
        </Panel>
        <div className="flex gap-1" role="group" aria-label="Show memories">
          {(
            [
              ["all", "All"],
              ["needs_review", "Needs review"],
              ["active", "In use"],
              ["inactive", "Outdated or replaced"],
            ] as const
          ).map(([k, label]) => (
            <Button key={k} size="sm" variant={status === k ? "primary" : "ghost"} aria-pressed={status === k} onClick={() => setStatus(k)}>
              {label}
            </Button>
          ))}
        </div>
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
        ) : shown.length ? (
          <ul className="space-y-2">{shown.map((m) => <MemoryRow key={m.id} m={m} projectName={pname(m.project_id)} />)}</ul>
        ) : all.length ? (
          <p className="py-8 text-center text-sm text-text-3">No memories in this view.</p>
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
