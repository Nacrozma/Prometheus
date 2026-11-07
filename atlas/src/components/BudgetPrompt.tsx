import { Wallet } from "lucide-react";
import { Button } from "@/components/ui/primitives";
import { useTurns } from "@/state/turns";
import { useUi } from "@/state/ui";

/** Shown when a message was held back because it would exceed a budget set to "ask first". */
export function BudgetPrompt({ conversationId }: { conversationId: string }) {
  const held = useTurns((s) => s.byConversation[conversationId]?.budgetPrompt);
  const confirm = useTurns((s) => s.confirmBudget);
  const dismiss = useTurns((s) => s.dismissBudget);
  const openSettings = useUi((s) => s.openSettings);
  if (!held) return null;
  return (
    <div role="alertdialog" aria-label="Budget check" className="mx-auto mb-4 flex w-full max-w-3xl flex-col gap-2 px-6">
      <div className="rounded-lg border border-[color:var(--warn)]/40 bg-warn-soft px-4 py-3">
        <p className="flex items-center gap-2 text-sm font-medium text-text-1">
          <Wallet className="size-4 text-warn" aria-hidden /> Budget check — not sent yet
        </p>
        <p className="mt-1 text-sm text-text-2">{held.message}</p>
        <p className="mt-1 text-xs text-text-3">Costs are estimates. Sending anyway applies to this one message only.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="primary" onClick={() => void confirm(conversationId)}>Send anyway</Button>
          <Button size="sm" variant="secondary" onClick={() => dismiss(conversationId)}>Don't send</Button>
          <Button size="sm" variant="ghost" onClick={() => openSettings("usage")}>Budget settings</Button>
        </div>
      </div>
    </div>
  );
}
