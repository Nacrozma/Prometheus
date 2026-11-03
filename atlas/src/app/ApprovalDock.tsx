import { ApprovalCard } from "@/components/ApprovalCard";
import { api } from "@/lib/bridge";
import { useAtlasQuery } from "@/lib/query";
import { useTurns } from "@/state/turns";
import { useUi } from "@/state/ui";

/** Approvals from any task, always visible. In the conversation that requested one, the card is shown inline instead. */
export function ApprovalDock() {
  const approvals = useAtlasQuery("approvals", api.pendingApprovals, ["approvals"]);
  const route = useUi((s) => s.route);
  const conv = useUi((s) => s.activeConversationId);
  const inlineTask = useTurns((s) => (conv ? s.byConversation[conv]?.taskId : undefined));
  const items = (approvals.data ?? []).filter((a) => !(route === "companion" && a.task_id === inlineTask));
  return (
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-30 flex w-[min(28rem,calc(100vw-6rem))] flex-col gap-3">
      {items.slice(0, 3).map((a) => (
        <div key={a.id} className="pointer-events-auto">
          <ApprovalCard approval={a} />
        </div>
      ))}
      {items.length > 3 && (
        <p className="pointer-events-auto rounded-md border border-line-2 bg-bg-2 px-3 py-2 text-xs text-text-2 shadow-2">
          {items.length - 3} more waiting — open Mission Control to review.
        </p>
      )}
    </div>
  );
}
