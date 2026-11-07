import {
  ChevronRight,
  File,
  FlaskConical,
  Folder,
  FolderOpen,
  GitBranch,
  GitCommitHorizontal,
  Hammer,
  History,
  Plus,
  Settings2,
  Square,
  SquareTerminal,
  Undo2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { BudgetPrompt } from "@/components/BudgetPrompt";
import { Badge, Button, EmptyState, ErrorNote, Field, Input, Segmented, Spinner } from "@/components/ui/primitives";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { api, AtlasError } from "@/lib/bridge";
import { cn, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Discipline, ForgeProject, ForgeRun } from "@/lib/schemas";
import { useTurns } from "@/state/turns";
import { useUi } from "@/state/ui";
import { Composer } from "../companion/Composer";
import { LiveTurn } from "../companion/LiveTurn";
import { Thread } from "../companion/Thread";
import { DiffView } from "./DiffView";

export const DISCIPLINES: { value: Discipline; label: string; blurb: string }[] = [
  { value: "architect", label: "Architect", blurb: "Studies the code and proposes a plan. Read-only." },
  { value: "builder", label: "Builder", blurb: "Implements changes, runs tests, proposes commits." },
  { value: "debugger", label: "Debugger", blurb: "Reproduces a failure, finds the root cause, proves the fix." },
  { value: "reconstructor", label: "Reconstructor", blurb: "Recovers how unfamiliar code works and documents it." },
];

function errMsg(e: unknown, fallback: string) {
  return e instanceof AtlasError ? e.message : fallback;
}

// ---------------- explorer ----------------

function TreeNode({ projectId, path, name, depth, onOpen, selected }: { projectId: string; path: string; name: string; depth: number; onOpen: (p: string) => void; selected: string | null }) {
  const [open, setOpen] = useState(depth === 0);
  const children = useAtlasQuery(`forge-tree:${projectId}:${path}:${open}`, () => (open ? api.forgeTree(projectId, path, 1) : Promise.resolve(null)), ["forge"]);
  const pad = { paddingLeft: `${8 + depth * 12}px` };
  return (
    <li>
      {depth > 0 && (
        <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex w-full items-center gap-1.5 rounded-sm py-1 pr-2 text-left text-xs text-text-2 hover:bg-bg-3 hover:text-text-1" style={pad}>
          <ChevronRight className={cn("size-3 shrink-0 transition-transform", open && "rotate-90")} aria-hidden />
          {open ? <FolderOpen className="size-3.5 shrink-0 text-accent" aria-hidden /> : <Folder className="size-3.5 shrink-0 text-accent" aria-hidden />}
          <span className="truncate">{name}</span>
        </button>
      )}
      {open && (
        <ul>
          {children.loading && !children.data && <li className="py-1 text-xs text-text-3" style={{ paddingLeft: `${20 + depth * 12}px` }}>Loading…</li>}
          {children.error && <li className="py-1 text-xs text-err" style={{ paddingLeft: `${20 + depth * 12}px` }}>{children.error.message}</li>}
          {children.data?.entries.map((e) => {
            const nm = e.path.split("/").pop() ?? e.path;
            return e.kind === "dir" ? (
              <TreeNode key={e.path} projectId={projectId} path={e.path} name={nm} depth={depth + 1} onOpen={onOpen} selected={selected} />
            ) : (
              <li key={e.path}>
                <button
                  onClick={() => onOpen(e.path)}
                  aria-current={selected === e.path ? "true" : undefined}
                  className={cn("flex w-full items-center gap-1.5 rounded-sm py-1 pr-2 text-left text-xs hover:bg-bg-3", selected === e.path ? "bg-accent-soft text-accent-strong" : "text-text-2 hover:text-text-1")}
                  style={{ paddingLeft: `${22 + depth * 12}px` }}
                >
                  <File className="size-3.5 shrink-0 text-text-3" aria-hidden />
                  <span className="truncate">{nm}</span>
                </button>
              </li>
            );
          })}
          {children.data?.truncated && <li className="py-1 text-xs text-text-3" style={pad}>More items not shown</li>}
        </ul>
      )}
    </li>
  );
}

// ---------------- center: session / file / diff ----------------

function SessionPane({ project }: { project: ForgeProject }) {
  const [activeId, setActiveId] = useState<string | null>(null);
  const sessions = useAtlasQuery(`forge-sessions:${project.id}`, () => api.forgeSessions(project.id), ["forge", "conversations"]);
  const session = sessions.data?.find((s) => s.id === activeId) ?? null;
  const [discipline, setDiscipline] = useState<Discipline>("builder");
  const turn = useTurns((s) => (activeId ? s.byConversation[activeId] : undefined));
  const send = useTurns((s) => s.send);
  const cancel = useTurns((s) => s.cancel);
  const messages = useAtlasQuery(`msgs:${activeId}:${turn?.revision ?? 0}`, () => (activeId ? api.messages(activeId) : Promise.resolve([])), []);
  const scroller = useRef<HTMLDivElement>(null);
  const running = turn?.running ?? false;

  useEffect(() => {
    setActiveId(null);
  }, [project.id]);
  useEffect(() => {
    if (session?.discipline) setDiscipline(session.discipline);
  }, [session?.id, session?.discipline]);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.data, turn?.text, turn?.tools.length]);

  const changeDiscipline = async (d: Discipline) => {
    setDiscipline(d);
    if (activeId) {
      try {
        await api.forgeSetDiscipline(activeId, d);
      } catch (e) {
        toast.error(errMsg(e, "Could not change discipline"));
      }
    }
  };

  const onSend = async (text: string) => {
    let id = activeId;
    if (!id) {
      try {
        id = (await api.forgeCreateSession(project.id, discipline)).id;
        setActiveId(id);
      } catch (e) {
        toast.error(errMsg(e, "Could not start a Forge session"));
        return;
      }
    }
    void send(id, text);
  };

  const blurb = DISCIPLINES.find((d) => d.value === discipline)?.blurb;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap items-center gap-2 border-b border-line-1 px-4 py-2">
        <Segmented label="Discipline" value={discipline} onChange={(d) => void changeDiscipline(d)} options={DISCIPLINES.map((d) => ({ value: d.value, label: d.label }))} />
        <select
          aria-label="Forge session"
          className="h-8 min-w-0 flex-1 rounded-md border border-line-2 bg-bg-1 px-2 text-xs text-text-1"
          value={activeId ?? ""}
          onChange={(e) => setActiveId(e.target.value || null)}
        >
          <option value="">New session</option>
          {sessions.data?.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title} · {relativeTime(s.updated_at)}
            </option>
          ))}
        </select>
      </div>
      <p className="border-b border-line-1 bg-bg-1/50 px-4 py-1.5 text-xs text-text-3">{blurb} Edits, commands and commits each ask for your approval first.</p>
      <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto pt-4">
        {!activeId || (messages.data && messages.data.length === 0 && !running) ? (
          <div className="mx-auto max-w-xl px-6 pt-[6vh] text-center">
            <Hammer className="mx-auto size-8 text-accent" aria-hidden />
            <h2 className="mt-3 font-display text-lg font-semibold">What should we work on in {project.name}?</h2>
            <p className="mt-1 text-sm text-text-2">Describe a feature, a bug, or something you want explained. Atlas reads the project, and anything that changes it waits for you.</p>
          </div>
        ) : messages.error ? (
          <div className="p-4">
            <ErrorNote message={messages.error.message} onRetry={messages.reload} />
          </div>
        ) : (
          <>
            <Thread messages={messages.data ?? []} canAskAgain={!running} running={running} onAskAgain={(t) => void onSend(t)} />
            {turn && <LiveTurn turn={turn} />}
          </>
        )}
        {activeId && <BudgetPrompt conversationId={activeId} />}
      </div>
      <Composer running={running} onSend={(t) => void onSend(t)} onStop={() => activeId && void cancel(activeId)} />
    </div>
  );
}

function FilePane({ project, path }: { project: ForgeProject; path: string | null }) {
  const file = useAtlasQuery(`forge-file:${project.id}:${path}`, () => (path ? api.forgeReadFile(project.id, path) : Promise.resolve(null)), ["forge"]);
  if (!path) return <EmptyState icon={<File className="size-5" aria-hidden />} title="No file open" body="Pick a file in the explorer to view it here." />;
  if (file.error) return <div className="p-4"><ErrorNote title="Could not open the file" message={file.error.message} /></div>;
  if (!file.data) return <div className="grid flex-1 place-items-center"><Spinner /></div>;
  const lines = file.data.content.split("\n");
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <p className="sticky top-0 z-10 border-b border-line-1 bg-bg-1 px-4 py-1.5 font-mono text-xs text-text-2">{file.data.path}</p>
      <pre className="py-2 font-mono text-[0.75rem] leading-[1.6]">
        {lines.map((l, i) => (
          <div key={i} className="flex">
            <span className="w-12 shrink-0 select-none pr-3 text-right text-text-3">{i + 1}</span>
            <span className="whitespace-pre pr-4 text-text-1">{l || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

function DiffPane({ project }: { project: ForgeProject }) {
  const diff = useAtlasQuery(`forge-diff:${project.id}`, () => api.forgeGitDiff(project.id, null), ["forge"]);
  return (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      {diff.error ? <ErrorNote title="Git diff unavailable" message={diff.error.message} onRetry={diff.reload} /> : diff.data === undefined ? <Spinner /> : <DiffView diff={diff.data} empty="No uncommitted changes." />}
    </div>
  );
}

// ---------------- right: terminal / tests / git / changes ----------------

function RunCard({ run, onCancel }: { run: ForgeRun; onCancel?: () => void }) {
  const tone = run.status === "succeeded" ? "ok" : run.status === "running" ? "accent" : "err";
  return (
    <div className="rounded-md border border-line-1 bg-bg-1">
      <div className="flex items-center gap-2 border-b border-line-1 px-3 py-1.5">
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-text-1">$ {run.command}</span>
        {run.initiated_by === "model" && <Badge tone="info">Atlas</Badge>}
        <Badge tone={tone as "ok" | "accent" | "err"}>{run.status === "running" ? "running" : `${run.status}${run.exit_code !== null ? ` (${run.exit_code})` : ""}`}</Badge>
        {run.status === "running" && onCancel && (
          <button aria-label="Stop command" onClick={onCancel} className="rounded-sm p-0.5 text-text-3 hover:text-err"><Square className="size-3.5" /></button>
        )}
      </div>
      {run.summary && (
        <p className="border-b border-line-1 px-3 py-1 text-xs">
          <span className="text-ok">{run.summary.passed} passed</span>
          {" · "}
          <span className={run.summary.failed ? "text-err" : "text-text-3"}>{run.summary.failed} failed</span>
          <span className="text-text-3"> · {run.summary.framework}</span>
        </p>
      )}
      {run.output && <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-[0.7rem] leading-[1.5] text-text-2">{run.output}</pre>}
      <p className="px-3 py-1 text-[0.68rem] text-text-3">{relativeTime(run.created_at)}{run.duration_ms !== null && ` · ${(run.duration_ms / 1000).toFixed(1)}s`}</p>
    </div>
  );
}

function TerminalPanel({ project }: { project: ForgeProject }) {
  const runs = useAtlasQuery(`forge-runs:${project.id}`, () => api.forgeRuns(project.id), ["forge"]);
  const [cmd, setCmd] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (command: string) => {
    if (!command.trim()) return;
    setBusy(true);
    try {
      await api.forgeRun(project.id, command);
      setCmd("");
    } catch (e) {
      toast.error(errMsg(e, "The command could not be started"));
    } finally {
      setBusy(false);
      runs.reload();
    }
  };
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <form
        className="flex gap-2 border-b border-line-1 p-3"
        onSubmit={(e) => {
          e.preventDefault();
          void run(cmd);
        }}
      >
        <Input aria-label="Command" value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder="e.g. cargo build, npm run lint" className="font-mono text-xs" disabled={busy} />
        <Button type="submit" size="md" variant="secondary" loading={busy}>Run</Button>
      </form>
      <p className="px-3 pt-2 text-[0.68rem] text-text-3">Runs in {project.root_path} without a shell (no pipes or &&), with a time limit. Variables that look like credentials are not passed on.</p>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
        {runs.data?.length === 0 && <p className="py-6 text-center text-xs text-text-3">No commands yet.</p>}
        {runs.data?.map((r) => <RunCard key={r.id} run={r} onCancel={() => void api.forgeCancelRun(r.id)} />)}
      </div>
    </div>
  );
}

function TestsPanel({ project, onConfigure }: { project: ForgeProject; onConfigure: () => void }) {
  const runs = useAtlasQuery(`forge-runs:${project.id}`, () => api.forgeRuns(project.id), ["forge"]);
  const [busy, setBusy] = useState(false);
  const testRuns = (runs.data ?? []).filter((r) => project.test_command && r.command === project.test_command.trim());
  const go = async () => {
    if (!project.test_command) return;
    setBusy(true);
    try {
      const r = await api.forgeRun(project.id, project.test_command);
      if (r.status === "succeeded") toast.success(r.summary ? `${r.summary.passed} tests passed` : "Tests passed");
      else toast.error(r.summary ? `${r.summary.failed} failed, ${r.summary.passed} passed` : `Tests ${r.status}`);
    } catch (e) {
      toast.error(errMsg(e, "Could not run the tests"));
    } finally {
      setBusy(false);
      runs.reload();
    }
  };
  if (!project.test_command)
    return <EmptyState icon={<FlaskConical className="size-5" aria-hidden />} title="No test command" body="Tell Atlas how this project runs its tests (for example `cargo test` or `npm test`)." action={<Button onClick={onConfigure}>Set test command</Button>} />;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2 border-b border-line-1 p-3">
        <code className="min-w-0 flex-1 truncate font-mono text-xs text-text-2">{project.test_command}</code>
        <Button size="md" variant="primary" icon={<FlaskConical className="size-4" />} loading={busy} onClick={() => void go()}>Run tests</Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
        {testRuns.length === 0 && <p className="py-6 text-center text-xs text-text-3">Tests have not been run in this project yet.</p>}
        {testRuns.map((r) => <RunCard key={r.id} run={r} />)}
      </div>
    </div>
  );
}

function GitPanel({ project }: { project: ForgeProject }) {
  const status = useAtlasQuery(`forge-git:${project.id}`, () => api.forgeGitStatus(project.id), ["forge"]);
  const log = useAtlasQuery(`forge-log:${project.id}`, () => api.forgeGitLog(project.id), ["forge"]);
  const [msg, setMsg] = useState("");
  const [branch, setBranch] = useState("");
  const [busy, setBusy] = useState(false);
  const refresh = () => {
    status.reload();
    log.reload();
  };
  const commit = async () => {
    setBusy(true);
    try {
      const h = await api.forgeGitCommit(project.id, msg, []);
      toast.success(`Committed ${h}`);
      setMsg("");
    } catch (e) {
      toast.error(errMsg(e, "Commit failed"));
    } finally {
      setBusy(false);
      refresh();
    }
  };
  const mkBranch = async () => {
    try {
      await api.forgeGitBranch(project.id, branch);
      toast.success(`Switched to new branch ${branch}`);
      setBranch("");
    } catch (e) {
      toast.error(errMsg(e, "Could not create the branch"));
    } finally {
      refresh();
    }
  };
  if (status.error) return <div className="p-3"><ErrorNote title="Git unavailable" message={status.error.message} onRetry={refresh} /></div>;
  if (!status.data) return <div className="p-4"><Spinner /></div>;
  if (!status.data.is_repo) return <EmptyState icon={<GitBranch className="size-5" aria-hidden />} title="Not a git repository" body="This folder is not under git, so Atlas cannot show history or commit. Atlas still keeps its own snapshots of every change (see Changes)." />;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
      <div className="border-b border-line-1 p-3">
        <p className="flex items-center gap-2 text-xs text-text-2">
          <GitBranch className="size-3.5 text-accent" aria-hidden />
          <span className="font-mono text-text-1">{status.data.branch ?? "(detached)"}</span>
          {status.data.ahead_behind && <span className="text-text-3">{status.data.ahead_behind}</span>}
        </p>
        <ul className="mt-2 max-h-40 overflow-y-auto">
          {status.data.files.length === 0 && <li className="text-xs text-text-3">Working tree clean.</li>}
          {status.data.files.map((f) => (
            <li key={f.path} className="flex gap-2 font-mono text-[0.7rem]">
              <span className={cn("w-5 shrink-0", f.code.includes("?") ? "text-text-3" : f.code.includes("D") ? "text-err" : "text-warn")}>{f.code.trim() || "·"}</span>
              <span className="truncate text-text-2">{f.path}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex flex-col gap-2 border-b border-line-1 p-3">
        <Input aria-label="Commit message" value={msg} onChange={(e) => setMsg(e.target.value)} placeholder="Commit message" />
        <Button size="sm" variant="secondary" icon={<GitCommitHorizontal className="size-3.5" />} disabled={!msg.trim() || status.data.files.length === 0} loading={busy} onClick={() => void commit()}>
          Commit all changes
        </Button>
        <p className="text-[0.68rem] text-text-3">Commits locally. Atlas never pushes.</p>
      </div>
      <div className="flex gap-2 border-b border-line-1 p-3">
        <Input aria-label="New branch name" value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="checkpoint branch, e.g. atlas/try-fix" className="font-mono text-xs" />
        <Button size="md" variant="ghost" disabled={!branch.trim()} onClick={() => void mkBranch()}>Branch</Button>
      </div>
      <div className="p-3">
        <p className="mb-1.5 text-[0.68rem] font-semibold uppercase tracking-wider text-text-3">Recent commits</p>
        {log.data?.length === 0 && <p className="text-xs text-text-3">No commits yet.</p>}
        <ul className="flex flex-col gap-1">
          {log.data?.map((c) => (
            <li key={c.hash} className="text-xs">
              <span className="font-mono text-accent">{c.hash}</span> <span className="text-text-1">{c.subject}</span>
              <span className="block text-[0.68rem] text-text-3">{c.author} · {c.date}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ChangesPanel({ project }: { project: ForgeProject }) {
  const changes = useAtlasQuery(`forge-changes:${project.id}`, () => api.forgeChanges(project.id), ["forge"]);
  const [open, setOpen] = useState<string | null>(null);
  const diff = useAtlasQuery(`forge-change-diff:${open}`, () => (open ? api.forgeChangeDiff(open) : Promise.resolve("")), ["forge"]);
  const [confirm, setConfirm] = useState<string | null>(null);
  const revert = async (id: string) => {
    try {
      const c = await api.forgeRevert(id);
      toast.success(`Reverted ${c.path}`);
    } catch (e) {
      toast.error(errMsg(e, "Could not revert"));
    } finally {
      changes.reload();
    }
  };
  if (changes.error) return <div className="p-3"><ErrorNote message={changes.error.message} onRetry={changes.reload} /></div>;
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
      <p className="text-[0.68rem] text-text-3">Every file Atlas changes here is snapshotted. Revert works only while the file is exactly as Atlas left it, so newer work is never overwritten.</p>
      {changes.data?.length === 0 && <p className="py-6 text-center text-xs text-text-3">Atlas has not changed any files in this project.</p>}
      {changes.data?.map((c) => (
        <div key={c.id} className="rounded-md border border-line-1 bg-bg-1">
          <div className="flex items-center gap-2 px-3 py-1.5">
            <button onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id} className="min-w-0 flex-1 truncate text-left font-mono text-xs text-text-1 hover:text-accent">{c.path}</button>
            <Badge tone={c.kind === "create" ? "ok" : "info"}>{c.kind === "create" ? "created" : "edited"}</Badge>
            {c.reverted_at ? (
              <Badge>reverted</Badge>
            ) : (
              <button
                onClick={() => setConfirm(c.id)}
                disabled={!c.revertible}
                title={c.revert_blocker ?? "Revert this change"}
                aria-label={`Revert ${c.path}`}
                className="rounded-sm p-1 text-text-3 hover:text-warn disabled:cursor-not-allowed disabled:opacity-40"
              >
                <Undo2 className="size-3.5" />
              </button>
            )}
          </div>
          <p className="px-3 pb-1.5 text-[0.68rem] text-text-3">
            {c.summary} · {relativeTime(c.created_at)}
            {!c.revertible && !c.reverted_at && c.revert_blocker && <span className="text-warn"> · cannot revert: {c.revert_blocker}</span>}
          </p>
          {open === c.id && <div className="border-t border-line-1 p-2">{diff.data !== undefined ? <DiffView diff={diff.data} /> : <Spinner />}</div>}
        </div>
      ))}
      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(v) => !v && setConfirm(null)}
        title="Revert this change?"
        body={<p>The file goes back to how it was before Atlas changed it{changes.data?.find((c) => c.id === confirm)?.kind === "create" ? " — for a created file, that means deleting it" : ""}.</p>}
        confirmLabel="Revert"
        onConfirm={() => (confirm ? revert(confirm) : undefined)}
      />
    </div>
  );
}

// ---------------- project settings ----------------

function ProjectSettings({ project, open, onOpenChange }: { project: ForgeProject; open: boolean; onOpenChange: (v: boolean) => void }) {
  const [name, setName] = useState(project.name);
  const [test, setTest] = useState(project.test_command ?? "");
  const [build, setBuild] = useState(project.build_command ?? "");
  const [remove, setRemove] = useState(false);
  useEffect(() => {
    setName(project.name);
    setTest(project.test_command ?? "");
    setBuild(project.build_command ?? "");
  }, [project]);
  const save = async () => {
    try {
      await api.forgeUpdateProject(project.id, name, test || null, build || null);
      toast.success("Project saved");
      onOpenChange(false);
    } catch (e) {
      toast.error(errMsg(e, "Could not save"));
    }
  };
  return (
    <>
      <Dialog
        open={open}
        onOpenChange={onOpenChange}
        title="Project settings"
        description={<span className="font-mono text-xs">{project.root_path}</span>}
        footer={
          <>
            <Button variant="danger" className="mr-auto" onClick={() => setRemove(true)}>Remove from Forge</Button>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => void save()}>Save</Button>
          </>
        }
      >
        <div className="flex flex-col gap-4">
          <Field label="Name" htmlFor="fp-name"><Input id="fp-name" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Test command" htmlFor="fp-test" hint="What Atlas runs for “Run tests” and forge.run_tests. One program and its arguments; no shell.">
            <Input id="fp-test" className="font-mono" value={test} onChange={(e) => setTest(e.target.value)} placeholder="cargo test" />
          </Field>
          <Field label="Build command (optional)" htmlFor="fp-build"><Input id="fp-build" className="font-mono" value={build} onChange={(e) => setBuild(e.target.value)} placeholder="npm run build" /></Field>
        </div>
      </Dialog>
      <ConfirmDialog
        open={remove}
        onOpenChange={setRemove}
        title="Remove this project from Forge?"
        body={<p>Atlas forgets the project, its sessions' link to it, its change snapshots and command history. Files on disk are not touched.</p>}
        confirmLabel="Remove"
        danger
        onConfirm={async () => {
          try {
            await api.forgeRemoveProject(project.id);
            onOpenChange(false);
          } catch (e) {
            toast.error(errMsg(e, "Could not remove"));
          }
        }}
      />
    </>
  );
}

// ---------------- page ----------------

type Center = "session" | "file" | "diff";
type Side = "terminal" | "tests" | "git" | "changes";

export function ForgePage() {
  const projects = useAtlasQuery("forge-projects", api.forgeProjects, ["forge"]);
  const forgeProjectId = useUi((s) => s.forgeProjectId);
  const setForgeProject = useUi((s) => s.setForgeProject);
  const project = useMemo(() => projects.data?.find((p) => p.id === forgeProjectId) ?? projects.data?.[0] ?? null, [projects.data, forgeProjectId]);
  const [center, setCenter] = useState<Center>("session");
  const [side, setSide] = useState<Side>("terminal");
  const [file, setFile] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [adding, setAdding] = useState(false);

  useEffect(() => setFile(null), [project?.id]);

  const add = async () => {
    setAdding(true);
    try {
      const p = await api.forgePickProject(null);
      if (p) {
        setForgeProject(p.id);
        toast.success(`Added ${p.name} to Forge`);
      }
    } catch (e) {
      toast.error(errMsg(e, "Could not add the project"));
    } finally {
      setAdding(false);
    }
  };

  if (projects.error) return <div className="p-8"><ErrorNote message={projects.error.message} onRetry={projects.reload} /></div>;
  if (!projects.data) return <div className="grid h-full place-items-center"><Spinner /></div>;
  if (!project)
    return (
      <div className="grid h-full place-items-center p-8">
        <div className="max-w-lg text-center">
          <Hammer className="mx-auto size-10 text-accent" aria-hidden />
          <h1 className="mt-4 font-display text-2xl font-semibold">Atlas Forge</h1>
          <p className="mt-2 text-sm text-text-2">Engineering with Atlas on a project folder you choose: an Architect to plan, a Builder to implement, a Debugger to find root causes and a Reconstructor to recover how old code works.</p>
          <ul className="mx-auto mt-4 max-w-sm space-y-1 text-left text-xs text-text-3">
            <li>• Atlas only sees the folder you pick, never the rest of your computer.</li>
            <li>• Every edit, command and commit shows you the exact change and waits for approval.</li>
            <li>• Every file change is snapshotted and can be reverted while it is unchanged.</li>
          </ul>
          <Button className="mt-6" variant="primary" size="lg" icon={<Plus className="size-4" />} loading={adding} onClick={() => void add()}>Choose a project folder</Button>
        </div>
      </div>
    );

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-64 shrink-0 flex-col border-r border-line-1 bg-bg-1/40" aria-label="Project explorer">
        <div className="flex items-center gap-1 border-b border-line-1 p-2">
          <select aria-label="Forge project" className="h-8 min-w-0 flex-1 rounded-md border border-line-2 bg-bg-1 px-2 text-xs font-medium text-text-1" value={project.id} onChange={(e) => setForgeProject(e.target.value)}>
            {projects.data.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button aria-label="Add project" onClick={() => void add()} className="rounded-sm p-1.5 text-text-3 hover:bg-bg-3 hover:text-text-1"><Plus className="size-4" /></button>
          <button aria-label="Project settings" onClick={() => setSettingsOpen(true)} className="rounded-sm p-1.5 text-text-3 hover:bg-bg-3 hover:text-text-1"><Settings2 className="size-4" /></button>
        </div>
        {!project.exists ? (
          <p className="p-3 text-xs text-err">The folder {project.root_path} no longer exists.</p>
        ) : (
          <ul className="min-h-0 flex-1 overflow-y-auto p-1">
            <TreeNode projectId={project.id} path="." name={project.name} depth={0} onOpen={(p) => { setFile(p); setCenter("file"); }} selected={file} />
          </ul>
        )}
      </aside>
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Forge workspace">
        <div className="flex h-11 shrink-0 items-center gap-3 border-b border-line-1 px-4">
          <h1 className="font-display text-sm font-semibold"><span className="text-accent">Forge</span> · {project.name}</h1>
          <div className="ml-auto">
            <Segmented label="View" value={center} onChange={setCenter} options={[{ value: "session", label: "Session" }, { value: "file", label: "File" }, { value: "diff", label: "Diff" }]} />
          </div>
        </div>
        {center === "session" && <SessionPane project={project} />}
        {center === "file" && <FilePane project={project} path={file} />}
        {center === "diff" && <DiffPane project={project} />}
      </section>
      <aside className="flex w-[22rem] shrink-0 flex-col border-l border-line-1" aria-label="Tools">
        <div role="tablist" aria-label="Forge tools" className="flex border-b border-line-1">
          {([
            ["terminal", "Terminal", SquareTerminal],
            ["tests", "Tests", FlaskConical],
            ["git", "Git", GitBranch],
            ["changes", "Changes", History],
          ] as const).map(([v, label, Icon]) => (
            <button key={v} role="tab" aria-selected={side === v} onClick={() => setSide(v)} className={cn("flex flex-1 items-center justify-center gap-1.5 py-2.5 text-xs", side === v ? "border-b-2 border-accent text-text-1" : "text-text-3 hover:text-text-1")}>
              <Icon className="size-3.5" aria-hidden /> {label}
            </button>
          ))}
        </div>
        {side === "terminal" && <TerminalPanel project={project} />}
        {side === "tests" && <TestsPanel project={project} onConfigure={() => setSettingsOpen(true)} />}
        {side === "git" && <GitPanel project={project} />}
        {side === "changes" && <ChangesPanel project={project} />}
      </aside>
      <ProjectSettings project={project} open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
