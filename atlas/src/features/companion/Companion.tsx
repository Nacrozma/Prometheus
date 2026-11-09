import { Archive, ArchiveRestore, Copy, Download, FolderInput, MessageSquarePlus, MoreHorizontal, Pencil, Plug, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { newConversation } from "@/app/CommandPalette";
import { Emblem } from "@/components/Emblem";
import { ConfirmDialog, Dialog } from "@/components/ui/dialog";
import { Badge, Button, EmptyState, ErrorNote, IconButton, Input, Select, Skeleton, Switch } from "@/components/ui/primitives";
import { api, AtlasError } from "@/lib/bridge";
import { cn, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Conversation } from "@/lib/schemas";
import { useTurns } from "@/state/turns";
import { useUi } from "@/state/ui";
import { Composer } from "./Composer";
import { BudgetPrompt } from "@/components/BudgetPrompt";
import { LiveTurn } from "./LiveTurn";
import { ModelPicker, type ModelChoice } from "./ModelPicker";
import { Thread } from "./Thread";
import { canRegenerate, conversationToMarkdown } from "./conversation";
import { audio } from "@/features/voice/audioEngine";
import { VoiceBar } from "@/features/voice/VoiceBar";
import { useVoice } from "@/state/voice";

const SUGGESTIONS = [
  "Help me plan my week — ask me what's on it first.",
  "Explain how compound interest works with a quick example.",
  "Draft a friendly note thanking a friend for a thoughtful gift, and save it as a draft.",
  "What is 17.5% of 2,340? Show the calculation.",
];

function ConversationList({ activeId, onOpen }: { activeId: string | null; onOpen: (id: string) => void }) {
  const [query, setQuery] = useState("");
  const [projectId, setProjectId] = useState<string>("");
  const [archived, setArchived] = useState(false);
  const projects = useAtlasQuery("projects", () => api.projects(false), ["projects"]);
  const list = useAtlasQuery(
    `convs:${projectId}:${archived}`,
    () => api.conversations({ projectId: projectId || null, includeArchived: archived, limit: 300 }),
    ["conversations"],
  );
  const search = useAtlasQuery(`search:${query}`, () => (query.trim().length > 2 ? api.searchConversations(query) : Promise.resolve([])), []);
  const running = useTurns((s) => s.byConversation);
  const items = (list.data ?? []).filter((c) => archived || !c.archived);
  const filtered = query.trim() ? items.filter((c) => c.title.toLowerCase().includes(query.toLowerCase())) : items;

  return (
    <aside aria-label="Conversations" className="flex w-72 shrink-0 flex-col border-r border-line-1 bg-bg-0/40">
      <div className="space-y-2 border-b border-line-1 p-3">
        <Button variant="primary" className="w-full" icon={<MessageSquarePlus className="size-4" aria-hidden />} onClick={() => newConversation(projectId || undefined)}>
          New conversation
        </Button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-text-3" aria-hidden />
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search conversations" className="pl-8" aria-label="Search conversations" />
        </div>
        <div className="flex items-center gap-2">
          <Select aria-label="Filter by project" value={projectId} onChange={(e) => setProjectId(e.target.value)} className="h-8 flex-1 text-xs">
            <option value="">All projects</option>
            {(projects.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </Select>
          <label className="flex items-center gap-1.5 text-[0.6875rem] text-text-3">
            <Switch checked={archived} onChange={setArchived} label="Show archived" />
            Archived
          </label>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {list.loading && !list.data ? (
          <div className="space-y-2 p-1">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : filtered.length === 0 && !(search.data?.length ?? 0) ? (
          <p className="px-3 py-8 text-center text-xs text-text-3">{query ? "No matching conversations." : "No conversations yet."}</p>
        ) : (
          <ul className="space-y-0.5">
            {filtered.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => onOpen(c.id)}
                  aria-current={c.id === activeId ? "true" : undefined}
                  className={cn(
                    "flex w-full flex-col gap-0.5 rounded-md px-3 py-2 text-left transition-colors",
                    c.id === activeId ? "bg-bg-4 text-text-1" : "text-text-2 hover:bg-bg-3 hover:text-text-1",
                  )}
                >
                  <span className="flex items-center gap-2 truncate text-sm">
                    {running[c.id]?.running && <span className="size-1.5 shrink-0 rounded-full bg-accent anim-pulse" aria-label="responding" />}
                    <span className="truncate">{c.title}</span>
                  </span>
                  <span className="flex items-center gap-1.5 text-[0.6875rem] text-text-3">
                    {relativeTime(c.updated_at)}
                    {c.archived && <Badge>archived</Badge>}
                    {c.project_id && <Badge tone="accent">{projects.data?.find((p) => p.id === c.project_id)?.name ?? "project"}</Badge>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {query.trim().length > 2 && (search.data?.length ?? 0) > 0 && (
          <div className="mt-3 border-t border-line-1 pt-2">
            <p className="px-3 pb-1 text-[0.6875rem] uppercase tracking-wider text-text-3">In messages</p>
            <ul className="space-y-0.5">
              {search.data!.slice(0, 15).map((h) => (
                <li key={h.message_id}>
                  <button onClick={() => onOpen(h.conversation_id)} className="w-full rounded-md px-3 py-1.5 text-left hover:bg-bg-3">
                    <span className="block truncate text-xs text-text-1">{h.conversation_title}</span>
                    <span className="block truncate text-[0.6875rem] text-text-3">{h.snippet}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </aside>
  );
}

function ConversationActions({ conv }: { conv: Conversation }) {
  const [menu, setMenu] = useState(false);
  const [rename, setRename] = useState(false);
  const [move, setMove] = useState(false);
  const [del, setDel] = useState(false);
  const [title, setTitle] = useState(conv.title);
  const [target, setTarget] = useState(conv.project_id ?? "");
  const projects = useAtlasQuery("projects", () => api.projects(false), ["projects"]);
  const openConversation = useUi((s) => s.openConversation);
  const act = async (fn: () => Promise<unknown>, ok?: string) => {
    try {
      await fn();
      if (ok) toast.success(ok);
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "Action failed");
    }
  };
  const itemCls = "flex w-full items-center gap-2 rounded-sm px-2.5 py-1.5 text-left text-sm text-text-2 hover:bg-bg-4 hover:text-text-1";
  return (
    <div className="relative">
      <IconButton label="Conversation actions" onClick={() => setMenu((v) => !v)} aria-expanded={menu}>
        <MoreHorizontal className="size-4" aria-hidden />
      </IconButton>
      {menu && (
        <div role="menu" className="absolute right-0 top-10 z-20 w-52 rounded-md border border-line-2 bg-bg-2 p-1 shadow-3 anim-fade" onMouseLeave={() => setMenu(false)}>
          <button role="menuitem" className={itemCls} onClick={() => (setMenu(false), setTitle(conv.title), setRename(true))}>
            <Pencil className="size-4" aria-hidden /> Rename
          </button>
          <button role="menuitem" className={itemCls} onClick={() => (setMenu(false), setMove(true))}>
            <FolderInput className="size-4" aria-hidden /> Move to project
          </button>
          <button
            role="menuitem"
            className={itemCls}
            onClick={() => (setMenu(false), act(async () => { const p = await api.exportConversation(conv.id); if (p) toast.success(`Saved to ${p}`); }))}
          >
            <Download className="size-4" aria-hidden /> Export as Markdown
          </button>
          <button
            role="menuitem"
            className={itemCls}
            onClick={() =>
              (setMenu(false),
              act(async () => {
                const msgs = await api.messages(conv.id);
                await navigator.clipboard.writeText(conversationToMarkdown(conv.title, msgs));
              }, "Conversation copied as Markdown"))
            }
          >
            <Copy className="size-4" aria-hidden /> Copy conversation
          </button>
          <button role="menuitem" className={itemCls} onClick={() => (setMenu(false), act(() => api.archiveConversation(conv.id, !conv.archived), conv.archived ? "Restored" : "Archived"))}>
            {conv.archived ? <ArchiveRestore className="size-4" aria-hidden /> : <Archive className="size-4" aria-hidden />} {conv.archived ? "Unarchive" : "Archive"}
          </button>
          <button role="menuitem" className={cn(itemCls, "text-err hover:text-err")} onClick={() => (setMenu(false), setDel(true))}>
            <Trash2 className="size-4" aria-hidden /> Delete…
          </button>
        </div>
      )}
      <Dialog
        open={rename}
        onOpenChange={setRename}
        title="Rename conversation"
        footer={
          <>
            <Button variant="ghost" onClick={() => setRename(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => act(() => api.renameConversation(conv.id, title)).then(() => setRename(false))}>Save</Button>
          </>
        }
      >
        <Input value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Title" autoFocus maxLength={120} />
      </Dialog>
      <Dialog
        open={move}
        onOpenChange={setMove}
        title="Move to project"
        description="Project instructions and project memories apply to conversations in that project."
        footer={
          <>
            <Button variant="ghost" onClick={() => setMove(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => act(() => api.moveConversation(conv.id, target || null), "Moved").then(() => setMove(false))}>Move</Button>
          </>
        }
      >
        <Select value={target} onChange={(e) => setTarget(e.target.value)} aria-label="Project">
          <option value="">No project</option>
          {(projects.data ?? []).map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </Select>
      </Dialog>
      <ConfirmDialog
        open={del}
        onOpenChange={setDel}
        title="Delete this conversation?"
        body={<p>“{conv.title}” and all of its messages will be permanently deleted from this computer. Task history is kept.</p>}
        confirmLabel="Delete permanently"
        danger
        onConfirm={() => act(() => api.deleteConversation(conv.id), "Conversation deleted").then(() => openConversation(null))}
      />
    </div>
  );
}

export function CompanionPage() {
  const activeId = useUi((s) => s.activeConversationId);
  const openConversation = useUi((s) => s.openConversation);
  const navigate = useUi((s) => s.navigate);
  const turn = useTurns((s) => (activeId ? s.byConversation[activeId] : undefined));
  const send = useTurns((s) => s.send);
  const cancel = useTurns((s) => s.cancel);
  const providers = useAtlasQuery("providers", api.providers, ["providers"]);
  const conv = useAtlasQuery(`conv:${activeId}`, () => (activeId ? api.conversations({ includeArchived: true, limit: 500 }).then((l) => l.find((c) => c.id === activeId) ?? null) : Promise.resolve(null)), ["conversations"]);
  const messages = useAtlasQuery(`msgs:${activeId}:${turn?.revision ?? 0}`, () => (activeId ? api.messages(activeId) : Promise.resolve([])), []);
  const [choice, setChoice] = useState<ModelChoice>({ providerId: null, model: null });
  const scroller = useRef<HTMLDivElement>(null);

  const noProviders = providers.data && providers.data.length === 0;
  const running = turn?.running ?? false;

  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.data, turn?.text, turn?.tools.length]);

  const onSend = async (text: string) => {
    let id = activeId;
    if (!id) {
      try {
        const c = await api.createConversation((await api.settings()).default_project_id);
        id = c.id;
        openConversation(id);
      } catch (e) {
        toast.error(e instanceof AtlasError ? e.message : "Could not start a conversation");
        return;
      }
    }
    // A click or key press: let Atlas's speech start when the reply arrives.
    audio.context();
    const v = useVoice.getState();
    if (v.settings?.enabled && v.settings.speak_responses) v.setAwaitingReply(true);
    void send(id, text, choice);
  };

  // A recognised voice request: send it at once, or leave it in the box to review.
  const voiceDraft = useVoice((s) => s.draft);
  const [composerDraft, setComposerDraft] = useState<{ text: string; nonce: number } | null>(null);
  const handledDraft = useRef(0);
  useEffect(() => {
    if (!voiceDraft || voiceDraft.nonce === handledDraft.current) return;
    handledDraft.current = voiceDraft.nonce;
    if (useVoice.getState().settings?.auto_send && !running) void onSend(voiceDraft.text);
    else setComposerDraft(voiceDraft);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voiceDraft]);

  const msgs = messages.data ?? [];
  const regenerateOk = Boolean(activeId) && !running && canRegenerate(msgs);
  const regenerate = () => {
    if (activeId && regenerateOk) void send(activeId, "", { ...choice, regenerate: true });
  };

  // Shortcuts: Esc stops a running reply; Ctrl/⌘+Shift+Enter regenerates the last one.
  const keys = useRef({ running, regenerate, stop: () => activeId && void cancel(activeId) });
  keys.current = { running, regenerate, stop: () => activeId && void cancel(activeId) };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || document.querySelector("[role=dialog]")) return;
      if (e.key === "Escape" && keys.current.running) {
        e.preventDefault();
        keys.current.stop();
      } else if (e.key === "Enter" && e.shiftKey && (e.ctrlKey || e.metaKey) && !keys.current.running) {
        e.preventDefault();
        keys.current.regenerate();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const transient = useMemo(() => (turn?.running ? turn.notices.filter((n) => n.level === "warn") : []), [turn]);

  return (
    <div className="flex h-full">
      <ConversationList activeId={activeId} onOpen={openConversation} />
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Conversation">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line-1 px-5">
          <h1 className="min-w-0 flex-1 truncate font-display text-[0.95rem] font-semibold">{conv.data?.title ?? "Companion"}</h1>
          <ModelPicker value={choice} onChange={setChoice} />
          {conv.data && <ConversationActions conv={conv.data} />}
        </header>
        <div ref={scroller} className="flex-1 overflow-y-auto">
          {noProviders ? (
            <EmptyState
              icon={<Plug className="size-5" aria-hidden />}
              title="Connect an AI model to start"
              body="Atlas needs at least one AI provider — a cloud service with your API key, or Ollama running on this computer."
              action={<Button variant="primary" onClick={() => navigate("integrations")}>Set up a provider</Button>}
            />
          ) : !activeId || (messages.data && messages.data.length === 0 && !running) ? (
            <div className="mx-auto flex max-w-2xl flex-col items-center px-6 pb-6 pt-[10vh] text-center">
              <Emblem size={64} glow />
              <h2 className="mt-5 font-display text-xl font-semibold">How can I help?</h2>
              <p className="mt-1.5 text-sm text-text-2">Ask a question, plan something, or have Atlas work with your files. Anything that changes something asks you first.</p>
              <div className="mt-6 grid w-full gap-2 sm:grid-cols-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => onSend(s)} className="rounded-lg border border-line-1 bg-bg-2/70 px-3.5 py-3 text-left text-sm text-text-2 transition-colors hover:border-line-3 hover:bg-bg-3 hover:text-text-1">
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : messages.error ? (
            <div className="p-6">
              <ErrorNote message={messages.error.message} onRetry={messages.reload} />
            </div>
          ) : (
            <>
              <Thread messages={msgs} canAskAgain={!running} running={running} onAskAgain={(t) => onSend(t)} onRegenerate={regenerate} onSpeak={(t) => useVoice.getState().speakText(t)} />
              {transient.map((n, i) => (
                <p key={i} className="mx-auto mb-2 max-w-3xl px-6 text-xs text-warn">{n.text}</p>
              ))}
              {turn && <LiveTurn turn={turn} />}
            </>
          )}
          {activeId && <BudgetPrompt conversationId={activeId} />}
        </div>
        <VoiceBar />
        <Composer
          draft={composerDraft}
          running={running}
          disabled={Boolean(noProviders)}
          disabledReason="Connect an AI provider first"
          onSend={onSend}
          onStop={() => activeId && void cancel(activeId)}
          autoFocus
        />
      </section>
    </div>
  );
}
