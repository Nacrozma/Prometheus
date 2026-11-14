import { AlertTriangle, BookOpen, FileText, FolderInput, Library, Loader2, RefreshCw, Search, Trash2, Upload, X } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Badge, Button, EmptyState, Field, Input, PageHeader, Panel, Select, Skeleton, Switch, type Tone } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, formatBytes, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { VaultCandidate, VaultDocument, VaultHit, VaultLibrary } from "@/lib/schemas";
import { useUi } from "@/state/ui";

const KINDS = [
  { value: "pdf", label: "PDF" },
  { value: "docx", label: "Word" },
  { value: "md", label: "Markdown" },
  { value: "txt", label: "Text" },
] as const;

const STATUS: Record<VaultDocument["status"], { label: string; tone: Tone }> = {
  imported: { label: "Imported", tone: "neutral" },
  processing: { label: "Processing", tone: "accent" },
  indexed: { label: "Indexed", tone: "ok" },
  needs_reindex: { label: "Needs re-indexing", tone: "warn" },
  failed: { label: "Failed", tone: "err" },
};

const errText = (e: unknown, fallback: string) => (e instanceof AtlasError ? e.message : fallback);

/** Where a passage is, in words ("page 3", "Budget › Travel"). Never invented: only what was stored. */
export function locationLabel(page: number | null, heading: string): string {
  if (page != null && heading) return `page ${page} · ${heading}`;
  if (page != null) return `page ${page}`;
  return heading || "no page or heading";
}

/**
 * A search snippet with its matches highlighted. The core marks matches with U+0002…U+0003; the
 * text is rendered as text (never as HTML), so nothing from a document can become markup.
 */
export function snippetParts(text: string): { text: string; match: boolean }[] {
  const START = String.fromCharCode(2);
  const END = String.fromCharCode(3);
  const out: { text: string; match: boolean }[] = [];
  let rest = text;
  while (rest.length) {
    const a = rest.indexOf(START);
    if (a < 0) {
      out.push({ text: rest, match: false });
      break;
    }
    if (a > 0) out.push({ text: rest.slice(0, a), match: false });
    const b = rest.indexOf(END, a + 1);
    if (b < 0) {
      out.push({ text: rest.slice(a + 1), match: false });
      break;
    }
    out.push({ text: rest.slice(a + 1, b), match: true });
    rest = rest.slice(b + 1);
  }
  return out;
}

export function Snippet({ text }: { text: string }) {
  return (
    <>
      {snippetParts(text).map((p, i) =>
        p.match ? (
          <mark key={i} className="rounded-sm bg-accent/25 px-0.5 text-text-1">
            {p.text}
          </mark>
        ) : (
          <Fragment key={i}>{p.text}</Fragment>
        ),
      )}
    </>
  );
}

function libraryFromValue(v: string): VaultLibrary {
  if (v === "all") return { kind: "all" };
  if (v === "personal") return { kind: "personal" };
  return { kind: "project", project_id: v };
}

function ImportDialog({ open, onOpenChange, candidates, defaultProject }: { open: boolean; onOpenChange: (v: boolean) => void; candidates: VaultCandidate[]; defaultProject: string }) {
  const projects = useAtlasQuery("projects", () => api.projects(false), ["projects"]);
  const [project, setProject] = useState(defaultProject);
  const [busy, setBusy] = useState(false);
  const ok = candidates.filter((c) => !c.problem);
  useEffect(() => {
    if (open) setProject(defaultProject);
  }, [open, defaultProject]);
  const run = async () => {
    setBusy(true);
    try {
      const r = await api.vaultImport(
        ok.map((c) => c.path),
        project || null,
      );
      const done = r.filter((x) => x.document).length;
      const failed = r.filter((x) => x.error);
      if (done) toast.success(`${done} ${done === 1 ? "document" : "documents"} imported`, { description: "Processing in the background. Each is searchable once it shows Indexed." });
      for (const f of failed) toast.error(f.path.split(/[\\/]/).pop() ?? f.path, { description: f.error ?? "Not imported" });
      onOpenChange(false);
    } catch (e) {
      toast.error(errText(e, "The documents could not be imported"));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Import documents"
      description="Atlas keeps its own copy and reads it on this computer. Your original files are never changed. Text in documents is treated as information, never as instructions."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} disabled={!ok.length} onClick={run}>
            Import {ok.length || ""}
          </Button>
        </>
      }
    >
      <div className="space-y-4" data-vault-import>
        <ul className="max-h-64 space-y-1.5 overflow-auto">
          {candidates.map((c) => (
            <li key={c.path} className="flex items-center gap-3 rounded-md border border-line-2 bg-bg-3/50 px-3 py-2 text-sm" data-candidate={c.problem ? "refused" : "ok"}>
              <FileText className="size-4 shrink-0 text-text-3" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{c.file_name}</span>
              <span className="shrink-0 text-xs uppercase text-text-3">{c.kind ?? "?"}</span>
              <span className="w-16 shrink-0 text-right text-xs text-text-3">{formatBytes(c.size_bytes)}</span>
              {c.problem && <span className="shrink-0 text-xs text-danger">{c.problem}</span>}
            </li>
          ))}
        </ul>
        <Field label="Library" htmlFor="vault-import-project" hint="The personal library is available in every conversation; a project's library only in that project.">
          <Select id="vault-import-project" value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">Personal library</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                Project: {p.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
    </Dialog>
  );
}

function MoveDialog({ doc, onOpenChange }: { doc: VaultDocument | null; onOpenChange: (v: boolean) => void }) {
  const projects = useAtlasQuery("projects", () => api.projects(false), ["projects"]);
  const [target, setTarget] = useState("");
  useEffect(() => setTarget(doc?.project_id ?? ""), [doc]);
  return (
    <Dialog
      open={!!doc}
      onOpenChange={onOpenChange}
      title="Move to another library"
      description="The document keeps its passages and history; only where it can be used changes."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!doc || target === (doc.project_id ?? "")}
            onClick={async () => {
              if (!doc) return;
              try {
                await api.vaultMove(doc.id, target || null);
                toast.success("Moved");
                onOpenChange(false);
              } catch (e) {
                toast.error(errText(e, "The document could not be moved"));
              }
            }}
          >
            Move
          </Button>
        </>
      }
    >
      <Field label="Library" htmlFor="vault-move-target">
        <Select id="vault-move-target" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Personal library</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              Project: {p.name}
            </option>
          ))}
        </Select>
      </Field>
    </Dialog>
  );
}

/** The extracted text, passage by passage, opened at a cited passage when there is one. */
function Reader({ target, onClose }: { target: { documentId: string; chunkId: string | null; page: number | null; heading: string } | null; onClose: () => void }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.vaultReader>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setData(null);
    setError(null);
    if (!target) return;
    api.vaultReader(target.documentId).then(setData, (e) => setError(errText(e, "The document could not be opened")));
  }, [target]);
  // The cited passage: by id; if the document was re-indexed since, the first passage at the same
  // page and heading (never a guess beyond that).
  const focusId = useMemo(() => {
    if (!data || !target) return null;
    if (target.chunkId && data.parts.some((p) => p.chunk_id === target.chunkId)) return target.chunkId;
    if (target.page != null || target.heading) return data.parts.find((p) => p.page === target.page && p.heading === target.heading)?.chunk_id ?? null;
    return null;
  }, [data, target]);
  useEffect(() => {
    if (!focusId) return;
    const el = box.current?.querySelector(`[data-chunk="${CSS.escape(focusId)}"]`);
    (el as HTMLElement | null)?.scrollIntoView?.({ block: "center" });
  }, [focusId]);
  const d = data?.document;
  return (
    <Dialog open={!!target} onOpenChange={(v) => !v && onClose()} title={d?.title ?? "Document"} description={d ? `${d.file_name} · ${d.kind.toUpperCase()} · ${formatBytes(d.size_bytes)}${d.pages ? ` · ${d.pages} pages` : ""} · ${d.chunks} passages` : undefined} width="max-w-3xl">
      <div ref={box} className="max-h-[60vh] space-y-3 overflow-auto pr-1" data-vault-reader>
        {error && <p className="text-sm text-danger">{error}</p>}
        {!data && !error && <Skeleton className="h-40" />}
        {data && data.parts.length === 0 && <p className="text-sm text-text-3">No extracted text (the document is not indexed).</p>}
        {data?.parts.map((p, i) => {
          const prev = data.parts[i - 1];
          const newPlace = !prev || prev.page !== p.page || prev.heading !== p.heading;
          return (
            <div key={p.chunk_id}>
              {newPlace && (p.page != null || p.heading) && <p className="mb-1 mt-3 text-xs font-semibold uppercase tracking-wide text-accent">{locationLabel(p.page, p.heading)}</p>}
              <p data-chunk={p.chunk_id} data-cited={p.chunk_id === focusId ? "true" : undefined} className={cn("whitespace-pre-wrap rounded-md px-2 py-1 text-sm leading-relaxed text-text-1", p.chunk_id === focusId && "bg-accent/15 ring-1 ring-accent/50")}>
                {p.text}
              </p>
            </div>
          );
        })}
      </div>
    </Dialog>
  );
}

function DocumentRow({ d, onOpen, onMove, onRemove }: { d: VaultDocument; onOpen: () => void; onMove: () => void; onRemove: () => void }) {
  const s = STATUS[d.status];
  const act = async (f: () => Promise<unknown>, fail: string) => {
    try {
      await f();
    } catch (e) {
      toast.error(errText(e, fail));
    }
  };
  return (
    <li className="group flex items-start gap-3 rounded-lg border border-line-2 bg-bg-2/70 px-4 py-3" data-vault-doc={d.title} data-status={d.status}>
      <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-md bg-bg-3 text-[10px] font-semibold uppercase text-accent">{d.kind}</span>
      <div className="min-w-0 flex-1">
        <button type="button" onClick={onOpen} disabled={d.chunks === 0} className="max-w-full truncate text-left text-sm font-medium text-text-1 hover:underline disabled:no-underline">
          {d.title}
        </button>
        <p className="mt-0.5 flex flex-wrap gap-x-3 text-xs text-text-3">
          <span>{d.project_name ? `Project: ${d.project_name}` : "Personal library"}</span>
          {d.pages != null && <span>{d.pages} pages</span>}
          {d.chunks > 0 && <span>{d.chunks} passages</span>}
          <span>{formatBytes(d.size_bytes)}</span>
          <span>imported {relativeTime(d.imported_at)}</span>
          {d.indexed_at && <span>indexed {relativeTime(d.indexed_at)}</span>}
        </p>
        {d.error && <p className={cn("mt-1 text-xs", d.status === "failed" ? "text-danger" : "text-warn")}>{d.error}</p>}
      </div>
      <Badge tone={s.tone}>
        {d.status === "processing" && <Loader2 className="mr-1 inline size-3 animate-spin" aria-hidden />}
        {s.label}
      </Badge>
      <div className="flex shrink-0 items-center gap-1">
        {d.chunks > 0 && (
          <Button size="sm" variant="ghost" icon={<BookOpen className="size-3.5" aria-hidden />} onClick={onOpen} aria-label={`Open ${d.title}`}>
            Open
          </Button>
        )}
        {d.status === "processing" ? (
          <Button size="sm" variant="ghost" icon={<X className="size-3.5" aria-hidden />} onClick={() => act(() => api.vaultCancel(d.id), "Could not cancel")} aria-label={`Cancel processing ${d.title}`}>
            Cancel
          </Button>
        ) : (
          <Button
            size="sm"
            variant="ghost"
            icon={<RefreshCw className="size-3.5" aria-hidden />}
            onClick={() => act(() => api.vaultReindex(d.id), "Could not re-index")}
            aria-label={`${d.status === "failed" ? "Retry" : "Re-index"} ${d.title}`}
          >
            {d.status === "failed" ? "Retry" : "Re-index"}
          </Button>
        )}
        <Button size="sm" variant="ghost" icon={<FolderInput className="size-3.5" aria-hidden />} onClick={onMove} aria-label={`Move ${d.title}`} />
        <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" aria-hidden />} onClick={onRemove} aria-label={`Remove ${d.title}`} />
      </div>
    </li>
  );
}

function HitRow({ h, projectName, onOpen }: { h: VaultHit; projectName: string; onOpen: () => void }) {
  return (
    <li>
      <button type="button" onClick={onOpen} className="w-full rounded-lg border border-line-2 bg-bg-2/70 px-4 py-3 text-left hover:border-accent/50" data-vault-hit={h.title}>
        <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
          <span className="font-medium text-text-1">{h.title}</span>
          <span className="text-xs text-accent">{locationLabel(h.page, h.heading)}</span>
          <span className="text-xs text-text-3">{projectName}</span>
        </p>
        <p className="mt-1 text-sm leading-relaxed text-text-2">
          <Snippet text={h.snippet} />
        </p>
      </button>
    </li>
  );
}

export function VaultPage() {
  const ui = useUi();
  const projects = useAtlasQuery("projects", () => api.projects(false), ["projects"]);
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const [libValue, setLibValue] = useState("all");
  const [kinds, setKinds] = useState<string[]>([]);
  const [q, setQ] = useState("");
  const [candidates, setCandidates] = useState<VaultCandidate[] | null>(null);
  const [moving, setMoving] = useState<VaultDocument | null>(null);
  const [removing, setRemoving] = useState<VaultDocument | null>(null);
  const library = libraryFromValue(libValue);
  const list = useAtlasQuery(`vault-list-${libValue}`, () => api.vaultList(library), ["vault", "projects"]);
  const query = q.trim();
  const search = useAtlasQuery(`vault-search-${libValue}-${kinds.join(",")}-${query}`, () => (query.length >= 2 ? api.vaultSearch(query, library, kinds) : Promise.resolve(null)), ["vault"]);
  const docs = (list.data?.documents ?? []).filter((d) => !kinds.length || kinds.includes(d.kind));
  const failed = docs.filter((d) => d.status === "failed");
  const others = docs.filter((d) => d.status !== "failed");
  const stats = list.data?.stats;
  const pname = (id: string | null) => (id ? `Project: ${projects.data?.find((p) => p.id === id)?.name ?? "…"}` : "Personal library");
  const vault = settings.data?.vault;
  const setVault = async (patch: Partial<NonNullable<typeof vault>>) => {
    if (!settings.data || !vault) return;
    try {
      await api.updateSettings({ ...settings.data, vault: { ...vault, ...patch } });
    } catch (e) {
      toast.error(errText(e, "Settings could not be saved"));
    }
  };
  const pick = async () => {
    try {
      const c = await api.vaultPickFiles();
      if (c.length) setCandidates(c);
    } catch (e) {
      toast.error(errText(e, "The file picker could not be opened"));
    }
  };
  const checkChanges = async () => {
    try {
      const n = await api.vaultCheckChanges();
      toast.success(n ? `${n} ${n === 1 ? "document has" : "documents have"} changed and can be re-indexed` : "No document has changed since it was indexed");
    } catch (e) {
      toast.error(errText(e, "Could not check for changes"));
    }
  };
  const row = (d: VaultDocument) => (
    <DocumentRow key={d.id} d={d} onOpen={() => ui.openVaultSource({ documentId: d.id, chunkId: null, page: null, heading: "" })} onMove={() => setMoving(d)} onRemove={() => setRemoving(d)} />
  );
  return (
    <div className="flex h-full flex-col overflow-auto">
      <PageHeader
        eyebrow="Knowledge"
        title="Knowledge Vault"
        subtitle="Your own documents, read and indexed on this computer. Ask Atlas about them and every answer points back to the page or section it came from."
        actions={
          <>
            <Button icon={<RefreshCw className="size-4" aria-hidden />} onClick={checkChanges}>
              Check for changes
            </Button>
            <Button variant="primary" icon={<Upload className="size-4" aria-hidden />} onClick={pick}>
              Import documents
            </Button>
          </>
        }
      />
      <div className="space-y-5 px-8 py-6" data-vault>
        <div className="grid gap-3 sm:grid-cols-4" data-vault-stats>
          {[
            ["Documents", stats?.documents ?? 0],
            ["Indexed", stats?.indexed ?? 0],
            ["Searchable passages", stats?.passages ?? 0],
            ["Storage", formatBytes(stats?.storage_bytes ?? 0)],
          ].map(([k, v]) => (
            <Panel key={k} className="px-4 py-3">
              <p className="text-xs text-text-3">{k}</p>
              <p className="mt-1 font-display text-lg font-semibold">{v}</p>
            </Panel>
          ))}
        </div>
        {vault && (
          <Panel className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3 text-sm" data-vault-settings>
            <label className="flex items-center gap-2">
              <Switch checked={vault.use_in_chat} label="Use in conversations" onChange={(v) => setVault({ use_in_chat: v })} />
              Use in conversations
            </label>
            <label className="flex items-center gap-2">
              <Switch checked={vault.local_only} label="Local-only" onChange={(v) => setVault({ local_only: v })} />
              Local-only
            </label>
            <p className="min-w-64 flex-1 text-xs text-text-3">
              {vault.local_only
                ? "Passages are only sent to a model running on this computer. With a cloud model, Atlas says when it held passages back."
                : "Search and indexing always stay on this computer. When a conversation uses a cloud model, the few relevant passages are sent with your message, and the reply shows which ones."}
            </p>
          </Panel>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-64 flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" aria-hidden />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder='Search your documents. Use "quotes" for an exact phrase.' className="pl-8" aria-label="Search the Knowledge Vault" />
          </div>
          <Select aria-label="Library" value={libValue} onChange={(e) => setLibValue(e.target.value)} className="w-56">
            <option value="all">All libraries</option>
            <option value="personal">Personal library</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                Project: {p.name}
              </option>
            ))}
          </Select>
          <div className="flex gap-1" role="group" aria-label="Document types">
            {KINDS.map((k) => {
              const on = kinds.includes(k.value);
              return (
                <Button key={k.value} size="sm" variant={on ? "primary" : "ghost"} aria-pressed={on} onClick={() => setKinds(on ? kinds.filter((x) => x !== k.value) : [...kinds, k.value])}>
                  {k.label}
                </Button>
              );
            })}
          </div>
        </div>

        {query.length >= 2 ? (
          search.data ? (
            search.data.length ? (
              <section aria-label="Search results" data-vault-results>
                <p className="mb-2 text-xs text-text-3">
                  {search.data.length} {search.data.length === 1 ? "passage" : "passages"} for “{query}”
                </p>
                <ul className="space-y-2">
                  {search.data.map((h) => (
                    <HitRow key={h.chunk_id} h={h} projectName={pname(h.project_id)} onOpen={() => ui.openVaultSource({ documentId: h.document_id, chunkId: h.chunk_id, page: h.page, heading: h.heading })} />
                  ))}
                </ul>
              </section>
            ) : (
              <p className="py-8 text-center text-sm text-text-3" data-vault-no-results>
                Nothing in {libValue === "all" ? "your libraries" : "this library"} matches “{query}”.
              </p>
            )
          ) : (
            <Skeleton className="h-24" />
          )
        ) : list.loading && !list.data ? (
          <div className="space-y-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : docs.length ? (
          <div className="space-y-5">
            {failed.length > 0 && (
              <section aria-label="Failed imports">
                <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-danger">
                  <AlertTriangle className="size-4" aria-hidden /> Could not be indexed ({failed.length})
                </h2>
                <ul className="space-y-2">{failed.map(row)}</ul>
              </section>
            )}
            <section aria-label="Documents">
              <ul className="space-y-2">{others.map(row)}</ul>
            </section>
          </div>
        ) : (
          <EmptyState
            icon={<Library className="size-5" aria-hidden />}
            title={libValue === "all" ? "Your Knowledge Vault is empty" : "No documents in this library"}
            body="Import text, Markdown, PDF or Word documents. Atlas reads them on this computer, finds the passages that matter when you ask, and shows exactly where each answer came from."
            action={
              <Button variant="primary" onClick={pick}>
                Import documents
              </Button>
            }
          />
        )}
      </div>
      {candidates && <ImportDialog open={!!candidates} onOpenChange={(v) => !v && setCandidates(null)} candidates={candidates} defaultProject={library.kind === "project" ? library.project_id : ""} />}
      <MoveDialog doc={moving} onOpenChange={(v) => !v && setMoving(null)} />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(v) => !v && setRemoving(null)}
        title={`Remove “${removing?.title ?? ""}” from the Vault?`}
        body={<p>Its passages leave the search index and Atlas deletes its own copy. Your original file is not touched, and conversations that cited it keep the citation, marked as removed.</p>}
        confirmLabel="Remove"
        danger
        onConfirm={async () => {
          if (!removing) return;
          try {
            await api.vaultRemove(removing.id);
            toast.success("Removed from the Knowledge Vault");
          } catch (e) {
            toast.error(errText(e, "The document could not be removed"));
          }
        }}
      />
      <Reader target={ui.vaultOpen} onClose={() => ui.openVaultSource(null)} />
    </div>
  );
}
