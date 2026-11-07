import { create } from "zustand";
import { api, AtlasError } from "@/lib/bridge";
import type { Approval, StartedEvent, TaskStatus, TurnEvent } from "@/lib/schemas";

export interface ToolActivity {
  key: string;
  toolId: string;
  stepId?: string;
  status: "preparing" | "pending" | "awaiting_approval" | "running" | "succeeded" | "failed" | "denied" | "rejected" | "expired" | "cancelled";
  approval?: Approval;
}

export interface TurnState {
  running: boolean;
  started?: StartedEvent;
  text: string;
  reasoning: string;
  tools: ToolActivity[];
  notices: { level: string; text: string }[];
  taskId?: string;
  taskStatus?: TaskStatus;
  outcome?: string;
  error?: string;
  /** Bumped whenever persisted messages changed so the thread reloads. */
  revision: number;
  /** A message held back because it would exceed a budget; the owner may send it once anyway. */
  budgetPrompt?: { text: string; message: string; opts?: SendOpts };
}

type SendOpts = { providerId?: string | null; model?: string | null };

export const empty = (): TurnState => ({ running: false, text: "", reasoning: "", tools: [], notices: [], revision: 0 });

interface TurnsStore {
  byConversation: Record<string, TurnState>;
  get: (conversationId: string) => TurnState;
  send: (conversationId: string, text: string, opts?: SendOpts & { budgetOverride?: boolean }) => Promise<void>;
  confirmBudget: (conversationId: string) => Promise<void>;
  dismissBudget: (conversationId: string) => void;
  cancel: (conversationId: string) => Promise<void>;
  anyRunning: () => boolean;
}

export function reduce(s: TurnState, e: TurnEvent): TurnState {
  switch (e.type) {
    case "started":
      return { ...s, started: e };
    case "text_delta":
      return { ...s, text: s.text + e.text };
    case "reasoning_delta":
      return { ...s, reasoning: s.reasoning + e.text };
    case "step_reset":
      return { ...s, text: "", reasoning: "" };
    case "tool_call_started":
      return { ...s, tools: [...s.tools, { key: e.call_id || `${e.name}-${s.tools.length}`, toolId: e.name.replace("_", "."), status: "preparing" }] };
    case "tool": {
      const ev = e.event;
      if (ev.type === "step_started") {
        // Replace the first "preparing" entry (calls run in order), keeping position.
        const idx = s.tools.findIndex((t) => t.status === "preparing");
        const next: ToolActivity = { key: ev.step_id, stepId: ev.step_id, toolId: ev.tool_id, status: "pending" };
        if (idx >= 0) {
          const copy = [...s.tools];
          copy[idx] = next;
          return { ...s, tools: copy, taskId: ev.task_id };
        }
        return { ...s, tools: [...s.tools, next], taskId: ev.task_id };
      }
      if (ev.type === "approval_required") {
        return {
          ...s,
          tools: s.tools.map((t) => (t.stepId === ev.approval.step_id ? { ...t, status: "awaiting_approval", approval: ev.approval } : t)),
        };
      }
      return {
        ...s,
        tools: s.tools.map((t) => (t.stepId === ev.step_id ? { ...t, status: ev.status as ToolActivity["status"], approval: undefined } : t)),
      };
    }
    case "assistant_message":
    case "tool_results":
      // Persisted: the thread reloads from storage; the live buffer resets for the next step.
      return { ...s, text: "", reasoning: "", revision: s.revision + 1, tools: e.type === "tool_results" ? [] : s.tools };
    case "notice":
      return { ...s, notices: [...s.notices, { level: e.level, text: e.text }] };
    case "task_updated":
      return { ...s, taskId: e.task_id, taskStatus: e.status };
    case "finished":
      return { ...s, running: false, outcome: e.outcome, error: e.error ?? undefined, revision: s.revision + 1, text: "", reasoning: "", tools: [] };
  }
}

export const useTurns = create<TurnsStore>((set, get) => ({
  byConversation: {},
  get: (id) => get().byConversation[id] ?? empty(),
  anyRunning: () => Object.values(get().byConversation).some((t) => t.running),
  send: async (conversationId, text, opts) => {
    const patch = (fn: (s: TurnState) => TurnState) =>
      set((st) => ({ byConversation: { ...st.byConversation, [conversationId]: fn(st.byConversation[conversationId] ?? empty()) } }));
    patch((s) => ({ ...empty(), revision: s.revision + 1, running: true }));
    try {
      await api.send(
        { conversationId, text, providerId: opts?.providerId, model: opts?.model, budgetOverride: opts?.budgetOverride },
        (e) => patch((s) => reduce(s, e)),
      );
    } catch (e) {
      if (e instanceof AtlasError && e.code === "budget_confirmation_required") {
        const held = { text, message: e.message, opts: { providerId: opts?.providerId, model: opts?.model } };
        patch((s) => ({ ...s, running: false, outcome: undefined, error: undefined, budgetPrompt: held }));
        return;
      }
      const msg = e instanceof AtlasError ? e.message : String(e);
      patch((s) => ({ ...s, running: false, error: msg, outcome: "failed", revision: s.revision + 1 }));
    }
  },
  confirmBudget: async (conversationId) => {
    const held = get().byConversation[conversationId]?.budgetPrompt;
    if (!held) return;
    await get().send(conversationId, held.text, { ...held.opts, budgetOverride: true });
  },
  dismissBudget: (conversationId) =>
    set((st) => ({ byConversation: { ...st.byConversation, [conversationId]: { ...(st.byConversation[conversationId] ?? empty()), budgetPrompt: undefined } } })),
  cancel: async (conversationId) => {
    await api.cancel(conversationId);
  },
}));
