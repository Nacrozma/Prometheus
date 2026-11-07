import { ShieldAlert, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api, AtlasError } from "@/lib/bridge";
import { permissionLabel, relativeTime } from "@/lib/format";
import { useAtlasQuery } from "@/lib/query";
import type { Approval } from "@/lib/schemas";
import { Badge, Button } from "./ui/primitives";

/**
 * Shows exactly what will happen before a gated action runs. The decision is bound in the core
 * to this action's tool and arguments; if either changes, a new approval is required.
 */
export function ApprovalCard({ approval, compact = false }: { approval: Approval; compact?: boolean }) {
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const tools = useAtlasQuery("tools", api.tools, ["registry"]);
  const task = useAtlasQuery(`task:${approval.task_id}`, () => api.taskDetail(approval.task_id), []);
  const tool = tools.data?.find((t) => t.id === approval.tool_id);
  const decide = async (approve: boolean) => {
    setBusy(approve ? "approve" : "reject");
    try {
      await api.decideApproval(approval.id, approve);
      toast(approve ? "Approved — running now" : "Declined — nothing was changed");
    } catch (e) {
      toast.error(e instanceof AtlasError ? e.message : "Could not record the decision");
    } finally {
      setBusy(null);
    }
  };
  const { preview } = approval;
  return (
    <section
      aria-label={`Approval needed: ${preview.action}`}
      className="anim-rise overflow-hidden rounded-lg border border-[color:var(--warn)]/35 bg-bg-2 shadow-2"
    >
      <div className="flex items-center gap-2 border-b border-line-1 bg-warn-soft px-4 py-2.5">
        <ShieldAlert className="size-4 text-warn" aria-hidden />
        <p className="text-sm font-semibold text-text-1">Approval needed</p>
        {/* Solid backgrounds keep these readable on the tinted header (WCAG AA). */}
        {tool && <Badge tone={tool.permission === "consequential" ? "err" : "warn"} solid>{permissionLabel[tool.permission]}</Badge>}
        {tool?.network && <Badge tone="info" solid>Sends data off this computer</Badge>}
        <span className="ml-auto text-xs text-text-3">{relativeTime(approval.created_at)}</span>
      </div>
      <dl className="grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-2 px-4 py-3 text-sm">
        <dt className="text-text-3">Action</dt>
        <dd className="font-medium text-text-1">{preview.action}</dd>
        <dt className="text-text-3">Target</dt>
        <dd className="break-all font-mono text-[0.8125rem] text-text-1">{preview.target}</dd>
        {!compact && task.data && (
          <>
            <dt className="text-text-3">Requested by</dt>
            <dd className="text-text-2">Task: “{task.data.task.request.slice(0, 140)}”</dd>
          </>
        )}
        {preview.consequences && (
          <>
            <dt className="text-text-3">What happens</dt>
            <dd className="text-text-2">{preview.consequences}</dd>
          </>
        )}
        <dt className="text-text-3">Tool</dt>
        <dd className="text-text-2">
          {tool?.name ?? approval.tool_id} <span className="font-mono text-xs text-text-3">({approval.tool_id})</span>
        </dd>
      </dl>
      {preview.details && (
        <div className="px-4 pb-3">
          <p className="mb-1 text-xs text-text-3">Content</p>
          <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-md border border-line-1 bg-[color:var(--code-bg)] p-3 font-mono text-xs text-text-1">
            {preview.details}
          </pre>
        </div>
      )}
      <div className="flex items-center justify-end gap-2 border-t border-line-1 px-4 py-2.5">
        <p className="mr-auto text-xs text-text-3">Approving runs this exact action once.</p>
        <Button variant="secondary" icon={<ShieldX className="size-4" aria-hidden />} loading={busy === "reject"} disabled={busy !== null} onClick={() => decide(false)}>
          Decline
        </Button>
        <Button variant="primary" icon={<ShieldCheck className="size-4" aria-hidden />} loading={busy === "approve"} disabled={busy !== null} onClick={() => decide(true)}>
          Approve
        </Button>
      </div>
    </section>
  );
}
