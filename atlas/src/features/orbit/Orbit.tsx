/**
 * ORBIT (Atlas): talk with Atlas, watch the plan form around the voice ring, shape it, approve it, run it.
 *
 * Atlas's own experience: the electric-blue voice ring is Atlas and sits at the centre; phases are
 * orbits, tasks are bodies on them. Every change goes through the core (`orbit_apply`), which owns the
 * rules: drafts until approved, no dependency loops, node states only from recorded events, paused
 * (never repeated) after a restart. Tool approvals stay in the Approvals dock, every time.
 */
import {
  Check,
  CircleDot,
  ListTree,
  Maximize2,
  Mic,
  MicOff,
  Minimize2,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Square,
  Undo2,
  VolumeX,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Markdown } from "@/components/Markdown";
import { Badge, Button, EmptyState, Input, Select } from "@/components/ui/primitives";
import { AtlasError, api } from "@/lib/bridge";
import { cn } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { OrbitNode, OrbitPlan, OrbitSession } from "@/lib/schemas";
import { onTurnEvent, useTurns } from "@/state/turns";
import { useUi } from "@/state/ui";
import { useVoice, voicePhase } from "@/state/voice";
import { audio } from "@/features/voice/audioEngine";
import { VoiceRing } from "@/features/voice/VoiceRing";
import { TurnTaker, findTask, layout, parseCommand, partialPlan, stripPlanBlocks } from "./orbitLogic";
import { OrbitSpace } from "./OrbitSpace";
import { coreState } from "./orbitSpace";

const MARK: Record<string, [string, string]> = {
  proposed: ["◌", "Proposed"],
  confirmed: ["○", "In the plan"],
  draft: ["◌", "Draft"],
  ready: ["○", "Ready"],
  waiting: ["⧗", "Waiting for a dependency"],
  awaiting_approval: ["?", "Awaiting your approval"],
  running: ["▶", "Running"],
  completed: ["✓", "Completed"],
  failed: ["!", "Failed"],
  paused: ["‖", "Paused"],
  cancelled: ["×", "Cancelled"],
  blocked: ["⊘", "Blocked"],
};
const TONE: Record<string, string> = {
  completed: "var(--ok)",
  running: "var(--accent)",
  failed: "var(--err)",
  awaiting_approval: "var(--warn)",
  blocked: "var(--warn)",
};
const OPS: [string, string][] = [
  ["atlas", "Atlas works on it"],
  ["research", "Atlas researches it"],
  ["todo", "Add to my tasks"],
  ["manual", "You do it"],
];
const AUTONOMY: [string, string, string][] = [
  ["approval_first", "Approval-first", "Every step waits for your go-ahead. Tools with real-world effects also ask."],
  [
    "balanced",
    "Balanced",
    "Thinking, research and task steps start on their own; anything that changes things waits. Tools always ask.",
  ],
  [
    "advanced",
    "Advanced",
    "The step kinds you allow start on their own. Tools with real-world effects still ask every time.",
  ],
];

function activePlan(s: OrbitSession | null): OrbitPlan | null {
  return s && s.active_version ? (s.versions[s.active_version - 1]?.plan ?? null) : null;
}

type Line = { who: "You" | "Atlas" | "ORBIT"; text: string; tone?: "warn" | "err" };

export function OrbitPage() {
  const sessions = useAtlasQuery("orbit_sessions", api.orbitSessions, []);
  const [session, setSession] = useState<OrbitSession | null>(null);
  const [view, setView] = useState<"orbit" | "outline">("orbit");
  const [tab, setTab] = useState<"talk" | "step" | "versions">("talk");
  const [sel, setSel] = useState<string>("");
  const [lines, setLines] = useState<Line[]>([]);
  const [input, setInput] = useState("");
  const [continuous, setContinuous] = useState(() => localStorage.getItem("orbit.continuous") !== "off");
  const [cmpVersion, setCmpVersion] = useState<number | null>(null);
  const immersive = useUi((s) => s.immersive);
  const setImmersive = useUi((s) => s.setImmersive);
  const voice = useVoice();
  const phase = voicePhase(voice);
  // select the stored state itself (stable between renders); `get` would build a new empty object each time
  // and make React re-render forever while a session has no turn yet
  const turn = useTurns((s) => (session?.conversation_id ? (s.byConversation[session.conversation_id] ?? null) : null));
  const send = useTurns((s) => s.send);
  const plan = activePlan(session);
  const runningNode = useRef<string | null>(null);
  const nodeConv = useRef<string | null>(null);

  const say = (l: Line) => setLines((x) => [...x.slice(-80), l]);
  const fail = (e: unknown) =>
    say({ who: "ORBIT", text: e instanceof AtlasError ? e.message : String(e), tone: "warn" });

  const act = useCallback(
    async (action: Record<string, unknown>, quiet = false) => {
      if (!session) return null;
      try {
        const r = await api.orbitApply(session.id, action);
        setSession(r.session);
        if (
          !quiet &&
          r.message &&
          !r.message.startsWith("run:") &&
          !r.message.startsWith("go-ahead:") &&
          r.message !== "ok"
        )
          say({ who: "ORBIT", text: r.message });
        sessions.reload();
        return r;
      } catch (e) {
        fail(e);
        return null;
      }
    },
    [session, sessions],
  );

  // open the most recent session (or none) on arrival
  useEffect(() => {
    if (session || !sessions.data) return;
    const last = localStorage.getItem("orbit.session") ?? sessions.data[0]?.id;
    if (last)
      void api
        .orbitGet(last)
        .then(setSession)
        .catch(() => localStorage.removeItem("orbit.session"));
  }, [sessions.data, session]);
  useEffect(() => {
    if (session) localStorage.setItem("orbit.session", session.id);
  }, [session?.id]);

  const newSession = async (title = "") => {
    try {
      const s = await api.orbitCreate(title, localStorage.getItem("orbit.autonomy") ?? "approval_first");
      setSession(s);
      setLines([]);
      sessions.reload();
      return s;
    } catch (e) {
      fail(e);
      return null;
    }
  };

  // ----- the conversation -----
  const talk = async (text: string) => {
    text = text.trim();
    if (!text) return;
    setInput("");
    say({ who: "You", text });
    const cmd = parseCommand(text, plan);
    if (cmd && "control" in cmd) {
      if (cmd.control === "stop_speaking") voice.stopSpeaking();
      else if (cmd.control === "pause") await act({ action: "pause" });
      else if (cmd.control === "resume") await act({ action: "resume" });
      else await cancelWorkflow();
      return;
    }
    if (cmd && "undo" in cmd) return void act({ action: "undo" });
    if (cmd && "edit" in cmd) return void act({ action: "edit", edit: cmd.edit, why: text });
    const s = session ?? (await newSession(text.slice(0, 60)));
    if (!s?.conversation_id) return;
    runningNode.current = null;
    await send(s.conversation_id, text, { orbitSessionId: s.id });
    try {
      const r = await api.orbitPropose(s.id);
      setSession(r.session);
      if (r.message) say({ who: "ORBIT", text: r.message });
    } catch (e) {
      fail(e);
    }
  };

  // replies from Atlas in this session's conversation
  const lastRevision = useRef(0);
  useEffect(() => {
    if (!turn || !session?.conversation_id || turn.running) return;
    if (turn.revision === lastRevision.current) return;
    lastRevision.current = turn.revision;
    if (turn.error) say({ who: "ORBIT", text: turn.error, tone: "err" });
  }, [turn, session?.conversation_id]);
  const streaming = turn?.running ? turn.text : "";
  const provisional = useMemo(() => (streaming ? partialPlan(streaming) : { phases: [], tasks: [] }), [streaming]);

  // the transcript shows Atlas's replies without the plan blocks
  const replies = useAtlasQuery(
    `orbit_msgs_${session?.conversation_id ?? "none"}`,
    () => (session?.conversation_id ? api.messages(session.conversation_id) : Promise.resolve([])),
    ["conversations"],
  );
  useEffect(() => {
    replies.reload();
  }, [turn?.revision]);

  // ----- voice: continuous conversation or push-to-talk -----
  const taker = useRef(new TurnTaker());
  useEffect(() => {
    if (voice.capture !== "listening" || !continuous) return;
    taker.current.reset(performance.now() / 1000);
    let raf = 0;
    const loop = () => {
      const ev = taker.current.feed(audio.level(), performance.now() / 1000);
      if (ev === "end") void voice.stopListening();
      else if (ev === "idle") {
        voice.cancelListening();
        say({ who: "ORBIT", text: "Stopped listening after a long silence. Press Talk to continue." });
        return;
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [voice.capture, continuous]);
  // what you said arrives as a draft: in ORBIT it is sent (the transcript shows it)
  const lastDraft = useRef(0);
  useEffect(() => {
    if (!voice.draft || voice.draft.nonce === lastDraft.current) return;
    lastDraft.current = voice.draft.nonce;
    void talk(voice.draft.text);
  }, [voice.draft]);
  // after Atlas finishes speaking, listen again (continuous), never while a step or approval waits
  const prevPlayback = useRef(voice.playback);
  useEffect(() => {
    const was = prevPlayback.current;
    prevPlayback.current = voice.playback;
    if (
      continuous &&
      was === "speaking" &&
      voice.playback === "idle" &&
      voice.capture === "off" &&
      !runningNode.current
    )
      void voice.startListening();
  }, [voice.playback]);

  // ----- workflow execution (each step through the real turn engine; approvals in the dock) -----
  const runNode = async (s: OrbitSession, nodeId: string) => {
    const node = s.workflow?.nodes.find((n) => n.id === nodeId);
    if (!node) return;
    if (node.operation === "todo") {
      try {
        const r = await api.orbitRunTodo(s.id, nodeId);
        setSession(r.session);
        say({ who: "ORBIT", text: `“${node.title}”: added to Tasks.` });
        return advance(r.session);
      } catch (e) {
        return fail(e);
      }
    }
    const p = s.versions[(s.workflow?.plan_version ?? 1) - 1]?.plan;
    const ask =
      node.operation === "research"
        ? "Investigate and report. Do not change anything."
        : "Do this step and only this step.";
    const text = `ORBIT step from the approved plan “${p?.title ?? ""}” (objective: ${p?.objective || "not stated"}). ${ask}\n\n${node.title}${node.detail ? ` — ${node.detail}` : ""}\n\nReport plainly what you did, what you found and what is left open.`;
    try {
      const conv = await api.createConversation(null, `ORBIT step · ${node.title}`.slice(0, 80));
      runningNode.current = nodeId;
      nodeConv.current = conv.id;
      const started = await api.orbitApply(s.id, { action: "step_started", node: nodeId, conversation_id: conv.id });
      setSession(started.session);
      await send(conv.id, text);
      const t = useTurns.getState().get(conv.id);
      const msgs = await api.messages(conv.id).catch(() => []);
      const reply = [...msgs].reverse().find((m) => m.role === "assistant" && m.content.trim())?.content ?? "";
      const ok = !t.error && t.outcome !== "failed" && t.outcome !== "cancelled";
      const r = await api.orbitApply(s.id, {
        action: "step_finished",
        node: nodeId,
        ok,
        output: reply.slice(0, 4000),
        error: t.error ?? (t.outcome === "cancelled" ? "cancelled" : ""),
      });
      setSession(r.session);
      runningNode.current = null;
      nodeConv.current = null;
      say({
        who: "ORBIT",
        text: ok ? `Step done: ${node.title}` : `Step failed: ${node.title}. Retry it or change the plan.`,
        tone: ok ? undefined : "err",
      });
      if (ok) advance(r.session);
    } catch (e) {
      runningNode.current = null;
      fail(e);
    }
  };

  // tool approvals inside a running step: recorded on the node, decided in the dock
  useEffect(() => {
    return onTurnEvent((cid, e) => {
      if (!session || cid !== nodeConv.current || !runningNode.current) return;
      if (e.type === "tool" && e.event.type === "approval_required")
        void act({ action: "step_waiting_for_tool", node: runningNode.current, tool: e.event.approval.tool_id }, true);
      if (e.type === "tool" && e.event.type === "step_finished") {
        const n = session.workflow?.nodes.find((x) => x.id === runningNode.current);
        if (n?.status === "awaiting_approval")
          void act(
            { action: "step_tool_answered", node: runningNode.current, approved: e.event.status !== "denied" },
            true,
          );
      }
    });
  }, [session, act]);

  const advance = (s: OrbitSession) => {
    const w = s.workflow;
    if (!w || w.paused) return;
    if (w.state === "completed") {
      toast.success("ORBIT workflow complete", { description: s.title });
      return;
    }
    if (w.nodes.some((n) => n.status === "ready")) setTimeout(() => void startNext(s), 300);
  };

  const startNext = async (s = session) => {
    if (!s) return;
    try {
      const r = await api.orbitApply(s.id, { action: "start_next" });
      setSession(r.session);
      const [kind, id = ""] = r.message.split(":");
      if (kind === "run") void runNode(r.session, id);
      else if (kind === "go-ahead") {
        setSel(id);
        setTab("step");
        say({
          who: "ORBIT",
          text: `Ready for the next step: “${r.session.workflow?.nodes.find((n) => n.id === id)?.title}”. Approve it when you are ready.`,
        });
      }
    } catch (e) {
      fail(e);
    }
  };

  const approveStep = async (id: string) => {
    const r = await act({ action: "approve_step", node: id });
    if (!r) return;
    if (r.message.startsWith("run:")) void runNode(r.session, id);
    else advance(r.session);
  };

  const cancelWorkflow = async () => {
    if (
      !window.confirm(
        "Stop the running step and cancel every step that has not finished? Completed steps stay completed; nothing is undone.",
      )
    )
      return;
    if (nodeConv.current) await api.cancel(nodeConv.current).catch(() => false);
    await act({ action: "cancel" });
  };

  // ----- keyboard -----
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && immersive && voice.playback !== "speaking" && voice.capture === "off")
        setImmersive(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [immersive, voice.playback, voice.capture]);

  const wf = session?.workflow ?? null;
  const status = useMemo(() => Object.fromEntries((wf?.nodes ?? []).map((n) => [n.id, n.status])), [wf]);
  const selTask = plan ? findTask(plan, sel) : undefined;
  const selNode = wf?.nodes.find((n) => n.id === sel);
  const waiting = wf?.nodes.find((n) => n.status === "awaiting_approval");
  const running = wf?.nodes.some((n) => n.status === "running") ?? false;
  const v = session?.active_version ?? 0;
  const approved = session?.approved_version ?? 0;
  const done = wf?.nodes.filter((n) => n.status === "completed").length ?? 0;
  const ringPhase = phase === "idle" && (turn?.running || running) ? "processing" : phase;

  const transcript = (replies.data ?? [])
    .filter((m) => (m.role === "user" || m.role === "assistant") && m.content.trim())
    .slice(-40);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 px-5 py-4">
      <header className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 font-display text-lg tracking-[0.3em] text-accent-strong">ORBIT</h1>
        <Select
          aria-label="ORBIT session"
          value={session?.id ?? ""}
          onChange={(e) =>
            e.target.value && void api.orbitGet(e.target.value).then((s) => (setSession(s), setLines([])))
          }
          className="w-64"
        >
          {!session && <option value="">No session yet</option>}
          {(sessions.data ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.title}
              {r.workflow_state ? ` · ${r.workflow_state}` : ""}
            </option>
          ))}
        </Select>
        <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => void newSession()}>
          New session
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <label className="text-xs text-text-3" htmlFor="orbit-autonomy">
            Autonomy
          </label>
          <Select
            id="orbit-autonomy"
            value={session?.autonomy ?? "approval_first"}
            title={AUTONOMY.find((a) => a[0] === session?.autonomy)?.[2]}
            onChange={(e) => {
              localStorage.setItem("orbit.autonomy", e.target.value);
              void act({
                action: "set_autonomy",
                autonomy: e.target.value,
                allowed: e.target.value === "advanced" ? ["think", "read", "organise"] : [],
              });
            }}
            disabled={!session}
          >
            {AUTONOMY.map(([k, n]) => (
              <option key={k} value={k}>
                {n}
              </option>
            ))}
          </Select>
          <Button
            size="sm"
            icon={<ListTree className="size-3.5" />}
            onClick={() => setView(view === "orbit" ? "outline" : "orbit")}
          >
            {view === "orbit" ? "Outline" : "Orbit view"}
          </Button>
          <Button
            size="sm"
            icon={immersive ? <Minimize2 className="size-3.5" /> : <Maximize2 className="size-3.5" />}
            onClick={() => setImmersive(!immersive)}
          >
            {immersive ? "Exit immersive" : "Immersive"}
          </Button>
        </div>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_400px] gap-4">
        <section className="flex min-h-0 flex-col gap-2" aria-label="Plan">
          <p className="text-sm text-text-2">
            {plan ? (
              <>
                <strong className="text-text-1">{plan.title}</strong>
                {plan.objective && ` — ${plan.objective}`}
                <span className="block text-xs text-text-3">
                  Version {v} ·{" "}
                  {approved === v ? "approved" : approved ? `draft (approved: v${approved})` : "draft, not approved"} ·{" "}
                  {plan.tasks.length} tasks in {plan.phases.length} phases · {plan.questions.length} open questions
                </span>
              </>
            ) : (
              "Tell Atlas what you want to achieve. As you talk, the plan forms around the ring; you shape it, approve it, then run it."
            )}
          </p>
          <div className={cn("relative min-h-0 flex-1 overflow-hidden", view !== "orbit" && "rounded-lg border border-line-1 bg-bg-0/60")}>
            {view === "orbit" ? (
              <OrbitSpace
                session={session}
                coreState={coreState({
                  voice: phase,
                  turnRunning: !!turn?.running,
                  planning: provisional.tasks.length > 0 || provisional.phases.length > 0,
                  waiting: !!waiting,
                  running,
                  failed: !!wf?.nodes.some((n) => n.status === "failed"),
                  completed: wf?.state === "completed",
                })}
                provisional={provisional}
                speaking={phase === "speaking"}
                onAct={act}
                onLink={(kind, ref) => {
                  if (kind === "approve" && waiting?.id === ref) void approveStep(ref);
                  else if (kind === "file") useUi.getState().navigate("files");
                  else {
                    setSel(ref);
                    setTab("step");
                  }
                }}
                constellation={
                  <Stage
                    plan={plan}
                    status={status}
                    provisional={provisional}
                    sel={sel}
                    onSelect={(id) => (setSel(id), setTab("step"))}
                    onMove={(id, ph) => void act({ action: "edit", edit: { op: "move_to_phase", task: id, phase: ph } })}
                    onRemove={(id) => void act({ action: "edit", edit: { op: "remove_task", task: id } })}
                  >
                    {null}
                  </Stage>
                }
              >
                <VoiceRing phase={ringPhase} size={150} />
              </OrbitSpace>
            ) : (
              <Outline plan={plan} status={status} sel={sel} onSelect={(id) => (setSel(id), setTab("step"))} />
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-text-3">
            <span className="mr-auto" aria-live="polite">
              {wf
                ? `Workflow (from v${wf.plan_version}): ${wf.state}${wf.paused ? " · paused" : ""} · ${done}/${wf.nodes.length} steps done`
                : plan
                  ? approved === v
                    ? "Approved. Build the workflow when you are ready."
                    : "Approve the plan, then build its workflow."
                  : ""}
            </span>
            {plan && approved !== v && !running && (
              <Button
                size="sm"
                variant="primary"
                icon={<Check className="size-3.5" />}
                onClick={() => void act({ action: "approve" })}
              >
                Approve plan
              </Button>
            )}
            {plan &&
              approved === v &&
              approved > 0 &&
              !running &&
              (!wf || ["completed", "cancelled"].includes(wf.state) || wf.plan_version !== approved) && (
                <Button size="sm" onClick={() => void act({ action: "build_workflow" })}>
                  Build workflow
                </Button>
              )}
            {wf && !running && !wf.paused && !waiting && wf.nodes.some((n) => n.status === "ready") && (
              <Button size="sm" icon={<Play className="size-3.5" />} onClick={() => void startNext()}>
                Start
              </Button>
            )}
            {waiting && (
              <Button size="sm" variant="primary" onClick={() => void approveStep(waiting.id)}>
                Approve step: {waiting.title.slice(0, 24)}
              </Button>
            )}
            {wf &&
              !["completed", "cancelled"].includes(wf.state) &&
              (wf.paused ? (
                <Button
                  size="sm"
                  icon={<Play className="size-3.5" />}
                  onClick={() => void act({ action: "resume" }).then((r) => r && advance(r.session))}
                >
                  Resume
                </Button>
              ) : (
                <Button size="sm" icon={<Pause className="size-3.5" />} onClick={() => void act({ action: "pause" })}>
                  Pause
                </Button>
              ))}
            {selNode && ["failed", "cancelled", "blocked"].includes(selNode.status) && !running && (
              <Button
                size="sm"
                icon={<RotateCcw className="size-3.5" />}
                onClick={() => void act({ action: "retry", node: selNode.id }).then((r) => r && advance(r.session))}
              >
                Retry step
              </Button>
            )}
            {wf && !["completed", "cancelled"].includes(wf.state) && (
              <Button
                size="sm"
                variant="danger"
                icon={<Square className="size-3.5" />}
                onClick={() => void cancelWorkflow()}
              >
                Cancel workflow
              </Button>
            )}
            {wf?.state === "completed" && !session?.reviewed && (
              <Button size="sm" onClick={() => void act({ action: "mark_reviewed" })}>
                Mark reviewed
              </Button>
            )}
            {session?.reviewed && !session.completed && (
              <Button size="sm" variant="primary" onClick={() => void act({ action: "mark_complete" })}>
                Mark complete
              </Button>
            )}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col gap-2" aria-label="Conversation and details">
          <div role="tablist" className="flex gap-1 border-b border-line-1">
            {(["talk", "step", "versions"] as const).map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={cn(
                  "px-3 py-2 text-sm",
                  tab === t ? "border-b-2 border-accent text-accent-strong" : "text-text-3 hover:text-text-1",
                )}
              >
                {t === "talk" ? "Conversation" : t === "step" ? "Step" : "Versions"}
              </button>
            ))}
          </div>
          {tab === "talk" && (
            <div className="flex min-h-0 flex-1 flex-col gap-2">
              <div className="text-sm" aria-live="polite">
                <span className="text-accent-strong">●</span>{" "}
                {phase === "listening"
                  ? "Listening · microphone on"
                  : phase === "speaking"
                    ? "Speaking"
                    : turn?.running
                      ? provisional.tasks.length
                        ? "Planning"
                        : "Thinking"
                      : running
                        ? "Running the workflow"
                        : waiting
                          ? "Waiting for you"
                          : "Ready"}
              </div>
              <div
                className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-md border border-line-1 bg-bg-1/60 p-3 text-sm"
                aria-label="Transcript"
              >
                {!transcript.length && !lines.length && (
                  <p className="text-text-3">
                    Say or type what you want to achieve. Atlas asks what it needs to know, then proposes a plan you can
                    change by voice or by hand. Nothing runs until you approve.
                  </p>
                )}
                {transcript.map((m) => (
                  <div key={m.id}>
                    <div
                      className={cn("text-xs font-semibold", m.role === "user" ? "text-text-2" : "text-accent-strong")}
                    >
                      {m.role === "user" ? "You" : "Atlas"}
                    </div>
                    <Markdown text={stripPlanBlocks(m.content)} />
                  </div>
                ))}
                {streaming && (
                  <div>
                    <div className="text-xs font-semibold text-accent-strong">Atlas</div>
                    <Markdown text={stripPlanBlocks(streaming)} />
                  </div>
                )}
                {lines
                  .filter((l) => l.who === "ORBIT")
                  .slice(-6)
                  .map((l, i) => (
                    <p
                      key={i}
                      className={cn(
                        "text-xs",
                        l.tone === "err" ? "text-err" : l.tone === "warn" ? "text-warn" : "text-text-3",
                      )}
                    >
                      {l.text}
                    </p>
                  ))}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant={voice.capture === "listening" ? "subtle" : "primary"}
                  icon={voice.capture === "listening" ? <MicOff className="size-4" /> : <Mic className="size-4" />}
                  onClick={() => void voice.toggleListening()}
                  disabled={!voice.status?.stt_ready || !voice.settings?.enabled}
                  title={
                    voice.status?.stt_ready
                      ? "Talk (Ctrl+Shift+Space)"
                      : "Set up speech recognition in Settings → Voice"
                  }
                >
                  {voice.capture === "listening"
                    ? "Send what I said"
                    : voice.capture === "transcribing"
                      ? "Understanding…"
                      : "Talk"}
                </Button>
                <label className="flex items-center gap-1.5 text-xs text-text-2">
                  <input
                    type="checkbox"
                    checked={continuous}
                    onChange={(e) => (
                      setContinuous(e.target.checked),
                      localStorage.setItem("orbit.continuous", e.target.checked ? "on" : "off")
                    )}
                  />
                  Continuous
                </label>
                <Button
                  size="sm"
                  icon={<VolumeX className="size-3.5" />}
                  onClick={() => voice.stopSpeaking()}
                  disabled={voice.playback !== "speaking"}
                >
                  Stop speaking
                </Button>
                <Button
                  size="sm"
                  icon={<X className="size-3.5" />}
                  onClick={() => {
                    voice.stopSpeaking();
                    voice.cancelListening();
                    if (turn?.running && session?.conversation_id) void api.cancel(session.conversation_id);
                    say({ who: "ORBIT", text: "Conversation ended. The plan and any workflow are unchanged." });
                  }}
                >
                  End conversation
                </Button>
              </div>
              <form className="flex gap-2" onSubmit={(e) => (e.preventDefault(), void talk(input))}>
                <Input
                  aria-label="Message to Atlas"
                  placeholder="Describe what you want, or edit the plan: “add task Write tests to Build”…"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                />
                <Button type="submit" disabled={!input.trim() || Boolean(turn?.running)}>
                  Send
                </Button>
              </form>
              <p className="text-[0.7rem] leading-snug text-text-3">
                Speech is recognised and spoken on this computer by Atlas's own voice engines. The microphone is on only
                while ORBIT is listening; while Atlas speaks it is paused (no echo cancellation), so interrupt with Stop
                speaking or Esc.
              </p>
            </div>
          )}
          {tab === "step" && (
            <StepPanel
              plan={plan}
              task={selTask}
              node={selNode}
              running={running}
              onEdit={(edit) => void act({ action: "edit", edit })}
              onApprove={(id) => void approveStep(id)}
              onDone={(id) => void act({ action: "mark_done", node: id }).then((r) => r && advance(r.session))}
              onUndo={() => void act({ action: "undo" })}
              canUndo={v > 1 && !running}
            />
          )}
          {tab === "versions" && session && (
            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto text-sm">
              {[...session.versions].reverse().map((ver) => (
                <button
                  key={ver.version}
                  onClick={() => setCmpVersion(ver.version)}
                  className={cn(
                    "rounded-md border px-3 py-2 text-left",
                    cmpVersion === ver.version ? "border-accent" : "border-line-1",
                  )}
                >
                  <div className="text-xs text-text-3">
                    v{ver.version} · {ver.author === "atlas" ? "Atlas" : "You"} ·{" "}
                    {new Date(ver.at).toLocaleTimeString()}
                    {ver.version === session.active_version && " · active"}
                    {ver.version === session.approved_version && " · approved"}
                  </div>
                  <div>{ver.why}</div>
                </button>
              ))}
              {cmpVersion && cmpVersion !== session.active_version && (
                <div className="rounded-md border border-line-1 p-3">
                  <Compare
                    a={session.versions[cmpVersion - 1]?.plan ?? plan!}
                    b={plan!}
                    label={`From v${cmpVersion} to the active v${v}`}
                  />
                  <Button
                    size="sm"
                    className="mt-2"
                    onClick={() => void act({ action: "restore", version: cmpVersion })}
                    disabled={running}
                  >
                    Restore this version
                  </Button>
                </div>
              )}
              <div className="mt-2 text-xs text-text-3">
                {session.events
                  .slice(-12)
                  .reverse()
                  .map((e, i) => (
                    <div key={i}>
                      {new Date(e.at).toLocaleTimeString()} {e.kind} {e.detail}
                    </div>
                  ))}
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function Compare({ a, b, label }: { a: OrbitPlan; b: OrbitPlan; label: string }) {
  const ta = new Map(a.tasks.map((t) => [t.id, t]));
  const tb = new Map(b.tasks.map((t) => [t.id, t]));
  const out: string[] = [];
  b.tasks.forEach((t) => !ta.has(t.id) && out.push(`+ ${t.title}`));
  a.tasks.forEach((t) => !tb.has(t.id) && out.push(`− ${t.title}`));
  b.tasks.forEach((t) => {
    const x = ta.get(t.id);
    if (!x) return;
    if (x.title !== t.title) out.push(`renamed: ${x.title} → ${t.title}`);
    if (x.phase !== t.phase) out.push(`moved: ${t.title} (${x.phase} → ${t.phase})`);
    if (x.priority !== t.priority) out.push(`priority: ${t.title} ${x.priority} → ${t.priority}`);
  });
  if (a.phases.join() !== b.phases.join()) out.push(`phases: ${b.phases.join(" → ")}`);
  return (
    <div>
      <div className="text-xs text-text-3">{label}</div>
      {out.length ? out.map((l, i) => <div key={i}>{l}</div>) : <div>No differences.</div>}
    </div>
  );
}

function StepPanel({
  plan,
  task,
  node,
  running,
  onEdit,
  onApprove,
  onDone,
  onUndo,
  canUndo,
}: {
  plan: OrbitPlan | null;
  task?: OrbitPlan["tasks"][number];
  node?: OrbitNode;
  running: boolean;
  onEdit: (e: Record<string, string>) => void;
  onApprove: (id: string) => void;
  onDone: (id: string) => void;
  onUndo: () => void;
  canUndo: boolean;
}) {
  const [rename, setRename] = useState("");
  const [newTask, setNewTask] = useState("");
  useEffect(() => setRename(task?.title ?? ""), [task?.id]);
  if (!plan)
    return (
      <EmptyState
        icon={<CircleDot />}
        title="No plan yet"
        body="Talk to Atlas in the Conversation tab; the plan appears here and around the ring."
      />
    );
  const st = node?.status ?? task?.status ?? "";
  const deps = task
    ? plan.deps
        .filter((d) => d.to === task.id)
        .map((d) => plan.tasks.find((t) => t.id === d.from)?.title)
        .filter(Boolean)
    : [];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto text-sm">
      {!task ? (
        <div className="text-text-3">
          Select a task on the orbit or in the outline.
          {plan.questions.length > 0 && (
            <ul className="mt-2 list-disc pl-5">
              {plan.questions.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          )}
        </div>
      ) : (
        <>
          <div>
            <h2 className="text-base font-semibold">{task.title}</h2>
            <div className="text-xs text-text-3">
              {MARK[st]?.[0]} {MARK[st]?.[1] ?? st} · {task.phase} · {task.priority} priority · done by:{" "}
              {OPS.find((o) => o[0] === task.operation)?.[1]}
              {deps.length > 0 && ` · waits for: ${deps.join(", ")}`}
            </div>
          </div>
          {task.detail && <p>{task.detail}</p>}
          {node?.status === "awaiting_approval" && node.history.at(-1)?.event.includes("go-ahead") && (
            <Button
              variant="primary"
              onClick={() => (node.operation === "manual" ? onDone(node.id) : onApprove(node.id))}
            >
              {node.operation === "manual" ? "Mark done" : "Approve this step"}
            </Button>
          )}
          {node?.status === "awaiting_approval" && !node.history.at(-1)?.event.includes("go-ahead") && (
            <Badge tone="warn">A tool in this step is waiting in Approvals</Badge>
          )}
          {node?.output && (
            <div className="rounded-md border border-line-1 p-2">
              <div className="text-xs text-text-3">Result</div>
              <Markdown text={node.output} />
            </div>
          )}
          {node?.error && <p className="text-err">Error: {node.error}</p>}
          {node && (
            <div className="text-xs text-text-3">
              {node.history.map((h, i) => (
                <div key={i}>
                  {new Date(h.at).toLocaleTimeString()} {h.event}
                </div>
              ))}
            </div>
          )}
          <fieldset disabled={running} className="flex flex-wrap gap-2">
            <Input aria-label="Task name" value={rename} onChange={(e) => setRename(e.target.value)} className="w-48" />
            <Button
              size="sm"
              onClick={() =>
                rename.trim() && rename !== task.title && onEdit({ op: "rename_task", task: task.id, title: rename })
              }
            >
              Rename
            </Button>
            <Select
              aria-label="Phase"
              value={task.phase}
              onChange={(e) => onEdit({ op: "move_to_phase", task: task.id, phase: e.target.value })}
            >
              {plan.phases.map((p) => (
                <option key={p}>{p}</option>
              ))}
            </Select>
            <Select
              aria-label="Priority"
              value={task.priority}
              onChange={(e) => onEdit({ op: "set_priority", task: task.id, priority: e.target.value })}
            >
              {["high", "normal", "low"].map((p) => (
                <option key={p}>{p}</option>
              ))}
            </Select>
            <Select
              aria-label="Done by"
              value={task.operation}
              onChange={(e) => onEdit({ op: "set_operation", task: task.id, operation: e.target.value })}
            >
              {OPS.map(([k, n]) => (
                <option key={k} value={k}>
                  {n}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Waits for"
              value=""
              onChange={(e) =>
                e.target.value &&
                onEdit({
                  op: deps.includes(e.target.value) ? "remove_dep" : "add_dep",
                  before: e.target.value,
                  after: task.id,
                })
              }
            >
              <option value="">Waits for…</option>
              {plan.tasks
                .filter((t) => t.id !== task.id)
                .map((t) => (
                  <option key={t.id} value={t.title}>
                    {deps.includes(t.title) ? "✓ " : ""}
                    {t.title}
                  </option>
                ))}
            </Select>
            <Button size="sm" variant="danger" onClick={() => onEdit({ op: "remove_task", task: task.id })}>
              Remove
            </Button>
          </fieldset>
        </>
      )}
      <form
        className="flex gap-2"
        onSubmit={(e) => (
          e.preventDefault(),
          newTask.trim() && (onEdit({ op: "add_task", title: newTask, phase: task?.phase ?? "" }), setNewTask(""))
        )}
      >
        <Input
          aria-label="New task"
          placeholder="Add a task…"
          value={newTask}
          onChange={(e) => setNewTask(e.target.value)}
          disabled={running}
        />
        <Button type="submit" size="sm" disabled={running || !newTask.trim()}>
          Add
        </Button>
        <Button type="button" size="sm" icon={<Undo2 className="size-3.5" />} onClick={onUndo} disabled={!canUndo}>
          Undo
        </Button>
      </form>
    </div>
  );
}

function Outline({
  plan,
  status,
  sel,
  onSelect,
}: {
  plan: OrbitPlan | null;
  status: Record<string, string>;
  sel: string;
  onSelect: (id: string) => void;
}) {
  if (!plan)
    return (
      <EmptyState
        icon={<ListTree />}
        title="No plan yet"
        body="The outline lists the same plan as the orbit view, phase by phase."
      />
    );
  return (
    <div className="h-full overflow-y-auto p-4" role="tree" aria-label="Plan outline">
      {plan.phases.map((ph, i) => (
        <div key={ph} role="group" className="mb-4">
          <div className="mb-1 text-xs uppercase tracking-widest text-text-3">
            {i + 1}. {ph}
          </div>
          {plan.tasks
            .filter((t) => t.phase === ph)
            .map((t) => {
              const st = status[t.id] ?? t.status;
              return (
                <button
                  key={t.id}
                  role="treeitem"
                  aria-selected={sel === t.id}
                  onClick={() => onSelect(t.id)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-3 py-1.5 text-left text-sm",
                    sel === t.id ? "bg-accent-softer" : "hover:bg-bg-3",
                  )}
                >
                  <span aria-hidden style={{ color: TONE[st] }}>
                    {MARK[st]?.[0]}
                  </span>
                  <span className="flex-1">{t.title}</span>
                  <span className="text-xs text-text-3">
                    {MARK[st]?.[1]} · {t.priority}
                  </span>
                </button>
              );
            })}
        </div>
      ))}
    </div>
  );
}

function Stage({
  plan,
  status,
  provisional,
  sel,
  onSelect,
  onMove,
  onRemove,
  children,
}: {
  plan: OrbitPlan | null;
  status: Record<string, string>;
  provisional: { phases: string[]; tasks: string[] };
  sel: string;
  onSelect: (id: string) => void;
  onMove: (id: string, phase: string) => void;
  onRemove: (id: string) => void;
  children: React.ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [zoom, setZoom] = useState(1);
  const [drag, setDrag] = useState<{ id: string; x: number; y: number } | null>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const shown =
    plan ??
    (provisional.tasks.length
      ? {
          title: "",
          objective: "",
          outcome: "",
          brief: "",
          ideas: [],
          phases: provisional.phases.length ? provisional.phases : ["Plan"],
          tasks: provisional.tasks.map((t, i) => ({
            id: `p${i}`,
            title: t,
            phase: provisional.phases[0] ?? "Plan",
            detail: "",
            priority: "normal",
            estimate: "",
            status: "proposed",
            operation: "atlas",
          })),
          deps: [],
          assumptions: [],
          questions: [],
          risks: [],
        }
      : null);
  const scaled = { w: size.w * zoom, h: size.h * zoom };
  const { pos, radius } = shown ? layout(shown, scaled) : { pos: {}, radius: () => 0 };
  const off = { x: (size.w - scaled.w) / 2, y: (size.h - scaled.h) / 2 };
  const ids = shown?.tasks.map((t) => t.id) ?? [];
  const ringAt = (x: number, y: number) => {
    if (!shown) return "";
    const d = Math.hypot(x - size.w / 2, y - size.h / 2);
    let best = 0;
    shown.phases.forEach((_, i) => {
      if (Math.abs(radius(i) - d) < Math.abs(radius(best) - d)) best = i;
    });
    return shown.phases[best];
  };
  return (
    <div
      ref={box}
      className="relative h-full w-full outline-none"
      tabIndex={0}
      aria-label="ORBIT plan: phases are orbits around Atlas; use the arrow keys to move between tasks, Enter to open, Delete to remove. The Outline view lists the same plan."
      onWheel={(e) => setZoom((z) => Math.max(0.6, Math.min(2, z * (e.deltaY < 0 ? 1.1 : 1 / 1.1))))}
      onKeyDown={(e) => {
        if (!plan || !ids.length) return;
        const i = ids.indexOf(sel);
        if (["ArrowRight", "ArrowDown"].includes(e.key)) onSelect(ids[(i + 1) % ids.length] ?? "");
        else if (["ArrowLeft", "ArrowUp"].includes(e.key)) onSelect(ids[(i - 1 + ids.length) % ids.length] ?? "");
        else if (e.key === "Delete" && sel) onRemove(sel);
        else if (e.key === "+" || e.key === "=") setZoom((z) => Math.min(2, z * 1.1));
        else if (e.key === "-") setZoom((z) => Math.max(0.6, z / 1.1));
        else if (e.key === "0") setZoom(1);
        else return;
        e.preventDefault();
      }}
    >
      <svg className="absolute inset-0 h-full w-full" role="presentation">
        <g transform={`translate(${off.x} ${off.y})`}>
          {shown?.phases.map((ph, i) => (
            <g key={ph}>
              <circle
                cx={scaled.w / 2}
                cy={scaled.h / 2}
                r={radius(i)}
                fill="none"
                stroke="var(--line-2)"
                strokeDasharray={plan ? undefined : "4 6"}
              />
              <text
                x={scaled.w / 2}
                y={scaled.h / 2 - radius(i) - 6}
                textAnchor="middle"
                className="fill-[color:var(--text-3)] text-[10px] uppercase tracking-widest"
              >
                {i + 1} {ph}
              </text>
            </g>
          ))}
          {plan?.deps.map((d) => {
            const a = pos[d.from];
            const b = pos[d.to];
            if (!a || !b) return null;
            const cx = (a.x + b.x) / 2 + (scaled.w / 2 - (a.x + b.x) / 2) * 0.35;
            const cy = (a.y + b.y) / 2 + (scaled.h / 2 - (a.y + b.y) / 2) * 0.35;
            return (
              <path
                key={`${d.from}-${d.to}`}
                d={`M${a.x},${a.y} Q${cx},${cy} ${b.x},${b.y}`}
                fill="none"
                stroke="var(--accent)"
                strokeOpacity={0.25}
                markerEnd="url(#orbit-arrow)"
              />
            );
          })}
          <defs>
            <marker
              id="orbit-arrow"
              viewBox="0 0 10 10"
              refX="22"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M0,0 L10,5 L0,10 z" fill="var(--accent)" fillOpacity={0.4} />
            </marker>
          </defs>
          {shown?.tasks.map((t) => {
            const p = drag?.id === t.id ? { x: drag.x - off.x, y: drag.y - off.y } : pos[t.id];
            if (!p) return null;
            const st = status[t.id] ?? t.status;
            const right = p.x >= scaled.w / 2;
            return (
              <g
                key={t.id}
                role="button"
                aria-label={`${t.title}: ${MARK[st]?.[1] ?? st}, ${t.phase}`}
                className="cursor-pointer"
                onPointerDown={(e) => {
                  if (!plan) return;
                  (e.target as Element).setPointerCapture?.(e.pointerId);
                  onSelect(t.id);
                  setDrag({ id: t.id, x: p.x + off.x, y: p.y + off.y });
                }}
                onPointerMove={(e) =>
                  drag?.id === t.id &&
                  box.current &&
                  setDrag({
                    id: t.id,
                    x: e.clientX - box.current.getBoundingClientRect().left,
                    y: e.clientY - box.current.getBoundingClientRect().top,
                  })
                }
                onPointerUp={() => {
                  if (drag?.id === t.id) {
                    const ph = ringAt(drag.x, drag.y);
                    setDrag(null);
                    if (ph && ph !== t.phase) onMove(t.id, ph);
                  }
                }}
              >
                <circle
                  cx={p.x}
                  cy={p.y}
                  r={t.priority === "high" ? 15 : 12}
                  fill="var(--bg-2)"
                  stroke={TONE[st] ?? "var(--accent)"}
                  strokeWidth={sel === t.id ? 2.5 : 1.3}
                  strokeDasharray={st === "proposed" ? "3 3" : undefined}
                />
                {sel === t.id && (
                  <circle cx={p.x} cy={p.y} r={20} fill="none" stroke="var(--accent-strong)" strokeOpacity={0.6} />
                )}
                <text
                  x={p.x}
                  y={p.y + 4}
                  textAnchor="middle"
                  className="text-[11px]"
                  fill={TONE[st] ?? "var(--accent)"}
                >
                  {MARK[st]?.[0]}
                </text>
                <text
                  x={right ? p.x + 20 : p.x - 20}
                  y={p.y + 4}
                  textAnchor={right ? "start" : "end"}
                  className={cn(
                    "text-[12px]",
                    sel === t.id ? "fill-[color:var(--text-1)]" : "fill-[color:var(--text-2)]",
                  )}
                >
                  {t.title.length > 28 ? `${t.title.slice(0, 27)}…` : t.title}
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">{children}</div>
      {!plan && provisional.tasks.length > 0 && (
        <div className="absolute bottom-2 w-full text-center text-xs text-text-3">
          Provisional: the plan is still arriving
        </div>
      )}
    </div>
  );
}
