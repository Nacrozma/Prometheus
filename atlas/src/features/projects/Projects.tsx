import { Archive, ArchiveRestore, Download, FolderKanban, MessageSquarePlus, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { newConversation } from "@/app/CommandPalette";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Badge, Button, EmptyState, Field, Input, PageHeader, Panel, Skeleton, Switch, Textarea } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Project } from "@/lib/schemas";

function ProjectDialog({ open, onOpenChange, project }: { open: boolean; onOpenChange: (v: boolean) => void; project?: Project }) {
  const [name, setName] = useState(project?.name ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [instructions, setInstructions] = useState(project?.instructions ?? "");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      if (project) await api.updateProject(project.id, name, description, instructions, project.archived);
      else await api.createProject(name, description, instructions);
      toast.success(project ? "Project saved" : "Project created");
      onOpenChange(false);
      if (!project) {
        setName("");
        setDescription("");
        setInstructions("");
      }
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
      title={project ? `Edit ${project.name}` : "New project"}
      description="Projects keep related conversations, memories and instructions together. Context from one project is not sent with another."
      width="max-w-xl"
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name.trim()} onClick={save}>{project ? "Save" : "Create project"}</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Name" htmlFor="pj-name"><Input id="pj-name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} autoFocus /></Field>
        <Field label="Description" htmlFor="pj-desc"><Textarea id="pj-desc" value={description} maxLength={2000} onChange={(e) => setDescription(e.target.value)} rows={2} /></Field>
        <Field label="Instructions for Atlas" htmlFor="pj-inst" hint="Added to every conversation in this project, e.g. “Use British spelling” or “The audience is beginners.”">
          <Textarea id="pj-inst" value={instructions} maxLength={8000} onChange={(e) => setInstructions(e.target.value)} rows={4} />
        </Field>
      </div>
    </Dialog>
  );
}

function ProjectCard({ p }: { p: Project }) {
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
    <Panel className="flex flex-col gap-3 p-5">
      <div className="flex items-start gap-3">
        <div className="grid size-10 shrink-0 place-items-center rounded-md border border-line-2 bg-accent-softer text-accent"><FolderKanban className="size-5" aria-hidden /></div>
        <div className="min-w-0 flex-1">
          <h3 className="flex items-center gap-2 font-semibold">{p.name} {p.archived && <Badge>archived</Badge>}</h3>
          <p className="text-xs text-text-3">Updated {relativeTime(p.updated_at)}</p>
        </div>
      </div>
      {p.description && <p className="line-clamp-3 text-sm text-text-2">{p.description}</p>}
      {p.instructions && <p className="line-clamp-2 rounded-sm bg-bg-1 px-2 py-1.5 text-xs text-text-3"><strong className="text-text-2">Instructions: </strong>{p.instructions}</p>}
      <div className="flex gap-4 text-xs text-text-3">
        <span>{p.conversation_count} conversations</span>
        <span>{p.memory_count} memories</span>
      </div>
      <div className="mt-auto flex flex-wrap gap-2 pt-1">
        <Button size="sm" variant="subtle" icon={<MessageSquarePlus className="size-3.5" aria-hidden />} onClick={() => newConversation(p.id)} disabled={p.archived}>New chat</Button>
        <Button size="sm" variant="ghost" icon={<Pencil className="size-3.5" aria-hidden />} onClick={() => setEdit(true)}>Edit</Button>
        <Button size="sm" variant="ghost" icon={p.archived ? <ArchiveRestore className="size-3.5" aria-hidden /> : <Archive className="size-3.5" aria-hidden />} onClick={() => act(() => api.updateProject(p.id, p.name, p.description, p.instructions, !p.archived), p.archived ? "Restored" : "Archived")}>
          {p.archived ? "Restore" : "Archive"}
        </Button>
        <Button size="sm" variant="ghost" icon={<Download className="size-3.5" aria-hidden />} onClick={() => act(async () => { const path = await api.exportProject(p.id); if (path) toast.success(`Saved to ${path}`); })}>Export</Button>
        <Button size="sm" variant="ghost" className="text-err" icon={<Trash2 className="size-3.5" aria-hidden />} onClick={() => setDel(true)}>Delete</Button>
      </div>
      <ProjectDialog open={edit} onOpenChange={setEdit} project={p} />
      <ConfirmDialog
        open={del}
        onOpenChange={setDel}
        title={`Delete “${p.name}”?`}
        body={<p>The project and its <strong>{p.memory_count} project memories</strong> are permanently deleted. Its {p.conversation_count} conversations are kept and moved out of the project.</p>}
        confirmLabel="Delete project"
        danger
        typeToConfirm={p.memory_count > 0 ? "DELETE" : undefined}
        onConfirm={() => act(() => api.deleteProject(p.id), "Project deleted")}
      />
    </Panel>
  );
}

export function ProjectsPage() {
  const [archived, setArchived] = useState(false);
  const [create, setCreate] = useState(false);
  const projects = useAtlasQuery("projects-all", () => api.projects(true), ["projects", "conversations", "memory"]);
  const list = (projects.data ?? []).filter((p) => archived || !p.archived);
  return (
    <div className="h-full overflow-y-auto">
      <PageHeader
        eyebrow="Workspaces"
        title="Projects"
        subtitle="Group conversations, memories and standing instructions around something you're working on."
        actions={
          <>
            <label className="flex items-center gap-2 text-xs text-text-2"><Switch checked={archived} onChange={setArchived} label="Show archived projects" /> Show archived</label>
            <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={() => setCreate(true)}>New project</Button>
          </>
        }
      />
      <div className="px-8 py-6">
        {projects.loading && !projects.data ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3"><Skeleton className="h-52" /><Skeleton className="h-52" /></div>
        ) : list.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{list.map((p) => <ProjectCard key={p.id} p={p} />)}</div>
        ) : (
          <EmptyState icon={<FolderKanban className="size-5" aria-hidden />} title="No projects yet" body="Create a project for a trip, a thesis, a renovation — anything with its own context." action={<Button variant="primary" onClick={() => setCreate(true)}>Create a project</Button>} />
        )}
      </div>
      <ProjectDialog open={create} onOpenChange={setCreate} />
    </div>
  );
}
