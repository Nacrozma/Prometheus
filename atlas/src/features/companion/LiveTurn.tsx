import { ChevronRight, CircleCheck, CircleSlash, Cloud, Cpu, Loader2, ShieldAlert, Sparkles, XCircle } from "lucide-react";
import { useState } from "react";
import { ApprovalCard } from "@/components/ApprovalCard";
import { Markdown } from "@/components/Markdown";
import { cn } from "@/lib/format";
import type { ToolActivity, TurnState } from "@/state/turns";
import { MemoryChips } from "./Thread";

const statusText: Record<ToolActivity["status"], string> = {
  preparing: "Preparing",
  pending: "Checking permissions",
  awaiting_approval: "Waiting for your approval",
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
  denied: "Not permitted",
  rejected: "Declined",
  expired: "Approval expired",
  cancelled: "Cancelled",
};

function ActivityRow({ a }: { a: ToolActivity }) {
  const busy = a.status === "preparing" || a.status === "pending" || a.status === "running";
  const Icon = busy ? Loader2 : a.status === "succeeded" ? CircleCheck : a.status === "awaiting_approval" ? ShieldAlert : a.status === "rejected" ? CircleSlash : XCircle;
  return (
    <li className="flex items-center gap-2 text-xs">
      <Icon
        className={cn("size-3.5", busy && "animate-spin text-accent", a.status === "succeeded" && "text-ok", a.status === "awaiting_approval" && "text-warn", ["failed", "denied", "expired", "cancelled"].includes(a.status) && "text-err")}
        aria-hidden
      />
      <span className="font-mono text-text-1">{a.toolId}</span>
      <span className="text-text-3">{statusText[a.status]}</span>
    </li>
  );
}

/** The in-progress part of a turn: route, memories, streaming text, tool activity, approvals. */
export function LiveTurn({ turn }: { turn: TurnState }) {
  const [showReasoning, setShowReasoning] = useState(false);
  if (!turn.running && !turn.notices.length) return null;
  const s = turn.started;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-6 pb-6" aria-live="polite">
      {s && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-text-3">
          <span className="inline-flex items-center gap-1.5" title={s.route_reason}>
            {s.local ? <Cpu className="size-3.5" aria-hidden /> : <Cloud className="size-3.5" aria-hidden />}
            {s.local ? "On this computer" : "Cloud"} · {s.provider_label} · <span className="font-mono">{s.model}</span>
          </span>
          {s.fell_back && <span className="text-warn">fallback provider</span>}
          <MemoryChips memories={s.memories} />
        </div>
      )}
      {turn.reasoning && (
        <div className="rounded-md border border-line-1 bg-bg-2/60">
          <button onClick={() => setShowReasoning((v) => !v)} aria-expanded={showReasoning} className="flex w-full items-center gap-2 px-3 py-1.5 text-xs text-text-3 hover:text-text-1">
            <Sparkles className="size-3.5 text-accent" aria-hidden /> Reasoning summary (from the model)
            <ChevronRight className={cn("ml-auto size-3.5 transition-transform", showReasoning && "rotate-90")} aria-hidden />
          </button>
          {showReasoning && <p className="whitespace-pre-wrap border-t border-line-1 px-3 py-2 text-xs text-text-2">{turn.reasoning}</p>}
        </div>
      )}
      {turn.text && (
        <div className="text-sm">
          <Markdown text={turn.text} />
          <span aria-hidden className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 bg-accent" style={{ animation: "caret 1s steps(1) infinite" }} />
        </div>
      )}
      {turn.tools.length > 0 && (
        <ul className="flex flex-col gap-1.5 rounded-md border border-line-1 bg-bg-2/60 px-3 py-2" aria-label="Tool activity">
          {turn.tools.map((a) => (
            <ActivityRow key={a.key} a={a} />
          ))}
        </ul>
      )}
      {turn.tools.filter((a) => a.approval).map((a) => (
        <ApprovalCard key={a.approval!.id} approval={a.approval!} compact />
      ))}
      {turn.running && !turn.text && !turn.tools.length && (
        <div className="flex items-center gap-2 text-xs text-text-3">
          <span className="flex gap-1" aria-hidden>
            <span className="size-1.5 rounded-full bg-accent anim-pulse" />
            <span className="size-1.5 rounded-full bg-accent anim-pulse [animation-delay:200ms]" />
            <span className="size-1.5 rounded-full bg-accent anim-pulse [animation-delay:400ms]" />
          </span>
          {s ? "Thinking…" : "Preparing request…"}
        </div>
      )}
    </div>
  );
}
