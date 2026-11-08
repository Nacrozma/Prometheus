import { PrometheusAvatar } from "@/features/siblings/avatar/PrometheusAvatar";
import { AlertTriangle, Brain, ChevronRight, CircleCheck, CircleSlash, Info, RefreshCw, RotateCcw, Wrench, XCircle } from "lucide-react";
import { useState } from "react";
import { CopyButton, Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/primitives";
import { cn, relativeTime } from "@/lib/format";
import type { Message, Part } from "@/lib/schemas";
import { canRegenerate, lastQuestionUnanswered, modKey } from "./conversation";

type ToolCall = Extract<Part, { type: "tool_call" }>;
type ToolResult = Extract<Part, { type: "tool_result" }>;

function ToolRun({ call, result, live }: { call: ToolCall; result?: ToolResult; live?: boolean }) {
  const [open, setOpen] = useState(false);
  const toolId = call.name.replace("_", ".");
  const state = !result ? "pending" : result.is_error ? (/declined/.test(result.content) ? "declined" : "error") : "ok";
  const Icon = state === "ok" ? CircleCheck : state === "declined" ? CircleSlash : state === "error" ? XCircle : Wrench;
  const label = state === "ok" ? "Completed" : state === "declined" ? "Declined" : state === "error" ? "Did not complete" : live ? "In progress" : "No result";
  return (
    <div className="rounded-md border border-line-1 bg-bg-2/70">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs text-text-2 hover:bg-bg-3/60"
      >
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} aria-hidden />
        <Icon className={cn("size-3.5", state === "ok" ? "text-ok" : state === "pending" ? "text-text-3" : state === "declined" ? "text-warn" : "text-err")} aria-hidden />
        <span className="font-mono text-text-1">{toolId}</span>
        <span className="text-text-3">· {label}</span>
      </button>
      {toolId === "sibling.consult" && result && !result.is_error && <SiblingAnswer content={result.content} />}
      {open && (
        <div className="space-y-2 border-t border-line-1 px-3 py-2.5">
          <div>
            <p className="mb-1 text-[0.6875rem] uppercase tracking-wider text-text-3">Arguments</p>
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-sm bg-[color:var(--code-bg)] p-2 font-mono text-[0.75rem] text-text-2">
              {JSON.stringify(call.input, null, 2)}
            </pre>
          </div>
          {result && (
            <div>
              <p className="mb-1 text-[0.6875rem] uppercase tracking-wider text-text-3">Result {result.is_error && "(error)"}</p>
              <pre className={cn("max-h-64 overflow-auto whitespace-pre-wrap rounded-sm bg-[color:var(--code-bg)] p-2 font-mono text-[0.75rem]", result.is_error ? "text-err" : "text-text-2")}>
                {prettyMaybeJson(result.content)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Prometheus's answer to a consultation, with his identity. The text is untrusted input. */
function SiblingAnswer({ content }: { content: string }) {
  const answer = (() => {
    try {
      return String((JSON.parse(content) as { answer?: unknown }).answer ?? "");
    } catch {
      return "";
    }
  })();
  if (!answer) return null;
  return (
    <div className="flex gap-2.5 border-t border-[#f5a524]/20 bg-[#f5a524]/[0.04] px-3 py-2.5">
      <PrometheusAvatar state="idle" size={26} birth={false} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-[#f5b14c]">Prometheus</p>
        <div className="mt-0.5 text-sm"><Markdown text={answer} /></div>
        <p className="mt-1 text-[0.68rem] text-text-3">From a separate assistant — untrusted input.</p>
      </div>
    </div>
  );
}

function prettyMaybeJson(s: string): string {
  try {
    return JSON.stringify(JSON.parse(s), null, 2);
  } catch {
    return s;
  }
}

function Notice({ m }: { m: Message }) {
  const Icon = m.status === "error" ? AlertTriangle : m.status === "warning" ? AlertTriangle : Info;
  return (
    <div
      role={m.status === "error" ? "alert" : undefined}
      className={cn(
        "mx-auto flex max-w-2xl items-start gap-2 rounded-md border px-3 py-2 text-xs",
        m.status === "error" ? "border-[color:var(--err)]/25 bg-err-soft text-text-1" : m.status === "warning" ? "border-[color:var(--warn)]/25 bg-warn-soft text-text-1" : "border-line-1 bg-bg-2 text-text-2",
      )}
    >
      <Icon className={cn("mt-0.5 size-3.5 shrink-0", m.status === "error" ? "text-err" : m.status === "warning" ? "text-warn" : "text-text-3")} aria-hidden />
      <span>{m.content}</span>
    </div>
  );
}

export function Thread({
  messages,
  onAskAgain,
  onRegenerate,
  canAskAgain,
  running = false,
}: {
  messages: Message[];
  onAskAgain: (text: string) => void;
  onRegenerate?: () => void;
  canAskAgain: boolean;
  running?: boolean;
}) {
  // Pair each assistant message's tool calls with the results in the tool message that follows it
  // (call ids are only unique within one exchange).
  const resultsFor = new Map<string, Map<string, ToolResult>>();
  messages.forEach((m, i) => {
    if (m.role !== "assistant") return;
    const next = messages.slice(i + 1).find((x) => x.role !== "notice");
    const map = new Map<string, ToolResult>();
    if (next?.role === "tool") for (const p of next.parts ?? []) if (p.type === "tool_result") map.set(p.call_id, p);
    resultsFor.set(m.id, map);
  });
  const lastUser = [...messages].reverse().find((m) => m.role === "user");
  const regen = canAskAgain && onRegenerate && canRegenerate(messages);
  const actionCls = "inline-flex items-center gap-1 rounded-xs px-1.5 py-0.5 hover:bg-bg-4 hover:text-text-1";

  return (
    <ol className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-6 py-6" aria-label="Conversation">
      {messages.map((m) => {
        if (m.role === "tool") return null;
        if (m.role === "notice")
          return (
            <li key={m.id}>
              <Notice m={m} />
            </li>
          );
        if (m.role === "user")
          return (
            <li key={m.id} className="flex justify-end">
              <div className="max-w-[85%] rounded-lg rounded-br-sm border border-line-2 bg-bg-3 px-4 py-2.5 text-sm text-text-1">
                <p className="whitespace-pre-wrap break-words">{m.content}</p>
              </div>
            </li>
          );
        const calls = (m.parts ?? []).filter((p): p is ToolCall => p.type === "tool_call");
        const hasText = m.content.trim().length > 0;
        return (
          <li key={m.id} className="group flex flex-col gap-2">
            {hasText && (
              <div className={cn("text-sm", m.status === "refused" && "opacity-70")}>
                <Markdown text={m.content} />
              </div>
            )}
            {calls.length > 0 && (
              <div className="flex flex-col gap-1.5" aria-label="Tool activity">
                {calls.map((c) => (
                  <ToolRun key={c.id} call={c} result={resultsFor.get(m.id)?.get(c.id)} live={running} />
                ))}
              </div>
            )}
            {hasText && (
              <div className="flex items-center gap-2 text-[0.6875rem] text-text-3 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                <span>{m.model ?? "model"}</span>
                <span>·</span>
                <span>{relativeTime(m.created_at)}</span>
                {m.status === "truncated" && <Badge tone="warn">cut off at length limit</Badge>}
                {m.status === "refused" && <Badge tone="warn">declined by model</Badge>}
                <CopyButton text={m.content} />
                {canAskAgain && lastUser && m === messages.filter((x) => x.role === "assistant").at(-1) &&
                  (regen ? (
                    <button onClick={onRegenerate} className={actionCls} title={`Replace this reply with a new one (${modKey()}+Shift+Enter)`} aria-keyshortcuts="Control+Shift+Enter">
                      <RefreshCw className="size-3.5" aria-hidden /> Regenerate
                    </button>
                  ) : (
                    <button onClick={() => onAskAgain(lastUser.content)} className={actionCls} title="This reply used tools, so it is kept; the question is asked again below">
                      <RotateCcw className="size-3.5" aria-hidden /> Ask again
                    </button>
                  ))}
              </div>
            )}
          </li>
        );
      })}
      {regen && lastQuestionUnanswered(messages) && (
        <li className="flex justify-end">
          <button onClick={onRegenerate} className={cn(actionCls, "text-xs text-text-3")} aria-keyshortcuts="Control+Shift+Enter">
            <RefreshCw className="size-3.5" aria-hidden /> Try again
          </button>
        </li>
      )}
    </ol>
  );
}

export function MemoryChips({ memories }: { memories: { id: string; content: string; reason: string }[] }) {
  const [open, setOpen] = useState(false);
  if (!memories.length) return null;
  return (
    <div className="text-xs">
      <button onClick={() => setOpen((v) => !v)} aria-expanded={open} className="inline-flex items-center gap-1.5 rounded-xs px-1.5 py-0.5 text-text-3 hover:bg-bg-3 hover:text-text-1">
        <Brain className="size-3.5 text-accent" aria-hidden />
        Using {memories.length} {memories.length === 1 ? "memory" : "memories"}
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      {open && (
        <ul className="mt-1.5 space-y-1 rounded-md border border-line-1 bg-bg-2 p-2">
          {memories.map((m) => (
            <li key={m.id} className="flex gap-2">
              <span className="text-text-1">{m.content}</span>
              <span className="ml-auto shrink-0 text-text-3">{m.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
