import { ChevronRight, ExternalLink, File, FileText, Folder, FolderOpen, Link2, Plus, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, EmptyState, ErrorNote, PageHeader, Panel, Skeleton } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, formatBytes, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";

async function guard<T>(fn: () => Promise<T>) {
  try {
    return await fn();
  } catch (e) {
    toast.error(e instanceof AtlasError ? e.message : String(e));
    return undefined;
  }
}

export function FilesPage() {
  const settings = useAtlasQuery("settings", api.settings, ["settings"]);
  const [path, setPath] = useState(".");
  const [preview, setPreview] = useState<string | null>(null);
  const ws = settings.data?.workspace_dir;
  const listing = useAtlasQuery(`ws:${ws}:${path}`, () => (ws ? api.browseWorkspace(path) : Promise.resolve(null)), ["settings", "tasks"]);
  const file = useAtlasQuery(`wsp:${preview}`, () => (preview ? api.previewWorkspaceFile(preview) : Promise.resolve(null)), []);
  const grants = useAtlasQuery("grants", api.grants, []);
  const crumbs = path === "." ? [] : path.split("/");

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        eyebrow="Approved files"
        title="Files"
        subtitle="Atlas works only inside your workspace folder and with individual files you explicitly share. It never overwrites a file."
        actions={
          <>
            <Button onClick={() => guard(api.pickWorkspace)}>{ws ? "Change folder…" : "Choose folder…"}</Button>
            {ws && <Button icon={<ExternalLink className="size-4" aria-hidden />} onClick={() => guard(() => api.revealWorkspace(path))}>Show in file manager</Button>}
          </>
        }
      />
      {!ws ? (
        <EmptyState
          icon={<FolderOpen className="size-5" aria-hidden />}
          title="No workspace folder yet"
          body="Choose a folder Atlas may read and create files in. Everything outside it stays off-limits."
          action={
            <div className="flex gap-2">
              <Button variant="primary" onClick={() => guard(api.useDefaultWorkspace)}>Use Documents/Atlas Workspace</Button>
              <Button onClick={() => guard(api.pickWorkspace)}>Choose a folder…</Button>
            </div>
          }
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <section className="flex w-[26rem] shrink-0 flex-col border-r border-line-1" aria-label="Workspace browser">
            <nav aria-label="Folder path" className="flex flex-wrap items-center gap-1 border-b border-line-1 px-4 py-2.5 text-xs">
              <button className="rounded-xs px-1 text-accent-strong hover:underline" onClick={() => (setPath("."), setPreview(null))}>Workspace</button>
              {crumbs.map((c, i) => (
                <span key={i} className="flex items-center gap-1">
                  <ChevronRight className="size-3 text-text-3" aria-hidden />
                  <button className="rounded-xs px-1 hover:underline" onClick={() => setPath(crumbs.slice(0, i + 1).join("/"))}>{c}</button>
                </span>
              ))}
            </nav>
            <div className="flex-1 overflow-y-auto p-2">
              {listing.error ? (
                <ErrorNote message={listing.error.message} onRetry={listing.reload} />
              ) : !listing.data ? (
                <div className="space-y-1.5 p-1"><Skeleton className="h-8" /><Skeleton className="h-8" /></div>
              ) : listing.data.entries.length === 0 ? (
                <p className="px-3 py-10 text-center text-sm text-text-3">This folder is empty. Ask Atlas to draft a document and it will appear here after you approve it.</p>
              ) : (
                <ul>
                  {listing.data.entries.map((e) => (
                    <li key={e.path}>
                      <button
                        onClick={() => (e.kind === "dir" ? (setPath(e.path), setPreview(null)) : setPreview(e.path))}
                        aria-current={preview === e.path ? "true" : undefined}
                        className={cn("flex w-full items-center gap-2.5 rounded-sm px-2.5 py-1.5 text-left text-sm", preview === e.path ? "bg-bg-4" : "hover:bg-bg-3")}
                      >
                        {e.kind === "dir" ? <Folder className="size-4 text-accent" aria-hidden /> : <File className="size-4 text-text-3" aria-hidden />}
                        <span className="truncate">{e.name}</span>
                        <span className="ml-auto shrink-0 text-[0.6875rem] text-text-3">{e.kind === "file" ? formatBytes(e.bytes) : ""}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <p className="border-t border-line-1 px-4 py-2 text-[0.6875rem] text-text-3">
              Readable: UTF-8 text formats (txt, md, csv, json, code…). PDF, Word, Excel and images are <strong>not supported yet</strong>.
            </p>
          </section>
          <section className="min-w-0 flex-1 overflow-y-auto px-6 py-5" aria-label="Preview">
            {preview && file.data ? (
              <div className="space-y-3 anim-fade">
                <div className="flex items-center gap-2">
                  <FileText className="size-4 text-accent" aria-hidden />
                  <h2 className="truncate font-mono text-sm">{preview}</h2>
                  {file.data.bytes != null && <Badge>{formatBytes(file.data.bytes)}</Badge>}
                  {file.data.truncated && <Badge tone="warn">preview truncated</Badge>}
                  <button aria-label="Close preview" className="ml-auto rounded-sm p-1 text-text-3 hover:bg-bg-3" onClick={() => setPreview(null)}><X className="size-4" /></button>
                </div>
                {file.data.error ? (
                  <ErrorNote title="Can't preview this file" message={file.data.error} />
                ) : (
                  <pre className="whitespace-pre-wrap break-words rounded-md border border-line-1 bg-[color:var(--code-bg)] p-4 font-mono text-xs leading-relaxed text-text-1">{file.data.content}</pre>
                )}
              </div>
            ) : (
              <div className="space-y-6">
                <Panel className="p-5">
                  <div className="flex items-center gap-2">
                    <Link2 className="size-4 text-accent" aria-hidden />
                    <h2 className="font-semibold">Files shared from outside the workspace</h2>
                    <Button size="sm" variant="subtle" className="ml-auto" icon={<Plus className="size-3.5" aria-hidden />} onClick={async () => { const g = await guard(api.shareFile); if (g) { toast.success(`Shared “${g.label}”`); grants.reload(); } }}>
                      Share a file…
                    </Button>
                  </div>
                  <p className="mt-1 text-sm text-text-2">You pick each file in your system's file dialog. Atlas can read it (read-only) until you revoke access.</p>
                  {grants.data?.length ? (
                    <ul className="mt-3 divide-y divide-[color:var(--line-1)]">
                      {grants.data.map((g) => (
                        <li key={g.id} className="flex items-center gap-3 py-2 text-sm">
                          <File className="size-4 text-text-3" aria-hidden />
                          <span className="truncate">{g.label}</span>
                          <span className="truncate font-mono text-[0.6875rem] text-text-3">{g.path}</span>
                          <span className="ml-auto shrink-0 text-xs text-text-3">{relativeTime(g.created_at)}</span>
                          <Button size="sm" variant="ghost" onClick={async () => { await guard(() => api.revokeGrant(g.id)); grants.reload(); }}>Revoke</Button>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-3 text-xs text-text-3">Nothing shared.</p>
                  )}
                </Panel>
                <p className="text-sm text-text-3">Select a file on the left to preview it.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
